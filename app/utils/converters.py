"""Responsabilidade: implementa o modulo app/utils/converters.py."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def epoch_to_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def epoch_to_date(value: Any) -> date | None:
    dt = epoch_to_datetime(value)
    return dt.date() if dt else None


