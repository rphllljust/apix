"""Responsabilidade: implementa o modulo app/dependencies.py."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Header, HTTPException, Request, status
from loguru import logger

from app.auth import AuthContext, require_api_auth
from app.config import Settings
from app.models.database import SyncStateStore
from app.moodle.client import MoodleClient
from app.moodle.metrics import MoodleService
from app.sheets.client import GoogleSheetsClient
from app.sync.engine import SyncEngine


def configure_logging(level: str, log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        enqueue=True,
    )
    logger.add(
        log_file,
        level=level.upper(),
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        encoding="utf-8",
    )


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings: Settings = request.app.state.settings
    if settings.middleware_api_key and x_api_key != settings.middleware_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key invalida.",
        )


def require_authenticated(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthContext:
    return require_api_auth(
        request=request,
        x_api_key=x_api_key,
        authorization=authorization,
    )


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_moodle_service(request: Request) -> MoodleService:
    return request.app.state.moodle_service


def get_sync_engine(request: Request) -> SyncEngine:
    return request.app.state.sync_engine


def build_sync_engine(settings: Settings) -> tuple[MoodleClient, MoodleService, SyncEngine]:
    moodle_client = MoodleClient(settings)
    sheets_client = GoogleSheetsClient(settings)
    moodle_service = MoodleService(moodle_client, settings)
    state_store = SyncStateStore(settings.sync_state_db_path)
    sync_engine = SyncEngine(
        moodle_service=moodle_service,
        sheets_client=sheets_client,
        state_store=state_store,
        sync_events_sheet=settings.google_sync_events_sheet,
        courses_sheet=settings.google_courses_sheet,
        categories_sheet=settings.google_categories_sheet,
        course_contents_sheet=settings.google_course_contents_sheet,
        students_sheet=settings.google_students_sheet,
        enrollments_sheet=settings.google_enrollments_sheet,
        grades_sheet=settings.google_grades_sheet,
        completion_sheet=settings.google_completion_sheet,
        progress_sheet=settings.google_progress_sheet,
        logs_sheet=settings.google_logs_sheet,
        badges_sheet=settings.google_badges_sheet,
        competencies_sheet=settings.google_competencies_sheet,
        groups_sheet=settings.google_groups_sheet,
        group_members_sheet=settings.google_group_members_sheet,
        groupings_sheet=settings.google_groupings_sheet,
        custom_metrics_sheet=settings.google_custom_metrics_sheet,
    )
    return moodle_client, moodle_service, sync_engine


