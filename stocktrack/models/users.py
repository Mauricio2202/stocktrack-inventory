"""Usuarios, roles y autenticación."""
from __future__ import annotations

import re

from werkzeug.security import check_password_hash, generate_password_hash

from ..db import is_integrity_error, utcnow_str
from ..errors import Conflict, NotFound, ValidationError
from . import audit

ROLES = ("admin", "gerente", "almacenista", "consulta")
ROLE_LABELS = {
    "admin": "Administrador",
    "gerente": "Gerente de inventario",
    "almacenista": "Almacenista",
    "consulta": "Solo consulta",
}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2 = "pbkdf2:sha256:600000"
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing", method="pbkdf2:sha256:600000")
COLUMNS = ("id, username, full_name, email, password_hash, role, is_active, receive_alerts, "
           "must_change_password, created_at, last_login_at")


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=PBKDF2)


def validate_password(password: str, min_length: int = 8) -> None:
    problems = []
    if len(password or "") < min_length:
        problems.append(f"mínimo {min_length} caracteres")
    if not re.search(r"[A-Za-z]", password or ""):
        problems.append("al menos una letra")
    if not re.search(r"\d", password or ""):
        problems.append("al menos un número")
    if problems:
        raise ValidationError("La contraseña no cumple la política: " + ", ".join(problems),
                              {"password": "Requiere " + ", ".join(problems)})


def _clean_profile(full_name: str, email: str | None, role: str) -> tuple[str, str | None]:
    errors = {}
    full_name = (full_name or "").strip()[:100]
    email = (email or "").strip()[:120] or None
    if len(full_name) < 2:
        errors["full_name"] = "El nombre es obligatorio"
    if email and not EMAIL_RE.match(email):
        errors["email"] = "Correo electrónico inválido"
    if role not in ROLES:
        errors["role"] = "Rol inválido"
    if errors:
        raise ValidationError("Revisa los campos marcados", errors)
    return full_name, email


def get(conn, user_id: int) -> dict | None:
    return conn.one(f"SELECT {COLUMNS} FROM users WHERE id = ?", (user_id,))


def get_by_username(conn, username: str) -> dict | None:
    return conn.one(f"SELECT {COLUMNS} FROM users WHERE username = ?", ((username or "").strip().lower(),))


def list_all(conn) -> list[dict]:
    return conn.all(f"SELECT {COLUMNS} FROM users ORDER BY is_active DESC, role, username")


def _active_admins(conn) -> int:
    return int(conn.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1") or 0)


def create(conn, *, username: str, full_name: str, email: str | None, password: str, role: str,
           receive_alerts: bool = False, must_change_password: bool = False,
           min_password_length: int = 8, actor: dict | None = None) -> int:
    username = (username or "").strip().lower()
    full_name, email = _clean_profile(full_name, email, role)
    if not USERNAME_RE.match(username):
        raise ValidationError("Revisa los campos marcados", {
            "username": "Usuario de 3-32 caracteres: minúsculas, números, punto, guion o guion bajo"})
    validate_password(password, min_password_length)
    with conn.transaction():
        if conn.scalar("SELECT 1 FROM users WHERE username = ?", (username,)):
            raise Conflict("El usuario ya existe", {"username": "Este usuario ya existe"})
        try:
            user_id = conn.insert(
                "INSERT INTO users (username, full_name, email, password_hash, role, is_active, receive_alerts, "
                "must_change_password, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (username, full_name, email, hash_password(password), role,
                 1 if receive_alerts else 0, 1 if must_change_password else 0, utcnow_str()),
            )
        except Exception as exc:
            if is_integrity_error(exc):
                raise Conflict("El usuario ya existe", {"username": "Este usuario ya existe"})
            raise
        audit.log(conn, actor, "user.create", "user", user_id, f"{username} ({role})")
    return user_id


def update(conn, user_id: int, *, full_name: str, email: str | None, role: str,
           receive_alerts: bool, actor: dict | None = None) -> None:
    full_name, email = _clean_profile(full_name, email, role)
    with conn.transaction():
        current = get(conn, user_id)
        if not current:
            raise NotFound("El usuario no existe")
        if current["role"] == "admin" and role != "admin" and current["is_active"] and _active_admins(conn) <= 1:
            raise ValidationError("Debe existir al menos un administrador activo",
                                  {"role": "No puedes quitar el rol al último administrador"})
        conn.execute(
            "UPDATE users SET full_name = ?, email = ?, role = ?, receive_alerts = ? WHERE id = ?",
            (full_name, email, role, 1 if receive_alerts else 0, user_id),
        )
        audit.log(conn, actor, "user.update", "user", user_id, f"rol={role}")


def set_active(conn, user_id: int, active: bool, actor: dict | None = None) -> None:
    with conn.transaction():
        current = get(conn, user_id)
        if not current:
            raise NotFound("El usuario no existe")
        if not active and current["role"] == "admin" and current["is_active"] and _active_admins(conn) <= 1:
            raise ValidationError("Debe existir al menos un administrador activo")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
        audit.log(conn, actor, "user.activate" if active else "user.deactivate", "user", user_id)


def set_password(conn, user_id: int, new_password: str, *, must_change: bool = False,
                 min_length: int = 8, actor: dict | None = None) -> None:
    validate_password(new_password, min_length)
    with conn.transaction():
        cur = conn.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
                           (hash_password(new_password), 1 if must_change else 0, user_id))
        if cur.rowcount == 0:
            raise NotFound("El usuario no existe")
        audit.log(conn, actor, "user.password", "user", user_id)


def authenticate(conn, username: str, password: str) -> dict | None:
    """Verifica credenciales. Hace un hash ficticio si el usuario no existe para igualar tiempos."""
    user = get_by_username(conn, username)
    if not user:
        check_password_hash(_DUMMY_HASH, password or "")
        return None
    if not check_password_hash(user["password_hash"], password or ""):
        return None
    if not user["is_active"]:
        return None
    return user


def record_login(conn, user_id: int) -> None:
    with conn.transaction():
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (utcnow_str(), user_id))
