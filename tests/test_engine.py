"""Pure helpers in the download/cache engine (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohbin._engine import _url_filename, cache_root


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r/releases/download/v1/tool_1_linux.tar.gz", "tool_1_linux.tar.gz"),
        ("https://example/path/rg-aarch64-apple-darwin.tar.gz?x=1", "rg-aarch64-apple-darwin.tar.gz"),
        ("https://example/some%20name.zip", "some name.zip"),
    ],
)
def test_url_filename(url: str, expected: str) -> None:
    assert _url_filename(url) == expected


def test_cache_root_respects_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg")
    assert cache_root("rg", "14.1.1") == Path("/tmp/xdg/ohbin/rg/14.1.1")


def test_cache_root_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    root = cache_root("fd", "10.2.0")
    assert root == Path.home() / ".cache" / "ohbin" / "fd" / "10.2.0"
