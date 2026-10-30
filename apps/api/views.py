"""REST API (IN10001): portal intake, application tracking, member lookup."""

import json

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.roles import MEMBER_ROLES, has_role
from apps.intake import services as intake
from apps.members.models import Application, Member


class PortalThrottle(SimpleRateThrottle):
    """Rate limit for the portal endpoint, per source address."""

    scope = "portal"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class TrackingSerializer(serializers.ModelSerializer):
    """Application status as shown to tracking callers (AT10001)."""

    status_label = serializers.CharField(source="get_status_display")
    member_number = serializers.CharField(source="member.member_number", default=None)

    class Meta:
        model = Application
        fields = ["tracking_number", "kind", "channel", "status", "status_label", "received_at", "decided_at", "member_number"]


class MemberSerializer(serializers.ModelSerializer):
    """Member summary (no medical data)."""

    programmes = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = ["member_number", "trn", "is_srn", "nis_number", "first_name", "last_name", "dob", "gender", "status", "programmes"]

    def get_programmes(self, obj) -> list[str]:
        """Open enrolments."""
        return list(obj.enrolments.filter(ended_at__isnull=True).values_list("programme__code", flat=True))


@extend_schema(
    summary="Receive a doctor-portal submission (OR10001)",
    description=(
        "Headers: X-Portal-Timestamp (Unix seconds, within 5 minutes), X-Portal-Nonce (16-100 random characters, never reused), "
        "X-Portal-Signature: sha256=<hex of HMAC-SHA256 over '<timestamp>.<nonce>.<raw body>' with the shared secret>."
    ),
    request=None,
    responses={201: TrackingSerializer},
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([PortalThrottle])
def portal_intake(request):
    """Doctor-portal push endpoint."""
    problem = intake.verify_signature(
        request.body,
        request.headers.get("X-Portal-Signature", ""),
        request.headers.get("X-Portal-Timestamp", ""),
        request.headers.get("X-Portal-Nonce", ""),
    )
    if problem:
        return Response({"detail": problem}, status=401)
    try:
        payload = json.loads(request.body or b"{}")
        app = intake.receive_portal_submission(payload)
    except (ValueError, intake.SubmissionError) as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(TrackingSerializer(app).data, status=201)


@extend_schema(summary="Application status by tracking number (AT10001)", responses=TrackingSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tracking(request, tracking_number):
    """Tracking lookup."""
    if not has_role(request.user, *MEMBER_ROLES):
        return Response(status=403)
    return Response(TrackingSerializer(get_object_or_404(Application, tracking_number=tracking_number)).data)


@extend_schema(summary="Member lookup by TRN, SRN or member number", parameters=[OpenApiParameter("q", str)], responses=MemberSerializer(many=True))
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def members(request):
    """Exact-match lookup."""
    if not has_role(request.user, *MEMBER_ROLES):
        return Response(status=403)
    q = "".join(ch for ch in request.GET.get("q", "") if ch.isdigit())
    qs = Member.objects.filter(trn=q) | Member.objects.filter(member_number=q) if q else Member.objects.none()
    return Response(MemberSerializer(qs[:10], many=True).data)
