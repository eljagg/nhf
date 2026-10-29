from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("mfa/setup/", views.mfa_setup, name="mfa-setup"),
    path("mfa/verify/", views.mfa_verify, name="mfa-verify"),
    path("me/", views.my_account, name="me"),
    path("temporary-roles/", views.temporary_roles, name="temporary-roles"),
    path("temporary-roles/<int:pk>/revoke/", views.revoke_temporary_role, name="revoke-temporary-role"),
]
