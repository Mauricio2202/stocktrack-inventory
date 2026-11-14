"""Bitácora de auditoría (consulta)."""
from __future__ import annotations

from flask import Blueprint, render_template

from ..deps import get_db
from ..models import audit
from ..security import permission_required

bp = Blueprint("audit", __name__, url_prefix="/auditoria")


@bp.get("")
@permission_required("audit.view")
def index():
    return render_template("audit/list.html", rows=audit.recent(get_db(), limit=200))
