"""Excepciones de dominio de StockTrack."""
from __future__ import annotations


class AppError(Exception):
    """Base de los errores controlados de la aplicación."""


class ValidationError(AppError):
    """Datos de entrada inválidos. `errors` mapea campo -> mensaje."""

    def __init__(self, message: str = "Datos inválidos", errors: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


class Conflict(ValidationError):
    """Violación de unicidad (por ejemplo, SKU duplicado)."""


class LimitExceeded(ValidationError):
    """Se superó la capacidad máxima de registros activos."""


class NotFound(AppError):
    """El registro solicitado no existe."""
