"""Responsabilidade: implementa o modulo app/moodle/models.py."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MoodleCourse(BaseModel):
    id: int
    shortname: str | None = None
    fullname: str | None = None
    categoryid: int | None = None
    visible: int | None = None


class MoodleCategory(BaseModel):
    id: int
    name: str
    parent: int | None = None
    depth: int | None = None


class MoodleGradeItem(BaseModel):
    course_id: int
    user_id: int
    item_name: str | None = None
    gradetype: int | None = None
    grade_value: float | None = None
    grade_max: float | None = None
    hidden: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


