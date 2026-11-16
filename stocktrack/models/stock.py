"""Movimientos de inventario (RF-18..22, RF-12, RF-16, RNF-15..17, RNF-25..26).

Tipos:
  compra      Entrada por Compra: suma al stock.
  venta       Salida por Venta: resta; exige disponibilidad suficiente.
  devolucion  Salida por Devolución: resta (devolución al proveedor); exige disponibilidad.
  reserva     Reserva de Stock (Segundo Nivel): el encargado la solicita, retiene unidades
              (`reserved`) y queda 'pendiente' hasta que el administrador la valida (RF-16).
              Al validar, las unidades salen del stock y se registra el movimiento aplicado
              (hijo, con parent_id); al rechazar, se liberan.

Invariantes (verificadas en las pruebas):
  products.stock    = SUM(delta) de movimientos con status 'aplicado'
  products.reserved = SUM(quantity) de reservas 'pendiente'
  disponible = stock - reserved >= 0
"""
from __future__ import annotations

from ..db import is_integrity_error, utcnow_str
from ..errors import Conflict, NotFound, ValidationError
from . import alerts, audit

KINDS = ("compra", "venta", "devolucion", "reserva")
KIND_LABELS = {
    "compra": "Entrada por Compra",
    "venta": "Salida por Venta",
    "devolucion": "Salida por Devolución",
    "reserva": "Reserva de Stock (Segundo Nivel)",
}
STATUS_LABELS = {"aplicado": "Aplicado", "pendiente": "Pendiente de validación",
                 "validado": "Validado", "rechazado": "Rechazado"}
MAX_QUANTITY = 1_000_000


def _parse_quantity(quantity) -> int:
    try:
        qty = int(str(quantity).strip())
    except (TypeError, ValueError):
        raise ValidationError("Revisa los datos del movimiento",
                              {"quantity": "La cantidad debe ser un número entero"})
    if qty < 1:
        raise ValidationError("Revisa los datos del movimiento", {"quantity": "La cantidad debe ser al menos 1"})
    if qty > MAX_QUANTITY:
        raise ValidationError("Revisa los datos del movimiento",
                              {"quantity": f"La cantidad máxima por movimiento es {MAX_QUANTITY:,}"})
    return qty


def _result(conn, movement_id: int, **extra) -> dict:
    row = conn.one(
        "SELECT m.id, m.kind, m.status, m.quantity, m.stock_before, m.stock_after, p.id AS product_id, "
        "p.sku, p.name FROM stock_movements m JOIN products p ON p.id = m.product_id WHERE m.id = ?",
        (movement_id,))
    return {"movement_id": movement_id, "product_id": row["product_id"], "sku": row["sku"],
            "name": row["name"], "kind": row["kind"], "status": row["status"], "quantity": row["quantity"],
            "stock_before": row["stock_before"], "stock_after": row["stock_after"],
            "new_alert_id": None, "duplicate": False, **extra}


def register_movement(conn, product_id: int, kind: str, quantity, actor: dict,
                      reference: str | None = None, notes: str | None = None,
                      request_key: str | None = None) -> dict:
    """Registra un movimiento de forma atómica. `request_key` evita duplicados por reenvío (RNF-15)."""
    if kind not in KINDS:
        raise ValidationError("Revisa los datos del movimiento", {"kind": "Tipo de movimiento inválido"})
    qty = _parse_quantity(quantity)
    reference = (reference or "").strip()[:60] or None
    notes = (notes or "").strip()[:300] or None
    request_key = (request_key or "").strip()[:64] or None

    if request_key:
        existing = conn.scalar("SELECT id FROM stock_movements WHERE request_key = ?", (request_key,))
        if existing:
            return _result(conn, existing, duplicate=True)

    try:
        with conn.transaction():
            product = conn.one(
                "SELECT id, sku, name, stock, reserved, is_active FROM products WHERE id = ?" + conn.for_update,
                (product_id,))
            if not product:
                raise NotFound("El producto no existe")
            if not product["is_active"]:
                raise ValidationError("El producto está desactivado; actívalo antes de mover inventario")

            stock, reserved = product["stock"], product["reserved"]
            available = stock - reserved
            status, delta, new_stock, new_reserved = "aplicado", 0, stock, reserved
            if kind == "compra":
                delta = qty
            else:
                if qty > available:
                    detail = f"Solo hay {available} unidades disponibles"
                    if reserved:
                        detail += f" ({reserved} reservadas)"
                    raise ValidationError("Stock insuficiente", {"quantity": detail})
                if kind == "reserva":
                    status, new_reserved = "pendiente", reserved + qty
                else:
                    delta = -qty
            new_stock = stock + delta
            now = utcnow_str()
            conn.execute("UPDATE products SET stock = ?, reserved = ?, updated_at = ? WHERE id = ?",
                         (new_stock, new_reserved, now, product_id))
            movement_id = conn.insert(
                "INSERT INTO stock_movements (product_id, user_id, kind, status, quantity, delta, stock_before, "
                "stock_after, reference, notes, request_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (product_id, actor.get("id"), kind, status, qty, delta, stock, new_stock,
                 reference, notes, request_key, now))
            audit.log(conn, actor, f"stock.{kind}", "product", product_id,
                      f"{product['sku']}: {stock} -> {new_stock}" + (f" (reserva pendiente +{qty})" if status == "pendiente" else ""))
            new_alert_id = alerts.evaluate_product(conn, product_id)
    except Exception as exc:
        if request_key and is_integrity_error(exc):  # carrera entre dos envíos idénticos
            existing = conn.scalar("SELECT id FROM stock_movements WHERE request_key = ?", (request_key,))
            if existing:
                return _result(conn, existing, duplicate=True)
        raise
    return _result(conn, movement_id, new_alert_id=new_alert_id)


def validate_reservation(conn, movement_id: int, approve: bool, actor: dict, note: str | None = None) -> dict:
    """RF-16: el administrador aprueba (sale del stock) o rechaza (se libera) una reserva pendiente."""
    note = (note or "").strip()[:300] or None
    if not approve and not note:
        raise ValidationError("Indica el motivo del rechazo", {"note": "El motivo es obligatorio al rechazar"})
    with conn.transaction():
        res = conn.one("SELECT id, product_id, kind, status, quantity, reference FROM stock_movements WHERE id = ?",
                       (movement_id,))
        if not res or res["kind"] != "reserva":
            raise NotFound("La reserva no existe")
        product = conn.one("SELECT id, sku, stock, reserved FROM products WHERE id = ?" + conn.for_update,
                           (res["product_id"],))
        cur = conn.execute(
            "UPDATE stock_movements SET status = ?, validated_by = ?, validated_at = ?, validation_note = ? "
            "WHERE id = ? AND status = 'pendiente'",
            ("validado" if approve else "rechazado", actor.get("id"), utcnow_str(), note, movement_id))
        if cur.rowcount == 0:
            raise Conflict("La reserva ya fue validada o rechazada por otro usuario")
        qty, now = res["quantity"], utcnow_str()
        child_id = None
        if approve:
            new_stock, new_reserved = product["stock"] - qty, product["reserved"] - qty
            child_id = conn.insert(
                "INSERT INTO stock_movements (product_id, user_id, kind, status, quantity, delta, stock_before, "
                "stock_after, reference, notes, parent_id, created_at) "
                "VALUES (?, ?, 'reserva', 'aplicado', ?, ?, ?, ?, ?, ?, ?, ?)",
                (res["product_id"], actor.get("id"), qty, -qty, product["stock"], new_stock, res["reference"],
                 f"Reserva #{movement_id} validada", movement_id, now))
        else:
            new_stock, new_reserved = product["stock"], product["reserved"] - qty
        conn.execute("UPDATE products SET stock = ?, reserved = ?, updated_at = ? WHERE id = ?",
                     (new_stock, new_reserved, now, res["product_id"]))
        audit.log(conn, actor, "reservation.approve" if approve else "reservation.reject", "stock_movement",
                  movement_id, f"{product['sku']} x{qty}" + (f" · {note}" if note else ""))
        new_alert_id = alerts.evaluate_product(conn, res["product_id"])
    return {"movement_id": movement_id, "child_id": child_id, "approved": approve, "new_alert_id": new_alert_id}


def pending_reservations_count(conn) -> int:
    return int(conn.scalar("SELECT COUNT(*) FROM stock_movements WHERE kind = 'reserva' AND status = 'pendiente'") or 0)


def _filters(product_id=None, kind=None, status=None, start_utc=None, end_utc=None):
    where, params = [], []
    if product_id:
        where.append("m.product_id = ?")
        params.append(product_id)
    if kind in KINDS:
        where.append("m.kind = ?")
        params.append(kind)
    if status in STATUS_LABELS:
        where.append("m.status = ?")
        params.append(status)
    if start_utc:
        where.append("m.created_at >= ?")
        params.append(start_utc)
    if end_utc:
        where.append("m.created_at < ?")
        params.append(end_utc)
    return ("WHERE " + " AND ".join(where)) if where else "", params


_SELECT = (
    "SELECT m.id, m.created_at, m.kind, m.status, m.quantity, m.delta, m.stock_before, m.stock_after, "
    "m.reference, m.notes, m.parent_id, m.validated_at, m.validation_note, p.id AS product_id, p.sku, "
    "p.name AS product_name, COALESCE(u.full_name, 'Sistema') AS user_name, "
    "v.full_name AS validated_by_name "
    "FROM stock_movements m JOIN products p ON p.id = m.product_id "
    "LEFT JOIN users u ON u.id = m.user_id LEFT JOIN users v ON v.id = m.validated_by"
)


def list_movements(conn, *, product_id=None, kind=None, status=None, start_utc=None, end_utc=None,
                   page: int = 1, per_page: int = 25):
    where, params = _filters(product_id, kind, status, start_utc, end_utc)
    total = int(conn.scalar(f"SELECT COUNT(*) FROM stock_movements m {where}", params) or 0)
    rows = conn.all(
        f"{_SELECT} {where} ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?",
        params + [per_page, max(page - 1, 0) * per_page])
    return rows, total


def iter_movements(conn, *, product_id=None, kind=None, status=None, start_utc=None, end_utc=None):
    where, params = _filters(product_id, kind, status, start_utc, end_utc)
    return conn.iter_rows(f"{_SELECT} {where} ORDER BY m.created_at, m.id", params)


def count_movements(conn, **filters) -> int:
    where, params = _filters(**filters)
    return int(conn.scalar(f"SELECT COUNT(*) FROM stock_movements m {where}", params) or 0)
