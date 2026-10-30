from django.urls import path

from . import views

app_name = "members"
urlpatterns = [
    path("new/", views.start, name="start"),
    path("new/without-trn/", views.start_without_trn, name="start-without-trn"),
    path("applications/", views.applications, name="applications"),
    path("search/", views.search, name="search"),
    path("expired-ids/", views.expired_ids, name="expired-ids"),
    path("applications/<str:tracking>/", views.application, name="application"),
    path("applications/<str:tracking>/slip/", views.pickup_slip, name="pickup-slip"),
    path("applications/<str:tracking>/identity/", views.identity_panel, name="identity-panel"),
    path("applications/<str:tracking>/heartbeat/", views.heartbeat, name="heartbeat"),
    path("applications/<str:tracking>/recheck/", views.recheck, name="recheck"),
    path("applications/<str:tracking>/revalidate/", views.revalidate, name="revalidate"),
    path("applications/<str:tracking>/terminate/", views.terminate, name="terminate"),
    path("applications/<str:tracking>/notify-invalid/", views.notify_invalid, name="notify-invalid"),
    path("applications/<str:tracking>/reject-invalid/", views.reject_invalid_trn, name="reject-invalid"),
    path("applications/<str:tracking>/request-srn/", views.request_srn, name="request-srn"),
    path("applications/<str:tracking>/approve/", views.approve, name="approve"),
    path("applications/<str:tracking>/reject/", views.reject, name="reject"),
    path("applications/<str:tracking>/assign/", views.assign, name="assign"),
    path("<str:member_number>/", views.member, name="member"),
    path("<str:member_number>/change/", views.start_change, name="start-change"),
    path("<str:member_number>/interaction/", views.add_interaction, name="add-interaction"),
]
