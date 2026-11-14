"""Capa de acceso a datos mínima y portable.

* PostgreSQL (psycopg2) en producción.
* SQLite (biblioteca estándar) para desarrollo y pruebas automatizadas.

Todo el SQL de la aplicación usa marcadores `?` y sintaxis común a ambos motores;
aquí se traducen al estilo de cada controlador.
"""
from __future__ import annotations

import datetime as dt
import decimal
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent / "schema"


def utcnow_str() -> str:
    """Marca de tiempo UTC con formato 'YYYY-MM-DD HH:MM:SS'."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _norm(value):
    """Normaliza tipos que devuelve PostgreSQL para que coincidan con los de SQLite."""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class Connection:
    def __init__(self, raw, dialect: str):
        self.raw = raw
        self.dialect = dialect
        self._in_tx = False

    # --- propiedades de dialecto -------------------------------------------------
    @property
    def is_pg(self) -> bool:
        return self.dialect == "postgresql"

    @property
    def for_update(self) -> str:
        """Cláusula de bloqueo de fila. SQLite ya serializa escrituras con BEGIN IMMEDIATE."""
        return " FOR UPDATE" if self.is_pg else ""

    def advisory_lock(self, key: int) -> None:
        """Bloqueo a nivel de transacción para operaciones que cuentan registros."""
        if self.is_pg:
            self.execute("SELECT pg_advisory_xact_lock(?)", (key,))

    # --- ejecución ---------------------------------------------------------------
    def _sql(self, sql: str) -> str:
        if self.is_pg:
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur

    def executemany(self, sql: str, rows) -> None:
        cur = self.raw.cursor()
        cur.executemany(self._sql(sql), [tuple(r) for r in rows])

    @staticmethod
    def _to_dicts(cur) -> list[dict]:
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, (_norm(v) for v in row))) for row in cur.fetchall()]

    def all(self, sql: str, params=()) -> list[dict]:
        return self._to_dicts(self.execute(sql, params))

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def iter_rows(self, sql: str, params=(), batch: int = 2000):
        """Recorre un resultado grande por lotes (reportes de hasta 100,000 filas)."""
        cur = self.execute(sql, params)
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            for row in rows:
                yield dict(zip(cols, (_norm(v) for v in row)))

    def scalar(self, sql: str, params=()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return _norm(row[0]) if row else None

    def insert(self, sql: str, params=()) -> int:
        """INSERT ... RETURNING id (soportado por SQLite >= 3.35 y PostgreSQL)."""
        cur = self.execute(sql + " RETURNING id", params)
        return int(cur.fetchone()[0])

    # --- transacciones -----------------------------------------------------------
    @contextmanager
    def transaction(self):
        """Transacción de escritura. En SQLite toma el bloqueo de escritura de inmediato
        (BEGIN IMMEDIATE) para evitar errores de 'database is locked' al promover lecturas."""
        if self._in_tx:  # transacciones anidadas se unen a la exterior
            yield self
            return
        if not self.is_pg and not self.raw.in_transaction:
            self.raw.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        try:
            yield self
        except BaseException:
            self.raw.rollback()
            raise
        else:
            self.raw.commit()
        finally:
            self._in_tx = False

    def rollback(self) -> None:
        try:
            self.raw.rollback()
        except Exception:  # la conexión pudo cerrarse ya
            pass

    def close(self) -> None:
        try:
            if self.is_pg:
                self.raw.rollback()  # evita dejar transacciones de solo lectura abiertas
            self.raw.close()
        except Exception:
            pass


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self.path = url[len("sqlite:///"):]
        elif url.startswith(("postgresql://", "postgres://")):
            self.dialect = "postgresql"
            self.path = ""
        else:
            raise ValueError("DATABASE_URL debe empezar con sqlite:/// o postgresql://")

    def connect(self) -> Connection:
        if self.dialect == "sqlite":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            raw = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("PRAGMA synchronous=NORMAL")
            raw.execute("PRAGMA busy_timeout=30000")
            return Connection(raw, "sqlite")
        try:
            import psycopg2  # type: ignore
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError("Instala psycopg2-binary para usar PostgreSQL (ver requirements.txt)") from exc
        raw = psycopg2.connect(self.url)
        return Connection(raw, "postgresql")

    def init_schema(self) -> None:
        sql = (SCHEMA_DIR / f"{self.dialect}.sql").read_text(encoding="utf-8")
        conn = self.connect()
        try:
            if self.dialect == "sqlite":
                conn.raw.execute("PRAGMA journal_mode=WAL")
                conn.raw.executescript(sql)
            else:
                cur = conn.raw.cursor()
                cur.execute(sql)
                conn.raw.commit()
        finally:
            conn.close()


def is_integrity_error(exc: BaseException) -> bool:
    return type(exc).__name__ == "IntegrityError"
