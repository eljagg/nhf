from django.urls import path

from . import views

app_name = "doctors"
urlpatterns = [
    path("", views.doctor_list, name="list"),
    path("confirmations/", views.confirmations, name="confirmations"),
    path("<str:mcj>/", views.doctor_detail, name="detail"),
    path("<str:mcj>/decide/", views.decide, name="decide"),
]
