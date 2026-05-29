"""Allow `python -m ohbin`."""

from __future__ import annotations

import sys

from ohbin.cli import main

if __name__ == "__main__":
    sys.exit(main())
