"""Root URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

admin.site.site_header = f"{settings.PRODUCT_NAME} — back office"
admin.site.site_title = "Member Registration admin"

urlpatterns = [
    path("", include("apps.core.urls")),
    path("accounts/oidc/", include("apps.directory.urls_oidc")),
    path("accounts/", include("apps.accounts.urls")),
    path("members/", include("apps.members.urls")),
    path("identity/", include("apps.identity.urls")),
    path("doctors/", include("apps.doctors.urls")),
    path("cards/", include("apps.cards.urls")),
    path("interactions/", include("apps.interactions.urls")),
    path("intake/", include("apps.intake.urls")),
    path("api/", include("apps.api.urls")),
    path("security/directory/", include("apps.directory.urls")),
    path("security/", include("apps.security.urls")),
    path("privacy/", include("apps.privacy.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("backoffice/", admin.site.urls),
]
