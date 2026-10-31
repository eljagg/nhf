from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .access import SCHEDULE_ROLES
from .models import ReportSchedule


class SaveReportForm(forms.Form):
    name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"class": "inp", "placeholder": "e.g. Weekly applications by centre"}))
    description = forms.CharField(max_length=300, required=False, widget=forms.TextInput(attrs={"class": "inp"}))
    shared = forms.BooleanField(required=False, label="Share with everyone who uses reports")


def schedule_recipients():
    """Active staff with an e-mail address who hold a role that may receive reports."""
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(Q(suspended_at__isnull=True) | Q(suspended_until__lte=timezone.now()))
        .exclude(email="")
        .filter(Q(groups__name__in=SCHEDULE_ROLES))
        .distinct()
        .order_by("last_name", "first_name")
    )


class ScheduleForm(forms.ModelForm):
    class Meta:
        model = ReportSchedule
        fields = ["frequency", "hour", "period_days", "recipients"]
        labels = {"hour": "Send at (hour, 0–23)", "period_days": "Each e-mail covers (days)"}
        widgets = {"recipients": forms.CheckboxSelectMultiple}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = schedule_recipients()
        self.fields["recipients"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.username})"
        for name in ("frequency", "hour", "period_days"):
            self.fields[name].widget.attrs["class"] = "inp"
        if user is not None and not self.is_bound:
            self.initial.setdefault("recipients", [user.pk])

    def clean_hour(self):
        hour = self.cleaned_data["hour"]
        if not 0 <= hour <= 23:
            raise forms.ValidationError("Enter an hour from 0 to 23.")
        return hour

    def clean_period_days(self):
        days = self.cleaned_data["period_days"]
        if not 1 <= days <= 366:
            raise forms.ValidationError("Enter 1 to 366 days.")
        return days
