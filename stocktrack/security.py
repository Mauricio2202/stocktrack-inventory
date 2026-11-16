"""Autenticación, permisos por rol, protección CSRF y control de intentos de acceso."""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

ALL_ROLES = ("admin", "encargado", "consulta")
STAFF = ("admin", "encargado")

# Matriz de permisos (requerimientos por usuario): permiso -> roles que lo tienen.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "dashboard.view": ALL_ROLES,                 # RF-02, RF-18, RF-30
    "products.view": ALL_ROLES,                  # RF-05, RF-19, RF-31..32, RF-34
    "products.edit": ("admin",),                 # RF-06, RF-07, RF-09
    "categories.view": ALL_ROLES,                # RF-33
    "categories.edit": ("admin",),               # RF-08
    "movements.view": STAFF,                     # RF-10, RF-23
    "movements.create": ("encargado",),          # RF-20..22: lo registra el encargado
    "reservations.validate": ("admin",),         # RF-16
    "alerts.view": STAFF,                        # RF-11, RF-24
    "alerts.attend": ("encargado",),             # RF-25
    "reports.view": STAFF,                       # RF-12, RF-26
    "reports.admin": ("admin",),                 # RF-13: diarios, mensuales, reservas, devoluciones
    "users.manage": ("admin",),                  # RF-03, RF-04
    "audit.view": ("admin",),                    # RF-15
}


def can(perm: str, user: dict | None = None) -> bool:
    user = user if user is not None else g.get("user")
    return bool(user) and user["role"] in PERMISSIONS.get(perm, ())


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user["must_change_password"] and request.endpoint not in ("auth.change_password", "auth.logout"):
            flash("Debes cambiar tu contraseña antes de continuar.", "warning")
            return redirect(url_for("auth.change_password"))
        return view(*args, **kwargs)
    return wrapper


def permission_required(perm: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not can(perm):
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


# --- CSRF ----------------------------------------------------------------------
def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def check_csrf() -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf") or ""
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Token CSRF inválido o ausente. Recarga la página e inténtalo de nuevo.")


def safe_next(target: str | None) -> str | None:
    """Solo se aceptan redirecciones internas (evita open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


# --- límite de intentos de acceso ---------------------------------------------
class LoginThrottle:
    """Bloquea temporalmente tras demasiados intentos fallidos (por usuario y por IP).
    Es en memoria: con varios procesos de aplicación cada uno lleva su propio conteo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str, window: int) -> list[float]:
        cutoff = time.monotonic() - window
        fails = [t for t in self._fails.get(key, []) if t > cutoff]
        self._fails[key] = fails
        return fails

    def is_locked(self, keys: list[str], max_attempts: int, window: int) -> bool:
        with self._lock:
            return any(len(self._recent(k, window)) >= max_attempts for k in keys)

    def failure(self, keys: list[str], window: int) -> None:
        with self._lock:
            for key in keys:
                self._recent(key, window).append(time.monotonic())

    def reset(self, keys: list[str]) -> None:
        with self._lock:
            for key in keys:
                self._fails.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._fails.clear()
