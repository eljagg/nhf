from django.urls import path

from . import views

app_name = "interactions"
urlpatterns = [path("<int:pk>/note/", views.add_note, name="add-note")]
