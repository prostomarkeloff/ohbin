<div align="center">

# ohbin

**Declare it once. Fetch it on demand. Pin it forever.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright](https://img.shields.io/badge/types-pyright-blue)](https://github.com/microsoft/pyright)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](https://github.com/astral-sh/ruff)

</div>

Any GitHub-release binary — linters, diff tools, formatters — declared in your `pyproject.toml` and fetched lazily on first use. `ohbin` downloads it, SHA256-verifies against a pinned hash, caches it per host, and execs it. One dev-dependency, any number of tools, zero per-tool wrapper packages to copy between repos.

```bash
uv add --dev git+https://github.com/prostomarkeloff/ohbin.git
```

```bash
uv run ohbin add BurntSushi/ripgrep --version 14.1.1 --name rg --binary rg
uv run ohbin run rg -- --version
#                       ^ first run: download + SHA256-verify + cache, then exec
#                         subsequent runs: straight to exec
```

---

## Why

uv can't install an arbitrary GitHub-release binary. `uv run <name>` resolves to a *Python* console-script entry point — static wheel metadata, fixed at build time. There is no hook for "read a config table and expose `<name>`".

So the usual workaround is a hand-rolled "download-on-first-use" wrapper package, one per tool, copied into every repo that needs it. That copy-paste is what `ohbin` deletes: the per-tool detail — repo, version, per-platform asset + checksum — moves into a `[tool.ohbin.tools.*]` table, and a single generic engine reads it.

| | hand-rolled wrapper per tool | `ohbin` |
|---|---|---|
| Packages to maintain | one per tool | one, total |
| New tool | a new wrapper package | one `ohbin add` |
| New repo | copy the wrapper files | one dev-dependency |
| Checksums | hand-pinned | auto-pinned by `add` |
| Integrity check | re-implemented per wrapper | shared, SHA256 |

---

## Add a tool

`ohbin add` hits the GitHub release, matches one asset per platform (linux/darwin × x86_64/arm64) by filename heuristics, pins each asset's SHA256 (from the GitHub API `digest`, else by downloading + hashing), and writes the result into your `pyproject.toml` — comments and formatting preserved (via `tomlkit`):

```bash
uv run ohbin add BurntSushi/ripgrep --version 14.1.1 --name rg --binary rg
uv run ohbin add sharkdp/fd --version 10.2.0
```

```toml
[tool.ohbin.tools.rg]
repo = "BurntSushi/ripgrep"
version = "14.1.1"
binary = "rg"                       # executable name inside the archive

[tool.ohbin.tools.rg.assets.darwin-arm64]
url = "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
sha256 = "..."
# ... one [..assets.<os>-<arch>] table per platform
```

`--name` sets the command when it should differ from the repo name; `--binary` sets the executable's name inside the archive when it differs from the command (ripgrep's repo is `ripgrep`, its binary is `rg`). Review what it matched — for an unusual naming scheme, fix an entry by hand. `add` uses the `gh` CLI when present (auth, rate limits), else the public REST API (`GH_TOKEN` / `GITHUB_TOKEN` honored).

---

## Run a tool

```bash
uv run ohbin run rg -- --version    # download-on-first-use, then exec
uv run ohbin which fd               # print the cached path (downloads if needed)
uv run ohbin list                   # show declared tools + resolved platforms
```

`run` execs the binary in place — signals and exit codes forward transparently, so it is drop-in for CI and Make. The `ohbin run` prefix disappears behind a variable:

```make
RG := uv run ohbin run rg --
search:; $(RG) TODO src/
```

---

## In-process use

When build tooling needs the binary's *path* — not to exec it — call the Python API. It reads the same manifest and returns the cached path:

```python
from ohbin import ensure

path = ensure("rg")   # -> pathlib.Path, downloaded + verified on first use
```

Manifest discovery walks up from CWD to the nearest `pyproject.toml` carrying `[tool.ohbin]`. Set `OHBIN_PYPROJECT` to point at a specific file — for CI, or callers running from an unrelated directory.

---

## How it works

```
ohbin run rg -- --version
        │
        ▼
  read [tool.ohbin.tools.rg] from pyproject          ← _manifest
        │
        ▼
  pick the asset for this os/arch  (darwin-arm64)     ← _platform
        │
        ▼
  cached?  ~/.cache/ohbin/rg/14.1.1/rg
   ├── yes ───────────────────────────────────┐
   └── no → flock → download → SHA256 verify   │     ← _engine
            → extract (tar / zip / raw) → chmod │
        ▼                                        ▼
  os.execv(binary, ["rg", "--version"])  ◄───────┘
```

- **Cache** — `$XDG_CACHE_HOME/ohbin/<tool>/<version>/<binary>` (`~/.cache/…` default). The version is in the path, so a bump is a fresh download that never collides with the old one.
- **Concurrency** — the first invocation downloads under a `flock`; the rest wait and reuse. Safe under xdist / parallel CI.
- **Integrity** — every download is SHA256-checked against the pinned hash *before* extraction. A mismatch aborts; nothing lands in the cache.
- **Exec** — `os.execv` replaces the process, so the tool owns stdin/stdout, signals, and the exit code.

---

## Limitations

- **POSIX only.** Uses `fcntl.flock` for the install lock; the engine imports `fcntl` at the top, so Windows fails on import. (The CI matrix keeps a Windows placeholder for when someone ports the lock.)
- **Heuristic matching.** `add` matches assets by OS/arch tokens in the filename and prefers `.tar.gz`. An unusual scheme may need a one-line manual fix to the written entry — by design, the manifest is the source of truth and `add` is just the convenience that fills it.
- **Four platforms.** linux/darwin × x86_64/arm64. Others (windows, musl variants, riscv) are not auto-resolved by `add`, though you can add their entries by hand.

---

## Development

```bash
git clone https://github.com/prostomarkeloff/ohbin
cd ohbin
uv sync

# ruff format + ruff check --fix + pyright
make lint-heavy

# unit suite (network-free: platform / matching / manifest / engine logic)
make test-full
```

CI runs the lint once, then an `os: [ubuntu, macos, windows] × python: [3.11, 3.12, 3.13, 3.14]` matrix.

---

<div align="center">

**Stop copying wrapper packages. Start declaring binaries.**

Made with 📦 by [@prostomarkeloff](https://github.com/prostomarkeloff)

</div>
