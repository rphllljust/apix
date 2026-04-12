"""Responsabilidade: implementa o modulo app/main.py."""

from __future__ import annotations

import asyncio
import os
import re
import secrets

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger

from app.auth import create_access_token, validate_user_credentials
from app.config import Settings, get_settings as load_settings
from app.dependencies import (
    build_sync_engine,
    configure_logging,
    get_moodle_service,
    get_settings,
    get_sync_engine,
    require_authenticated,
)
from app.exceptions import (
    MoodleAPIError,
    MoodleAuthError,
    MoodleConnectionError,
    MoodleTokenExpiredError,
    SheetQuotaExceededError,
    SyncConflictError,
    ValidationError as AppValidationError,
)
from app.models.schemas import (
    BidirectionalRequest,
    DriveToMoodleRequest,
    GoogleSheetsOAuthConfigRequest,
    MoodleTokenConfigRequest,
    MoodleToSheetsRequest,
    SheetsEnrollRequest,
    SheetsToMoodleRequest,
)
from app.moodle.client import MoodleClient
from app.moodle.metrics import MoodleService
from app.sheets.client import GoogleSheetsClient
from app.sheets.oauth import (
    GoogleOAuthError,
    build_google_oauth_authorization_url,
    exchange_google_oauth_code,
)
from app.sync.engine import SyncEngine
from app.sync.scheduler import SyncScheduler
from app.utils.rate_limit import InMemoryRateLimiter
from app.utils.security import get_client_ip, sanitize_structure, sanitize_text

try:
    from app.graphql.schema import create_graphql_router
except Exception:  # pragma: no cover - fallback quando dependencia GraphQL nao estiver instalada
    create_graphql_router = None


def _bootstrap_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip().strip("'\"")
    if not raw:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("CORS_ALLOWED_ORIGINS="):
                    raw = stripped.split("=", 1)[1].strip().strip("'\"")
                    break
    base_items = [item.strip().strip("'\"") for item in raw.split(",") if item.strip()]
    expanded: list[str] = []
    seen: set[str] = set()

    def add_origin(origin: str) -> None:
        normalized = origin.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        expanded.append(normalized)

    dev_ports = (3000, 4173, 5173, 5174, 5180)
    for origin in base_items:
        add_origin(origin)
        parsed = urlparse(origin)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port is None:
            for port in dev_ports:
                add_origin(f"{parsed.scheme}://{parsed.hostname}:{port}")

    return expanded


def _secrets_from_settings(settings: Settings | None) -> list[str]:
    if settings is None:
        return []
    return [
        settings.moodle_token,
        settings.middleware_api_key or "",
    ]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


def _is_https_request(request: Request, settings: Settings | None) -> bool:
    if request.url.scheme == "https":
        return True
    if settings and settings.trust_proxy_headers:
        proto = request.headers.get("X-Forwarded-Proto", "")
        if proto.lower().startswith("https"):
            return True
    return False


def _build_error_payload(
    request: Request,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details or {},
            "request_id": _request_id(request),
            "timestamp": datetime.now(UTC).isoformat(),
        },
    }


def _persist_error_log(
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any],
) -> None:
    sync_engine = getattr(request.app.state, "sync_engine", None)
    state_store = getattr(sync_engine, "state", None)
    settings: Settings | None = getattr(request.app.state, "settings", None)
    secrets = _secrets_from_settings(settings)

    if state_store is None:
        return

    client_ip = get_client_ip(request, settings.trust_proxy_headers if settings else False)
    try:
        state_store.add_error_log(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": _request_id(request),
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
                "status_code": int(status_code),
                "error_code": sanitize_text(error_code, secrets),
                "message": sanitize_text(message, secrets),
                "details": sanitize_structure(details, secrets),
            },
        )
    except Exception as exc:  # pragma: no cover - persistencia defensiva
        logger.error("Falha ao registrar erro no SQLite: {}", sanitize_text(exc, secrets))


def _error_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    secrets = _secrets_from_settings(settings)

    safe_message = sanitize_text(message, secrets)
    safe_details = sanitize_structure(details or {}, secrets)
    safe_code = sanitize_text(error_code, secrets)

    logger.error(
        "Falha final status={} code={} request_id={} method={} path={} details={}",
        status_code,
        safe_code,
        _request_id(request),
        request.method,
        request.url.path,
        safe_details,
    )

    _persist_error_log(
        request=request,
        status_code=status_code,
        error_code=safe_code,
        message=safe_message,
        details=safe_details,
    )

    payload = _build_error_payload(
        request=request,
        error_code=safe_code,
        message=safe_message,
        details=safe_details,
    )
    response_headers = {"X-Request-ID": _request_id(request)}
    if headers:
        response_headers.update(headers)

    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers=response_headers,
    )


def _site_host_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc:
        return parsed.netloc
    return str(url or "").replace("https://", "").replace("http://", "").strip("/")


def _upsert_env_key(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            updated_lines.append(f"{key}={value}")
            replaced = True
            continue
        updated_lines.append(line)

    if not replaced:
        updated_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


def _extract_google_spreadsheet_id(value: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("Informe a URL completa da planilha ou o Spreadsheet ID.")

    parsed = urlparse(raw_value)
    if parsed.scheme and parsed.netloc:
        match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", parsed.path or "")
        if not match:
            raise ValueError("URL de planilha invalida. Use o link do Google Sheets.")
        spreadsheet_id = match.group(1)
    else:
        spreadsheet_id = raw_value

    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", spreadsheet_id):
        raise ValueError("Spreadsheet ID invalido.")
    return spreadsheet_id


def _validate_google_redirect_uri(value: str) -> str:
    redirect_uri = str(value or "").strip()
    if not redirect_uri:
        raise ValueError("Informe o Redirect URI do OAuth Google.")
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Redirect URI invalido. Use URL completa iniciando com http:// ou https://.")
    return redirect_uri


def _mask_secret(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "*" * len(clean)
    return f"{clean[:4]}{'*' * (len(clean) - 8)}{clean[-4:]}"


async def _apply_runtime_env_updates(
    request: Request,
    env_updates: dict[str, str],
) -> Settings:
    env_path = Path(".env")
    for key, value in env_updates.items():
        _upsert_env_key(env_path, key, value)
        os.environ[key] = value

    new_settings = _reload_settings()
    configure_logging(level=new_settings.log_level, log_file=new_settings.log_file)
    request.app.state.settings = new_settings
    request.app.state.rate_limiter = InMemoryRateLimiter(
        max_requests=new_settings.api_rate_limit_per_minute,
        window_seconds=60,
    )
    await _refresh_runtime_services(request.app, new_settings)
    return new_settings


def _reload_settings() -> Settings:
    load_settings.cache_clear()
    return load_settings()


def _cleanup_google_oauth_states(app: FastAPI) -> None:
    states: dict[str, datetime] = getattr(app.state, "google_oauth_states", {})
    if not states:
        return
    now = datetime.now(UTC)
    stale = [key for key, created_at in states.items() if (now - created_at).total_seconds() > 900]
    for key in stale:
        states.pop(key, None)


def _register_google_oauth_state(app: FastAPI, state: str) -> None:
    states: dict[str, datetime] = getattr(app.state, "google_oauth_states", {})
    states[state] = datetime.now(UTC)
    app.state.google_oauth_states = states
    _cleanup_google_oauth_states(app)


def _consume_google_oauth_state(app: FastAPI, state: str) -> bool:
    states: dict[str, datetime] = getattr(app.state, "google_oauth_states", {})
    created_at = states.pop(state, None)
    if created_at is None:
        return False
    return (datetime.now(UTC) - created_at).total_seconds() <= 900


def _oauth_callback_html(*, success: bool, title: str, message: str) -> str:
    status_text = "Sucesso" if success else "Falha"
    badge_color = "#0f766e" if success else "#b91c1c"
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#f8f7f4; margin:0; padding:32px; }}
    .card {{ max-width:720px; margin:0 auto; background:#fff; border:1px solid #ddd; border-radius:12px; padding:24px; }}
    .badge {{ display:inline-block; background:{badge_color}; color:#fff; border-radius:999px; padding:6px 12px; font-weight:700; font-size:12px; letter-spacing:.03em; text-transform:uppercase; }}
    h1 {{ margin:14px 0 8px; color:#1f2937; font-size:26px; }}
    p {{ color:#475569; line-height:1.5; margin:0 0 10px; }}
  </style>
</head>
<body>
  <main class="card">
    <span class="badge">{status_text}</span>
    <h1>{title}</h1>
    <p>{message}</p>
    <p>Volte ao painel e clique em <strong>Atualizar</strong>.</p>
  </main>
</body>
</html>"""


async def _shutdown_runtime_services(app: FastAPI) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown()
        app.state.scheduler = None

    moodle_client = getattr(app.state, "moodle_client", None)
    if moodle_client is not None:
        await moodle_client.close()
        app.state.moodle_client = None

    app.state.moodle_service = None
    app.state.sync_engine = None


def _initialize_runtime_services(app: FastAPI, settings: Settings) -> None:
    moodle_client, moodle_service, sync_engine = build_sync_engine(settings)
    scheduler = SyncScheduler(
        sync_service=sync_engine,
        interval_minutes=settings.sync_interval_minutes,
        auto_direction=settings.sync_auto_direction,
        students_input_sheet=settings.google_students_input_sheet,
        enrollments_input_sheet=settings.google_enrollments_input_sheet,
    )

    app.state.moodle_client = moodle_client
    app.state.moodle_service = moodle_service
    app.state.sync_engine = sync_engine
    app.state.scheduler = scheduler
    app.state.startup_error = None

    scheduler.start()


async def _refresh_runtime_services(app: FastAPI, settings: Settings) -> None:
    await _shutdown_runtime_services(app)

    try:
        _initialize_runtime_services(app, settings)
        logger.info(
            "API iniciada em ambiente {} com rate_limit={} req/min",
            settings.app_env,
            settings.api_rate_limit_per_minute,
        )
    except Exception as exc:
        app.state.startup_error = str(exc)
        logger.exception(
            "API iniciada em modo degradado. Dependencias externas indisponiveis: {}",
            exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    configure_logging(level=settings.log_level, log_file=settings.log_file)

    app.state.settings = settings
    app.state.startup_error = None
    app.state.moodle_client = None
    app.state.moodle_service = None
    app.state.sync_engine = None
    app.state.scheduler = None
    app.state.google_oauth_states = {}
    app.state.rate_limiter = InMemoryRateLimiter(
        max_requests=settings.api_rate_limit_per_minute,
        window_seconds=60,
    )

    await _refresh_runtime_services(app, settings)

    try:
        yield
    finally:
        await _shutdown_runtime_services(app)


app = FastAPI(
    title="Moodle Sheets Middleware",
    version="1.0.0",
    description="Middleware bidirecional entre Moodle Web Services e Google Sheets.",
    lifespan=lifespan,
)

if create_graphql_router is not None:
    app.include_router(create_graphql_router())
else:  # pragma: no cover - ambiente sem dependencia opcional
    logger.warning("GraphQL desabilitado: dependencia 'strawberry-graphql' indisponivel.")

_cors_allowed_origins = _bootstrap_cors_origins()
if _cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    )


@app.middleware("http")
async def request_context_and_rate_limit(request: Request, call_next: Any):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id

    settings: Settings | None = getattr(request.app.state, "settings", None)
    limiter: InMemoryRateLimiter | None = getattr(request.app.state, "rate_limiter", None)

    if settings and limiter and request.url.path.startswith("/api/"):
        client_ip = get_client_ip(request, settings.trust_proxy_headers)
        allowed, retry_after = await limiter.allow(client_ip)
        if not allowed:
            return _error_response(
                request,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="rate_limit_exceeded",
                message=(
                    f"Limite de {settings.api_rate_limit_per_minute} requisicoes por minuto excedido."
                ),
                details={
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    if settings and settings.security_enable_headers:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", settings.security_referrer_policy)
        response.headers.setdefault("Permissions-Policy", settings.security_permissions_policy)
        response.headers.setdefault("Content-Security-Policy", settings.security_content_security_policy)
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if _is_https_request(request, settings):
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={int(settings.security_hsts_seconds)}; includeSubDomains",
            )
    return response


@app.exception_handler(MoodleTokenExpiredError)
async def handle_moodle_token_expired(request: Request, exc: MoodleTokenExpiredError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_401_UNAUTHORIZED,
        error_code="moodle_token_expired",
        message="Token do Moodle invalido ou expirado.",
        details={"moodle_error_code": exc.errorcode},
    )


@app.exception_handler(MoodleAuthError)
async def handle_moodle_auth_error(request: Request, exc: MoodleAuthError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_401_UNAUTHORIZED,
        error_code="moodle_auth_error",
        message="Token do Moodle invalido, expirado ou sem permissao para o servico web.",
        details={"moodle_error_code": exc.errorcode},
    )


@app.exception_handler(MoodleConnectionError)
async def handle_moodle_connection_error(request: Request, _: MoodleConnectionError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="moodle_connection_error",
        message="Falha de conectividade com o Moodle.",
        details={"source": "moodle"},
    )


@app.exception_handler(MoodleAPIError)
async def handle_moodle_api_error(request: Request, exc: MoodleAPIError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_502_BAD_GATEWAY,
        error_code="moodle_api_error",
        message="Erro retornado pela API do Moodle.",
        details={"moodle_error_code": exc.errorcode},
    )


@app.exception_handler(SheetQuotaExceededError)
async def handle_sheet_quota(request: Request, _: SheetQuotaExceededError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        error_code="sheet_quota_exceeded",
        message="Limite de requisicoes do Google Sheets excedido.",
        details={"source": "google_sheets"},
    )


@app.exception_handler(SyncConflictError)
async def handle_sync_conflict(request: Request, exc: SyncConflictError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_409_CONFLICT,
        error_code="sync_conflict",
        message="Conflito de dados na sincronizacao.",
        details={"reason": str(exc)},
    )


@app.exception_handler(AppValidationError)
async def handle_validation_error(request: Request, exc: AppValidationError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_code="validation_error",
        message="Dados invalidos na requisicao.",
        details={"reason": str(exc)},
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_code="request_validation_error",
        message="Payload da requisicao invalido.",
        details={"errors_count": len(exc.errors())},
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    code_map = {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "unauthorized",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_429_TOO_MANY_REQUESTS: "too_many_requests",
    }
    message_map = {
        status.HTTP_400_BAD_REQUEST: "Requisicao invalida.",
        status.HTTP_401_UNAUTHORIZED: "Nao autorizado.",
        status.HTTP_403_FORBIDDEN: "Acesso negado.",
        status.HTTP_404_NOT_FOUND: "Recurso nao encontrado.",
        status.HTTP_405_METHOD_NOT_ALLOWED: "Metodo HTTP nao permitido.",
        status.HTTP_409_CONFLICT: "Conflito de dados.",
        status.HTTP_429_TOO_MANY_REQUESTS: "Muitas requisicoes em pouco tempo.",
    }
    error_code = code_map.get(exc.status_code, f"http_{exc.status_code}")
    default_message = message_map.get(exc.status_code, "Erro HTTP na requisicao.")
    detail_message = (
        str(exc.detail).strip()
        if isinstance(exc.detail, str) and str(exc.detail).strip()
        else default_message
    )
    return _error_response(
        request,
        status_code=exc.status_code,
        error_code=error_code,
        message=detail_message,
        details={"http_status": exc.status_code},
    )


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, _: Exception) -> JSONResponse:
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="internal_server_error",
        message="Erro interno inesperado.",
        details={},
    )


@app.get("/api/v1/health")
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()
    last_check = datetime.now(UTC).isoformat()
    site_host = _site_host_from_url(settings.moodle_base_url)

    moodle_payload: dict[str, Any] = {
        "status": "offline",
        "username": "",
        "fullname": "",
        "userid": 0,
        "site": site_host,
        "version": "",
    }

    moodle_client: MoodleClient | None = getattr(request.app.state, "moodle_client", None)
    temp_client: MoodleClient | None = None
    if moodle_client is None:
        temp_client = MoodleClient(settings)
        moodle_client = temp_client

    try:
        identity = await moodle_client.validate_token()
        moodle_payload.update(
            {
                "status": "online",
                "username": identity.get("username") or "",
                "fullname": identity.get("fullname") or "",
                "userid": int(identity.get("userid") or 0),
                "version": identity.get("moodle_version") or "",
            },
        )
    except MoodleAuthError as exc:
        moodle_payload["status"] = "auth_error"
        _persist_error_log(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="moodle_auth_error",
            message="Token do Moodle invalido ou sem permissao.",
            details={"reason": str(exc)},
        )
    except MoodleConnectionError as exc:
        moodle_payload["status"] = "offline"
        _persist_error_log(
            request=request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="moodle_connection_error",
            message="Nao foi possivel conectar ao AVA Moodle.",
            details={"reason": str(exc)},
        )
    except Exception as exc:  # pragma: no cover - fallback defensivo
        moodle_payload["status"] = "offline"
        _persist_error_log(
            request=request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="moodle_health_error",
            message="Falha inesperada ao verificar o Moodle.",
            details={"reason": str(exc)},
        )
    finally:
        if temp_client is not None:
            await temp_client.close()

    sheets_status = "offline"
    sync_engine: SyncEngine | None = getattr(request.app.state, "sync_engine", None)
    try:
        if sync_engine is not None and getattr(sync_engine, "sheets", None) is not None:
            sheets_ok = bool(await asyncio.to_thread(sync_engine.sheets.ping))
        else:
            sheets_ok = bool(await asyncio.to_thread(lambda: GoogleSheetsClient(settings).ping()))
        sheets_status = "online" if sheets_ok else "offline"
        if not sheets_ok:
            _persist_error_log(
                request=request,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="sheets_connection_error",
                message="Google Sheets indisponivel no health check.",
                details={},
            )
    except Exception as exc:
        sheets_status = "offline"
        _persist_error_log(
            request=request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="sheets_connection_error",
            message="Falha de conectividade com Google Sheets.",
            details={"reason": str(exc)},
        )

    return {
        "moodle": moodle_payload,
        "sheets": {
            "status": sheets_status,
            "last_check": last_check,
        },
    }


@app.get("/api/v1/config/google-sheets", dependencies=[Depends(require_authenticated)])
async def get_google_sheets_config(request: Request) -> dict[str, Any]:
    settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()
    spreadsheet_id = str(settings.google_spreadsheet_id or "").strip()
    spreadsheet_url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        if spreadsheet_id
        else ""
    )
    return {
        "oauth": {
            "configured": bool(
                settings.google_oauth_client_id and settings.google_oauth_client_secret,
            ),
            "client_id_masked": _mask_secret(settings.google_oauth_client_id or ""),
            "redirect_uri": settings.google_oauth_redirect_uri,
            "refresh_token_configured": bool(settings.google_oauth_refresh_token),
        },
        "spreadsheet": {
            "id": spreadsheet_id,
            "url": spreadsheet_url,
        },
    }


@app.post("/api/v1/config/google-sheets", dependencies=[Depends(require_authenticated)])
async def configure_google_sheets(
    payload: GoogleSheetsOAuthConfigRequest,
    request: Request,
) -> dict[str, Any]:
    client_id = str(payload.client_id or "").strip()
    client_secret = str(payload.client_secret or "").strip()

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o GOOGLE_OAUTH_CLIENT_ID.",
        )
    if len(client_id) < 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="GOOGLE_OAUTH_CLIENT_ID invalido.",
        )
    if not client_secret:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o GOOGLE_OAUTH_CLIENT_SECRET.",
        )
    if len(client_secret) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="GOOGLE_OAUTH_CLIENT_SECRET invalido.",
        )

    try:
        redirect_uri = _validate_google_redirect_uri(payload.redirect_uri)
        spreadsheet_id = _extract_google_spreadsheet_id(payload.spreadsheet)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    current_settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()
    refresh_token_changed = (
        str(current_settings.google_oauth_client_id or "").strip() != client_id
        or str(current_settings.google_oauth_client_secret or "").strip() != client_secret
    )

    env_updates = {
        "GOOGLE_OAUTH_CLIENT_ID": client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": client_secret,
        "GOOGLE_OAUTH_REDIRECT_URI": redirect_uri,
        "SPREADSHEET_ID": spreadsheet_id,
        "GOOGLE_SPREADSHEET_ID": spreadsheet_id,
    }
    if refresh_token_changed:
        env_updates["GOOGLE_OAUTH_REFRESH_TOKEN"] = ""

    new_settings = await _apply_runtime_env_updates(request, env_updates)

    sync_engine: SyncEngine | None = getattr(request.app.state, "sync_engine", None)
    sheets_status = "offline"
    try:
        if sync_engine is not None and getattr(sync_engine, "sheets", None) is not None:
            sheets_ok = bool(await asyncio.to_thread(sync_engine.sheets.ping))
            sheets_status = "online" if sheets_ok else "offline"
    except Exception:
        sheets_status = "offline"

    return {
        "ok": True,
        "message": (
            "Configuracao Google salva com sucesso. "
            "Agora clique em 'Login Google Sheets' para autorizar a conta."
        ),
        "oauth": {
            "configured": bool(
                new_settings.google_oauth_client_id and new_settings.google_oauth_client_secret,
            ),
            "redirect_uri": new_settings.google_oauth_redirect_uri,
            "refresh_token_configured": bool(new_settings.google_oauth_refresh_token),
        },
        "spreadsheet": {
            "id": spreadsheet_id,
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        },
        "sheets_runtime_status": sheets_status,
    }


@app.get("/api/v1/google-sheets/oauth/start", dependencies=[Depends(require_authenticated)])
async def start_google_sheets_oauth(request: Request) -> dict[str, Any]:
    settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()
    state = secrets.token_urlsafe(32)
    _register_google_oauth_state(request.app, state)

    try:
        auth_url = build_google_oauth_authorization_url(settings, state)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Nao foi possivel iniciar login Google Sheets. "
                f"{str(exc)}"
            ),
        ) from exc

    return {
        "auth_url": auth_url,
        "expires_in_seconds": 900,
        "redirect_uri": settings.google_oauth_redirect_uri,
    }


@app.get("/api/v1/google-sheets/oauth/callback")
async def google_sheets_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    if error:
        html = _oauth_callback_html(
            success=False,
            title="Login Google Sheets recusado",
            message="O Google retornou erro na autorizacao. Tente novamente pelo painel.",
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    if not code or not state:
        html = _oauth_callback_html(
            success=False,
            title="Callback invalido",
            message="Parametros de autorizacao ausentes. Reinicie o login pelo painel.",
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    if not _consume_google_oauth_state(request.app, state):
        html = _oauth_callback_html(
            success=False,
            title="Sessao expirada",
            message="O estado OAuth expirou ou e invalido. Reinicie o login Google no painel.",
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()

    try:
        tokens = await exchange_google_oauth_code(settings, code)
    except GoogleOAuthError as exc:
        html = _oauth_callback_html(
            success=False,
            title="Falha ao conectar Google Sheets",
            message=str(exc),
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not refresh_token:
        html = _oauth_callback_html(
            success=False,
            title="Falha ao conectar Google Sheets",
            message=(
                "Google nao retornou refresh token. Revogue o acesso do app na conta Google "
                "e tente novamente."
            ),
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    await _apply_runtime_env_updates(
        request,
        {"GOOGLE_OAUTH_REFRESH_TOKEN": refresh_token},
    )

    runtime_ok = bool(getattr(request.app.state, "sync_engine", None))
    html = _oauth_callback_html(
        success=runtime_ok,
        title=(
            "Google Sheets conectado com sucesso"
            if runtime_ok
            else "Google autorizado, mas integracao ainda indisponivel"
        ),
        message=(
            "Login concluido e token salvo no servidor."
            if runtime_ok
            else "O login foi concluido, mas a API ainda nao conseguiu inicializar totalmente."
        ),
    )
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK if runtime_ok else status.HTTP_503_SERVICE_UNAVAILABLE)


@app.post("/api/v1/config/moodle-token", dependencies=[Depends(require_authenticated)])
async def configure_moodle_token(payload: MoodleTokenConfigRequest, request: Request) -> dict[str, Any]:
    token = str(payload.token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe um token valido do Moodle.",
        )
    if len(token) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Token muito curto. Verifique a chave de Web Service do Moodle.",
        )
    if len(token) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Token invalido: tamanho acima do permitido.",
        )
    if not re.fullmatch(r"[A-Za-z0-9]+", token):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Token invalido. Use apenas caracteres alfanumericos.",
        )

    current_settings: Settings = getattr(request.app.state, "settings", None) or _reload_settings()
    candidate_settings = current_settings.model_copy(update={"moodle_token": token})

    validator = MoodleClient(candidate_settings)
    try:
        identity = await validator.validate_token(token)
    except MoodleAuthError as exc:
        _persist_error_log(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="moodle_auth_error",
            message="Token do Moodle invalido ou sem permissao.",
            details={"reason": str(exc)},
        )
        raise MoodleAuthError(
            "Token invalido ou sem permissao para o servico web do Moodle.",
            errorcode=exc.errorcode,
        ) from exc
    except MoodleConnectionError as exc:
        _persist_error_log(
            request=request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="moodle_connection_error",
            message="Nao foi possivel validar token no Moodle.",
            details={"reason": str(exc)},
        )
        raise MoodleConnectionError(
            "Nao foi possivel conectar ao AVA para validar o token. Tente novamente.",
        ) from exc
    finally:
        await validator.close()

    new_settings = await _apply_runtime_env_updates(
        request,
        {"MOODLE_TOKEN": token},
    )

    return {
        "ok": True,
        "message": "Token Moodle validado e salvo com sucesso.",
        "moodle": {
            "username": identity.get("username") or "",
            "fullname": identity.get("fullname") or "",
            "userid": int(identity.get("userid") or 0),
            "site": _site_host_from_url(new_settings.moodle_base_url),
            "version": identity.get("moodle_version") or "",
        },
        "runtime_status": "online" if getattr(request.app.state, "sync_engine", None) else "degraded",
    }


@app.post("/api/v1/auth/token")
async def issue_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not settings.auth_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Emissao de token JWT desabilitada. Configure AUTH_PASSWORD no .env.",
        )
    if not validate_user_credentials(settings, form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais invalidas para emissao de token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token, expires_in = create_access_token(settings, subject=form_data.username)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@app.post("/api/v1/sync/course/{course_id}/full", dependencies=[Depends(require_authenticated)])
async def sync_course_full(course_id: int, sync_engine: SyncEngine = Depends(get_sync_engine)) -> Any:
    return await sync_engine.sync_course_full(course_id)


@app.post("/api/v1/sync/course/{course_id}/grades", dependencies=[Depends(require_authenticated)])
async def sync_course_grades(course_id: int, sync_engine: SyncEngine = Depends(get_sync_engine)) -> Any:
    return await sync_engine.sync_course_grades(course_id)


@app.post("/api/v1/sync/course/{course_id}/enrollments", dependencies=[Depends(require_authenticated)])
async def sync_course_enrollments(course_id: int, sync_engine: SyncEngine = Depends(get_sync_engine)) -> Any:
    return await sync_engine.sync_course_enrollments(course_id)


@app.post("/api/v1/sync/sheets-to-moodle/enroll", dependencies=[Depends(require_authenticated)])
async def sync_sheets_to_moodle_enroll(
    payload: SheetsEnrollRequest,
    sync_engine: SyncEngine = Depends(get_sync_engine),
) -> Any:
    return await sync_engine.sync_sheet_to_moodle_enroll(
        sheet_name=payload.sheet_name,
        course_id=payload.course_id,
        dry_run=payload.dry_run,
    )


@app.post("/api/v1/sync/moodle-to-sheets", dependencies=[Depends(require_authenticated)])
async def sync_moodle_to_sheets(
    payload: MoodleToSheetsRequest,
    sync_engine: SyncEngine = Depends(get_sync_engine),
) -> Any:
    return await sync_engine.sync_moodle_to_sheets(payload)


@app.post("/api/v1/sync/sheets-to-moodle", dependencies=[Depends(require_authenticated)])
async def sync_sheets_to_moodle(
    payload: SheetsToMoodleRequest,
    sync_engine: SyncEngine = Depends(get_sync_engine),
    settings: Settings = Depends(get_settings),
) -> Any:
    return await sync_engine.sync_sheets_to_moodle(
        payload,
        students_input_sheet=settings.google_students_input_sheet,
        enrollments_input_sheet=settings.google_enrollments_input_sheet,
    )


@app.post("/api/v1/sync/bidirectional", dependencies=[Depends(require_authenticated)])
async def sync_bidirectional(
    payload: BidirectionalRequest,
    sync_engine: SyncEngine = Depends(get_sync_engine),
    settings: Settings = Depends(get_settings),
) -> Any:
    return await sync_engine.sync_bidirectional(
        payload,
        students_input_sheet=settings.google_students_input_sheet,
        enrollments_input_sheet=settings.google_enrollments_input_sheet,
    )


@app.post("/api/v1/sync/google-drive-to-moodle/{course_id}", dependencies=[Depends(require_authenticated)])
async def sync_google_drive_to_moodle(
    course_id: int,
    payload: DriveToMoodleRequest = Body(default_factory=DriveToMoodleRequest),
    sync_engine: SyncEngine = Depends(get_sync_engine),
) -> Any:
    return await sync_engine.sync_drive_to_moodle(course_id, payload)


@app.get("/api/v1/moodle/courses", dependencies=[Depends(require_authenticated)])
async def moodle_courses(service: MoodleService = Depends(get_moodle_service)) -> Any:
    return await service.get_courses()


@app.get("/api/v1/moodle/course/{course_id}/students", dependencies=[Depends(require_authenticated)])
async def moodle_course_students(
    course_id: int,
    service: MoodleService = Depends(get_moodle_service),
) -> Any:
    return await service.get_course_students_with_metrics(course_id)


@app.get("/api/v1/moodle/course/{course_id}/grades", dependencies=[Depends(require_authenticated)])
async def moodle_course_grades(
    course_id: int,
    service: MoodleService = Depends(get_moodle_service),
) -> Any:
    return await service.get_course_grades_report(course_id)


@app.get("/api/v1/moodle/user/{user_id}/progress", dependencies=[Depends(require_authenticated)])
async def moodle_user_progress(
    user_id: int,
    course_id: int | None = Query(default=None),
    service: MoodleService = Depends(get_moodle_service),
) -> Any:
    return await service.get_user_progress(user_id=user_id, course_id=course_id)


@app.get("/api/v1/sync/logs", dependencies=[Depends(require_authenticated)])
async def list_sync_logs(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    sync_engine: SyncEngine = Depends(get_sync_engine),
) -> Any:
    return sync_engine.get_sync_logs(date_from=date_from, date_to=date_to, status=status_filter)


@app.get("/api/v1/sync/logs/{sync_id}", dependencies=[Depends(require_authenticated)])
async def get_sync_log(sync_id: str, sync_engine: SyncEngine = Depends(get_sync_engine)) -> Any:
    result = sync_engine.get_sync_log(sync_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync_id nao encontrado.")
    return result

