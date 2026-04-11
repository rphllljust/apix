"""Responsabilidade: implementa o modulo app/sheets/exceptions.py."""

from app.exceptions import SheetQuotaExceededError


class SheetsSyncError(RuntimeError):
    """Erro para falhas de leitura/escrita no Google Sheets."""


__all__ = ["SheetsSyncError", "SheetQuotaExceededError"]

