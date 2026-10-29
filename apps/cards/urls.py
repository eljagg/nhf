from django.urls import path

from . import views

app_name = "cards"
urlpatterns = [path("queue/", views.queue, name="queue")]
