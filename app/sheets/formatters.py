"""Responsabilidade: implementa o modulo app/sheets/formatters.py."""

from __future__ import annotations

import re


def to_course_students_sheet_name(course_name: str) -> str:
    safe = re.sub(r"[\[\]\*\?/\\]", "-", course_name or "Curso")
    safe = safe.strip() or "Curso"
    return f"Alunos — {safe}"[:100]


def to_course_detailed_grades_sheet_name(course_name: str) -> str:
    safe = re.sub(r"[\[\]\*\?/\\]", "-", course_name or "Curso")
    safe = safe.strip() or "Curso"
    return f"Notas Detalhadas — {safe}"[:100]

