import os

import dj_database_url

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS: list[str] = []
ROOT_URLCONF = "shop.urls"
DATABASES = {"default": dj_database_url.config()}
