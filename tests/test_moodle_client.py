"""Testes de cliente e servico Moodle com foco em conexao, validacoes, retry e batch."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings
from app.exceptions import MoodleConnectionError
from app.moodle.client import MoodleClient
from app.moodle.exceptions import MoodleAuthError
from app.moodle.metrics import MoodleService


def run_async(task_factory: Callable[[], Any]) -> Any:
    """Executa corrotina de teste sem depender de plugin extra do pytest."""
    return asyncio.run(task_factory())


class FakeMoodleClient:
    """Cliente Moodle fake para simular respostas de Web Services."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, wsfunction: str, **params: Any) -> Any:
        self.calls.append((wsfunction, params))
        return self.responses.get(wsfunction, [])

    async def validate_token(self, token: str | None = None) -> dict[str, Any]:
        _ = token
        self.calls.append(("core_webservice_get_site_info", {}))
        response = self.responses.get("core_webservice_get_site_info", {})
        return {
            "sitename": response.get("sitename"),
            "username": response.get("username"),
            "fullname": response.get("fullname"),
            "userid": response.get("userid"),
            "moodle_version": response.get("release"),
        }


class FakeBatchClient:
    """Cliente fake que registra chamadas para validar tamanho de lotes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, wsfunction: str, **params: Any) -> Any:
        self.calls.append((wsfunction, params))
        return {"ok": True}


def test_flatten_nested_payload() -> None:
    """Valida flatten de payload com lista e booleano."""
    out: dict[str, object] = {}
    MoodleClient._flatten("users", [{"id": 10, "active": True}], out)
    assert out["users[0][id]"] == 10
    assert out["users[0][active]"] == 1


def test_moodle_connection_auth_and_courses(test_settings: Settings) -> None:
    """Confirma fluxo de autenticacao (site info) e leitura de cursos."""

    async def scenario() -> None:
        fake_client = FakeMoodleClient(
            {
                "core_webservice_get_site_info": {
                    "sitename": "AVA IDEP",
                    "username": "api_user",
                    "fullname": "Administrador AVA",
                    "userid": 2,
                    "release": "4.3",
                },
                "core_course_get_courses": [
                    {"id": 10, "fullname": "Curso A"},
                    {"id": 11, "fullname": "Curso B"},
                ],
            },
        )
        service = MoodleService(fake_client, test_settings)

        ping = await service.ping()
        courses = await service.get_courses()

        assert ping["site_name"] == "AVA IDEP"
        assert ping["username"] == "api_user"
        assert ping["fullname"] == "Administrador AVA"
        assert ping["userid"] == 2
        assert len(courses) == 2
        assert courses[0]["fullname"] == "Curso A"

    run_async(scenario)


def test_invalid_cpf_is_rejected_with_clear_message(test_settings: Settings) -> None:
    """Garante rejeicao de CPF invalido com mensagem objetiva."""

    async def scenario() -> None:
        service = MoodleService(FakeMoodleClient({}), test_settings)
        rows = [
            {
                "_row_number": 2,
                "action": "create",
                "username": "11111111111",
                "email": "aluno@example.com",
                "firstname": "Aluno",
                "lastname": "Teste",
                "password": "Senha@123",
            },
        ]

        counts, warnings, processed = await service.apply_students_rows(rows, dry_run=False)

        assert counts == {"created": 0, "updated": 0}
        assert processed == []
        assert any("CPF invalido" in warning for warning in warnings)

    run_async(scenario)


def test_retry_with_exponential_backoff(test_settings: Settings, monkeypatch: Any) -> None:
    """Simula timeout para validar retries e backoff 1s, 2s, 4s."""

    async def scenario() -> None:
        client = MoodleClient(test_settings)
        delays: list[float] = []

        attempt = {"value": 0}

        async def fake_request_once(_: str, __: dict[str, Any]) -> Any:
            attempt["value"] += 1
            if attempt["value"] <= 3:
                raise httpx.TimeoutException("timeout simulado")
            return {"ok": True}

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        monkeypatch.setattr(client, "_request_once", fake_request_once)
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        response = await client._request("core_course_get_courses", {})
        await client.close()

        assert response == {"ok": True}
        assert delays == [1.0, 2.0, 4.0]

    run_async(scenario)


def test_validate_token_detects_errorcode_even_with_http_200(test_settings: Settings) -> None:
    """Moodle pode retornar 200 com payload de erro; deve virar MoodleAuthError."""

    async def scenario() -> None:
        settings = test_settings.model_copy(update={"moodle_timeout_seconds": 10})
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "errorcode": "invalidtoken",
                    "message": "Token invalido",
                },
            ),
        )
        client = MoodleClient(settings)
        client._http = httpx.AsyncClient(transport=transport, timeout=10.0)

        raised = False
        try:
            await client.validate_token("token-invalido")
        except MoodleAuthError:
            raised = True
        finally:
            await client.close()

        assert raised

    run_async(scenario)


def test_retry_timeout_raises_connection_error(test_settings: Settings, monkeypatch: Any) -> None:
    """Confirma falha final apos esgotar retries de timeout."""

    async def scenario() -> None:
        settings = test_settings.model_copy(update={"moodle_max_retries": 2})
        client = MoodleClient(settings)

        async def fake_request_once(_: str, __: dict[str, Any]) -> Any:
            raise httpx.TimeoutException("timeout definitivo")

        async def fake_sleep(_: float) -> None:
            return None

        monkeypatch.setattr(client, "_request_once", fake_request_once)
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        raised = False
        try:
            await client._request("core_course_get_courses", {})
        except MoodleConnectionError:
            raised = True
        finally:
            await client.close()

        assert raised

    run_async(scenario)


def test_batch_processing_for_more_than_100_students(test_settings: Settings) -> None:
    """Valida processamento de 100+ linhas em lotes maximos de 50."""

    async def scenario() -> None:
        settings = test_settings.model_copy(update={"sync_batch_size": 50})
        fake_client = FakeBatchClient()
        service = MoodleService(fake_client, settings)

        rows: list[dict[str, Any]] = []
        for idx in range(1, 121):
            rows.append(
                {
                    "_row_number": idx,
                    "action": "enroll",
                    "course_id": 999,
                    "user_id": idx,
                },
            )

        counts, warnings, processed = await service.apply_enrollment_rows(rows, dry_run=False)

        assert counts["enrolled"] == 120
        assert warnings == []
        assert len(processed) == 120

        enroll_calls = [
            call
            for call in fake_client.calls
            if call[0] == "enrol_manual_enrol_users"
        ]
        batch_sizes = [len(call[1]["enrolments"]) for call in enroll_calls]
        assert batch_sizes == [50, 50, 20]

    run_async(scenario)
