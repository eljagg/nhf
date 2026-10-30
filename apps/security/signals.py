"""Session tracking, failed sign-in alerts and password history."""

import hashlib

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.core.models import Parameter
from apps.core.net import client_ip  # noqa: E402,F401  (re-exported for existing imports)

from .models import PasswordHistory, UserSession


def session_ref(key):
    """Short, non-reversible reference to a session key for logs."""
    return hashlib.sha256((key or "").encode()).hexdigest()[:12] if key else ""


@receiver(user_logged_in)
def track_login(sender, request, user, **kwargs):
    if request is None:
        return
    if not request.session.session_key:
        request.session.save()
    UserSession.objects.update_or_create(
        session_key=request.session.session_key,
        defaults={"user": user, "ip_address": client_ip(request), "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200], "ended_at": None},
    )
    cache.delete(f"failed-login:{user.get_username().lower()}")


@receiver(user_logged_out)
def track_logout(sender, request, user, **kwargs):
    if request is not None and request.session.session_key:
        UserSession.objects.filter(session_key=request.session.session_key, ended_at__isnull=True).update(ended_at=timezone.now(), end_reason="signed out")


@receiver(user_login_failed)
def failed_login(sender, credentials, request=None, **kwargs):
    username = str(credentials.get("username", ""))[:150]
    if not username:
        return
    key = f"failed-login:{username.lower()}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 15 * 60)
        count = 1
    ip = client_ip(request)
    if ip:
        ip_key = f"failed-login-ip:{ip}"
        try:
            ip_count = cache.incr(ip_key)
        except ValueError:
            cache.set(ip_key, 1, 15 * 60)
            ip_count = 1
        ip_limit = int(Parameter.get("alert-failed-logins-address"))
        if ip_count >= ip_limit:
            from .services import raise_alert

            raise_alert(
                "failed_logins",
                f"{ip_count} failed sign-ins from address {ip} within 15 minutes, across usernames (possible password spraying).",
                severity="high",
                subject=ip,
                dedupe_minutes=15,
                ip=ip,
            )
    limit = int(Parameter.get("alert-failed-logins"))
    if count >= limit:
        from .services import raise_alert

        user = get_user_model().objects.filter(username__iexact=username).first()
        raise_alert(
            "failed_logins",
            f"{count} failed sign-ins for '{username}' within 15 minutes (from {client_ip(request) or 'unknown address'}).",
            severity="high" if user else "medium",
            user=user,
            subject=username.lower(),
            dedupe_minutes=15,
            ip=client_ip(request),
        )


@receiver(post_save, sender=get_user_model())
def record_password(sender, instance, **kwargs):
    if not getattr(instance, "_password_changed_now", False) or not instance.password:
        return
    instance._password_changed_now = False
    PasswordHistory.objects.create(user=instance, password=instance.password)
    keep = max(int(Parameter.get("password-history-count")), 1)
    old = PasswordHistory.objects.filter(user=instance).order_by("-created_at").values_list("pk", flat=True)[keep:]
    PasswordHistory.objects.filter(pk__in=list(old)).delete()
