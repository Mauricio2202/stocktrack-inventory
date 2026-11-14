"""Panel principal con indicadores del inventario."""
from __future__ import annotations

from flask import Blueprint, render_template

from ..deps import get_db
from ..models import alerts, products, stock
from ..security import login_required

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@login_required
def index():
    conn = get_db()
    stats = products.dashboard_stats(conn)
    recent, _ = stock.list_movements(conn, per_page=8)
    vigentes, _ = alerts.list_alerts(conn, "vigentes", per_page=5)
    max_units = max([c["units"] for c in stats["by_category"]] or [1]) or 1
    return render_template("dashboard.html", stats=stats, recent=recent, active_alerts=vigentes,
                           max_units=max_units)
