"""`write_tool`: round-trip rewrites that must not clobber surrounding file content."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohbin._add import write_tool
from ohbin._manifest import load_tool
from ohbin._types import AssetEntry, ToolConfig


def _cfg(version: str) -> ToolConfig:
    return ToolConfig(
        repo="owner/foo",
        version=version,
        binary="foo",
        assets={
            "linux-x86_64": AssetEntry(url=f"https://example/v{version}/foo-linux.tar.gz", sha256="aaaa"),
            "darwin-arm64": AssetEntry(url=f"https://example/v{version}/foo-darwin.tar.gz", sha256="bbbb"),
        },
    )


def test_overwrite_preserves_following_comment_block(tmp_path: Path) -> None:
    # The comment block + blank line before the NEXT section is parsed by tomlkit
    # into the tool's innermost sub-table body. Overwriting the tool must not eat it.
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        "[tool.ohbin.tools.foo]\n"
        'repo = "owner/foo"\n'
        'version = "0.7.0"\n'
        'binary = "foo"\n'
        "\n"
        "[tool.ohbin.tools.foo.assets.darwin-arm64]\n"
        'url = "https://example/v0.7.0/foo-darwin.tar.gz"\n'
        'sha256 = "old"\n'
        "\n"
        "# Single source of truth for the harness path scope.\n"
        "# This block belongs to [tool.other], not to foo.\n"
        "[tool.other]\n"
        'key = "value"\n'
    )

    write_tool(pp, "foo", _cfg("0.7.5"))
    out = pp.read_text()

    assert "# Single source of truth for the harness path scope." in out
    assert "# This block belongs to [tool.other], not to foo." in out
    # Blank-line separator between the tool block and the comment survives.
    assert "\n\n# Single source of truth" in out
    # The next section header is intact and still preceded by its comments.
    assert out.index("# This block belongs") < out.index("[tool.other]")
    # The version bump actually happened.
    assert load_tool("foo", pyproject=pp)["version"] == "0.7.5"
    assert "0.7.0" not in out


def test_add_new_tool_keeps_following_comment_after_new_entry(tmp_path: Path) -> None:
    # An existing tool's innermost body holds the comment block that belongs to the
    # NEXT top-level section. Appending a *new* tool must move that comment past the
    # new entry (not strand it above it) and keep a blank separator before the section.
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        "[tool.ohbin.tools.foo]\n"
        'repo = "owner/foo"\n'
        'version = "0.7.0"\n'
        'binary = "foo"\n'
        "\n"
        "[tool.ohbin.tools.foo.assets.darwin-arm64]\n"
        'url = "https://example/v0.7.0/foo-darwin.tar.gz"\n'
        'sha256 = "old"\n'
        "\n"
        "# This comment belongs to [tool.other], not to foo or bar.\n"
        "[tool.other]\n"
        'key = "value"\n'
    )

    write_tool(pp, "bar", _cfg("1.0.0"))
    out = pp.read_text()

    # The new tool is fully present and the old one untouched.
    assert load_tool("bar", pyproject=pp)["version"] == "1.0.0"
    assert load_tool("foo", pyproject=pp)["version"] == "0.7.0"
    # Comment block now sits AFTER the new tool's last asset and BEFORE [tool.other],
    # with a blank-line separator — not stranded above [tool.ohbin.tools.bar].
    assert out.index("[tool.ohbin.tools.bar]") < out.index("# This comment belongs")
    assert out.index("# This comment belongs") < out.index("[tool.other]")
    assert "\n\n# This comment belongs" in out


def test_add_new_tool_appends_without_touching_existing(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "demo"\n\n# trailing project comment\n')

    write_tool(pp, "foo", _cfg("1.0.0"))
    out = pp.read_text()

    assert "# trailing project comment" in out
    tool = load_tool("foo", pyproject=pp)
    assert tool["version"] == "1.0.0"
    assert set(tool["assets"]) == {"linux-x86_64", "darwin-arm64"}


def test_overwrite_at_eof_is_idempotent_on_layout(tmp_path: Path) -> None:
    # No following section: a re-add must produce stable, parseable output.
    pp = tmp_path / "pyproject.toml"
    pp.write_text("")
    write_tool(pp, "foo", _cfg("0.1.0"))
    write_tool(pp, "foo", _cfg("0.2.0"))

    tool = load_tool("foo", pyproject=pp)
    assert tool["version"] == "0.2.0"
    assert "0.1.0" not in pp.read_text()


def test_write_new_tool_into_empty_file(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("")
    write_tool(pp, "foo", _cfg("3.1.4"))
    assert load_tool("foo", pyproject=pp)["version"] == "3.1.4"


@pytest.mark.parametrize("trailing", ["", "\n", "\n\n"])
def test_overwrite_tolerates_varied_trailing_whitespace(tmp_path: Path, trailing: str) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("")
    write_tool(pp, "foo", _cfg("0.1.0"))
    pp.write_text(pp.read_text().rstrip("\n") + trailing)

    write_tool(pp, "foo", _cfg("0.2.0"))
    assert load_tool("foo", pyproject=pp)["version"] == "0.2.0"


def _enc_cfg(version: str, plats: tuple[str, ...] = ("darwin-arm64", "linux-x86_64")) -> ToolConfig:
    # Encrypted (gist-style) cfg: per-platform ciphertext + decrypted-binary hash.
    return ToolConfig(
        repo="gist:abc123",
        version=version,
        binary="dbmap",
        encrypted=True,
        password="pw",
        assets={
            plat: AssetEntry(
                url=f"https://gist/{version}/{plat}.enc.b64",
                sha256=f"sha-{version}-{plat}",
                binary_sha256=f"bin-{version}-{plat}",
            )
            for plat in plats
        },
    )


_DBMAP_PYPROJECT = (
    "[tool.ohbin.tools.dbmap]\n"
    'repo = "gist:abc123"\n'
    'version = "gist-old"\n'
    'binary = "dbmap"\n'
    "encrypted = true\n"
    'password = "pw"\n'
    "# Password intentionally committed: secret gist, dev tool — not a secret.\n"
    "password_committed_ok = true\n"
    "\n"
    "[tool.ohbin.tools.dbmap.assets.darwin-arm64]\n"
    'url = "https://gist/old/darwin-arm64.enc.b64"\n'
    'sha256 = "sha-gist-old-darwin-arm64"\n'
    'binary_sha256 = "bin-gist-old-darwin-arm64"\n'
    "\n"
    "[tool.ohbin.tools.dbmap.assets.linux-x86_64]\n"
    'url = "https://gist/old/linux-x86_64.enc.b64"\n'
    'sha256 = "sha-gist-old-linux-x86_64"\n'
    'binary_sha256 = "bin-gist-old-linux-x86_64"\n'
    "\n"
    "# flowmap — a sibling tool; this comment belongs to it.\n"
    "[tool.ohbin.tools.flowmap]\n"
    'repo = "gist:def456"\n'
    'version = "gist-fm"\n'
    'binary = "flowmap"\n'
)


def test_overwrite_preserves_interior_comment_and_user_key(tmp_path: Path) -> None:
    # Re-publishing an encrypted gist tool (same platform set, new version + hashes)
    # must not eat a user-authored key (`password_committed_ok`), its leading
    # comment, or the blank-line layout before the following section — the
    # regression behind the dbmap re-publish.
    pp = tmp_path / "pyproject.toml"
    pp.write_text(_DBMAP_PYPROJECT)

    write_tool(pp, "dbmap", _enc_cfg("gist-new"))
    out = pp.read_text()

    tool = load_tool("dbmap", pyproject=pp)
    # User-authored key + its leading comment survive untouched.
    assert tool.get("password_committed_ok") is True
    assert "# Password intentionally committed: secret gist, dev tool — not a secret." in out
    # The generated fields were actually refreshed.
    assert tool["version"] == "gist-new"
    assert "gist-old" not in out
    assert tool["assets"]["darwin-arm64"].get("binary_sha256") == "bin-gist-new-darwin-arm64"
    assert "bin-gist-old-darwin-arm64" not in out
    # The sibling's comment still sits directly above its header — no stray blank
    # line injected between them — and the sibling tool is intact.
    assert "# flowmap — a sibling tool; this comment belongs to it.\n[tool.ohbin.tools.flowmap]" in out
    assert load_tool("flowmap", pyproject=pp)["version"] == "gist-fm"
    # No blank line was injected where there wasn't one (no doubled blank lines).
    assert "\n\n\n" not in out


def test_overwrite_with_changed_platforms_keeps_user_key(tmp_path: Path) -> None:
    # Even when the platform set changes (rebuild path), the user-authored key and
    # the following section's comment must be preserved.
    pp = tmp_path / "pyproject.toml"
    pp.write_text(_DBMAP_PYPROJECT)

    write_tool(pp, "dbmap", _enc_cfg("gist-new", plats=("darwin-arm64", "darwin-x86_64", "linux-x86_64")))
    out = pp.read_text()

    tool = load_tool("dbmap", pyproject=pp)
    assert tool.get("password_committed_ok") is True
    assert "# Password intentionally committed: secret gist, dev tool — not a secret." in out
    assert set(tool["assets"]) == {"darwin-arm64", "darwin-x86_64", "linux-x86_64"}
    assert "# flowmap — a sibling tool; this comment belongs to it." in out
    assert load_tool("flowmap", pyproject=pp)["version"] == "gist-fm"
    assert "\n\n\n" not in out
