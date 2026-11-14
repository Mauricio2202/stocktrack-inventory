"""Dependencias compartidas por las vistas: conexión a la BD, actor de auditoría y paginación."""
from __future__ import annotations

import math

from flask import current_app, g, request


def get_db():
    """Conexión a la base de datos ligada a la petición actual."""
    if "db" not in g:
        g.db = current_app.extensions["stocktrack_db"].connect()
    return g.db


def close_db(exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        if exc is not None:
            conn.rollback()
        conn.close()


def actor() -> dict:
    user = g.get("user")
    return {"id": user["id"] if user else None,
            "username": user["username"] if user else None,
            "ip": request.remote_addr}


def int_arg(name: str, default: int = 1, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(value, minimum)
    return min(value, maximum) if maximum is not None else value


def paginate(total: int, page: int, per_page: int) -> dict:
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    start = 0 if total == 0 else (page - 1) * per_page + 1
    return {"page": page, "pages": pages, "total": total, "per_page": per_page,
            "start": start, "end": min(page * per_page, total),
            "has_prev": page > 1, "has_next": page < pages}
