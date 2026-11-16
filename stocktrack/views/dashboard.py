"""Panel principal con indicadores del inventario."""
from __future__ import annotations

from flask import Blueprint, render_template

from ..deps import get_db
from ..models import alerts, products, stock
from ..security import can, permission_required

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@permission_required("dashboard.view")
def index():
    conn = get_db()
    stats = products.dashboard_stats(conn)
    staff = can("movements.view")  # el usuario de consulta solo ve el resumen de existencias
    recent = stock.list_movements(conn, per_page=8)[0] if staff else []
    vigentes = alerts.list_alerts(conn, "vigentes", per_page=5)[0] if can("alerts.view") else []
    pending = stock.list_movements(conn, kind="reserva", status="pendiente", per_page=5)[0] \
        if can("reservations.validate") else []
    max_units = max([c["units"] for c in stats["by_category"]] or [1]) or 1
    return render_template("dashboard.html", stats=stats, recent=recent, active_alerts=vigentes,
                           max_units=max_units, pending=pending)
