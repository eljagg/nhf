from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("how-to-apply/", views.how_to_apply, name="how-to-apply"),
    path("inbox/", views.notifications, name="notifications"),
    path("inbox/<int:pk>/open/", views.notification_open, name="notification-open"),
    path("audit/", views.audit_trail, name="audit"),
    path("integrations/", views.integrations, name="integrations"),
    path("images/<uuid:pk>/", views.image, name="image"),
]
