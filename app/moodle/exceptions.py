"""Responsabilidade: implementa o modulo app/moodle/exceptions.py."""

from app.exceptions import (
    MoodleAPIError,
    MoodleAuthError,
    MoodleConnectionError,
    MoodleTokenExpiredError,
)

# Backward compatibility
MoodleApiError = MoodleAPIError

__all__ = [
    "MoodleAPIError",
    "MoodleApiError",
    "MoodleAuthError",
    "MoodleConnectionError",
    "MoodleTokenExpiredError",
]
