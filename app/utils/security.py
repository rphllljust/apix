"""Responsabilidade: implementa o modulo app/utils/security.py."""

from __future__ import annotations

import re
from typing import Any, Iterable

from fastapi import Request

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_WSTOKEN_RE = re.compile(r"(?i)(wstoken=)[^&\s]+")
_GENERIC_TOKEN_RE = re.compile(r"(?i)(token=)[^&\s]+")
_AUTH_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/=]+")
_API_KEY_RE = re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+")


def sanitize_text(value: Any, secrets: Iterable[str] | None = None) -> str:
    text = str(value or "")
    if not text:
        return ""

    sanitized = text
    for secret in secrets or []:
        if secret:
            sanitized = sanitized.replace(secret, "***")

    sanitized = _WSTOKEN_RE.sub(r"\1***", sanitized)
    sanitized = _GENERIC_TOKEN_RE.sub(r"\1***", sanitized)
    sanitized = _AUTH_BEARER_RE.sub(r"\1***", sanitized)
    sanitized = _API_KEY_RE.sub(r"\1***", sanitized)
    sanitized = _EMAIL_RE.sub("***EMAIL***", sanitized)
    sanitized = _CPF_RE.sub("***CPF***", sanitized)
    return sanitized


def sanitize_structure(value: Any, secrets: Iterable[str] | None = None) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize_structure(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_structure(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [sanitize_structure(item, secrets) for item in value]
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    return sanitize_text(value, secrets)


def get_client_ip(request: Request, trust_proxy_headers: bool = False) -> str:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            first = forwarded_for.split(",")[0].strip()
            if first:
                return first

    if request.client and request.client.host:
        return request.client.host
    return "unknown"

