"""
Django settings for Sagaz Django Example.

Run with: python manage.py runserver
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-sagaz-example-key-do-not-use-in-production"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "orders",  # Our example app
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    # Use the native Sagaz middleware for correlation ID propagation
    "sagaz.integrations.django.SagaDjangoMiddleware",  # <-- Native middleware!
]

ROOT_URLCONF = "config.urls"

# Database - SQLite for simplicity
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Sagaz Configuration
SAGAZ = {
    "STORAGE_URL": os.environ.get("SAGAZ_STORAGE_URL", "memory://"),
    "BROKER_URL": os.environ.get("SAGAZ_BROKER_URL", None),
    "METRICS": True,
    "LOGGING": True,
}

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
