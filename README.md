<div align="center">

# ohbin

**Declare binaries, not wrapper packages.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright](https://img.shields.io/badge/types-pyright-blue)](https://github.com/microsoft/pyright)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](https://github.com/astral-sh/ruff)

</div>

Your project needs `ripgrep`, or `oasdiff`, or some Rust linter that ships only as a GitHub release. Python can't install it. So you either tell every developer "go install it yourself" — and watch versions drift and CI break — or you hand-write a download-and-verify wrapper package, and copy it into every repo, for every tool.

`ohbin` deletes that. Declare the tool in `pyproject.toml`; it's fetched on first use, SHA256-checked against a pinned hash, cached per host, and exec'd. One dev-dependency. Any number of tools.

```bash
uv add --dev git+https://github.com/prostomarkeloff/ohbin.git
```

---

## Before & After

**❌ The hand-rolled wrapper — a whole package, per tool, copied into every repo**

```python
# a download-and-verify wrapper · ~180 lines · written again for the next tool
_PLATFORM_ASSETS = {
    ("linux",  "x86_64"): _Asset("ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz", "4cf9f2741e6c…"),
    ("darwin", "arm64"):  _Asset("ripgrep-14.1.1-aarch64-apple-darwin.tar.gz",      "24ad767777…"),
    # ...two more, each SHA hand-copied from the release page
}

def ensure_binary() -> Path:
    asset = _resolve_asset()                      # platform.machine() guesswork
    with _flock(cache / ".lock"):                 # concurrency, if you bother
        _download(url, archive)                   # urllib + redirects (+ retries, if you bother)
        _verify_checksum(archive, asset.sha256)   # hashlib
        _extract(archive, binary)                 # tarfile, atomic rename
    return binary
# + a wheel shim, [project.scripts], and a [tool.uv.sources] entry — in every repo
```

**✅ ohbin — one dev-dependency, one table per tool**

```bash
uv run ohbin add BurntSushi/ripgrep --version 14.1.1 --name rg --binary rg
```

```toml
[tool.ohbin.tools.rg]
repo = "BurntSushi/ripgrep"
version = "14.1.1"
binary = "rg"
# + one [..assets.<os>-<arch>] table per platform — written by `add`, checksums and all
```

```bash
uv run ohbin run rg -- TODO src/
```

One is **a package you maintain**. The other is **a table you declare**.

---

## Why a wrapper at all?

uv can't install an arbitrary GitHub-release binary — and that's not an oversight. `uv run <name>` resolves to a Python console-script entry point, which is *static wheel metadata* baked at build time. There is no hook that reads a config table and conjures a command. So *something* has to bridge "a binary on a release page" to "a command in your venv."

The honest choices are **(a)** a wrapper package per tool — the duplication above — or **(b)** one generic engine that reads a manifest. `ohbin` is (b): the per-tool detail (repo, version, per-platform asset + checksum) lives in `[tool.ohbin.tools.*]`, and a single mostly-stdlib engine does download / verify / cache / exec for all of them.

---

## `ohbin add` does the boring part

Point it at a repo. It resolves the release, matches one asset per platform, pins each SHA256 (from the GitHub API `digest`, else by downloading and hashing), and writes it into your pyproject — comments and formatting intact, via `tomlkit`:

```console
$ uv run ohbin add BurntSushi/ripgrep --version 14.1.1 --name rg --binary rg
resolving BurntSushi/ripgrep@14.1.1 ...
  + linux-x86_64    ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz   (downloaded+hashed)
  + linux-aarch64   ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz   (downloaded+hashed)
  + darwin-x86_64   ripgrep-14.1.1-x86_64-apple-darwin.tar.gz         (downloaded+hashed)
  + darwin-arm64    ripgrep-14.1.1-aarch64-apple-darwin.tar.gz        (downloaded+hashed)

wrote [tool.ohbin.tools.rg] to pyproject.toml
```

`--name` sets the command when it differs from the repo (`ripgrep` → `rg`); `--binary` sets the executable's name inside the archive. Odd naming scheme? The manifest is the source of truth — `add` just fills it; fix an entry by hand. Uses the `gh` CLI when present (auth, rate limits), else the public REST API (`GH_TOKEN` / `GITHUB_TOKEN` honored).

---

## `ohbin run` does the rest

```bash
uv run ohbin run rg -- --files       # first run: download → verify → cache → exec
uv run ohbin run rg -- TODO src/     # next runs: straight to exec
uv run ohbin which fd                 # print the cached path (downloads if needed)
uv run ohbin list                     # declared tools + resolved platforms
```

`run` replaces the process with `execv`, so the tool owns stdin/stdout, signals, and the exit code — drop-in for CI and Make, where the prefix disappears behind a variable:

```make
RG := uv run ohbin run rg --
search:; $(RG) TODO src/
```

---

## How it works

```
ohbin run rg -- --version
   │
   ├─ read [tool.ohbin.tools.rg]                  _manifest   (walks up to your pyproject)
   ├─ pick the asset for this os/arch             _platform   (→ darwin-arm64)
   │
   ├─ cached?  ~/.cache/ohbin/rg/14.1.1/rg
   │    ├─ yes ───────────────────────────────┐
   │    └─ no → flock → download → SHA256 ✓    │   _engine
   │              → extract (tar/zip/raw) → +x │
   ▼                                            ▼
  os.execv(binary, ["rg", "--version"])  ◄──────┘
```

- **Cache** — `$XDG_CACHE_HOME/ohbin/<tool>/<version>/<binary>` (`~/.cache/…` default). The version is in the path, so a bump is a clean new download that never collides with the old one.
- **Concurrency** — the first caller downloads under a `flock`; the rest wait and reuse. Safe under xdist / parallel CI.
- **Integrity** — SHA256-checked *before* extraction. A mismatch aborts; nothing partial lands in the cache.

---

## It survives the network

Release assets live behind CDNs that hiccup; `gh` rate-limits; DNS blips mid-clone. Every release lookup and every download retries with exponential backoff — and a real **404 is never mistaken for a transient failure** (the bug that makes naive wrappers cry "release not found" on a dropped packet):

```console
$ uv run ohbin add BurntSushi/ripgrep --version 14.1.1
ohbin: download failed (attempt 1/4): … Connection reset by peer; retrying in 0.5s
  + linux-x86_64    ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz   (downloaded+hashed)
  …
```

That is a real line from a live run — a reset connection, recovered, no fuss.

---

## In-process

Need the binary's *path*, not to exec it? Same manifest, one call:

```python
from ohbin import ensure

path = ensure("rg")   # -> pathlib.Path, downloaded + verified on first use
```

Discovery walks up from CWD to the nearest `pyproject.toml` carrying `[tool.ohbin]`; set `OHBIN_PYPROJECT` to point at a specific file (CI, or callers running from an unrelated directory).

---

## Hand-rolled wrapper vs `ohbin`

| | wrapper package per tool | `ohbin` |
|---|---|---|
| Packages to maintain | one per tool | one, total |
| New tool | write a new package | `ohbin add` |
| New repo | copy the files | one dev-dependency |
| Checksums | hand-pinned from the release page | auto-pinned by `add` |
| Network resilience | re-implemented (or skipped) | retry + backoff, built in |
| Integrity check | re-implemented per wrapper | shared, SHA256 |

---

## Limitations

- **POSIX only.** The install lock is `fcntl.flock`; the engine imports `fcntl` at the top, so Windows fails on import.
- **Four platforms.** linux/darwin × x86_64/arm64 are what `add` auto-resolves. Others (windows, musl, riscv) you add by hand — the engine runs them fine.
- **Heuristic matching.** `add` matches assets by OS/arch tokens in the filename and prefers `.tar.gz`. The manifest is the source of truth; an unusual scheme is a one-line fix.

---

## Development

```bash
git clone https://github.com/prostomarkeloff/ohbin
cd ohbin && uv sync

make lint-heavy     # ruff format + ruff check --fix + pyright
make test-full      # 44 network-free tests (platform / matching / manifest / engine / retry)
```

CI runs the lint once, then an `os: [ubuntu, macos, windows] × python: [3.11, 3.12, 3.13, 3.14]` matrix.

---

<div align="center">

**Stop copying wrapper packages. Start declaring binaries.**

Made with 📦 by [@prostomarkeloff](https://github.com/prostomarkeloff)

</div>
