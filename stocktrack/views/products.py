"""Catálogo de productos: consulta/búsqueda (todos los roles); alta, edición y desactivación (administrador)."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from ..deps import actor, get_db, int_arg, paginate
from ..errors import LimitExceeded, NotFound, ValidationError
from ..models import audit, categories, products, stock
from ..security import can, permission_required

bp = Blueprint("products", __name__, url_prefix="/productos")


def _list_args() -> dict:
    status = request.args.get("estado", "active")
    return {
        "q": (request.args.get("q") or "").strip()[:80],
        "category": (request.args.get("categoria") or "").strip() if (request.args.get("categoria") or "").strip().isdigit() else "",
        "status": status if status in ("active", "inactive", "all") else "active",
        "low_only": request.args.get("escasez") == "1",
        "sort": request.args.get("orden", "name"),
        "direction": "desc" if request.args.get("dir") == "desc" else "asc",
    }


@bp.get("")
@permission_required("products.view")
def index():
    conn = get_db()
    args = _list_args()
    per_page = current_app.config["PAGE_SIZE"]
    page = int_arg("page", 1)
    rows, total = products.search(conn, page=page, per_page=per_page, **args)
    pager = paginate(total, page, per_page)
    if pager["page"] != page:  # página fuera de rango: se vuelve a consultar la última
        rows, total = products.search(conn, page=pager["page"], per_page=per_page, **args)
    return render_template("products/list.html", rows=rows, pager=pager, args=args,
                           categories=categories.list_all(conn),
                           active_count=products.count_active(conn),
                           max_active=current_app.config["MAX_ACTIVE_RECORDS"])


@bp.get("/sugerencias")
@permission_required("products.view")
def suggestions():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(products.suggestions(get_db(), q))


@bp.route("/nuevo", methods=["GET", "POST"])
@permission_required("products.edit")
def create():
    conn = get_db()
    values, errors = {}, {}
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            data = products.clean_form(request.form, with_initial_stock=True)
            product_id = products.create(conn, data, actor(), current_app.config["MAX_ACTIVE_RECORDS"])
        except LimitExceeded as exc:
            flash(exc.message, "error")
            return render_template("products/form.html", values=values, errors={}, product=None,
                                   categories=categories.active_choices(conn)), 409
        except ValidationError as exc:
            errors = exc.errors
            flash(exc.message, "error")
        else:
            flash("Producto creado correctamente.", "success")
            return redirect(url_for("products.detail", product_id=product_id))
    return render_template("products/form.html", values=values, errors=errors, product=None,
                           categories=categories.active_choices(conn)), (422 if errors else 200)


@bp.get("/<int:product_id>")
@permission_required("products.view")
def detail(product_id: int):
    conn = get_db()
    product = products.get(conn, product_id)
    if not product:
        return render_template("error.html", code=404, title="Página no encontrada",
                               message="El producto no existe."), 404
    staff = can("movements.view")  # el usuario de consulta solo ve existencias, no movimientos ni bitácora
    movements, total = stock.list_movements(conn, product_id=product_id, per_page=15) if staff else ([], 0)
    history = audit.recent(conn, limit=10, entity="product", entity_id=product_id) if can("audit.view") else []
    return render_template("products/detail.html", product=product, movements=movements,
                           movement_total=total, history=history,
                           kinds=stock.KIND_LABELS, statuses=stock.STATUS_LABELS)


@bp.route("/<int:product_id>/editar", methods=["GET", "POST"])
@permission_required("products.edit")
def edit(product_id: int):
    conn = get_db()
    product = products.get(conn, product_id)
    if not product:
        return render_template("error.html", code=404, title="Página no encontrada",
                               message="El producto no existe."), 404
    values = {
        "sku": product["sku"], "name": product["name"], "description": product["description"] or "",
        "category_id": product["category_id"] or "", "brand": product["brand"] or "",
        "location": product["location"] or "", "min_stock": product["min_stock"],
        "cost": f"{product['cost_cents'] / 100:.2f}", "price": f"{product['price_cents'] / 100:.2f}",
    }
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            data = products.clean_form(request.form)
            products.update(conn, product_id, data, actor())
        except ValidationError as exc:
            errors = exc.errors
            flash(exc.message, "error")
        else:
            flash("Producto actualizado.", "success")
            return redirect(url_for("products.detail", product_id=product_id))
    return render_template("products/form.html", values=values, errors=errors, product=product,
                           categories=categories.active_choices(conn)), (422 if errors else 200)


@bp.post("/<int:product_id>/desactivar")
@permission_required("products.edit")
def deactivate(product_id: int):
    try:
        products.deactivate(get_db(), product_id, actor())
        flash("Producto desactivado. Su historial se conserva y ya no cuenta como registro activo.", "success")
    except (NotFound, ValidationError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.post("/<int:product_id>/activar")
@permission_required("products.edit")
def restore(product_id: int):
    try:
        products.restore(get_db(), product_id, actor(), current_app.config["MAX_ACTIVE_RECORDS"])
        flash("Producto activado.", "success")
    except LimitExceeded as exc:
        flash(exc.message, "error")
    except NotFound as exc:
        flash(str(exc), "error")
    return redirect(url_for("products.detail", product_id=product_id))
