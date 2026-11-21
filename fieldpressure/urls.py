from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Platform API (core). Interactive docs: /api/docs/
    path("api/", include("core.urls")),
    # Chat endpoints (assistant app, owner Ola; docs/interfaces.md -> Chat)
    path("api/", include("assistant.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
    # Web app (must stay last: it serves "/")
    path("", include("frontend.urls")),
]
