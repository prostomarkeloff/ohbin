"""ohbin — declarative GitHub-release binaries for uv projects.

Declare tools in your project's pyproject:

    [tool.ohbin.tools.rg]
    repo = "BurntSushi/ripgrep"
    version = "14.1.1"
    binary = "rg"

    [tool.ohbin.tools.rg.assets.darwin-arm64]
    url = "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
    sha256 = "..."

then `uv run ohbin run rg -- <args>`, or in-process `ohbin.ensure("rg")`.
"""

from __future__ import annotations

from pathlib import Path

from ohbin._engine import (
    BinaryNotFoundError,
    ChecksumMismatchError,
    cache_root,
    ensure_from,
)
from ohbin._manifest import ManifestError, find_pyproject, load_tool, load_tools
from ohbin._platform import Platform, UnsupportedPlatformError, current_platform
from ohbin._types import AssetEntry, ToolConfig

__all__ = [
    "AssetEntry",
    "BinaryNotFoundError",
    "ChecksumMismatchError",
    "ManifestError",
    "Platform",
    "ToolConfig",
    "UnsupportedPlatformError",
    "cache_root",
    "current_platform",
    "ensure",
    "ensure_from",
    "find_pyproject",
    "load_tool",
    "load_tools",
]


def ensure(tool: str, *, pyproject: Path | None = None) -> Path:
    """Return the cached binary path for a declared tool, downloading on first use.

    Reads `[tool.ohbin.tools.<tool>]` from the project's pyproject (discovered
    from CWD, or `OHBIN_PYPROJECT`). This is the in-process entry point — call it
    from build tooling that needs the binary's path rather than exec-ing it.
    """
    cfg = load_tool(tool, pyproject=pyproject)
    plat = current_platform()
    entry = cfg["assets"].get(plat.key)
    if entry is None:
        declared = ", ".join(sorted(cfg["assets"])) or "none"
        msg = f"tool {tool!r} has no asset for {plat.key} (declared: {declared})"
        raise UnsupportedPlatformError(msg)
    return ensure_from(
        tool=tool,
        version=cfg["version"],
        binary=cfg["binary"],
        url=entry["url"],
        sha256=entry["sha256"],
    )
