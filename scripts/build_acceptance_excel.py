"""Genera docs/acceptance/StockTrack_Pruebas_de_Aceptacion.xlsx a partir de results.json.

Uso:  python -m pytest tests && python scripts/build_acceptance_excel.py
Los conteos del resumen son fórmulas (COUNTIFS) sobre la hoja «Casos».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.acceptance.catalog import CASES, CRITERIA  # noqa: E402

RESULTS = ROOT / "docs" / "acceptance" / "results.json"
OUT = ROOT / "docs" / "acceptance" / "StockTrack_Pruebas_de_Aceptacion.xlsx"

NAVY, TEAL, GREY = "0F2742", "0E7F8A", "E8EEF4"
FONT = "Arial"
STATUS = {"passed": "Aprobado", "failed": "Fallido", "skipped": "Omitido"}
thin = Side(style="thin", color="C9D3DE")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def font(**kw):
    return Font(name=FONT, size=kw.pop("size", 10), **kw)


def header(ws, row, labels, widths=None):
    for col, label in enumerate(labels, 1):
        c = ws.cell(row, col, label)
        c.font = font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[row].height = 30
    for col, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(col)].width = w


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    by_id = {r["case_id"]: r for r in data["results"]}
    missing = [c["id"] for c in CASES if c["id"] not in by_id]
    if missing:
        raise SystemExit(f"Faltan resultados para: {missing}. Ejecuta primero: python -m pytest tests")

    wb = Workbook()

    # ---------------------------------------------------------------- Casos
    cases = wb.active
    cases.title = "Casos"
    labels = ["ID", "Criterio", "Caso de prueba", "Precondiciones", "Pasos", "Resultado esperado",
              "Resultado (automatizado)", "Duración (s)", "Evidencia (prueba)", "Aprobación del cliente", "Observaciones"]
    cases["A1"] = "StockTrack · Casos de prueba de aceptación"
    cases["A1"].font = font(bold=True, size=15, color=NAVY)
    cases["A2"] = (f"Resultados de la ejecución automatizada del {data['generated_at'][:16].replace('T', ' ')} "
                   f"(Python {data['environment']['python']}, base de datos: {data['environment']['database']}).")
    cases["A2"].font = font(size=9, color="5B6B7E")
    header(cases, 4, labels, [10, 10, 34, 34, 40, 46, 16, 12, 44, 18, 36])
    first = 5
    for i, case in enumerate(CASES):
        row = first + i
        res = by_id[case["id"]]
        values = [case["id"], case["criterion"], case["title"], case["preconditions"], case["steps"],
                  case["expected"], STATUS[res["outcome"]], res["duration_s"], res["test"], "Pendiente",
                  res["message"][:200] if res["outcome"] != "passed" else ""]
        for col, v in enumerate(values, 1):
            c = cases.cell(row, col, v)
            c.font = font(bold=(col == 1))
            c.alignment = Alignment(vertical="top", wrap_text=True,
                                    horizontal="center" if col in (1, 2, 7, 8, 10) else "left")
            c.border = BORDER
        cases.cell(row, 8).number_format = "0.00"
        cases.row_dimensions[row].height = 62
    last = first + len(CASES) - 1
    status_rng = f"G{first}:G{last}"
    cases.conditional_formatting.add(status_rng, CellIsRule(operator="equal", formula=['"Aprobado"'],
        fill=PatternFill("solid", bgColor="DCEFE3"), font=Font(name=FONT, bold=True, color="166534")))
    cases.conditional_formatting.add(status_rng, CellIsRule(operator="equal", formula=['"Fallido"'],
        fill=PatternFill("solid", bgColor="F8D9D6"), font=Font(name=FONT, bold=True, color="9B1C1C")))
    cases.conditional_formatting.add(status_rng, CellIsRule(operator="equal", formula=['"Omitido"'],
        fill=PatternFill("solid", bgColor="FFF0D6"), font=Font(name=FONT, bold=True, color="92400E")))
    cases.conditional_formatting.add(f"J{first}:J{last}", CellIsRule(operator="equal", formula=['"Aceptado"'],
        fill=PatternFill("solid", bgColor="DCEFE3"), font=Font(name=FONT, bold=True, color="166534")))
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1='"Pendiente,Aceptado,Rechazado"', allow_blank=False)
    dv.error, dv.errorTitle = "Elige Pendiente, Aceptado o Rechazado", "Valor no válido"
    cases.add_data_validation(dv)
    dv.add(f"J{first}:J{last}")
    cases.freeze_panes = "D5"
    cases.auto_filter.ref = f"A4:K{last}"
    cases["A3"] = "Columna J: el cliente registra su aceptación formal (lista desplegable). Es la única columna que se edita a mano."
    cases["A3"].font = font(size=9, italic=True, color="5B6B7E")

    # -------------------------------------------------------------- Resumen
    summary = wb.create_sheet("Resumen", 0)
    summary["A1"] = "StockTrack · Control total de inventarios"
    summary["A1"].font = font(bold=True, size=16, color=NAVY)
    summary["A2"] = "Resumen del estado de las pruebas de aceptación"
    summary["A2"].font = font(size=11, color=TEAL, bold=True)
    summary["A3"] = "Cliente: tienda de electrónicos, Monterrey, N.L.  ·  Los conteos se calculan con fórmulas sobre la hoja «Casos»."
    summary["A3"].font = font(size=9, color="5B6B7E")
    header(summary, 5, ["Criterio", "Descripción", "Casos", "Aprobados", "Fallidos", "Omitidos", "% aprobado", "Aceptación del cliente"],
           [10, 62, 10, 12, 10, 11, 13, 22])
    crit_first = 6
    for i, (cid, desc) in enumerate(CRITERIA.items()):
        r = crit_first + i
        summary.cell(r, 1, cid)
        summary.cell(r, 2, desc)
        summary.cell(r, 3, f'=COUNTIF(Casos!$B${first}:$B${last},A{r})')
        for col, label in ((4, "Aprobado"), (5, "Fallido"), (6, "Omitido")):
            summary.cell(r, col, f'=COUNTIFS(Casos!$B${first}:$B${last},$A{r},Casos!$G${first}:$G${last},"{label}")')
        summary.cell(r, 7, f"=IF(C{r}=0,0,D{r}/C{r})")
        summary.cell(r, 8, f'=COUNTIFS(Casos!$B${first}:$B${last},$A{r},Casos!$J${first}:$J${last},"Aceptado")&" de "&C{r}')
    crit_last = crit_first + len(CRITERIA) - 1
    total = crit_last + 1
    summary.cell(total, 1, "TOTAL")
    summary.cell(total, 2, "Todos los casos")
    for col in (3, 4, 5, 6):
        L = get_column_letter(col)
        summary.cell(total, col, f"=SUM({L}{crit_first}:{L}{crit_last})")
    summary.cell(total, 7, f"=IF(C{total}=0,0,D{total}/C{total})")
    summary.cell(total, 8, f'=COUNTIF(Casos!$J${first}:$J${last},"Aceptado")&" de "&C{total}')
    for r in range(crit_first, total + 1):
        for col in range(1, 9):
            c = summary.cell(r, col)
            c.font = font(bold=(r == total or col == 1))
            c.border = BORDER
            c.alignment = Alignment(vertical="center", wrap_text=True,
                                    horizontal="left" if col == 2 else "center")
            if r == total:
                c.fill = PatternFill("solid", fgColor=GREY)
        summary.cell(r, 7).number_format = "0%"
        summary.row_dimensions[r].height = 30
    summary.conditional_formatting.add(f"E{crit_first}:E{total}", CellIsRule(operator="greaterThan", formula=["0"],
        fill=PatternFill("solid", bgColor="F8D9D6"), font=Font(name=FONT, bold=True, color="9B1C1C")))

    notes = [
        "Lo que significa «Aprobado»: la prueba automatizada pasó contra el código entregado, en el entorno indicado en la hoja «Alcance».",
        "La aceptación formal es del cliente: se registra en la columna J de la hoja «Casos» y se refleja aquí.",
        "Criterios PA-01 a PA-03: pruebas de aceptación pedidas por el cliente. RN-01 y RN-02: requerimiento no funcional y restricción del proyecto.",
    ]
    for i, text in enumerate(notes):
        c = summary.cell(total + 2 + i, 1, text)
        c.font = font(size=9, color="5B6B7E")
    summary.freeze_panes = "A6"
    summary.sheet_view.showGridLines = False

    # -------------------------------------------------------------- Métricas
    met = wb.create_sheet("Metricas")
    met["A1"] = "Mediciones registradas por las pruebas"
    met["A1"].font = font(bold=True, size=14, color=NAVY)
    header(met, 3, ["ID", "Caso de prueba", "Medición", "Valor"], [10, 46, 36, 30])
    r = 4
    for case in CASES:
        for key, value in by_id[case["id"]]["metrics"].items():
            for col, v in enumerate([case["id"], case["title"], key.replace("_", " "), value], 1):
                c = met.cell(r, col, v)
                c.font = font()
                c.border = BORDER
                c.alignment = Alignment(vertical="top", wrap_text=True, horizontal="left" if col != 4 else "right")
            r += 1
    met.freeze_panes = "A4"
    met.auto_filter.ref = f"A3:D{r - 1}"

    # --------------------------------------------------------------- Alcance
    scope = wb.create_sheet("Alcance")
    scope.column_dimensions["A"].width = 30
    scope.column_dimensions["B"].width = 110
    scope["A1"] = "Alcance, entorno y limitaciones"
    scope["A1"].font = font(bold=True, size=14, color=NAVY)
    rows = [
        ("Cómo reproducir", "python -m pytest tests   →   python scripts/build_acceptance_excel.py   →   python scripts/build_status_pptx.py"),
        ("Base de datos probada", "SQLite (modo WAL). El código incluye esquema y soporte para PostgreSQL, pero NO se ejecutó contra PostgreSQL en esta corrida (no había controlador psycopg2 ni red para instalarlo)."),
        ("Correo", "Se probó el envío SMTP real contra un servidor SMTP de prueba en memoria (entrega, contenido, fallas). No se probó contra un proveedor real (Gmail, SES, etc.) ni con TLS."),
        ("Concurrencia (PA-03)", "10 usuarios con sesión propia contra un servidor HTTP real con hilos, por loopback, en un solo equipo. No equivale a una prueba de carga de producción con red y servidor dedicado."),
        ("Mediana vs. un usuario", "Con 10 usuarios la mediana de latencia sube respecto a un solo usuario (ver hoja Metricas); el criterio aplicado fue absoluto: 0 errores, p95 de páginas ≤ 1 s y reporte Excel ≤ 3 s."),
        ("Capacidad (RN-02)", "100,000 productos activos cargados en bloque; páginas medidas ≤ 2 s. El PDF se limita a 5,000 filas (configurable); para más filas se usa Excel."),
        ("Logo y metodología", "El logo se entrega en SVG/PNG. Kanban (tablero) e ISO 9001 (matriz) están en la carpeta docs/ del proyecto; la certificación ISO 9001 es de la organización, no del software."),
    ]
    for i, (k, v) in enumerate(rows, 3):
        a, b = scope.cell(i, 1, k), scope.cell(i, 2, v)
        a.font, b.font = font(bold=True), font()
        for c in (a, b):
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = BORDER
        scope.row_dimensions[i].height = 44

    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = TEAL if ws.title == "Resumen" else NAVY
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(OUT)
    print("Guardado:", OUT)


if __name__ == "__main__":
    main()
