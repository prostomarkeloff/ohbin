"""Password-based encryption of release binaries via the system `openssl` CLI.

A published blob is `gzip(raw binary)` → AES-256-CBC (PBKDF2 key derivation) →
base64 text, so it fits inside a (text-only) GitHub gist. ohbin is the only thing
that decrypts it, so a leaked gist link is useless without the password — which
stays out of the gist (a private repo, or `--password`).

We shell out to `openssl` instead of taking a Python crypto dependency, keeping the
`run` hot path free of pip deps. The password is handed to openssl over an inherited
pipe FD (`-pass fd:N`), never on argv, so it can't leak via the process table.

CBC is unauthenticated; integrity is enforced one layer up by pinning the decrypted
binary's SHA256 in the manifest (`binary_sha256`), which also catches a wrong
password — a bad key almost always yields invalid PKCS#7 padding (openssl errors) or
garbage that fails the gzip/SHA check.
"""

from __future__ import annotations

import base64
import gzip
import os
import shutil
import subprocess

from ohbin._errors import OhbinError

# LibreSSL (macOS) and OpenSSL agree on this fully-pinned recipe; -pbkdf2 + an
# explicit digest/iter count keeps producer and consumer interoperable.
_ITER = "200000"
_ENC_ARGS = ("enc", "-aes-256-cbc", "-pbkdf2", "-md", "sha256", "-iter", _ITER, "-salt")


class OpensslMissingError(OhbinError):
    """Raised when the `openssl` CLI isn't on PATH (required for encrypted tools)."""


class DecryptError(OhbinError):
    """Raised when decryption fails — almost always a wrong password or a corrupt blob."""


def _openssl() -> str:
    path = shutil.which("openssl")
    if path is None:
        msg = "openssl not found on PATH — required to (de)crypt an encrypted ohbin tool"
        raise OpensslMissingError(msg)
    return path


def _run(extra: tuple[str, ...], stdin: bytes, password: str) -> bytes:
    """Run `openssl enc [...] -pass fd:N` feeding the password over an inherited pipe."""
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, password.encode())  # passwords are tiny — never blocks the buffer
        os.close(write_fd)
        # pass_fds keeps read_fd open + inheritable in the child; argv carries no secret.
        proc = subprocess.run(
            [_openssl(), *_ENC_ARGS, *extra, "-pass", f"fd:{read_fd}"],
            input=stdin,
            capture_output=True,
            pass_fds=(read_fd,),
            check=False,
        )
    finally:
        os.close(read_fd)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise DecryptError(detail or "openssl failed")
    return proc.stdout


def encrypt_binary(binary: bytes, password: str) -> str:
    """`gzip(binary)` → AES-256-CBC → base64. Returns gist-ready text."""
    ciphertext = _run((), gzip.compress(binary), password)
    return base64.b64encode(ciphertext).decode()


def decrypt_binary(blob_b64: str, password: str) -> bytes:
    """Reverse `encrypt_binary`: base64-decode → openssl -d → gunzip → raw binary."""
    try:
        ciphertext = base64.b64decode(blob_b64, validate=True)  # binascii.Error <: ValueError
    except ValueError as exc:
        msg = "encrypted blob is not valid base64"
        raise DecryptError(msg) from exc
    try:
        plaintext = _run(("-d",), ciphertext, password)
    except DecryptError as exc:
        # openssl's raw "bad decrypt" + libressl file path is noise — say what it means.
        msg = "decryption failed — wrong password or corrupt blob"
        raise DecryptError(msg) from exc
    try:
        return gzip.decompress(plaintext)  # BadGzipFile <: OSError
    except (OSError, EOFError) as exc:
        msg = "decryption produced invalid data — wrong password or corrupt blob"
        raise DecryptError(msg) from exc
