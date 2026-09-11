"""
Django settings for BORDER SENTINEL - AI-Based Fake Identity & Document
Screening System.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # .../border_sentinel
PROJECT_ROOT = BASE_DIR.parent                             # repo root

SECRET_KEY = "django-insecure-demo-key-border-sentinel-2026-do-not-use-in-prod"

DEBUG = True

# The platform live-preview proxies arbitrary hosts; accept them all in demo mode.
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["https://*.e2b.app", "http://*.e2b.app",
                        "https://*.ngrok-free.app", "https://*.ngrok.io",
                        "https://*.ngrok.app"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "screening.apps.ScreeningConfig",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.JSONParser",
    ],
}

# --------------------------------------------------------------------------
# BORDER SENTINEL engine configuration
# --------------------------------------------------------------------------
SCREENING_MODELS_DIR = BASE_DIR / "screening" / "models"   # ONNX face models
DEMO_ASSETS_DIR = PROJECT_ROOT / "demo_assets"

# SFace cosine similarity threshold (OpenCV zoo documented value).
SFACE_MATCH_THRESHOLD = 0.363
# Classical descriptor cosine threshold used when the ONNX model is absent.
CLASSICAL_MATCH_THRESHOLD = 0.80

# Risk banding
RISK_LOW_MAX = 30
RISK_MEDIUM_MAX = 60

DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# --------------------------------------------------------------------------
# MySQL identity verification database (read-only)
# --------------------------------------------------------------------------
import os

IDENTITY_DB = {
    "host": os.environ.get("IDENTITY_DB_HOST", "localhost"),
    "user": os.environ.get("IDENTITY_DB_USER", "root"),
    "password": os.environ.get("IDENTITY_DB_PASSWORD", "4310"),
    "database": os.environ.get("IDENTITY_DB_NAME", "identity_screening"),
    "port": int(os.environ.get("IDENTITY_DB_PORT", "3306")),
}

# --------------------------------------------------------------------------
# Email verification (passport screening only)
# --------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "ar.harish2008@gmail.com")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "sutgftsntblaxyoz")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "ar.harish2008@gmail.com")

# Verification token expiry in seconds (default 10 minutes)
EMAIL_VERIFICATION_EXPIRY = int(os.environ.get("EMAIL_VERIFICATION_EXPIRY", "600"))
