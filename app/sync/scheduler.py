"""Responsabilidade: implementa o modulo app/sync/scheduler.py."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.models.schemas import MoodleToSheetsRequest, SheetsToMoodleRequest
from app.sync.engine import SyncEngine
from app.utils.security import sanitize_text


class SyncScheduler:
    def __init__(
        self,
        sync_service: SyncEngine,
        interval_minutes: int,
        auto_direction: str,
        students_input_sheet: str,
        enrollments_input_sheet: str,
    ) -> None:
        self.sync_service = sync_service
        self.interval_minutes = interval_minutes
        self.auto_direction = auto_direction
        self.students_input_sheet = students_input_sheet
        self.enrollments_input_sheet = enrollments_input_sheet
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()

    async def _run(self) -> None:
        if self._lock.locked():
            logger.warning("Execucao automatica ignorada: job anterior ainda em andamento.")
            return

        async with self._lock:
            logger.info("Iniciando sincronizacao automatica direction={}", self.auto_direction)
            direction = self.auto_direction.strip().lower()
            try:
                if direction == "moodle_to_sheets":
                    request = MoodleToSheetsRequest(triggered_by="scheduler")
                    await self.sync_service.sync_moodle_to_sheets(request)
                    return

                if direction == "sheets_to_moodle":
                    request = SheetsToMoodleRequest(triggered_by="scheduler")
                    await self.sync_service.sync_sheets_to_moodle(
                        request,
                        students_input_sheet=self.students_input_sheet,
                        enrollments_input_sheet=self.enrollments_input_sheet,
                    )
                    return

                if direction == "bidirectional":
                    m_request = MoodleToSheetsRequest(triggered_by="scheduler")
                    s_request = SheetsToMoodleRequest(triggered_by="scheduler")
                    await self.sync_service.sync_moodle_to_sheets(m_request)
                    await self.sync_service.sync_sheets_to_moodle(
                        s_request,
                        students_input_sheet=self.students_input_sheet,
                        enrollments_input_sheet=self.enrollments_input_sheet,
                    )
                    return

                logger.warning("Direcao de sincronizacao automatica desconhecida: {}", self.auto_direction)
            except Exception as exc:
                safe_error = sanitize_text(exc)
                logger.error(
                    "Falha final no agendador direction={} error={}",
                    self.auto_direction,
                    safe_error,
                )
                try:
                    self.sync_service.state.add_error_log(
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "request_id": f"scheduler-{uuid4()}",
                            "method": "SCHEDULER",
                            "path": "/internal/scheduler/auto_sync",
                            "client_ip": "scheduler",
                            "status_code": 500,
                            "error_code": "scheduler_sync_error",
                            "message": "Falha na execucao automatica de sincronizacao.",
                            "details": {
                                "direction": self.auto_direction,
                                "error": safe_error,
                            },
                        },
                    )
                except Exception as log_exc:  # pragma: no cover - persistencia defensiva
                    logger.error("Falha ao persistir erro do agendador: {}", sanitize_text(log_exc))

    def start(self) -> None:
        if self.interval_minutes <= 0:
            logger.info("Agendador desativado (SYNC_INTERVAL_MINUTES <= 0).")
            return
        self.scheduler.add_job(
            self._run,
            trigger="interval",
            minutes=self.interval_minutes,
            id="auto_sync",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        self.scheduler.start()
        logger.info("Agendador iniciado a cada {} minuto(s).", self.interval_minutes)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Agendador finalizado.")

