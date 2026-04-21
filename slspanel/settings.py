import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")

DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() in ['true', '1', 'yes']

REQUIRE_LOGIN = os.getenv('REQUIRE_LOGIN', 'False').lower() in ['true', '1', 'yes']

USERNAME = os.getenv('USERNAME', 'admin')
PASSWORD = os.getenv('PASSWORD', 'password')

SRT_PUBLISH_PORT = int(os.getenv("SRT_PUBLISH_PORT", 4001))
SRT_PLAYER_PORT = int(os.getenv("SRT_PLAYER_PORT", 4000))
SRTLA_PUBLISH_PORT = int(os.getenv("SRTLA_PUBLISH_PORT", 5000))
SLS_DOMAIN_IP = os.getenv("SLS_DOMAIN_IP", "localhost")
SLS_STATS_DOMAIN_IP = os.getenv("SLS_STATS_DOMAIN_IP", SLS_DOMAIN_IP)
SLS_STATS_PORT = int(os.getenv("SLS_STATS_PORT", 8789))

SLS_API_URL = os.getenv("SLS_API_URL", "http://localhost:8789")
SLS_API_KEY = os.getenv("SLS_API_KEY", "")
PUSH_INTERNAL_TOKEN = os.getenv("PUSH_INTERNAL_TOKEN", "")
SLSPANEL_DB_PATH = os.getenv("SLSPANEL_DB_PATH", "/app/data/db.sqlite3")


def _env_csv(name, default):
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SLSPANEL_ALLOWED_HOSTS = _env_csv(
    "SLSPANEL_ALLOWED_HOSTS",
    f"localhost,127.0.0.1,{SLS_DOMAIN_IP},{SLS_STATS_DOMAIN_IP}",
)
ALLOWED_HOSTS = list(dict.fromkeys(SLSPANEL_ALLOWED_HOSTS))

CSRF_TRUSTED_ORIGINS = _env_csv("SLSPANEL_CSRF_TRUSTED_ORIGINS", "")

SLSPANEL_SECURE_COOKIES = os.getenv("SLSPANEL_SECURE_COOKIES", "False").lower() in ['true', '1', 'yes']
SESSION_COOKIE_SECURE = SLSPANEL_SECURE_COOKIES
CSRF_COOKIE_SECURE = SLSPANEL_SECURE_COOKIES
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.getenv("SLSPANEL_SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.getenv("SLSPANEL_CSRF_COOKIE_SAMESITE", "Lax")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.getenv("SLSPANEL_REFERRER_POLICY", "same-origin")
X_FRAME_OPTIONS = os.getenv("SLSPANEL_X_FRAME_OPTIONS", "DENY")
SECURE_PROXY_SSL_HEADER = None
if os.getenv("SLSPANEL_TRUST_PROXY_SSL_HEADER", "False").lower() in ['true', '1', 'yes']:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SLSPANEL_ENABLE_LOGIN_THROTTLE = os.getenv("SLSPANEL_ENABLE_LOGIN_THROTTLE", "True").lower() in ['true', '1', 'yes']
SLSPANEL_LOGIN_THROTTLE_WINDOW_SECONDS = int(os.getenv("SLSPANEL_LOGIN_THROTTLE_WINDOW_SECONDS", "300"))
SLSPANEL_LOGIN_THROTTLE_MAX_ATTEMPTS = int(os.getenv("SLSPANEL_LOGIN_THROTTLE_MAX_ATTEMPTS", "6"))
SLSPANEL_LOGIN_LOCKOUT_SECONDS = int(os.getenv("SLSPANEL_LOGIN_LOCKOUT_SECONDS", "900"))

USE_I18N = True
USE_L10N = True
LOCALE_PATHS = []
LANGUAGE_CODE = "en"
LANGUAGES = [('en', 'English')]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "streams",
    "django.contrib.humanize",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    'whitenoise.middleware.WhiteNoiseMiddleware',
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "slspanel.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "slspanel.wsgi.application"

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': SLSPANEL_DB_PATH,
    }
}

AUTH_PASSWORD_VALIDATORS = []

TIME_ZONE = os.getenv("TZ", "UTC")
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
