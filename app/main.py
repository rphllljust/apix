"""Responsabilidade: implementa o modulo app/main.py."""

from __future__ import annotations

import os

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    MoodleConnectionError,
    MoodleTokenExpiredError,
    SheetQuotaExceededError,
    SyncConflictError,
    ValidationError as AppValidationError,
)
from app.models.schemas import (
    BidirectionalRequest,
    MoodleToSheetsRequest,
    SheetsEnrollRequest,
    SheetsToMoodleRequest,
)
from app.moodle.metrics import MoodleService
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
    return [item.strip().strip("'\"") for item in raw.split(",") if item.strip()]


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    configure_logging(level=settings.log_level, log_file=settings.log_file)

    moodle_client, moodle_service, sync_engine = build_sync_engine(settings)
    scheduler = SyncScheduler(
        sync_service=sync_engine,
        interval_minutes=settings.sync_interval_minutes,
        auto_direction=settings.sync_auto_direction,
        students_input_sheet=settings.google_students_input_sheet,
        enrollments_input_sheet=settings.google_enrollments_input_sheet,
    )

    app.state.settings = settings
    app.state.moodle_client = moodle_client
    app.state.moodle_service = moodle_service
    app.state.sync_engine = sync_engine
    app.state.scheduler = scheduler
    app.state.rate_limiter = InMemoryRateLimiter(
        max_requests=settings.api_rate_limit_per_minute,
        window_seconds=60,
    )

    scheduler.start()
    logger.info(
        "API iniciada em ambiente {} com rate_limit={} req/min",
        settings.app_env,
        settings.api_rate_limit_per_minute,
    )
    try:
        yield
    finally:
        scheduler.shutdown()
        await moodle_client.close()


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
    return _error_response(
        request,
        status_code=exc.status_code,
        error_code=error_code,
        message=message_map.get(exc.status_code, "Erro HTTP na requisicao."),
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
async def health(sync_engine: SyncEngine = Depends(get_sync_engine)) -> dict[str, Any]:
    return await sync_engine.health()


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



