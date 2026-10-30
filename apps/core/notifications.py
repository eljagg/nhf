"""Notification templates and queueing (NT10001–NT10004, OR10003, TV10006)."""

from django.db import transaction

from .models import Notification

TEMPLATES = {
    "trn-invalid": (
        "TRN could not be validated",
        "NHF: We could not validate TRN {trn} for your NHF Card application {tracking}. Please visit any NHFCard centre with your TRN card.",
    ),
    "application-received-online": (
        "Online application received",
        "NHF: Your doctor has submitted your NHF Card application {tracking}. We will text you when your card is ready to collect.",
    ),
    "online-application-cc": (
        "New online application {tracking}",
        "A doctor-portal application {tracking} is in the online queue ({kind}). TRN check: {trn_status}.",
    ),
    "application-approved": (
        "Application approved",
        "NHF: Application {tracking} is approved. Member no. {member_number}. Your card will be ready at {centre}.",
    ),
    "application-rejected": ("Application not approved", "NHF: Application {tracking} could not be approved: {reason}. Call 1-888-NHF-LINK for help."),
    "security-alert": ("Security alert", "{message}"),
    "dsr-received": ("Data-subject request {reference}", "{kind} request from {name} received; answer due {due}."),
    "breach-logged": ("Personal-data breach {reference}", "Breach logged: {title}. Report to the Information Commissioner by {deadline}."),
    "srn-approval-needed": ("SRN approval needed", "{requester} asked for a Special Registration Number for {name} (DOB {dob}). Reason: {reason}."),
    "doctor-confirmation-needed": (
        "Doctor confirmation needed",
        "MCJ number {mcj} on application {tracking} is not in the NHF Doctors register. Confirm with the Medical Council.",
    ),
}


def queue(template, channel, to, *, obj=None, recipient_user=None, link="", **context):
    """Queue a notification; it is dispatched after the surrounding transaction commits."""
    subject, body = TEMPLATES[template]
    note = Notification.objects.create(
        channel=channel,
        to=to or "",
        recipient_user=recipient_user,
        template=template,
        subject=subject.format(**context),
        body=body.format(**context),
        link=link,
        status="queued",
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
    )
    from .tasks import send_notification

    transaction.on_commit(lambda: send_notification.delay(note.pk))
    return note


def notify_role(role, template, *, obj=None, link="", **context):
    """In-app notification to every active user holding a role (incl. temporary grants)."""
    from apps.accounts.roles import users_with_role

    return [queue(template, "inapp", u.get_username(), obj=obj, recipient_user=u, link=link, **context) for u in users_with_role(role)]
