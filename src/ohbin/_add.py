"""`ohbin add`: resolve a GitHub release's per-platform assets and write them into pyproject."""

from __future__ import annotations

import sys
from pathlib import Path

from ohbin._engine import sha256_of_url
from ohbin._github import Asset, fetch_release
from ohbin._platform import (
    ALL_ARCH_TOKENS,
    TARGET_PLATFORMS,
    Platform,
    arch_tokens,
    os_tokens,
)
from ohbin._types import AssetEntry, ToolConfig

# Asset filenames that are never the binary we want.
_DENY_SUFFIXES = (
    ".txt",
    ".sha256",
    ".sha256sum",
    ".sums",
    ".asc",
    ".sig",
    ".minisig",
    ".pem",
    ".pubkey",
    ".json",
    ".deb",
    ".rpm",
    ".msi",
    ".pdb",
    ".md",
)


class AddError(RuntimeError):
    """Raised when a release yields no usable assets, or pyproject can't be located."""


def _is_candidate(name: str) -> bool:
    low = name.lower()
    if low.endswith(_DENY_SUFFIXES):
        return False
    return not ("checksum" in low or "sbom" in low)


def _archive_rank(name: str) -> int:
    low = name.lower()
    if low.endswith((".tar.gz", ".tgz")):
        return 0
    if low.endswith((".tar.xz", ".tar.bz2", ".tar")):
        return 1
    if low.endswith(".zip"):
        return 2
    return 3  # bare binary


def _has_token(name: str, tokens: tuple[str, ...]) -> bool:
    low = name.lower()
    return any(token in low for token in tokens)


def match_asset(assets: list[Asset], plat: Platform) -> Asset | None:
    candidates = [a for a in assets if _is_candidate(a.name)]
    primary = [a for a in candidates if _has_token(a.name, os_tokens(plat)) and _has_token(a.name, arch_tokens(plat))]
    if not primary:
        # Universal asset: matches the OS but carries no arch token at all
        # (e.g. a `*_darwin_universal.tar.gz` serves both darwin arches).
        primary = [
            a for a in candidates if _has_token(a.name, os_tokens(plat)) and not _has_token(a.name, ALL_ARCH_TOKENS)
        ]
    if not primary:
        return None
    primary.sort(key=lambda a: (_archive_rank(a.name), len(a.name)))
    return primary[0]


def _digest_sha256(asset: Asset) -> str | None:
    if asset.digest and asset.digest.startswith("sha256:"):
        return asset.digest.removeprefix("sha256:")
    return None


def _nearest_pyproject(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    msg = "no pyproject.toml found from CWD upward"
    raise AddError(msg)


def resolve_tool(*, repo: str, version: str | None, binary: str | None) -> ToolConfig:
    """Fetch the release and build a ToolConfig with per-platform assets + checksums."""
    release = fetch_release(repo, version)
    cmd_name = repo.split("/")[-1]
    bin_name = binary or cmd_name

    assets: dict[str, AssetEntry] = {}
    for plat in TARGET_PLATFORMS:
        asset = match_asset(release.assets, plat)
        if asset is None:
            print(f"  ! {plat.key:15} no matching asset — skipped", file=sys.stderr)
            continue
        sha256 = _digest_sha256(asset)
        source = "digest" if sha256 else "downloaded+hashed"
        if sha256 is None:
            sha256 = sha256_of_url(asset.url)
        assets[plat.key] = AssetEntry(url=asset.url, sha256=sha256)
        print(f"  + {plat.key:15} {asset.name}  ({source})")

    if not assets:
        msg = f"no matching assets found in {repo}@{release.tag}"
        raise AddError(msg)

    return ToolConfig(
        repo=repo,
        version=release.tag.removeprefix("v"),
        binary=bin_name,
        assets=assets,
    )


def write_tool(pyproject: Path, name: str, cfg: ToolConfig) -> None:
    """Write/overwrite `[tool.ohbin.tools.<name>]`, preserving the rest of the file."""
    import tomlkit
    from tomlkit import TOMLDocument
    from tomlkit.items import Table

    doc = tomlkit.parse(pyproject.read_text())

    def ensure(parent: TOMLDocument | Table, key: str, *, super_table: bool) -> Table:
        existing = parent.get(key)
        if isinstance(existing, Table):
            return existing
        created = tomlkit.table(is_super_table=super_table)
        parent[key] = created
        return created

    tools = ensure(
        ensure(ensure(doc, "tool", super_table=True), "ohbin", super_table=True),
        "tools",
        super_table=True,
    )

    entry = tomlkit.table()
    entry["repo"] = cfg["repo"]
    entry["version"] = cfg["version"]
    entry["binary"] = cfg["binary"]

    assets = tomlkit.table(is_super_table=True)
    for plat_key, asset in cfg["assets"].items():
        asset_table = tomlkit.table()
        asset_table["url"] = asset["url"]
        asset_table["sha256"] = asset["sha256"]
        assets[plat_key] = asset_table
    entry["assets"] = assets

    tools[name] = entry
    pyproject.write_text(tomlkit.dumps(doc))


def add_tool(
    *,
    repo: str,
    version: str | None,
    name: str | None,
    binary: str | None,
    pyproject: Path | None,
) -> tuple[str, Path]:
    cfg = resolve_tool(repo=repo, version=version, binary=binary)
    cmd_name = name or repo.split("/")[-1]
    target = pyproject or _nearest_pyproject()
    write_tool(target, cmd_name, cfg)
    return cmd_name, target
