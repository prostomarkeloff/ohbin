"""Download + SHA256-verify + cache a release binary on first use.

Cache layout (`$XDG_CACHE_HOME` or `~/.cache`):

    ohbin/<tool>/<version>/<binary>   ← extracted, chmod +x binary
    ohbin/<tool>/<version>/.lock      ← flock during install

Concurrent invocations on the same host coordinate via flock — first one
downloads, the rest wait and reuse the same binary. POSIX-only (fcntl); a
Windows path isn't shipped until someone needs it.
"""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, TYPE_CHECKING
from urllib.parse import unquote, urlparse

from ohbin._crypto import decrypt_binary
from ohbin._errors import OhbinError
from ohbin._retry import retry, retryable_http_status

if TYPE_CHECKING:
    from collections.abc import Iterator

_DOWNLOAD_TIMEOUT = 60  # seconds per read/connect attempt


class ChecksumMismatchError(OhbinError):
    """Raised when a downloaded asset's SHA256 doesn't match the pinned value."""


class BinaryNotFoundError(OhbinError):
    """Raised when the expected binary isn't present inside a downloaded archive."""


class MissingPasswordError(OhbinError):
    """Raised when an encrypted tool is run without a password from --password or pyproject."""


class _TransientDownloadError(RuntimeError):
    """Internal: a retryable download failure (network / timeout / truncated stream)."""


def cache_root(tool: str, version: str) -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ohbin" / tool / version


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _sha256_of(stream: IO[bytes]) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def _download_once(url: str, dest: Path) -> None:
    # Release URLs redirect to a signed CDN host; urllib follows redirects by
    # default. Stream to disk so we don't buffer the archive in RAM.
    request = urllib.request.Request(url, headers={"User-Agent": "ohbin"})
    try:
        with (
            urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response,
            dest.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
    except urllib.error.HTTPError as exc:  # check first — subclass of URLError/OSError
        if retryable_http_status(exc.code):
            raise _TransientDownloadError(f"download {url} → HTTP {exc.code}") from exc
        raise
    except (OSError, http.client.IncompleteRead) as exc:
        # URLError, ConnectionError, timeout, or a truncated/reset stream.
        raise _TransientDownloadError(f"download {url} failed: {exc}") from exc


def _download(url: str, dest: Path) -> None:
    retry(lambda: _download_once(url, dest), op="download", retry_on=(_TransientDownloadError,))


def sha256_of_url(url: str) -> str:
    """Download a URL to a temp file and return its SHA256 (used by `add`)."""
    fd, name = tempfile.mkstemp(prefix="ohbin-")
    os.close(fd)
    tmp = Path(name)
    try:
        _download(url, tmp)
        with tmp.open("rb") as fh:
            return _sha256_of(fh)
    finally:
        tmp.unlink(missing_ok=True)


def _verify(path: Path, expected_sha256: str) -> None:
    with path.open("rb") as fh:
        actual = _sha256_of(fh)
    if actual != expected_sha256:
        msg = f"checksum mismatch for {path.name}: expected {expected_sha256}, got {actual}"
        raise ChecksumMismatchError(msg)


def _url_filename(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or "download"


def _finalize(staged: Path, dest: Path) -> None:
    staged.chmod(0o755)
    staged.replace(dest)  # atomic within the same filesystem


def _extract_tar(archive: Path, binary: str, dest: Path) -> None:
    with tarfile.open(archive, "r:*") as tf:  # r:* auto-detects gz/xz/bz2/plain
        member = next(
            (m for m in tf.getmembers() if m.isfile() and Path(m.name).name == binary),
            None,
        )
        if member is None:
            msg = f"binary {binary!r} not found in archive {archive.name}"
            raise BinaryNotFoundError(msg)
        with tempfile.TemporaryDirectory(dir=str(dest.parent)) as staging:
            tf.extract(member, path=staging, filter="data")
            _finalize(Path(staging) / member.name, dest)


def _extract_zip(archive: Path, binary: str, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        member = next(
            (n for n in zf.namelist() if not n.endswith("/") and Path(n).name == binary),
            None,
        )
        if member is None:
            msg = f"binary {binary!r} not found in archive {archive.name}"
            raise BinaryNotFoundError(msg)
        with tempfile.TemporaryDirectory(dir=str(dest.parent)) as staging:
            zf.extract(member, path=staging)
            _finalize(Path(staging) / member, dest)


def _place_raw(archive: Path, dest: Path) -> None:
    # Asset is the bare executable (no archive wrapper).
    with tempfile.TemporaryDirectory(dir=str(dest.parent)) as staging:
        staged = Path(staging) / dest.name
        shutil.copyfile(archive, staged)
        _finalize(staged, dest)


def _decrypt_into(archive: Path, dest: Path, *, password: str | None, binary_sha256: str | None) -> None:
    # The downloaded file is base64 text (gzip+AES blob); decrypt to the raw binary.
    if not password:
        msg = "encrypted tool requires a password (pass --password or set 'password' in pyproject)"
        raise MissingPasswordError(msg)
    binary = decrypt_binary(archive.read_text(), password)
    if binary_sha256 is not None:
        actual = hashlib.sha256(binary).hexdigest()
        if actual != binary_sha256:
            msg = (
                f"decrypted binary checksum mismatch: expected {binary_sha256}, got {actual} "
                "(wrong password or corrupt blob)"
            )
            raise ChecksumMismatchError(msg)
    with tempfile.TemporaryDirectory(dir=str(dest.parent)) as staging:
        staged = Path(staging) / dest.name
        staged.write_bytes(binary)
        _finalize(staged, dest)


def _extract(archive: Path, binary: str, dest: Path) -> None:
    name = archive.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
        _extract_tar(archive, binary, dest)
    elif name.endswith(".zip"):
        _extract_zip(archive, binary, dest)
    else:
        _place_raw(archive, dest)


def ensure_from(
    *,
    tool: str,
    version: str,
    binary: str,
    url: str,
    sha256: str,
    encrypted: bool = False,
    password: str | None = None,
    binary_sha256: str | None = None,
) -> Path:
    """Return the cached binary path, downloading + verifying it on first use.

    For encrypted tools the downloaded file is a base64 gzip+AES blob: `sha256`
    verifies the ciphertext (tamper-evidence on the gist), then it's decrypted with
    `password` and the plaintext checked against `binary_sha256`. The decrypted
    binary is cached like any other — first run decrypts, the rest reuse it.
    """
    cache = cache_root(tool, version)
    target = cache / binary
    if target.is_file() and os.access(target, os.X_OK):
        return target

    with _exclusive_lock(cache / ".lock"):
        # Another process may have finished while we waited on the lock.
        if target.is_file() and os.access(target, os.X_OK):
            return target

        archive = cache / _url_filename(url)
        try:
            _download(url, archive)
            _verify(archive, sha256)
            if encrypted:
                _decrypt_into(archive, target, password=password, binary_sha256=binary_sha256)
            else:
                _extract(archive, binary, target)
        finally:
            archive.unlink(missing_ok=True)

    return target
