"""Categorías de productos: crear, modificar y desactivar (RF-08); consultar (RF-33)."""
from __future__ import annotations

from ..db import is_integrity_error, utcnow_str
from ..errors import Conflict, NotFound, ValidationError
from . import audit


def _clean_name(name: str | None) -> str:
    name = " ".join((name or "").split())[:60]
    if len(name) < 2:
        raise ValidationError("Revisa los campos marcados",
                              {"name": "El nombre de la categoría es obligatorio (mínimo 2 caracteres)"})
    return name


def get(conn, category_id: int) -> dict | None:
    return conn.one("SELECT id, name, is_active, created_at FROM categories WHERE id = ?", (category_id,))


def list_all(conn, *, only_active: bool = False) -> list[dict]:
    where = "WHERE c.is_active = 1" if only_active else ""
    return conn.all(
        "SELECT c.id, c.name, c.is_active, c.created_at, "
        "(SELECT COUNT(*) FROM products p WHERE p.category_id = c.id AND p.is_active = 1) AS product_count "
        f"FROM categories c {where} ORDER BY c.is_active DESC, LOWER(c.name)")


def active_choices(conn) -> list[dict]:
    return conn.all("SELECT id, name FROM categories WHERE is_active = 1 ORDER BY LOWER(name)")


def _duplicate(conn, name: str, exclude_id: int | None = None) -> bool:
    sql, params = "SELECT 1 FROM categories WHERE LOWER(name) = LOWER(?)", [name]
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return bool(conn.scalar(sql, params))


def create(conn, name: str, actor: dict) -> int:
    name = _clean_name(name)
    with conn.transaction():
        if _duplicate(conn, name):
            raise Conflict("Ya existe una categoría con ese nombre", {"name": "Ya existe una categoría con este nombre"})
        try:
            category_id = conn.insert(
                "INSERT INTO categories (name, is_active, created_at) VALUES (?, 1, ?)", (name, utcnow_str()))
        except Exception as exc:
            if is_integrity_error(exc):
                raise Conflict("Ya existe una categoría con ese nombre",
                               {"name": "Ya existe una categoría con este nombre"})
            raise
        audit.log(conn, actor, "category.create", "category", category_id, name)
    return category_id


def rename(conn, category_id: int, name: str, actor: dict) -> None:
    name = _clean_name(name)
    with conn.transaction():
        current = get(conn, category_id)
        if not current:
            raise NotFound("La categoría no existe")
        if _duplicate(conn, name, category_id):
            raise Conflict("Ya existe una categoría con ese nombre", {"name": "Ya existe una categoría con este nombre"})
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
        audit.log(conn, actor, "category.update", "category", category_id, f"{current['name']} -> {name}")


def set_active(conn, category_id: int, active: bool, actor: dict) -> None:
    with conn.transaction():
        current = get(conn, category_id)
        if not current:
            raise NotFound("La categoría no existe")
        if not active:
            in_use = conn.scalar("SELECT COUNT(*) FROM products WHERE category_id = ? AND is_active = 1",
                                 (category_id,))
            if in_use:
                raise ValidationError(
                    f"No se puede desactivar: tiene {in_use} producto(s) activo(s). Reasígnalos o desactívalos primero.")
        conn.execute("UPDATE categories SET is_active = ? WHERE id = ?", (1 if active else 0, category_id))
        audit.log(conn, actor, "category.activate" if active else "category.deactivate", "category", category_id,
                  current["name"])
