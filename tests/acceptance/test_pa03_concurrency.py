"""PA-03 · El sistema debe soportar hasta 10 usuarios concurrentes sin pérdida de rendimiento.

Se levanta un servidor HTTP real con hilos y 10 usuarios con sesión propia que trabajan a la vez.
Nota: estas pruebas usan SQLite; ver docs/acceptance/README.md para el alcance respecto de PostgreSQL.
"""
from __future__ import annotations

import random

import pytest

from stocktrack.models import products, users
from tests.helpers.live import User, live, run_parallel, summarize

N_USERS = 10
ROUNDS = 15
PAGE_LABELS = {"panel", "buscar", "detalle", "alertas", "movimientos"}
ROLE_CYCLE = ["admin", "gerente", "almacenista"]
INITIAL_STOCK = 200


@pytest.fixture
def team(app, conn):
    """Diez usuarios reales con sesión propia (admin, gerente y almacenista)."""
    names = []
    for i in range(1, N_USERS + 1):
        name = f"user{i:02d}"
        users.create(conn, username=name, full_name=f"Usuario {i}", email=None, password="Concurrente123",
                     role=ROLE_CYCLE[i % 3])
        names.append(name)
    return names


@pytest.fixture
def catalog500(conn):
    """500 productos cargados en bloque, sin movimiento de alta (stock base = INITIAL_STOCK)."""
    rows = [(f"P{n:05d}", f"Producto {n}", f"Categoría {n % 12}", INITIAL_STOCK, 10 if n % 25 == 0 else 5,
             10_000, 15_000, "2026-01-01 00:00:00", "2026-01-01 00:00:00") for n in range(1, 501)]
    with conn.transaction():
        conn.executemany("INSERT INTO products (sku, name, category, stock, min_stock, cost_cents, price_cents, "
                         "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)", rows)


def _login_all(server, names):
    crowd = [User(server.base, name, "Concurrente123") for name in names]
    run_parallel(crowd, lambda user, i: user.login())
    assert all(u.token for u in crowd), [e for u in crowd for e in u.errors]
    return crowd


def _round(user: User, rng: random.Random, product_ids: list[int], skus: list[str], report: bool):
    user.get("panel", "/")
    user.get("buscar", f"/productos?q=Producto+{rng.randint(1, 500)}")
    user.get("detalle", f"/productos/{rng.choice(product_ids)}")
    sku = rng.choice(skus)
    kind = rng.choice(["entrada", "salida", "salida"])
    user.post("movimiento", "/movimientos/nuevo", sku=sku, kind=kind, quantity=str(rng.randint(1, 4)),
              reference="CARGA")
    user.get("alertas", "/alertas")
    user.get("movimientos", "/movimientos?tipo=salida")
    if report:
        user.get("reporte-xlsx", "/reportes/inventario.xlsx")


def stock_mismatches(conn, base: int = 0) -> list[dict]:
    """Productos cuyo stock no coincide con `base` + suma de sus variaciones (o con stock negativo)."""
    return conn.all(
        "SELECT p.id, p.stock, COALESCE(m.s, 0) AS total FROM products p "
        "LEFT JOIN (SELECT product_id, SUM(delta) AS s FROM stock_movements GROUP BY product_id) m "
        "ON m.product_id = p.id WHERE p.stock <> ? + COALESCE(m.s, 0) OR p.stock < 0", (base,))


def _chain_gaps(conn, product_ids) -> int:
    gaps = 0
    for pid in product_ids:
        previous = None
        for row in conn.all("SELECT stock_before, stock_after, delta FROM stock_movements "
                            "WHERE product_id = ? ORDER BY id", (pid,)):
            assert row["stock_after"] - row["stock_before"] == row["delta"]
            if previous is not None and row["stock_before"] != previous:
                gaps += 1
            previous = row["stock_after"]
    return gaps


@pytest.mark.acceptance("PA-03.1")
def test_ten_concurrent_users_mixed_workflow(app, conn, team, catalog500, metrics):
    product_ids = [r["id"] for r in conn.all("SELECT id FROM products ORDER BY id")]
    skus = [r["sku"] for r in conn.all("SELECT sku FROM products ORDER BY id")]
    with live(app) as server:
        crowd = _login_all(server, team)

        # Línea base: un solo usuario ejecuta el mismo flujo (3 rondas).
        solo = crowd[0]
        solo.samples.clear()
        rng = random.Random(1)
        for _ in range(3):
            _round(solo, rng, product_ids, skus, report=True)
        baseline = summarize(solo.samples, PAGE_LABELS)
        for user in crowd:
            user.samples.clear()

        def work(user: User, index: int):
            rng = random.Random(100 + index)
            for n in range(ROUNDS):
                _round(user, rng, product_ids, skus, report=(n % 5 == 0))

        elapsed = run_parallel(crowd, work)

    samples = [s for u in crowd for s in u.samples]
    errors = [e for u in crowd for e in u.errors]
    bad = [(label, status) for label, _, status in samples if status >= 500 or status == 0]
    unexpected = [(label, status) for label, _, status in samples
                  if label != "movimiento" and status not in (200,)]
    pages = summarize(samples, PAGE_LABELS)
    reports = summarize(samples, {"reporte-xlsx"})
    writes = summarize(samples, {"movimiento"})
    write_codes = {status for label, _, status in samples if label == "movimiento"}

    metrics.update({
        "usuarios_concurrentes": N_USERS, "solicitudes": len(samples), "duracion_total_s": round(elapsed, 2),
        "paginas_mediana_ms": pages["median_ms"], "paginas_p95_ms": pages["p95_ms"], "paginas_max_ms": pages["max_ms"],
        "escrituras_p95_ms": writes["p95_ms"], "reporte_excel_p95_ms": reports["p95_ms"],
        "base_un_usuario_mediana_ms": baseline["median_ms"], "errores": len(errors) + len(bad),
        "rendimiento_solicitudes_por_s": round(len(samples) / elapsed, 1),
    })
    assert not errors, errors[:3]
    assert not bad, f"errores 5xx / conexión: {bad[:5]}"
    assert not unexpected, f"respuestas inesperadas: {unexpected[:5]}"
    assert write_codes <= {302, 422}, write_codes
    assert pages["p95_ms"] <= 1000, f"p95 de páginas {pages['p95_ms']} ms"
    assert reports["p95_ms"] <= 3000, f"p95 del reporte {reports['p95_ms']} ms"
    # Los 500 productos se cargaron sin movimiento de alta: stock = 200 + suma de variaciones.
    assert not stock_mismatches(conn, base=INITIAL_STOCK)


@pytest.mark.acceptance("PA-03.2")
def test_no_overselling_under_concurrency(app, conn, make_product, team, metrics):
    product = make_product("HOT-001", name="Producto en disputa", stock_qty=50, min_stock=0)
    with live(app) as server:
        crowd = _login_all(server, team)

        def work(user: User, index: int):
            for _ in range(10):
                user.post("salida", "/movimientos/nuevo", sku="HOT-001", kind="salida", quantity="1",
                          reference=f"U{index}")

        run_parallel(crowd, work)
    codes = [status for u in crowd for label, _, status in u.samples if label == "salida"]
    accepted, rejected = codes.count(302), codes.count(422)
    final = conn.scalar("SELECT stock FROM products WHERE id = ?", (product,))
    moved = conn.scalar("SELECT COALESCE(SUM(quantity), 0) FROM stock_movements WHERE product_id = ? AND kind = 'salida'",
                        (product,))
    metrics.update({"intentos": len(codes), "aceptadas": accepted, "rechazadas": rejected, "stock_final": final})
    assert len(codes) == 100 and accepted + rejected == 100, set(codes)
    assert accepted == 50 and rejected == 50
    assert final == 0 and moved == 50


@pytest.mark.acceptance("PA-03.3")
def test_data_integrity_after_simultaneous_writes(app, conn, make_product, team, metrics):
    hot = [make_product(f"INT-{i}", name=f"Compartido {i}", stock_qty=100, min_stock=20) for i in range(1, 6)]
    with live(app) as server:
        crowd = _login_all(server, team)

        def work(user: User, index: int):
            rng = random.Random(900 + index)
            for _ in range(30):
                kind = rng.choice(["entrada", "salida", "salida", "ajuste"])
                qty = rng.randint(1, 15) if kind != "ajuste" else rng.randint(0, 120)
                user.post("mov", "/movimientos/nuevo", sku=f"INT-{rng.randint(1, 5)}", kind=kind, quantity=str(qty))

        run_parallel(crowd, work)
    errors = [e for u in crowd for e in u.errors]
    assert not errors, errors[:3]
    server_errors = [s for u in crowd for label, _, s in u.samples if label == "mov" and s >= 500]
    assert not server_errors
    assert not stock_mismatches(conn)          # los 5 productos nacieron con movimiento de alta (stock inicial)
    gaps = _chain_gaps(conn, hot)
    open_alerts = conn.scalar("SELECT COUNT(*) FROM stock_alerts WHERE status IN ('abierta','reconocida')")
    duplicated = conn.scalar("SELECT COUNT(*) FROM (SELECT product_id FROM stock_alerts WHERE status IN "
                             "('abierta','reconocida') GROUP BY product_id HAVING COUNT(*) > 1) t")
    expected_low = conn.scalar("SELECT COUNT(*) FROM products WHERE min_stock > 0 AND stock <= min_stock")
    movements = conn.scalar("SELECT COUNT(*) FROM stock_movements")
    metrics.update({"movimientos_registrados": movements, "huecos_en_cadena": gaps,
                    "alertas_duplicadas": duplicated, "productos_en_escasez": expected_low})
    assert gaps == 0
    assert duplicated == 0
    assert open_alerts == expected_low
    assert products.count_active(conn) == 5
