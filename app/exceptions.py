"""Responsabilidade: implementa o modulo app/exceptions.py."""

from __future__ import annotations


class MoodleAPIError(Exception):
    """Erro retornado pela API do Moodle."""

    def __init__(self, errorcode: str, message: str, debuginfo: str = "") -> None:
        self.errorcode = errorcode
        self.message = message
        self.debuginfo = debuginfo
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {
            "errorcode": self.errorcode,
            "message": self.message,
            "debuginfo": self.debuginfo,
        }


class MoodleConnectionError(Exception):
    """Timeout ou falha de rede com o Moodle."""


class MoodleTokenExpiredError(MoodleAPIError):
    """Token invalido ou expirado."""


class SheetQuotaExceededError(Exception):
    """Rate limit do Google Sheets API (100 req/100s por usuario)."""


class SyncConflictError(Exception):
    """Conflito de dados entre Moodle e Sheets."""


class ValidationError(Exception):
    """Dados invalidos (CPF, email, etc.)."""


