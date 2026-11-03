from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("myapp.urls")),
]

handler403 = "myapp.views.core.permission_denied"
handler404 = "myapp.views.core.not_found"
handler500 = "myapp.views.core.server_error"
