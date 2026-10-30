from django.urls import path

from . import views

app_name = "security"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("alerts/<int:pk>/acknowledge/", views.acknowledge, name="acknowledge"),
    path("unlock/", views.unlock, name="unlock"),
    path("activity/", views.activity, name="activity"),
    path("activity/export.csv", views.activity_csv, name="activity-csv"),
    path("users/<int:user_id>/end-sessions/", views.end_user_sessions, name="end-sessions"),
]
