"""Django settings for LearnMate AI. All secrets come from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Tiny .env loader so the project runs without extra packages."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        k = key.strip()
        v = value.strip().strip('"').strip("'")
        if not os.environ.get(k):
            os.environ[k] = v


_load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "myapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "myproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "myapp.context_processors.shell",
            ],
        },
    },
]

WSGI_APPLICATION = "myproject.wsgi.application"

# --- Database: SQLite for development, PostgreSQL when DATABASE_URL-style vars are set
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "LearnMate AI <no-reply@learnmate.local>")

# --- Sessions and cookies
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

TEACHER_SELF_SIGNUP = env_bool("TEACHER_SELF_SIGNUP", False)
ADMIN_SELF_SIGNUP = env_bool("ADMIN_SELF_SIGNUP", True)


# --- Uploads
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
MAX_IMAGE_UPLOAD_MB = int(os.environ.get("MAX_IMAGE_UPLOAD_MB", "8"))
MAX_AUDIO_UPLOAD_MB = int(os.environ.get("MAX_AUDIO_UPLOAD_MB", "10"))
MAX_MATERIAL_UPLOAD_MB = int(os.environ.get("MAX_MATERIAL_UPLOAD_MB", "15"))

# --- Caching (used for rate limiting). Use Redis in production for multi-process setups.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "learnmate"}}
if os.environ.get("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": os.environ["REDIS_URL"]}}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}

# --- Rate limits for expensive AI operations: (max requests, window in seconds) per user
AI_RATE_LIMITS = {
    "tutor": (int(os.environ.get("RATE_TUTOR_MAX", "30")), 3600),
    "quiz": (int(os.environ.get("RATE_QUIZ_MAX", "10")), 3600),
    "vision": (int(os.environ.get("RATE_VISION_MAX", "15")), 3600),
    "voice": (int(os.environ.get("RATE_VOICE_MAX", "20")), 3600),
    "image": (int(os.environ.get("RATE_IMAGE_MAX", "8")), 3600),
}

# --- Data retention (days). Run `python manage.py purge_old_data` from cron.
RETENTION_DAYS = {
    "ai_request_logs": int(os.environ.get("RETAIN_AI_LOG_DAYS", "90")),
    "read_notifications": int(os.environ.get("RETAIN_NOTIFICATION_DAYS", "60")),
}

# --- Meta AI provider configuration (see README: verify every value against the official docs)
META_AI = {
    "BASE_URL": os.environ.get("META_API_BASE_URL", ""),
    "API_KEY": os.environ.get("META_API_KEY", ""),
    "TIMEOUT": float(os.environ.get("META_API_TIMEOUT", "90")),
    "MAX_RETRIES": int(os.environ.get("META_API_MAX_RETRIES", "2")),
    "MODELS": {
        "spark": {
            "model": os.environ.get("MUSE_SPARK_MODEL") or "muse-spark-1.3",
            "path": os.environ.get("MUSE_SPARK_PATH") or "/responses",
        },
        "wonder": {
            "model": os.environ.get("MUSE_WONDER_MODEL") or "muse-wonder-1.0",
            "path": os.environ.get("MUSE_WONDER_PATH") or "/responses",
        },
        "image": {
            "model": os.environ.get("MUSE_IMAGE_MODEL") or "muse-image-1.0",
            "path": os.environ.get("MUSE_IMAGE_PATH") or "/images/generations",
        },
        "voice": {
            "model": os.environ.get("MUSE_VOICE_MODEL", ""),
            "path": os.environ.get("MUSE_VOICE_PATH", ""),
        },
        "sam": {
            "model": os.environ.get("SAM_MODEL", ""),
            "path": os.environ.get("SAM_PATH", ""),
        },
    },
    # Optional self-hosted OpenAI-compatible server (vLLM, llama.cpp, Ollama...) for open-weight models.
    "LOCAL": {
        "base_url": os.environ.get("LOCAL_MODEL_BASE_URL", ""),
        "model": os.environ.get("LOCAL_MODEL_NAME", ""),
        "api_key": os.environ.get("LOCAL_MODEL_API_KEY", ""),
    },
    "TEXT_PROVIDER": os.environ.get("TEXT_PROVIDER", "spark"),  # spark | local
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"myapp": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")}},
}
