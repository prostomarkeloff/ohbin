"""`ohbin publish-gist` / `add-gist`: ship encrypted private binaries through gists.

A gist holds one base64'd `gzip+AES` blob per platform (`<name>-<platform>.enc.b64`)
plus an `ohbin.json` index that maps each platform to its file and the *decrypted*
binary's SHA256. `publish-gist` produces and uploads them; `add-gist` reads the index,
resolves each file's immutable raw URL, pins the ciphertext SHA, and writes the tool
into pyproject. Gists are secret (link-gated), the binary is encrypted, and the
password lives elsewhere — a leaked link alone is useless.

All GitHub access goes through the `gh` CLI (`gh api`), reusing the user's auth.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

from ohbin._add import local_pyproject, write_tool
from ohbin._crypto import encrypt_binary
from ohbin._engine import sha256_of_url, text_of_url
from ohbin._errors import OhbinError
from ohbin._platform import current_platform
from ohbin._types import AssetEntry, ToolConfig

_OHBIN_INDEX = "ohbin.json"
_INDEX_VERSION = 1


class GistAssetInfo(TypedDict):
    """Per-platform entry in a gist's `ohbin.json` index."""

    file: str
    binary_sha256: str


class GistMeta(TypedDict):
    """The `ohbin.json` index stored alongside the encrypted blobs in a gist."""

    ohbin_gist: int
    name: str
    binary: str
    encrypted: bool
    assets: dict[str, GistAssetInfo]


class GistError(OhbinError):
    """Raised when a gist can't be published or resolved (gh failure, malformed index)."""


def _require_gh() -> str:
    path = shutil.which("gh")
    if path is None:
        msg = "gh CLI not found on PATH — required to publish/resolve gists"
        raise GistError(msg)
    return path


def _gh_api(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    cmd = [_require_gh(), "api", "-X", method, path]
    payload: bytes | None = None
    if body is not None:
        cmd += ["--input", "-"]
        payload = json.dumps(body).encode()
    proc = subprocess.run(cmd, input=payload, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        msg = f"gh api {method} {path} failed: {detail or 'unknown error'}"
        raise GistError(msg)
    parsed: dict[str, object] = json.loads(proc.stdout)
    return parsed


def _parse_gist_id(ref: str) -> str:
    ref = ref.strip()
    if "/" not in ref and ":" not in ref:
        return ref  # already a bare id
    parts = [p for p in urlparse(ref).path.split("/") if p]
    if "raw" in parts:  # gist raw URL: .../<user>/<id>/raw/<sha>/<file>
        parts = parts[: parts.index("raw")]
    if not parts:
        msg = f"cannot parse a gist id from {ref!r}"
        raise GistError(msg)
    return parts[-1]


def _file_entry(files: dict[str, object], name: str) -> dict[str, object]:
    entry = files.get(name)
    if not isinstance(entry, dict):
        msg = f"gist is missing file {name!r}"
        raise GistError(msg)
    return entry


def _load_index(files: dict[str, object]) -> GistMeta:
    entry = _file_entry(files, _OHBIN_INDEX)
    raw = entry.get("content")
    # GitHub truncates the inline `content` of *every* file in the gists API once
    # any single file exceeds ~1MB — so a tiny index sitting next to a multi-MB
    # encrypted blob comes back empty (`truncated: true`, `content: ""`). Fall back
    # to the file's raw_url, which always serves the complete bytes.
    if entry.get("truncated") or not isinstance(raw, str) or not raw:
        raw_url = entry.get("raw_url")
        if not isinstance(raw_url, str):
            msg = f"{_OHBIN_INDEX} content is truncated and has no raw_url to fall back to"
            raise GistError(msg)
        raw = text_of_url(raw_url)
    meta: GistMeta = json.loads(raw)
    return meta


def publish_gist(
    *,
    name: str,
    binary: str,
    binary_path: Path,
    password: str,
    platform_key: str | None,
    gist_ref: str | None,
    description: str,
) -> str:
    """Encrypt `binary_path` for one platform and POST/PATCH it into a secret gist.

    With `gist_ref` the blob is added to an existing gist (another platform for the
    same tool); otherwise a fresh secret gist is created. Returns the gist's html_url.
    """
    plat = platform_key or current_platform().key
    data = binary_path.read_bytes()
    blob = encrypt_binary(data, password)
    fname = f"{name}-{plat}.enc.b64"

    if gist_ref is not None:
        gid = _parse_gist_id(gist_ref)
        existing = _gh_api("GET", f"gists/{gid}")
        files = existing.get("files")
        meta = _load_index(files) if isinstance(files, dict) else _new_index(name, binary)
    else:
        meta = _new_index(name, binary)

    meta["assets"][plat] = {"file": fname, "binary_sha256": hashlib.sha256(data).hexdigest()}
    body: dict[str, object] = {
        "public": False,
        "files": {
            fname: {"content": blob},
            _OHBIN_INDEX: {"content": json.dumps(meta, indent=2, sort_keys=True)},
        },
    }
    if gist_ref is not None:
        result = _gh_api("PATCH", f"gists/{_parse_gist_id(gist_ref)}", body)
    else:
        body["description"] = description
        result = _gh_api("POST", "gists", body)

    html_url = result.get("html_url")
    if not isinstance(html_url, str):
        msg = "gist created but GitHub returned no html_url"
        raise GistError(msg)
    return html_url


def _new_index(name: str, binary: str) -> GistMeta:
    return {
        "ohbin_gist": _INDEX_VERSION,
        "name": name,
        "binary": binary,
        "encrypted": True,
        "assets": {},
    }


def _snapshot(gist: dict[str, object], gid: str) -> str:
    """Short id for the gist's current revision — used as the cache-busting version."""
    history = gist.get("history")
    if isinstance(history, list) and history:
        first = history[0]
        if isinstance(first, dict):
            version = first.get("version")
            if isinstance(version, str):
                return version[:12]
    return gid[:12]


def resolve_gist(gist_ref: str, *, password: str | None = None) -> tuple[str, ToolConfig]:
    """Read a gist's `ohbin.json` index and build a ToolConfig (pins ciphertext SHAs)."""
    gid = _parse_gist_id(gist_ref)
    gist = _gh_api("GET", f"gists/{gid}")
    files = gist.get("files")
    if not isinstance(files, dict):
        msg = f"gist {gid} has no files"
        raise GistError(msg)
    meta = _load_index(files)

    assets: dict[str, AssetEntry] = {}
    for plat, info in meta["assets"].items():
        raw_url = _file_entry(files, info["file"]).get("raw_url")
        if not isinstance(raw_url, str):
            msg = f"gist file {info['file']!r} has no raw_url"
            raise GistError(msg)
        # Hash the bytes GitHub actually serves (immune to any newline normalisation).
        assets[plat] = AssetEntry(
            url=raw_url,
            sha256=sha256_of_url(raw_url),
            binary_sha256=info["binary_sha256"],
        )

    cfg = ToolConfig(
        repo=f"gist:{gid}",
        version=f"gist-{_snapshot(gist, gid)}",
        binary=meta["binary"],
        assets=assets,
        encrypted=True,
    )
    if password is not None:
        cfg["password"] = password
    return meta["name"], cfg


def add_gist_tool(
    *,
    gist_ref: str,
    name: str | None,
    password: str | None,
    pyproject: Path | None,
) -> tuple[str, Path]:
    """Resolve a gist and write its (encrypted) tool entry into pyproject."""
    resolved_name, cfg = resolve_gist(gist_ref, password=password)
    cmd_name = name or resolved_name
    target = local_pyproject(pyproject)
    write_tool(target, cmd_name, cfg)
    return cmd_name, target
