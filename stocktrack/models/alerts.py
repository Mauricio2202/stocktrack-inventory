"""Alertas de escasez y notificaciones internas.

Regla: un producto activo con umbral mínimo > 0 está en escasez cuando stock <= mínimo.
Mientras siga en escasez existe UNA sola alerta vigente (abierta o reconocida); al reponer
el stock por encima del mínimo, la alerta se resuelve sola.
"""
from __future__ import annotations

from ..db import utcnow_str
from ..errors import NotFound
from . import audit

NOTIFY_ROLES = ("admin", "gerente", "almacenista")
VIGENTES = "('abierta','reconocida')"


def is_low(stock: int, min_stock: int) -> bool:
    return min_stock > 0 and stock <= min_stock


def _notify(conn, alert_id: int, product: dict) -> None:
    message = (f"Stock bajo: {product['name']} ({product['sku']}) tiene "
               f"{product['stock']} unidades; el mínimo es {product['min_stock']}.")
    users = conn.all(
        "SELECT id FROM users WHERE is_active = 1 AND role IN ('admin','gerente','almacenista')"
    )
    now = utcnow_str()
    conn.executemany(
        "INSERT INTO notifications (user_id, alert_id, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
        [(u["id"], alert_id, message, now) for u in users],
    )


def evaluate_product(conn, product_id: int) -> int | None:
    """Crea o resuelve la alerta de un producto. Devuelve el id si se creó una alerta nueva.
    Debe llamarse dentro de la transacción que modificó el producto."""
    p = conn.one(
        "SELECT id, sku, name, stock, min_stock, is_active FROM products WHERE id = ?", (product_id,)
    )
    if not p:
        return None
    current = conn.one(
        f"SELECT id FROM stock_alerts WHERE product_id = ? AND status IN {VIGENTES}", (product_id,)
    )
    low = p["is_active"] == 1 and is_low(p["stock"], p["min_stock"])
    if low and not current:
        alert_id = conn.insert(
            "INSERT INTO stock_alerts (product_id, status, stock_at_alert, min_stock_at_alert, created_at) "
            "VALUES (?, 'abierta', ?, ?, ?)",
            (product_id, p["stock"], p["min_stock"], utcnow_str()),
        )
        _notify(conn, alert_id, p)
        return alert_id
    if not low and current:
        conn.execute(
            "UPDATE stock_alerts SET status = 'resuelta', resolved_at = ? WHERE id = ?",
            (utcnow_str(), current["id"]),
        )
    return None


def scan_all(conn) -> list[int]:
    """Revisión completa (tarea programada): crea alertas faltantes y resuelve las obsoletas."""
    new_ids: list[int] = []
    with conn.transaction():
        missing = conn.all(
            "SELECT p.id FROM products p WHERE p.is_active = 1 AND p.min_stock > 0 AND p.stock <= p.min_stock "
            f"AND NOT EXISTS (SELECT 1 FROM stock_alerts a WHERE a.product_id = p.id AND a.status IN {VIGENTES}) "
            "ORDER BY p.id"
        )
        for row in missing:
            alert_id = evaluate_product(conn, row["id"])
            if alert_id:
                new_ids.append(alert_id)
        stale = conn.all(
            f"SELECT a.product_id AS id FROM stock_alerts a JOIN products p ON p.id = a.product_id "
            f"WHERE a.status IN {VIGENTES} AND (p.is_active = 0 OR p.min_stock = 0 OR p.stock > p.min_stock)"
        )
        for row in stale:
            evaluate_product(conn, row["id"])
    return new_ids


def get_context(conn, alert_id: int) -> dict | None:
    """Alerta + datos del producto, para armar el correo."""
    return conn.one(
        "SELECT a.id, a.status, a.created_at, a.stock_at_alert, a.min_stock_at_alert, "
        "p.id AS product_id, p.sku, p.name, p.category, p.location, p.stock, p.min_stock "
        "FROM stock_alerts a JOIN products p ON p.id = a.product_id WHERE a.id = ?",
        (alert_id,),
    )


def email_recipients(conn, extra: list[str] | None = None) -> list[str]:
    rows = conn.all(
        "SELECT email FROM users WHERE is_active = 1 AND receive_alerts = 1 "
        "AND email IS NOT NULL AND email <> ''"
    )
    seen, result = set(), []
    for email in [r["email"] for r in rows] + list(extra or []):
        key = email.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(email.strip())
    return result


def set_email_result(conn, alert_id: int, status: str, detail: str | None) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE stock_alerts SET email_status = ?, email_detail = ?, email_sent_at = ? WHERE id = ?",
            (status, (detail or "")[:300] or None, utcnow_str() if status == "enviado" else None, alert_id),
        )


def open_count(conn) -> int:
    return int(conn.scalar(f"SELECT COUNT(*) FROM stock_alerts WHERE status IN {VIGENTES}") or 0)


def list_alerts(conn, status: str = "vigentes", page: int = 1, per_page: int = 25):
    where, params = "", []
    if status == "vigentes":
        where = f"WHERE a.status IN {VIGENTES}"
    elif status in ("abierta", "reconocida", "resuelta"):
        where, params = "WHERE a.status = ?", [status]
    total = int(conn.scalar(f"SELECT COUNT(*) FROM stock_alerts a {where}", params) or 0)
    rows = conn.all(
        "SELECT a.*, p.sku, p.name, p.stock AS current_stock, p.min_stock AS current_min, "
        "u.full_name AS ack_name FROM stock_alerts a JOIN products p ON p.id = a.product_id "
        f"LEFT JOIN users u ON u.id = a.acknowledged_by {where} "
        "ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?",
        params + [per_page, max(page - 1, 0) * per_page],
    )
    return rows, total


def acknowledge(conn, alert_id: int, actor: dict) -> None:
    with conn.transaction():
        cur = conn.execute(
            "UPDATE stock_alerts SET status = 'reconocida', acknowledged_by = ?, acknowledged_at = ? "
            "WHERE id = ? AND status = 'abierta'",
            (actor.get("id"), utcnow_str(), alert_id),
        )
        if cur.rowcount == 0:
            raise NotFound("La alerta no existe o ya no está abierta")
        audit.log(conn, actor, "alert.acknowledge", "stock_alert", alert_id)


# --- notificaciones internas ---------------------------------------------------
def unread_count(conn, user_id: int) -> int:
    return int(conn.scalar(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)) or 0)


def list_notifications(conn, user_id: int, limit: int = 20) -> list[dict]:
    return conn.all(
        "SELECT id, alert_id, message, is_read, created_at FROM notifications "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))


def mark_all_read(conn, user_id: int) -> None:
    with conn.transaction():
        conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user_id,))
