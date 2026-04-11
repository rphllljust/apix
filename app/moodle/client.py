"""Responsabilidade: implementa o modulo app/moodle/client.py."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from loguru import logger

from app.config import Settings
from app.moodle.exceptions import MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError
from app.utils.security import sanitize_text


class MoodleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=settings.moodle_timeout_seconds)

        endpoint = settings.moodle_rest_endpoint
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            self.endpoint_url = endpoint
        else:
            self.endpoint_url = f"{settings.moodle_base_url.rstrip('/')}{endpoint}"

    async def close(self) -> None:
        await self._http.aclose()

    def _sanitize(self, value: Any) -> str:
        return sanitize_text(value, secrets=[self.settings.moodle_token, self.settings.middleware_api_key or ""])

    @staticmethod
    def _extract_capabilities(text: str) -> list[str]:
        found = re.findall(r"[a-z]+/[a-z0-9:_]+", text.lower())
        unique: list[str] = []
        for capability in found:
            if capability not in unique:
                unique.append(capability)
        return unique

    @staticmethod
    def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                next_prefix = f"{prefix}[{key}]"
                MoodleClient._flatten(next_prefix, item, out)
            return
        if isinstance(value, list):
            for idx, item in enumerate(value):
                next_prefix = f"{prefix}[{idx}]"
                MoodleClient._flatten(next_prefix, item, out)
            return
        if isinstance(value, bool):
            out[prefix] = int(value)
            return
        out[prefix] = value

    def _build_payload(self, wsfunction: str, params: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "wstoken": self.settings.moodle_token,
            "moodlewsrestformat": "json",
            "wsfunction": wsfunction,
        }
        for key, value in params.items():
            self._flatten(key, value, payload)
        return payload

    async def _request_once(self, wsfunction: str, params: dict[str, Any]) -> Any:
        payload = self._build_payload(wsfunction, params)
        response = await self._http.post(self.endpoint_url, data=payload)
        if response.status_code >= 500:
            response.raise_for_status()
        if response.status_code >= 400:
            logger.error(
                "Falha final Moodle wsfunction={} status_code={}",
                wsfunction,
                response.status_code,
            )
            raise MoodleAPIError(
                errorcode=f"http_{response.status_code}",
                message=f"HTTP {response.status_code} em {wsfunction}.",
            )

        try:
            body = response.json()
        except ValueError as exc:
            logger.error("Falha final Moodle wsfunction={} error=invalid_json", wsfunction)
            raise MoodleAPIError(
                errorcode="invalid_json",
                message="Resposta invalida do Moodle (nao-JSON).",
            ) from exc

        if isinstance(body, dict) and body.get("exception"):
            errorcode = str(body.get("errorcode", "unknown_error"))
            message = str(body.get("message", "Erro sem detalhes"))
            debuginfo = str(body.get("debuginfo", "") or "")
            token_hints = f"{errorcode} {message}".lower()
            if "token" in token_hints or "invalidtoken" in token_hints:
                logger.error(
                    "Falha final Moodle wsfunction={} errorcode={} (token expirado/invalido)",
                    wsfunction,
                    self._sanitize(errorcode),
                )
                raise MoodleTokenExpiredError(
                    errorcode=errorcode,
                    message=message,
                    debuginfo=debuginfo,
                )
            message = (
                f"{errorcode}: "
                f"{message}"
            )
            logger.error(
                "Falha final Moodle wsfunction={} errorcode={}",
                wsfunction,
                self._sanitize(errorcode),
            )
            permission_hints = f"{errorcode} {message} {debuginfo}".lower()
            if any(
                term in permission_hints
                for term in ("nopermissions", "accessdenied", "requirecapability", "permission")
            ):
                capabilities = self._extract_capabilities(permission_hints)
                if capabilities:
                    logger.error(
                        "Sugestao Moodle wsfunction={}: habilite capabilities para o token/perfil: {}",
                        wsfunction,
                        ", ".join(capabilities),
                    )
                else:
                    logger.error(
                        "Sugestao Moodle wsfunction={}: revise as capabilities do perfil do token (ex.: webservice/rest:use e capacidades da funcao).",
                        wsfunction,
                    )
            raise MoodleAPIError(
                errorcode=errorcode,
                message=message,
                debuginfo=debuginfo,
            )

        return body

    async def _request(self, wsfunction: str, params: dict[str, Any]) -> Any:
        max_retries = max(0, int(self.settings.moodle_max_retries))
        max_attempts = 1 + max_retries
        backoff_seconds = 2.0
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._request_once(wsfunction, params)
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                logger.warning(
                    "Retry Moodle wsfunction={} retry={}/{} wait={}s error={}",
                    wsfunction,
                    attempt,
                    max_retries,
                    backoff_seconds,
                    self._sanitize(exc),
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 8.0)

        logger.error(
            "Falha final Moodle wsfunction={} apos {} tentativa(s)",
            wsfunction,
            max_attempts,
        )
        raise MoodleConnectionError(
            self._sanitize(
                f"Falha ao chamar {wsfunction} apos {max_retries} retry(s) e {max_attempts} tentativa(s): {last_error}",
            ),
        )

    async def call(self, wsfunction: str, **params: Any) -> Any:
        try:
            return await self._request(wsfunction, params)
        except (MoodleAPIError, MoodleConnectionError):
            raise
        except Exception as exc:  # pragma: no cover - fallback defensivo
            logger.error(
                "Falha final Moodle wsfunction={} error=unexpected_error details={}",
                wsfunction,
                self._sanitize(exc),
            )
            raise MoodleAPIError(
                errorcode="unexpected_error",
                message=self._sanitize(f"Erro inesperado em {wsfunction}: {exc}"),
            ) from exc

