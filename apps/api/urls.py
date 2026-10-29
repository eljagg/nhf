from django.urls import path

from . import views

app_name = "api"
urlpatterns = [
    path("intake/portal/", views.portal_intake, name="portal-intake"),
    path("applications/<str:tracking_number>/", views.tracking, name="tracking"),
    path("members/", views.members, name="members"),
]
