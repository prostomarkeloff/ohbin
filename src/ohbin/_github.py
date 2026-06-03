"""Resolve a GitHub release + its assets — via the `gh` CLI when present, else the REST API.

Failures are split two ways: a clean **404** means "this tag doesn't exist"
(we try `v`-prefixed then bare, then give up — never retried), while anything
else — network error, timeout, rate-limit, 5xx, a non-404 `gh` failure — is
**transient** and retried with backoff. Conflating the two is exactly what made
a flaky network look like "release not found".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, NamedTuple

from ohbin._errors import OhbinError
from ohbin._retry import retry, retryable_http_status

_API = "https://api.github.com"
_TIMEOUT = 30  # seconds per attempt


class ReleaseNotFoundError(OhbinError):
    """Raised when no release matches the given repo/version (a real 404)."""


class _TransientError(RuntimeError):
    """Internal: a retryable GitHub fetch failure (network / timeout / 5xx / rate-limit / gh error)."""


class Asset(NamedTuple):
    name: str
    url: str
    digest: str | None  # GitHub asset digest like "sha256:..." (may be absent)


class Release(NamedTuple):
    tag: str
    assets: list[Asset]


def _candidate_paths(repo: str, version: str | None) -> list[str]:
    if version is None:
        return [f"repos/{repo}/releases/latest"]
    # Accept both `v1.2.3` and `1.2.3` tag conventions.
    return [
        f"repos/{repo}/releases/tags/v{version}",
        f"repos/{repo}/releases/tags/{version}",
    ]


def _fetch_gh_one(path: str) -> dict[str, Any] | None:
    """Return parsed JSON, None on a clean 404, or raise `_TransientError` otherwise."""
    try:
        proc = subprocess.run(  # fixed argv, `gh` resolved from PATH
            ["gh", "api", path],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise _TransientError(f"gh api {path} timed out after {_TIMEOUT}s") from exc
    if proc.returncode == 0:
        parsed: dict[str, Any] = json.loads(proc.stdout)
        return parsed
    stderr = proc.stderr.strip()
    if "http 404" in stderr.lower() or "not found" in stderr.lower():
        return None
    raise _TransientError(f"gh api {path} failed: {stderr or 'unknown error'}")


def _fetch_http_one(path: str) -> dict[str, Any] | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ohbin",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{_API}/{path}", headers=headers)  # fixed https host
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            parsed: dict[str, Any] = json.loads(response.read())
            return parsed
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if retryable_http_status(exc.code):
            raise _TransientError(f"GET {path} → HTTP {exc.code}") from exc
        raise
    except urllib.error.URLError as exc:  # network / DNS / timeout
        raise _TransientError(f"GET {path} failed: {exc.reason}") from exc


def _fetch_raw(repo: str, version: str | None) -> dict[str, Any]:
    fetch_one = _fetch_gh_one if shutil.which("gh") else _fetch_http_one
    candidates = _candidate_paths(repo, version)

    def attempt() -> dict[str, Any] | None:
        for path in candidates:
            data = fetch_one(path)
            if data is not None:
                return data
        return None  # every candidate was a clean 404 → genuinely not found

    raw = retry(attempt, op=f"fetch release for {repo}", retry_on=(_TransientError,))
    if raw is None:
        msg = f"could not resolve a release for {repo} (tried: {', '.join(candidates)})"
        raise ReleaseNotFoundError(msg)
    return raw


def fetch_release(repo: str, version: str | None) -> Release:
    raw = _fetch_raw(repo, version)
    assets = [
        Asset(name=str(a["name"]), url=str(a["browser_download_url"]), digest=a.get("digest"))
        for a in raw.get("assets", [])
    ]
    return Release(tag=str(raw["tag_name"]), assets=assets)
