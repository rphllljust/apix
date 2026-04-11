"""Responsabilidade: implementa o modulo app/sync/strategies.py."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import MoodleToSheetsRequest, SyncRunSummary
from app.sync.engine import SyncEngine


@dataclass(slots=True)
class FullSyncStrategy:
    engine: SyncEngine

    async def run(self, course_id: int, triggered_by: str = "strategy") -> SyncRunSummary:
        request = MoodleToSheetsRequest(triggered_by=triggered_by)
        request.scope.course_ids = [course_id]
        request.force_full = True
        request.incremental = False
        return await self.engine.sync_moodle_to_sheets(request)


@dataclass(slots=True)
class IncrementalSyncStrategy:
    engine: SyncEngine

    async def run(self, course_id: int, triggered_by: str = "strategy") -> SyncRunSummary:
        request = MoodleToSheetsRequest(triggered_by=triggered_by)
        request.scope.course_ids = [course_id]
        request.incremental = True
        return await self.engine.sync_moodle_to_sheets(request)


@dataclass(slots=True)
class DiffSyncStrategy:
    engine: SyncEngine

    async def run(self, course_id: int, triggered_by: str = "strategy") -> SyncRunSummary:
        request = MoodleToSheetsRequest(triggered_by=triggered_by)
        request.scope.course_ids = [course_id]
        request.incremental = True
        return await self.engine.sync_moodle_to_sheets(request)


