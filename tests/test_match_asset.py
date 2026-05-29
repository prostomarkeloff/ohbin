"""Asset-to-platform matching heuristics used by `ohbin add`."""

from __future__ import annotations

from ohbin._add import match_asset
from ohbin._github import Asset
from ohbin._platform import Platform


def _assets(*names: str) -> list[Asset]:
    return [Asset(name=n, url=f"https://example/{n}", digest=None) for n in names]


# A release with per-OS amd64/arm64 on linux and a single universal
# `*_darwin_all` archive serving both macOS arches.
UNIVERSAL = _assets(
    "demotool_1.2.3_linux_amd64.tar.gz",
    "demotool_1.2.3_linux_arm64.tar.gz",
    "demotool_1.2.3_darwin_all.tar.gz",
    "checksums.txt",
)

# Real ripgrep-style release: rust target triples, explicit per-arch macOS.
RIPGREP = _assets(
    "ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz",
    "ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz",
    "ripgrep-14.1.1-x86_64-apple-darwin.tar.gz",
    "ripgrep-14.1.1-aarch64-apple-darwin.tar.gz",
    "ripgrep-14.1.1-x86_64-pc-windows-msvc.zip",
    "ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz.sha256",
)


def _name(asset: Asset | None) -> str | None:
    return asset.name if asset else None


def test_universal_darwin_serves_both_arches() -> None:
    # No arch token in the darwin asset → it matches both darwin platforms.
    assert _name(match_asset(UNIVERSAL, Platform("darwin", "x86_64"))) == "demotool_1.2.3_darwin_all.tar.gz"
    assert _name(match_asset(UNIVERSAL, Platform("darwin", "arm64"))) == "demotool_1.2.3_darwin_all.tar.gz"


def test_linux_arch_specific() -> None:
    assert _name(match_asset(UNIVERSAL, Platform("linux", "x86_64"))) == "demotool_1.2.3_linux_amd64.tar.gz"
    assert _name(match_asset(UNIVERSAL, Platform("linux", "aarch64"))) == "demotool_1.2.3_linux_arm64.tar.gz"


def test_rust_target_triples() -> None:
    assert _name(match_asset(RIPGREP, Platform("darwin", "arm64"))) == "ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
    assert _name(match_asset(RIPGREP, Platform("linux", "x86_64"))) == "ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz"


def test_checksum_and_sig_assets_are_ignored() -> None:
    # The `.sha256` sidecar must never win for linux-x86_64.
    chosen = match_asset(RIPGREP, Platform("linux", "x86_64"))
    assert chosen is not None
    assert not chosen.name.endswith(".sha256")


def test_archive_preferred_over_zip() -> None:
    mixed = _assets(
        "tool-x86_64-apple-darwin.zip",
        "tool-x86_64-apple-darwin.tar.gz",
    )
    assert _name(match_asset(mixed, Platform("darwin", "x86_64"))) == "tool-x86_64-apple-darwin.tar.gz"


def test_no_match_returns_none() -> None:
    only_windows = _assets("tool-x86_64-pc-windows-msvc.zip")
    assert match_asset(only_windows, Platform("linux", "x86_64")) is None
