"""Responsabilidade: define schema GraphQL para consultas e sincronizacao do middleware."""

from __future__ import annotations

from typing import Any

import strawberry
from fastapi import Request
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from app.auth import require_api_auth
from app.models.schemas import SyncRunSummary


def _require_graphql_auth(request: Request) -> None:
    require_api_auth(
        request=request,
        x_api_key=request.headers.get("X-API-Key"),
        authorization=request.headers.get("Authorization"),
    )


@strawberry.type
class MoodleHealthType:
    site_name: str | None = None
    username: str | None = None
    moodle_release: str | None = None


@strawberry.type
class HealthType:
    moodle: MoodleHealthType
    sheets_ok: bool
    last_moodle_to_sheets: str | None = None
    last_sheets_to_moodle: str | None = None


@strawberry.type
class CourseType:
    id: int
    shortname: str | None = None
    fullname: str | None = None
    visible: int | None = None


@strawberry.type
class SyncLogType:
    sync_id: str
    timestamp: str
    direction: str
    entity: str
    course_id: int
    records_processed: int
    records_created: int
    records_updated: int
    records_failed: int
    errors: list[str]
    duration_seconds: float
    status: str


@strawberry.type
class SyncSummaryType:
    direction: str
    started_at: str
    finished_at: str
    duration_seconds: float
    processed_counts: JSON
    warnings: list[str]
    extra: JSON


@strawberry.input
class TriggerCourseSyncInput:
    course_id: int
    mode: str


def _to_summary_type(summary: SyncRunSummary) -> SyncSummaryType:
    return SyncSummaryType(
        direction=summary.direction.value,
        started_at=summary.started_at.isoformat(),
        finished_at=summary.finished_at.isoformat(),
        duration_seconds=summary.duration_seconds,
        processed_counts=summary.processed_counts,
        warnings=[str(item) for item in summary.warnings],
        extra=summary.extra,
    )


@strawberry.type
class Query:
    @strawberry.field
    async def health(self, info: strawberry.Info) -> HealthType:
        request: Request = info.context["request"]
        _require_graphql_auth(request)
        sync_engine = request.app.state.sync_engine
        payload = await sync_engine.health()
        moodle_data = payload.get("moodle") or {}
        return HealthType(
            moodle=MoodleHealthType(
                site_name=moodle_data.get("site_name"),
                username=moodle_data.get("username"),
                moodle_release=moodle_data.get("moodle_release"),
            ),
            sheets_ok=bool(payload.get("sheets_ok")),
            last_moodle_to_sheets=(
                payload.get("last_moodle_to_sheets").isoformat()
                if payload.get("last_moodle_to_sheets")
                else None
            ),
            last_sheets_to_moodle=(
                payload.get("last_sheets_to_moodle").isoformat()
                if payload.get("last_sheets_to_moodle")
                else None
            ),
        )

    @strawberry.field
    async def courses(self, info: strawberry.Info) -> list[CourseType]:
        request: Request = info.context["request"]
        _require_graphql_auth(request)
        service = request.app.state.moodle_service
        courses = await service.get_courses()
        output: list[CourseType] = []
        for item in courses:
            output.append(
                CourseType(
                    id=int(item.get("id", 0) or 0),
                    shortname=item.get("shortname"),
                    fullname=item.get("fullname"),
                    visible=int(item.get("visible")) if item.get("visible") is not None else None,
                ),
            )
        return output

    @strawberry.field
    async def sync_logs(
        self,
        info: strawberry.Info,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
    ) -> list[SyncLogType]:
        request: Request = info.context["request"]
        _require_graphql_auth(request)
        sync_engine = request.app.state.sync_engine
        logs = sync_engine.get_sync_logs(date_from=date_from, date_to=date_to, status=status)
        output: list[SyncLogType] = []
        for row in logs:
            output.append(
                SyncLogType(
                    sync_id=str(row.get("sync_id") or ""),
                    timestamp=str(row.get("timestamp") or ""),
                    direction=str(row.get("direction") or ""),
                    entity=str(row.get("entity") or ""),
                    course_id=int(row.get("course_id") or 0),
                    records_processed=int(row.get("records_processed") or 0),
                    records_created=int(row.get("records_created") or 0),
                    records_updated=int(row.get("records_updated") or 0),
                    records_failed=int(row.get("records_failed") or 0),
                    errors=[str(item) for item in row.get("errors", [])],
                    duration_seconds=float(row.get("duration_seconds") or 0.0),
                    status=str(row.get("status") or ""),
                ),
            )
        return output


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def trigger_course_sync(
        self,
        info: strawberry.Info,
        input: TriggerCourseSyncInput,
    ) -> SyncSummaryType:
        request: Request = info.context["request"]
        _require_graphql_auth(request)
        sync_engine = request.app.state.sync_engine
        mode = input.mode.strip().lower()

        if mode == "full":
            result = await sync_engine.sync_course_full(input.course_id, triggered_by="graphql")
            return _to_summary_type(result)
        if mode == "grades":
            result = await sync_engine.sync_course_grades(input.course_id, triggered_by="graphql")
            return _to_summary_type(result)
        if mode == "enrollments":
            result = await sync_engine.sync_course_enrollments(
                input.course_id,
                triggered_by="graphql",
            )
            return _to_summary_type(result)

        raise ValueError(f"Modo de sincronizacao nao suportado: {input.mode}")


def create_graphql_router() -> GraphQLRouter:
    """Cria roteador GraphQL com queries e mutations da API."""
    schema = strawberry.Schema(query=Query, mutation=Mutation)

    async def context_getter(request: Request) -> dict[str, Any]:
        return {"request": request}

    return GraphQLRouter(
        schema=schema,
        path="/api/v1/graphql",
        graphiql=True,
        context_getter=context_getter,
    )
