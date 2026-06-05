# ohbin

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

ohbin runs the binaries your project needs but can't `pip install`. You know the ones:
`ripgrep` ([or… can you?](https://pypi.org/project/ripgrep/)), [`find-dup-defs`](https://github.com/prostomarkeloff/find-dup-defs), [`oasdiff`](https://github.com/oasdiff/oasdiff), some linter
written in Rust that only ships as a GitHub release. uv
installs Python packages, and those aren't Python packages, so normally you're stuck either
telling everyone to install them by hand and watching the versions drift, or writing a little
download-and-verify wrapper package and copying it into every repo.

With ohbin you just write the tool down in your `pyproject.toml`. The first time you run it,
ohbin downloads it, checks it against a SHA256 you pinned, caches it, and runs it. One
dev-dependency, as many tools as you want.

It's a small thing on purpose, built for people who already live in uv. Your binaries get
pinned right next to your Python deps, in the same file, and run through the same flow.

What it gives you:

* binaries pinned to a version, pulled from GitHub releases
* a SHA256 per platform, checked before anything gets unpacked
* one dev-dependency, however many tools you declare
* a per-host cache that's safe to hit from parallel CI
* mostly stdlib (it shells out to `gh` and `openssl` only for the private-gist part)

## Installation

It's a dev dependency, so with uv:

```sh
uv add --dev git+https://github.com/prostomarkeloff/ohbin.git
```

## How to?

Say you want ripgrep. Point ohbin at the repo:

```sh
uv run ohbin add BurntSushi/ripgrep --version 14.1.1 --name rg --binary rg
```

This goes and looks at the release, finds the right asset for each platform, pins the SHA256s,
and writes a little table into your `pyproject.toml`. Your comments and formatting stay where
they are:

```toml
[tool.ohbin.tools.rg]
repo = "BurntSushi/ripgrep"
version = "14.1.1"
binary = "rg"
# add writes one [..assets.<os>-<arch>] table per platform under here, checksums and all
```

`--name` is what you'll type when it's different from the repo name (ripgrep becomes rg), and
`--binary` is the actual executable inside the archive. If add guesses an asset wrong, don't
fight it, the table is the source of truth, just fix the line.

Then run it:

```sh
uv run ohbin run rg -- --files     # first time: downloads, checks, caches, runs
uv run ohbin run rg -- TODO src/   # after that it just runs
```

ohbin hands the process straight over with execv, so the tool itself gets stdin, stdout,
signals and the exit code, exactly like you'd run it yourself. In a Makefile I usually hide
the prefix behind a variable:

```make
RG := uv run ohbin run rg --
search:; $(RG) TODO src/
```

`ohbin which fd` prints the cached path (and downloads it first if it has to), and `ohbin list`
shows what you've declared.

### Private binaries

Sometimes the binary isn't on a public release page. Maybe you built it yourself and you don't
want it in a repo at all. ohbin can ship it through a secret gist instead, encrypted with a
password:

```sh
uv run ohbin publish-gist ./dist/mytool --password "$PW"
```

That gzips it, encrypts it, and drops one gist file per platform plus a small index. Run it
from each platform's own machine, passing `--gist <id>` to add to the same gist. After that
it's just another tool:

```sh
uv run ohbin add-gist https://gist.github.com/you/ab12… --name mytool
uv run ohbin run --password "$PW" mytool -- --help
```

Why a gist and not a private repo? Because a gist isn't tied to a repo, and that's the whole
point. You don't commit the binary anywhere, you don't hand out repo access and tokens to
everyone who needs it, you just give them a link and a password. The link is unlisted and the
bytes are AES-256-CBC, so a leaked link on its own is nothing without the password. The
password goes to openssl over a file descriptor, never on the command line. To take access
away, delete the gist or change the password.

### From Python

If you want the path instead of running the thing:

```python
from ohbin import ensure

path = ensure("rg")   # a Path, downloaded and checked the first time
```

It finds your `pyproject.toml` by walking up from wherever you are. Set `OHBIN_PYPROJECT` if
you need to point it at a specific file, like in CI.

## How it works

Nothing clever. On `ohbin run rg`, it reads the rg table, works out your os and arch, and looks
for `~/.cache/ohbin/rg/14.1.1/rg`. If it's there, it runs it. If not, it downloads under a lock
(so two parallel runs don't race), checks the SHA256 before unpacking anything, extracts, and
runs. The version is in the cache path, so bumping it is just a fresh download that doesn't step
on the old one. Downloads retry with backoff, and a real 404 doesn't get mistaken for a flaky
network.

## Limitations

POSIX only for now, the locking uses `fcntl` so it won't even import on Windows. add
auto-resolves four platforms (linux and macOS, x86_64 and arm64); anything else (windows, musl,
riscv) you add to the table by hand and the engine runs it fine. Asset matching is just looking
at the os/arch words in the filename and preferring `.tar.gz`, so a weird naming scheme might
cost you a one-line fix.

## Development

```sh
git clone https://github.com/prostomarkeloff/ohbin
cd ohbin && uv sync

make lint-heavy   # ruff format + check + pyright
make test-full    # the network-free test suite
```

## License

MIT, see [LICENSE](LICENSE).

Made with 📦 by [prostomarkeloff](https://github.com/prostomarkeloff) and contributors.
