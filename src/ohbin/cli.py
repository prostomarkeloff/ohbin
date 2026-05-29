"""Command-line interface: `ohbin run | add | which | list`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ohbin import ensure
from ohbin._add import add_tool
from ohbin._manifest import load_tools


def _cmd_run(ns: argparse.Namespace) -> int:
    rest: list[str] = list(ns.args)
    if rest and rest[0] == "--":  # tolerate `ohbin run tool -- <args>`
        rest = rest[1:]
    binary = ensure(ns.tool)
    # execv replaces this process so signals + exit codes forward transparently.
    os.execv(str(binary), [ns.tool, *rest])
    return 0  # unreachable


def _cmd_add(ns: argparse.Namespace) -> int:
    print(f"resolving {ns.repo}{f'@{ns.version}' if ns.version else ' (latest)'} ...")
    name, target = add_tool(
        repo=ns.repo,
        version=ns.version,
        name=ns.name,
        binary=ns.binary,
        pyproject=ns.pyproject,
    )
    print(f"\nwrote [tool.ohbin.tools.{name}] to {target}")
    print(f"run it with:  uv run ohbin run {name} -- <args>")
    return 0


def _cmd_which(ns: argparse.Namespace) -> int:
    print(ensure(ns.tool))
    return 0


def _cmd_list(_ns: argparse.Namespace) -> int:
    tools = load_tools()
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
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="download (if needed) and exec a declared tool")
    p_run.add_argument("tool")
    p_run.add_argument("args", nargs=argparse.REMAINDER, help="args forwarded to the tool")
    p_run.set_defaults(func=_cmd_run)

    p_add = sub.add_parser("add", help="resolve a GitHub release and write it into pyproject")
    p_add.add_argument("repo", help="GitHub repo as owner/name")
    p_add.add_argument("--version", default=None, help="release version/tag (default: latest)")
    p_add.add_argument("--name", default=None, help="command name (default: repo name)")
    p_add.add_argument("--binary", default=None, help="binary name in archive (default: cmd name)")
    p_add.add_argument("--pyproject", default=None, type=Path, help="target pyproject.toml")
    p_add.set_defaults(func=_cmd_add)

    p_which = sub.add_parser("which", help="print the cached binary path (downloads if needed)")
    p_which.add_argument("tool")
    p_which.set_defaults(func=_cmd_which)

    p_list = sub.add_parser("list", help="list declared tools")
    p_list.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    ns = _build_parser().parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
