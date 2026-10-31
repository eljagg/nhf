"""The period / centre / channel filters every report and the dashboard share."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django import forms
from django.utils import timezone

from apps.core.models import Centre
from apps.members.models import Application

from .access import centre_filter

PRESETS = [("today", "Today"), ("7", "Last 7 days"), ("30", "Last 30 days"), ("90", "Last 90 days"), ("365", "Last 12 months")]
MAX_DAYS = 731


class PeriodForm(forms.Form):
    preset = forms.ChoiceField(choices=[("", "Custom dates")] + PRESETS, required=False, initial="30")
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": "inp"}, format="%Y-%m-%d"))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": "inp"}, format="%Y-%m-%d"))
    centre = forms.ModelChoiceField(queryset=Centre.objects.none(), required=False, empty_label="All centres")
    channel = forms.ChoiceField(choices=[("", "All channels")] + list(Application.CHANNELS), required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centre"].queryset = Centre.objects.filter(is_active=True).order_by("name")
        for name in ("preset", "centre", "channel"):
            self.fields[name].widget.attrs["class"] = "inp"
        if user is not None and centre_filter(user) is not None:
            self.fields.pop("centre")


@dataclass
class Period:
    start_date: date
    end_date: date
    centre: object = None  # Centre or None
    channel: str = ""
    label: str = ""

    @property
    def start(self):
        return timezone.make_aware(datetime.combine(self.start_date, time.min))

    @property
    def end(self):
        """Exclusive upper bound (midnight after end_date)."""
        return timezone.make_aware(datetime.combine(self.end_date + timedelta(days=1), time.min))

    @property
    def days(self):
        return [self.start_date + timedelta(days=i) for i in range((self.end_date - self.start_date).days + 1)]

    def as_query(self):
        q = {"date_from": self.start_date.isoformat(), "date_to": self.end_date.isoformat()}
        if self.centre:
            q["centre"] = self.centre.pk
        if self.channel:
            q["channel"] = self.channel
        return q


def period_from(request_data, user, default_days=30):
    """Read the shared filters; a centre-bound user is always held to their own centre."""
    form = PeriodForm(request_data or None, user=user)
    today = timezone.localdate()
    start, end, centre, channel, label = today - timedelta(days=default_days - 1), today, None, "", f"Last {default_days} days"
    if form.is_valid():
        data = form.cleaned_data
        preset = data.get("preset")
        if data.get("date_from") or data.get("date_to"):
            start = data.get("date_from") or start
            end = data.get("date_to") or end
            label = f"{start:%d %b %Y} – {end:%d %b %Y}"
        elif preset == "today":
            start, end, label = today, today, "Today"
        elif preset and preset.isdigit():
            start, label = today - timedelta(days=int(preset) - 1), dict(PRESETS)[preset]
        centre = data.get("centre")
        channel = data.get("channel") or ""
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_DAYS:
        start = end - timedelta(days=MAX_DAYS)
    forced = centre_filter(user)
    if forced is not None:
        centre = Centre.objects.filter(pk=forced).first()
    if not form.is_bound:
        form = PeriodForm(initial={"preset": str(default_days)}, user=user)
    return Period(start, end, centre, channel, label), form
