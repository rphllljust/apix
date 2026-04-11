"""Responsabilidade: implementa o modulo app/models/schemas.py."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SyncDirection(str, Enum):
    MOODLE_TO_SHEETS = "moodle_to_sheets"
    SHEETS_TO_MOODLE = "sheets_to_moodle"
    BIDIRECTIONAL = "bidirectional"


class SyncScope(BaseModel):
    course_ids: list[int] | None = None
    include_course_catalog: bool = True
    include_grades: bool = True
    include_completion: bool = True
    include_progress: bool = True
    include_logs: bool = True
    include_badges: bool = True
    include_competencies: bool = True
    include_groups: bool = True
    include_groupings: bool = True
    include_custom_metrics: bool = True


class MoodleToSheetsRequest(BaseModel):
    scope: SyncScope = Field(default_factory=SyncScope)
    incremental: bool = True
    force_full: bool = False
    triggered_by: str = "api"


class SheetsToMoodleRequest(BaseModel):
    dry_run: bool = False
    process_students: bool = True
    process_enrollments: bool = True
    clear_processed_rows: bool = False
    triggered_by: str = "api"


class BidirectionalRequest(BaseModel):
    moodle_to_sheets: MoodleToSheetsRequest = Field(default_factory=MoodleToSheetsRequest)
    sheets_to_moodle: SheetsToMoodleRequest = Field(default_factory=SheetsToMoodleRequest)
    moodle_first: bool = True


class SyncRunSummary(BaseModel):
    direction: SyncDirection
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    processed_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class AlunoSheet(BaseModel):
    """Representa uma linha na planilha de alunos."""

    model_config = {"extra": "allow"}

    moodle_user_id: int
    username: str  # CPF sem pontuacao
    nome_completo: str
    email: str
    curso_id: int
    curso_nome: str
    status_matricula: Literal["ativo", "suspenso", "concluido"]
    data_matricula: date

    progresso_curso_percent: float = 0.0
    nota_final: Optional[float] = None
    nota_maxima: Optional[float] = None
    nota_percentual: Optional[float] = None

    total_atividades: int = 0
    atividades_concluidas: int = 0
    atividades_pendentes: int = 0

    ultimo_acesso_curso: Optional[datetime] = None
    total_badges: int = 0
    badges_lista: Optional[str] = None
    grupo: Optional[str] = None


class SyncLog(BaseModel):
    """Registro de cada sincronizacao executada."""

    sync_id: str
    timestamp: datetime
    direction: Literal["moodle_to_sheets", "sheets_to_moodle"]
    entity: Literal["users", "grades", "enrollments", "progress"]
    course_id: int
    records_processed: int
    records_created: int
    records_updated: int
    records_failed: int
    errors: list[str]
    duration_seconds: float
    status: Literal["success", "partial", "failed"]


class SheetsEnrollRequest(BaseModel):
    sheet_name: str
    course_id: int
    dry_run: bool = False

