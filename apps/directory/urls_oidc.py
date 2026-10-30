from django.urls import path

from . import oidc

app_name = "oidc"
urlpatterns = [
    path("login/", oidc.start, name="login"),
    path("callback/", oidc.callback, name="callback"),
]
