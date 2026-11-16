"""Categorías: consulta (todos los roles) y alta/modificación/desactivación (administrador) · RF-08, RF-33."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..deps import actor, get_db
from ..errors import NotFound, ValidationError
from ..models import categories
from ..security import permission_required

bp = Blueprint("categories", __name__, url_prefix="/categorias")


@bp.get("")
@permission_required("categories.view")
def index():
    return render_template("categories/list.html", rows=categories.list_all(get_db()), errors={}, values={})


@bp.post("")
@permission_required("categories.edit")
def create():
    conn = get_db()
    values = {"name": request.form.get("name", "")}
    try:
        categories.create(conn, values["name"], actor())
    except ValidationError as exc:
        return render_template("categories/list.html", rows=categories.list_all(conn),
                               errors=exc.errors or {"name": exc.message}, values=values), 422
    flash("Categoría creada.", "success")
    return redirect(url_for("categories.index"))


@bp.post("/<int:category_id>/renombrar")
@permission_required("categories.edit")
def rename(category_id: int):
    try:
        categories.rename(get_db(), category_id, request.form.get("name", ""), actor())
        flash("Categoría actualizada.", "success")
    except (NotFound, ValidationError) as exc:
        flash(exc.message if isinstance(exc, ValidationError) else str(exc), "error")
    return redirect(url_for("categories.index"))


@bp.post("/<int:category_id>/estado")
@permission_required("categories.edit")
def toggle(category_id: int):
    active = request.form.get("active") == "1"
    try:
        categories.set_active(get_db(), category_id, active, actor())
        flash("Categoría activada." if active else "Categoría desactivada.", "success")
    except (NotFound, ValidationError) as exc:
        flash(exc.message if isinstance(exc, ValidationError) else str(exc), "error")
    return redirect(url_for("categories.index"))
