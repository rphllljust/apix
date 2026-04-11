"""Testes de autenticacao da API (API Key + JWT)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import create_access_token, require_api_auth
from app.config import Settings


def build_settings() -> Settings:
    settings = Settings(
        moodle_base_url="https://example.com",
        moodle_token="token_teste",
        google_service_account_file="credentials.json",
        google_spreadsheet_id="spreadsheet-id",
    )
    return settings.model_copy(
        update={
            "middleware_api_key": "api-key-teste",
            "auth_username": "admin",
            "auth_password": "senha-super-secreta",
            "auth_jwt_secret_key": "jwt-secret-teste",
            "auth_jwt_algorithm": "HS256",
        },
    )


def build_request(settings: Settings) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        headers={},
    )


def test_require_api_auth_accepts_api_key() -> None:
    settings = build_settings()
    request = build_request(settings)

    auth = require_api_auth(request, x_api_key="api-key-teste", authorization=None)

    assert auth.method == "api_key"


def test_require_api_auth_accepts_bearer_jwt() -> None:
    settings = build_settings()
    request = build_request(settings)
    token, _ = create_access_token(settings, subject="admin")

    auth = require_api_auth(request, x_api_key=None, authorization=f"Bearer {token}")

    assert auth.method == "jwt"
    assert auth.subject == "admin"


def test_require_api_auth_rejects_when_no_credentials() -> None:
    settings = build_settings()
    request = build_request(settings)

    with pytest.raises(HTTPException) as exc:
        require_api_auth(request, x_api_key=None, authorization=None)

    assert exc.value.status_code == 401
