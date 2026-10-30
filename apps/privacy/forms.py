"""Privacy forms."""

from django import forms

from .models import Breach, DataSubjectRequest


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%dT%H:%M")


def _style(form):
    for f in form.fields.values():
        if not isinstance(f.widget, forms.CheckboxInput):
            f.widget.attrs.setdefault("class", "inp")


class DsrForm(forms.ModelForm):
    """Log a request; the member is found by member number, TRN or NIS."""

    member_lookup = forms.CharField(label="Member number, TRN or NIS (if known)", required=False)

    class Meta:
        model = DataSubjectRequest
        fields = ["requester_name", "requester_contact", "identity_checked", "kind", "channel", "details"]
        widgets = {"details": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class DsrUpdateForm(forms.ModelForm):
    class Meta:
        model = DataSubjectRequest
        fields = ["status", "identity_checked", "response"]
        widgets = {"response": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class BreachForm(forms.ModelForm):
    class Meta:
        model = Breach
        fields = [
            "title",
            "discovered_at",
            "occurred_at",
            "severity",
            "status",
            "description",
            "data_categories",
            "subjects_affected",
            "contained_at",
            "reported_to_commissioner_at",
            "subjects_notified_at",
            "actions",
        ]
        widgets = {
            "discovered_at": DateTimeInput(),
            "occurred_at": DateTimeInput(),
            "contained_at": DateTimeInput(),
            "reported_to_commissioner_at": DateTimeInput(),
            "subjects_notified_at": DateTimeInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "actions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("discovered_at", "occurred_at", "contained_at", "reported_to_commissioner_at", "subjects_notified_at"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M"]
        _style(self)
