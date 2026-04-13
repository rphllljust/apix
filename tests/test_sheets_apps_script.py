"""Testes do modo Google Apps Script no cliente de Sheets."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.sheets.client import GoogleSheetsClient
from app.sheets.exceptions import SheetsSyncError


class _FakeResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body
        self.headers = {"content-type": "application/json"}
        self.text = json.dumps(body, ensure_ascii=False)

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, object]:
        return self._body


def _build_apps_client() -> GoogleSheetsClient:
    client = object.__new__(GoogleSheetsClient)
    client._use_apps_script = True
    client._apps_script_url = "https://script.google.com/macros/s/demo/exec"
    client._apps_script_token = "secret-token"
    client.settings = SimpleNamespace(
        google_spreadsheet_id="sheet-123",
        google_apps_script_timeout_seconds=20.0,
    )
    return client


def test_apps_script_calls_webhook_and_maps_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()
    captured: list[dict[str, object]] = []

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        captured.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
                "headers": headers,
                "follow_redirects": follow_redirects,
            },
        )
        action = str(json.get("action") or "")
        if action == "ensure_headers":
            return _FakeResponse({"ok": True, "result": ["id", "nome"]})
        if action == "ping":
            return _FakeResponse({"ok": True, "result": {"ok": True, "title": "Planilha"}})
        raise AssertionError(f"Acao inesperada no teste: {action}")

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    headers = client.ensure_headers("alunos", ["id", "nome"])
    status = client.ping()

    assert headers == ["id", "nome"]
    assert status is True
    assert len(captured) == 2
    assert captured[0]["url"] == "https://script.google.com/macros/s/demo/exec"
    payload = captured[0]["json"]
    assert isinstance(payload, dict)
    assert payload["token"] == "secret-token"
    assert payload["spreadsheet_id"] == "sheet-123"


def test_apps_script_upsert_parses_inserted_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, timeout, headers, follow_redirects)
        assert json["action"] == "upsert_records"
        return _FakeResponse({"ok": True, "result": {"inserted": "2", "updated": 1}})

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    result = client.upsert_records(
        "students",
        [{"user_id": "1", "nome": "Alice"}, {"user_id": "2", "nome": "Bob"}],
        ["user_id"],
    )

    assert result == {"inserted": 2, "updated": 1}


def test_apps_script_upsert_unknown_action_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, timeout, headers, follow_redirects)
        assert json["action"] == "upsert_records"
        return _FakeResponse({"ok": False, "error": "Ação desconhecida: upsert_records"})

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    result = client.upsert_records("students", [{"user_id": "1"}], ["user_id"])
    assert result == {"inserted": 0, "updated": 0}


def test_apps_script_error_returns_sheets_sync_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, json, timeout, headers, follow_redirects)
        return _FakeResponse({"ok": False, "error": "invalid token"})

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    with pytest.raises(SheetsSyncError):
        client.read_records("students")


def test_apps_script_serializes_dates_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()
    captured_json: dict[str, object] = {}

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, timeout, headers, follow_redirects)
        captured_json.update(json)
        return _FakeResponse({"ok": True, "result": 1})

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    written = client.overwrite_records(
        "students",
        [{"cpf": "39053344705", "data_matricula": date(2026, 4, 13)}],
    )

    assert written == 1
    assert isinstance(captured_json.get("records"), list)
    records = captured_json["records"]
    assert isinstance(records, list)
    assert records[0]["data_matricula"] == "2026-04-13"


def test_apps_script_fallback_read_records_with_row_number(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, timeout, headers, follow_redirects)
        action = str(json.get("action") or "")
        if action == "read_records_with_row_number":
            return _FakeResponse({"ok": False, "error": "Ação desconhecida: read_records_with_row_number"})
        if action == "read_records":
            return _FakeResponse({"ok": True, "result": [{"cpf": "39053344705", "email": "a@b.com"}]})
        raise AssertionError(f"Acao inesperada no teste: {action}")

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    rows = client.read_records_with_row_number("students")
    assert rows == [{"_row_number": 2, "cpf": "39053344705", "email": "a@b.com"}]


def test_apps_script_append_event_unknown_action_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_apps_client()

    def fake_post(
        url: str,
        json: dict[str, object],
        timeout: float,
        headers: dict[str, str],
        follow_redirects: bool,
    ) -> _FakeResponse:
        _ = (url, timeout, headers, follow_redirects)
        action = str(json.get("action") or "")
        if action == "append_event":
            return _FakeResponse({"ok": False, "error": "Ação desconhecida: append_event"})
        raise AssertionError(f"Acao inesperada no teste: {action}")

    monkeypatch.setattr("app.sheets.client.httpx.post", fake_post)

    # Nao deve levantar erro quando o Apps Script nao suporta append_event.
    client.append_event("Log de Sincronização", {"x": "y"})
