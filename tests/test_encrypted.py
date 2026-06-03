"""Encrypted-tool support across the manifest → write → resolve → decrypt path."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from ohbin._add import AddError, local_pyproject, write_tool
from ohbin._crypto import DecryptError, encrypt_binary
from ohbin._engine import MissingPasswordError, ensure_from
from ohbin._manifest import load_tool
from ohbin._types import AssetEntry, ToolConfig

openssl_required = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")


def _encrypted_cfg() -> ToolConfig:
    return ToolConfig(
        repo="gist:abc123",
        version="gist-deadbeef",
        binary="foo",
        assets={
            "darwin-arm64": AssetEntry(url="https://x/foo.enc.b64", sha256="cipher", binary_sha256="plain"),
        },
        encrypted=True,
        password="pw",
        password_committed_ok=True,
    )


def test_manifest_parses_encrypted_fields(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        "[tool.ohbin.tools.foo]\n"
        'repo = "gist:abc"\n'
        'version = "gist-1"\n'
        'binary = "foo"\n'
        "encrypted = true\n"
        'password = "pw"\n'
        "password_committed_ok = true\n"
        "\n"
        "[tool.ohbin.tools.foo.assets.darwin-arm64]\n"
        'url = "https://x/foo.enc.b64"\n'
        'sha256 = "cipher"\n'
        'binary_sha256 = "plain"\n'
    )
    tool = load_tool("foo", pyproject=pp)
    assert tool.get("encrypted") is True
    assert tool.get("password") == "pw"
    assert tool.get("password_committed_ok") is True
    assert tool["assets"]["darwin-arm64"].get("binary_sha256") == "plain"


def test_plain_tool_omits_encrypted_keys(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        "[tool.ohbin.tools.rg]\n"
        'repo = "o/rg"\n'
        'version = "1"\n'
        "\n"
        "[tool.ohbin.tools.rg.assets.darwin-arm64]\n"
        'url = "https://x/rg.tar.gz"\n'
        'sha256 = "aaa"\n'
    )
    tool = load_tool("rg", pyproject=pp)
    assert "encrypted" not in tool
    assert "password" not in tool
    assert "binary_sha256" not in tool["assets"]["darwin-arm64"]


def test_write_tool_round_trips_encrypted(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("")
    write_tool(pp, "foo", _encrypted_cfg())

    tool = load_tool("foo", pyproject=pp)
    assert tool.get("encrypted") is True
    assert tool.get("password") == "pw"
    assert tool.get("password_committed_ok") is True
    assert tool["assets"]["darwin-arm64"].get("binary_sha256") == "plain"


def test_local_pyproject_prefers_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.toml"
    assert local_pyproject(explicit) == explicit


def test_local_pyproject_uses_cwd_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    assert local_pyproject(None) == Path("pyproject.toml")


def test_local_pyproject_never_walks_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A parent pyproject must NOT be picked up — writing stays in the CWD.
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    with pytest.raises(AddError):
        local_pyproject(None)


@openssl_required
def test_ensure_from_decrypts_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    binary = b"\x7fELF not-really but has null \x00 bytes"
    blob_file = tmp_path / "tool.enc.b64"
    blob_file.write_text(encrypt_binary(binary, "pw"))

    path = ensure_from(
        tool="tool",
        version="1",
        binary="tool",
        url=blob_file.as_uri(),
        sha256=hashlib.sha256(blob_file.read_bytes()).hexdigest(),
        encrypted=True,
        password="pw",
        binary_sha256=hashlib.sha256(binary).hexdigest(),
    )
    assert path.read_bytes() == binary
    assert os.access(path, os.X_OK)


@openssl_required
def test_ensure_from_wrong_password_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    blob_file = tmp_path / "tool.enc.b64"
    blob_file.write_text(encrypt_binary(b"secret binary", "right"))

    with pytest.raises(DecryptError):
        ensure_from(
            tool="tool",
            version="1",
            binary="tool",
            url=blob_file.as_uri(),
            sha256=hashlib.sha256(blob_file.read_bytes()).hexdigest(),
            encrypted=True,
            password="wrong",
        )


def test_ensure_from_encrypted_requires_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    blob_file = tmp_path / "tool.enc.b64"
    blob_file.write_text("anything")  # password is checked before any decryption

    with pytest.raises(MissingPasswordError):
        ensure_from(
            tool="tool",
            version="1",
            binary="tool",
            url=blob_file.as_uri(),
            sha256=hashlib.sha256(blob_file.read_bytes()).hexdigest(),
            encrypted=True,
            password=None,
        )
