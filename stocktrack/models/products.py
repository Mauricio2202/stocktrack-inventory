"""Productos del inventario: validación, alta/edición/archivo, búsqueda y estadísticas."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Mapping

from ..db import is_integrity_error, utcnow_str
from ..errors import Conflict, LimitExceeded, NotFound, ValidationError
from . import alerts, audit, stock

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,39}$")
MONEY_RE = re.compile(r"\d+(\.\d+)?|\.\d+")
LOCK_KEY = 70001  # clave del bloqueo consultivo que protege el conteo de registros activos
MAX_UNITS = 10_000_000
MAX_MONEY_CENTS = 9_999_999_999  # $99,999,999.99

SORTS = {
    "sku": "sku", "name": "name", "category": "category", "stock": "stock",
    "price": "price_cents", "updated": "updated_at",
}
COLUMNS = ("id, sku, name, description, category, brand, location, stock, min_stock, "
           "cost_cents, price_cents, is_active, created_at, updated_at")


def parse_money(text, label: str) -> int:
    raw = str(text or "").strip().replace(",", "").replace("$", "")
    if raw == "":
        return 0
    if raw.startswith("-"):
        raise ValueError(f"{label} no puede ser negativo")
    # Solo dígitos con punto decimal opcional: rechaza notación científica, NaN e Infinity.
    if not MONEY_RE.fullmatch(raw) or len(raw) > 20:
        raise ValueError(f"{label} debe ser un monto válido, por ejemplo 1299.90")
    try:
        amount = Decimal(raw)
    except InvalidOperation:  # pragma: no cover - el patrón ya lo impide
        raise ValueError(f"{label} debe ser un monto válido, por ejemplo 1299.90")
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents > MAX_MONEY_CENTS:
        raise ValueError(f"{label} es demasiado grande")
    return cents


def _parse_units(text, label: str) -> int:
    raw = str(text or "").strip()
    if raw == "":
        return 0
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{label} debe ser un número entero")
    if value < 0 or value > MAX_UNITS:
        raise ValueError(f"{label} debe estar entre 0 y {MAX_UNITS:,}")
    return value


def clean_form(form: Mapping, *, with_initial_stock: bool = False) -> dict:
    """Valida y normaliza los datos de un producto. Lanza ValidationError con errores por campo."""
    errors: dict[str, str] = {}

    def text(key: str, limit: int) -> str:
        return (form.get(key) or "").strip()[:limit]

    sku = text("sku", 40).upper()
    if not SKU_RE.match(sku):
        errors["sku"] = "El SKU debe tener 2-40 caracteres: letras, números, punto, guion o guion bajo"
    name = text("name", 120)
    if len(name) < 2:
        errors["name"] = "El nombre es obligatorio (mínimo 2 caracteres)"

    data = {
        "sku": sku, "name": name,
        "description": text("description", 500) or None,
        "category": text("category", 60) or None,
        "brand": text("brand", 60) or None,
        "location": text("location", 60) or None,
    }
    for field, label in (("min_stock", "El stock mínimo"),):
        try:
            data[field] = _parse_units(form.get(field), label)
        except ValueError as exc:
            errors[field] = str(exc)
    for field, label in (("cost", "El costo"), ("price", "El precio")):
        try:
            data[f"{field}_cents"] = parse_money(form.get(field), label)
        except ValueError as exc:
            errors[field] = str(exc)
    if with_initial_stock:
        try:
            data["initial_stock"] = _parse_units(form.get("initial_stock"), "El stock inicial")
        except ValueError as exc:
            errors["initial_stock"] = str(exc)
    if errors:
        raise ValidationError("Revisa los campos marcados", errors)
    return data


# --- consultas -----------------------------------------------------------------
def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(q="", category="", status="active", low_only=False):
    where, params = [], []
    if status == "active":
        where.append("is_active = 1")
    elif status == "archived":
        where.append("is_active = 0")
    if q:
        like = f"%{_escape_like(q.strip().lower())}%"
        where.append("(LOWER(sku) LIKE ? ESCAPE '\\' OR LOWER(name) LIKE ? ESCAPE '\\' "
                     "OR LOWER(COALESCE(brand, '')) LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if category:
        where.append("category = ?")
        params.append(category)
    if low_only:
        where.append("min_stock > 0 AND stock <= min_stock")
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _decorate(row: dict) -> dict:
    row["is_low"] = alerts.is_low(row["stock"], row["min_stock"])
    return row


def search(conn, *, q="", category="", status="active", low_only=False,
           sort="name", direction="asc", page=1, per_page=25):
    where, params = _filters(q, category, status, low_only)
    total = int(conn.scalar(f"SELECT COUNT(*) FROM products {where}", params) or 0)
    order = f"{SORTS.get(sort, 'name')} {'DESC' if direction == 'desc' else 'ASC'}, id ASC"
    rows = conn.all(
        f"SELECT {COLUMNS} FROM products {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per_page, max(page - 1, 0) * per_page],
    )
    return [_decorate(r) for r in rows], total


def iter_for_report(conn, *, category="", low_only=False):
    where, params = _filters("", category, "active", low_only)
    return conn.iter_rows(
        f"SELECT {COLUMNS} FROM products {where} ORDER BY COALESCE(category, ''), name, id", params)


def count_for_report(conn, *, category="", low_only=False) -> int:
    where, params = _filters("", category, "active", low_only)
    return int(conn.scalar(f"SELECT COUNT(*) FROM products {where}", params) or 0)


def get(conn, product_id: int) -> dict | None:
    row = conn.one(f"SELECT {COLUMNS} FROM products WHERE id = ?", (product_id,))
    return _decorate(row) if row else None


def get_by_sku(conn, sku: str) -> dict | None:
    row = conn.one(f"SELECT {COLUMNS} FROM products WHERE sku = ?", ((sku or "").strip().upper(),))
    return _decorate(row) if row else None


def suggestions(conn, q: str, limit: int = 8) -> list[dict]:
    rows, _ = search(conn, q=q, per_page=limit, sort="sku")
    return [{"id": r["id"], "sku": r["sku"], "name": r["name"], "stock": r["stock"]} for r in rows]


def categories(conn) -> list[str]:
    rows = conn.all("SELECT DISTINCT category FROM products WHERE is_active = 1 AND category IS NOT NULL "
                    "AND category <> '' ORDER BY category")
    return [r["category"] for r in rows]


def count_active(conn) -> int:
    return int(conn.scalar("SELECT COUNT(*) FROM products WHERE is_active = 1") or 0)


# --- escritura -----------------------------------------------------------------
def _check_capacity(conn, max_active: int) -> None:
    active = count_active(conn)
    if active >= max_active:
        raise LimitExceeded(
            f"Se alcanzó la capacidad máxima de {max_active:,} registros activos. "
            "Archiva productos que ya no se manejan para poder agregar nuevos.")


def create(conn, data: dict, actor: dict, max_active: int) -> int:
    with conn.transaction():
        conn.advisory_lock(LOCK_KEY)
        _check_capacity(conn, max_active)
        if conn.scalar("SELECT 1 FROM products WHERE sku = ?", (data["sku"],)):
            raise Conflict("Ya existe un producto con ese SKU", {"sku": "Este SKU ya está registrado"})
        now = utcnow_str()
        try:
            product_id = conn.insert(
                "INSERT INTO products (sku, name, description, category, brand, location, stock, min_stock, "
                "cost_cents, price_cents, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 1, ?, ?)",
                (data["sku"], data["name"], data.get("description"), data.get("category"),
                 data.get("brand"), data.get("location"), data["min_stock"], data["cost_cents"],
                 data["price_cents"], now, now),
            )
        except Exception as exc:
            if is_integrity_error(exc):
                raise Conflict("Ya existe un producto con ese SKU", {"sku": "Este SKU ya está registrado"})
            raise
        audit.log(conn, actor, "product.create", "product", product_id, f"{data['sku']} · {data['name']}")
        initial = int(data.get("initial_stock") or 0)
        if initial > 0:
            stock.register_movement(conn, product_id, "entrada", initial, actor,
                                    reference="ALTA", notes="Stock inicial")
        else:
            alerts.evaluate_product(conn, product_id)
    return product_id


_TRACKED = ("sku", "name", "description", "category", "brand", "location", "min_stock",
            "cost_cents", "price_cents")


def update(conn, product_id: int, data: dict, actor: dict) -> None:
    with conn.transaction():
        current = conn.one(f"SELECT {COLUMNS} FROM products WHERE id = ?" + conn.for_update, (product_id,))
        if not current:
            raise NotFound("El producto no existe")
        clash = conn.scalar("SELECT id FROM products WHERE sku = ? AND id <> ?", (data["sku"], product_id))
        if clash:
            raise Conflict("Ya existe un producto con ese SKU", {"sku": "Este SKU ya está registrado"})
        changes = [f"{f}: {current[f]!r} -> {data[f]!r}" for f in _TRACKED if current[f] != data[f]]
        if not changes:
            return
        conn.execute(
            "UPDATE products SET sku = ?, name = ?, description = ?, category = ?, brand = ?, location = ?, "
            "min_stock = ?, cost_cents = ?, price_cents = ?, updated_at = ? WHERE id = ?",
            (data["sku"], data["name"], data.get("description"), data.get("category"), data.get("brand"),
             data.get("location"), data["min_stock"], data["cost_cents"], data["price_cents"],
             utcnow_str(), product_id),
        )
        audit.log(conn, actor, "product.update", "product", product_id, "; ".join(changes))
        alerts.evaluate_product(conn, product_id)


def archive(conn, product_id: int, actor: dict) -> None:
    with conn.transaction():
        cur = conn.execute("UPDATE products SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1",
                           (utcnow_str(), product_id))
        if cur.rowcount == 0:
            raise NotFound("El producto no existe o ya está archivado")
        audit.log(conn, actor, "product.archive", "product", product_id)
        alerts.evaluate_product(conn, product_id)  # resuelve su alerta vigente


def restore(conn, product_id: int, actor: dict, max_active: int) -> None:
    with conn.transaction():
        conn.advisory_lock(LOCK_KEY)
        _check_capacity(conn, max_active)
        cur = conn.execute("UPDATE products SET is_active = 1, updated_at = ? WHERE id = ? AND is_active = 0",
                           (utcnow_str(), product_id))
        if cur.rowcount == 0:
            raise NotFound("El producto no existe o ya está activo")
        audit.log(conn, actor, "product.restore", "product", product_id)
        alerts.evaluate_product(conn, product_id)


# --- panel principal -----------------------------------------------------------
def dashboard_stats(conn) -> dict:
    totals = conn.one(
        "SELECT COUNT(*) AS products, COALESCE(SUM(stock), 0) AS units, "
        "COALESCE(SUM(stock * cost_cents), 0) AS cost_cents, "
        "COALESCE(SUM(stock * price_cents), 0) AS value_cents, "
        "COALESCE(SUM(CASE WHEN min_stock > 0 AND stock <= min_stock THEN 1 ELSE 0 END), 0) AS low_count, "
        "COALESCE(SUM(CASE WHEN stock = 0 THEN 1 ELSE 0 END), 0) AS out_count "
        "FROM products WHERE is_active = 1"
    )
    by_category = conn.all(
        "SELECT COALESCE(category, 'Sin categoría') AS category, COUNT(*) AS products, "
        "COALESCE(SUM(stock), 0) AS units FROM products WHERE is_active = 1 "
        "GROUP BY COALESCE(category, 'Sin categoría') ORDER BY units DESC, category LIMIT 8"
    )
    low = conn.all(
        f"SELECT {COLUMNS} FROM products WHERE is_active = 1 AND min_stock > 0 AND stock <= min_stock "
        "ORDER BY (stock * 1.0 / min_stock) ASC, name ASC LIMIT 8"
    )
    return {"totals": totals, "by_category": by_category, "low": [_decorate(r) for r in low]}
