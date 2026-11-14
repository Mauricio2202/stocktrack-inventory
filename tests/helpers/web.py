"""Utilidades para probar la aplicación vía HTTP (cliente de pruebas de Flask y servidor real)."""
from __future__ import annotations

import re

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

PASSWORDS = {"admin": "Admin12345", "gerente": "Gerente12345", "almacen": "Almacen12345", "consulta": "Consulta12345"}


def token_from(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match, "la página no incluye token CSRF"
    return match.group(1)


def login(client, username: str = "admin", password: str | None = None):
    """Inicia sesión con un cliente de Flask y devuelve la respuesta."""
    password = password or PASSWORDS.get(username, "x")
    token = token_from(client.get("/login").get_data(as_text=True))
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def csrf(client) -> str:
    """Token CSRF de la sesión actual (cualquier usuario autenticado puede abrir /cuenta/password)."""
    return token_from(client.get("/cuenta/password").get_data(as_text=True))


def post(client, url: str, **data):
    data["csrf_token"] = csrf(client)
    return client.post(url, data=data)
