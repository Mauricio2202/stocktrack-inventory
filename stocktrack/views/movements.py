"""Movimientos: historial (admin y encargado), registro (encargado) y validación de reservas (administrador)."""
from __future__ import annotations

import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..deps import actor, get_db, int_arg, paginate
from ..errors import NotFound, ValidationError
from ..models import products, stock
from ..security import permission_required
from ..services import mailer
from ..timeutil import local_range_to_utc, parse_date

bp = Blueprint("movements", __name__, url_prefix="/movimientos")


@bp.get("")
@permission_required("movements.view")
def index():
    conn = get_db()
    tzname = current_app.config["TIMEZONE"]
    sku = (request.args.get("sku") or "").strip()
    kind = request.args.get("tipo") or ""
    status = request.args.get("estado") or ""
    date_from, date_to = parse_date(request.args.get("desde")), parse_date(request.args.get("hasta"))
    product = products.get_by_sku(conn, sku) if sku else None
    start_utc, end_utc = local_range_to_utc(date_from, date_to, tzname)
    per_page = current_app.config["PAGE_SIZE"]
    page = int_arg("page", 1)
    if sku and not product:
        rows, total = [], 0
        flash(f"No existe un producto con SKU «{sku}».", "warning")
    else:
        rows, total = stock.list_movements(conn, product_id=product["id"] if product else None,
                                           kind=kind or None, status=status or None, start_utc=start_utc, end_utc=end_utc,
                                           page=page, per_page=per_page)
    return render_template("movements/list.html", rows=rows, pager=paginate(total, page, per_page),
                           args={"sku": sku, "tipo": kind, "estado": status, "desde": request.args.get("desde", ""),
                                 "hasta": request.args.get("hasta", "")},
                           kinds=stock.KIND_LABELS, statuses=stock.STATUS_LABELS)


@bp.route("/nuevo", methods=["GET", "POST"])
@permission_required("movements.create")
def create():
    conn = get_db()
    values = {"sku": (request.args.get("sku") or "").strip().upper(), "kind": request.args.get("tipo", "compra"),
              "quantity": "", "reference": "", "notes": ""}
    errors: dict[str, str] = {}
    product = None
    if request.method == "POST":
        values = {k: (request.form.get(k) or "").strip() for k in ("sku", "kind", "quantity", "reference", "notes")}
        values["request_key"] = (request.form.get("request_key") or "").strip()
        values["sku"] = values["sku"].upper()
    if values["sku"]:
        product = products.get_by_sku(conn, values["sku"])
    if request.method == "POST":
        try:
            if not product:
                raise ValidationError("Producto no encontrado", {"sku": "No existe un producto con ese SKU"})
            result = stock.register_movement(conn, product["id"], values["kind"], values["quantity"], actor(),
                                             values["reference"], values["notes"],
                                             request_key=values.get("request_key") or None)
        except NotFound as exc:
            errors["sku"] = str(exc)
        except ValidationError as exc:
            errors = exc.errors or {"quantity": exc.message}
            flash(exc.message, "error")
        else:
            if result["duplicate"]:
                flash("Este movimiento ya estaba registrado; no se duplicó.", "warning")
            elif result["status"] == "pendiente":
                flash(f"Reserva registrada para {result['sku']} ({result['quantity']} unidades). "
                      "Queda pendiente de validación del administrador.", "success")
            else:
                flash(f"Movimiento registrado: {result['sku']} pasó de {result['stock_before']} a "
                      f"{result['stock_after']} unidades.", "success")
            if result["new_alert_id"]:
                flash(f"⚠ {result['name']} quedó en escasez. Se generó una alerta y se notificó al equipo.", "warning")
                mailer.dispatch_alert(conn_db(), current_app.config, result["new_alert_id"])
            return redirect(url_for("products.detail", product_id=result["product_id"]))
    values.setdefault("request_key", "")
    if not values["request_key"] or not errors:  # clave nueva por formulario; se conserva si hubo error
        values["request_key"] = secrets.token_urlsafe(24)
    return render_template("movements/form.html", values=values, errors=errors, product=product,
                           kinds=stock.KIND_LABELS), (422 if errors else 200)


@bp.get("/reservas")
@permission_required("reservations.validate")
def reservations():
    """RF-16: cola de reservas de segundo nivel por validar."""
    rows, _ = stock.list_movements(get_db(), kind="reserva", status="pendiente", per_page=200)
    return render_template("movements/reservations.html", rows=rows)


@bp.post("/<int:movement_id>/validar")
@permission_required("reservations.validate")
def validate(movement_id: int):
    approve = request.form.get("decision") == "approve"
    try:
        stock.validate_reservation(get_db(), movement_id, approve, actor(), request.form.get("note"))
        flash("Reserva validada: las unidades salieron del inventario." if approve
              else "Reserva rechazada: las unidades quedaron libres otra vez.", "success")
    except (NotFound, ValidationError) as exc:
        flash(exc.message if isinstance(exc, ValidationError) else str(exc), "error")
    return redirect(url_for("movements.reservations"))


def conn_db():
    """Objeto Database (no la conexión de la petición): el envío de correo usa su propia conexión."""
    return current_app.extensions["stocktrack_db"]
