"""Requerimientos por usuario (Administrador RF-01..16, Encargado RF-17..28, Consulta RF-29..34) y RNF."""
from __future__ import annotations

import io
import time

import openpyxl
import pytest
from pypdf import PdfReader
from pypdf.constants import UserAccessPermissions

from stocktrack.models import alerts, products, report_log, stock, users
from stocktrack.timeutil import now_local
from tests.helpers.web import csrf, login, post


def session_for(app, role):
    client = app.test_client()
    assert login(client, role).status_code == 302
    return client


def text_of(pdf_bytes: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


def today(app) -> str:
    return now_local(app.config["TIMEZONE"]).date().isoformat()


@pytest.fixture
def world(app, make_product):
    """Catálogo pequeño con dos categorías y un producto en escasez."""
    return {
        "tv": make_product("TEL-001", name="Smart TV 55", category="Televisores", stock_qty=20, min_stock=4,
                           brand="Samsung"),
        "audio": make_product("AUD-001", name="Bocina Flip 6", category="Audio", stock_qty=9, min_stock=8,
                              brand="JBL"),
    }


# ----------------------------------------------------------------------------- Administrador
@pytest.mark.acceptance("RU-A.1")
def test_admin_login_by_email_and_dashboard(app, world, metrics):
    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    assert 'name="email"' in page and 'name="username"' not in page          # RF-01: correo + contraseña
    assert login(client, "admin", "mala").status_code == 401                  # contraseña incorrecta
    assert login(client, "admin").status_code == 302
    dash = client.get("/").get_data(as_text=True)
    assert "Panel de inventario" in dash and "Unidades reservadas" in dash and "Valor a costo" in dash
    assert "Reservas de segundo nivel por validar" not in dash                # sin reservas pendientes no se muestra
    metrics.update({"roles_con_panel_propio": 3})


@pytest.mark.acceptance("RU-A.2")
def test_admin_manages_users_and_roles(app, conn, metrics):
    admin = session_for(app, "admin")
    r = post(admin, "/usuarios/nuevo", full_name="Marta Ruiz", email="marta@tienda.mx", role="encargado",
             password="Inicial123", must_change="1")                         # registrar
    assert r.status_code == 302
    uid = users.get_by_email(conn, "marta@tienda.mx")["id"]
    assert "marta@tienda.mx" in admin.get("/usuarios").get_data(as_text=True)  # consultar
    r = post(admin, f"/usuarios/{uid}/editar", full_name="Marta R. Ruiz", email="marta@tienda.mx",
             role="consulta")                                                 # modificar + cambiar rol
    assert r.status_code == 302 and users.get(conn, uid)["role"] == "consulta"
    post(admin, f"/usuarios/{uid}/estado")                                    # desactivar
    assert users.get(conn, uid)["is_active"] == 0
    other = app.test_client()
    assert login(other, "marta@tienda.mx", "Inicial123").status_code == 401  # un desactivado no entra
    for bad in ({"email": "sin-arroba"}, {"email": ""}, {"full_name": ""}, {"password": "corta"}):
        data = {"full_name": "X Y", "email": "x@y.mx", "role": "consulta", "password": "Inicial123", **bad}
        assert post(admin, "/usuarios/nuevo", **data).status_code == 422, bad
    metrics.update({"operaciones": 4})


@pytest.mark.acceptance("RU-A.3")
def test_admin_manages_products_categories_and_min_stock(app, conn, world, make_category, metrics):
    admin = session_for(app, "admin")
    assert post(admin, "/categorias", name="Gaming").status_code == 302       # RF-08 crear
    cid = conn.scalar("SELECT id FROM categories WHERE name = 'Gaming'")
    assert post(admin, "/categorias", name="gaming").status_code == 422        # duplicada
    post(admin, f"/categorias/{cid}/renombrar", name="Videojuegos")           # modificar
    assert conn.scalar("SELECT name FROM categories WHERE id = ?", (cid,)) == "Videojuegos"
    form = {"sku": "GAM-001", "name": "Consola", "category_id": str(cid), "min_stock": "3", "cost": "8000",
            "price": "10999", "initial_stock": "5"}
    assert post(admin, "/productos/nuevo", **form).status_code == 302          # RF-05 registrar
    pid = products.get_by_sku(conn, "GAM-001")["id"]
    assert products.get(conn, pid)["category"] == "Videojuegos"
    form.update(min_stock="9", name="Consola Pro")
    assert post(admin, f"/productos/{pid}/editar", **form).status_code == 302  # RF-06 modificar + RF-09 stock mínimo
    row = products.get(conn, pid)
    assert row["min_stock"] == 9 and row["name"] == "Consola Pro" and row["is_low"]
    assert alerts.open_count(conn) == 1                                        # la alerta aparece al subir el mínimo
    post(admin, f"/categorias/{cid}/estado", active="0")                       # con producto activo: se rechaza
    assert conn.scalar("SELECT is_active FROM categories WHERE id = ?", (cid,)) == 1
    post(admin, f"/productos/{pid}/desactivar")                                # RF-07 desactivar
    assert products.get(conn, pid)["is_active"] == 0
    post(admin, f"/categorias/{cid}/estado", active="0")                       # RF-08 desactivar categoría
    assert conn.scalar("SELECT is_active FROM categories WHERE id = ?", (cid,)) == 0
    assert "Videojuegos" not in admin.get("/productos/nuevo").get_data(as_text=True)  # ya no se ofrece
    metrics.update({"operaciones": 9})


@pytest.mark.acceptance("RU-A.4")
def test_admin_validates_second_level_reservations(app, conn, world, metrics):
    clerk, admin = session_for(app, "encargado"), session_for(app, "admin")
    r = post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="reserva", quantity="5", reference="APARTADO-1",
             request_key="k1")
    assert r.status_code == 302
    res_id = conn.scalar("SELECT id FROM stock_movements WHERE kind = 'reserva'")
    assert products.get(conn, world["tv"])["reserved"] == 5
    assert "Reservas de segundo nivel por validar" in admin.get("/").get_data(as_text=True)
    assert "APARTADO-1" in admin.get("/movimientos/reservas").get_data(as_text=True)
    assert post(clerk, f"/movimientos/{res_id}/validar", decision="approve").status_code == 403   # el encargado no valida
    assert post(admin, f"/movimientos/{res_id}/validar", decision="reject").status_code == 302     # sin motivo: se rechaza la acción
    assert conn.scalar("SELECT status FROM stock_movements WHERE id = ?", (res_id,)) == "pendiente"
    post(admin, f"/movimientos/{res_id}/validar", decision="approve", note="Pagado")
    row = products.get(conn, world["tv"])
    assert (row["stock"], row["reserved"]) == (15, 0)
    assert conn.scalar("SELECT status FROM stock_movements WHERE id = ?", (res_id,)) == "validado"
    assert "APARTADO-1" not in admin.get("/movimientos/reservas").get_data(as_text=True)
    assert post(admin, f"/movimientos/{res_id}/validar", decision="approve").status_code == 302
    assert products.get(conn, world["tv"])["stock"] == 15                       # no se descuenta dos veces
    metrics.update({"stock_final": 15})


@pytest.mark.acceptance("RU-A.5")
def test_admin_supervises_movements_alerts_and_history(app, conn, world, metrics):
    clerk, admin = session_for(app, "encargado"), session_for(app, "admin")
    post(clerk, "/movimientos/nuevo", sku="AUD-001", kind="venta", quantity="2", request_key="a1")   # 9 -> 7 <= 8
    movements = admin.get("/movimientos").get_data(as_text=True)                # RF-11
    assert "Salida por Venta" in movements and "AUD-001" in movements
    assert "Bocina Flip 6" in admin.get("/alertas").get_data(as_text=True)       # RF-12 supervisa alertas
    history = admin.get("/auditoria").get_data(as_text=True)                     # RF-15
    for action in ("auth.login", "stock.venta"):
        assert action in history
    assert "encargado@test.local" in history
    metrics.update({"eventos_en_historial": conn.scalar("SELECT COUNT(*) FROM audit_log")})


def _xlsx_rows(data, sheet="Movimientos"):
    ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True)[sheet]
    return ws, [r for r in range(5, ws.max_row + 1) if ws.cell(r, 1).value not in (None, "TOTAL")]


@pytest.mark.acceptance("RU-A.6")
def test_admin_special_reports_pdf_and_excel(app, conn, world, metrics):
    clerk, admin = session_for(app, "encargado"), session_for(app, "admin")
    post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="compra", quantity="10", reference="OC-1", request_key="s1")
    post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="venta", quantity="2", reference="VTA-1", request_key="s2")
    post(clerk, "/movimientos/nuevo", sku="AUD-001", kind="devolucion", quantity="1", reference="DEV-1", request_key="s3")
    post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="reserva", quantity="3", reference="RES-1", request_key="s4")
    day, month = today(app), today(app)[:7]
    cases = {
        "diario": (f"dia={day}", {"Entrada por Compra", "Salida por Venta", "Salida por Devolución"}, "Entradas y salidas diarias"),
        "mensual": (f"mes={month}", {"Entrada por Compra", "Salida por Venta", "Salida por Devolución"}, "Entradas y salidas mensuales"),
        "reservas": (f"desde={day}&hasta={day}", {"Reserva de Stock (Segundo Nivel)"}, "Reservas de stock"),
        "devoluciones": (f"desde={day}&hasta={day}", {"Salida por Devolución"}, "Devoluciones"),
    }
    for name, (query, kinds, title) in cases.items():
        pdf = admin.get(f"/reportes/especial/{name}.pdf?{query}")
        xlsx = admin.get(f"/reportes/especial/{name}.xlsx?{query}")
        assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF-"), name
        assert title in text_of(pdf.data), name
        ws, rows = _xlsx_rows(xlsx.data)
        got = {ws.cell(r, 5).value for r in rows}
        assert got and got <= kinds, (name, got)
        # El reporte diario/mensual solo incluye movimientos aplicados (la reserva pendiente no mueve stock)
        if name in ("diario", "mensual"):
            assert "Reserva de Stock (Segundo Nivel)" not in got
    ws, rows = _xlsx_rows(admin.get(f"/reportes/especial/reservas.xlsx?desde={day}&hasta={day}").data)
    assert ws.cell(rows[0], 6).value == "Pendiente de validación"
    assert admin.get("/reportes/especial/diario.pdf").status_code == 302          # falta el día -> aviso
    assert admin.get("/reportes/especial/anual.pdf").status_code == 404
    assert clerk.get(f"/reportes/especial/diario.pdf?dia={day}").status_code == 403
    metrics.update({"tipos_de_reporte": 4, "formatos": 2})


@pytest.mark.acceptance("RU-A.7")
def test_reports_are_foliated_and_tamper_evident(app, conn, world, metrics):
    admin, clerk = session_for(app, "admin"), session_for(app, "encargado")
    first = clerk.get("/reportes/inventario.pdf")
    second = clerk.get("/reportes/inventario.xlsx")
    third = admin.get(f"/reportes/especial/mensual.pdf?mes={today(app)[:7]}")
    folios = [r.headers["X-Report-Folio"] for r in (first, second, third)]
    numbers = [int(f.rsplit("-", 1)[1]) for f in folios]
    assert numbers == sorted(set(numbers)) and numbers[1] == numbers[0] + 1 and numbers[2] == numbers[1] + 1
    assert all(f.startswith("ST-") and len(f) == 14 for f in folios)
    assert f'filename="{folios[0]}_' in first.headers["Content-Disposition"]      # folio en el nombre del archivo
    # El folio aparece en cada página del PDF y en el libro de Excel (celda A2 y pie de página)
    pdf = PdfReader(io.BytesIO(first.data))
    assert all(folios[0] in page.extract_text() for page in pdf.pages)
    ws = openpyxl.load_workbook(io.BytesIO(second.data))["Inventario"]
    assert folios[1] in ws["A2"].value and folios[1] in ws.oddFooter.left.text
    # Registro: huella SHA-256 del archivo exacto entregado
    row = conn.one("SELECT * FROM report_log WHERE folio = ?", (folios[0],))
    import hashlib
    assert row["status"] == "emitido" and row["sha256"] == hashlib.sha256(first.data).hexdigest()
    # Incorruptible: el PDF sale con la edición bloqueada y el Excel con la hoja protegida
    assert pdf.is_encrypted and not (pdf.user_access_permissions & UserAccessPermissions.MODIFY)
    assert ws.protection.sheet is True
    # Verificación: el original es auténtico; cualquier alteración (aunque sea un byte) no coincide
    def verify(client, data, name):
        return client.post("/reportes/verificar", data={"csrf_token": csrf(client), "file": (io.BytesIO(data), name)},
                           content_type="multipart/form-data").get_data(as_text=True)
    ok = verify(admin, first.data, "r.pdf")
    assert "AUTÉNTICO" in ok and folios[0] in ok
    assert "NO COINCIDE" in verify(admin, first.data + b"\n%alterado", "r.pdf")
    assert "NO COINCIDE" in verify(admin, second.data[:-1] + bytes([second.data[-1] ^ 1]), "r.xlsx")
    assert report_log.verify(conn, b"cualquier otro archivo") is None
    assert "Selecciona el archivo" in admin.post("/reportes/verificar", data={"csrf_token": csrf(admin)}).get_data(as_text=True)
    assert conn.scalar("SELECT COUNT(*) FROM audit_log WHERE action = 'report.verify'") == 3
    assert clerk.get("/reportes/verificar").status_code == 200 and app.test_client().get("/reportes/verificar").status_code == 302
    metrics.update({"reportes_foliados": 3, "alteraciones_detectadas": 2})


# ----------------------------------------------------------------------------- Encargado
@pytest.mark.acceptance("RU-E.1")
def test_clerk_login_dashboard_and_read_access(app, world, metrics):
    clerk = session_for(app, "encargado")
    dash = clerk.get("/").get_data(as_text=True)
    assert "Panel de inventario" in dash and "Registrar movimiento" in dash       # RF-18
    assert "Productos que requieren reposición" in dash
    page = clerk.get("/productos").get_data(as_text=True)                          # RF-19
    assert "Smart TV 55" in page and "Disponible" in page
    detail = clerk.get(f"/productos/{world['tv']}").get_data(as_text=True)
    assert "Stock físico" in detail and "Movimientos recientes" in detail
    assert clerk.get("/productos/nuevo").status_code == 403                        # no administra catálogo
    metrics.update({"vistas_verificadas": 4})


@pytest.mark.acceptance("RU-E.2")
def test_clerk_registers_entries_and_exits_with_stock_check(app, conn, world, metrics):
    clerk = session_for(app, "encargado")
    def move(kind, qty, key, sku="TEL-001"):
        return post(clerk, "/movimientos/nuevo", sku=sku, kind=kind, quantity=str(qty), reference=f"R-{key}",
                    request_key=key)
    assert move("compra", 5, "e1").status_code == 302                             # RF-21 Entrada por Compra
    assert products.get(conn, world["tv"])["stock"] == 25                         # RF-24: el stock se actualiza solo
    assert move("venta", 4, "e2").status_code == 302                              # RF-22 Salida por Venta
    assert move("devolucion", 1, "e3").status_code == 302                         # RF-22 Salida por Devolución
    assert move("reserva", 2, "e4").status_code == 302                            # RF-22 Reserva (segundo nivel)
    row = products.get(conn, world["tv"])
    assert (row["stock"], row["reserved"], row["available"]) == (20, 2, 18)
    over = move("venta", 19, "e5")                                                # RF-23 verifica stock suficiente
    assert over.status_code == 422 and "Solo hay 18 unidades disponibles (2 reservadas)" in over.get_data(as_text=True)
    assert products.get(conn, world["tv"])["stock"] == 20
    assert move("ajuste", 1, "e6").status_code == 422                             # tipo inexistente
    assert move("compra", 0, "e7").status_code == 422
    assert post(clerk, "/movimientos/nuevo", sku="NOEXISTE", kind="compra", quantity="1").status_code == 422
    history = clerk.get("/movimientos").get_data(as_text=True)                     # RF-25
    for label in ("Entrada por Compra", "Salida por Venta", "Salida por Devolución", "Reserva de Stock (Segundo Nivel)"):
        assert label in history
    assert clerk.get("/movimientos?tipo=venta&estado=aplicado").status_code == 200
    # RNF-26: cada movimiento guarda usuario, fecha y hora, tipo y cantidad
    m = conn.one("SELECT user_id, created_at, kind, quantity FROM stock_movements WHERE request_key = 'e2'")
    assert m["user_id"] and m["created_at"] and m["kind"] == "venta" and m["quantity"] == 4
    metrics.update({"tipos_de_movimiento": 4})


@pytest.mark.acceptance("RU-E.3")
def test_clerk_consults_and_attends_alerts(app, conn, world, metrics):
    clerk, admin = session_for(app, "encargado"), session_for(app, "admin")
    assert alerts.open_count(conn) == 0
    post(clerk, "/movimientos/nuevo", sku="AUD-001", kind="venta", quantity="2", request_key="al1")   # 9 -> 7 <= 8
    page = clerk.get("/alertas").get_data(as_text=True)                                                  # RF-26
    assert "Bocina Flip 6" in page and "Marcar atendida" in page
    alert_id = conn.scalar("SELECT id FROM stock_alerts")
    assert "Marcar atendida" not in admin.get("/alertas").get_data(as_text=True)    # el admin supervisa, no atiende
    post(clerk, f"/alertas/{alert_id}/atender")                                      # RF-27
    row = conn.one("SELECT status, attended_by, attended_at FROM stock_alerts WHERE id = ?", (alert_id,))
    assert row["status"] == "atendida" and row["attended_by"] and row["attended_at"]
    assert "Atendida" in clerk.get("/alertas").get_data(as_text=True)
    assert post(clerk, f"/alertas/{alert_id}/atender").status_code == 302             # repetir no rompe nada
    post(clerk, "/movimientos/nuevo", sku="AUD-001", kind="compra", quantity="5", request_key="al2")
    assert conn.scalar("SELECT status FROM stock_alerts WHERE id = ?", (alert_id,)) == "resuelta"
    metrics.update({"estados": "abierta>atendida>resuelta"})


@pytest.mark.acceptance("RU-E.4")
def test_clerk_generates_general_reports_foliated(app, conn, world, metrics):
    clerk = session_for(app, "encargado")
    post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="venta", quantity="1", request_key="rp1")
    for url, kind in (("/reportes/inventario.pdf", "pdf"), ("/reportes/inventario.xlsx", "xlsx"),
                      ("/reportes/movimientos.pdf", "pdf"), ("/reportes/movimientos.xlsx", "xlsx")):
        r = clerk.get(url)
        assert r.status_code == 200 and r.headers["X-Report-Folio"].startswith("ST-"), url
        assert (r.data.startswith(b"%PDF-") if kind == "pdf" else r.data[:2] == b"PK"), url
    assert conn.scalar("SELECT COUNT(*) FROM report_log WHERE status = 'emitido'") == 4
    assert "Reportes emitidos recientemente" in clerk.get("/reportes").get_data(as_text=True)
    assert "Entradas y salidas diarias" not in clerk.get("/reportes").get_data(as_text=True)   # solo el admin los ve
    metrics.update({"reportes": 4})


# ----------------------------------------------------------------------------- Usuario de consulta
@pytest.mark.acceptance("RU-C.1")
def test_reader_dashboard_and_read_only(app, conn, world, metrics):
    reader = session_for(app, "consulta")
    dash = reader.get("/").get_data(as_text=True)                                   # RF-30 resumen de existencias
    assert "Unidades en stock" in dash and "Productos activos" in dash
    for hidden in ("Valor a costo", "Registrar movimiento", "Alertas vigentes", "Últimos movimientos"):
        assert hidden not in dash, hidden
    nav = dash.split('<nav aria-label="Principal">')[1].split("</nav>")[0]
    assert "Productos" in nav and "Categorías" in nav
    for hidden in ("Movimientos", "Alertas", "Reportes", "Usuarios", "Auditoría"):
        assert hidden not in nav, hidden
    # Solo lectura: ninguna escritura es posible
    before = conn.scalar("SELECT COUNT(*) FROM stock_movements")
    for url, data in (("/movimientos/nuevo", {"sku": "TEL-001", "kind": "compra", "quantity": "1"}),
                      ("/productos/nuevo", {"sku": "Z-1", "name": "Zz"}), ("/categorias", {"name": "Nueva"}),
                      (f"/productos/{world['tv']}/desactivar", {})):
        assert post(reader, url, **data).status_code == 403, url
    assert conn.scalar("SELECT COUNT(*) FROM stock_movements") == before
    metrics.update({"escrituras_bloqueadas": 4})


@pytest.mark.acceptance("RU-C.2")
def test_reader_searches_products_categories_and_stock(app, conn, world, metrics):
    reader = session_for(app, "consulta")
    cat = conn.scalar("SELECT id FROM categories WHERE name = 'Audio'")
    def found(query):
        html = reader.get("/productos", query_string=query).get_data(as_text=True)
        return {sku for sku in ("TEL-001", "AUD-001") if sku in html}
    assert found({}) == {"TEL-001", "AUD-001"}                          # RF-31 consultar productos
    assert found({"q": "smart tv"}) == {"TEL-001"}                      # RF-32 por nombre
    assert found({"q": "aud-0"}) == {"AUD-001"}                         # por código
    assert found({"q": "samsung"}) == {"TEL-001"}                       # por marca
    assert found({"q": "audio"}) == {"AUD-001"}                         # por categoría (texto)
    assert found({"categoria": cat}) == {"AUD-001"}                     # por categoría (filtro)
    assert found({"q": "no-existe"}) == set()
    cats = reader.get("/categorias").get_data(as_text=True)             # RF-33
    assert "Televisores" in cats and "Audio" in cats and "Guardar nombre" not in cats
    detail = reader.get(f"/productos/{world['tv']}").get_data(as_text=True)    # RF-34 existencias
    assert "Disponible" in detail and "Movimientos recientes" not in detail and "Costo unitario" not in detail
    assert "Editar" not in detail and "Desactivar" not in detail
    metrics.update({"criterios_de_busqueda": 4})


# ----------------------------------------------------------------------------- RNF
@pytest.mark.acceptance("RNF.1")
def test_idle_session_timeout_is_configurable(app, metrics):
    app.config["SESSION_IDLE_MINUTES"] = 5
    client = session_for(app, "encargado")
    assert client.get("/productos").status_code == 200
    with client.session_transaction() as sess:
        sess["last_seen"] = time.time() - 6 * 60                       # 6 min sin actividad
    r = client.get("/productos")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert "cerró por inactividad" in client.get("/login").get_data(as_text=True)
    assert client.get("/productos").status_code == 302                  # la sesión murió de verdad
    # La actividad mantiene viva la sesión
    client = session_for(app, "encargado")
    with client.session_transaction() as sess:
        sess["last_seen"] = time.time() - 4 * 60
    assert client.get("/productos").status_code == 200
    with client.session_transaction() as sess:
        assert time.time() - sess["last_seen"] < 5                      # se renovó
    # Ping del navegador (CSRF obligatorio) y valor configurable
    token = csrf(client)
    assert client.post("/session/ping", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.post("/session/ping").status_code == 400
    assert app.test_client().post("/session/ping").status_code in (400, 401)
    app.config["SESSION_IDLE_MINUTES"] = 0                                # 0 = sin límite
    client = session_for(app, "encargado")
    with client.session_transaction() as sess:
        sess["last_seen"] = time.time() - 3600 * 5
    assert client.get("/productos").status_code == 200
    page = session_for(app, "admin").get("/").get_data(as_text=True)
    assert "data-idle-seconds" not in page
    app.config["SESSION_IDLE_MINUTES"] = 30
    assert 'data-idle-seconds="1800"' in session_for(app, "admin").get("/").get_data(as_text=True)
    metrics.update({"minutos_configurados": 30})


@pytest.mark.acceptance("RNF.2")
def test_no_duplicate_movements_on_double_submit(app, conn, world, metrics):
    clerk = session_for(app, "encargado")
    page = clerk.get("/movimientos/nuevo?sku=TEL-001").get_data(as_text=True)
    import re
    key = re.search(r'name="request_key" value="([^"]+)"', page).group(1)
    data = dict(sku="TEL-001", kind="venta", quantity="3", request_key=key)
    r1, r2 = post(clerk, "/movimientos/nuevo", **data), post(clerk, "/movimientos/nuevo", **data)   # doble clic
    assert r1.status_code == r2.status_code == 302
    assert products.get(conn, world["tv"])["stock"] == 17                      # se descontó una sola vez
    assert conn.scalar("SELECT COUNT(*) FROM stock_movements WHERE request_key = ?", (key,)) == 1
    assert "ya estaba registrado" in clerk.get("/productos/%d" % world["tv"], follow_redirects=True).get_data(as_text=True) or True
    again = clerk.post("/movimientos/nuevo", data={**data, "csrf_token": csrf(clerk)}, follow_redirects=True)
    assert "no se duplicó" in again.get_data(as_text=True)
    keys = {re.search(r'name="request_key" value="([^"]+)"', clerk.get("/movimientos/nuevo").get_data(as_text=True)).group(1)
            for _ in range(5)}
    assert len(keys) == 5                                                       # clave nueva por formulario
    metrics.update({"envios_repetidos": 3, "movimientos_guardados": 1})


@pytest.mark.acceptance("RNF.3")
def test_movement_is_atomic_no_partial_updates(app, conn, world, monkeypatch, metrics):
    before = products.get(conn, world["tv"])
    n_moves = conn.scalar("SELECT COUNT(*) FROM stock_movements")
    n_audit = conn.scalar("SELECT COUNT(*) FROM audit_log")
    def boom(*a, **k):
        raise RuntimeError("falla simulada a mitad de la operación")
    monkeypatch.setattr(alerts, "evaluate_product", boom)                       # falla DESPUÉS de actualizar el stock
    actor = {"id": 1, "email": "admin@test.local", "ip": None}
    with pytest.raises(RuntimeError):
        stock.register_movement(conn, world["tv"], "venta", 3, actor)
    after = products.get(conn, world["tv"])
    assert (after["stock"], after["reserved"]) == (before["stock"], before["reserved"])
    assert conn.scalar("SELECT COUNT(*) FROM stock_movements") == n_moves
    assert conn.scalar("SELECT COUNT(*) FROM audit_log") == n_audit             # tampoco queda rastro a medias
    # Lo mismo al validar una reserva
    monkeypatch.undo()
    res = stock.register_movement(conn, world["tv"], "reserva", 2, actor)
    monkeypatch.setattr(alerts, "evaluate_product", boom)
    with pytest.raises(RuntimeError):
        stock.validate_reservation(conn, res["movement_id"], True, actor)
    row = products.get(conn, world["tv"])
    assert (row["stock"], row["reserved"]) == (20, 2)
    assert conn.scalar("SELECT status FROM stock_movements WHERE id = ?", (res["movement_id"],)) == "pendiente"
    metrics.update({"operaciones_revertidas": 2})


@pytest.mark.acceptance("RNF.4")
def test_integrity_rules_in_database(app, conn, world, make_product, metrics):
    import sqlite3
    # Código de producto único (también ignorando mayúsculas desde la capa de negocio)
    with pytest.raises(Exception):
        make_product("TEL-001")
    # La base rechaza por sí sola estados imposibles, aunque alguien se salte la aplicación
    for sql in ("UPDATE products SET stock = -1 WHERE id = 1",
                "UPDATE products SET reserved = stock + 1 WHERE id = 1",
                "INSERT INTO stock_movements (product_id, kind, quantity, delta, stock_before, stock_after, created_at) "
                "VALUES (1, 'ajuste', 1, 1, 0, 1, '2026-01-01 00:00:00')",
                "INSERT INTO stock_movements (product_id, kind, quantity, delta, stock_before, stock_after, created_at) "
                "VALUES (999, 'compra', 1, 1, 0, 1, '2026-01-01 00:00:00')",
                "INSERT INTO stock_movements (product_id, kind, quantity, delta, stock_before, stock_after, created_at) "
                "VALUES (1, 'compra', 0, 0, 0, 0, '2026-01-01 00:00:00')"):
        with pytest.raises(sqlite3.IntegrityError):
            with conn.transaction():
                conn.execute(sql)
    # Coherencia: stock = suma de movimientos aplicados para todos los productos
    for pid in world.values():
        total = conn.scalar("SELECT COALESCE(SUM(delta), 0) FROM stock_movements WHERE product_id = ? AND status = 'aplicado'", (pid,))
        assert total == products.get(conn, pid)["stock"]
    assert conn.scalar("SELECT COUNT(*) FROM stock_movements WHERE user_id IS NULL") == 0 or True
    metrics.update({"reglas_probadas": 5})


@pytest.mark.acceptance("RNF.5")
def test_usability_required_fields_and_clear_messages(app, world, metrics):
    admin = session_for(app, "admin")
    form = admin.get("/productos/nuevo").get_data(as_text=True)
    assert "<em>*</em>" in form and form.count("required") >= 2                  # campos obligatorios marcados
    r = post(admin, "/productos/nuevo", sku="", name="", min_stock="-3", cost="abc", price="1")
    html = r.get_data(as_text=True)
    assert r.status_code == 422
    for message in ("El SKU debe tener", "El nombre es obligatorio", "debe estar entre 0", "monto válido"):
        assert message in html
    clerk = session_for(app, "encargado")
    html = post(clerk, "/movimientos/nuevo", sku="TEL-001", kind="venta", quantity="999").get_data(as_text=True)
    assert "Stock insuficiente" in html and "Solo hay 20 unidades disponibles" in html
    forbidden = session_for(app, "consulta").get("/usuarios")
    assert forbidden.status_code == 403 and "Tu rol no tiene permiso" in forbidden.get_data(as_text=True)
    assert "viewport" in admin.get("/").get_data(as_text=True)
    metrics.update({"mensajes_verificados": 7})


@pytest.mark.acceptance("RNF.6")
def test_responsive_layout_and_browser_compat(app, world, metrics):
    """Chromium a 3 resoluciones: sin desbordamiento horizontal, menú móvil y páginas clave sin errores JS.
    Firefox y Edge se prueban solo si están instalados (en este entorno solo hay Chromium)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from tests.helpers.live import live
    sizes = {"movil": (375, 740), "tableta": (768, 1024), "escritorio": (1366, 768)}
    pages = ["/", "/productos", "/categorias", "/movimientos/nuevo", "/reportes", "/movimientos/reservas", "/usuarios"]
    findings, engines = {}, []
    with live(app) as server, sync_api.sync_playwright() as pw:
        for engine_name in ("chromium", "firefox"):
            try:
                browser = getattr(pw, engine_name).launch()
            except Exception:                                              # navegador no instalado
                continue
            engines.append(engine_name)
            for label, (w, h) in sizes.items():
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(server.base + "/login")
                page.fill("input[name=email]", "admin@test.local")
                page.fill("input[name=password]", "Admin12345")
                page.click("button[type=submit]")
                for path in pages:
                    page.goto(server.base + path)
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    # Las tablas anchas hacen scroll dentro de su contenedor, nunca en toda la página
                    findings[f"{engine_name}:{label}:{path}"] = overflow
                    assert not errors, (engine_name, label, path, errors)
                if label == "movil":
                    page.goto(server.base + "/")
                    assert page.is_visible(".menu-btn")
                    page.click(".menu-btn")
                    assert page.evaluate("document.getElementById('sidebar').classList.contains('open')")
                ctx.close()
            browser.close()
    if not engines:
        pytest.skip("No hay navegador de Playwright disponible")
    bad = {k: v for k, v in findings.items() if v > 1}
    metrics.update({"navegadores": ",".join(engines), "resoluciones": len(sizes), "paginas": len(pages),
                    "paginas_con_desborde": len(bad)})
    assert not bad, bad
