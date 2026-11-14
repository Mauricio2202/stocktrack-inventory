"""Capa de Vista (V de MVT): rutas HTTP organizadas en blueprints."""
from __future__ import annotations


def register(app) -> None:
    from . import alerts, audit, auth, dashboard, movements, products, reports, users

    for module in (auth, dashboard, products, movements, alerts, reports, users, audit):
        app.register_blueprint(module.bp)
