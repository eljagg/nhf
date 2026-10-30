from django.urls import path

from . import views

app_name = "doctors"
urlpatterns = [
    path("", views.doctor_list, name="list"),
    path("confirmations/", views.confirmations, name="confirmations"),
    path("register-import/", views.register_import, name="register-import"),
    path("nurses/", views.nurse_list, name="nurses"),
    path("nurses/add/", views.nurse_add, name="nurse-add"),
    path("nurses/<str:ncj>/", views.nurse_detail, name="nurse-detail"),
    path("nurses/<str:ncj>/decide/", views.decide_nurse, name="decide-nurse"),
    path("<str:kind>/<str:number>/check-register/", views.check_register, name="check-register"),
    path("<str:kind>/<str:number>/photo/", views.upload_photo, name="photo"),
    path("<str:mcj>/", views.doctor_detail, name="detail"),
    path("<str:mcj>/decide/", views.decide, name="decide"),
]
