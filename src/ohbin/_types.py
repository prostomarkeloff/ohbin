"""Typed shapes for the manifest boundary (`[tool.ohbin.tools.*]`)."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class AssetEntry(TypedDict):
    """A single resolved release asset for one platform: where to get it + its hash.

    `sha256` is the hash of the *downloaded* file (verified before any decryption,
    so a tampered gist is caught early). For encrypted tools the downloaded file is
    the ciphertext; `binary_sha256` then pins the *decrypted* executable, which also
    doubles as a wrong-password / corruption check.
    """

    url: str
    sha256: str
    binary_sha256: NotRequired[str]


class ToolConfig(TypedDict):
    """One tool as declared under `[tool.ohbin.tools.<name>]`.

    `binary` is the executable's filename *inside* the archive (defaults to the
    tool's command name). `assets` is keyed by `"<os>-<arch>"` platform keys.

    Encrypted tools (`encrypted = true`) ship a gzip+AES-CBC+base64 blob per
    platform; ohbin decrypts on first use with a password from `--password` or the
    `password` field. `password_committed_ok` silences the warning emitted when the
    password is read from the (typically committed) manifest.
    """

    repo: str
    version: str
    binary: str
    assets: dict[str, AssetEntry]
    encrypted: NotRequired[bool]
    password: NotRequired[str]
    password_committed_ok: NotRequired[bool]
