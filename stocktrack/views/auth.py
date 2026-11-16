"""Inicio y cierre de sesión, cambio de contraseña."""
from __future__ import annotations

import time

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from ..deps import actor, get_db
from ..errors import ValidationError
from ..models import audit
from ..models import users as users_model
from ..security import login_required, safe_next

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    cfg = current_app.config
    throttle = current_app.extensions["login_throttle"]
    next_url = safe_next(request.values.get("next"))
    if request.method == "POST":
        email = users_model.normalize_email(request.form.get("email"))[:120]
        password = request.form.get("password") or ""
        ip = request.remote_addr or "?"
        user_key, ip_key = f"user:{email}", f"ip:{ip}"
        window, limit = cfg["LOGIN_LOCK_SECONDS"], cfg["LOGIN_MAX_ATTEMPTS"]
        if throttle.is_locked([user_key], limit, window) or throttle.is_locked([ip_key], limit * 4, window):
            flash(f"Demasiados intentos fallidos. Espera {window // 60 or 1} minuto(s) e inténtalo otra vez.", "error")
            return render_template("login.html", next_url=next_url, email=email), 429
        conn = get_db()
        user = users_model.authenticate(conn, email, password)
        if user:
            throttle.reset([user_key, ip_key])
            session.clear()
            session["uid"] = user["id"]
            session.permanent = True
            session["last_seen"] = time.time()
            users_model.record_login(conn, user["id"])
            with conn.transaction():
                audit.log(conn, {"id": user["id"], "email": user["email"], "ip": ip}, "auth.login")
            return redirect(next_url or url_for("dashboard.index"))
        throttle.failure([user_key, ip_key], window)
        with conn.transaction():
            audit.log(conn, {"id": None, "email": email or None, "ip": ip}, "auth.login_failed")
        flash("Correo o contraseña incorrectos.", "error")
        return render_template("login.html", next_url=next_url, email=email), 401
    return render_template("login.html", next_url=next_url, email="")


@bp.post("/logout")
@login_required
def logout():
    conn = get_db()
    with conn.transaction():
        audit.log(conn, actor(), "auth.logout")
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/cuenta/password", methods=["GET", "POST"])
@login_required
def change_password():
    errors: dict[str, str] = {}
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        conn = get_db()
        if not check_password_hash(g.user["password_hash"], current):
            errors["current_password"] = "La contraseña actual no es correcta"
        elif new != confirm:
            errors["confirm_password"] = "La confirmación no coincide"
        elif check_password_hash(g.user["password_hash"], new):
            errors["new_password"] = "La nueva contraseña debe ser distinta a la actual"
        else:
            try:
                users_model.set_password(conn, g.user["id"], new, must_change=False,
                                         min_length=current_app.config["PASSWORD_MIN_LENGTH"], actor=actor())
            except ValidationError as exc:
                errors.update(exc.errors or {"new_password": exc.message})
            else:
                flash("Contraseña actualizada.", "success")
                return redirect(url_for("dashboard.index"))
    return render_template("account/password.html", errors=errors,
                           min_length=current_app.config["PASSWORD_MIN_LENGTH"]), (400 if errors else 200)
