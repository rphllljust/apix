"""Responsabilidade: implementa o modulo app/utils/retry.py."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def retry_moodle_request(fn: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.TransportError,
                httpx.HTTPStatusError,
            ),
        ),
        reraise=True,
    )(fn)


