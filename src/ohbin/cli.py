"""Command-line interface: `ohbin run | add | which | list | publish-gist | add-gist`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ohbin import ensure
from ohbin._add import add_tool, local_pyproject
from ohbin._errors import OhbinError
from ohbin._gist import add_gist_tool, publish_gist
from ohbin._manifest import find_pyproject, load_tools


def _resolved_pyproject(explicit: Path | None, *, write: bool) -> Path:
    """Resolve the manifest a command will use and announce it (to stderr).

    Reading discovers upward; writing stays CWD-local. Either way we print the
    fully-resolved realpath so it's never a mystery which pyproject ohbin touched.
    """
    path = local_pyproject(explicit) if write else (explicit or find_pyproject())
    real = path.resolve()
    print(f"[ohbin] resolved pyproject as {real}", file=sys.stderr)
    return real


def _cmd_run(ns: argparse.Namespace) -> int:
    rest: list[str] = list(ns.args)
    if rest and rest[0] == "--":  # tolerate `ohbin run tool -- <args>`
        rest = rest[1:]
    pyproject = _resolved_pyproject(ns.pyproject_file, write=False)
    binary = ensure(ns.tool, pyproject=pyproject, password=ns.password)
    # execv replaces this process so signals + exit codes forward transparently.
    os.execv(str(binary), [ns.tool, *rest])
    return 0  # unreachable


def _cmd_add(ns: argparse.Namespace) -> int:
    pyproject = _resolved_pyproject(ns.pyproject_file, write=True)
    print(f"resolving {ns.repo}{f'@{ns.version}' if ns.version else ' (latest)'} ...")
    name, target = add_tool(
        repo=ns.repo,
        version=ns.version,
        name=ns.name,
        binary=ns.binary,
        pyproject=pyproject,
    )
    print(f"\nwrote [tool.ohbin.tools.{name}] to {target}")
    print(f"run it with:  uv run ohbin run {name} -- <args>")
    return 0


def _cmd_publish_gist(ns: argparse.Namespace) -> int:
    name = ns.name or Path(ns.path).name
    url = publish_gist(
        name=name,
        binary=ns.binary or name,
        binary_path=Path(ns.path),
        password=ns.password,
        platform_key=ns.platform,
        gist_ref=ns.gist,
        description=ns.desc or f"ohbin: encrypted {name}",
    )
    print(f"published {name} ({ns.platform or 'current platform'}) to {url}")
    print(f"add it with:  uv run ohbin add-gist {url}")
    return 0


def _cmd_add_gist(ns: argparse.Namespace) -> int:
    pyproject = _resolved_pyproject(ns.pyproject_file, write=True)
    name, target = add_gist_tool(
        gist_ref=ns.gist,
        name=ns.name,
        password=ns.password,
        pyproject=pyproject,
    )
    print(f"wrote [tool.ohbin.tools.{name}] (encrypted) to {target}")
    print(f"run it with:  uv run ohbin run --password <pw> {name} -- <args>")
    return 0


def _cmd_which(ns: argparse.Namespace) -> int:
    pyproject = _resolved_pyproject(ns.pyproject_file, write=False)
    print(ensure(ns.tool, pyproject=pyproject, password=ns.password))
    return 0


def _cmd_list(ns: argparse.Namespace) -> int:
    pyproject = _resolved_pyproject(ns.pyproject_file, write=False)
    tools = load_tools(pyproject)
    if not tools:
        print("no tools declared in [tool.ohbin.tools]")
        return 0
    width = max(len(n) for n in tools)
    for name, cfg in sorted(tools.items()):
        platforms = ", ".join(sorted(cfg["assets"]))
        print(f"{name:{width}}  {cfg['repo']}@{cfg['version']}  [{platforms}]")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ohbin", description=__doc__)

    # Shared across every subcommand: which manifest to read/write. Default None
    # keeps walk-up discovery (find_pyproject) + the OHBIN_PYPROJECT override; an
    # explicit path wins over both.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--pyproject-file",
        dest="pyproject_file",
        default=None,
        type=Path,
        metavar="PATH",
        help="manifest to read/write (default: nearest pyproject.toml with [tool.ohbin], or $OHBIN_PYPROJECT)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", parents=[common], help="download (if needed) and exec a declared tool")
    p_run.add_argument("tool")
    p_run.add_argument("--password", default=None, help="decrypt password for an encrypted tool")
    p_run.add_argument("args", nargs=argparse.REMAINDER, help="args forwarded to the tool")
    p_run.set_defaults(func=_cmd_run)

    p_add = sub.add_parser("add", parents=[common], help="resolve a GitHub release and write it into pyproject")
    p_add.add_argument("repo", help="GitHub repo as owner/name")
    p_add.add_argument("--version", default=None, help="release version/tag (default: latest)")
    p_add.add_argument("--name", default=None, help="command name (default: repo name)")
    p_add.add_argument("--binary", default=None, help="binary name in archive (default: cmd name)")
    p_add.set_defaults(func=_cmd_add)

    p_pub = sub.add_parser("publish-gist", help="encrypt a binary and upload it to a secret gist for one platform")
    p_pub.add_argument("path", help="path to the binary to encrypt + publish")
    p_pub.add_argument("--password", required=True, help="encryption password (keep it out of the gist)")
    p_pub.add_argument("--name", default=None, help="command name (default: binary filename)")
    p_pub.add_argument("--binary", default=None, help="executable name to run (default: command name)")
    p_pub.add_argument("--platform", default=None, help="platform key, e.g. linux-x86_64 (default: current)")
    p_pub.add_argument("--gist", default=None, help="existing gist id/url to add this platform to")
    p_pub.add_argument("--desc", default=None, help="gist description")
    p_pub.set_defaults(func=_cmd_publish_gist)

    p_addg = sub.add_parser("add-gist", parents=[common], help="resolve a published gist and write it into pyproject")
    p_addg.add_argument("gist", help="gist id or url produced by publish-gist")
    p_addg.add_argument("--name", default=None, help="command name (default: from the gist index)")
    p_addg.add_argument(
        "--password",
        default=None,
        help="store this decrypt password in pyproject (omit to pass --password at run time)",
    )
    p_addg.set_defaults(func=_cmd_add_gist)

    p_which = sub.add_parser("which", parents=[common], help="print the cached binary path (downloads if needed)")
    p_which.add_argument("tool")
    p_which.add_argument("--password", default=None, help="decrypt password for an encrypted tool")
    p_which.set_defaults(func=_cmd_which)

    p_list = sub.add_parser("list", parents=[common], help="list declared tools")
    p_list.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    ns = _build_parser().parse_args(argv)
    try:
        return ns.func(ns)
    except OhbinError as exc:  # expected, user-facing failures — no stack trace
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
