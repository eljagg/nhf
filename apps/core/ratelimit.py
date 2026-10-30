"""Simple per-user rate limits for lookups that reveal personal data (TRN screening, council register checks)."""

from django.core.cache import cache


def hit(key, limit, window_seconds):
    """Count one use; True while within the limit."""
    full = f"rl:{key}"
    if cache.add(full, 1, window_seconds):
        return True
    try:
        count = cache.incr(full)
    except ValueError:
        cache.set(full, 1, window_seconds)
        count = 1
    return count <= limit


def enforce(request, name, parameter, what):
    """Apply a per-user hourly limit from a parameter; on the first refusal in an hour raise a security alert. True = allowed."""
    from apps.core.models import Parameter
    from apps.security.services import raise_alert

    limit = int(Parameter.get(parameter))
    if hit(f"{name}:{request.user.pk}", limit, 3600):
        return True
    raise_alert(
        "rate_limit",
        f"{request.user.username} went over the limit of {limit} {what} in an hour; further lookups refused.",
        severity="high",
        user=request.user,
        dedupe_minutes=60,
    )
    return False
