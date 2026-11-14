"""Alertas de escasez y notificaciones internas."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from ..deps import actor, get_db, int_arg, paginate
from ..errors import NotFound
from ..models import alerts
from ..security import permission_required

bp = Blueprint("alerts", __name__)


@bp.get("/alertas")
@permission_required("alerts.view")
def index():
    conn = get_db()
    state = request.args.get("estado", "vigentes")
    if state not in ("vigentes", "resuelta", "todas"):
        state = "vigentes"
    per_page = current_app.config["PAGE_SIZE"]
    page = int_arg("page", 1)
    rows, total = alerts.list_alerts(conn, state if state != "todas" else "todas", page=page, per_page=per_page)
    return render_template("alerts/list.html", rows=rows, pager=paginate(total, page, per_page), state=state,
                           notifications=alerts.list_notifications(conn, g.user["id"]))


@bp.post("/alertas/<int:alert_id>/reconocer")
@permission_required("alerts.ack")
def acknowledge(alert_id: int):
    try:
        alerts.acknowledge(get_db(), alert_id, actor())
        flash("Alerta reconocida. Seguirá vigente hasta que se reponga el stock.", "success")
    except NotFound as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("alerts.index"))


@bp.post("/notificaciones/leer-todas")
@permission_required("alerts.view")
def mark_read():
    alerts.mark_all_read(get_db(), g.user["id"])
    return redirect(url_for("alerts.index"))
