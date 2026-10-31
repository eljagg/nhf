from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.catalogue, name="catalogue"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("builder/", views.builder, name="builder"),
    path("builder/save/", views.builder_save, name="builder-save"),
    path("saved/<int:pk>/", views.saved, name="saved"),
    path("saved/<int:pk>/save/", views.builder_save, name="builder-update"),
    path("saved/<int:pk>/delete/", views.delete_saved, name="delete"),
    path("saved/<int:pk>/schedule/", views.schedule, name="schedule"),
    path("schedules/<int:pk>/stop/", views.schedule_stop, name="schedule-stop"),
    path("schedules/<int:pk>/send-now/", views.schedule_send_now, name="schedule-send-now"),
    path("standard/<slug:key>/", views.standard_report, name="standard"),
    path("standard/<slug:key>/save/", views.save_standard, name="save-standard"),
]
