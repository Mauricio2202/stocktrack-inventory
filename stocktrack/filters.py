"""Filtros de plantilla (formato de dinero, números y fechas locales)."""
from __future__ import annotations

from flask import current_app

from .timeutil import fmt_local


def register(app) -> None:
    @app.template_filter("money")
    def money(cents) -> str:
        return f"${(cents or 0) / 100:,.2f}"

    @app.template_filter("num")
    def num(value) -> str:
        return f"{int(value or 0):,}"

    @app.template_filter("local_dt")
    def local_dt(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
        return fmt_local(value, current_app.config["TIMEZONE"], fmt)

    @app.template_global("page_url")
    def page_url(page: int) -> str:
        """URL de la vista actual conservando filtros, con otro número de página."""
        from flask import request, url_for

        params = request.args.to_dict()
        params["page"] = page
        return url_for(request.endpoint, **{**(request.view_args or {}), **params})

    @app.template_global("sort_params")
    def sort_params(key: str, direction: str) -> dict:
        from flask import request

        params = request.args.to_dict()
        params.update({"orden": key, "dir": direction, "page": 1})
        return params

    @app.template_filter("signed")
    def signed(value) -> str:
        return f"{int(value or 0):+,}"
