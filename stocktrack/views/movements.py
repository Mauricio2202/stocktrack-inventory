"""Movimientos de inventario: historial y registro de entradas, salidas y ajustes."""
from __future__ import annotations

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
                                           kind=kind or None, start_utc=start_utc, end_utc=end_utc,
                                           page=page, per_page=per_page)
    return render_template("movements/list.html", rows=rows, pager=paginate(total, page, per_page),
                           args={"sku": sku, "tipo": kind, "desde": request.args.get("desde", ""),
                                 "hasta": request.args.get("hasta", "")},
                           kinds=stock.KIND_LABELS)


@bp.route("/nuevo", methods=["GET", "POST"])
@permission_required("movements.create")
def create():
    conn = get_db()
    values = {"sku": (request.args.get("sku") or "").strip().upper(), "kind": request.args.get("tipo", "entrada"),
              "quantity": "", "reference": "", "notes": ""}
    errors: dict[str, str] = {}
    product = None
    if request.method == "POST":
        values = {k: (request.form.get(k) or "").strip() for k in ("sku", "kind", "quantity", "reference", "notes")}
        values["sku"] = values["sku"].upper()
    if values["sku"]:
        product = products.get_by_sku(conn, values["sku"])
    if request.method == "POST":
        try:
            if not product:
                raise ValidationError("Producto no encontrado", {"sku": "No existe un producto con ese SKU"})
            result = stock.register_movement(conn, product["id"], values["kind"], values["quantity"], actor(),
                                             values["reference"], values["notes"])
        except NotFound as exc:
            errors["sku"] = str(exc)
        except ValidationError as exc:
            errors = exc.errors or {"quantity": exc.message}
            flash(exc.message, "error")
        else:
            flash(f"Movimiento registrado: {result['sku']} pasó de {result['stock_before']} a "
                  f"{result['stock_after']} unidades.", "success")
            if result["new_alert_id"]:
                flash(f"⚠ {result['name']} quedó en escasez. Se generó una alerta y se notificó al equipo.", "warning")
                mailer.dispatch_alert(conn_db(), current_app.config, result["new_alert_id"])
            return redirect(url_for("products.detail", product_id=result["product_id"]))
    return render_template("movements/form.html", values=values, errors=errors, product=product,
                           kinds=stock.KIND_LABELS), (422 if errors else 200)


def conn_db():
    """Objeto Database (no la conexión de la petición): el envío de correo usa su propia conexión."""
    return current_app.extensions["stocktrack_db"]
