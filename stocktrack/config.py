"""Configuración de StockTrack, leída de variables de entorno."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def load_config() -> dict:
    """Devuelve la configuración leyendo el entorno en el momento de la llamada."""
    env = os.environ.get("STOCKTRACK_ENV", "development").lower()
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        if env == "production":
            raise RuntimeError("SECRET_KEY es obligatoria cuando STOCKTRACK_ENV=production")
        secret = "dev-only-insecure-secret-key"

    default_db = f"sqlite:///{BASE_DIR / 'instance' / 'stocktrack.db'}"
    alert_to = [e.strip() for e in os.environ.get("ALERT_EMAIL_TO", "").split(",") if e.strip()]

    return {
        "ENV": env,
        "SECRET_KEY": secret,
        "DATABASE_URL": os.environ.get("DATABASE_URL", default_db),
        "COMPANY_NAME": os.environ.get("COMPANY_NAME", "Tienda de Electrónicos, Monterrey"),
        "TIMEZONE": os.environ.get("TIMEZONE", "America/Monterrey"),
        # Restricción del proyecto: máximo de registros activos (productos activos).
        "MAX_ACTIVE_RECORDS": _int("MAX_ACTIVE_RECORDS", 100_000),
        "PAGE_SIZE": _int("PAGE_SIZE", 25),
        # Sesiones y seguridad
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=_int("SESSION_HOURS", 8)),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _bool(os.environ.get("SESSION_COOKIE_SECURE"), env == "production"),
        "PASSWORD_MIN_LENGTH": _int("PASSWORD_MIN_LENGTH", 8),
        "LOGIN_MAX_ATTEMPTS": _int("LOGIN_MAX_ATTEMPTS", 5),
        "LOGIN_LOCK_SECONDS": _int("LOGIN_LOCK_SECONDS", 300),
        # Reportes
        "REPORT_PDF_MAX_ROWS": _int("REPORT_PDF_MAX_ROWS", 5_000),
        # Correo de alertas
        "MAIL_ENABLED": _bool(os.environ.get("MAIL_ENABLED"), False),
        "MAIL_HOST": os.environ.get("MAIL_HOST", "localhost"),
        "MAIL_PORT": _int("MAIL_PORT", 587),
        "MAIL_USER": os.environ.get("MAIL_USER", ""),
        "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD", ""),
        "MAIL_USE_TLS": _bool(os.environ.get("MAIL_USE_TLS"), True),
        "MAIL_USE_SSL": _bool(os.environ.get("MAIL_USE_SSL"), False),
        "MAIL_FROM": os.environ.get("MAIL_FROM", "StockTrack <alertas@stocktrack.local>"),
        "MAIL_TIMEOUT": _int("MAIL_TIMEOUT", 10),
        "MAIL_ASYNC": _bool(os.environ.get("MAIL_ASYNC"), True),
        "ALERT_EMAIL_TO": alert_to,
    }
