from django.contrib.auth import views as auth_views
from django.urls import path

from . import staff, views

app_name = "accounts"
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("mfa/setup/", views.mfa_setup, name="mfa-setup"),
    path("mfa/verify/", views.mfa_verify, name="mfa-verify"),
    path("mfa/backup-codes/", views.mfa_backup_codes, name="mfa-backup-codes"),
    path("me/backup-codes/", views.regenerate_backup_codes, name="regenerate-backup-codes"),
    path("me/", views.my_account, name="me"),
    path("me/end-other-sessions/", views.end_other_sessions, name="end-other-sessions"),
    path("password/", views.StaffPasswordChangeView.as_view(), name="password-change"),
    path("password/reset/", views.ThrottledPasswordResetView.as_view(), name="password-reset"),
    path("password/reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password-reset-done"),
    path("password/reset/<uidb64>/<token>/", views.AuditedPasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path(
        "password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
        name="password-reset-complete",
    ),
    path("temporary-roles/", views.temporary_roles, name="temporary-roles"),
    path("me/photo/", staff.my_photo, name="my-photo"),
    path("staff/", staff.staff_list, name="staff"),
    path("staff/<int:user_id>/", staff.staff_detail, name="staff-detail"),
    path("staff/<int:user_id>/image/<str:kind>/", staff.staff_image, name="staff-image"),
    path("staff/<int:user_id>/suspend/", staff.suspend, name="staff-suspend"),
    path("staff/<int:user_id>/reinstate/", staff.reinstate, name="staff-reinstate"),
    path("staff/<int:user_id>/role-request/", staff.request_role_change, name="role-request"),
    path("role-requests/<int:pk>/decide/", staff.decide_role_change, name="role-decide"),
    path("temporary-roles/<int:pk>/revoke/", views.revoke_temporary_role, name="revoke-temporary-role"),
]
