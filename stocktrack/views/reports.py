"""Reportes descargables en PDF y Excel."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, Response, current_app, flash, g, redirect, render_template, request, url_for

from ..deps import actor, get_db
from ..models import audit, products, stock
from ..security import permission_required
from ..services import reports
from ..timeutil import local_range_to_utc, now_local, parse_date

bp = Blueprint("reports", __name__, url_prefix="/reportes")


def _respond(content: bytes, fmt: str, base_name: str) -> Response:
    stamp = now_local(current_app.config["TIMEZONE"]).strftime("%Y%m%d_%H%M")
    mime = "application/pdf" if fmt == "pdf" else reports.XLSX_MIME
    response = Response(content, mimetype=mime)
    response.headers["Content-Disposition"] = f'attachment; filename="StockTrack_{base_name}_{stamp}.{fmt}"'
    return response


def _too_big(count: int, fmt: str):
    cap = current_app.config["REPORT_PDF_MAX_ROWS"]
    if fmt == "pdf" and count > cap:
        flash(f"El reporte tiene {count:,} filas y el PDF admite hasta {cap:,}. "
              "Aplica filtros o descarga la versión en Excel.", "error")
        return redirect(url_for("reports.index"))
    return None


@bp.get("")
@permission_required("reports.view")
def index():
    today = now_local(current_app.config["TIMEZONE"]).date()
    return render_template("reports/index.html", categories=products.categories(get_db()),
                           default_from=(today - dt.timedelta(days=30)).isoformat(),
                           default_to=today.isoformat(), kinds=stock.KIND_LABELS)


@bp.get("/inventario.<fmt>")
@permission_required("reports.view")
def inventory(fmt: str):
    if fmt not in ("pdf", "xlsx"):
        return render_template("error.html", code=404, title="Formato no disponible",
                               message="Los formatos disponibles son PDF y Excel (xlsx)."), 404
    conn = get_db()
    category = (request.args.get("categoria") or "").strip()
    low_only = request.args.get("escasez") == "1"
    count = products.count_for_report(conn, category=category, low_only=low_only)
    blocked = _too_big(count, fmt)
    if blocked:
        return blocked
    builder = reports.inventory_pdf if fmt == "pdf" else reports.inventory_xlsx
    content = builder(conn, current_app.config, category=category, low_only=low_only,
                      generated_by=g.user["full_name"])
    with conn.transaction():
        audit.log(conn, actor(), "report.inventory", detail=f"{fmt}; filas={count}")
    return _respond(content, fmt, "Inventario_Escasez" if low_only else "Inventario")


@bp.get("/movimientos.<fmt>")
@permission_required("reports.view")
def movements(fmt: str):
    if fmt not in ("pdf", "xlsx"):
        return render_template("error.html", code=404, title="Formato no disponible",
                               message="Los formatos disponibles son PDF y Excel (xlsx)."), 404
    conn = get_db()
    tzname = current_app.config["TIMEZONE"]
    date_from, date_to = parse_date(request.args.get("desde")), parse_date(request.args.get("hasta"))
    if date_from and date_to and date_to < date_from:
        flash("La fecha final no puede ser anterior a la inicial.", "error")
        return redirect(url_for("reports.index"))
    kind = request.args.get("tipo") or None
    start_utc, end_utc = local_range_to_utc(date_from, date_to, tzname)
    label = "Periodo: " + (
        f"{date_from:%d/%m/%Y} al {date_to:%d/%m/%Y}" if date_from and date_to else
        f"desde {date_from:%d/%m/%Y}" if date_from else
        f"hasta {date_to:%d/%m/%Y}" if date_to else "todo el historial")
    if kind in stock.KINDS:
        label += f" · Tipo: {stock.KIND_LABELS[kind]}"
    count = stock.count_movements(conn, kind=kind, start_utc=start_utc, end_utc=end_utc)
    blocked = _too_big(count, fmt)
    if blocked:
        return blocked
    builder = reports.movements_pdf if fmt == "pdf" else reports.movements_xlsx
    content = builder(conn, current_app.config, kind=kind, start_utc=start_utc, end_utc=end_utc,
                      range_label=label, generated_by=g.user["full_name"])
    with conn.transaction():
        audit.log(conn, actor(), "report.movements", detail=f"{fmt}; filas={count}; {label}")
    return _respond(content, fmt, "Movimientos")
