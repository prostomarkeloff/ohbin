"""Common base for all expected, user-facing ohbin failures.

The CLI catches `OhbinError` and prints `error: <message>` without a stack trace;
anything else propagates as a real (unexpected) crash. Library callers can likewise
`except ohbin.OhbinError` to handle every anticipated failure in one place.
"""

from __future__ import annotations


class OhbinError(RuntimeError):
    """Base class for anticipated ohbin failures (bad manifest, checksum, decrypt, …)."""
