"""Responsabilidade: implementa o modulo app/moodle/endpoints.py."""

from __future__ import annotations

from typing import Final


MOODLE_ENDPOINTS: Final[dict[str, dict[str, str]]] = {
    "user": {
        "get_users": "core_user_get_users",
        "get_users_by_field": "core_user_get_users_by_field",
        "create_users": "core_user_create_users",
        "update_users": "core_user_update_users",
    },
    "course": {
        "list": "core_course_get_courses",
        "by_field": "core_course_get_courses_by_field",
        "categories": "core_course_get_categories",
        "contents": "core_course_get_contents",
        "user_navigation_options": "core_course_get_user_navigation_options",
    },
    "enrollment": {
        "list_users": "core_enrol_get_enrolled_users",
        "enroll": "enrol_manual_enrol_users",
        "unenroll": "enrol_manual_unenrol_users",
    },
    "gradebook": {
        "user_items": "gradereport_user_get_grade_items",
        "user_table": "gradereport_user_get_grades_table",
        "core_grades": "core_grades_get_grades",
        "assign_grades": "mod_assign_get_grades",
        "quiz_attempts": "mod_quiz_get_user_attempts",
        "quiz_review": "mod_quiz_get_attempt_review",
    },
    "completion": {
        "activities": "core_completion_get_activities_completion_status",
        "course": "core_completion_get_course_completion_status",
    },
    "participation": {
        "logs": "core_log_get_logs",
        "user_report": "core_log_get_course_user_report",
        "competency_report": "report_competency_data_for_report",
        "badges": "core_badges_get_user_badges",
        "groups": "core_group_get_course_groups",
        "group_members": "core_group_get_group_members",
        "groupings": "core_group_get_groupings",
        "course_groupings": "core_group_get_course_groupings",
    },
}


def get_wsfunction(domain: str, action: str) -> str:
    try:
        return MOODLE_ENDPOINTS[domain][action]
    except KeyError as exc:
        raise KeyError(f"Wsfunction nao mapeada para {domain}.{action}") from exc

