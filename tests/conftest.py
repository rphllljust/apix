"""Fixtures compartilhadas para testes unitarios da API de integracao Moodle e Google Sheets."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Cria configuracao consistente para testes locais sem dependencias externas."""
    tmp_dir: Path = tmp_path_factory.mktemp("dados_teste")
    os.environ["MOODLE_BASE_URL"] = "https://example.com"
    os.environ["MOODLE_TOKEN"] = "token_teste"
    os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = "credentials.json"
    os.environ["GOOGLE_SPREADSHEET_ID"] = "spreadsheet-id"
    os.environ["SYNC_STATE_DB_PATH"] = str(tmp_dir / "sync_state.db")
    os.environ["API_RATE_LIMIT_PER_MINUTE"] = "60"
    os.environ["CORS_ALLOWED_ORIGINS"] = "https://cursos.idep.ro.gov.br"
    return Settings()
