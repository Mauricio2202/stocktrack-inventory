"""PA-01 · Los reportes deben generarse correctamente en formatos PDF y Excel."""
from __future__ import annotations

import io

import openpyxl
import pytest
from pypdf import PdfReader

from tests.helpers.web import login

CATALOG = [  # (sku, categoría, stock, mínimo, costo, precio)
    *[(f"TEL-{i:03d}", "Teléfonos", 10 + i, 3, "1000", "1500.50") for i in range(1, 11)],
    *[(f"LAP-{i:03d}", "Laptops", 5 + i, 2, "9000.25", "12999") for i in range(1, 11)],
    *[(f"ACC-{i:03d}", "Accesorios", 40 + i, 10, "99.9", "199") for i in range(1, 10)],
    ("ESC-001", "Accesorios", 2, 5, "50", "99"),  # en escasez
]


@pytest.fixture
def seeded(app, make_product, move, conn):
    ids = {}
    for sku, category, qty, minimum, cost, price in CATALOG:
        ids[sku] = make_product(sku, name=f"Producto {sku}", category=category, stock_qty=qty,
                                min_stock=minimum, cost=cost, price=price)
    move(ids["TEL-001"], "salida", 3, reference="VTA-1")
    move(ids["LAP-002"], "entrada", 4, reference="OC-7")
    move(ids["ACC-003"], "ajuste", 20, notes="Conteo físico")
    return ids


def _expected_totals(conn):
    row = conn.one("SELECT SUM(stock) AS u, SUM(stock * cost_cents) AS c, SUM(stock * price_cents) AS p, "
                   "COUNT(*) AS n FROM products WHERE is_active = 1")
    return row


def _download(client, url):
    response = client.get(url)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    return response


@pytest.fixture
def reader_client(app, seeded):
    client = app.test_client()
    assert login(client, "consulta").status_code == 302  # el rol de solo lectura también descarga reportes
    return client


@pytest.mark.acceptance("PA-01.1")
def test_inventory_pdf(reader_client, conn, metrics):
    response = _download(reader_client, "/reportes/inventario.pdf")
    assert response.mimetype == "application/pdf"
    assert "attachment" in response.headers["Content-Disposition"] and ".pdf" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"%PDF-")
    pdf = PdfReader(io.BytesIO(response.data))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    totals = _expected_totals(conn)
    assert "Reporte de inventario" in text
    for sku, *_ in CATALOG:
        assert sku in text, f"falta {sku} en el PDF"
    assert f"{totals['n']:,}" in text and f"{totals['u']:,}" in text            # KPIs: productos y unidades
    assert f"${totals['c'] / 100:,.2f}" in text                                    # valor a costo
    assert f"${totals['p'] / 100:,.2f}" in text                                    # valor a precio
    assert "ESCASEZ" in text and f"Página 1 de {len(pdf.pages)}" in text
    metrics.update({"pdf_paginas": len(pdf.pages), "pdf_bytes": len(response.data), "filas": totals["n"]})


@pytest.mark.acceptance("PA-01.2")
def test_inventory_xlsx(reader_client, conn, metrics):
    response = _download(reader_client, "/reportes/inventario.xlsx")
    assert response.mimetype.endswith("spreadsheetml.sheet")
    formulas = openpyxl.load_workbook(io.BytesIO(response.data))["Inventario"]
    values = openpyxl.load_workbook(io.BytesIO(response.data), data_only=True)["Inventario"]
    assert [c.value for c in formulas[4]][:8] == ["SKU", "Producto", "Categoría", "Marca", "Ubicación", "Stock", "Mínimo", "Estado"]
    data_rows = [r for r in range(5, formulas.max_row + 1) if formulas.cell(r, 1).value not in (None, "TOTAL")]
    assert len(data_rows) == len(CATALOG)
    first = data_rows[0]
    assert formulas.cell(first, 11).value == f"=F{first}*I{first}"                 # fórmula, no valor fijo
    total_row = data_rows[-1] + 1
    assert formulas.cell(total_row, 1).value == "TOTAL"
    assert str(formulas.cell(total_row, 6).value).startswith("=SUM(")
    totals = _expected_totals(conn)
    assert values.cell(total_row, 6).value == totals["u"]
    assert round(values.cell(total_row, 11).value, 2) == round(totals["c"] / 100, 2)
    assert round(values.cell(total_row, 12).value, 2) == round(totals["p"] / 100, 2)
    status = {values.cell(r, 1).value: values.cell(r, 8).value for r in data_rows}
    assert status["ESC-001"] == "ESCASEZ" and status["TEL-001"] == "OK"
    assert formulas.auto_filter.ref and formulas.freeze_panes == "C5"
    metrics.update({"xlsx_filas": len(data_rows), "xlsx_bytes": len(response.data)})


@pytest.mark.acceptance("PA-01.3")
def test_movements_pdf(reader_client, conn, metrics):
    today = _today(reader_client)
    response = _download(reader_client, f"/reportes/movimientos.pdf?desde={today}&hasta={today}")
    assert response.data.startswith(b"%PDF-")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(response.data)).pages)
    total = conn.scalar("SELECT COUNT(*) FROM stock_movements")
    assert "Reporte de movimientos de inventario" in text
    assert f"{total:,}" in text                          # KPI «Movimientos»
    for reference in ("VTA-1", "OC-7"):
        assert reference in text
    assert "Entrada" in text and "Salida" in text and "Ajuste" in text
    metrics.update({"movimientos": total})


@pytest.mark.acceptance("PA-01.4")
def test_movements_xlsx_and_filters(reader_client, conn, metrics):
    today = _today(reader_client)
    response = _download(reader_client, f"/reportes/movimientos.xlsx?desde={today}&hasta={today}")
    sheet = openpyxl.load_workbook(io.BytesIO(response.data), data_only=True)["Movimientos"]
    rows = [r for r in range(5, sheet.max_row + 1) if sheet.cell(r, 1).value]
    assert len(rows) == conn.scalar("SELECT COUNT(*) FROM stock_movements")
    only_out = _download(reader_client, f"/reportes/movimientos.xlsx?tipo=salida&desde={today}&hasta={today}")
    sheet = openpyxl.load_workbook(io.BytesIO(only_out.data), data_only=True)["Movimientos"]
    kinds = {sheet.cell(r, 5).value for r in range(5, sheet.max_row + 1) if sheet.cell(r, 1).value}
    assert kinds == {"Salida"}
    future = _download(reader_client, "/reportes/movimientos.xlsx?desde=2099-01-01&hasta=2099-01-31")
    sheet = openpyxl.load_workbook(io.BytesIO(future.data), data_only=True)["Movimientos"]
    assert not [r for r in range(5, sheet.max_row + 1) if sheet.cell(r, 1).value]   # periodo vacío -> hoja sin datos
    bad = reader_client.get("/reportes/movimientos.pdf?desde=2026-02-10&hasta=2026-02-01")
    assert bad.status_code == 302                                                      # rango invertido -> aviso
    metrics.update({"movimientos_excel": len(rows)})


@pytest.mark.acceptance("PA-01.5")
def test_filters_match_between_formats(app, reader_client, metrics):
    for query, expected_skus in (("categoria=Laptops", {s for s, c, *_ in CATALOG if c == "Laptops"}),
                                 ("escasez=1", {"ESC-001"})):
        xlsx = _download(reader_client, f"/reportes/inventario.xlsx?{query}")
        sheet = openpyxl.load_workbook(io.BytesIO(xlsx.data), data_only=True)["Inventario"]
        in_excel = {sheet.cell(r, 1).value for r in range(5, sheet.max_row + 1)} - {None, "TOTAL"}
        pdf = _download(reader_client, f"/reportes/inventario.pdf?{query}")
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.data)).pages)
        in_pdf = {sku for sku, *_ in CATALOG if sku in text}
        assert in_excel == expected_skus == in_pdf, query
    # El PDF rechaza volúmenes por encima del máximo configurado y sugiere Excel; Excel sigue disponible.
    app.config["REPORT_PDF_MAX_ROWS"] = 5
    blocked = reader_client.get("/reportes/inventario.pdf", follow_redirects=True)
    assert "descarga la versión en Excel" in blocked.get_data(as_text=True)
    assert reader_client.get("/reportes/inventario.xlsx").status_code == 200
    assert reader_client.get("/reportes/inventario.csv").status_code == 404          # formato no soportado
    metrics.update({"filtros_verificados": 2})


def _today(client):
    from stocktrack.timeutil import now_local
    return now_local(client.application.config["TIMEZONE"]).date().isoformat()
