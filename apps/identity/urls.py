from django.urls import path

from . import views

app_name = "identity"
urlpatterns = [
    path("screen/", views.screen, name="screen"),
    path("screen/<int:pk>/", views.screen_result, name="screen-result"),
    path("srn/", views.srn_list, name="srn-list"),
    path("srn/<int:pk>/", views.srn_detail, name="srn-detail"),
    path("srn/<int:pk>/decide/", views.srn_decide, name="srn-decide"),
]
