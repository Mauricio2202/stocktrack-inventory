"""Generación de reportes en Excel (.xlsx) y PDF.

* Excel: xlsxwriter en modo `constant_memory`, apto para 100,000 filas.
* PDF: reportlab; limitado por `REPORT_PDF_MAX_ROWS` (para volúmenes mayores se usa Excel).
"""
from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from ..models import alerts as alerts_model
from ..models import products as products_model
from ..models import stock as stock_model
from ..timeutil import fmt_local, now_local

STATIC_IMG = Path(__file__).resolve().parent.parent / "static" / "img"
NAVY, TEAL = "#0f2742", "#0e9aa7"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KIND_ES = {"entrada": "Entrada", "salida": "Salida", "ajuste": "Ajuste"}


def stock_status(stock: int, min_stock: int) -> str:
    if stock == 0:
        return "AGOTADO"
    return "ESCASEZ" if alerts_model.is_low(stock, min_stock) else "OK"


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _stamp(config: dict) -> str:
    return now_local(config["TIMEZONE"]).strftime("%d/%m/%Y %H:%M")


# =============================================================================
# Excel
# =============================================================================
def _new_workbook(title: str):
    handle = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    handle.close()
    wb = xlsxwriter.Workbook(handle.name, {"constant_memory": True})
    wb.set_properties({"title": title, "author": "StockTrack", "company": "StockTrack",
                       "comments": "Generado por StockTrack - Control total de inventarios"})
    return wb, handle.name


def _finish(wb, path: str) -> bytes:
    wb.close()
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def _formats(wb) -> dict:
    base = {"font_name": "Arial", "font_size": 10}
    f = lambda **kw: wb.add_format({**base, **kw})  # noqa: E731
    return {
        "title": f(bold=True, font_size=16, font_color=NAVY),
        "meta": f(font_color="#5b6b7e", font_size=9),
        "head": f(bold=True, font_color="#ffffff", bg_color=NAVY, border=1, border_color="#0b1d33",
                  align="center", valign="vcenter", text_wrap=True),
        "text": f(), "int": f(num_format="#,##0"),
        "money": f(num_format='"$"#,##0.00'),
        "center": f(align="center"),
        "total_label": f(bold=True, top=2, bg_color="#e8eef4"),
        "total_int": f(bold=True, top=2, bg_color="#e8eef4", num_format="#,##0"),
        "total_money": f(bold=True, top=2, bg_color="#e8eef4", num_format='"$"#,##0.00'),
        "bad": wb.add_format({"bg_color": "#fde2e0", "font_color": "#9b1c1c", "bold": True}),
        "warn": wb.add_format({"bg_color": "#fff0d6", "font_color": "#92400e", "bold": True}),
        "good": wb.add_format({"font_color": "#166534"}),
    }


def inventory_xlsx(conn, config: dict, *, category: str = "", low_only: bool = False,
                   generated_by: str = "") -> bytes:
    wb, path = _new_workbook("Reporte de inventario - StockTrack")
    ws = wb.add_worksheet("Inventario")
    fm = _formats(wb)
    headers = ["SKU", "Producto", "Categoría", "Marca", "Ubicación", "Stock", "Mínimo", "Estado",
               "Costo unitario", "Precio unitario", "Valor a costo", "Valor a precio"]
    widths = [14, 44, 18, 16, 14, 9, 9, 11, 14, 14, 16, 16]
    kinds = [fm["text"], fm["text"], fm["text"], fm["text"], fm["text"], fm["int"], fm["int"],
             fm["center"], fm["money"], fm["money"], fm["money"], fm["money"]]
    for col, (w, fmt) in enumerate(zip(widths, kinds)):
        ws.set_column(col, col, w, fmt)

    scope = []
    if category:
        scope.append(f"Categoría: {category}")
    if low_only:
        scope.append("Solo productos en escasez")
    ws.write(0, 0, "StockTrack · Reporte de inventario", fm["title"])
    ws.write(1, 0, f"{config.get('COMPANY_NAME', '')} · Generado el {_stamp(config)}"
                   f"{' por ' + generated_by if generated_by else ''}"
                   f" · {'; '.join(scope) if scope else 'Todos los productos activos'}", fm["meta"])
    header_row, first = 3, 4
    ws.set_row(header_row, 30)
    for col, name in enumerate(headers):
        ws.write(header_row, col, name, fm["head"])

    row = first
    total_units = total_cost = total_price = 0
    for p in products_model.iter_for_report(conn, category=category, low_only=low_only):
        excel_row = row + 1
        ws.write_string(row, 0, p["sku"])
        ws.write_string(row, 1, p["name"])
        ws.write_string(row, 2, p["category"] or "")
        ws.write_string(row, 3, p["brand"] or "")
        ws.write_string(row, 4, p["location"] or "")
        ws.write_number(row, 5, p["stock"])
        ws.write_number(row, 6, p["min_stock"])
        ws.write_string(row, 7, stock_status(p["stock"], p["min_stock"]))
        ws.write_number(row, 8, p["cost_cents"] / 100)
        ws.write_number(row, 9, p["price_cents"] / 100)
        ws.write_formula(row, 10, f"=F{excel_row}*I{excel_row}", None, p["stock"] * p["cost_cents"] / 100)
        ws.write_formula(row, 11, f"=F{excel_row}*J{excel_row}", None, p["stock"] * p["price_cents"] / 100)
        total_units += p["stock"]
        total_cost += p["stock"] * p["cost_cents"]
        total_price += p["stock"] * p["price_cents"]
        row += 1

    last_data = row  # fila (0-based) siguiente al último dato
    if row > first:
        ws.autofilter(header_row, 0, row - 1, len(headers) - 1)
    ws.write(row, 0, "TOTAL", fm["total_label"])
    for col in range(1, 12):
        ws.write_blank(row, col, None, fm["total_label"])
    rng = lambda c: f"{c}{first + 1}:{c}{last_data}"  # noqa: E731
    if last_data > first:
        ws.write_formula(row, 5, f"=SUM({rng('F')})", fm["total_int"], total_units)
        ws.write_formula(row, 10, f"=SUM({rng('K')})", fm["total_money"], total_cost / 100)
        ws.write_formula(row, 11, f"=SUM({rng('L')})", fm["total_money"], total_price / 100)
        ws.conditional_format(first, 7, last_data - 1, 7, {
            "type": "cell", "criteria": "==", "value": '"AGOTADO"', "format": fm["bad"]})
        ws.conditional_format(first, 7, last_data - 1, 7, {
            "type": "cell", "criteria": "==", "value": '"ESCASEZ"', "format": fm["warn"]})
        ws.conditional_format(first, 7, last_data - 1, 7, {
            "type": "cell", "criteria": "==", "value": '"OK"', "format": fm["good"]})
    ws.freeze_panes(first, 2)
    ws.set_landscape()
    ws.set_paper(9)
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(header_row)
    return _finish(wb, path)


def movements_xlsx(conn, config: dict, *, product_id=None, kind=None, start_utc=None, end_utc=None,
                   range_label: str = "", generated_by: str = "") -> bytes:
    wb, path = _new_workbook("Reporte de movimientos - StockTrack")
    ws = wb.add_worksheet("Movimientos")
    fm = _formats(wb)
    headers = ["Folio", "Fecha y hora", "SKU", "Producto", "Tipo", "Cantidad", "Variación",
               "Stock antes", "Stock después", "Referencia", "Usuario", "Notas"]
    widths = [9, 17, 14, 40, 11, 10, 10, 11, 13, 16, 22, 36]
    kinds = [fm["int"], fm["text"], fm["text"], fm["text"], fm["center"], fm["int"], fm["int"],
             fm["int"], fm["int"], fm["text"], fm["text"], fm["text"]]
    for col, (w, fmt) in enumerate(zip(widths, kinds)):
        ws.set_column(col, col, w, fmt)
    ws.write(0, 0, "StockTrack · Reporte de movimientos de inventario", fm["title"])
    ws.write(1, 0, f"{config.get('COMPANY_NAME', '')} · Generado el {_stamp(config)}"
                   f"{' por ' + generated_by if generated_by else ''} · {range_label or 'Todo el historial'}",
             fm["meta"])
    header_row, first = 3, 4
    ws.set_row(header_row, 30)
    for col, name in enumerate(headers):
        ws.write(header_row, col, name, fm["head"])
    row = first
    for m in stock_model.iter_movements(conn, product_id=product_id, kind=kind,
                                        start_utc=start_utc, end_utc=end_utc):
        ws.write_number(row, 0, m["id"])
        ws.write_string(row, 1, fmt_local(m["created_at"], config["TIMEZONE"], "%d/%m/%Y %H:%M"))
        ws.write_string(row, 2, m["sku"])
        ws.write_string(row, 3, m["product_name"])
        ws.write_string(row, 4, KIND_ES[m["kind"]])
        ws.write_number(row, 5, m["quantity"])
        ws.write_number(row, 6, m["delta"])
        ws.write_number(row, 7, m["stock_before"])
        ws.write_number(row, 8, m["stock_after"])
        ws.write_string(row, 9, m["reference"] or "")
        ws.write_string(row, 10, m["user_name"])
        ws.write_string(row, 11, m["notes"] or "")
        row += 1
    if row > first:
        ws.autofilter(header_row, 0, row - 1, len(headers) - 1)
    ws.freeze_panes(first, 0)
    ws.set_landscape()
    ws.set_paper(9)
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(header_row)
    return _finish(wb, path)


# =============================================================================
# PDF
# =============================================================================
def _safe(text) -> str:
    """Helvetica solo dibuja WinAnsi (cp1252): se sustituyen los caracteres no soportados."""
    return str(text or "").encode("cp1252", "replace").decode("cp1252")


def _clip(text, limit: int) -> str:
    text = _safe(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _canvas_class(title: str, config: dict, generated_by: str):
    logo = str(STATIC_IMG / "logo.png")

    class PageNumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int):
            width, height = self._pagesize
            self.saveState()
            self.drawImage(logo, 1.5 * cm, height - 1.55 * cm, width=3.9 * cm, height=0.98 * cm,
                           preserveAspectRatio=True, mask="auto")
            self.setFont("Helvetica-Bold", 11)
            self.setFillColor(colors.HexColor(NAVY))
            self.drawRightString(width - 1.5 * cm, height - 1.05 * cm, _safe(title))
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#5b6b7e"))
            self.drawRightString(width - 1.5 * cm, height - 1.45 * cm, _safe(config.get("COMPANY_NAME", "")))
            self.setStrokeColor(colors.HexColor(TEAL))
            self.setLineWidth(1.2)
            self.line(1.5 * cm, height - 1.75 * cm, width - 1.5 * cm, height - 1.75 * cm)
            self.setStrokeColor(colors.HexColor("#c9d3de"))
            self.setLineWidth(0.5)
            self.line(1.5 * cm, 1.25 * cm, width - 1.5 * cm, 1.25 * cm)
            self.setFont("Helvetica", 7.5)
            left = f"StockTrack · Control total de inventarios · Generado el {_stamp(config)}"
            if generated_by:
                left += f" por {_safe(generated_by)}"
            self.drawString(1.5 * cm, 0.8 * cm, left)
            self.drawRightString(width - 1.5 * cm, 0.8 * cm, f"Página {self._pageNumber} de {total}")
            self.restoreState()

    return PageNumberedCanvas


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15,
                             textColor=colors.HexColor(NAVY), spaceAfter=2),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontName="Helvetica", fontSize=8.5,
                               textColor=colors.HexColor("#5b6b7e"), leading=11),
    }


def _kpi_table(items: list[tuple[str, str]], width: float) -> LongTable:
    col = width / len(items)
    data = [[label for label, _ in items], [value for _, value in items]]
    table = LongTable(data, colWidths=[col] * len(items))
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica", 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5b6b7e")),
        ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 13), ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor(NAVY)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef3f8")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d3de")),
        ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _main_table(header: list[str], rows: list[list], widths: list[float], numeric_cols: set[int],
                row_colors: dict[int, str] | None = None) -> LongTable:
    table = LongTable([header] + rows, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fa")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde4ec")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for col in numeric_cols:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    for index, color in (row_colors or {}).items():
        style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor(color)))
    table.setStyle(TableStyle(style))
    return table


def _build_pdf(title: str, config: dict, generated_by: str, story: list) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=2.2 * cm, bottomMargin=1.6 * cm, title=title, author="StockTrack",
                            subject="Reporte generado por StockTrack")
    doc.build(story, canvasmaker=_canvas_class(title, config, generated_by))
    return buffer.getvalue()


def inventory_pdf(conn, config: dict, *, category: str = "", low_only: bool = False,
                  generated_by: str = "") -> bytes:
    styles = _styles()
    rows, row_colors = [], {}
    units = cost = price = low = 0
    for index, p in enumerate(products_model.iter_for_report(conn, category=category, low_only=low_only), 1):
        status = stock_status(p["stock"], p["min_stock"])
        if status != "OK":
            low += 1
            row_colors[index] = "#fde2e0" if status == "AGOTADO" else "#fff0d6"
        units += p["stock"]
        cost += p["stock"] * p["cost_cents"]
        price += p["stock"] * p["price_cents"]
        rows.append([_clip(p["sku"], 20), _clip(p["name"], 52), _clip(p["category"], 22), _clip(p["location"], 16),
                     f"{p['stock']:,}", f"{p['min_stock']:,}", status, money(p["cost_cents"]),
                     money(p["price_cents"]), money(p["stock"] * p["cost_cents"])])
    scope = []
    if category:
        scope.append(f"Categoría: {category}")
    if low_only:
        scope.append("solo productos en escasez")
    page_width = landscape(A4)[0] - 3 * cm
    story = [
        Paragraph("Reporte de inventario", styles["h1"]),
        Paragraph(_safe(("Filtros: " + "; ".join(scope)) if scope else "Todos los productos activos"), styles["meta"]),
        Spacer(1, 8),
        _kpi_table([("Productos listados", f"{len(rows):,}"), ("Unidades en stock", f"{units:,}"),
                    ("En escasez o agotados", f"{low:,}"), ("Valor a costo", money(cost)),
                    ("Valor a precio de venta", money(price))], page_width),
        Spacer(1, 10),
    ]
    if rows:
        widths = [2.8, 6.4, 3.2, 2.5, 1.5, 1.5, 1.9, 2.2, 2.2, 2.5]
        widths = [w * cm for w in widths]
        scale = page_width / sum(widths)
        story.append(_main_table(
            ["SKU", "Producto", "Categoría", "Ubicación", "Stock", "Mín.", "Estado", "Costo", "Precio", "Valor a costo"],
            rows, [w * scale for w in widths], {4, 5, 7, 8, 9}, row_colors))
    else:
        story.append(Paragraph("No hay productos que coincidan con los filtros.", styles["meta"]))
    return _build_pdf("Reporte de inventario", config, generated_by, story)


def movements_pdf(conn, config: dict, *, product_id=None, kind=None, start_utc=None, end_utc=None,
                  range_label: str = "", generated_by: str = "") -> bytes:
    styles = _styles()
    rows = []
    inflow = outflow = 0
    for m in stock_model.iter_movements(conn, product_id=product_id, kind=kind,
                                        start_utc=start_utc, end_utc=end_utc):
        inflow += max(m["delta"], 0)
        outflow += max(-m["delta"], 0)
        rows.append([str(m["id"]), fmt_local(m["created_at"], config["TIMEZONE"]), _clip(m["sku"], 18),
                     _clip(m["product_name"], 40), KIND_ES[m["kind"]], f"{m['quantity']:,}", f"{m['delta']:+,}",
                     f"{m['stock_after']:,}", _clip(m["reference"], 16), _clip(m["user_name"], 22)])
    page_width = landscape(A4)[0] - 3 * cm
    story = [
        Paragraph("Reporte de movimientos de inventario", styles["h1"]),
        Paragraph(_safe(range_label or "Todo el historial"), styles["meta"]),
        Spacer(1, 8),
        _kpi_table([("Movimientos", f"{len(rows):,}"), ("Unidades que entraron", f"{inflow:,}"),
                    ("Unidades que salieron", f"{outflow:,}"), ("Variación neta", f"{inflow - outflow:+,}")],
                   page_width),
        Spacer(1, 10),
    ]
    if rows:
        widths = [1.4, 3.1, 2.8, 6.6, 1.9, 1.7, 1.7, 1.9, 2.6, 3.4]
        widths = [w * cm for w in widths]
        scale = page_width / sum(widths)
        story.append(_main_table(
            ["Folio", "Fecha y hora", "SKU", "Producto", "Tipo", "Cant.", "Var.", "Stock", "Referencia", "Usuario"],
            rows, [w * scale for w in widths], {0, 5, 6, 7}))
    else:
        story.append(Paragraph("No hay movimientos en el periodo seleccionado.", styles["meta"]))
    return _build_pdf("Reporte de movimientos", config, generated_by, story)
