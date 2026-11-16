"""Reportes PDF y Excel, foliados y verificables (RF-12, RF-13, RF-27)."""
from __future__ import annotations

import calendar
import datetime as dt

from flask import Blueprint, Response, current_app, flash, g, redirect, render_template, request, url_for

from ..deps import actor, get_db
from ..models import audit, categories, products, report_log, stock
from ..security import can, permission_required
from ..services import reports
from ..timeutil import local_range_to_utc, now_local, parse_date

bp = Blueprint("reports", __name__, url_prefix="/reportes")

SPECIAL = {  # reportes exclusivos del administrador (RF-13)
    "diario": "Entradas y salidas diarias",
    "mensual": "Entradas y salidas mensuales",
    "reservas": "Reservas de stock (segundo nivel)",
    "devoluciones": "Devoluciones",
}


def _bad_format():
    return render_template("error.html", code=404, title="Formato no disponible",
                           message="Los formatos disponibles son PDF y Excel (xlsx)."), 404


def _too_big(count: int, fmt: str):
    cap = current_app.config["REPORT_PDF_MAX_ROWS"]
    if fmt == "pdf" and count > cap:
        flash(f"El reporte tiene {count:,} filas y el PDF admite hasta {cap:,}. "
              "Aplica filtros o descarga la versión en Excel.", "error")
        return redirect(url_for("reports.index"))
    return None


def _emit(conn, *, report_type: str, fmt: str, title: str, params: dict, count: int, base_name: str,
          builder, **kwargs) -> Response:
    """Reserva folio, genera el archivo, guarda su huella SHA-256 y lo entrega."""
    entry = report_log.reserve(conn, report_type=report_type, fmt=fmt, title=title, params=params,
                               user_id=g.user["id"])
    try:
        content = builder(conn, current_app.config, generated_by=g.user["full_name"], folio=entry["folio"], title=title,
                          **kwargs)
    except Exception as exc:
        report_log.fail(conn, entry["id"], repr(exc))
        raise
    report_log.finalize(conn, entry["id"], content, count)
    with conn.transaction():
        audit.log(conn, actor(), f"report.{report_type}", "report", entry["id"],
                  f"{entry['folio']}; {fmt}; filas={count}")
    mime = "application/pdf" if fmt == "pdf" else reports.XLSX_MIME
    response = Response(content, mimetype=mime)
    response.headers["Content-Disposition"] = f'attachment; filename="{entry["folio"]}_{base_name}.{fmt}"'
    response.headers["X-Report-Folio"] = entry["folio"]
    return response


def _period_label(date_from, date_to) -> str:
    return "Periodo: " + (
        f"{date_from:%d/%m/%Y} al {date_to:%d/%m/%Y}" if date_from and date_to else
        f"desde {date_from:%d/%m/%Y}" if date_from else
        f"hasta {date_to:%d/%m/%Y}" if date_to else "todo el historial")


@bp.get("")
@permission_required("reports.view")
def index():
    conn = get_db()
    today = now_local(current_app.config["TIMEZONE"]).date()
    return render_template("reports/index.html", categories=categories.list_all(conn),
                           default_from=(today - dt.timedelta(days=30)).isoformat(),
                           default_to=today.isoformat(), today=today.isoformat(),
                           this_month=today.strftime("%Y-%m"), kinds=stock.KIND_LABELS,
                           special=SPECIAL, recent=report_log.recent(conn, 15))


@bp.get("/inventario.<fmt>")
@permission_required("reports.view")
def inventory(fmt: str):
    if fmt not in ("pdf", "xlsx"):
        return _bad_format()
    conn = get_db()
    raw = (request.args.get("categoria") or "").strip()
    category = raw if raw.isdigit() else ""
    low_only = request.args.get("escasez") == "1"
    count = products.count_for_report(conn, category=category, low_only=low_only)
    blocked = _too_big(count, fmt)
    if blocked:
        return blocked
    cat = categories.get(conn, int(category)) if category else None
    builder = reports.inventory_pdf if fmt == "pdf" else reports.inventory_xlsx
    return _emit(conn, report_type="inventory", fmt=fmt, title="Reporte de inventario",
                 params={"categoria": category, "escasez": low_only}, count=count,
                 base_name="Inventario_Escasez" if low_only else "Inventario", builder=builder,
                 category=category, low_only=low_only, category_label=cat["name"] if cat else "")


@bp.get("/movimientos.<fmt>")
@permission_required("reports.view")
def movements(fmt: str):
    if fmt not in ("pdf", "xlsx"):
        return _bad_format()
    conn = get_db()
    tzname = current_app.config["TIMEZONE"]
    date_from, date_to = parse_date(request.args.get("desde")), parse_date(request.args.get("hasta"))
    if date_from and date_to and date_to < date_from:
        flash("La fecha final no puede ser anterior a la inicial.", "error")
        return redirect(url_for("reports.index"))
    kind = request.args.get("tipo") or None
    start_utc, end_utc = local_range_to_utc(date_from, date_to, tzname)
    label = _period_label(date_from, date_to)
    if kind in stock.KINDS:
        label += f" · Tipo: {stock.KIND_LABELS[kind]}"
    else:
        kind = None
    count = stock.count_movements(conn, kind=kind, start_utc=start_utc, end_utc=end_utc)
    blocked = _too_big(count, fmt)
    if blocked:
        return blocked
    builder = reports.movements_pdf if fmt == "pdf" else reports.movements_xlsx
    return _emit(conn, report_type="movements", fmt=fmt, title="Reporte de movimientos de inventario",
                 params={"desde": str(date_from or ""), "hasta": str(date_to or ""), "tipo": kind or ""},
                 count=count, base_name="Movimientos", builder=builder, kind=kind,
                 start_utc=start_utc, end_utc=end_utc, range_label=label)


@bp.get("/especial/<name>.<fmt>")
@permission_required("reports.admin")
def special(name: str, fmt: str):
    if fmt not in ("pdf", "xlsx"):
        return _bad_format()
    if name not in SPECIAL:
        return render_template("error.html", code=404, title="Reporte no disponible",
                               message="Ese tipo de reporte no existe."), 404
    conn = get_db()
    tzname = current_app.config["TIMEZONE"]
    kind = status = None
    if name == "diario":
        day = parse_date(request.args.get("dia"))
        if not day:
            flash("Elige el día del reporte.", "error")
            return redirect(url_for("reports.index"))
        date_from = date_to = day
        status, label = "aplicado", f"Día: {day:%d/%m/%Y} · movimientos aplicados al inventario"
    elif name == "mensual":
        try:
            year, month = (int(x) for x in (request.args.get("mes") or "").split("-"))
            date_from = dt.date(year, month, 1)
            date_to = dt.date(year, month, calendar.monthrange(year, month)[1])
        except (ValueError, TypeError):
            flash("Elige el mes del reporte.", "error")
            return redirect(url_for("reports.index"))
        status, label = "aplicado", f"Mes: {date_from:%m/%Y} · movimientos aplicados al inventario"
    else:
        date_from, date_to = parse_date(request.args.get("desde")), parse_date(request.args.get("hasta"))
        if date_from and date_to and date_to < date_from:
            flash("La fecha final no puede ser anterior a la inicial.", "error")
            return redirect(url_for("reports.index"))
        kind = "reserva" if name == "reservas" else "devolucion"
        label = _period_label(date_from, date_to) + f" · {stock.KIND_LABELS[kind]}"
    start_utc, end_utc = local_range_to_utc(date_from, date_to, tzname)
    count = stock.count_movements(conn, kind=kind, status=status, start_utc=start_utc, end_utc=end_utc)
    blocked = _too_big(count, fmt)
    if blocked:
        return blocked
    builder = reports.movements_pdf if fmt == "pdf" else reports.movements_xlsx
    return _emit(conn, report_type=name, fmt=fmt, title=f"Reporte: {SPECIAL[name]}",
                 params={"desde": str(date_from or ""), "hasta": str(date_to or "")}, count=count,
                 base_name=name.capitalize(), builder=builder, kind=kind, status=status,
                 start_utc=start_utc, end_utc=end_utc, range_label=label)


@bp.route("/verificar", methods=["GET", "POST"])
@permission_required("reports.view")
def verify():
    """Comprueba que un PDF/Excel presentado es idéntico al emitido por el sistema."""
    result = None
    if request.method == "POST":
        upload = request.files.get("file")
        data = upload.read(30 * 1024 * 1024 + 1) if upload else b""
        if not data:
            flash("Selecciona el archivo del reporte a verificar.", "error")
        elif len(data) > 30 * 1024 * 1024:
            flash("El archivo es demasiado grande.", "error")
        else:
            match = report_log.verify(get_db(), data)
            result = {"ok": bool(match), "report": match, "name": upload.filename}
            with get_db().transaction():
                audit.log(get_db(), actor(), "report.verify", "report", match["id"] if match else None,
                          "auténtico" if match else "NO coincide")
    return render_template("reports/verify.html", result=result)
