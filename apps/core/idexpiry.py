"""Daily check of ID expiry dates: staff IDs (the person and the administrators are told) and members' IDs (a digest
for supervisors, plus a banner on each record)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Notification, Parameter
from .notifications import notify_role, queue


def _already_told(template, obj, days=7):
    since = timezone.now() - timedelta(days=days)
    return Notification.objects.filter(template=template, object_type=obj._meta.label_lower, object_id=str(obj.pk), created_at__gte=since).exists()


def check_id_expiry():
    today = timezone.localdate()
    warn = today + timedelta(days=int(Parameter.get("id-expiry-warning-days")))
    staff = get_user_model().objects.filter(is_active=True, id_expiry__isnull=False, id_expiry__lte=warn).order_by("id_expiry")
    told = 0
    for user in staff:
        state = "expired" if user.id_expiry < today else "expires"
        if _already_told("staff-id-expiry", user):
            continue
        queue(
            "staff-id-expiry",
            "inapp",
            user.get_username(),
            obj=user,
            recipient_user=user,
            link="/accounts/me/",
            id_type=user.get_id_type_display() or "ID",
            state=state,
            date=user.id_expiry.strftime("%d %b %Y"),
        )
        told += 1
    if staff and not Notification.objects.filter(template="staff-ids-digest", created_at__date=today).exists():
        names = ", ".join(f"{u.display_name()} ({u.id_expiry:%d %b %Y})" for u in staff[:15])
        notify_role(
            "ict_admin",
            "staff-ids-digest",
            link="/accounts/staff/?state=id_expired",
            count=len(staff),
            days=Parameter.get("id-expiry-warning-days"),
            names=names,
        )
    from apps.accounts.roles import users_with_role
    from apps.accounts.scoping import scope_by_centre
    from apps.members.models import Member

    expired = Member.objects.filter(id_expiry__lt=today).count()
    soon = Member.objects.filter(id_expiry__gte=today, id_expiry__lte=warn).count()
    for sup in users_with_role("supervisor"):  # each supervisor hears about their own centre's members
        if Notification.objects.filter(template="member-ids-digest", recipient_user=sup, created_at__date=today).exists():
            continue
        mine = scope_by_centre(Member.objects.all(), sup, field="collection_centre")
        e, s = mine.filter(id_expiry__lt=today).count(), mine.filter(id_expiry__gte=today, id_expiry__lte=warn).count()
        if e or s:
            queue("member-ids-digest", "inapp", sup.get_username(), recipient_user=sup, link="/members/expired-ids/", expired=e, soon=s)
    return {"staff_told": told, "staff_due": len(staff), "members_expired": expired, "members_expiring": soon}
