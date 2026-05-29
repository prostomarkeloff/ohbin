"""Manifest discovery + parsing of `[tool.ohbin.tools.*]`."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohbin._manifest import ManifestError, find_pyproject, load_tool, load_tools

_PYPROJECT = """\
[project]
name = "demo"
version = "0.0.0"

[tool.ohbin.tools.rg]
repo = "BurntSushi/ripgrep"
version = "14.1.1"
binary = "rg"

[tool.ohbin.tools.rg.assets.darwin-arm64]
url = "https://example/ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
sha256 = "deadbeef"

[tool.ohbin.tools.fd]
repo = "sharkdp/fd"
version = "10.2.0"

[tool.ohbin.tools.fd.assets.linux-x86_64]
url = "https://example/fd-v10.2.0-x86_64-unknown-linux-gnu.tar.gz"
sha256 = "cafef00d"
"""


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    pp = tmp_path / "pyproject.toml"
    pp.write_text(_PYPROJECT)
    return pp


def test_load_tool_parses_assets(manifest: Path) -> None:
    rg = load_tool("rg", pyproject=manifest)
    assert rg["repo"] == "BurntSushi/ripgrep"
    assert rg["version"] == "14.1.1"
    assert rg["binary"] == "rg"
    assert rg["assets"]["darwin-arm64"]["sha256"] == "deadbeef"


def test_binary_defaults_to_tool_name(manifest: Path) -> None:
    # `fd` declares no explicit `binary` → it defaults to the tool's key.
    assert load_tool("fd", pyproject=manifest)["binary"] == "fd"


def test_load_tools_returns_all(manifest: Path) -> None:
    assert set(load_tools(manifest)) == {"rg", "fd"}


def test_unknown_tool_raises(manifest: Path) -> None:
    with pytest.raises(ManifestError, match="not declared"):
        load_tool("nope", pyproject=manifest)


def test_find_pyproject_via_env(manifest: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHBIN_PYPROJECT", str(manifest))
    assert find_pyproject() == manifest


def test_find_pyproject_missing_env_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OHBIN_PYPROJECT", str(tmp_path / "nope.toml"))
    with pytest.raises(ManifestError, match="missing file"):
        find_pyproject()
