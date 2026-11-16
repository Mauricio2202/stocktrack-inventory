"""PA-02 · Las alertas de escasez deben enviarse correctamente por correo y/o notificaciones."""
from __future__ import annotations

import socket

import pytest

from stocktrack.models import alerts
from tests.helpers.smtp import MiniSMTP
from tests.helpers.web import login, post


@pytest.fixture
def smtp(app):
    server = MiniSMTP().start()
    app.config.update(MAIL_ENABLED=True, MAIL_HOST="127.0.0.1", MAIL_PORT=server.port, MAIL_USE_TLS=False,
                      MAIL_USE_SSL=False, MAIL_USER="")
    yield server
    server.stop()


def _movement(client, sku, kind, qty):
    return post(client, "/movimientos/nuevo", sku=sku, kind=kind, quantity=str(qty), reference="PRUEBA")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.acceptance("PA-02.1")
def test_alert_email_is_delivered(app, smtp, make_product, conn, metrics):
    product = make_product("CEL-100", name="Galaxy A55 256GB", stock_qty=8, min_stock=5, category="Smartphones")
    worker = app.test_client()
    login(worker, "encargado")
    response = _movement(worker, "CEL-100", "venta", 3)       # 8 -> 5 = mínimo => escasez
    assert response.status_code == 302
    assert len(smtp.messages) == 1
    mail = smtp.messages[0]
    assert sorted(mail["to"]) == ["admin@test.local", "encargado@test.local"]       # solo quienes activaron alertas
    assert "CEL-100" in mail["subject"] and "Galaxy A55 256GB" in mail["subject"]
    assert "Stock disponible: 5 unidades" in mail["text"] and "Stock mínimo:   5 unidades" in mail["text"]
    assert "<table" in mail["html"] and "Galaxy A55 256GB" in mail["html"]
    row = conn.one("SELECT email_status, email_detail, email_sent_at FROM stock_alerts WHERE product_id = ?", (product,))
    assert row["email_status"] == "enviado" and row["email_sent_at"]
    metrics.update({"correos_recibidos": len(smtp.messages), "destinatarios": len(mail["to"])})


@pytest.mark.acceptance("PA-02.2")
def test_in_app_notifications_by_role(app, make_product, conn, metrics):
    make_product("NOT-001", name="Router AX23", stock_qty=6, min_stock=5)
    worker = app.test_client()
    login(worker, "encargado")
    _movement(worker, "NOT-001", "venta", 2)
    counts = {r["email"].split("@")[0]: r["n"] for r in conn.all(
        "SELECT u.email, COUNT(n.id) AS n FROM users u LEFT JOIN notifications n ON n.user_id = u.id GROUP BY u.email")}
    assert counts == {"admin": 1, "encargado": 1, "consulta": 0}
    # La notificación es visible en la interfaz y se puede marcar como leída.
    admin = app.test_client()
    login(admin, "admin")
    page = admin.get("/alertas").get_data(as_text=True)
    assert "Stock bajo: Router AX23 (NOT-001)" in page
    assert alerts.unread_count(conn, conn.scalar("SELECT id FROM users WHERE email = 'admin@test.local'")) == 1
    post(admin, "/notificaciones/leer-todas")
    assert alerts.unread_count(conn, conn.scalar("SELECT id FROM users WHERE email = 'admin@test.local'")) == 0
    metrics.update({"notificaciones_generadas": sum(counts.values())})


@pytest.mark.acceptance("PA-02.3")
def test_single_alert_and_email_per_episode(app, smtp, make_product, conn, metrics):
    product = make_product("EPI-001", stock_qty=10, min_stock=5)
    worker = app.test_client()
    login(worker, "encargado")
    _movement(worker, "EPI-001", "venta", 5)      # 10 -> 5: alerta 1
    _movement(worker, "EPI-001", "venta", 1)      # 5 -> 4: sigue en escasez, NO hay alerta nueva
    _movement(worker, "EPI-001", "venta", 1)
    assert conn.scalar("SELECT COUNT(*) FROM stock_alerts WHERE product_id = ?", (product,)) == 1
    assert len(smtp.messages) == 1
    _movement(worker, "EPI-001", "compra", 20)    # se repone: alerta resuelta
    _movement(worker, "EPI-001", "venta", 20)     # nuevo episodio
    assert conn.scalar("SELECT COUNT(*) FROM stock_alerts WHERE product_id = ?", (product,)) == 2
    assert len(smtp.messages) == 2
    assert conn.scalar("SELECT COUNT(*) FROM stock_alerts WHERE product_id = ? AND status IN ('abierta','atendida')",
                       (product,)) == 1
    metrics.update({"alertas": 2, "correos": len(smtp.messages)})


@pytest.mark.acceptance("PA-02.4")
def test_alert_resolves_and_threshold_is_inclusive(app, make_product, move, conn, metrics):
    product = make_product("RES-001", stock_qty=6, min_stock=5)
    assert alerts.open_count(conn) == 0                      # 6 > 5: sin alerta
    move(product, "venta", 1)                               # 5 == mínimo: dispara (umbral inclusivo)
    assert alerts.open_count(conn) == 1
    alert_id = conn.scalar("SELECT id FROM stock_alerts WHERE product_id = ?", (product,))
    admin = app.test_client()
    login(admin, "admin")
    assert post(admin, f"/alertas/{alert_id}/atender").status_code == 403    # solo el encargado marca atendidas (RF-25)
    clerk = app.test_client()
    login(clerk, "encargado")
    post(clerk, f"/alertas/{alert_id}/atender")
    assert conn.scalar("SELECT status FROM stock_alerts WHERE id = ?", (alert_id,)) == "atendida"
    assert alerts.open_count(conn) == 1                      # atendida sigue vigente hasta reponer
    move(product, "compra", 1)                              # 6 > 5: se resuelve sola
    row = conn.one("SELECT status, resolved_at FROM stock_alerts WHERE id = ?", (alert_id,))
    assert row["status"] == "resuelta" and row["resolved_at"]
    assert alerts.open_count(conn) == 0
    zero = make_product("CER-001", stock_qty=2, min_stock=0)  # mínimo 0 = sin alerta aunque llegue a 0
    move(zero, "venta", 2)
    assert alerts.open_count(conn) == 0
    metrics.update({"umbral_inclusivo": True})


@pytest.mark.acceptance("PA-02.5")
def test_smtp_failure_does_not_break_movements(app, make_product, conn, metrics):
    product = make_product("FAL-001", stock_qty=6, min_stock=5)
    app.config.update(MAIL_ENABLED=True, MAIL_HOST="127.0.0.1", MAIL_PORT=_free_port(), MAIL_USE_TLS=False)
    worker = app.test_client()
    login(worker, "encargado")
    response = _movement(worker, "FAL-001", "venta", 2)
    assert response.status_code == 302                                    # el movimiento se guardó
    assert conn.scalar("SELECT stock FROM products WHERE id = ?", (product,)) == 4
    row = conn.one("SELECT status, email_status, email_detail FROM stock_alerts WHERE product_id = ?", (product,))
    assert row["status"] == "abierta" and row["email_status"] == "error" and row["email_detail"]
    assert conn.scalar("SELECT COUNT(*) FROM notifications WHERE alert_id IS NOT NULL") >= 1   # la alerta interna sigue
    metrics.update({"detalle_error": row["email_detail"][:80]})
