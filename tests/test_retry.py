"""Retry-with-backoff mechanics."""

from __future__ import annotations

import pytest

from ohbin._retry import retry, retryable_http_status


class BoomError(RuntimeError):
    pass


def test_succeeds_first_try_without_sleeping() -> None:
    slept: list[float] = []
    result = retry(lambda: "ok", op="x", retry_on=(BoomError,), sleep=slept.append, warn=None)
    assert result == "ok"
    assert slept == []


def test_retries_then_succeeds_with_exponential_backoff() -> None:
    state = {"n": 0}

    def fn() -> str:
        state["n"] += 1
        if state["n"] < 3:
            raise BoomError("not yet")
        return "ok"

    slept: list[float] = []
    result = retry(fn, op="x", retry_on=(BoomError,), sleep=slept.append, warn=None)
    assert result == "ok"
    assert state["n"] == 3
    assert slept == [0.5, 1.0]  # base 0.5 → 0.5, then 1.0


def test_exhausts_then_reraises_last() -> None:
    def fn() -> str:
        raise BoomError("always")

    with pytest.raises(BoomError, match="always"):
        retry(fn, op="x", retry_on=(BoomError,), attempts=2, sleep=lambda _d: None, warn=None)


def test_does_not_catch_unlisted_exceptions() -> None:
    def fn() -> str:
        raise ValueError("different")

    with pytest.raises(ValueError, match="different"):
        retry(fn, op="x", retry_on=(BoomError,), sleep=lambda _d: None, warn=None)


@pytest.mark.parametrize(
    ("code", "expected"),
    [(403, True), (408, True), (429, True), (500, True), (503, True), (404, False), (400, False), (200, False)],
)
def test_retryable_http_status(code: int, expected: bool) -> None:
    assert retryable_http_status(code) is expected
