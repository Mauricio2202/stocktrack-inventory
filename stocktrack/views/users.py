"""Administración de usuarios y roles (solo administradores)."""
from __future__ import annotations

import secrets

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from ..deps import actor, get_db
from ..errors import Conflict, NotFound, ValidationError
from ..models import users
from ..security import permission_required

bp = Blueprint("users", __name__, url_prefix="/usuarios")


def _temp_password() -> str:
    return "Tmp" + secrets.token_urlsafe(9).replace("-", "x").replace("_", "y") + "7"


@bp.get("")
@permission_required("users.manage")
def index():
    return render_template("users/list.html", rows=users.list_all(get_db()))


@bp.route("/nuevo", methods=["GET", "POST"])
@permission_required("users.manage")
def create():
    values = {"role": "almacenista"}
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            users.create(get_db(), username=values.get("username", ""), full_name=values.get("full_name", ""),
                         email=values.get("email"), password=values.get("password", ""),
                         role=values.get("role", ""), receive_alerts=values.get("receive_alerts") == "1",
                         must_change_password=values.get("must_change") == "1",
                         min_password_length=current_app.config["PASSWORD_MIN_LENGTH"], actor=actor())
        except (ValidationError, Conflict) as exc:
            errors = exc.errors
            flash(exc.message, "error")
        else:
            flash("Usuario creado.", "success")
            return redirect(url_for("users.index"))
    return render_template("users/form.html", values=values, errors=errors, user=None,
                           roles=users.ROLES), (422 if errors else 200)


@bp.route("/<int:user_id>/editar", methods=["GET", "POST"])
@permission_required("users.manage")
def edit(user_id: int):
    conn = get_db()
    user = users.get(conn, user_id)
    if not user:
        return render_template("error.html", code=404, title="Página no encontrada",
                               message="El usuario no existe."), 404
    values = {"full_name": user["full_name"], "email": user["email"] or "", "role": user["role"],
              "receive_alerts": "1" if user["receive_alerts"] else ""}
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            users.update(conn, user_id, full_name=values.get("full_name", ""), email=values.get("email"),
                         role=values.get("role", ""), receive_alerts=values.get("receive_alerts") == "1",
                         actor=actor())
        except ValidationError as exc:
            errors = exc.errors
            flash(exc.message, "error")
        else:
            flash("Usuario actualizado.", "success")
            return redirect(url_for("users.index"))
    return render_template("users/form.html", values=values, errors=errors, user=user,
                           roles=users.ROLES), (422 if errors else 200)


@bp.post("/<int:user_id>/estado")
@permission_required("users.manage")
def toggle(user_id: int):
    conn = get_db()
    user = users.get(conn, user_id)
    try:
        if not user:
            raise NotFound("El usuario no existe")
        if user["id"] == g.user["id"]:
            raise ValidationError("No puedes desactivar tu propia cuenta")
        users.set_active(conn, user_id, not user["is_active"], actor=actor())
        flash("Usuario activado." if not user["is_active"] else "Usuario desactivado.", "success")
    except (ValidationError, NotFound) as exc:
        flash(getattr(exc, "message", None) or str(exc), "error")
    return redirect(url_for("users.index"))


@bp.post("/<int:user_id>/restablecer")
@permission_required("users.manage")
def reset_password(user_id: int):
    conn = get_db()
    user = users.get(conn, user_id)
    if not user:
        flash("El usuario no existe", "error")
        return redirect(url_for("users.index"))
    temp = _temp_password()
    users.set_password(conn, user_id, temp, must_change=True,
                       min_length=current_app.config["PASSWORD_MIN_LENGTH"], actor=actor())
    flash(f"Contraseña temporal para {user['username']}: {temp} (deberá cambiarla al entrar; "
          "compártela por un canal seguro).", "success")
    return redirect(url_for("users.index"))
