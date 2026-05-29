"""Tiny retry-with-backoff for transient network failures.

Shared by `_github` (release resolution) and `_engine` (asset download). Both
classify failures into *permanent* (404, bad checksum — surfaced immediately)
and *transient* (network blip, timeout, rate-limit, 5xx — retried here).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

ATTEMPTS = 4
BASE_DELAY = 0.5  # exponential backoff base → sleeps of 0.5s, 1s, 2s between tries


def retryable_http_status(code: int) -> bool:
    """True for HTTP statuses worth retrying (rate-limit / request-timeout / 5xx)."""
    return code in (403, 408, 425, 429) or code >= 500


def _warn_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def retry(
    fn: Callable[[], T],
    *,
    op: str,
    retry_on: tuple[type[BaseException], ...],
    attempts: int = ATTEMPTS,
    base_delay: float = BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    warn: Callable[[str], None] | None = _warn_stderr,
) -> T:
    """Call `fn`, retrying with exponential backoff on `retry_on` exceptions.

    Re-raises the last exception after `attempts` tries. `op` labels the action
    in the retry notice. `sleep`/`warn` are injectable for tests (pass
    `warn=None` to silence).
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            if warn is not None:
                warn(f"ohbin: {op} failed (attempt {attempt}/{attempts}): {exc}; retrying in {delay:.1f}s")
            sleep(delay)
    raise RuntimeError(f"retry({op}): exhausted without result")  # pragma: no cover
