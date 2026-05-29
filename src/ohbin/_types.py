"""Typed shapes for the manifest boundary (`[tool.ohbin.tools.*]`)."""

from __future__ import annotations

from typing import TypedDict


class AssetEntry(TypedDict):
    """A single resolved release asset for one platform: where to get it + its hash."""

    url: str
    sha256: str


class ToolConfig(TypedDict):
    """One tool as declared under `[tool.ohbin.tools.<name>]`.

    `binary` is the executable's filename *inside* the archive (defaults to the
    tool's command name). `assets` is keyed by `"<os>-<arch>"` platform keys.
    """

    repo: str
    version: str
    binary: str
    assets: dict[str, AssetEntry]
