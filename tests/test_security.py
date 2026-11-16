"""Pruebas de seguridad: CSRF, bloqueo por intentos, redirecciones, XSS, contraseñas y auditoría."""
from __future__ import annotations

import pytest

from stocktrack.models import users
from tests.helpers.web import PASSWORDS, login, post, token_from


def test_csrf_required_on_posts(app, make_product):
    make_product("CSR-1", stock_qty=5)
    client = app.test_client()
    login(client, "encargado")
    response = client.post("/movimientos/nuevo", data={"sku": "CSR-1", "kind": "venta", "quantity": "1"})
    assert response.status_code == 400
    wrong = client.post("/movimientos/nuevo", data={"sku": "CSR-1", "kind": "venta", "quantity": "1",
                                                     "csrf_token": "falso"})
    assert wrong.status_code == 400
    assert client.post("/logout", data={}).status_code == 400            # cerrar sesión también exige token


def test_login_lockout_after_repeated_failures(app):
    client = app.test_client()
    for _ in range(5):
        assert login(client, "admin", "incorrecta").status_code == 401
    assert login(client, "admin", PASSWORDS["admin"]).status_code == 429   # bloqueado aunque la clave sea correcta
    other = app.test_client()                                               # otro usuario, misma IP (límite mayor)
    assert login(other, "encargado").status_code == 302


def test_login_failures_are_audited(app, conn):
    client = app.test_client()
    login(client, "admin", "mala")
    login(client, "admin")
    actions = [r["action"] for r in conn.all("SELECT action FROM audit_log ORDER BY id")]
    assert "auth.login_failed" in actions and "auth.login" in actions


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil.example"])
def test_open_redirect_is_blocked(app, target):
    client = app.test_client()
    token = token_from(client.get("/login").get_data(as_text=True))
    response = client.post("/login", data={"email": "admin@test.local", "password": PASSWORDS["admin"],
                                           "csrf_token": token, "next": target})
    assert response.status_code == 302 and response.headers["Location"] == "/"


def test_internal_next_is_honored(app):
    client = app.test_client()
    token = token_from(client.get("/login?next=/alertas").get_data(as_text=True))
    response = client.post("/login", data={"email": "admin@test.local", "password": PASSWORDS["admin"],
                                           "csrf_token": token, "next": "/alertas"})
    assert response.headers["Location"] == "/alertas"


def test_html_is_escaped(app, make_product):
    make_product("XSS-1", name='<script>alert("x")</script>', stock_qty=1, min_stock=5)
    client = app.test_client()
    login(client, "admin")
    for path in ("/productos", "/productos/1", "/", "/alertas"):
        html = client.get(path).get_data(as_text=True)
        assert "<script>alert" not in html, path
    assert "&lt;script&gt;" in client.get("/productos").get_data(as_text=True)


def test_sql_injection_in_search_is_inert(app, make_product, conn):
    make_product("SQL-1", stock_qty=1)
    client = app.test_client()
    login(client, "admin")
    for payload in ("' OR 1=1 --", "%", "_", "'; DROP TABLE products; --"):
        assert client.get("/productos", query_string={"q": payload}).status_code == 200
    assert conn.scalar("SELECT COUNT(*) FROM products") == 1
    body = client.get("/productos", query_string={"q": "%"}).get_data(as_text=True)
    assert "SQL-1" not in body                         # el comodín se escapa: «%» no coincide con todo


def test_security_headers(client):
    response = client.get("/login")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "HttpOnly" in client.get("/login").headers.get("Set-Cookie", "HttpOnly")


def test_forced_password_change_flow(app, conn):
    user = users.get_by_email(conn, "encargado@test.local")
    users.set_password(conn, user["id"], "Temporal123", must_change=True)
    client = app.test_client()
    login(client, "encargado", "Temporal123")
    response = client.get("/productos")
    assert response.status_code == 302 and "/cuenta/password" in response.headers["Location"]
    bad = post(client, "/cuenta/password", current_password="Temporal123", new_password="corta",
               confirm_password="corta")
    assert bad.status_code == 400
    ok = post(client, "/cuenta/password", current_password="Temporal123", new_password="NuevaClave99",
              confirm_password="NuevaClave99")
    assert ok.status_code == 302
    assert client.get("/productos").status_code == 200


def test_deactivated_user_loses_session(app, conn):
    client = app.test_client()
    login(client, "consulta")
    assert client.get("/productos").status_code == 200
    users.set_active(conn, users.get_by_email(conn, "consulta@test.local")["id"], False)
    assert client.get("/productos").status_code == 302


def test_admin_user_management_and_audit(app, conn):
    admin = app.test_client()
    login(admin, "admin")
    created = post(admin, "/usuarios/nuevo", full_name="Nuevo Usuario", email="n@x.com",
                   role="encargado", password="Inicial123", must_change="1", receive_alerts="1")
    assert created.status_code == 302
    assert users.get_by_email(conn, "n@x.com")["role"] == "encargado"
    dup = post(admin, "/usuarios/nuevo", full_name="Otro", email="N@X.com", role="consulta",
               password="Inicial123")
    assert dup.status_code == 422                                   # correo duplicado (sin distinguir mayúsculas)
    assert conn.scalar("SELECT COUNT(*) FROM audit_log WHERE action = 'user.create'") >= 4   # 3 de fixture + 1 nuevo


def test_health_endpoint(client):
    body = client.get("/health").get_json()
    assert body["status"] == "ok" and body["database"] == "ok"
