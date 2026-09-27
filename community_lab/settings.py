"""Dedicated local demo settings. Never import the production settings or .env."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "synthetic-community-lab-local-only-not-a-production-secret"
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
INSTALLED_APPS = ["community_lab"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
ROOT_URLCONF = "community_lab.urls"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "community_lab", "USER": "community_demo", "PASSWORD": "",
    "HOST": "/private/tmp/jokesfor-communities/pgsocket", "PORT": "55437",
    "CONN_MAX_AGE": 0,
}}
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
COMMUNITY_LAB_ENABLED = True
CSRF_TRUSTED_ORIGINS = ["http://localhost:5187", "http://127.0.0.1:5187"]
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_NAME = "community_lab_csrf"
DATA_UPLOAD_MAX_MEMORY_SIZE = 4096
SECURE_CONTENT_TYPE_NOSNIFF = True
APPEND_SLASH = True
