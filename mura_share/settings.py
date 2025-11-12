from pathlib import Path
import os
from datetime import timedelta

# ─────────────────────────────────────────────────────────
# 基本
# ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# 開発中は True、デプロイ時は False に
DEBUG = True

# ローカル開発用
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# そのままでも動きますが、環境変数からも拾えるように
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-this-in-production-please"
)

# ─────────────────────────────────────────────────────────
# アプリ
# ─────────────────────────────────────────────────────────
INSTALLED_APPS = [
    # Django標準
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # 追加（API/認証/スキーマ/CORS/フィルタ）
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",

    # 自作アプリ
    "marketplace",
    "chat",
    "notifications",
    "accounts",
]

# ─────────────────────────────────────────────────────────
# ミドルウェア（CORSはできるだけ先頭付近）
# ─────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mura_share.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # 必要なら templates フォルダを作成
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

WSGI_APPLICATION = "mura_share.wsgi.application"
ASGI_APPLICATION = "mura_share.asgi.application"  # Channels導入時にも使えます

# ─────────────────────────────────────────────────────────
# DB（まずはSQLiteで最速起動。PostgreSQLにするならここを差し替え）
# ─────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# 例：PostgreSQL にする場合
# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": os.getenv("POSTGRES_DB", "mura_share"),
#         "USER": os.getenv("POSTGRES_USER", "postgres"),
#         "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
#         "HOST": os.getenv("POSTGRES_HOST", "localhost"),
#         "PORT": os.getenv("POSTGRES_PORT", "5432"),
#     }
# }

# ─────────────────────────────────────────────────────────
# パスワードバリデータ（デフォルト）
# ─────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─────────────────────────────────────────────────────────
# i18n / tz
# ─────────────────────────────────────────────────────────
LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True  # DBはUTC、表示はAsia/TokyoでOK

# ─────────────────────────────────────────────────────────
# 静的/メディア
# ─────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic 用（本番）
# 開発で追加の静的ファイルを置くなら
# STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─────────────────────────────────────────────────────────
# CORS（フロント別ドメイン想定・開発はゆるめ）
# ─────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True
# 本番は CORS_ALLOWED_ORIGINS に限定
# CORS_ALLOWED_ORIGINS = [
#     "https://your-frontend.example.com",
# ]

# ─────────────────────────────────────────────────────────
# DRF / JWT / OpenAPI
# ─────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# SimpleJWT（デフォルトのままでも動きます。期限を調整したい場合だけ）
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MURAシェア API",
    "DESCRIPTION": "Graduation Project API (Django + DRF)",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ─────────────────────────────────────────────────────────
# ここから先は必要に応じて（S3, Email等）
# ─────────────────────────────────────────────────────────
# 例：S3アップロードに切替えるなら（django-storages[boto3]）
# INSTALLED_APPS += ["storages"]
# DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
# AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
# AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
# AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "")
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/products/'  # ログイン後に移動するページ（お好みで）
LOGOUT_REDIRECT_URL = '/login/'
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # ← 追加
