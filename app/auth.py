"""Responsabilidade: autenticacao da API (API Key e JWT via OAuth2 password flow)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Header, HTTPException, Request, status
from jwt import InvalidTokenError

from app.config import Settings


@dataclass(frozen=True)
class AuthContext:
    """Contexto de autenticacao resolvido para a requisicao atual."""

    method: str
    subject: str


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    raw = authorization.strip()
    if raw.lower().startswith(prefix):
        token = raw[len(prefix) :].strip()
        return token or None
    return None


def create_access_token(
    settings: Settings,
    subject: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Gera JWT assinado para autenticar chamadas no middleware."""
    now = datetime.now(UTC)
    expire_delta = expires_delta or timedelta(minutes=settings.auth_access_token_minutes)
    expire_at = now + expire_delta
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire_at.timestamp()),
    }
    token = jwt.encode(payload, settings.auth_jwt_secret_key, algorithm=settings.auth_jwt_algorithm)
    return token, int(expire_delta.total_seconds())


def decode_access_token(settings: Settings, token: str) -> dict[str, object]:
    """Decodifica e valida JWT recebido no header Authorization."""
    return jwt.decode(
        token,
        settings.auth_jwt_secret_key,
        algorithms=[settings.auth_jwt_algorithm],
        options={"require": ["sub", "exp"]},
    )


def validate_user_credentials(settings: Settings, username: str, password: str) -> bool:
    """Valida credenciais de emissao de token OAuth2 password."""
    if not settings.auth_password:
        return False
    return username == settings.auth_username and password == settings.auth_password


def require_api_auth(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthContext:
    """Permite autenticacao por API key ou JWT bearer."""
    settings: Settings = request.app.state.settings
    api_key_enabled = bool(settings.middleware_api_key)
    jwt_enabled = bool(settings.auth_password)

    if not api_key_enabled and not jwt_enabled:
        return AuthContext(method="none", subject="anonymous")

    if api_key_enabled and x_api_key == settings.middleware_api_key:
        return AuthContext(method="api_key", subject="api_key")

    bearer = _extract_bearer_token(authorization)
    if bearer:
        try:
            payload = decode_access_token(settings, bearer)
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token JWT invalido ou expirado.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        subject = str(payload.get("sub") or "user")
        return AuthContext(method="jwt", subject=subject)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticacao obrigatoria via X-API-Key ou Bearer JWT.",
        headers={"WWW-Authenticate": "Bearer"},
    )
