"""Locate and parse the `[tool.ohbin.tools.*]` manifest from a project's pyproject."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from ohbin._errors import OhbinError
from ohbin._types import AssetEntry, ToolConfig


class ManifestError(OhbinError):
    """Raised when the manifest is missing or a tool entry is malformed."""


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _has_ohbin(path: Path) -> bool:
    data = _read(path)
    tool = data.get("tool")
    return isinstance(tool, dict) and "ohbin" in tool


def find_pyproject(start: Path | None = None) -> Path:
    """Find the nearest pyproject.toml carrying `[tool.ohbin]`, walking up from CWD.

    `OHBIN_PYPROJECT` overrides discovery (handy for CI / in-process callers
    that run from an unrelated CWD).
    """
    override = os.environ.get("OHBIN_PYPROJECT")
    if override:
        p = Path(override)
        if not p.is_file():
            msg = f"OHBIN_PYPROJECT points to a missing file: {p}"
            raise ManifestError(msg)
        return p

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file() and _has_ohbin(candidate):
            return candidate

    msg = "no pyproject.toml with [tool.ohbin] found (set OHBIN_PYPROJECT to override)"
    raise ManifestError(msg)


def _parse_asset(tool: str, key: str, raw: object) -> AssetEntry:
    if not isinstance(raw, dict) or "url" not in raw or "sha256" not in raw:
        msg = f"tool {tool!r}: asset {key!r} must define both 'url' and 'sha256'"
        raise ManifestError(msg)
    entry = AssetEntry(url=str(raw["url"]), sha256=str(raw["sha256"]))
    if "binary_sha256" in raw:
        entry["binary_sha256"] = str(raw["binary_sha256"])
    return entry


def _parse_tool(name: str, raw: object) -> ToolConfig:
    if not isinstance(raw, dict):
        msg = f"tool {name!r} must be a table"
        raise ManifestError(msg)
    for required in ("repo", "version"):
        if required not in raw:
            msg = f"tool {name!r} is missing required key {required!r}"
            raise ManifestError(msg)
    raw_assets = raw.get("assets", {})
    if not isinstance(raw_assets, dict):
        msg = f"tool {name!r}: 'assets' must be a table"
        raise ManifestError(msg)
    assets = {str(k): _parse_asset(name, str(k), v) for k, v in raw_assets.items()}
    cfg = ToolConfig(
        repo=str(raw["repo"]),
        version=str(raw["version"]),
        binary=str(raw.get("binary", name)),
        assets=assets,
    )
    if raw.get("encrypted"):
        cfg["encrypted"] = True
    if "password" in raw:
        cfg["password"] = str(raw["password"])
    if raw.get("password_committed_ok"):
        cfg["password_committed_ok"] = True
    return cfg


def load_tools(pyproject: Path | None = None) -> dict[str, ToolConfig]:
    path = pyproject or find_pyproject()
    data = _read(path)
    raw_tools = data.get("tool", {}).get("ohbin", {}).get("tools", {})
    if not isinstance(raw_tools, dict):
        msg = "[tool.ohbin.tools] must be a table"
        raise ManifestError(msg)
    return {str(name): _parse_tool(str(name), raw) for name, raw in raw_tools.items()}


def load_tool(name: str, pyproject: Path | None = None) -> ToolConfig:
    tools = load_tools(pyproject)
    if name not in tools:
        declared = ", ".join(sorted(tools)) or "none"
        msg = f"tool {name!r} not declared in [tool.ohbin.tools] (declared: {declared})"
        raise ManifestError(msg)
    return tools[name]
