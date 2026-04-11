"""Responsabilidade: implementa o modulo app/moodle/metrics.py."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.moodle.client import MoodleClient
from app.config import Settings
from app.exceptions import ValidationError
from app.moodle.endpoints import get_wsfunction
from app.moodle.exceptions import MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError
from app.models.schemas import SyncScope
from app.utils.validators import (
    assert_valid_cpf,
    assert_valid_email,
    is_valid_cpf,
    is_valid_email,
    normalize_cpf,
)


class MoodleService:
    def __init__(self, client: MoodleClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        max_concurrency = max(1, min(settings.moodle_max_concurrency, 50))
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def ping(self) -> dict[str, Any]:
        info = await self.client.call("core_webservice_get_site_info")
        return {
            "site_name": info.get("sitename"),
            "username": info.get("username"),
            "moodle_release": info.get("release"),
        }

    async def list_course_ids(self, course_ids: list[int] | None = None) -> list[int]:
        if course_ids:
            return sorted(set(course_ids))
        if self.settings.moodle_default_course_ids:
            return sorted(set(self.settings.moodle_default_course_ids))

        courses = await self.client.call("core_course_get_courses")
        ids = [int(course["id"]) for course in courses if int(course.get("id", 0)) > 1]
        return sorted(set(ids))

    async def get_courses(self) -> list[dict[str, Any]]:
        payload = await self.client.call("core_course_get_courses")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def get_courses_by_field(self, field: str, value: str) -> list[dict[str, Any]]:
        payload = await self.client.call(
            "core_course_get_courses_by_field",
            field=field,
            value=value,
        )
        if isinstance(payload, dict):
            courses = payload.get("courses")
            if isinstance(courses, list):
                return [item for item in courses if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def get_categories(self) -> list[dict[str, Any]]:
        payload = await self.client.call("core_course_get_categories")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def get_course_contents(self, course_id: int) -> list[dict[str, Any]]:
        payload = await self.client.call("core_course_get_contents", courseid=course_id)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    async def get_enrolled_users(self, course_id: int) -> list[dict[str, Any]]:
        payload = await self.client.call(get_wsfunction("enrollment", "list_users"), courseid=course_id)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    @staticmethod
    def _find_payload_rows(payload: Any, preferred_keys: list[str]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in preferred_keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [payload]
        return []

    async def _try_first_success(
        self,
        calls: list[tuple[str, dict[str, Any]]],
    ) -> tuple[str, Any]:
        last_error: Exception | None = None
        for wsfunction, params in calls:
            try:
                async with self._semaphore:
                    response = await self.client.call(wsfunction, **params)
                return wsfunction, response
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                last_error = exc
                logger.debug(
                    "Moodle wsfunction failed wsfunction={} params={} err={}",
                    wsfunction,
                    params,
                    exc,
                )
        raise MoodleAPIError(
            errorcode="wsfunction_unavailable",
            message=f"Nenhuma wsfunction funcionou. Erro final: {last_error}",
        )

    @staticmethod
    def _extract_custom_fields(user: dict[str, Any]) -> dict[str, Any]:
        fields = {}
        for item in user.get("customfields", []) or []:
            shortname = item.get("shortname")
            value = item.get("value")
            if shortname:
                fields[f"cf_{shortname}"] = value
        return fields

    @staticmethod
    def _extract_enrollment_status(user: dict[str, Any]) -> str:
        enrolments = user.get("enrolledcourses") or user.get("enrolments") or []
        statuses = []
        for enrolment in enrolments:
            status = enrolment.get("status")
            if status is None:
                continue
            statuses.append(str(status))
        if not statuses:
            if int(user.get("suspended", 0) or 0) == 1:
                return "suspended"
            return "active"
        if any(status in {"1", "suspended"} for status in statuses):
            return "suspended"
        return "active"

    @staticmethod
    def _normalize_cpf(value: str | None) -> str:
        return normalize_cpf(value)

    @staticmethod
    def _is_valid_cpf(cpf: str) -> bool:
        return is_valid_cpf(cpf)

    @staticmethod
    def _is_valid_email(email: str | None) -> bool:
        return is_valid_email(email)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _chunk_list(values: list[dict[str, Any]], chunk_size: int) -> list[list[dict[str, Any]]]:
        size = max(1, int(chunk_size))
        return [values[idx : idx + size] for idx in range(0, len(values), size)]

    def _extract_grade_items(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for value in node:
                    walk(value)
                return
            if not isinstance(node, dict):
                return

            marker_keys = {
                "itemid",
                "itemname",
                "graderaw",
                "grademax",
                "gradeformatted",
                "finalgrade",
                "gradetype",
            }
            if marker_keys.intersection(node.keys()):
                items.append(node)

            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)

        walk(payload)
        return items

    def _normalize_grade_item(
        self,
        course_id: int,
        user_id: int,
        source_function: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        gradetype = self._as_int(item.get("gradetype"))
        grade_raw = self._as_float(item.get("graderaw"))
        if grade_raw is None and item.get("grade") not in (None, ""):
            grade_raw = self._as_float(item.get("grade"))
        grade_max = self._as_float(item.get("grademax"))
        weighted_grade = self._as_float(item.get("finalgrade"))
        hidden = bool(int(item.get("hidden", 0) or 0))

        grade_type_name = {
            1: "numeric",
            2: "scale",
            3: "text",
        }.get(gradetype or 1, "numeric")

        scale_text = None
        feedback_text = None
        if gradetype == 2:
            scale_text = item.get("gradeformatted") or item.get("gradestr") or item.get("str_grade")
        if gradetype == 3:
            feedback_text = item.get("feedback") or item.get("feedbacktext") or item.get("gradeformatted")

        return {
            "course_id": course_id,
            "user_id": user_id,
            "item_id": item.get("itemid"),
            "item_name": item.get("itemname") or item.get("name"),
            "item_module": item.get("itemmodule") or item.get("modname"),
            "item_type": item.get("itemtype"),
            "gradetype": gradetype,
            "grade_type_name": grade_type_name,
            "grade_value": grade_raw,
            "grade_is_null": grade_raw is None,
            "grade_max": grade_max,
            "grade_percent": (grade_raw / grade_max * 100) if grade_raw is not None and grade_max else None,
            "weighted_grade": weighted_grade,
            "hidden": hidden,
            "aggregationweight": item.get("aggregationweight"),
            "aggregationcoef": item.get("aggregationcoef"),
            "scale_text": scale_text,
            "feedback_text": feedback_text,
            "source_function": source_function,
            "raw": item,
        }

    async def _collect_grade_rows(
        self,
        course_id: int,
        user_id: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        calls = [
            ("gradereport_user_get_grade_items", {"courseid": course_id, "userid": user_id}),
            ("gradereport_user_get_grades_table", {"courseid": course_id, "userid": user_id}),
            ("core_grades_get_grades", {"courseid": course_id, "userids": [user_id]}),
            ("gradereport_overview_get_course_grades", {"userid": user_id}),
        ]
        try:
            source_function, payload = await self._try_first_success(calls)
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            return [], [f"Notas indisponiveis curso={course_id} user={user_id}: {exc}"]

        rows = self._extract_grade_items(payload)
        normalized = []
        for row in rows or [{}]:
            normalized.append(self._normalize_grade_item(course_id, user_id, source_function, row))
        return normalized, []

    async def _collect_assignment_quiz_grade_rows(
        self,
        course_id: int,
        user_ids: list[int],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []

        try:
            contents = await self.get_course_contents(course_id)
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            return [], [f"Conteudo do curso indisponivel para notas detalhadas curso={course_id}: {exc}"]

        assignment_ids: list[int] = []
        quizzes: list[tuple[int, str]] = []
        for section in contents:
            for module in section.get("modules", []) or []:
                modname = str(module.get("modname") or "").lower()
                instance = self._as_int(module.get("instance"))
                if not instance:
                    continue
                if modname == "assign":
                    assignment_ids.append(instance)
                elif modname == "quiz":
                    quizzes.append((instance, str(module.get("name") or f"quiz_{instance}")))

        if assignment_ids:
            try:
                source_function, payload = await self._try_first_success(
                    [("mod_assign_get_grades", {"assignmentids": assignment_ids})],
                )
                assignments = self._find_payload_rows(payload, ["assignments", "data"])
                for assignment in assignments:
                    assignment_name = assignment.get("assignmentname") or assignment.get("name")
                    for grade in assignment.get("grades", []) or []:
                        user_id = self._as_int(grade.get("userid"))
                        if user_id is None:
                            continue
                        rows.append(
                            {
                                "course_id": course_id,
                                "user_id": user_id,
                                "item_name": assignment_name,
                                "item_module": "assign",
                                "gradetype": 1,
                                "grade_type_name": "numeric",
                                "grade_value": self._as_float(grade.get("grade")),
                                "grade_is_null": grade.get("grade") in (None, ""),
                                "grade_max": None,
                                "grade_percent": None,
                                "weighted_grade": None,
                                "hidden": False,
                                "source_function": source_function,
                                "raw": grade,
                            },
                        )
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                warnings.append(f"mod_assign_get_grades indisponivel curso={course_id}: {exc}")

        for quiz_id, quiz_name in quizzes:
            for user_id in user_ids:
                try:
                    source_function, payload = await self._try_first_success(
                        [
                            (
                                "mod_quiz_get_user_attempts",
                                {"quizid": quiz_id, "userid": user_id, "status": "all"},
                            ),
                        ],
                    )
                    attempts = self._find_payload_rows(payload, ["attempts", "data"])
                    for attempt in attempts:
                        attempt_id = self._as_int(attempt.get("id"))
                        grade_value = self._as_float(attempt.get("sumgrades"))
                        rows.append(
                            {
                                "course_id": course_id,
                                "user_id": user_id,
                                "item_name": f"{quiz_name} (tentativa {attempt.get('attempt')})",
                                "item_module": "quiz",
                                "item_type": "attempt",
                                "gradetype": 1,
                                "grade_type_name": "numeric",
                                "grade_value": grade_value,
                                "grade_is_null": grade_value is None,
                                "grade_max": self._as_float(attempt.get("maxmark")),
                                "grade_percent": None,
                                "weighted_grade": grade_value,
                                "hidden": False,
                                "attempt_id": attempt_id,
                                "source_function": source_function,
                                "raw": attempt,
                            },
                        )
                        if attempt_id:
                            try:
                                review_fn, review_payload = await self._try_first_success(
                                    [("mod_quiz_get_attempt_review", {"attemptid": attempt_id})],
                                )
                                rows.append(
                                    {
                                        "course_id": course_id,
                                        "user_id": user_id,
                                        "item_name": f"{quiz_name} (review tentativa {attempt.get('attempt')})",
                                        "item_module": "quiz",
                                        "item_type": "review",
                                        "gradetype": 3,
                                        "grade_type_name": "text",
                                        "grade_value": None,
                                        "grade_is_null": True,
                                        "grade_max": None,
                                        "grade_percent": None,
                                        "weighted_grade": None,
                                        "hidden": False,
                                        "attempt_id": attempt_id,
                                        "source_function": review_fn,
                                        "raw": review_payload,
                                    },
                                )
                            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                                warnings.append(
                                    f"mod_quiz_get_attempt_review indisponivel attempt={attempt_id}: {exc}",
                                )
                except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                    warnings.append(
                        f"mod_quiz_get_user_attempts indisponivel quiz={quiz_id} user={user_id}: {exc}",
                    )

        return rows, warnings

    async def _collect_completion_rows(
        self,
        course_id: int,
        user_id: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        completion_rows: list[dict[str, Any]] = []
        progress_rows: list[dict[str, Any]] = []

        activity_calls = [
            (
                get_wsfunction("completion", "activities"),
                {"courseid": course_id, "userid": user_id},
            ),
        ]
        course_calls = [
            (
                get_wsfunction("completion", "course"),
                {"courseid": course_id, "userid": user_id},
            ),
        ]
        navigation_calls = [
            (
                get_wsfunction("course", "user_navigation_options"),
                {"courseid": course_id, "userid": user_id},
            ),
            (
                get_wsfunction("course", "user_navigation_options"),
                {"userid": user_id, "courseid": course_id},
            ),
            (
                get_wsfunction("course", "user_navigation_options"),
                {"courseids": [course_id], "userid": user_id},
            ),
            (
                get_wsfunction("course", "user_navigation_options"),
                {"courseids": [course_id]},
            ),
        ]

        try:
            source_function, payload = await self._try_first_success(activity_calls)
            statuses = self._find_payload_rows(payload, ["statuses", "completionstatus", "activities", "data"])
            if not statuses:
                statuses = self._find_payload_rows(payload, ["cmcompletion"])

            completed_count = 0
            tracked_total = 0
            for status in statuses:
                state = int(status.get("state", 0) or 0)
                tracking = int(status.get("tracking", 0) or 0)
                if tracking > 0:
                    tracked_total += 1
                if tracking > 0 and state > 0:
                    completed_count += 1
                completion_rows.append(
                    {
                        "course_id": course_id,
                        "user_id": user_id,
                        "cmid": status.get("cmid"),
                        "state": state,
                        "timecompleted": status.get("timecompleted"),
                        "tracking": tracking,
                        "source_function": source_function,
                        "raw": status,
                    },
                )
            total = tracked_total
            progress = round((completed_count / total) * 100, 2) if total else 0.0
            progress_rows.append(
                {
                    "course_id": course_id,
                    "user_id": user_id,
                    "progress_percent": progress,
                    "completed_activities": completed_count,
                    "total_activities": total,
                    "source_function": source_function,
                },
            )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Conclusao de atividades indisponivel curso={course_id} user={user_id}: {exc}")

        try:
            source_function, payload = await self._try_first_success(course_calls)
            status_rows = self._find_payload_rows(payload, ["completionstatus", "completions", "data"])
            for status in status_rows:
                percent = status.get("progress") or status.get("progresspercentage")
                progress_rows.append(
                    {
                        "course_id": course_id,
                        "user_id": user_id,
                        "progress_percent": percent,
                        "is_complete": status.get("completed"),
                        "timecompleted": status.get("timecompleted"),
                        "source_function": source_function,
                        "raw": status,
                    },
                )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Progresso do curso indisponivel curso={course_id} user={user_id}: {exc}")

        try:
            source_function, payload = await self._try_first_success(navigation_calls)
            progress_rows.append(
                {
                    "course_id": course_id,
                    "user_id": user_id,
                    "source_function": source_function,
                    "navigation_options": payload,
                    "raw": payload,
                },
            )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(
                f"Navegacao do curso indisponivel curso={course_id} user={user_id}: {exc}",
            )

        return completion_rows, progress_rows, warnings

    async def _collect_logs_rows(
        self,
        course_id: int,
        user_ids: list[int],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []

        calls = [
            (
                "core_log_get_logs",
                {"courseids": [course_id], "limitfrom": 0, "limitnum": 5000},
            ),
        ]

        try:
            source_function, payload = await self._try_first_success(calls)
            logs = self._find_payload_rows(payload, ["logs", "entries", "events", "data"])
            for log in logs:
                rows.append(
                    {
                        "course_id": course_id,
                        "user_id": log.get("userid"),
                        "eventname": log.get("eventname") or log.get("action"),
                        "timecreated": log.get("timecreated"),
                        "source_function": source_function,
                        "raw": log,
                    },
                )
            return rows, warnings
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Logs agregados indisponiveis para curso={course_id}: {exc}")

        for user_id in user_ids:
            try:
                source_function, payload = await self._try_first_success(
                    [
                        (
                            "core_log_get_course_user_report",
                            {"courseid": course_id, "userid": user_id},
                        ),
                    ],
                )
                logs = self._find_payload_rows(payload, ["logs", "entries", "events", "data"])
                for log in logs:
                    rows.append(
                        {
                            "course_id": course_id,
                            "user_id": user_id,
                            "eventname": log.get("eventname") or log.get("action"),
                            "timecreated": log.get("timecreated"),
                            "source_function": source_function,
                            "raw": log,
                        },
                    )
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                warnings.append(f"Logs por usuario indisponiveis curso={course_id} user={user_id}: {exc}")

        return rows, warnings

    async def _collect_badges_rows(
        self,
        course_id: int,
        user_id: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            source_function, payload = await self._try_first_success(
                [(get_wsfunction("participation", "badges"), {"userid": user_id})],
            )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            return [], [f"Badges indisponiveis curso={course_id} user={user_id}: {exc}"]

        badges = self._find_payload_rows(payload, ["badges", "items", "data"])
        rows = []
        for badge in badges:
            rows.append(
                {
                    "course_id": course_id,
                    "user_id": user_id,
                    "badge_id": badge.get("id"),
                    "badge_name": badge.get("name"),
                    "dateissued": badge.get("dateissued"),
                    "source_function": source_function,
                    "raw": badge,
                },
            )
        return rows, []

    async def _collect_competencies_rows(
        self,
        course_id: int,
        user_id: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        calls = [
            (
                "core_competency_data_for_user_competency_summary_in_course",
                {"courseid": course_id, "userid": user_id},
            ),
            ("core_competency_data_for_user_competency_summary", {"userid": user_id}),
            (
                get_wsfunction("participation", "competency_report"),
                {"courseid": course_id, "userid": user_id},
            ),
        ]
        try:
            source_function, payload = await self._try_first_success(calls)
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            return [], [f"Competencias indisponiveis curso={course_id} user={user_id}: {exc}"]

        competencies = self._find_payload_rows(
            payload,
            ["competencies", "usercompetency", "items", "data"],
        )
        rows = []
        for competency in competencies or [{}]:
            rows.append(
                {
                    "course_id": course_id,
                    "user_id": user_id,
                    "competency_id": competency.get("id") or competency.get("competencyid"),
                    "shortname": competency.get("shortname"),
                    "grade": competency.get("grade"),
                    "proficiency": competency.get("proficiency"),
                    "source_function": source_function,
                    "raw": competency,
                },
            )
        return rows, []

    async def _collect_groups(self, course_id: int) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        try:
            source_function, payload = await self._try_first_success(
                [(get_wsfunction("participation", "groups"), {"courseid": course_id})],
            )
            groups = self._find_payload_rows(payload, ["groups", "data"])
            for group in groups:
                rows.append(
                    {
                        "course_id": course_id,
                        "group_id": group.get("id"),
                        "group_name": group.get("name"),
                        "description": group.get("description"),
                        "source_function": source_function,
                        "raw": group,
                    },
                )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Grupos indisponiveis curso={course_id}: {exc}")
        return rows, warnings

    async def _collect_group_members(
        self,
        course_id: int,
        groups: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        group_ids = [self._as_int(group.get("group_id")) for group in groups]
        group_ids = [group_id for group_id in group_ids if group_id]
        if not group_ids:
            return rows, warnings
        try:
            source_function, payload = await self._try_first_success(
                [(get_wsfunction("participation", "group_members"), {"groupids": group_ids})],
            )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            return [], [f"Membros de grupo indisponiveis curso={course_id}: {exc}"]

        members_rows = self._find_payload_rows(payload, ["groups", "groupmembers", "data", "items"])
        for entry in members_rows:
            group_id = entry.get("groupid") or entry.get("id")
            users = entry.get("userids") or entry.get("users") or []
            if isinstance(users, list) and users and not isinstance(users[0], dict):
                for user_id in users:
                    rows.append(
                        {
                            "course_id": course_id,
                            "group_id": group_id,
                            "user_id": user_id,
                            "source_function": source_function,
                            "raw": entry,
                        },
                    )
            elif isinstance(users, list):
                for user in users:
                    rows.append(
                        {
                            "course_id": course_id,
                            "group_id": group_id,
                            "user_id": user.get("id"),
                            "username": user.get("username"),
                            "fullname": user.get("fullname"),
                            "source_function": source_function,
                            "raw": user,
                        },
                    )
            else:
                rows.append(
                    {
                        "course_id": course_id,
                        "group_id": group_id,
                        "user_id": None,
                        "source_function": source_function,
                        "raw": entry,
                    },
                )

        return rows, warnings

    async def _collect_groupings(self, course_id: int) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        calls = [
            ("core_group_get_course_groupings", {"courseid": course_id}),
            ("core_group_get_groupings", {"courseid": course_id}),
        ]
        try:
            source_function, payload = await self._try_first_success(calls)
            groupings = self._find_payload_rows(payload, ["groupings", "data", "items"])
            for grouping in groupings:
                rows.append(
                    {
                        "course_id": course_id,
                        "grouping_id": grouping.get("id"),
                        "grouping_name": grouping.get("name"),
                        "description": grouping.get("description"),
                        "source_function": source_function,
                        "raw": grouping,
                    },
                )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Agrupamentos indisponiveis curso={course_id}: {exc}")
        return rows, warnings

    async def _collect_custom_metrics(self, course_id: int) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for wsfunction in self.settings.moodle_custom_metrics_functions:
            try:
                payload = await self.client.call(wsfunction, courseid=course_id)
                entries = self._find_payload_rows(payload, ["data", "items", "rows", "records"])
                if not entries:
                    entries = [{}]
                for entry in entries:
                    rows.append(
                        {
                            "course_id": course_id,
                            "metric_function": wsfunction,
                            "raw": entry,
                        },
                    )
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                warnings.append(
                    f"Metrica personalizada indisponivel wsfunction={wsfunction} curso={course_id}: {exc}",
                )
        return rows, warnings

    async def collect_course_metrics(
        self,
        course_id: int,
        scope: SyncScope,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        warnings: list[str] = []
        users = await self.get_enrolled_users(course_id)

        students: list[dict[str, Any]] = []
        enrollments: list[dict[str, Any]] = []
        grades: list[dict[str, Any]] = []
        completion: list[dict[str, Any]] = []
        progress: list[dict[str, Any]] = []
        badges: list[dict[str, Any]] = []
        competencies: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        group_members: list[dict[str, Any]] = []
        groupings: list[dict[str, Any]] = []
        custom_metrics: list[dict[str, Any]] = []

        user_ids: list[int] = []
        for user in users:
            user_id = int(user.get("id", 0))
            if not user_id:
                continue
            user_ids.append(user_id)
            students.append(
                {
                    "user_id": user_id,
                    "username": user.get("username"),
                    "email": user.get("email"),
                    "firstname": user.get("firstname"),
                    "lastname": user.get("lastname"),
                    "fullname": user.get("fullname"),
                    "suspended": user.get("suspended"),
                    "confirmed": user.get("confirmed"),
                    "lastaccess": user.get("lastaccess"),
                    **self._extract_custom_fields(user),
                },
            )
            enrollments.append(
                {
                    "course_id": course_id,
                    "user_id": user_id,
                    "status": self._extract_enrollment_status(user),
                    "roles": user.get("roles"),
                    "groups": user.get("groups"),
                    "timeenrolled": user.get("timeenrolled"),
                    "lastcourseaccess": user.get("lastcourseaccess"),
                    "raw": user.get("enrolments") or user.get("enrolledcourses"),
                },
            )

        for user_id in user_ids:
            if scope.include_grades:
                rows, row_warnings = await self._collect_grade_rows(course_id, user_id)
                grades.extend(rows)
                warnings.extend(row_warnings)

            if scope.include_completion or scope.include_progress:
                c_rows, p_rows, row_warnings = await self._collect_completion_rows(course_id, user_id)
                if scope.include_completion:
                    completion.extend(c_rows)
                if scope.include_progress:
                    progress.extend(p_rows)
                warnings.extend(row_warnings)

            if scope.include_badges:
                rows, row_warnings = await self._collect_badges_rows(course_id, user_id)
                badges.extend(rows)
                warnings.extend(row_warnings)

            if scope.include_competencies:
                rows, row_warnings = await self._collect_competencies_rows(course_id, user_id)
                competencies.extend(rows)
                warnings.extend(row_warnings)

        if scope.include_grades:
            rows, row_warnings = await self._collect_assignment_quiz_grade_rows(course_id, user_ids)
            grades.extend(rows)
            warnings.extend(row_warnings)

        if scope.include_logs:
            rows, row_warnings = await self._collect_logs_rows(course_id, user_ids)
            logs.extend(rows)
            warnings.extend(row_warnings)

        if scope.include_groups:
            rows, row_warnings = await self._collect_groups(course_id)
            groups.extend(rows)
            warnings.extend(row_warnings)
            member_rows, member_warnings = await self._collect_group_members(course_id, rows)
            group_members.extend(member_rows)
            warnings.extend(member_warnings)

        if scope.include_groupings:
            rows, row_warnings = await self._collect_groupings(course_id)
            groupings.extend(rows)
            warnings.extend(row_warnings)

        if scope.include_custom_metrics:
            rows, row_warnings = await self._collect_custom_metrics(course_id)
            custom_metrics.extend(rows)
            warnings.extend(row_warnings)

        datasets = {
            "students": students,
            "enrollments": enrollments,
            "grades": grades,
            "completion": completion,
            "progress": progress,
            "logs": logs,
            "badges": badges,
            "competencies": competencies,
            "groups": groups,
            "group_members": group_members,
            "groupings": groupings,
            "custom_metrics": custom_metrics,
        }
        return datasets, warnings

    async def collect_catalog(
        self,
        course_ids: list[int],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        warnings: list[str] = []
        courses_rows: list[dict[str, Any]] = []
        categories_rows: list[dict[str, Any]] = []
        contents_rows: list[dict[str, Any]] = []

        try:
            courses = await self.get_courses()
            for course in courses:
                courses_rows.append(
                    {
                        "course_id": course.get("id"),
                        "shortname": course.get("shortname"),
                        "fullname": course.get("fullname"),
                        "categoryid": course.get("categoryid"),
                        "visible": course.get("visible"),
                        "startdate": course.get("startdate"),
                        "enddate": course.get("enddate"),
                        "raw": course,
                    },
                )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Cursos indisponiveis: {exc}")

        try:
            categories = await self.get_categories()
            for category in categories:
                categories_rows.append(
                    {
                        "category_id": category.get("id"),
                        "name": category.get("name"),
                        "idnumber": category.get("idnumber"),
                        "description": category.get("description"),
                        "parent": category.get("parent"),
                        "depth": category.get("depth"),
                        "raw": category,
                    },
                )
        except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
            warnings.append(f"Categorias indisponiveis: {exc}")

        for course_id in course_ids:
            try:
                contents = await self.get_course_contents(course_id)
                for section in contents:
                    modules = section.get("modules", []) or []
                    if not modules:
                        contents_rows.append(
                            {
                                "course_id": course_id,
                                "section_id": section.get("id"),
                                "section_name": section.get("name"),
                                "module_id": None,
                                "module_name": None,
                                "module_type": None,
                                "raw": section,
                            },
                        )
                        continue
                    for module in modules:
                        contents_rows.append(
                            {
                                "course_id": course_id,
                                "section_id": section.get("id"),
                                "section_name": section.get("name"),
                                "module_id": module.get("id"),
                                "module_name": module.get("name"),
                                "module_type": module.get("modname"),
                                "visible": module.get("visible"),
                                "completion": module.get("completion"),
                                "raw": module,
                            },
                        )
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError) as exc:
                warnings.append(f"Conteudo indisponivel para curso={course_id}: {exc}")

        return {
            "courses": courses_rows,
            "categories": categories_rows,
            "course_contents": contents_rows,
        }, warnings

    async def get_course_students_with_metrics(self, course_id: int) -> dict[str, Any]:
        scope = SyncScope()
        scope.course_ids = [course_id]
        rows, warnings = await self.collect_course_metrics(course_id, scope)
        return {
            "course_id": course_id,
            "students": rows.get("students", []),
            "enrollments": rows.get("enrollments", []),
            "progress": rows.get("progress", []),
            "badges": rows.get("badges", []),
            "groups": rows.get("groups", []),
            "group_members": rows.get("group_members", []),
            "warnings": warnings,
        }

    async def get_course_grades_report(self, course_id: int) -> dict[str, Any]:
        scope = SyncScope(
            course_ids=[course_id],
            include_course_catalog=False,
            include_grades=True,
            include_completion=True,
            include_progress=True,
            include_logs=False,
            include_badges=False,
            include_competencies=False,
            include_groups=False,
            include_groupings=False,
            include_custom_metrics=False,
        )
        rows, warnings = await self.collect_course_metrics(course_id, scope)
        return {
            "course_id": course_id,
            "grades": rows.get("grades", []),
            "progress": rows.get("progress", []),
            "completion": rows.get("completion", []),
            "warnings": warnings,
        }

    async def get_user_progress(self, user_id: int, course_id: int | None = None) -> dict[str, Any]:
        course_ids = [course_id] if course_id else await self.list_course_ids()
        details: list[dict[str, Any]] = []
        warnings: list[str] = []
        for current_course_id in course_ids:
            completion_rows, progress_rows, row_warnings = await self._collect_completion_rows(
                current_course_id,
                user_id,
            )
            warnings.extend(row_warnings)
            details.append(
                {
                    "course_id": current_course_id,
                    "completion": completion_rows,
                    "progress": progress_rows,
                },
            )
        return {
            "user_id": user_id,
            "courses": details,
            "warnings": warnings,
        }

    async def _search_users_by_field(self, field: str, value: str) -> list[dict[str, Any]]:
        if not value:
            return []
        users = await self.client.call(
            get_wsfunction("user", "get_users_by_field"),
            field=field,
            values=[value],
        )
        if isinstance(users, list):
            return [item for item in users if isinstance(item, dict)]
        return []

    async def _search_users(self, field: str, value: str) -> list[dict[str, Any]]:
        if not value:
            return []
        payload = await self.client.call(
            get_wsfunction("user", "get_users"),
            criteria=[{"key": field, "value": value}],
        )
        if isinstance(payload, dict):
            users = payload.get("users")
            if isinstance(users, list):
                return [item for item in users if isinstance(item, dict)]
        return []

    async def _resolve_user_id(self, payload: dict[str, Any]) -> int:
        for key in ("user_id", "userid", "id"):
            if payload.get(key):
                return int(payload[key])

        username = str(payload.get("username") or "").strip()
        if username:
            users = await self._search_users_by_field("username", username)
            if not users:
                users = await self._search_users("username", username)
            if users:
                return int(users[0]["id"])

        email = str(payload.get("email") or "").strip()
        if email:
            users = await self._search_users_by_field("email", email)
            if not users:
                users = await self._search_users("email", email)
            if users:
                return int(users[0]["id"])

        raise MoodleAPIError(
            errorcode="user_not_found",
            message=f"Usuario nao encontrado para payload={payload}",
        )

    async def apply_students_rows(
        self,
        rows: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> tuple[dict[str, int], list[str], list[int]]:
        processed_rows: list[int] = []
        warnings: list[str] = []
        created = 0
        updated = 0

        for row in rows:
            row_number = int(row.get("_row_number", 0) or 0)
            payload = {key: value for key, value in row.items() if not str(key).startswith("_")}
            action = (str(payload.get("action", "upsert")) or "upsert").strip().lower()
            if action not in {"create", "update", "upsert"}:
                warnings.append(f"Linha {row_number}: acao invalida para aluno '{action}'")
                continue

            username = self._normalize_cpf(str(payload.get("username") or ""))
            email = str(payload.get("email") or "").strip().lower()
            try:
                if username:
                    assert_valid_cpf(username)
                if email:
                    assert_valid_email(email)
            except ValidationError as exc:
                message = f"Linha {row_number}: {exc}"
                logger.warning(message)
                warnings.append(message)
                continue
            if username:
                payload["username"] = username
            if email:
                payload["email"] = email

            try:
                user_id = await self._resolve_user_id(payload) if action in {"update", "upsert"} else None
            except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError):
                user_id = None

            if user_id is None and email:
                try:
                    users = await self._search_users_by_field("email", email)
                    if not users:
                        users = await self._search_users("email", email)
                    if users:
                        user_id = int(users[0]["id"])
                except (MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError):
                    user_id = None

            user_data = {
                "username": payload.get("username"),
                "firstname": payload.get("firstname"),
                "lastname": payload.get("lastname"),
                "email": payload.get("email"),
            }

            if user_id:
                user_data["id"] = user_id
                if dry_run:
                    updated += 1
                    processed_rows.append(row_number)
                    continue
                await self.client.call(get_wsfunction("user", "update_users"), users=[user_data])
                updated += 1
                processed_rows.append(row_number)
                continue

            if action == "update":
                warnings.append(f"Linha {row_number}: usuario nao encontrado para update.")
                continue

            password = payload.get("password") or self.settings.moodle_default_new_user_password
            if not password:
                warnings.append(f"Linha {row_number}: create/upsert requer coluna password.")
                continue

            user_data["password"] = password
            if dry_run:
                created += 1
                processed_rows.append(row_number)
                continue
            await self.client.call(get_wsfunction("user", "create_users"), users=[user_data])
            created += 1
            processed_rows.append(row_number)

        return {"created": created, "updated": updated}, warnings, processed_rows

    async def apply_enrollment_rows(
        self,
        rows: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> tuple[dict[str, int], list[str], list[int]]:
        warnings: list[str] = []
        processed_rows: list[int] = []
        enroll_payloads = []
        unenroll_payloads = []
        counts = {"enrolled": 0, "suspended": 0, "unenrolled": 0}

        for row in rows:
            row_number = int(row.get("_row_number", 0) or 0)
            payload = {key: value for key, value in row.items() if not str(key).startswith("_")}
            action = (str(payload.get("action", "enroll")) or "enroll").strip().lower()

            if not payload.get("course_id"):
                warnings.append(f"Linha {row_number}: coluna course_id e obrigatoria.")
                continue

            try:
                user_id = await self._resolve_user_id(payload)
                course_id = int(payload["course_id"])
                role_id = int(payload.get("role_id") or self.settings.moodle_default_role_id)
            except Exception as exc:
                warnings.append(f"Linha {row_number}: falha ao resolver usuario/curso ({exc}).")
                continue

            if action in {"enroll", "activate"}:
                enroll_payloads.append(
                    {
                        "roleid": role_id,
                        "userid": user_id,
                        "courseid": course_id,
                        "suspend": 0,
                    },
                )
                counts["enrolled"] += 1
                processed_rows.append(row_number)
                continue

            if action in {"suspend"}:
                enroll_payloads.append(
                    {
                        "roleid": role_id,
                        "userid": user_id,
                        "courseid": course_id,
                        "suspend": 1,
                    },
                )
                counts["suspended"] += 1
                processed_rows.append(row_number)
                continue

            if action in {"unenroll", "remove"}:
                unenroll_payloads.append(
                    {
                        "userid": user_id,
                        "courseid": course_id,
                        "roleid": role_id,
                    },
                )
                counts["unenrolled"] += 1
                processed_rows.append(row_number)
                continue

            warnings.append(f"Linha {row_number}: acao de matricula nao suportada '{action}'.")

        if not dry_run:
            batch_size = max(1, min(int(getattr(self.settings, "sync_batch_size", 50) or 50), 50))
            if enroll_payloads:
                for batch in self._chunk_list(enroll_payloads, batch_size):
                    await self.client.call(get_wsfunction("enrollment", "enroll"), enrolments=batch)
            if unenroll_payloads:
                for batch in self._chunk_list(unenroll_payloads, batch_size):
                    await self.client.call(
                        get_wsfunction("enrollment", "unenroll"),
                        enrolments=batch,
                    )

        return counts, warnings, processed_rows





