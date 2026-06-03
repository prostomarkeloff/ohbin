"""Round-trip + failure behaviour of the openssl-backed gzip+AES blob format."""

from __future__ import annotations

import shutil

import pytest

from ohbin._crypto import DecryptError, decrypt_binary, encrypt_binary

openssl_required = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")


@openssl_required
def test_round_trip_preserves_arbitrary_bytes() -> None:
    data = bytes(range(256)) * 200  # null bytes + every byte value, non-trivial size
    assert decrypt_binary(encrypt_binary(data, "s3cret"), "s3cret") == data


@openssl_required
def test_blob_is_ascii_text() -> None:
    # Gists are text-only; the published blob must survive as plain ASCII.
    blob = encrypt_binary(b"\x00\x01\x02\xff binary payload", "pw")
    blob.encode("ascii")  # raises if not pure ASCII


@openssl_required
def test_wrong_password_is_rejected() -> None:
    blob = encrypt_binary(b"the real binary", "correct-horse")
    with pytest.raises(DecryptError):
        decrypt_binary(blob, "battery-staple")


@openssl_required
def test_corrupt_blob_is_rejected() -> None:
    with pytest.raises(DecryptError):
        decrypt_binary("not even base64 $$$", "pw")
