"""`ohbin add`: resolve a GitHub release's per-platform assets and write them into pyproject."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ohbin._engine import sha256_of_url
from ohbin._errors import OhbinError
from ohbin._github import Asset, fetch_release
from ohbin._platform import (
    ALL_ARCH_TOKENS,
    TARGET_PLATFORMS,
    Platform,
    arch_tokens,
    os_tokens,
)
from ohbin._types import AssetEntry, ToolConfig

if TYPE_CHECKING:
    from tomlkit.items import Item, Key, Table

    # One element of a tomlkit container body: a real key + item, or (None, item)
    # for standalone whitespace/comment lines.
    BodyEntry = tuple[Key | None, Item]

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


class AddError(OhbinError):
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


def local_pyproject(explicit: Path | None) -> Path:
    """Resolve the pyproject to *write* to: an explicit `--pyproject-file`, else ./pyproject.toml.

    Mutating commands never walk up the tree — that would let `ohbin add` from a
    subdirectory silently edit a parent project's pyproject. Reading still discovers
    upward (see `find_pyproject`); writing stays local and explicit.
    """
    if explicit is not None:
        return explicit
    local = Path("pyproject.toml")
    if not local.is_file():
        msg = "no pyproject.toml in the current directory (pass --pyproject-file to target one)"
        raise AddError(msg)
    return local


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


def _deepest_last_table(table: Table) -> Table:
    """Descend through the last sub-table at each level to the innermost one.

    Standalone comments/blank lines between the end of a tool's last sub-table and
    the next section header are parsed by tomlkit into *that* innermost sub-table's
    body — so this is where trailing trivia lives and must be re-attached.
    """
    from tomlkit.items import Table

    last_sub: Table | None = None
    for _key, item in table.value.body:
        if isinstance(item, Table):
            last_sub = item
    if last_sub is None:
        return table
    return _deepest_last_table(last_sub)


def _detach_trailing_trivia(table: Table) -> list[BodyEntry]:
    """Pop the trailing run of standalone whitespace/comments from a tool's last table.

    Returns them in document order; an empty list when the table ends on a real key.
    These belong to the *following* section (a comment block before the next header),
    not the tool — overwriting the tool entry must not eat them.
    """
    from tomlkit.items import Comment, Whitespace

    body = _deepest_last_table(table).value.body
    trailing: list[BodyEntry] = []
    while body and body[-1][0] is None and isinstance(body[-1][1], (Whitespace, Comment)):
        trailing.insert(0, body.pop())
    return trailing


def _set_asset_fields(sub: Table, asset: AssetEntry) -> None:
    """Set url/sha256/binary_sha256 on one asset sub-table, in place."""
    sub["url"] = asset["url"]
    sub["sha256"] = asset["sha256"]
    if "binary_sha256" in asset:
        sub["binary_sha256"] = asset["binary_sha256"]
    elif "binary_sha256" in sub:
        del sub["binary_sha256"]


def _build_assets_table(cfg_assets: dict[str, AssetEntry]) -> Table:
    """A fresh `[...assets.<plat>]` super-table from a resolved asset map."""
    import tomlkit

    assets = tomlkit.table(is_super_table=True)
    for plat_key, asset in cfg_assets.items():
        sub = tomlkit.table()
        _set_asset_fields(sub, asset)
        assets[plat_key] = sub
    return assets


def _set_generated_fields(entry: Table, cfg: ToolConfig) -> None:
    """Write the fields ohbin owns: repo / version / binary / encrypted / password.

    Assigning an existing key updates its value in place — position and any attached
    comment are kept — so user-authored keys ohbin doesn't generate (e.g.
    `password_committed_ok`) are never touched here. `password` is only written when
    the caller supplied one (omitting it lets a manually-set password survive).
    """
    entry["repo"] = cfg["repo"]
    entry["version"] = cfg["version"]
    entry["binary"] = cfg["binary"]
    if cfg.get("encrypted"):
        entry["encrypted"] = True
    if "password" in cfg:
        entry["password"] = cfg["password"]


def _update_assets_in_place(entry: Table, cfg_assets: dict[str, AssetEntry]) -> None:
    """Refresh a tool's asset sub-tables without disturbing surrounding trivia.

    Same platform set (the common re-publish): update each sub-table's values in
    place — nothing structural moves, so the comment block that belongs to the next
    section (which tomlkit parses into the last asset's body) stays put. If the set
    or order changed, detach that trailing block, rebuild the sub-tables, then
    re-attach it to the new last asset so it still precedes the next section.
    """
    import tomlkit
    from tomlkit.items import Table

    existing = entry.get("assets")
    if not isinstance(existing, Table):
        entry["assets"] = _build_assets_table(cfg_assets)
        return
    if list(existing.keys()) == list(cfg_assets.keys()):
        for plat, asset in cfg_assets.items():
            _set_asset_fields(existing[plat], asset)
        return
    # Set/order changed. Reconcile rather than empty-and-rebuild: deleting the
    # first sub-table perturbs the leading blank line before the assets block, so
    # keep the platforms that survive (update in place), drop the gone ones, and
    # append the new ones. The trailing comment block lives in the current last
    # asset's body — detach it first so a removed-or-shifted last asset can't strand
    # it, then re-attach it to whatever asset ends up last.
    trailing = _detach_trailing_trivia(entry)
    for plat in list(existing.keys()):
        if plat not in cfg_assets:
            del existing[plat]
    for plat, asset in cfg_assets.items():
        sub = existing.get(plat)
        if isinstance(sub, Table):
            _set_asset_fields(sub, asset)
        else:
            sub = tomlkit.table()
            _set_asset_fields(sub, asset)
            existing[plat] = sub
    if trailing:
        _deepest_last_table(entry).value.body.extend(trailing)


def _append_new_tool(tools: Table, name: str, cfg: ToolConfig) -> None:
    """Append a brand-new tool entry, keeping any following section's comment block.

    A comment block before the next top-level section is parsed into the innermost
    body of whichever tool is physically last in `[tool.ohbin.tools]`. tomlkit would
    place the new table *after* that trivia — stranding the comment above the new
    entry and dropping the separator — so detach it and move it past the new entry.
    """
    import tomlkit

    next_section_trivia: list[BodyEntry] = []
    if _deepest_last_table(tools) is not tools:
        next_section_trivia = _detach_trailing_trivia(tools)

    entry = tomlkit.table()
    _set_generated_fields(entry, cfg)
    if cfg.get("password_committed_ok"):
        entry["password_committed_ok"] = True
    entry["assets"] = _build_assets_table(cfg["assets"])

    tools[name] = entry
    if next_section_trivia:
        _deepest_last_table(entry).value.body.extend(next_section_trivia)


def write_tool(pyproject: Path, name: str, cfg: ToolConfig) -> None:
    """Write/overwrite `[tool.ohbin.tools.<name>]`, preserving the rest of the file.

    Overwriting an existing tool mutates it *in place*: only the ohbin-generated
    fields and asset hashes change, so interior comments and user-authored keys
    (e.g. `password_committed_ok`) survive untouched. Appending a new tool builds a
    fresh table and moves any following comment block (which tomlkit parses into the
    last existing tool's body) past the new entry.
    """
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

    old_entry = tools.get(name)
    if isinstance(old_entry, Table):
        _set_generated_fields(old_entry, cfg)
        _update_assets_in_place(old_entry, cfg["assets"])
    else:
        _append_new_tool(tools, name, cfg)

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
    target = local_pyproject(pyproject)
    write_tool(target, cmd_name, cfg)
    return cmd_name, target
