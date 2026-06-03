"""Current-platform detection + the OS/arch token aliases used to match assets."""

from __future__ import annotations

import platform
from typing import NamedTuple

from ohbin._errors import OhbinError


class UnsupportedPlatformError(OhbinError):
    """Raised when a tool declares no asset for the current OS/arch."""


class Platform(NamedTuple):
    os: str  # "linux" | "darwin" | "windows"
    arch: str  # "x86_64" | "aarch64" | "arm64"

    @property
    def key(self) -> str:
        return f"{self.os}-{self.arch}"


def _normalized_arch(machine: str, os_name: str) -> str:
    m = machine.lower()
    if m in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if m in {"aarch64", "arm64"}:
        # Apple Silicon reports "arm64"; Linux reports "aarch64". Keep each OS
        # family's canonical spelling so the platform key matches what `add`
        # wrote (which uses the same TARGET_PLATFORMS below).
        return "arm64" if os_name == "darwin" else "aarch64"
    return m


def current_platform() -> Platform:
    os_name = platform.system().lower()
    return Platform(os=os_name, arch=_normalized_arch(platform.machine(), os_name))


# The platforms `add` tries to resolve assets for, with their canonical keys.
TARGET_PLATFORMS: tuple[Platform, ...] = (
    Platform("linux", "x86_64"),
    Platform("linux", "aarch64"),
    Platform("darwin", "x86_64"),
    Platform("darwin", "arm64"),
)

# Token aliases for fuzzy-matching release asset filenames during `add`.
_OS_ALIASES: dict[str, tuple[str, ...]] = {
    "linux": ("linux",),
    "darwin": ("darwin", "macos", "apple", "osx"),
    "windows": ("windows", "win"),
}
_ARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "x86_64": ("x86_64", "amd64", "x64"),
    "aarch64": ("aarch64", "arm64"),
    "arm64": ("arm64", "aarch64"),
}
# Every arch token we know — used to detect "universal" assets (an OS match
# carrying no arch token at all, e.g. a `*_darwin_universal.tar.gz`).
ALL_ARCH_TOKENS: tuple[str, ...] = (
    "x86_64",
    "amd64",
    "x64",
    "aarch64",
    "arm64",
    "i386",
    "i686",
    "armv7",
    "armv6",
    "s390x",
    "ppc64le",
    "riscv64",
)


def os_tokens(p: Platform) -> tuple[str, ...]:
    return _OS_ALIASES[p.os]


def arch_tokens(p: Platform) -> tuple[str, ...]:
    return _ARCH_ALIASES[p.arch]
