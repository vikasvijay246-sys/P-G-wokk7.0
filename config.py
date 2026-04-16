"""
config.py — Environment-based configuration.

Usage:
    FLASK_ENV=production flask run
    FLASK_ENV=development flask run   (default)
"""
import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY     = os.environ.get("SECRET_KEY",     "pg-manager-dev-secret-CHANGE-IN-PROD")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "pg-jwt-secret-CHANGE-IN-PROD")
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(days=7)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # ── Files ─────────────────────────────────────────────────────────────────
    UPLOAD_FOLDER       = os.path.join(BASE_DIR, "static", "uploads")
    MAX_CONTENT_LENGTH  = 20 * 1024 * 1024   # 20 MB hard limit
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    ALLOWED_FILE_EXTENSIONS  = {
        "pdf", "png", "jpg", "jpeg", "webp", "gif",
        "doc", "docx", "mp4", "mov", "webm", "3gp",
    }

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # Detect dead connections before use
        "pool_recycle":  300,    # Recycle connections every 5 min
        "pool_timeout":  20,
        "max_overflow":  10,
    }

    # ── SMS provider (OTP) ────────────────────────────────────────────────────
    # Set SMS_PROVIDER=twilio and TWILIO_SID/TWILIO_AUTH/TWILIO_FROM in env
    SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "console")


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'pg_manager.db')}"
    )
    # Verbose SQLAlchemy queries in development
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    DEBUG   = False
    TESTING = False

    _db_url = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'pg_manager.db')}"
    )
    # Render provides postgres:// — SQLAlchemy requires postgresql://
    if _db_url and _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    SQLALCHEMY_ECHO = False

    # Stricter secrets in production
    @classmethod
    def validate(cls):
        if cls.SECRET_KEY == "pg-manager-dev-secret-CHANGE-IN-PROD":
            raise RuntimeError("SECRET_KEY must be set in production!")
        if cls.JWT_SECRET_KEY == "pg-jwt-secret-CHANGE-IN-PROD":
            raise RuntimeError("JWT_SECRET_KEY must be set in production!")


class TestingConfig(Config):
    TESTING = True
    DEBUG   = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    WTF_CSRF_ENABLED = False


_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development").lower()
    cfg = _CONFIG_MAP.get(env, DevelopmentConfig)
    if env == "production" and hasattr(cfg, "validate"):
        cfg.validate()
    return cfg
