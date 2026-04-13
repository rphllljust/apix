"""Responsabilidade: implementa o modulo app/moodle/client.py."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from loguru import logger

from app.config import Settings
from app.moodle.exceptions import (
    MoodleAPIError,
    MoodleAuthError,
    MoodleConnectionError,
    MoodleTokenExpiredError,
)
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
            "moodlewsrestformat": self.settings.moodle_ws_format,
            "wsfunction": wsfunction,
        }
        for key, value in params.items():
            self._flatten(key, value, payload)
        return payload

    @staticmethod
    def _extract_moodle_error(body: Any) -> tuple[str, str, str] | None:
        if not isinstance(body, dict):
            return None
        has_exception = bool(body.get("exception"))
        has_errorcode = bool(body.get("errorcode"))
        if not has_exception and not has_errorcode:
            return None

        errorcode = str(body.get("errorcode") or body.get("exception") or "unknown_error")
        message = str(body.get("message") or body.get("error") or "Erro sem detalhes")
        debuginfo = str(body.get("debuginfo") or "")
        return errorcode, message, debuginfo

    @staticmethod
    def _is_token_error(errorcode: str, message: str, debuginfo: str = "") -> bool:
        hints = f"{errorcode} {message} {debuginfo}".lower()
        return any(
            token in hints
            for token in (
                "invalidtoken",
            )
        )

    @staticmethod
    def _is_permission_error(errorcode: str, message: str, debuginfo: str = "") -> bool:
        hints = f"{errorcode} {message} {debuginfo}".lower()
        return any(
            token in hints
            for token in (
                "accessexception",
                "notauthorised",
                "nopermissions",
                "wsusercannotassign",
            )
        )

    def _raise_from_moodle_error(
        self,
        wsfunction: str,
        errorcode: str,
        message: str,
        debuginfo: str,
        *,
        auth_context: bool,
    ) -> None:
        logger.error(
            "Falha final Moodle wsfunction={} errorcode={}",
            wsfunction,
            self._sanitize(errorcode),
        )

        if auth_context:
            raise MoodleAuthError(
                "Token do Moodle invalido, expirado ou sem permissao para consultar o AVA.",
                errorcode=errorcode,
            )

        if self._is_token_error(errorcode, message, debuginfo):
            raise MoodleTokenExpiredError(
                errorcode=errorcode,
                message=message,
                debuginfo=debuginfo,
            )

        if self._is_permission_error(errorcode, message, debuginfo):
            raise MoodleAuthError(
                "Usuario/token sem permissao para executar esta operacao no Moodle.",
                errorcode=errorcode,
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
                    "Sugestao Moodle wsfunction={}: revise as capabilities do perfil do token.",
                    wsfunction,
                )

        raise MoodleAPIError(
            errorcode=errorcode,
            message=f"{errorcode}: {message}",
            debuginfo=debuginfo,
        )

    async def _request_once(self, wsfunction: str, params: dict[str, Any]) -> Any:
        payload = self._build_payload(wsfunction, params)
        response = await self._http.post(self.endpoint_url, data=payload)
        if response.status_code >= 500:
            response.raise_for_status()

        try:
            body = response.json()
        except ValueError as exc:
            logger.error("Falha final Moodle wsfunction={} error=invalid_json", wsfunction)
            raise MoodleAPIError(
                errorcode="invalid_json",
                message="Resposta invalida do Moodle (nao-JSON).",
            ) from exc

        moodle_error = self._extract_moodle_error(body)
        if moodle_error is not None:
            errorcode, message, debuginfo = moodle_error
            self._raise_from_moodle_error(
                wsfunction,
                errorcode,
                message,
                debuginfo,
                auth_context=False,
            )

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

        return body

    async def _request(self, wsfunction: str, params: dict[str, Any]) -> Any:
        max_retries = max(0, int(self.settings.moodle_max_retries))
        max_attempts = 1 + max_retries
        backoff_seconds = 1.0
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
                backoff_seconds = min(backoff_seconds * 2, 4.0)

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
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError, MoodleAuthError):
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

    async def validate_token(self, token: str | None = None) -> dict[str, Any]:
        token_value = str(token or self.settings.moodle_token).strip()
        if not token_value:
            raise MoodleAuthError("Token do Moodle nao informado.", errorcode="missing_token")

        query = {
            "wstoken": token_value,
            "wsfunction": "core_webservice_get_site_info",
            "moodlewsrestformat": self.settings.moodle_ws_format,
        }

        retry_delays = [1.0, 2.0, 4.0]
        max_attempts = len(retry_delays) + 1
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._http.get(self.endpoint_url, params=query, timeout=10.0)
                if response.status_code >= 500:
                    response.raise_for_status()

                try:
                    body = response.json()
                except ValueError as exc:
                    raise MoodleConnectionError(
                        "Resposta invalida do AVA ao validar token.",
                    ) from exc

                moodle_error = self._extract_moodle_error(body)
                if moodle_error is not None:
                    errorcode, message, debuginfo = moodle_error
                    self._raise_from_moodle_error(
                        "core_webservice_get_site_info",
                        errorcode,
                        message,
                        debuginfo,
                        auth_context=True,
                    )

                if response.status_code >= 400:
                    raise MoodleConnectionError(
                        f"AVA indisponivel no momento (HTTP {response.status_code}).",
                    )

                if not isinstance(body, dict):
                    raise MoodleAuthError(
                        "Resposta inesperada ao validar token no AVA.",
                        errorcode="invalid_payload",
                    )

                return {
                    "username": str(body.get("username") or ""),
                    "fullname": str(body.get("fullname") or ""),
                    "sitename": str(body.get("sitename") or ""),
                    "moodle_version": str(body.get("release") or body.get("version") or ""),
                    "userid": int(body.get("userid") or 0),
                }
            except MoodleAuthError:
                raise
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, MoodleConnectionError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                delay = retry_delays[attempt - 1]
                logger.warning(
                    "Retry Moodle token validation retry={}/3 wait={}s error={}",
                    attempt,
                    delay,
                    self._sanitize(exc),
                )
                await asyncio.sleep(delay)

        raise MoodleConnectionError(
            self._sanitize(
                f"Nao foi possivel conectar ao AVA para validar token apos {max_attempts} tentativa(s): {last_error}",
            ),
        )
