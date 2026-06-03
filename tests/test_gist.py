"""`_load_index`: read the gist index even when GitHub truncates inline content."""

from __future__ import annotations

import json

import pytest

from ohbin import _gist
from ohbin._gist import GistError, _load_index

_INDEX = {
    "ohbin_gist": 1,
    "name": "dbmap",
    "binary": "dbmap",
    "encrypted": True,
    "assets": {"darwin-arm64": {"file": "dbmap-darwin-arm64.enc.b64", "binary_sha256": "plain"}},
}


def test_load_index_reads_inline_content() -> None:
    files = {"ohbin.json": {"content": json.dumps(_INDEX), "truncated": False}}
    assert _load_index(files)["name"] == "dbmap"


def test_load_index_falls_back_to_raw_url_when_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    # GitHub returns empty `content` + `truncated: true` for a small index when the
    # gist also holds a >1MB blob; the full bytes are only at raw_url.
    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        return json.dumps(_INDEX)

    monkeypatch.setattr(_gist, "text_of_url", fake_fetch)
    files = {"ohbin.json": {"content": "", "truncated": True, "raw_url": "https://gist/raw/ohbin.json"}}
    assert _load_index(files)["name"] == "dbmap"
    assert fetched == ["https://gist/raw/ohbin.json"]


def test_load_index_truncated_without_raw_url_errors() -> None:
    files = {"ohbin.json": {"content": "", "truncated": True}}
    with pytest.raises(GistError, match="raw_url"):
        _load_index(files)
