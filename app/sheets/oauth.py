"""Responsabilidade: fluxo OAuth do Google para acesso ao Google Sheets."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleOAuthError(RuntimeError):
    """Erro de configuracao/execucao do fluxo OAuth Google."""


def build_google_oauth_authorization_url(settings: Settings, state: str) -> str:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise GoogleOAuthError(
            "Configurar GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET no .env.",
        )

    redirect_uri = str(settings.google_oauth_redirect_uri or "").strip()
    if not redirect_uri:
        raise GoogleOAuthError("Configurar GOOGLE_OAUTH_REDIRECT_URI no .env.")

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_OAUTH_AUTH_URL}?{urlencode(params)}"


async def exchange_google_oauth_code(settings: Settings, code: str) -> dict[str, Any]:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise GoogleOAuthError(
            "Configurar GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET no .env.",
        )

    redirect_uri = str(settings.google_oauth_redirect_uri or "").strip()
    if not redirect_uri:
        raise GoogleOAuthError("Configurar GOOGLE_OAUTH_REDIRECT_URI no .env.")

    payload = {
        "code": code,
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    try:
        body = response.json()
    except ValueError as exc:  # pragma: no cover - erro externo
        raise GoogleOAuthError("Resposta invalida ao trocar codigo OAuth do Google.") from exc

    if response.status_code >= 400:
        message = str(body.get("error_description") or body.get("error") or "erro_oauth")
        raise GoogleOAuthError(f"Google OAuth recusou a autorizacao: {message}")

    if isinstance(body, dict) and body.get("error"):
        message = str(body.get("error_description") or body.get("error") or "erro_oauth")
        raise GoogleOAuthError(f"Google OAuth recusou a autorizacao: {message}")

    refresh_token = str((body or {}).get("refresh_token") or "").strip()
    if not refresh_token:
        raise GoogleOAuthError(
            "Google nao retornou refresh_token. Revogue o acesso anterior e tente novamente com consentimento.",
        )

    return body
