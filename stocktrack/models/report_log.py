"""Registro de reportes emitidos: folio consecutivo y huella SHA-256 (RF-13, RF-27: foliado e incorruptible).

"Incorruptible" se implementa como *evidencia de alteración*: al emitir un reporte se guarda la huella
SHA-256 del archivo exacto entregado. Con la página de verificación se comprueba si un PDF/Excel
presentado después coincide byte a byte con el original; cualquier modificación cambia la huella.
Además el PDF sale con permisos de edición bloqueados y el Excel con las hojas protegidas.
"""
from __future__ import annotations

import hashlib
import json

from ..db import utcnow_str
from ..errors import NotFound


def reserve(conn, *, report_type: str, fmt: str, title: str, params: dict, user_id: int | None) -> dict:
    """Asigna el folio (consecutivo, sin huecos entre emitidos salvo errores registrados)."""
    with conn.transaction():
        now = utcnow_str()
        row_id = conn.insert(
            "INSERT INTO report_log (report_type, format, title, params, generated_by, generated_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'generando')",
            (report_type, fmt, title, json.dumps(params, ensure_ascii=False, sort_keys=True), user_id, now))
        folio = f"ST-{now[:4]}-{row_id:06d}"
        conn.execute("UPDATE report_log SET folio = ? WHERE id = ?", (folio, row_id))
    return {"id": row_id, "folio": folio, "generated_at": now}


def finalize(conn, row_id: int, content: bytes, row_count: int) -> str:
    digest = hashlib.sha256(content).hexdigest()
    with conn.transaction():
        conn.execute("UPDATE report_log SET status = 'emitido', sha256 = ?, size_bytes = ?, row_count = ? "
                     "WHERE id = ?", (digest, len(content), row_count, row_id))
    return digest


def fail(conn, row_id: int, detail: str) -> None:
    with conn.transaction():
        conn.execute("UPDATE report_log SET status = 'error', error_detail = ? WHERE id = ?",
                     (detail[:300], row_id))


def verify(conn, content: bytes) -> dict | None:
    """Devuelve el registro del reporte original si la huella coincide; None si no."""
    digest = hashlib.sha256(content).hexdigest()
    row = conn.one(
        "SELECT r.id, r.folio, r.report_type, r.format, r.title, r.row_count, r.generated_at, r.sha256, "
        "u.full_name AS generated_by_name FROM report_log r LEFT JOIN users u ON u.id = r.generated_by "
        "WHERE r.sha256 = ? AND r.status = 'emitido'", (digest,))
    return row


def get_by_folio(conn, folio: str) -> dict:
    row = conn.one("SELECT * FROM report_log WHERE folio = ?", ((folio or "").strip().upper(),))
    if not row:
        raise NotFound("No existe un reporte con ese folio")
    return row


def recent(conn, limit: int = 30) -> list[dict]:
    return conn.all(
        "SELECT r.id, r.folio, r.report_type, r.format, r.title, r.row_count, r.generated_at, r.status, "
        "r.sha256, u.full_name AS generated_by_name FROM report_log r "
        "LEFT JOIN users u ON u.id = r.generated_by ORDER BY r.id DESC LIMIT ?", (limit,))
