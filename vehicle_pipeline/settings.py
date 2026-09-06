"""
Django settings for the Vehicle Pipeline web app.

This app is a thin web UI wrapped around your EXISTING pipeline code
(modules.database, modules.matcher, modules.gemini_service, modules.enricher,
modules.excel_processor, modules.excel_handler, modules.batch_resolver, config.py).

Copy your existing `modules/` package and `config.py` into this project's
root directory (next to manage.py) so they can be imported unchanged.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------
# SECURITY - change this before deploying anywhere public
# -----------------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# -----------------------------------------------------------------------
# Apps
# -----------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pipeline",
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

ROOT_URLCONF = "vehicle_pipeline.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "pipeline" / "templates"],
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

WSGI_APPLICATION = "vehicle_pipeline.wsgi.application"
ASGI_APPLICATION = "vehicle_pipeline.asgi.application"

# -----------------------------------------------------------------------
# Database used ONLY for tracking upload jobs in this web app (sqlite).
# This is separate from the SQL Server database your pipeline writes
# vehicle facts/master data into via modules.database.Database and
# processor.persist_to_database() - that connection is configured inside
# your own config.py / modules/database.py, unchanged.
# -----------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------
# Paths your pipeline modules rely on (mirrors the standalone script's
# `data/master_data.json` and `data/low_confidence.json`). Adjust to
# match your config.py if it defines these already.
# -----------------------------------------------------------------------
MASTER_DATA_PATH = str(BASE_DIR / "data" / "master_data.json")
LOW_CONFIDENCE_PATH = str(BASE_DIR / "data" / "low_confidence.json")

# Max upload size guard (50 MB) - tune as needed
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
