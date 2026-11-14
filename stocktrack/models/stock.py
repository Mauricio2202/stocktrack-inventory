"""Movimientos de inventario: entradas, salidas y ajustes con trazabilidad completa."""
from __future__ import annotations

from ..db import utcnow_str
from ..errors import NotFound, ValidationError
from . import alerts, audit

KINDS = ("entrada", "salida", "ajuste")
KIND_LABELS = {"entrada": "Entrada", "salida": "Salida", "ajuste": "Ajuste (conteo físico)"}
MAX_QUANTITY = 1_000_000


def register_movement(conn, product_id: int, kind: str, quantity, actor: dict,
                      reference: str | None = None, notes: str | None = None) -> dict:
    """Registra un movimiento de forma atómica.

    * entrada: suma `quantity` al stock.
    * salida: resta `quantity`; falla si no alcanza el stock (nunca queda negativo).
    * ajuste: fija el stock en `quantity` (conteo físico).
    Devuelve el detalle e `new_alert_id` si el movimiento disparó una alerta nueva.
    """
    errors: dict[str, str] = {}
    if kind not in KINDS:
        errors["kind"] = "Tipo de movimiento inválido"
    try:
        qty = int(str(quantity).strip())
    except (TypeError, ValueError):
        qty = None
        errors["quantity"] = "La cantidad debe ser un número entero"
    if qty is not None:
        minimum = 0 if kind == "ajuste" else 1
        if qty < minimum:
            errors["quantity"] = ("La cantidad contada no puede ser negativa" if kind == "ajuste"
                                  else "La cantidad debe ser al menos 1")
        elif qty > MAX_QUANTITY:
            errors["quantity"] = f"La cantidad máxima por movimiento es {MAX_QUANTITY:,}"
    reference = (reference or "").strip()[:60] or None
    notes = (notes or "").strip()[:300] or None
    if errors:
        raise ValidationError("Revisa los datos del movimiento", errors)

    with conn.transaction():
        product = conn.one(
            "SELECT id, sku, name, stock, min_stock, is_active FROM products WHERE id = ?" + conn.for_update,
            (product_id,),
        )
        if not product:
            raise NotFound("El producto no existe")
        if not product["is_active"]:
            raise ValidationError("El producto está archivado; restáuralo antes de mover inventario")

        before = product["stock"]
        if kind == "entrada":
            after = before + qty
        elif kind == "salida":
            after = before - qty
            if after < 0:
                raise ValidationError(
                    "Stock insuficiente", {"quantity": f"Solo hay {before} unidades disponibles"})
        else:
            after = qty
            if after == before:
                raise ValidationError(
                    "El conteo coincide con el stock actual", {"quantity": "No hay diferencia que ajustar"})
        now = utcnow_str()
        conn.execute("UPDATE products SET stock = ?, updated_at = ? WHERE id = ?", (after, now, product_id))
        movement_id = conn.insert(
            "INSERT INTO stock_movements (product_id, user_id, kind, quantity, delta, stock_before, "
            "stock_after, reference, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_id, actor.get("id"), kind, qty, after - before, before, after, reference, notes, now),
        )
        audit.log(conn, actor, f"stock.{kind}", "product", product_id,
                  f"{product['sku']}: {before} -> {after}")
        new_alert_id = alerts.evaluate_product(conn, product_id)

    return {
        "movement_id": movement_id,
        "product_id": product_id,
        "sku": product["sku"],
        "name": product["name"],
        "stock_before": before,
        "stock_after": after,
        "new_alert_id": new_alert_id,
    }


def _filters(product_id=None, kind=None, start_utc=None, end_utc=None):
    where, params = [], []
    if product_id:
        where.append("m.product_id = ?")
        params.append(product_id)
    if kind in KINDS:
        where.append("m.kind = ?")
        params.append(kind)
    if start_utc:
        where.append("m.created_at >= ?")
        params.append(start_utc)
    if end_utc:
        where.append("m.created_at < ?")
        params.append(end_utc)
    return ("WHERE " + " AND ".join(where)) if where else "", params


_SELECT = (
    "SELECT m.id, m.created_at, m.kind, m.quantity, m.delta, m.stock_before, m.stock_after, "
    "m.reference, m.notes, p.id AS product_id, p.sku, p.name AS product_name, "
    "COALESCE(u.full_name, 'Sistema') AS user_name "
    "FROM stock_movements m JOIN products p ON p.id = m.product_id "
    "LEFT JOIN users u ON u.id = m.user_id"
)


def list_movements(conn, *, product_id=None, kind=None, start_utc=None, end_utc=None,
                   page: int = 1, per_page: int = 25):
    where, params = _filters(product_id, kind, start_utc, end_utc)
    total = int(conn.scalar(f"SELECT COUNT(*) FROM stock_movements m {where}", params) or 0)
    rows = conn.all(
        f"{_SELECT} {where} ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?",
        params + [per_page, max(page - 1, 0) * per_page],
    )
    return rows, total


def iter_movements(conn, *, product_id=None, kind=None, start_utc=None, end_utc=None):
    where, params = _filters(product_id, kind, start_utc, end_utc)
    return conn.iter_rows(f"{_SELECT} {where} ORDER BY m.created_at, m.id", params)


def count_movements(conn, **filters) -> int:
    where, params = _filters(**filters)
    return int(conn.scalar(f"SELECT COUNT(*) FROM stock_movements m {where}", params) or 0)
