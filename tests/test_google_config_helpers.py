"""Testes de validacao de configuracao Google Sheets OAuth."""

from __future__ import annotations

import pytest

from app.main import _extract_google_spreadsheet_id, _validate_google_redirect_uri


def test_extract_google_spreadsheet_id_from_url() -> None:
    spreadsheet_id = _extract_google_spreadsheet_id(
        "https://docs.google.com/spreadsheets/d/1Q2nm_MDUIynHmbYsSEWC9m0voEEdc_atRbUlrLkvCBM/edit?gid=0",
    )

    assert spreadsheet_id == "1Q2nm_MDUIynHmbYsSEWC9m0voEEdc_atRbUlrLkvCBM"


def test_extract_google_spreadsheet_id_from_raw_value() -> None:
    spreadsheet_id = _extract_google_spreadsheet_id(
        "1Q2nm_MDUIynHmbYsSEWC9m0voEEdc_atRbUlrLkvCBM",
    )

    assert spreadsheet_id == "1Q2nm_MDUIynHmbYsSEWC9m0voEEdc_atRbUlrLkvCBM"


def test_extract_google_spreadsheet_id_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        _extract_google_spreadsheet_id("https://example.com")


def test_validate_google_redirect_uri_accepts_http_https() -> None:
    assert (
        _validate_google_redirect_uri("http://192.168.1.89:8000/api/v1/google-sheets/oauth/callback")
        == "http://192.168.1.89:8000/api/v1/google-sheets/oauth/callback"
    )
    assert (
        _validate_google_redirect_uri("https://api.exemplo.com/api/v1/google-sheets/oauth/callback")
        == "https://api.exemplo.com/api/v1/google-sheets/oauth/callback"
    )


def test_validate_google_redirect_uri_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        _validate_google_redirect_uri("localhost:8000/callback")
