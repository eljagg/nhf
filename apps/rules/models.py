"""Reference data configured by NHF: programmes, benefits, medical conditions, rejection reasons (BR10009–BR10011)."""

from django.db import models

SEX_CHOICES = [("", "Any"), ("M", "Male only"), ("F", "Female only")]


class Programme(models.Model):
    """A benefits programme (NHF Individual Benefit, JADEP, GOJ …)."""

    code = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    auto_assign = models.BooleanField(default=False, help_text="Assigned by the rules engine whenever the member is eligible (e.g. JADEP at 60).")
    requires_condition = models.BooleanField(default=True, help_text="Member must have at least one condition covered by this programme.")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Benefit(models.Model):
    """A benefit offered under a programme."""

    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name="benefits")
    code = models.SlugField(max_length=30)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["programme", "name"]
        constraints = [models.UniqueConstraint(fields=["programme", "code"], name="uniq_benefit_code")]

    def __str__(self):
        return f"{self.programme.code}: {self.name}"


class MedicalCondition(models.Model):
    """A condition the Fund covers; sex and age bounds drive the clinical-consistency rule (BR10006)."""

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    group = models.CharField(max_length=60, blank=True, help_text="Reporting group, e.g. Cardiovascular.")
    sex_restriction = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    programmes = models.ManyToManyField(Programme, related_name="conditions", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RejectionReason(models.Model):
    """Configurable rejection reasons (MR10008, MR10009). System reasons are used by automated decisions."""

    code = models.SlugField(max_length=30, unique=True)
    label = models.CharField(max_length=160)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label
