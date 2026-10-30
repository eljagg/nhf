"""Counter forms."""

from django import forms
from django.utils import timezone

from apps.core.models import PARISHES, Centre

from .models import Application, Member


class DateInput(forms.DateInput):
    """HTML5 date picker (value must be ISO for the browser to show it)."""

    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d"):  # noqa: A002 - Django's own argument name
        super().__init__(attrs=attrs, format=format)


class DateTimeInput(forms.DateTimeInput):
    """HTML5 date-time picker."""

    input_type = "datetime-local"


def _style(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput | forms.RadioSelect | forms.CheckboxSelectMultiple):
            continue
        widget.attrs.setdefault("class", "inp")


class StartForm(forms.Form):
    """MR10001/MR10010/MR10012: capture the application context, then the TRN as written on the form."""

    channel = forms.ChoiceField(
        label="Entry channel", choices=[c for c in Application.CHANNELS if c[0] != "online"], initial="walk_in", widget=forms.RadioSelect
    )
    centre = forms.ModelChoiceField(label="Processing centre", queryset=Centre.objects.filter(is_active=True))
    received_at = forms.DateTimeField(label="Date and time received", widget=DateTimeInput(format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    trn = forms.CharField(
        label="TRN",
        max_length=11,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off", "autofocus": True, "class": "inp inp-lg", "placeholder": "000 000 000"}),
    )
    form_first_name = forms.CharField(label="First name (as on form)", max_length=60)
    form_last_name = forms.CharField(label="Last name (as on form)", max_length=60)
    form_dob = forms.DateField(label="Date of birth (as on form)", widget=DateInput())

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
        self.fields["received_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        if user is not None and user.centre_id:
            self.fields["centre"].initial = user.centre_id

    def clean_trn(self):
        """Nine digits."""
        trn = "".join(ch for ch in self.cleaned_data["trn"] if ch.isdigit())
        if len(trn) != 9:
            raise forms.ValidationError("A TRN has nine digits.")
        return trn

    def clean_received_at(self):
        """Cannot be in the future."""
        value = self.cleaned_data["received_at"]
        if value > timezone.now() + timezone.timedelta(minutes=5):
            raise forms.ValidationError("The received time cannot be in the future.")
        return value


class RecheckForm(forms.Form):
    """Correct a keying error on the form details and re-check the TRN."""

    form_first_name = forms.CharField(
        label="First name (as on form)", max_length=60, widget=forms.TextInput(attrs={"placeholder": "First name", "aria-label": "First name as on form"})
    )
    form_last_name = forms.CharField(
        label="Last name (as on form)", max_length=60, widget=forms.TextInput(attrs={"placeholder": "Last name", "aria-label": "Last name as on form"})
    )
    form_dob = forms.DateField(label="Date of birth (as on form)", widget=DateInput(attrs={"aria-label": "Date of birth as on form"}))

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "rc_%s")
        super().__init__(*args, **kwargs)
        _style(self)


class ApplicationForm(forms.ModelForm):
    """Editable part of the counter screen. Name, DOB and gender are not here: they come from the TRN service only."""

    class Meta:
        model = Application
        fields = [
            # Office use / form header
            "form_serial",
            "form_revision",
            # Section A
            "title",
            "nis_number",
            "occupation",
            "phone_mobile",
            "phone_home",
            "email",
            "address_line1",
            "address_line2",
            "post_office",
            "parish",
            "collection_centre",
            "incapacitated",
            "institutional_care",
            "screening_only",
            "plwd",
            "jcpd_evidence",
            "jcpd_number",
            # Section B
            "guardian_type",
            "guardian_institution",
            "guardian_title",
            "guardian_name",
            "guardian_relationship",
            "guardian_address",
            "guardian_parish",
            "guardian_trn",
            "guardian_phone",
            "guardian_id_type",
            "guardian_id_number",
            # Declaration
            "declaration_signed",
            "declaration_date",
            "trn_copy_attached",
            "consent_given",
            # Section C
            "doctor_mcj",
            "referring_doctor_name",
            "doctor_office_address",
            "doctor_parish",
            "doctor_office_phone",
            "certified_on",
            "conditions_total",
            "doctor_signed",
            # Change form tick-boxes
            "change_contact",
            "change_conditions",
            "change_guardian",
            "change_identity",
            "reprint_reason",
        ]
        widgets = {
            "declaration_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "certified_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "guardian_address": forms.TextInput(),
            "doctor_office_address": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collection_centre"].queryset = Centre.objects.filter(is_active=True)
        for name in ("parish", "guardian_parish", "doctor_parish"):
            self.fields[name].choices = [("", "—")] + PARISHES
        for name in ("doctor_mcj", "form_serial", "conditions_total"):
            self.fields[name].widget.attrs["inputmode"] = "numeric"
        self.fields["guardian_id_number"].widget = forms.TextInput(attrs={"autocomplete": "off"})
        if self.instance.kind != "change":
            for f in ("change_contact", "change_conditions", "change_guardian", "change_identity", "reprint_reason"):
                self.fields.pop(f)
        if self.instance.channel != "mail":
            self.fields.pop("trn_copy_attached")
        _style(self)
        if not self.instance.is_open:
            for field in self.fields.values():
                field.disabled = True

    def clean_form_serial(self):
        """Digits only; each pre-printed form is used once."""
        value = "".join(ch for ch in self.cleaned_data.get("form_serial", "") if not ch.isspace())
        if value and not value.isdigit():
            raise forms.ValidationError("The form serial number is the digits printed on the form.")
        if value and Application.objects.filter(form_serial=value).exclude(pk=self.instance.pk).exists():
            other = Application.objects.filter(form_serial=value).exclude(pk=self.instance.pk).first()
            raise forms.ValidationError(f"Form {value} is already recorded on application {other.tracking_number}.")
        return value

    def clean_conditions_total(self):
        """The doctor's 'total number of conditions' box: 1–28 when filled."""
        value = self.cleaned_data.get("conditions_total")
        if value is not None and not 0 < value <= 40:
            raise forms.ValidationError("Enter the number the doctor wrote (1–28).")
        return value

    def clean(self):
        data = super().clean()
        if data.get("guardian_type") == "institution" and not data.get("guardian_institution"):
            self.add_error("guardian_institution", "Name the institution.")
        if data.get("declaration_date") and data["declaration_date"] > timezone.localdate():
            self.add_error("declaration_date", "The date signed cannot be in the future.")
        if data.get("certified_on") and data["certified_on"] > timezone.localdate():
            self.add_error("certified_on", "The certification date cannot be in the future.")
        if data.get("jcpd_number"):
            data["jcpd_number"] = data["jcpd_number"].strip().upper()
        return data

    def clean_nis_number(self):
        """Normalised; must match the configured NIS format and not belong to another member."""
        from .identifiers import is_valid_nis, nis_owner, normalise_nis

        value = normalise_nis(self.cleaned_data.get("nis_number", ""))
        if value and not is_valid_nis(value):
            raise forms.ValidationError("Not a valid NIS number for the configured format.")
        member_id = self.instance.pk if isinstance(self.instance, Member) else self.instance.member_id
        owner = nis_owner(value, exclude_member_id=member_id)
        if owner:
            raise forms.ValidationError(f"Already recorded for member {owner.member_number}.")
        return value

    def clean_guardian_trn(self):
        """Optional; nine digits when given."""
        value = "".join(ch for ch in self.cleaned_data.get("guardian_trn", "") if ch.isdigit())
        if value and len(value) != 9:
            raise forms.ValidationError("A TRN has nine digits.")
        return value


class RejectForm(forms.Form):
    """MR10008: reason from the configurable list, plus free text."""

    reason = forms.ModelChoiceField(queryset=None, label="Reason")
    text = forms.CharField(label="Note", max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        from apps.rules.models import RejectionReason

        super().__init__(*args, **kwargs)
        self.fields["reason"].queryset = RejectionReason.objects.filter(is_active=True, is_system=False)
        _style(self)
        self.fields["text"].widget.attrs["placeholder"] = "Note for the record (optional)"


class ContactForm(forms.ModelForm):
    """MR10006: contact details edited directly on the profile."""

    class Meta:
        model = Member
        fields = ["nis_number", "phone_mobile", "phone_home", "email", "address_line1", "address_line2", "parish"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parish"].choices = [("", "—")] + PARISHES
        _style(self)

    def clean_nis_number(self):
        """Normalised; must match the configured NIS format and not belong to another member."""
        from .identifiers import is_valid_nis, nis_owner, normalise_nis

        value = normalise_nis(self.cleaned_data.get("nis_number", ""))
        if value and not is_valid_nis(value):
            raise forms.ValidationError("Not a valid NIS number for the configured format.")
        member_id = self.instance.pk if isinstance(self.instance, Member) else self.instance.member_id
        owner = nis_owner(value, exclude_member_id=member_id)
        if owner:
            raise forms.ValidationError(f"Already recorded for member {owner.member_number}.")
        return value


class SrnRequestForm(forms.Form):
    """SR10001: the applicant has no TRN that can be validated."""

    first_name = forms.CharField(max_length=60)
    middle_name = forms.CharField(max_length=60, required=False)
    last_name = forms.CharField(max_length=60)
    dob = forms.DateField(label="Date of birth", widget=DateInput())
    gender = forms.ChoiceField(choices=[("F", "Female"), ("M", "Male")])
    reason = forms.CharField(max_length=300, label="Why there is no validated TRN")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class InteractionForm(forms.Form):
    """Staff-recorded contact (IL10001)."""

    kind = forms.ChoiceField(choices=[("visit", "Counter visit"), ("call", "Telephone call"), ("email", "E-mail"), ("note", "Note")])
    summary = forms.CharField(max_length=400, widget=forms.TextInput(attrs={"placeholder": "What happened"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class IdDocumentForm(forms.ModelForm):
    """The government ID the member showed: type, number, issue and expiry dates."""

    class Meta:
        model = Member
        fields = ["id_type", "id_number", "id_issue_date", "id_expiry"]
        widgets = {
            "id_issue_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "id_expiry": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["id_number"].widget = forms.TextInput(attrs={"autocomplete": "off"})
        _style(self)
        self.fields["id_number"].widget.attrs["class"] = "inp font-mono"

    def clean(self):
        from django.utils import timezone

        data = super().clean()
        data["id_number"] = " ".join((data.get("id_number") or "").split()).upper()
        if data["id_number"] and not data.get("id_type"):
            self.add_error("id_type", "Choose the ID type.")
        issued, expiry = data.get("id_issue_date"), data.get("id_expiry")
        if issued and issued > timezone.localdate():
            self.add_error("id_issue_date", "The issue date cannot be in the future.")
        if issued and expiry and expiry <= issued:
            self.add_error("id_expiry", "The expiry date must be after the issue date.")
        return data
