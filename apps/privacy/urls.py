from django.urls import path

from . import views

app_name = "privacy"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("requests/", views.dsr_list, name="dsr-list"),
    path("requests/<int:pk>/", views.dsr_detail, name="dsr-detail"),
    path("requests/<int:pk>/export.json", views.dsr_export, name="dsr-export"),
    path("breaches/", views.breach_list, name="breach-list"),
    path("breaches/<int:pk>/", views.breach_detail, name="breach-detail"),
    path("breaches/<int:pk>/notice/<str:audience>.txt", views.breach_notice, name="breach-notice"),
    path("impact-assessments/", views.dpia_list, name="dpia-list"),
    path("impact-assessments/<int:year>/", views.dpia_detail, name="dpia-detail"),
    path("register/", views.register, name="register"),
    path("retention/run/", views.retention_run, name="retention-run"),
]
