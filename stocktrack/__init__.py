"""StockTrack · Control total de inventarios.

Aplicación monolítica con arquitectura Model-View-Template (Flask + Jinja2):

* Modelo  -> `stocktrack.models`   (reglas de negocio y acceso a datos)
* Vista   -> `stocktrack.views`    (controladores / rutas HTTP)
* Plantilla -> `stocktrack/templates` (HTML renderizado en el servidor)
"""
from __future__ import annotations

import logging
import time

from flask import Flask, flash, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from . import deps, filters, security
from .config import load_config
from .db import Database
from .models import alerts as alerts_model
from .models import stock as stock_model
from .models import users as users_model

__version__ = "2.0.0"


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(load_config())
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = Database(app.config["DATABASE_URL"])
    app.extensions["stocktrack_db"] = db
    app.extensions["login_throttle"] = security.LoginThrottle()
    if app.config.get("AUTO_INIT_DB", True):
        db.init_schema()  # idempotente (CREATE ... IF NOT EXISTS)

    filters.register(app)
    # Globales de Jinja: así también están disponibles dentro de macros importados.
    app.jinja_env.globals.update(csrf_token=security.csrf_token, can=security.can)
    app.teardown_appcontext(deps.close_db)

    @app.before_request
    def load_user():
        g.user = None
        if request.endpoint == "static":
            return
        security.check_csrf()
        user_id = session.get("uid")
        if user_id:
            idle = app.config["SESSION_IDLE_MINUTES"] * 60
            now = time.time()
            if idle and now - session.get("last_seen", now) > idle:
                session.clear()
                flash("Tu sesión se cerró por inactividad. Inicia sesión de nuevo.", "warning")
                return
            if request.endpoint != "idle_ping":
                session["last_seen"] = now
            user = users_model.get(deps.get_db(), user_id)
            if user and user["is_active"]:
                g.user = user
            else:
                session.clear()

    @app.context_processor
    def inject_globals():
        extra = {"can": security.can, "csrf_token": security.csrf_token,
                 "ROLE_LABELS": users_model.ROLE_LABELS, "ROLE_DESCRIPTIONS": users_model.ROLE_DESCRIPTIONS, "app_version": __version__,
                 "open_alerts": 0, "unread_notifications": 0, "pending_reservations": 0,
                 "idle_seconds": app.config["SESSION_IDLE_MINUTES"] * 60}
        if g.get("user"):
            conn = deps.get_db()
            if security.can("alerts.view"):
                extra["open_alerts"] = alerts_model.open_count(conn)
                extra["unread_notifications"] = alerts_model.unread_count(conn, g.user["id"])
            if security.can("reservations.validate"):
                extra["pending_reservations"] = stock_model.pending_reservations_count(conn)
        return extra

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    from . import views
    views.register(app)

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        titles = {400: "Solicitud no válida", 403: "Acceso denegado", 404: "Página no encontrada",
                  405: "Método no permitido", 429: "Demasiados intentos"}
        messages = {403: "Tu rol no tiene permiso para realizar esta acción.",
                    404: "La página o el registro que buscas no existe."}
        return render_template("error.html", code=error.code,
                               title=titles.get(error.code, "Error"),
                               message=messages.get(error.code) or error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        app.logger.exception("Error no controlado")
        return render_template("error.html", code=500, title="Error interno",
                               message="Ocurrió un error inesperado. Ya quedó registrado."), 500

    @app.post("/session/ping")
    def idle_ping():
        """Mantiene viva la sesión cuando el usuario sigue activo en la página (lo llama app.js)."""
        if not g.get("user"):
            return jsonify(status="expired"), 401
        session["last_seen"] = time.time()
        return jsonify(status="ok")

    @app.get("/health")
    def health():
        try:
            deps.get_db().scalar("SELECT 1")
            return jsonify(status="ok", database="ok", version=__version__)
        except Exception:  # pragma: no cover
            return jsonify(status="error", database="unavailable"), 503

    from . import cli
    cli.register(app)
    return app
