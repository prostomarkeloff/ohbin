"""GitHub fetch failure classification — the 404-vs-transient distinction.

This is the regression guard for the bug where a transient `gh` failure was
treated as "release not found".
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from ohbin import _github


def _fake_gh(returncode: int, stdout: str = "", stderr: str = ""):
    def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_clean_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_github.subprocess, "run", _fake_gh(1, stderr="gh: Not Found (HTTP 404)"))
    assert _github._fetch_gh_one("repos/x/y/releases/tags/v1") is None


def test_success_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_github.subprocess, "run", _fake_gh(0, stdout='{"tag_name": "v1"}'))
    assert _github._fetch_gh_one("repos/x/y/releases/tags/v1") == {"tag_name": "v1"}


def test_network_failure_is_transient_not_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # A DNS/network error must raise (→ retried), NOT be mistaken for "not found".
    monkeypatch.setattr(
        _github.subprocess,
        "run",
        _fake_gh(1, stderr="dial tcp: lookup api.github.com: no such host"),
    )
    with pytest.raises(_github._TransientError):
        _github._fetch_gh_one("repos/x/y/releases/tags/v1")


def test_gh_timeout_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(_github.subprocess, "run", run)
    with pytest.raises(_github._TransientError):
        _github._fetch_gh_one("repos/x/y/releases/tags/v1")


def test_fetch_raw_retries_transient_then_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call blows up transiently, second returns the release. _fetch_raw
    # (through retry) must recover rather than report "not found".
    calls = {"n": 0}

    def fake_fetch_one(_path: str) -> dict[str, object] | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _github._TransientError("flaky")
        return {"tag_name": "v1", "assets": []}

    monkeypatch.setattr(_github.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(_github, "_fetch_gh_one", fake_fetch_one)
    monkeypatch.setattr(_github, "retry", _no_sleep_retry)

    raw = _github._fetch_raw("x/y", "1")
    assert raw["tag_name"] == "v1"
    assert calls["n"] == 2


def _no_sleep_retry(fn, **kwargs):
    # Test shim: same call shape as retry(), but never actually sleeps.
    from ohbin._retry import retry as real_retry

    return real_retry(fn, **{**kwargs, "sleep": lambda _d: None, "warn": None})
