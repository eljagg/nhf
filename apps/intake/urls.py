from django.urls import path

from . import views

app_name = "intake"
urlpatterns = [
    path("", views.queue, name="queue"),
    path("simulate/", views.simulate, name="simulate"),
]
