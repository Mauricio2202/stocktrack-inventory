"""Bitácora de auditoría: historial de actividades de los usuarios (RF-15, ISO 9001 §7.5 y §8.5.2)."""
from __future__ import annotations

from ..db import utcnow_str

SYSTEM_ACTOR = {"id": None, "email": "sistema", "ip": None}


def log(conn, actor: dict | None, action: str, entity: str | None = None,
        entity_id: int | None = None, detail: str | None = None) -> None:
    actor = actor or SYSTEM_ACTOR
    conn.execute(
        "INSERT INTO audit_log (user_id, actor, action, entity, entity_id, detail, ip, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (actor.get("id"), actor.get("email"), action, entity, entity_id,
         (detail or "")[:500] or None, actor.get("ip"), utcnow_str()),
    )


def recent(conn, limit: int = 50, entity: str | None = None, entity_id: int | None = None) -> list[dict]:
    where, params = "", []
    if entity:
        where = "WHERE entity = ?"
        params.append(entity)
        if entity_id is not None:
            where += " AND entity_id = ?"
            params.append(entity_id)
    return conn.all(
        f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?", params + [limit]
    )
