"""Servidor HTTP real (werkzeug con hilos) y clientes concurrentes con sesión propia."""
from __future__ import annotations

import statistics
import threading
import time
from contextlib import contextmanager

import requests
from werkzeug.serving import make_server

from .web import CSRF_RE


class LiveServer:
    def __init__(self, app):
        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="live-server")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join(timeout=5)


class User:
    """Un usuario simulado: sesión HTTP propia y registro de latencias."""

    def __init__(self, base: str, username: str, password: str):
        self.base, self.username, self.password = base, username, password
        self.http = requests.Session()
        self.samples: list[tuple[str, float, int]] = []     # (etiqueta, segundos, estado HTTP)
        self.errors: list[str] = []
        self.token = ""

    def request(self, label: str, method: str, path: str, **kw):
        start = time.perf_counter()
        try:
            response = self.http.request(method, self.base + path, timeout=60, allow_redirects=False, **kw)
        except Exception as exc:  # noqa: BLE001 - se registra como error de la prueba
            self.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            self.samples.append((label, time.perf_counter() - start, 0))
            return None
        self.samples.append((label, time.perf_counter() - start, response.status_code))
        return response

    def login(self) -> bool:
        page = self.request("login-page", "GET", "/login")
        if page is None:
            return False
        token = CSRF_RE.search(page.text).group(1)
        response = self.request("login", "POST", "/login", data={
            "username": self.username, "password": self.password, "csrf_token": token})
        ok = response is not None and response.status_code == 302
        if ok:
            self.refresh_token()
        else:
            self.errors.append(f"login falló para {self.username}")
        return ok

    def refresh_token(self) -> None:
        page = self.http.get(self.base + "/cuenta/password", timeout=30)
        self.token = CSRF_RE.search(page.text).group(1)

    def get(self, label: str, path: str):
        return self.request(label, "GET", path)

    def post(self, label: str, path: str, **data):
        data["csrf_token"] = self.token
        return self.request(label, "POST", path, data=data)


def run_parallel(users: list[User], work) -> float:
    """Ejecuta work(user, index) en un hilo por usuario, con arranque simultáneo. Devuelve segundos totales."""
    barrier = threading.Barrier(len(users))
    failures: list[BaseException] = []

    def target(index: int, user: User):
        try:
            barrier.wait(30)
            work(user, index)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
            user.errors.append(f"excepción: {exc!r}")

    threads = [threading.Thread(target=target, args=(i, u), name=f"user-{u.username}") for i, u in enumerate(users)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    elapsed = time.perf_counter() - start
    if failures:
        raise failures[0]
    return elapsed


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return ordered[index]


def summarize(samples: list[tuple[str, float, int]], labels: set[str] | None = None) -> dict:
    times = [s for label, s, _ in samples if labels is None or label in labels]
    if not times:
        return {"n": 0, "median_ms": 0, "p95_ms": 0, "max_ms": 0}
    return {"n": len(times), "median_ms": round(statistics.median(times) * 1000, 1),
            "p95_ms": round(percentile(times, 95) * 1000, 1), "max_ms": round(max(times) * 1000, 1)}


@contextmanager
def live(app):
    with LiveServer(app) as server:
        yield server
