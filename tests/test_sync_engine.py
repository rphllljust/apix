"""Testes do motor de sincronizacao com foco em idempotencia e normalizacao de entrada."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.exceptions import MoodleAuthError
from app.models.database import SyncStateStore
from app.models.schemas import MoodleToSheetsRequest
from app.sheets.formatters import to_course_students_sheet_name
from app.sync.engine import SyncEngine


class FakeMoodleService:
    """Servico Moodle fake com dataset deterministico para testes de idempotencia."""

    def __init__(self) -> None:
        self.settings = SimpleNamespace(moodle_default_new_user_password="Senha@123")
        self.received_student_rows: list[dict[str, Any]] = []
        self.received_enrollment_rows: list[dict[str, Any]] = []

    async def ping(self) -> dict[str, Any]:
        return {"site_name": "AVA Teste", "username": "api", "moodle_release": "4.3"}

    async def list_course_ids(self, _: list[int] | None = None) -> list[int]:
        return [125]

    async def collect_catalog(self, course_ids: list[int]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        return (
            {
                "courses": [
                    {
                        "course_id": int(course_ids[0]),
                        "fullname": "Curso Integracao",
                        "shortname": "CURSO_INT",
                    },
                ],
                "categories": [],
                "course_contents": [],
            },
            [],
        )

    async def collect_course_metrics(self, course_id: int, _: Any) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        return (
            {
                "courses": [],
                "categories": [],
                "course_contents": [],
                "students": [
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "username": "12345678909",
                        "fullname": "José da Conceição",
                        "email": "jose@example.com",
                        "lastaccess": 1712000000,
                    },
                ],
                "enrollments": [
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "status": "active",
                        "timeenrolled": 1711000000,
                        "lastcourseaccess": 1712000000,
                    },
                ],
                "grades": [
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "item_id": 10,
                        "item_name": "Quiz 1",
                        "item_module": "quiz",
                        "item_type": "mod",
                        "grade_value": None,
                        "grade_max": 10.0,
                        "gradetype": 1,
                        "hidden": 0,
                    },
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "item_id": 11,
                        "item_name": "Tarefa 1",
                        "item_module": "assign",
                        "item_type": "mod",
                        "grade_value": 0,
                        "grade_max": 10.0,
                        "gradetype": 1,
                        "hidden": 0,
                    },
                ],
                "completion": [
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "activity_id": 10,
                        "tracking": 2,
                        "state": 1,
                    },
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "activity_id": 11,
                        "tracking": 2,
                        "state": 0,
                    },
                ],
                "progress": [
                    {
                        "course_id": course_id,
                        "user_id": 1,
                        "progress_percent": 50.0,
                        "is_complete": False,
                    },
                ],
                "logs": [],
                "badges": [],
                "competencies": [],
                "groups": [],
                "group_members": [],
                "groupings": [],
                "custom_metrics": [],
            },
            [],
        )

    async def apply_students_rows(
        self,
        rows: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> tuple[dict[str, int], list[str], list[int]]:
        _ = dry_run
        self.received_student_rows = copy.deepcopy(rows)
        warnings: list[str] = []
        processed: list[int] = []
        created = 0
        updated = 0
        for row in rows:
            row_number = int(row.get("_row_number", 0) or 0)
            email = str(row.get("email") or "")
            if not email or email.endswith("@hotmail.com"):
                warnings.append(f"Linha {row_number}: email invalido para criacao.")
                continue
            processed.append(row_number)
            if email.startswith("novo"):
                created += 1
            else:
                updated += 1
        return {"created": created, "updated": updated}, warnings, processed

    async def apply_enrollment_rows(
        self,
        rows: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> tuple[dict[str, int], list[str], list[int]]:
        _ = dry_run
        self.received_enrollment_rows = copy.deepcopy(rows)
        processed = [int(row.get("_row_number", 0) or 0) for row in rows]
        counts = {"enrolled": len(rows), "suspended": 0, "unenrolled": 0}
        return counts, [], processed


class FakeSheetsClient:
    """Cliente de planilha in-memory para validar comportamento idempotente."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.detailed: dict[str, dict[str, Any]] = {}
        self.rows_by_sheet: dict[str, list[dict[str, Any]]] = {}
        self.status_updates: dict[str, list[dict[str, Any]]] = {}

    def ping(self) -> bool:
        return True

    def upsert_records(self, sheet_name: str, records: list[dict[str, Any]], key_fields: list[str]) -> dict[str, int]:
        table = self.tables.setdefault(sheet_name, [])
        inserted = 0
        updated = 0

        for record in records:
            key = tuple(record.get(field) for field in key_fields)
            matched_index = None
            for idx, current in enumerate(table):
                current_key = tuple(current.get(field) for field in key_fields)
                if current_key == key:
                    matched_index = idx
                    break
            if matched_index is None:
                table.append(copy.deepcopy(record))
                inserted += 1
            else:
                table[matched_index] = copy.deepcopy(record)
                updated += 1

        return {"inserted": inserted, "updated": updated}

    def overwrite_records(
        self,
        sheet_name: str,
        records: list[dict[str, Any]],
        headers: list[str] | None = None,
    ) -> int:
        _ = headers
        self.tables[sheet_name] = [copy.deepcopy(row) for row in records]
        return len(records)

    def overwrite_table_with_subheader(
        self,
        sheet_name: str,
        headers: list[str],
        subheader: list[str],
        rows: list[list[Any]],
    ) -> int:
        self.detailed[sheet_name] = {
            "headers": copy.deepcopy(headers),
            "subheader": copy.deepcopy(subheader),
            "rows": copy.deepcopy(rows),
        }
        return len(rows)

    def apply_alunos_layout(self, sheet_name: str, header_count: int) -> None:
        _ = sheet_name
        _ = header_count

    def append_event(self, sheet_name: str, payload: dict[str, Any]) -> None:
        self.events.append({"sheet": sheet_name, **copy.deepcopy(payload)})

    def read_records_with_row_number(self, sheet_name: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.rows_by_sheet.get(sheet_name, []))

    def update_sync_status_rows(
        self,
        sheet_name: str,
        updates: list[dict[str, Any]],
        status_header: str = "Status Sync",
        error_header: str = "Erro",
    ) -> None:
        _ = status_header
        _ = error_header
        self.status_updates[sheet_name] = copy.deepcopy(updates)


def build_engine(
    tmp_path: Path,
    moodle_service: FakeMoodleService | None = None,
) -> tuple[SyncEngine, FakeSheetsClient]:
    """Cria engine com dependencias fake e banco SQLite temporario."""
    moodle_service = moodle_service or FakeMoodleService()
    sheets_client = FakeSheetsClient()
    state = SyncStateStore(str(tmp_path / "sync_state.db"))
    engine = SyncEngine(
        moodle_service=moodle_service,
        sheets_client=sheets_client,
        state_store=state,
        sync_events_sheet="Log de Sincronizacao",
        courses_sheet="courses",
        categories_sheet="categories",
        course_contents_sheet="course_contents",
        students_sheet="students",
        enrollments_sheet="enrollments",
        grades_sheet="grades",
        completion_sheet="completion",
        progress_sheet="progress",
        logs_sheet="logs",
        badges_sheet="badges",
        competencies_sheet="competencies",
        groups_sheet="groups",
        group_members_sheet="group_members",
        groupings_sheet="groupings",
        custom_metrics_sheet="custom_metrics",
    )
    return engine, sheets_client


def test_course_sheet_name_sanitization() -> None:
    """Mantem sanitizacao de nome de aba para caracteres proibidos."""
    result = to_course_students_sheet_name("Curso/Teste?*")
    assert result.startswith("Alunos — ")
    assert "/" not in result
    assert "?" not in result


def test_normalize_google_forms_columns_for_enrollment() -> None:
    """Normaliza colunas de formulario Google para payload de matricula."""
    rows = [
        {
            "_row_number": 2,
            "Email - (Obrigatoriamente Gmail)": "gestor.idep@gmail.com",
            "Nome completo": "Aluno Teste",
            "CPF": "123.456.789-09",
            "Local que pretende fazer o curso": "Curso 125 - Turma A",
        },
    ]

    normalized = SyncEngine._normalize_input_enrollment_rows(rows, fallback_course_id=999)

    assert normalized[0]["_row_number"] == 2
    assert normalized[0]["email"] == "gestor.idep@gmail.com"
    assert normalized[0]["username"] == "12345678909"
    assert normalized[0]["course_id"] == "125"


def test_expand_compact_csv_row_with_status_columns() -> None:
    """Expande coluna CSV mesmo quando existem colunas de status auxiliares."""
    rows = [
        {
            "_row_number": 2,
            "cpf,email,nome,curso_id,status": "52998224725,aluno.teste@gmail.com,Aluno Teste Silva,125,ativo",
            "Status Sync": "sucesso",
            "Erro": "",
        },
    ]

    expanded = SyncEngine._expand_compact_csv_rows(rows)

    assert expanded[0]["cpf"] == "52998224725"
    assert expanded[0]["email"] == "aluno.teste@gmail.com"
    assert expanded[0]["nome"] == "Aluno Teste Silva"
    assert expanded[0]["curso_id"] == "125"
    assert expanded[0]["Status Sync"] == "sucesso"


def test_resolve_field_name_marks_ambiguous_as_unrecognized() -> None:
    """Quando houver colisao de aliases, classifica como nao reconhecido com sugestao."""
    alias_map = {
        "username": {"documento"},
        "email": {"documento"},
    }

    resolved = SyncEngine._resolve_field_name("documento", alias_map)

    assert resolved["status"] == "campo_nao_reconhecido"
    assert resolved["motivo"] == "ambiguidade"
    assert resolved["campo_moodle_sugerido"] == "username"


def test_sync_idempotency_same_data_after_two_runs(tmp_path: Path) -> None:
    """Executa sync duas vezes e garante ausencia de duplicacao de dados."""

    async def scenario() -> None:
        engine, sheets = build_engine(tmp_path)
        request = MoodleToSheetsRequest()

        summary_1 = await engine.sync_moodle_to_sheets(request)
        first_snapshot = copy.deepcopy(sheets.tables)

        summary_2 = await engine.sync_moodle_to_sheets(request)
        second_snapshot = copy.deepcopy(sheets.tables)

        assert summary_1.direction.value == "moodle_to_sheets"
        assert summary_2.direction.value == "moodle_to_sheets"

        for key in [
            "courses",
            "students",
            "enrollments",
            "grades",
            "completion",
            "progress",
        ]:
            assert first_snapshot.get(key) == second_snapshot.get(key)

        assert len(sheets.events) == 2
        alunos_sheet = "Alunos — Curso Integracao"
        assert alunos_sheet in second_snapshot
        assert second_snapshot[alunos_sheet][0]["nome_completo"] == "José da Conceição"

    asyncio.run(scenario())


def test_sync_moodle_to_sheets_handles_permission_error_as_partial(tmp_path: Path) -> None:
    """Permissao insuficiente no Moodle vira warning parcial, sem quebrar endpoint."""

    async def scenario() -> None:
        moodle_service = FakeMoodleService()

        async def denied_collect_metrics(
            course_id: int,
            _: Any,
        ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
            _ = course_id
            raise MoodleAuthError("Sem permissao para listar usuarios do curso.", errorcode="accessexception")

        moodle_service.collect_course_metrics = denied_collect_metrics  # type: ignore[assignment]
        engine, sheets = build_engine(tmp_path, moodle_service=moodle_service)

        summary = await engine.sync_moodle_to_sheets(MoodleToSheetsRequest())

        assert summary.direction.value == "moodle_to_sheets"
        assert summary.processed_counts["students_inserted"] == 0
        assert summary.processed_counts["enrollments_inserted"] == 0
        assert any("Falha ao coletar metricas do curso 125" in item for item in summary.warnings)
        assert any("dados existentes em planilhas foram preservados" in item for item in summary.warnings)
        assert "students" not in sheets.tables
        assert "enrollments" not in sheets.tables

    asyncio.run(scenario())


def test_sync_sheet_to_moodle_enroll_upsert_user_and_enroll(tmp_path: Path) -> None:
    """Executa fluxo completo da aba de inscricao (upsert + matricula) com status por linha."""

    async def scenario() -> None:
        service = FakeMoodleService()
        engine, sheets = build_engine(tmp_path, moodle_service=service)
        sheet_name = "Inscrever Novos Alunos"
        sheets.rows_by_sheet[sheet_name] = [
            {
                "_row_number": 2,
                "Email - (Obrigatoriamente Gmail)": "novo.aluno@gmail.com",
                "Local que pretende fazer o curso": "Curso 125 - Turma A",
                "Nome completo": "Maria Conceicao Silva",
                "CPF": "390.533.447-05",
                "Campo livre nao mapeado": "qualquer valor",
            },
            {
                "_row_number": 3,
                "Email - (Obrigatoriamente Gmail)": "joao@hotmail.com",
                "Local que pretende fazer o curso": "Curso 125 - Turma B",
                "Nome completo": "Joao Teste",
                "CPF": "390.533.447-05",
            },
        ]

        summary = await engine.sync_sheet_to_moodle_enroll(
            sheet_name=sheet_name,
            course_id=125,
            dry_run=False,
        )

        assert summary.processed_counts["rows_read"] == 2
        assert summary.processed_counts["students_created"] == 1
        assert summary.processed_counts["students_updated"] == 0
        assert summary.processed_counts["enrolled"] == 1
        assert summary.processed_counts["rows_failed"] == 1
        assert any("gmail" in warning.lower() for warning in summary.warnings)

        assert len(service.received_student_rows) == 2
        first_student = service.received_student_rows[0]
        assert first_student["firstname"] == "Maria"
        assert first_student["lastname"] == "Conceicao Silva"
        assert first_student["password"] == "Senha@123"
        assert first_student["username"] == "39053344705"

        assert len(service.received_enrollment_rows) == 1
        assert service.received_enrollment_rows[0]["course_id"] == "125"
        assert service.received_enrollment_rows[0]["email"] == "novo.aluno@gmail.com"

        updates = sheets.status_updates[sheet_name]
        status_by_row = {int(item["row_number"]): item for item in updates}
        assert status_by_row[2]["status"] == "sucesso"
        assert status_by_row[2]["error"] == ""
        assert status_by_row[3]["status"] == "erro"
        assert "gmail" in str(status_by_row[3]["error"]).lower()

        normalizacao = summary.extra.get("normalizacao_campos") or {}
        totais = normalizacao.get("totais") or {}
        assert normalizacao.get("schema") == "normalizacao_campos_v1"
        assert int(totais.get("total_campos_avaliados", 0)) > 0
        assert int(totais.get("campo_nao_reconhecido", 0)) >= 1

    asyncio.run(scenario())
