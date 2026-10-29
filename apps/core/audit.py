"""Audit and request context helpers."""

import contextvars

_request = contextvars.ContextVar("request", default=None)


def set_request(request):
    """Bind the current request so audit rows can carry actor, IP and request id."""
    return _request.set(request)


def reset_request(token):
    """Unbind the request."""
    _request.reset(token)


def current_user():
    """The signed-in user of the current request, or None (management commands, workers)."""
    req = _request.get()
    user = getattr(req, "user", None)
    return user if user is not None and user.is_authenticated else None


def record(action, obj=None, summary="", actor=None, **data):
    """Write one AuditEvent for a business event."""
    from .models import AuditEvent

    req = _request.get()
    return AuditEvent.objects.create(
        actor=actor or current_user(),
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        summary=summary[:500],
        data=data,
        ip_address=(req.META.get("REMOTE_ADDR") if req else None),
        request_id=getattr(req, "request_id", "") if req else "",
    )
