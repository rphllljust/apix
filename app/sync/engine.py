"""Responsabilidade: implementa o modulo app/sync/engine.py."""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from loguru import logger

from app.sheets.client import GoogleSheetsClient
from app.sheets.drive import GoogleDriveClient
from app.sheets.formatters import (
    to_course_detailed_grades_sheet_name,
    to_course_students_sheet_name,
)
from app.sheets.templates import ALUNOS_BASE_HEADERS
from app.models.schemas import (
    AlunoSheet,
    BidirectionalRequest,
    DriveToMoodleRequest,
    MoodleToSheetsRequest,
    SheetsToMoodleRequest,
    SyncDirection,
    SyncRunSummary,
)
from app.moodle.metrics import MoodleService
from app.models.database import SyncStateStore


class SyncEngine:
    def __init__(
        self,
        moodle_service: MoodleService,
        sheets_client: GoogleSheetsClient,
        state_store: SyncStateStore,
        sync_events_sheet: str,
        courses_sheet: str,
        categories_sheet: str,
        course_contents_sheet: str,
        students_sheet: str,
        enrollments_sheet: str,
        grades_sheet: str,
        completion_sheet: str,
        progress_sheet: str,
        logs_sheet: str,
        badges_sheet: str,
        competencies_sheet: str,
        groups_sheet: str,
        group_members_sheet: str,
        groupings_sheet: str,
        custom_metrics_sheet: str,
    ) -> None:
        self.moodle_service = moodle_service
        self.sheets = sheets_client
        self.state = state_store
        self.sync_events_sheet = sync_events_sheet

        self.courses_sheet = courses_sheet
        self.categories_sheet = categories_sheet
        self.course_contents_sheet = course_contents_sheet
        self.students_sheet = students_sheet
        self.enrollments_sheet = enrollments_sheet
        self.grades_sheet = grades_sheet
        self.completion_sheet = completion_sheet
        self.progress_sheet = progress_sheet
        self.logs_sheet = logs_sheet
        self.badges_sheet = badges_sheet
        self.competencies_sheet = competencies_sheet
        self.groups_sheet = groups_sheet
        self.group_members_sheet = group_members_sheet
        self.groupings_sheet = groupings_sheet
        self.custom_metrics_sheet = custom_metrics_sheet

    async def _run_sheet(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.sheets, method_name)
        return await asyncio.to_thread(method, *args, **kwargs)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _epoch_to_datetime(value: Any) -> datetime | None:
        if value in (None, "", 0, "0"):
            return None
        try:
            return datetime.fromtimestamp(int(value), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _epoch_to_date(value: Any) -> date | None:
        dt = SyncEngine._epoch_to_datetime(value)
        return dt.date() if dt else None

    @staticmethod
    def _sheet_title_for_course(course_name: str) -> str:
        return to_course_students_sheet_name(course_name)

    @staticmethod
    def _detailed_grades_sheet_title(course_name: str) -> str:
        return to_course_detailed_grades_sheet_name(course_name)

    @staticmethod
    def _status_pt(enrollment_status: str, progress_percent: float, is_complete: bool) -> str:
        if enrollment_status == "suspended":
            return "suspenso"
        if is_complete or progress_percent >= 100:
            return "concluido"
        return "ativo"

    def _build_aluno_rows_for_course(
        self,
        course_id: int,
        course_name: str,
        rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        students_by_user = {int(item["user_id"]): item for item in rows.get("students", []) if item.get("user_id")}
        enrollments = [item for item in rows.get("enrollments", []) if int(item.get("course_id", 0) or 0) == course_id]

        progress_map: dict[tuple[int, int], dict[str, Any]] = {}
        for item in rows.get("progress", []):
            key = (int(item.get("course_id", 0) or 0), int(item.get("user_id", 0) or 0))
            if key[0] != course_id or key[1] == 0:
                continue
            current = progress_map.get(key)
            pct = self._to_float(item.get("progress_percent")) or 0.0
            if current is None or pct >= (self._to_float(current.get("progress_percent")) or 0.0):
                progress_map[key] = item

        completion_count_map: dict[tuple[int, int], dict[str, int]] = {}
        for item in rows.get("completion", []):
            key = (int(item.get("course_id", 0) or 0), int(item.get("user_id", 0) or 0))
            if key[0] != course_id or key[1] == 0:
                continue
            counter = completion_count_map.setdefault(key, {"total": 0, "done": 0})
            tracking = int(item.get("tracking", 0) or 0)
            if tracking <= 0:
                continue
            counter["total"] += 1
            if int(item.get("state", 0) or 0) > 0:
                counter["done"] += 1

        badges_map: dict[tuple[int, int], list[str]] = {}
        for item in rows.get("badges", []):
            key = (int(item.get("course_id", 0) or 0), int(item.get("user_id", 0) or 0))
            if key[0] != course_id or key[1] == 0:
                continue
            name = str(item.get("badge_name") or "").strip()
            if not name:
                continue
            badges_map.setdefault(key, []).append(name)

        group_name_by_id = {
            int(item.get("group_id", 0) or 0): str(item.get("group_name") or "")
            for item in rows.get("groups", [])
            if item.get("group_id")
        }
        group_by_user: dict[tuple[int, int], str] = {}
        for member in rows.get("group_members", []):
            key = (int(member.get("course_id", 0) or 0), int(member.get("user_id", 0) or 0))
            if key[0] != course_id or key[1] == 0:
                continue
            group_id = int(member.get("group_id", 0) or 0)
            group_name = group_name_by_id.get(group_id)
            if group_name:
                group_by_user[key] = group_name

        grades_by_user: dict[tuple[int, int], list[dict[str, Any]]] = {}
        dynamic_headers: list[str] = []
        for grade in rows.get("grades", []):
            key = (int(grade.get("course_id", 0) or 0), int(grade.get("user_id", 0) or 0))
            if key[0] != course_id or key[1] == 0:
                continue
            grades_by_user.setdefault(key, []).append(grade)
            item_name = str(grade.get("item_name") or "").strip()
            if item_name and item_name not in dynamic_headers:
                dynamic_headers.append(item_name)

        aluno_rows: list[dict[str, Any]] = []
        for enrollment in enrollments:
            user_id = int(enrollment.get("user_id", 0) or 0)
            if user_id == 0:
                continue

            student = students_by_user.get(user_id, {})
            key = (course_id, user_id)
            completion_counter = completion_count_map.get(key, {"total": 0, "done": 0})
            done = completion_counter["done"]
            total = completion_counter["total"]
            pending = max(total - done, 0)

            progress_row = progress_map.get(key, {})
            progress_percent = self._to_float(progress_row.get("progress_percent")) or 0.0
            is_complete = bool(progress_row.get("is_complete"))

            user_grades = grades_by_user.get(key, [])
            final_grade = None
            final_max = None
            for grade in user_grades:
                item_name = str(grade.get("item_name") or "").lower()
                item_type = str(grade.get("item_type") or "").lower()
                if "total" in item_name or item_type in {"course", "category"}:
                    final_grade = self._to_float(grade.get("weighted_grade"))
                    if final_grade is None:
                        final_grade = self._to_float(grade.get("grade_value"))
                    final_max = self._to_float(grade.get("grade_max"))
                    break
            if final_grade is None:
                numeric = [self._to_float(g.get("grade_value")) for g in user_grades]
                numeric = [v for v in numeric if v is not None]
                final_grade = round(sum(numeric) / len(numeric), 2) if numeric else None
                final_max = None

            nota_percentual = (
                round((final_grade / final_max) * 100, 2)
                if final_grade is not None and final_max not in (None, 0)
                else None
            )

            badges = badges_map.get(key, [])
            status_enrollment = str(enrollment.get("status") or "active")
            status_pt = self._status_pt(status_enrollment, progress_percent, is_complete)
            data_matricula = (
                self._epoch_to_date(enrollment.get("timeenrolled"))
                or self._epoch_to_date(enrollment.get("lastcourseaccess"))
                or self._epoch_to_date(student.get("lastaccess"))
                or date(1970, 1, 1)
            )

            base = AlunoSheet(
                moodle_user_id=user_id,
                username=str(student.get("username") or ""),
                nome_completo=str(student.get("fullname") or "").strip(),
                email=str(student.get("email") or "").strip(),
                curso_id=course_id,
                curso_nome=course_name,
                status_matricula=status_pt,
                data_matricula=data_matricula,
                progresso_curso_percent=progress_percent,
                nota_final=final_grade,
                nota_maxima=final_max,
                nota_percentual=nota_percentual,
                total_atividades=total,
                atividades_concluidas=done,
                atividades_pendentes=pending,
                ultimo_acesso_curso=self._epoch_to_datetime(
                    enrollment.get("lastcourseaccess") or student.get("lastaccess"),
                ),
                total_badges=len(badges),
                badges_lista="; ".join(sorted(set(badges))) if badges else None,
                grupo=group_by_user.get(key),
            ).model_dump(mode="python")

            base["atividades_concluidas"] = f"{done} de {total}"
            base.pop("total_atividades", None)
            base.pop("atividades_pendentes", None)
            base.pop("total_badges", None)
            base.pop("curso_id", None)
            base.pop("curso_nome", None)

            for grade in user_grades:
                item_name = str(grade.get("item_name") or "").strip()
                if not item_name:
                    continue
                gradetype = int(grade.get("gradetype", 1) or 1)
                if gradetype == 1:
                    base[item_name] = grade.get("grade_value")
                elif gradetype == 2:
                    base[item_name] = grade.get("scale_text")
                elif gradetype == 3:
                    base[item_name] = grade.get("feedback_text")
                else:
                    base[item_name] = grade.get("grade_value")
                base[f"{item_name}__oculto"] = bool(grade.get("hidden"))

            aluno_rows.append(base)

        return aluno_rows, dynamic_headers

    @staticmethod
    def _activity_label(module_name: str) -> str:
        mapping = {
            "quiz": "Quiz",
            "assign": "Tarefa",
            "forum": "Forum",
        }
        return mapping.get(module_name.lower(), (module_name or "Atividade").capitalize())

    @staticmethod
    def _grade_value_for_sheet(grade: dict[str, Any]) -> Any:
        gradetype = int(grade.get("gradetype", 1) or 1)
        if gradetype == 1:
            return grade.get("grade_value")
        if gradetype == 2:
            return grade.get("scale_text")
        if gradetype == 3:
            return grade.get("feedback_text")
        return grade.get("grade_value")

    def _build_detailed_grades_table(
        self,
        course_id: int,
        rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[str], list[str], list[list[Any]]]:
        students_by_user = {int(item["user_id"]): item for item in rows.get("students", []) if item.get("user_id")}
        enrollments = [item for item in rows.get("enrollments", []) if int(item.get("course_id", 0) or 0) == course_id]
        grades = [item for item in rows.get("grades", []) if int(item.get("course_id", 0) or 0) == course_id]

        activity_meta: dict[str, dict[str, Any]] = {}
        activity_order: list[str] = []
        grades_by_user: dict[int, dict[str, Any]] = {}

        for grade in grades:
            user_id = int(grade.get("user_id", 0) or 0)
            if user_id == 0:
                continue
            item_id = str(grade.get("item_id") or "")
            item_name = str(grade.get("item_name") or "").strip()
            if not item_name:
                continue
            module = str(grade.get("item_module") or grade.get("item_type") or "atividade").strip()
            raw_key = f"{item_id}|{item_name}|{module}"
            column_key = raw_key
            counter = 2
            while column_key in activity_meta and activity_meta[column_key]["item_name"] != item_name:
                column_key = f"{raw_key}|{counter}"
                counter += 1

            if column_key not in activity_meta:
                activity_meta[column_key] = {
                    "item_name": item_name,
                    "module": module,
                    "max": grade.get("grade_max"),
                }
                activity_order.append(column_key)

            grades_by_user.setdefault(user_id, {})
            grades_by_user[user_id][column_key] = self._grade_value_for_sheet(grade)

        headers = ["moodle_user_id", "username", "nome_completo", "email"]
        headers.extend(activity_meta[key]["item_name"] for key in activity_order)

        subheader = ["", "", "", ""]
        for key in activity_order:
            meta = activity_meta[key]
            max_value = meta.get("max")
            max_text = f"Max {max_value}" if max_value not in (None, "") else "Max -"
            subheader.append(f"{self._activity_label(str(meta.get('module') or 'atividade'))} | {max_text}")

        table_rows: list[list[Any]] = []
        for enrollment in enrollments:
            user_id = int(enrollment.get("user_id", 0) or 0)
            if user_id == 0:
                continue
            student = students_by_user.get(user_id, {})
            row = [
                user_id,
                student.get("username"),
                student.get("fullname"),
                student.get("email"),
            ]
            user_grades = grades_by_user.get(user_id, {})
            for key in activity_order:
                row.append(user_grades.get(key))
            table_rows.append(row)

        return headers, subheader, table_rows

    @staticmethod
    def _row_warnings_map(warnings: list[str]) -> dict[int, list[str]]:
        mapping: dict[int, list[str]] = {}
        for warning in warnings:
            match = re.search(r"Linha\s+(\d+):\s*(.*)", str(warning))
            if not match:
                continue
            row_number = int(match.group(1))
            mapping.setdefault(row_number, []).append(match.group(2).strip())
        return mapping

    @staticmethod
    def _extract_first_number(value: str) -> str:
        match = re.search(r"\d+", value or "")
        return match.group(0) if match else ""

    @staticmethod
    def _normalize_header_name(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    @staticmethod
    def _get_field_by_alias(payload: dict[str, Any], aliases: list[str]) -> str:
        normalized_aliases = set(aliases)
        for key, value in payload.items():
            if key == "_row_number":
                continue
            normalized_key = SyncEngine._normalize_header_name(str(key))
            if normalized_key in normalized_aliases and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _split_full_name(full_name: str) -> tuple[str, str]:
        cleaned = " ".join((full_name or "").split()).strip()
        if not cleaned:
            return "", ""
        parts = cleaned.split(" ")
        if len(parts) == 1:
            return parts[0], "-"
        return parts[0], " ".join(parts[1:])

    @staticmethod
    def _normalize_input_student_rows(
        rows: list[dict[str, Any]],
        default_password: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        normalized_rows: list[dict[str, Any]] = []
        warnings: list[str] = []

        for item in rows:
            row_number = int(item.get("_row_number", 0) or 0)
            cpf = SyncEngine._get_field_by_alias(
                item,
                [
                    "cpf",
                    "username",
                    "usuario",
                    "moodleusername",
                ],
            )
            cpf = re.sub(r"\D", "", cpf)

            email = SyncEngine._get_field_by_alias(
                item,
                [
                    "email",
                    "emailobrigatoriamentegmail",
                ],
            ).lower()
            if email and not email.endswith("@gmail.com"):
                warnings.append(
                    f"Linha {row_number}: email deve ser Gmail (@gmail.com).",
                )

            full_name = SyncEngine._get_field_by_alias(
                item,
                [
                    "nomecompleto",
                    "nome",
                    "studentname",
                ],
            )
            firstname, lastname = SyncEngine._split_full_name(full_name)
            if not firstname:
                warnings.append(f"Linha {row_number}: nome completo obrigatorio.")

            if not cpf and not email:
                warnings.append(f"Linha {row_number}: informe CPF ou email para identificar aluno.")

            normalized_rows.append(
                {
                    "_row_number": row_number,
                    "action": "upsert",
                    "username": cpf,
                    "email": email,
                    "firstname": firstname,
                    "lastname": lastname,
                    "password": default_password,
                },
            )

        return normalized_rows, warnings

    @staticmethod
    def _normalize_input_enrollment_rows(
        rows: list[dict[str, Any]],
        fallback_course_id: int,
    ) -> list[dict[str, Any]]:
        normalized_rows: list[dict[str, Any]] = []
        for item in rows:
            row_number = int(item.get("_row_number", 0) or 0)
            cpf = SyncEngine._get_field_by_alias(
                item,
                [
                    "cpf",
                    "username",
                    "usuario",
                    "moodleusername",
                ],
            )
            cpf = re.sub(r"\D", "", cpf)
            email = SyncEngine._get_field_by_alias(
                item,
                [
                    "email",
                    "emailobrigatoriamentegmail",
                ],
            ).lower()
            course_id = SyncEngine._get_field_by_alias(
                item,
                [
                    "cursoid",
                    "courseid",
                    "curso",
                    "localquepretendefazero curso",
                    "localquepretendefazero",
                    "localquepretendefazerocurso",
                ],
            )
            course_id = SyncEngine._extract_first_number(course_id) if course_id else ""
            if not course_id:
                course_id = str(fallback_course_id)

            status_text = SyncEngine._get_field_by_alias(
                item,
                ["status", "statusmatricula", "statussync", "situacao"],
            ).strip().lower()
            action = "enroll"
            if status_text in {"suspenso", "suspend", "suspended"}:
                action = "suspend"
            if status_text in {"desmatricular", "remove", "unenroll"}:
                action = "unenroll"

            normalized_rows.append(
                {
                    "_row_number": row_number,
                    "username": cpf,
                    "email": email,
                    "course_id": course_id,
                    "action": action,
                },
            )
        return normalized_rows

    async def _append_sync_event(self, summary: SyncRunSummary, status: str) -> None:
        await self._run_sheet(
            "append_event",
            self.sync_events_sheet,
            {
                "timestamp": summary.finished_at.isoformat(),
                "direction": summary.direction.value,
                "duration_seconds": summary.duration_seconds,
                "status": status,
                "processed_counts": summary.processed_counts,
                "warnings_count": len(summary.warnings),
                "extra": summary.extra,
            },
        )

    def _save_entity_log(
        self,
        direction: str,
        entity: str,
        course_id: int,
        records_processed: int,
        records_created: int,
        records_updated: int,
        records_failed: int,
        errors: list[str],
        duration_seconds: float,
    ) -> None:
        status = "success"
        if records_failed > 0 and records_processed > records_failed:
            status = "partial"
        elif records_failed > 0 and records_processed == records_failed:
            status = "failed"

        self.state.add_entity_sync_log(
            {
                "sync_id": str(uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
                "direction": direction,
                "entity": entity,
                "course_id": course_id,
                "records_processed": records_processed,
                "records_created": records_created,
                "records_updated": records_updated,
                "records_failed": records_failed,
                "errors": errors,
                "duration_seconds": duration_seconds,
                "status": status,
            },
        )

    async def health(self) -> dict[str, Any]:
        moodle = await self.moodle_service.ping()
        sheets_ok = await self._run_sheet("ping")
        return {
            "moodle": moodle,
            "sheets_ok": sheets_ok,
            "last_moodle_to_sheets": self.state.get_datetime("moodle_to_sheets"),
            "last_sheets_to_moodle": self.state.get_datetime("sheets_to_moodle"),
        }

    async def sync_moodle_to_sheets(self, request: MoodleToSheetsRequest) -> SyncRunSummary:
        started_at = datetime.now(UTC)
        course_ids = await self.moodle_service.list_course_ids(request.scope.course_ids)
        warnings: list[str] = []

        dataset: dict[str, list[dict[str, Any]]] = {
            "courses": [],
            "categories": [],
            "course_contents": [],
            "students": [],
            "enrollments": [],
            "grades": [],
            "completion": [],
            "progress": [],
            "logs": [],
            "badges": [],
            "competencies": [],
            "groups": [],
            "group_members": [],
            "groupings": [],
            "custom_metrics": [],
        }

        course_name_map: dict[int, str] = {}
        if request.scope.include_course_catalog:
            catalog_rows, catalog_warnings = await self.moodle_service.collect_catalog(course_ids)
            warnings.extend(catalog_warnings)
            dataset["courses"].extend(catalog_rows.get("courses", []))
            dataset["categories"].extend(catalog_rows.get("categories", []))
            dataset["course_contents"].extend(catalog_rows.get("course_contents", []))
            for item in catalog_rows.get("courses", []):
                if item.get("course_id"):
                    course_name_map[int(item["course_id"])] = str(item.get("fullname") or item.get("shortname") or item["course_id"])

        per_course_metrics: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for course_id in course_ids:
            logger.info("Coletando metricas do curso {}", course_id)
            rows, row_warnings = await self.moodle_service.collect_course_metrics(course_id, request.scope)
            per_course_metrics[course_id] = rows
            warnings.extend(row_warnings)
            for key in dataset.keys():
                dataset[key].extend(rows.get(key, []))

        counts: dict[str, int] = {}

        courses_result = await self._run_sheet("upsert_records", self.courses_sheet, dataset["courses"], ["course_id"])
        categories_result = await self._run_sheet(
            "upsert_records",
            self.categories_sheet,
            dataset["categories"],
            ["category_id"],
        )
        course_contents_count = await self._run_sheet("overwrite_records", self.course_contents_sheet, dataset["course_contents"])

        students_result = await self._run_sheet("upsert_records", self.students_sheet, dataset["students"], ["user_id"])
        enrollments_result = await self._run_sheet(
            "upsert_records",
            self.enrollments_sheet,
            dataset["enrollments"],
            ["course_id", "user_id"],
        )
        groups_result = await self._run_sheet("upsert_records", self.groups_sheet, dataset["groups"], ["course_id", "group_id"])
        group_members_result = await self._run_sheet(
            "upsert_records",
            self.group_members_sheet,
            dataset["group_members"],
            ["course_id", "group_id", "user_id"],
        )
        groupings_result = await self._run_sheet(
            "upsert_records",
            self.groupings_sheet,
            dataset["groupings"],
            ["course_id", "grouping_id"],
        )

        grades_count = await self._run_sheet("overwrite_records", self.grades_sheet, dataset["grades"])
        completion_count = await self._run_sheet("overwrite_records", self.completion_sheet, dataset["completion"])
        progress_count = await self._run_sheet("overwrite_records", self.progress_sheet, dataset["progress"])
        logs_count = await self._run_sheet("overwrite_records", self.logs_sheet, dataset["logs"])
        badges_count = await self._run_sheet("overwrite_records", self.badges_sheet, dataset["badges"])
        competencies_count = await self._run_sheet("overwrite_records", self.competencies_sheet, dataset["competencies"])
        custom_metrics_count = await self._run_sheet(
            "overwrite_records",
            self.custom_metrics_sheet,
            dataset["custom_metrics"],
        )

        base_headers = ALUNOS_BASE_HEADERS
        for course_id, course_rows in per_course_metrics.items():
            course_name = course_name_map.get(course_id, f"Curso {course_id}")
            alunos_rows, _ = self._build_aluno_rows_for_course(course_id, course_name, course_rows)
            sheet_name = self._sheet_title_for_course(course_name)
            await self._run_sheet("overwrite_records", sheet_name, alunos_rows, base_headers)
            header_count = len(base_headers)
            if alunos_rows:
                all_headers = list(dict.fromkeys(key for row in alunos_rows for key in row.keys()))
                header_count = max(len(all_headers), len(base_headers))
            await self._run_sheet("apply_alunos_layout", sheet_name, max(header_count, 15))

            detailed_headers, detailed_subheader, detailed_rows = self._build_detailed_grades_table(
                course_id,
                course_rows,
            )
            detailed_sheet = self._detailed_grades_sheet_title(course_name)
            await self._run_sheet(
                "overwrite_table_with_subheader",
                detailed_sheet,
                detailed_headers,
                detailed_subheader,
                detailed_rows,
            )

        counts["courses_inserted"] = courses_result["inserted"]
        counts["courses_updated"] = courses_result["updated"]
        counts["categories_inserted"] = categories_result["inserted"]
        counts["categories_updated"] = categories_result["updated"]
        counts["course_contents"] = course_contents_count

        counts["students_inserted"] = students_result["inserted"]
        counts["students_updated"] = students_result["updated"]
        counts["enrollments_inserted"] = enrollments_result["inserted"]
        counts["enrollments_updated"] = enrollments_result["updated"]
        counts["groups_inserted"] = groups_result["inserted"]
        counts["groups_updated"] = groups_result["updated"]
        counts["group_members_inserted"] = group_members_result["inserted"]
        counts["group_members_updated"] = group_members_result["updated"]
        counts["groupings_inserted"] = groupings_result["inserted"]
        counts["groupings_updated"] = groupings_result["updated"]

        counts["grades"] = grades_count
        counts["completion"] = completion_count
        counts["progress"] = progress_count
        counts["logs"] = logs_count
        counts["badges"] = badges_count
        counts["competencies"] = competencies_count
        counts["custom_metrics"] = custom_metrics_count

        finished_at = datetime.now(UTC)
        self.state.set_datetime("moodle_to_sheets", finished_at)

        summary = SyncRunSummary(
            direction=SyncDirection.MOODLE_TO_SHEETS,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            processed_counts=counts,
            warnings=warnings,
            extra={
                "courses": course_ids,
                "triggered_by": request.triggered_by,
                "incremental": request.incremental,
                "force_full": request.force_full,
            },
        )

        self.state.add_sync_log(
            direction=summary.direction.value,
            started_at=summary.started_at,
            finished_at=summary.finished_at,
            status="partial" if summary.warnings else "success",
            processed_counts=summary.processed_counts,
            warnings=summary.warnings,
            extra=summary.extra,
        )

        for course_id, course_rows in per_course_metrics.items():
            duration = summary.duration_seconds
            users_count = len(course_rows.get("students", []))
            enroll_count = len(course_rows.get("enrollments", []))
            grade_count = len(course_rows.get("grades", []))
            progress_rows = [row for row in course_rows.get("progress", []) if int(row.get("course_id", 0) or 0) == course_id]
            self._save_entity_log("moodle_to_sheets", "users", course_id, users_count, 0, users_count, 0, [], duration)
            self._save_entity_log("moodle_to_sheets", "enrollments", course_id, enroll_count, 0, enroll_count, 0, [], duration)
            self._save_entity_log(
                "moodle_to_sheets",
                "grades",
                course_id,
                grade_count,
                0,
                grade_count,
                0,
                [],
                duration,
            )
            self._save_entity_log(
                "moodle_to_sheets",
                "progress",
                course_id,
                len(progress_rows),
                0,
                len(progress_rows),
                0,
                [],
                duration,
            )

        await self._append_sync_event(summary, "partial" if summary.warnings else "success")
        return summary

    async def sync_sheets_to_moodle(
        self,
        request: SheetsToMoodleRequest,
        students_input_sheet: str,
        enrollments_input_sheet: str,
    ) -> SyncRunSummary:
        started_at = datetime.now(UTC)
        warnings: list[str] = []
        counts: dict[str, int] = {}

        if request.process_students:
            student_rows = await self._run_sheet("read_records_with_row_number", students_input_sheet)
            result_counts, row_warnings, processed_rows = await self.moodle_service.apply_students_rows(
                student_rows,
                dry_run=request.dry_run,
            )
            warnings.extend(row_warnings)
            counts.update(result_counts)
            counts["students_input_rows"] = len(student_rows)
            if request.clear_processed_rows and processed_rows and not request.dry_run:
                await self._run_sheet("clear_rows", students_input_sheet, processed_rows)

        if request.process_enrollments:
            enrollment_rows = await self._run_sheet("read_records_with_row_number", enrollments_input_sheet)
            result_counts, row_warnings, processed_rows = await self.moodle_service.apply_enrollment_rows(
                enrollment_rows,
                dry_run=request.dry_run,
            )
            warnings.extend(row_warnings)
            counts.update(result_counts)
            counts["enrollments_input_rows"] = len(enrollment_rows)
            if request.clear_processed_rows and processed_rows and not request.dry_run:
                await self._run_sheet("clear_rows", enrollments_input_sheet, processed_rows)

        finished_at = datetime.now(UTC)
        self.state.set_datetime("sheets_to_moodle", finished_at)

        summary = SyncRunSummary(
            direction=SyncDirection.SHEETS_TO_MOODLE,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            processed_counts=counts,
            warnings=warnings,
            extra={
                "dry_run": request.dry_run,
                "triggered_by": request.triggered_by,
            },
        )

        self.state.add_sync_log(
            direction=summary.direction.value,
            started_at=summary.started_at,
            finished_at=summary.finished_at,
            status="partial" if summary.warnings else "success",
            processed_counts=summary.processed_counts,
            warnings=summary.warnings,
            extra=summary.extra,
        )

        self._save_entity_log(
            "sheets_to_moodle",
            "enrollments",
            0,
            summary.processed_counts.get("enrollments_input_rows", 0),
            summary.processed_counts.get("enrolled", 0),
            summary.processed_counts.get("suspended", 0),
            0,
            warnings,
            summary.duration_seconds,
        )

        await self._append_sync_event(summary, "partial" if summary.warnings else "success")
        return summary

    async def sync_course_full(self, course_id: int, triggered_by: str = "api") -> SyncRunSummary:
        request = MoodleToSheetsRequest()
        request.scope.course_ids = [course_id]
        request.triggered_by = triggered_by
        return await self.sync_moodle_to_sheets(request)

    async def sync_course_grades(self, course_id: int, triggered_by: str = "api") -> SyncRunSummary:
        request = MoodleToSheetsRequest()
        request.scope.course_ids = [course_id]
        request.scope.include_course_catalog = False
        request.scope.include_completion = True
        request.scope.include_progress = True
        request.scope.include_grades = True
        request.scope.include_logs = False
        request.scope.include_badges = False
        request.scope.include_competencies = False
        request.scope.include_groups = False
        request.scope.include_groupings = False
        request.scope.include_custom_metrics = False
        request.triggered_by = triggered_by
        return await self.sync_moodle_to_sheets(request)

    async def sync_course_enrollments(self, course_id: int, triggered_by: str = "api") -> SyncRunSummary:
        request = MoodleToSheetsRequest()
        request.scope.course_ids = [course_id]
        request.scope.include_course_catalog = False
        request.scope.include_completion = False
        request.scope.include_progress = False
        request.scope.include_grades = False
        request.scope.include_logs = False
        request.scope.include_badges = False
        request.scope.include_competencies = False
        request.scope.include_groups = True
        request.scope.include_groupings = True
        request.scope.include_custom_metrics = False
        request.triggered_by = triggered_by
        return await self.sync_moodle_to_sheets(request)

    async def sync_sheet_to_moodle_enroll(
        self,
        sheet_name: str,
        course_id: int,
        dry_run: bool = False,
    ) -> SyncRunSummary:
        input_rows = await self._run_sheet("read_records_with_row_number", sheet_name)
        started_at = datetime.now(UTC)
        default_password = str(
            getattr(self.moodle_service.settings, "moodle_default_new_user_password", "") or "",
        )

        students_rows, students_input_warnings = self._normalize_input_student_rows(
            input_rows,
            default_password=default_password,
        )
        enrollment_rows = self._normalize_input_enrollment_rows(
            input_rows,
            fallback_course_id=course_id,
        )

        student_counts, student_warnings, student_processed_rows = await self.moodle_service.apply_students_rows(
            students_rows,
            dry_run=dry_run,
        )
        student_processed_set = set(student_processed_rows)
        students_input_warning_map = self._row_warnings_map(students_input_warnings)
        student_warning_map = self._row_warnings_map(student_warnings)

        eligible_enrollment_rows: list[dict[str, Any]] = []
        for row in enrollment_rows:
            row_number = int(row.get("_row_number", 0) or 0)
            has_input_warning = row_number in students_input_warning_map
            has_student_warning = row_number in student_warning_map
            if row_number in student_processed_set and not has_input_warning and not has_student_warning:
                eligible_enrollment_rows.append(row)

        enroll_counts, enroll_warnings, enroll_processed_rows = await self.moodle_service.apply_enrollment_rows(
            eligible_enrollment_rows,
            dry_run=dry_run,
        )
        enroll_processed_set = set(enroll_processed_rows)

        warnings = [
            *students_input_warnings,
            *student_warnings,
            *enroll_warnings,
        ]
        warnings_by_row = self._row_warnings_map(warnings)
        updates: list[dict[str, Any]] = []
        for row in enrollment_rows:
            row_number = int(row.get("_row_number", 0) or 0)
            warning_messages = warnings_by_row.get(row_number)
            if warning_messages:
                updates.append(
                    {
                        "row_number": row_number,
                        "status": "erro",
                        "error": "; ".join(warning_messages),
                    },
                )
            elif row_number in enroll_processed_set:
                status_text = "simulado" if dry_run else "sucesso"
                updates.append({"row_number": row_number, "status": status_text, "error": ""})
            elif row_number in student_processed_set:
                updates.append(
                    {
                        "row_number": row_number,
                        "status": "erro",
                        "error": "Aluno preparado, mas matricula nao executada.",
                    },
                )
            else:
                updates.append({"row_number": row_number, "status": "erro", "error": "Linha nao processada"})
        await self._run_sheet("update_sync_status_rows", sheet_name, updates)
        finished_at = datetime.now(UTC)

        rows_failed = sum(1 for row in enrollment_rows if warnings_by_row.get(int(row.get("_row_number", 0) or 0)))
        counts = {
            "rows_read": len(input_rows),
            "students_created": int(student_counts.get("created", 0)),
            "students_updated": int(student_counts.get("updated", 0)),
            "enrolled": int(enroll_counts.get("enrolled", 0)),
            "suspended": int(enroll_counts.get("suspended", 0)),
            "unenrolled": int(enroll_counts.get("unenrolled", 0)),
            "rows_success": len(enroll_processed_set),
            "rows_failed": rows_failed,
        }

        summary = SyncRunSummary(
            direction=SyncDirection.SHEETS_TO_MOODLE,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            processed_counts=counts,
            warnings=warnings,
            extra={"sheet_name": sheet_name, "course_id": course_id, "dry_run": dry_run},
        )

        self.state.add_sync_log(
            direction=summary.direction.value,
            started_at=summary.started_at,
            finished_at=summary.finished_at,
            status="partial" if summary.warnings else "success",
            processed_counts=summary.processed_counts,
            warnings=summary.warnings,
            extra=summary.extra,
        )

        self._save_entity_log(
            "sheets_to_moodle",
            "enrollments",
            course_id,
            len(input_rows),
            counts.get("enrolled", 0) + counts.get("students_created", 0),
            counts.get("suspended", 0) + counts.get("students_updated", 0),
            counts.get("rows_failed", 0),
            warnings,
            summary.duration_seconds,
        )

        await self._append_sync_event(summary, "partial" if summary.warnings else "success")
        return summary

    async def sync_bidirectional(
        self,
        request: BidirectionalRequest,
        students_input_sheet: str,
        enrollments_input_sheet: str,
    ) -> dict[str, SyncRunSummary]:
        if request.moodle_first:
            moodle_result = await self.sync_moodle_to_sheets(request.moodle_to_sheets)
            sheets_result = await self.sync_sheets_to_moodle(
                request.sheets_to_moodle,
                students_input_sheet=students_input_sheet,
                enrollments_input_sheet=enrollments_input_sheet,
            )
        else:
            sheets_result = await self.sync_sheets_to_moodle(
                request.sheets_to_moodle,
                students_input_sheet=students_input_sheet,
                enrollments_input_sheet=enrollments_input_sheet,
            )
            moodle_result = await self.sync_moodle_to_sheets(request.moodle_to_sheets)

        return {
            "moodle_to_sheets": moodle_result,
            "sheets_to_moodle": sheets_result,
        }

    def get_sync_logs(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.state.list_entity_sync_logs(date_from=date_from, date_to=date_to, status=status)

    def get_sync_log(self, sync_id: str) -> dict[str, Any] | None:
        return self.state.get_entity_sync_log(sync_id)

    async def sync_drive_to_moodle(
        self,
        course_id: int,
        request: DriveToMoodleRequest,
    ) -> SyncRunSummary:
        """
        Sincroniza arquivos do Google Drive para o Moodle como recursos de curso.

        Args:
            course_id: ID do curso no Moodle
            request: Configuração com folder_id ou file_ids, seção do curso, etc.

        Returns:
            SyncRunSummary com lista de arquivos enviados e falhados
        """
        started_at = datetime.now(UTC)
        warnings: list[str] = []
        uploaded: list[str] = []
        failed: list[str] = []

        # Inicializa cliente Drive
        drive = await asyncio.to_thread(GoogleDriveClient, self.sheets.settings)

        # Resolve lista de arquivos
        files: list[dict[str, Any]] = []
        if request.file_ids:
            files = [
                {"id": fid, "name": fid, "mimeType": "application/octet-stream"}
                for fid in request.file_ids
            ]
            logger.info("Using {} file IDs from request", len(files))
        elif request.folder_id:
            try:
                files = await asyncio.to_thread(drive.list_files_in_folder, request.folder_id)
            except Exception as exc:
                logger.error("Falha ao listar pasta Drive folder_id={} error={}", request.folder_id, exc)
                warnings.append(f"Falha ao listar pasta: {exc}")
        else:
            warnings.append("Nenhum folder_id nem file_ids informado.")

        # Upload de cada arquivo para o Moodle
        for f in files:
            file_id = f.get("id", "")
            file_name = f.get("name", "arquivo")
            mime_type = f.get("mimeType", "application/octet-stream")

            try:
                # 1) Baixa arquivo do Drive
                content, final_mime = await asyncio.to_thread(
                    drive.download_file, file_id, mime_type
                )
                b64 = base64.b64encode(content).decode()

                # 2) Upload para draft file area do Moodle
                draft_result = await self.moodle_service.client.call(
                    "core_files_upload",
                    component="user",
                    filearea="draft",
                    itemid=0,
                    filepath="/",
                    filename=file_name,
                    filecontent=b64,
                    contextlevel="course",
                    instanceid=course_id,
                )
                logger.info("Uploaded file to draft area file={} draft_result={}", file_name, draft_result)

                # 3) Cria recurso (mod_resource) no curso
                resource_result = await self.moodle_service.client.call(
                    "mod_resource_create_instance",
                    course=course_id,
                    name=file_name,
                    section=request.section_number,
                    introformat=1,
                    intro="",
                )
                logger.info("Created resource in course file={} course_id={} resource_id={}", file_name, course_id, resource_result)
                uploaded.append(file_name)

            except Exception as exc:
                logger.error("Falha upload Drive->Moodle file={} course_id={} error={}", file_name, course_id, exc)
                failed.append(file_name)
                warnings.append(f"Falha em {file_name}: {exc}")

        finished_at = datetime.now(UTC)
        status = "success" if not failed else ("partial" if uploaded else "failed")

        summary = SyncRunSummary(
            direction=SyncDirection.SHEETS_TO_MOODLE,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            processed_counts={"uploaded": len(uploaded), "failed": len(failed)},
            warnings=warnings,
            extra={"uploaded": uploaded, "failed": failed, "triggered_by": request.triggered_by},
        )

        # Registra log estruturado
        self.state.add_sync_log(
            direction="sheets_to_moodle",
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            entity="drive_files",
            course_id=course_id,
            records_processed=len(files),
            records_created=len(uploaded),
            records_updated=0,
            records_failed=len(failed),
            errors=warnings,
        )

        await self._append_sync_event(summary, status)
        return summary


# Backward compatibility alias
SyncService = SyncEngine


