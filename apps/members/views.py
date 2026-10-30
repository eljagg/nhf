"""Counter screens: start, application (counter page), member profile, applications list, tracking search."""

import re
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.roles import MEMBER_ROLES, PROCESS_ROLES, can_view_conditions, has_role, role_required
from apps.core import audit
from apps.core.models import Centre, Parameter
from apps.identity import services as identity
from apps.intake import services as intake
from apps.interactions.services import log
from apps.rules.engine import active_conditions
from apps.rules.models import Programme, RejectionReason

from . import services
from .forms import ApplicationForm, ContactForm, IdDocumentForm, InteractionForm, RecheckForm, RejectForm, SrnRequestForm, StartForm
from .identifiers import normalise_nis
from .models import SEVERITIES, Application, Member


def _work_app(request, tracking):
    """The application, if this user may change it (own centre, island-wide role, or assigned to them)."""
    from django.core.exceptions import PermissionDenied

    from apps.accounts.scoping import can_work_application

    app = _app(tracking)
    if not can_work_application(request.user, app):
        raise PermissionDenied
    return app


def _app(tracking):
    return get_object_or_404(
        Application.objects.select_related(
            "centre", "member", "doctor", "trn_validation", "srn_issue", "collection_centre", "worked_by", "assigned_to", "rejection_reason"
        ),
        tracking_number=tracking,
    )


@role_required(*PROCESS_ROLES)
def start(request):
    """New application: context, then TRN and the name/DOB as written on the form."""
    form = StartForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            app = services.start_application(
                user=request.user,
                centre=d["centre"],
                channel=d["channel"],
                received_at=d["received_at"],
                trn=d["trn"],
                form_first_name=d["form_first_name"],
                form_last_name=d["form_last_name"],
                form_dob=d["form_dob"],
            )
        except services.ProcessingError as exc:
            form.add_error("trn", str(exc))
        else:
            return redirect("members:application", tracking=app.tracking_number)
    return render(request, "members/start.html", {"form": form, "srn_form": SrnRequestForm(), "page_title": "New application"})


@require_POST
@role_required(*PROCESS_ROLES)
def start_without_trn(request):
    """No TRN: open an application and request a Special Registration Number (SR10001)."""
    form = SrnRequestForm(request.POST)
    centre = request.user.centre or Centre.objects.first()
    if not form.is_valid():
        messages.error(request, "Complete the applicant's name, date of birth, gender and the reason to request an SRN.")
        return redirect("members:start")
    d = form.cleaned_data
    app = services.start_application(
        user=request.user,
        centre=centre,
        channel="walk_in",
        received_at=timezone.now(),
        form_first_name=d["first_name"],
        form_last_name=d["last_name"],
        form_dob=d["dob"],
    )
    issue = identity.request_srn(
        user=request.user,
        first_name=d["first_name"],
        middle_name=d["middle_name"],
        last_name=d["last_name"],
        dob=d["dob"],
        gender=d["gender"],
        reason=d["reason"],
    )
    services.link_srn_request(app, issue)
    if not issue.duplicate_check.get("clear"):
        messages.warning(request, "Possible duplicate found — the approver will see the matches before issuing an SRN.")
    messages.success(request, "SRN requested. The application waits for management approval.")
    return redirect("members:application", tracking=app.tracking_number)


@require_POST
@role_required(*PROCESS_ROLES)
def start_change(request, member_number):
    """MR10005/MR10007: a change form is an application against an existing member."""
    member = get_object_or_404(Member, member_number=member_number)
    open_change = member.applications.filter(kind="change", status__in=Application.OPEN_STATUSES).first()
    if open_change:
        messages.warning(request, f"Change form {open_change.tracking_number} is already open for this member.")
        return redirect("members:application", tracking=open_change.tracking_number)
    app = services.start_application(
        user=request.user,
        centre=request.user.centre or member.collection_centre,
        channel=request.POST.get("channel", "walk_in"),
        received_at=timezone.now(),
        kind="change",
        member=member,
    )
    return redirect("members:application", tracking=app.tracking_number)


def _condition_rows(app, data=None):
    chosen = {ac.condition_id: ac.severity for ac in app.conditions.all()}
    rows = []
    for cond in active_conditions():
        key = f"cond_{cond.pk}"
        if data is not None:
            checked = key in data
            severity = data.get(f"sev_{cond.pk}", "moderate")
        else:
            checked = cond.pk in chosen
            severity = chosen.get(cond.pk, "moderate")
        rows.append({"c": cond, "checked": checked, "severity": severity})
    return rows


def _context(request, app, form=None, condition_rows=None):
    from apps.accounts.scoping import can_work_application

    outcome = services.evaluate(app)
    validation = app.trn_validation
    return {
        "app": app,
        "form": form or ApplicationForm(instance=app),
        "outcome": outcome,
        "validation": validation,
        "identity_changes": services.identity_changes(app),
        "condition_rows": condition_rows or _condition_rows(app),
        "severities": [sv for sv in SEVERITIES if sv[0] != "moderate" or app.conditions.filter(severity="moderate").exists()],  # paper form: mild / severe
        "can_conditions": can_view_conditions(request.user),
        "can_process": has_role(request.user, *PROCESS_ROLES) and app.is_open and can_work_application(request.user, app),
        "other_centre": not can_work_application(request.user, app),
        "reject_form": RejectForm(auto_id="rej_%s"),
        "recheck_form": RecheckForm(initial={"form_first_name": app.form_first_name, "form_last_name": app.form_last_name, "form_dob": app.form_dob}),
        "srn_form": SrnRequestForm(auto_id="srn_%s", initial={"first_name": app.form_first_name, "last_name": app.form_last_name, "dob": app.form_dob}),
        "interactions": app.interactions.select_related("actor").prefetch_related("notes")[:40],
        "privacy_notice": Parameter.get("privacy-notice-text"),
        "locked_by": app.worked_by_other(request.user),
        "page_title": app.tracking_number,
    }


@role_required(*MEMBER_ROLES)
def application(request, tracking):
    """The counter page: identity, details, conditions, rules, decision, log."""
    from apps.accounts.scoping import can_work_application

    app = _app(tracking)
    own = can_work_application(request.user, app)
    if request.method == "GET" and app.is_open and has_role(request.user, *PROCESS_ROLES) and own:
        intake.take_work_lock(app, request.user)
        app.refresh_from_db(fields=["worked_by", "worked_heartbeat"])
    if request.method == "POST":
        if not (has_role(request.user, *PROCESS_ROLES) and app.is_open and own):
            return redirect("members:application", tracking=tracking)
        other = app.worked_by_other(request.user)
        if other:
            messages.error(request, f"{other.display_name()} is working on this record. Your changes were not saved.")
            return redirect("members:application", tracking=tracking)
        form = ApplicationForm(request.POST, instance=app)
        rows = _condition_rows(app, request.POST) if can_view_conditions(request.user) else None
        if form.is_valid():
            app = form.save(commit=False)
            if app.consent_given and not app.consent_at:
                app.consent_at = timezone.now()
                app.consent_version = str(Parameter.get("privacy-notice-version"))
            elif not app.consent_given:
                app.consent_at, app.consent_version = None, ""
            signature_data = request.POST.get("signature_data", "")
            if signature_data and "signature_data" in request.POST:
                from apps.core.images import ImageRejected, store_signature

                try:
                    app.signature = store_signature(signature_data, user=request.user)
                except (ImageRejected, ValueError) as exc:
                    messages.error(request, f"Signature not saved: {exc}")
                else:
                    app.declaration_signed = True
                    app.declaration_date = app.declaration_date or timezone.localdate()
                    audit.record("application.signature_captured", app, f"{app.tracking_number} signature captured on the signature pad")
            services.resolve_doctor(app, user=request.user)
            app.save()
            if rows is not None:
                services.set_conditions(app, [(r["c"], r["severity"]) for r in rows if r["checked"]])
            services.refresh_status(app)
            audit.record("application.saved", app, f"{app.tracking_number} details saved", fields=list(form.changed_data))
            app = _app(tracking)
            messages.success(request, "Saved. " + ("Ready to approve." if app.status == "ready" else "See the checks below."))
            return redirect("members:application", tracking=tracking)
        problems = ", ".join(str(form.fields[name].label or name).lower() for name in form.errors if name in form.fields)
        messages.error(
            request,
            "Not saved — check " + (problems or "the form") + "." + (" Ask the applicant to sign again." if request.POST.get("signature_data") else ""),
        )
        return render(request, "members/application.html", _context(request, app, form=form, condition_rows=rows))
    return render(request, "members/application.html", _context(request, app))


@role_required(*MEMBER_ROLES)
def identity_panel(request, tracking):
    """HTMX: TRN result panel; polls while the worker is calling the service."""
    app = _app(tracking)
    if request.GET.get("poll") and app.trn_validation and app.trn_validation.is_done:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"  # result is in: reload so the locked fields and rule checks update together
        return response
    return render(
        request,
        "members/_identity.html",
        {
            "identity_changes": services.identity_changes(app),
            "app": app,
            "validation": app.trn_validation,
            "can_process": has_role(request.user, *PROCESS_ROLES) and app.is_open,
            "recheck_form": RecheckForm(initial={"form_first_name": app.form_first_name, "form_last_name": app.form_last_name, "form_dob": app.form_dob}),
        },
    )


@role_required(*PROCESS_ROLES)
def pickup_slip(request, tracking):
    """The tear-off stub of the paper form, printed for the applicant: tracking number, collection centre, what to bring."""
    app = _app(tracking)
    audit.record("application.slip_printed", app, f"{app.tracking_number} pick-up slip printed")
    centre = app.collection_centre or app.centre
    return render(
        request,
        "members/pickup_slip.html",
        {
            "app": app,
            "centre": centre,
            "clerk": app.entered_by or request.user,
            "trn_masked": f"•••-•••-{app.trn[-3:]}" if app.trn else "",
            "toll_free": Parameter.get("toll-free-numbers"),
            "record_update_hours": Parameter.get("record-update-hours"),
            "printed_at": timezone.localtime(),
        },
    )


@require_POST
@role_required(*PROCESS_ROLES)
def heartbeat(request, tracking):
    """OR10010: keep the 'being worked by' indicator alive while the page is open."""
    app = _work_app(request, tracking)
    if app.is_open:
        intake.take_work_lock(app, request.user)
    return HttpResponse(status=204)


@require_POST
@role_required(*PROCESS_ROLES)
def recheck(request, tracking):
    """Correct the keyed form details and send the TRN again."""
    app = _work_app(request, tracking)
    form = RecheckForm(request.POST)
    if form.is_valid() and app.is_open:
        app.form_first_name, app.form_last_name, app.form_dob = (
            form.cleaned_data["form_first_name"],
            form.cleaned_data["form_last_name"],
            form.cleaned_data["form_dob"],
        )
        app.save(update_fields=["form_first_name", "form_last_name", "form_dob", "updated_at"])
        services.accept_corrected_form(app, user=request.user)
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def revalidate(request, tracking):
    """Fresh TRN call (e.g. after a service outage, or the identity refresh on a change form)."""
    app = _work_app(request, tracking)
    if app.is_open and app.trn and not app.is_srn:
        services.begin_identity_check(app, user=request.user)
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def terminate(request, tracking):
    """TV10004/TV10005: terminate on identity mismatch."""
    app = _work_app(request, tracking)
    try:
        services.terminate_for_mismatch(app, user=request.user, text=request.POST.get("text", ""))
        messages.success(request, f"{app.tracking_number} terminated: identity does not match the Tax Office record.")
    except services.ProcessingError as exc:
        messages.error(request, str(exc))
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def notify_invalid(request, tracking):
    """TV10006: SMS the applicant about an invalid TRN."""
    app = _work_app(request, tracking)
    try:
        services.notify_invalid_trn(app, user=request.user)
        messages.success(request, f"SMS queued to {app.phone_mobile}.")
    except services.ProcessingError as exc:
        messages.error(request, str(exc))
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def reject_invalid_trn(request, tracking):
    """Reject an application whose TRN the Tax Office does not know."""
    app = _work_app(request, tracking)
    try:
        services.reject(app, user=request.user, reason=RejectionReason.objects.get(code="trn_invalid"), text="TRN not found at the Tax Office.")
    except services.ProcessingError as exc:
        messages.error(request, str(exc))
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def request_srn(request, tracking):
    """Ask for an SRN from within an application whose TRN cannot be validated."""
    app = _work_app(request, tracking)
    form = SrnRequestForm(request.POST)
    if form.is_valid() and app.is_open:
        d = form.cleaned_data
        issue = identity.request_srn(
            user=request.user,
            first_name=d["first_name"],
            middle_name=d["middle_name"],
            last_name=d["last_name"],
            dob=d["dob"],
            gender=d["gender"],
            reason=d["reason"],
        )
        services.link_srn_request(app, issue)
        messages.success(request, "SRN requested; waiting for management approval.")
    else:
        messages.error(request, "Complete every SRN field.")
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def approve(request, tracking):
    """Approve (one transaction)."""
    app = _work_app(request, tracking)
    try:
        app = services.approve(app.pk, user=request.user)
    except services.ProcessingError as exc:
        messages.error(request, str(exc))
        return redirect("members:application", tracking=tracking)
    if app.kind == "change":
        card = app.cards.first()
        messages.success(
            request, "Change form approved." + (f" Card v{card.version_no} queued ({card.get_reason_display().lower()})." if card else " No reprint needed.")
        )
    else:
        messages.success(request, f"Approved. Member number {app.member.member_number}. Card queued for printing.")
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required(*PROCESS_ROLES)
def reject(request, tracking):
    """Reject with a reason (MR10008, MR10009)."""
    app = _work_app(request, tracking)
    form = RejectForm(request.POST)
    if form.is_valid():
        try:
            services.reject(app, user=request.user, reason=form.cleaned_data["reason"], text=form.cleaned_data["text"])
            messages.success(request, f"{app.tracking_number} rejected.")
        except services.ProcessingError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Choose a rejection reason.")
    return redirect("members:application", tracking=tracking)


@require_POST
@role_required("supervisor", "manager")
def assign(request, tracking):
    """Supervisor assigns the application to an agent."""
    from django.contrib.auth import get_user_model

    app = _work_app(request, tracking)
    user = get_user_model().objects.filter(pk=request.POST.get("user"), is_active=True).first()
    if user:
        intake.assign(app, to_user=user, by_user=request.user)
        messages.success(request, f"Assigned to {user.display_name()}.")
    nxt = request.POST.get("next", "")
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()) else "intake:queue")


@role_required(*MEMBER_ROLES)
def member(request, member_number):
    """Member profile (MR10014–MR10016)."""
    m = get_object_or_404(Member.objects.select_related("collection_centre", "registered_centre"), member_number=member_number)
    # The form gets its own copy: validation writes into its instance, and update_contact compares against the stored record.
    contact_form = ContactForm(request.POST if request.POST.get("action") == "contact" else None, instance=Member.objects.get(pk=m.pk), prefix="c")
    id_form = IdDocumentForm(request.POST if request.POST.get("action") == "iddoc" else None, instance=Member.objects.get(pk=m.pk), prefix="d")
    if request.method == "POST" and request.POST.get("action") == "iddoc":
        if not has_role(request.user, *PROCESS_ROLES):
            return redirect("members:member", member_number=member_number)
        if id_form.is_valid():
            changed = services.update_id_document(m, user=request.user, data=id_form.cleaned_data)
            messages.success(request, "Identity document updated." if changed else "No changes.")
            return redirect("members:member", member_number=member_number)
    if request.method == "POST" and request.POST.get("action") == "contact":
        if not has_role(request.user, *PROCESS_ROLES):
            return redirect("members:member", member_number=member_number)
        if contact_form.is_valid():
            changed = services.update_contact(m, user=request.user, data=contact_form.cleaned_data)
            messages.success(request, "Contact details updated." if changed else "No changes.")
            return redirect("members:member", member_number=member_number)
    audit.record("member.viewed", m, f"Profile {m.member_number} viewed" + (" incl. conditions" if can_view_conditions(request.user) else ""))
    ctx = {
        "m": m,
        "contact_form": contact_form,
        "id_form": id_form,
        "interaction_form": InteractionForm(),
        "conditions": m.conditions.filter(active=True).select_related("condition", "certified_by"),
        "can_conditions": can_view_conditions(request.user),
        "can_process": has_role(request.user, *PROCESS_ROLES),
        "enrolments": m.enrolments.select_related("programme"),
        "cards": m.cards.select_related("centre"),
        "applications": m.applications.select_related("centre", "rejection_reason")[:20],
        "interactions": m.interactions.select_related("actor", "application").prefetch_related("notes")[:60],
        "guardian": getattr(m, "guardian", None),
        "screenings": _screenings_for(m, with_conditions=can_view_conditions(request.user)),
        "child_double": m.age() is not None and m.age() < int(Parameter.get("child-double-subsidy-under-age")),
        "child_age": Parameter.get("child-double-subsidy-under-age"),
        "page_title": m.full_name,
    }
    return render(request, "members/member.html", ctx)


def _screenings_for(m, *, with_conditions):
    """Screening tests the member qualifies for. Staff who may not see conditions get only the age/sex-based ones."""
    from apps.rules.models import ScreeningTest

    codes = set(m.conditions.filter(active=True).values_list("condition__code", flat=True)) if with_conditions else set()
    rows = []
    for test in ScreeningTest.objects.filter(is_active=True).select_related("requires_condition", "allowance_condition"):
        if not with_conditions and test.requires_condition_id:
            continue
        ok, allowance = test.eligible(age=m.age(), gender=m.gender, condition_codes=codes)
        if ok:
            rows.append({"test": test, "allowance": allowance})
    return rows


@role_required(*MEMBER_ROLES)
def applications(request):
    """Applications list with filters."""
    from apps.accounts.scoping import scope_by_centre, sees_all_centres

    qs = scope_by_centre(Application.objects.select_related("centre", "assigned_to", "worked_by", "member"), request.user)
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.filter(status__in=Application.OPEN_STATUSES)
    elif status:
        qs = qs.filter(status=status)
    for key in ("channel", "kind"):
        if request.GET.get(key):
            qs = qs.filter(**{key: request.GET[key]})
    if request.GET.get("centre"):
        qs = qs.filter(centre_id=request.GET["centre"])
    if request.GET.get("mine"):
        qs = qs.filter(Q(entered_by=request.user) | Q(assigned_to=request.user))
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "members/applications.html",
        {
            "page": page,
            "status": status,
            "statuses": Application.STATUSES,
            "channels": Application.CHANNELS,
            "centres": Centre.objects.all(),
            "all_centres": sees_all_centres(request.user),
            "page_title": "Applications",
        },
    )


TRACK_RE = re.compile(r"^NHF-A-\d{4}-\d{1,7}$", re.I)


@role_required(*MEMBER_ROLES)
def search(request):
    """MR10016 search and AT10001 tracking by TRN, application number, member number or programme."""
    q = request.GET.get("q", "").strip()
    programme = request.GET.get("programme", "")
    members = Member.objects.none()
    apps = Application.objects.none()
    if q:
        digits = re.sub(r"\D", "", q)
        if TRACK_RE.match(q):
            app = Application.objects.filter(tracking_number__iexact=q.upper()).first()
            if app:
                return redirect("members:application", tracking=app.tracking_number)
        nis = normalise_nis(q)
        if len(digits) == 9 and digits == q.replace(" ", "").replace("-", ""):
            members = Member.objects.filter(Q(trn=digits) | Q(nis_number=digits))
            apps = Application.objects.filter(Q(trn=digits) | Q(nis_number=digits))
        elif re.fullmatch(r"[A-Z][0-9]{6}", nis):
            members = Member.objects.filter(nis_number=nis)
            apps = Application.objects.filter(nis_number=nis)
        elif len(digits) == 10 and digits == q.strip():
            members = Member.objects.filter(member_number=digits)
            apps = Application.objects.filter(member__member_number=digits)
        else:
            parts = q.split()
            members = Member.objects.all()
            for p in parts:
                members = members.filter(Q(first_name__istartswith=p) | Q(last_name__istartswith=p) | Q(middle_name__istartswith=p))
            apps = Application.objects.filter(Q(last_name__iexact=parts[-1]) | Q(form_last_name__iexact=parts[-1]))
            if len(parts) > 1:
                apps = apps.filter(Q(first_name__istartswith=parts[0]) | Q(form_first_name__istartswith=parts[0]))
    if programme:
        base = members if q else Member.objects.all()
        members = base.filter(enrolments__programme__code=programme, enrolments__ended_at__isnull=True)
        apps = (
            apps.filter(member__enrolments__programme__code=programme)
            if q
            else Application.objects.filter(member__enrolments__programme__code=programme, status__in=Application.OPEN_STATUSES)
        )
    members = members.select_related("collection_centre").distinct()[:50]
    apps = apps.select_related("centre", "member").distinct()[:50]
    if q and len(members) == 1 and not apps:
        return redirect("members:member", member_number=members[0].member_number)
    return render(
        request,
        "members/search.html",
        {
            "q": q,
            "programme": programme,
            "programmes": Programme.objects.filter(is_active=True),
            "members": members,
            "apps": apps,
            "page_title": "Tracking search",
        },
    )


@require_POST
@role_required(*PROCESS_ROLES)
def add_interaction(request, member_number):
    """IL10001: staff-recorded contact on the member."""
    m = get_object_or_404(Member, member_number=member_number)
    form = InteractionForm(request.POST)
    if form.is_valid():
        log(form.cleaned_data["summary"], member=m, kind=form.cleaned_data["kind"], event="staff." + form.cleaned_data["kind"], actor=request.user)
    return redirect(f"/members/{m.member_number}/#log")


@role_required(*PROCESS_ROLES)
def expired_ids(request):
    """Members whose ID on file has expired or expires soon: ask for a current ID at their next visit."""
    from django.core.paginator import Paginator

    from apps.core.models import Parameter

    today = timezone.localdate()
    soon = today + timedelta(days=int(Parameter.get("id-expiry-warning-days")))
    which = request.GET.get("show", "expired")
    from apps.accounts.scoping import scope_by_centre

    base = scope_by_centre(Member.objects.all(), request.user, field="collection_centre")
    qs = base.filter(id_expiry__isnull=False).order_by("id_expiry")
    qs = qs.filter(id_expiry__lt=today) if which == "expired" else qs.filter(id_expiry__gte=today, id_expiry__lte=soon)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "members/expired_ids.html",
        {
            "page": page,
            "show": which,
            "today": today,
            "soon": soon,
            "counts": {
                "expired": base.filter(id_expiry__lt=today).count(),
                "soon": base.filter(id_expiry__gte=today, id_expiry__lte=soon).count(),
            },
            "page_title": "Expired IDs",
        },
    )
