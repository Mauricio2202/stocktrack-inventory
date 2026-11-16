"""Fixtures compartidos y recolector de resultados de las pruebas de aceptación."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from stocktrack import create_app
from stocktrack.models import products, stock, users

from .helpers.web import PASSWORDS

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = Path(os.environ.get("ACCEPTANCE_RESULTS", ROOT / "docs" / "acceptance" / "results.json"))
_results: dict[str, dict] = {}

DEMO_ROLES = {"admin": "admin", "encargado": "encargado", "consulta": "consulta"}


# --------------------------------------------------------------------------- app
@pytest.fixture
def app_config(tmp_path):
    return {
        "TESTING": True,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "SECRET_KEY": "test-secret",
        "MAIL_ENABLED": False,
        "MAIL_ASYNC": False,
        "MAIL_USE_TLS": False,
        "MAIL_TIMEOUT": 3,
        "MAX_ACTIVE_RECORDS": 100_000,
        "PAGE_SIZE": 25,
        "LOGIN_MAX_ATTEMPTS": 5,
        "PASSWORD_MIN_LENGTH": 8,
    }


@pytest.fixture
def app(app_config):
    application = create_app(app_config)
    db = application.extensions["stocktrack_db"]
    conn = db.connect()
    try:
        for username, role in DEMO_ROLES.items():
            users.create(conn, full_name=f"Usuario {username}", email=f"{username}@test.local",
                         password=PASSWORDS[username], role=role,
                         receive_alerts=username in ("admin", "encargado"))
    finally:
        conn.close()
    return application


@pytest.fixture
def db(app):
    return app.extensions["stocktrack_db"]


@pytest.fixture
def conn(db):
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def actor(conn):
    admin = users.get_by_email(conn, "admin@test.local")
    return {"id": admin["id"], "email": "admin@test.local", "ip": "127.0.0.1"}


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def encargado(conn):
    user = users.get_by_email(conn, "encargado@test.local")
    return {"id": user["id"], "email": user["email"], "ip": "127.0.0.1"}


@pytest.fixture
def make_category(conn, actor):
    from stocktrack.models import categories

    def factory(name: str = "Pruebas") -> int:
        row = conn.one("SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (name,))
        return row["id"] if row else categories.create(conn, name, actor)
    return factory


@pytest.fixture
def make_product(conn, actor, app, make_category):
    """Crea productos rápido: make_product('SKU-1', stock=10, min_stock=3)."""
    def factory(sku: str, *, name: str | None = None, stock_qty: int = 0, min_stock: int = 0,
                category: str = "Pruebas", cost: str = "100", price: str = "150", **extra) -> int:
        data = products.clean_form({
            "sku": sku, "name": name or f"Producto {sku}", "category_id": str(make_category(category)),
            "min_stock": min_stock,
            "cost": cost, "price": price, "initial_stock": stock_qty, **extra}, with_initial_stock=True)
        return products.create(conn, data, actor, app.config["MAX_ACTIVE_RECORDS"])
    return factory


@pytest.fixture
def move(conn, actor):
    def run(product_id: int, kind: str, qty: int, **kw):
        return stock.register_movement(conn, product_id, kind, qty, actor, **kw)
    return run


# ------------------------------------------------------- resultados de aceptación
def pytest_configure(config):
    config.addinivalue_line("markers", "acceptance(case_id): caso de la matriz de pruebas de aceptación")


@pytest.fixture
def metrics(request):
    """Diccionario donde una prueba de aceptación puede dejar mediciones (se guardan en results.json)."""
    request.node._metrics = {}
    return request.node._metrics


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("acceptance")
    if not marker:
        return
    case_id = marker.args[0]
    entry = _results.setdefault(case_id, {"case_id": case_id, "test": item.nodeid, "outcome": "passed",
                                          "duration_s": 0.0, "message": "", "metrics": {}})
    entry["duration_s"] = round(entry["duration_s"] + report.duration, 3)
    entry["metrics"].update(getattr(item, "_metrics", {}) or {})
    if report.failed:
        entry["outcome"] = "failed"
        entry["message"] = (report.longreprtext or "")[-600:]
    elif report.skipped and entry["outcome"] != "failed":
        entry["outcome"] = "skipped"
        entry["message"] = str(report.longrepr)[-300:]


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "environment": {"python": os.sys.version.split()[0], "database": "SQLite (pruebas locales)"},
        "results": sorted(_results.values(), key=lambda r: r["case_id"]),
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
