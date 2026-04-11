"""Responsabilidade: implementa o modulo app/sheets/templates.py."""

from __future__ import annotations


ALUNOS_BASE_HEADERS: list[str] = [
    "moodle_user_id",
    "username",
    "nome_completo",
    "email",
    "status_matricula",
    "data_matricula",
    "progresso_curso_percent",
    "nota_final",
    "nota_maxima",
    "nota_percentual",
    "atividades_concluidas",
    "ultimo_acesso_curso",
    "badges_lista",
    "grupo",
]

DEFAULT_SHEETS: list[str] = [
    "courses",
    "categories",
    "course_contents",
    "students",
    "enrollments",
    "grades",
    "completion",
    "progress",
    "logs",
    "badges",
    "competencies",
    "groups",
    "group_members",
    "groupings",
    "custom_metrics",
    "students_input",
    "Inscrever Novos Alunos",
    "Log de Sincronização",
]

