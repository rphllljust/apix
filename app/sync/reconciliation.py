"""Responsabilidade: implementa o modulo app/sync/reconciliation.py."""

from __future__ import annotations

from typing import Any

from app.exceptions import SyncConflictError


def reconcile_moodle_truth(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    strict: bool = False,
) -> dict[str, Any]:
    """Moodle e fonte da verdade para notas/progresso."""
    if strict:
        for key, old_value in existing.items():
            if key not in incoming:
                continue
            new_value = incoming[key]
            if old_value not in (None, "") and new_value not in (None, "") and old_value != new_value:
                raise SyncConflictError(f"Conflito no campo '{key}' entre Moodle e Sheets.")
    result = dict(existing)
    result.update(incoming)
    return result


def reconcile_sheets_enrollment(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Sheets e fonte da verdade para novos pedidos de inscricao."""
    result = dict(existing)
    for key, value in incoming.items():
        if value not in (None, ""):
            result[key] = value
    return result

