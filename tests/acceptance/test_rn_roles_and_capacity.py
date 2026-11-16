"""RN-01 (roles) y RN-02 (capacidad de 100,000 registros activos)."""
from __future__ import annotations

import threading
import time

import pytest

from stocktrack.errors import LimitExceeded
from stocktrack.models import products
from tests.helpers.web import csrf, login, post

ROLES = ["admin", "encargado", "consulta"]
ALL = dict.fromkeys(ROLES, 200)


def only(*allowed, ok=200, no=403):
    return {role: (ok if role in allowed else no) for role in ROLES}


# (método, ruta, {rol: estado esperado}) — requerimientos por usuario
MATRIX = [
    ("GET", "/", ALL),                                                 # RF-02, RF-18, RF-30: cada rol su panel
    ("GET", "/productos", ALL),                                        # RF-05, RF-19, RF-31
    ("GET", "/productos/1", ALL),
    ("GET", "/productos?q=ROL", ALL),                                  # RF-32
    ("GET", "/categorias", ALL),                                       # RF-33
    ("GET", "/movimientos", only("admin", "encargado")),               # RF-10, RF-23
    ("GET", "/alertas", only("admin", "encargado")),                   # RF-11, RF-24
    ("GET", "/reportes", only("admin", "encargado")),                  # RF-12, RF-27
    ("GET", "/reportes/inventario.xlsx", only("admin", "encargado")),
    ("GET", "/reportes/inventario.pdf", only("admin", "encargado")),
    ("GET", "/reportes/movimientos.pdf", only("admin", "encargado")),
    ("GET", "/reportes/especial/diario.pdf?dia=2026-01-01", only("admin")),        # RF-13
    ("GET", "/reportes/especial/mensual.xlsx?mes=2026-01", only("admin")),
    ("GET", "/reportes/especial/reservas.pdf", only("admin")),
    ("GET", "/reportes/especial/devoluciones.xlsx", only("admin")),
    ("GET", "/reportes/verificar", only("admin", "encargado")),
    ("GET", "/productos/nuevo", only("admin")),                        # RF-06
    ("GET", "/productos/1/editar", only("admin")),                     # RF-07, RF-09
    ("GET", "/movimientos/nuevo", only("encargado")),                  # RF-20..22
    ("GET", "/movimientos/reservas", only("admin")),                   # RF-16
    ("GET", "/auditoria", only("admin")),                              # RF-15
    ("GET", "/usuarios", only("admin")),                               # RF-03
    ("GET", "/usuarios/nuevo", only("admin")),
]
FORBIDDEN_WRITES = [  # escrituras que cada rol NO debe poder hacer
    ("/productos/1/desactivar", {"encargado", "consulta"}),
    ("/productos/nuevo", {"encargado", "consulta"}),
    ("/categorias", {"encargado", "consulta"}),
    ("/categorias/1/estado", {"encargado", "consulta"}),
    ("/movimientos/nuevo", {"admin", "consulta"}),
    ("/movimientos/1/validar", {"encargado", "consulta"}),
    ("/alertas/1/atender", {"admin", "consulta"}),
    ("/usuarios/nuevo", {"encargado", "consulta"}),
    ("/usuarios/1/estado", {"encargado", "consulta"}),
]


@pytest.mark.acceptance("RN-01.1")
def test_role_permission_matrix(app, make_product, metrics):
    make_product("ROL-001", stock_qty=5, min_stock=2)
    checks = 0
    for role in ROLES:
        client = app.test_client()
        assert login(client, role).status_code == 302
        for method, path, expected in MATRIX:
            status = client.open(path, method=method).status_code
            assert status == expected[role], f"{role} {method} {path}: {status} != {expected[role]}"
            checks += 1
        for path, denied in FORBIDDEN_WRITES:
            if role in denied:
                assert post(client, path, sku="X", kind="compra", quantity="1").status_code == 403, (role, path)
                checks += 1
    anonymous = app.test_client()
    for _, path, _ in MATRIX:
        response = anonymous.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
        checks += 1
    assert anonymous.post("/movimientos/nuevo", data={}).status_code in (302, 400)   # sin sesión ni token
    metrics.update({"verificaciones": checks, "roles": len(ROLES)})


@pytest.mark.acceptance("RN-02.1")
def test_active_record_cap_is_enforced(app, make_product, conn, actor, metrics):
    app.config["MAX_ACTIVE_RECORDS"] = 3
    ids = [make_product(f"CAP-{i}") for i in range(1, 4)]
    admin = app.test_client()
    login(admin, "admin")
    form = {"sku": "CAP-4", "name": "Cuarto producto", "min_stock": "0", "cost": "1", "price": "2", "initial_stock": "0"}
    response = post(admin, "/productos/nuevo", **form)
    assert response.status_code == 409 and "capacidad máxima de 3" in response.get_data(as_text=True)
    assert products.count_active(conn) == 3
    post(admin, f"/productos/{ids[0]}/desactivar")                               # desactivar libera un lugar
    assert post(admin, "/productos/nuevo", **form).status_code == 302
    restored = admin.post(f"/productos/{ids[0]}/activar", data={"csrf_token": csrf(admin)}, follow_redirects=True)
    assert "capacidad máxima de 3" in restored.get_data(as_text=True)            # restaurar con el catálogo lleno
    assert products.get(conn, ids[0])["is_active"] == 0                          # ...no se permite
    # Condición de carrera: 10 altas simultáneas con 2 lugares libres => exactamente 2 entran.
    app.config["MAX_ACTIVE_RECORDS"] = products.count_active(conn) + 2
    db = app.extensions["stocktrack_db"]
    outcomes: list[str] = []
    barrier = threading.Barrier(10)

    def create(n: int):
        c = db.connect()
        try:
            data = products.clean_form({"sku": f"RACE-{n}", "name": f"Carrera {n}", "min_stock": 0, "cost": 1,
                                        "price": 2}, with_initial_stock=True)
            barrier.wait(10)
            products.create(c, data, actor, app.config["MAX_ACTIVE_RECORDS"])
            outcomes.append("ok")
        except LimitExceeded:
            outcomes.append("limit")
        finally:
            c.close()

    threads = [threading.Thread(target=create, args=(n,)) for n in range(10)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert outcomes.count("ok") == 2 and outcomes.count("limit") == 8, outcomes
    assert products.count_active(conn) == app.config["MAX_ACTIVE_RECORDS"]
    metrics.update({"limite_probado": 3, "carrera_aceptadas": 2, "carrera_rechazadas": 8})


@pytest.mark.acceptance("RN-02.2")
def test_performance_with_100k_active_records(app, conn, actor, metrics):
    total = 100_000
    with conn.transaction():
        conn.executemany("INSERT INTO categories (name, is_active, created_at) VALUES (?, 1, ?)",
                         [(f"Categoría {n:02d}", "2026-01-01 00:00:00") for n in range(20)])
    cat_ids = [r["id"] for r in conn.all("SELECT id FROM categories ORDER BY name")]
    rows = [(f"BULK-{n:06d}", f"Producto de volumen {n}", cat_ids[n % 20], f"Marca {n % 50}",
             (n * 7) % 40, 8 if n % 100 == 0 else 5, 15_000, 22_000, "2026-01-01 00:00:00", "2026-01-01 00:00:00")
            for n in range(1, total + 1)]
    started = time.perf_counter()
    with conn.transaction():
        conn.executemany("INSERT INTO products (sku, name, category_id, brand, stock, min_stock, cost_cents, price_cents, "
                         "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)", rows)
    load_s = time.perf_counter() - started
    assert products.count_active(conn) == total
    with pytest.raises(LimitExceeded):                                           # el registro 100,001 se rechaza
        products.create(conn, products.clean_form({"sku": "EXTRA-1", "name": "Extra", "cost": 1, "price": 2}),
                        actor, app.config["MAX_ACTIVE_RECORDS"])

    admin = app.test_client()
    login(admin, "admin")
    timings: dict[str, float] = {}

    def timed(label: str, path: str) -> object:
        start = time.perf_counter()
        response = admin.get(path)
        timings[label] = round((time.perf_counter() - start) * 1000, 1)
        return response

    assert timed("panel_ms", "/").status_code == 200
    assert timed("listado_ms", "/productos").status_code == 200
    assert timed("pagina_ultima_ms", "/productos?page=4000").status_code == 200
    assert timed("busqueda_ms", "/productos?q=volumen+99999").status_code == 200
    assert timed("filtro_categoria_ms", f"/productos?categoria={cat_ids[7]}&orden=stock&dir=desc").status_code == 200
    assert timed("escasez_ms", "/productos?escasez=1").status_code == 200

    start = time.perf_counter()
    excel = admin.get("/reportes/inventario.xlsx")
    timings["excel_100k_s"] = round(time.perf_counter() - start, 2)
    assert excel.status_code == 200 and len(excel.data) > 1_000_000
    import io

    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(excel.data), read_only=True)["Inventario"]
    rows_in_excel = sum(1 for row in sheet.iter_rows(min_row=5, max_col=1, values_only=True)
                        if row[0] and row[0] != "TOTAL")
    assert rows_in_excel == total

    blocked = admin.get("/reportes/inventario.pdf", follow_redirects=True)
    assert "descarga la versión en Excel" in blocked.get_data(as_text=True)
    low = admin.get(f"/reportes/inventario.pdf?escasez=1&categoria={cat_ids[0]}")   # filtrado: sí cabe en PDF
    assert low.status_code == 200 and low.data.startswith(b"%PDF-")

    metrics.update({"registros_activos": total, "carga_masiva_s": round(load_s, 2), **timings,
                    "excel_bytes": len(excel.data), "excel_filas": rows_in_excel})
    for label, value in timings.items():
        if label.endswith("_ms"):
            assert value <= 2000, f"{label} = {value} ms"
    assert timings["excel_100k_s"] <= 60
