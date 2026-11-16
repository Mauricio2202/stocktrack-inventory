"""Usuarios, roles y autenticación por correo electrónico (RF-01, RF-03, RF-04, RNF-01..03)."""
from __future__ import annotations

import re

from werkzeug.security import check_password_hash, generate_password_hash

from ..db import is_integrity_error, utcnow_str
from ..errors import Conflict, NotFound, ValidationError
from . import audit

ROLES = ("admin", "encargado", "consulta")
ROLE_LABELS = {
    "admin": "Administrador",
    "encargado": "Encargado de inventario",
    "consulta": "Usuario de consulta",
}
ROLE_DESCRIPTIONS = {
    "admin": "Acceso completo",
    "encargado": "Acceso operativo",
    "consulta": "Acceso de solo lectura",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2 = "pbkdf2:sha256:600000"  # RNF-02: hash con sal; nunca se guarda la contraseña
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing", method=PBKDF2)
COLUMNS = ("id, email, full_name, password_hash, role, is_active, receive_alerts, "
           "must_change_password, created_at, last_login_at")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


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


def _clean_profile(full_name: str, email: str | None, role: str) -> tuple[str, str]:
    errors = {}
    full_name = (full_name or "").strip()[:100]
    email = normalize_email(email)[:120]
    if len(full_name) < 2:
        errors["full_name"] = "El nombre es obligatorio"
    if not email:
        errors["email"] = "El correo electrónico es obligatorio"
    elif not EMAIL_RE.match(email):
        errors["email"] = "Escribe un correo válido, por ejemplo nombre@empresa.com"
    if role not in ROLES:
        errors["role"] = "Elige un rol válido"
    if errors:
        raise ValidationError("Revisa los campos marcados", errors)
    return full_name, email


def get(conn, user_id: int) -> dict | None:
    return conn.one(f"SELECT {COLUMNS} FROM users WHERE id = ?", (user_id,))


def get_by_email(conn, email: str) -> dict | None:
    return conn.one(f"SELECT {COLUMNS} FROM users WHERE email = ?", (normalize_email(email),))


def list_all(conn) -> list[dict]:
    return conn.all(f"SELECT {COLUMNS} FROM users ORDER BY is_active DESC, role, email")


def _active_admins(conn) -> int:
    return int(conn.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1") or 0)


def create(conn, *, email: str, full_name: str, password: str, role: str,
           receive_alerts: bool = False, must_change_password: bool = False,
           min_password_length: int = 8, actor: dict | None = None) -> int:
    full_name, email = _clean_profile(full_name, email, role)
    validate_password(password, min_password_length)
    with conn.transaction():
        if conn.scalar("SELECT 1 FROM users WHERE email = ?", (email,)):
            raise Conflict("El correo ya está registrado", {"email": "Ya existe un usuario con este correo"})
        try:
            user_id = conn.insert(
                "INSERT INTO users (email, full_name, password_hash, role, is_active, receive_alerts, "
                "must_change_password, created_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                (email, full_name, hash_password(password), role,
                 1 if receive_alerts else 0, 1 if must_change_password else 0, utcnow_str()),
            )
        except Exception as exc:
            if is_integrity_error(exc):
                raise Conflict("El correo ya está registrado", {"email": "Ya existe un usuario con este correo"})
            raise
        audit.log(conn, actor, "user.create", "user", user_id, f"{email} ({role})")
    return user_id


def update(conn, user_id: int, *, full_name: str, email: str, role: str,
           receive_alerts: bool, actor: dict | None = None) -> None:
    full_name, email = _clean_profile(full_name, email, role)
    with conn.transaction():
        current = get(conn, user_id)
        if not current:
            raise NotFound("El usuario no existe")
        if conn.scalar("SELECT 1 FROM users WHERE email = ? AND id <> ?", (email, user_id)):
            raise Conflict("El correo ya está registrado", {"email": "Ya existe un usuario con este correo"})
        if current["role"] == "admin" and role != "admin" and current["is_active"] and _active_admins(conn) <= 1:
            raise ValidationError("Debe existir al menos un administrador activo",
                                  {"role": "No puedes quitar el rol al último administrador"})
        conn.execute(
            "UPDATE users SET full_name = ?, email = ?, role = ?, receive_alerts = ? WHERE id = ?",
            (full_name, email, role, 1 if receive_alerts else 0, user_id),
        )
        audit.log(conn, actor, "user.update", "user", user_id,
                  f"rol {current['role']} -> {role}" if current["role"] != role else "datos")


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


def authenticate(conn, email: str, password: str) -> dict | None:
    """Verifica correo y contraseña. Hace un hash ficticio si el usuario no existe para igualar tiempos."""
    user = get_by_email(conn, email)
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
