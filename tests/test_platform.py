"""OS/arch normalization and platform keys."""

from __future__ import annotations

import pytest

from ohbin._platform import TARGET_PLATFORMS, Platform, _normalized_arch


@pytest.mark.parametrize(
    ("machine", "os_name", "expected"),
    [
        ("x86_64", "linux", "x86_64"),
        ("amd64", "linux", "x86_64"),
        ("x64", "windows", "x86_64"),
        ("aarch64", "linux", "aarch64"),
        ("arm64", "linux", "aarch64"),  # Linux release triples spell it aarch64
        ("arm64", "darwin", "arm64"),  # Apple Silicon keeps arm64
        ("aarch64", "darwin", "arm64"),
        ("riscv64", "linux", "riscv64"),  # unknown arch passes through verbatim
    ],
)
def test_normalized_arch(machine: str, os_name: str, expected: str) -> None:
    assert _normalized_arch(machine, os_name) == expected


def test_platform_key() -> None:
    assert Platform("darwin", "arm64").key == "darwin-arm64"
    assert Platform("linux", "x86_64").key == "linux-x86_64"


def test_target_platforms_have_unique_keys() -> None:
    keys = [p.key for p in TARGET_PLATFORMS]
    assert keys == ["linux-x86_64", "linux-aarch64", "darwin-x86_64", "darwin-arm64"]
    assert len(set(keys)) == len(keys)
