import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from PIL import Image

from myapp.models import Course, Subject


def make_user(name, role="student", consent=True, **kw):
    u = User.objects.create_user(name, f"{name}@example.com", "Pass-12345-x", first_name=name.title(), **kw)
    p = u.profile
    p.role = role
    p.ai_consent = consent
    p.save()
    return u


def make_course(teacher, title="Science"):
    subject, _ = Subject.objects.get_or_create(name="Science")
    return Course.objects.create(subject=subject, teacher=teacher, title=title)


def png_upload(name="page.png", size=(40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


AI_SETTINGS = {
    "BASE_URL": "https://ai.example.test", "API_KEY": "test-key", "TIMEOUT": 5, "MAX_RETRIES": 1, "TEXT_PROVIDER": "spark",
    "MODELS": {k: {"model": f"{k}-model", "path": f"/v1/{k}"} for k in ("spark", "wonder", "image", "voice", "sam")},
    "LOCAL": {"base_url": "", "model": "", "api_key": ""},
}


class ClearCacheMixin:
    def setUp(self):
        cache.clear()
        super().setUp()
