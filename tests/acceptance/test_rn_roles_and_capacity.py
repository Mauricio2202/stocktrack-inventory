"""RN-01 (roles) y RN-02 (capacidad de 100,000 registros activos)."""
from __future__ import annotations

import threading
import time

import pytest

from stocktrack.errors import LimitExceeded
from stocktrack.models import products
from tests.helpers.web import csrf, login, post

ROLES = ["admin", "gerente", "almacen", "consulta"]

# (método, ruta, {rol: estado esperado})
MATRIX = [
    ("GET", "/", dict.fromkeys(ROLES, 200)),
    ("GET", "/productos", dict.fromkeys(ROLES, 200)),
    ("GET", "/movimientos", dict.fromkeys(ROLES, 200)),
    ("GET", "/alertas", dict.fromkeys(ROLES, 200)),
    ("GET", "/reportes", dict.fromkeys(ROLES, 200)),
    ("GET", "/reportes/inventario.xlsx", dict.fromkeys(ROLES, 200)),
    ("GET", "/productos/nuevo", {"admin": 200, "gerente": 200, "almacen": 403, "consulta": 403}),
    ("GET", "/productos/1/editar", {"admin": 200, "gerente": 200, "almacen": 403, "consulta": 403}),
    ("GET", "/movimientos/nuevo", {"admin": 200, "gerente": 200, "almacen": 200, "consulta": 403}),
    ("GET", "/auditoria", {"admin": 200, "gerente": 200, "almacen": 403, "consulta": 403}),
    ("GET", "/usuarios", {"admin": 200, "gerente": 403, "almacen": 403, "consulta": 403}),
    ("GET", "/usuarios/nuevo", {"admin": 200, "gerente": 403, "almacen": 403, "consulta": 403}),
]
FORBIDDEN_WRITES = [  # escrituras que cada rol NO debe poder hacer
    ("/productos/1/archivar", {"almacen", "consulta"}),
    ("/productos/nuevo", {"almacen", "consulta"}),
    ("/movimientos/nuevo", {"consulta"}),
    ("/alertas/1/reconocer", {"consulta"}),
    ("/usuarios/nuevo", {"gerente", "almacen", "consulta"}),
    ("/usuarios/1/estado", {"gerente", "almacen", "consulta"}),
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
                assert post(client, path, sku="X", kind="entrada", quantity="1").status_code == 403, (role, path)
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
    post(admin, f"/productos/{ids[0]}/archivar")                                 # archivar libera un lugar
    assert post(admin, "/productos/nuevo", **form).status_code == 302
    restored = admin.post(f"/productos/{ids[0]}/restaurar", data={"csrf_token": csrf(admin)}, follow_redirects=True)
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
    rows = [(f"BULK-{n:06d}", f"Producto de volumen {n}", f"Categoría {n % 20:02d}", f"Marca {n % 50}",
             (n * 7) % 40, 8 if n % 100 == 0 else 5, 15_000, 22_000, "2026-01-01 00:00:00", "2026-01-01 00:00:00")
            for n in range(1, total + 1)]
    started = time.perf_counter()
    with conn.transaction():
        conn.executemany("INSERT INTO products (sku, name, category, brand, stock, min_stock, cost_cents, price_cents, "
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
    assert timed("filtro_categoria_ms", "/productos?categoria=Categor%C3%ADa+07&orden=stock&dir=desc").status_code == 200
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
    low = admin.get("/reportes/inventario.pdf?escasez=1&categoria=Categor%C3%ADa+00")   # filtrado: sí cabe en PDF
    assert low.status_code == 200 and low.data.startswith(b"%PDF-")

    metrics.update({"registros_activos": total, "carga_masiva_s": round(load_s, 2), **timings,
                    "excel_bytes": len(excel.data), "excel_filas": rows_in_excel})
    for label, value in timings.items():
        if label.endswith("_ms"):
            assert value <= 2000, f"{label} = {value} ms"
    assert timings["excel_100k_s"] <= 60
