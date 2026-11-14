"""Utilidades de zona horaria. En la base de datos todo se guarda en UTC."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
_FMT = "%Y-%m-%d %H:%M:%S"


def tz(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # sin tzdata: Monterrey está en UTC-6 sin horario de verano
        return dt.timezone(dt.timedelta(hours=-6))


def to_local(utc_str: str | None, tzname: str) -> dt.datetime | None:
    if not utc_str:
        return None
    naive = dt.datetime.strptime(str(utc_str)[:19], _FMT)
    return naive.replace(tzinfo=UTC).astimezone(tz(tzname))


def fmt_local(utc_str: str | None, tzname: str, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = to_local(utc_str, tzname)
    return local.strftime(fmt) if local else ""


def parse_date(text: str | None) -> dt.date | None:
    """Convierte 'YYYY-MM-DD' en fecha; devuelve None si viene vacío o inválido."""
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text.strip())
    except ValueError:
        return None


def local_range_to_utc(date_from: dt.date | None, date_to: dt.date | None, tzname: str):
    """Rango de fechas locales (ambos extremos inclusivos) -> (inicio UTC, fin UTC exclusivo)."""
    zone = tz(tzname)
    start = end = None
    if date_from:
        start = dt.datetime.combine(date_from, dt.time.min, tzinfo=zone).astimezone(UTC).strftime(_FMT)
    if date_to:
        end = dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, tzinfo=zone)
        end = end.astimezone(UTC).strftime(_FMT)
    return start, end


def now_local(tzname: str) -> dt.datetime:
    return dt.datetime.now(UTC).astimezone(tz(tzname))
