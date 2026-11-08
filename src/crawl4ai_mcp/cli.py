from __future__ import annotations

import argparse
import sys

from .credentials import data_dir_from_env, load_connection


def cmd_info(_: argparse.Namespace) -> int:
    data_dir = data_dir_from_env()
    conn = load_connection(data_dir)
    if not conn:
        print(
            "No connection.json found. Start the server once with "
            "`crawl4ai-mcp serve` (requires CDP_URL), then retry.",
            file=sys.stderr,
        )
        return 1
    print(f"url: {conn.get('url', '')}")
    print(f"api_key: {conn.get('api_key', '')}")
    print(f"authorization: {conn.get('authorization', '')}")
    print(f"transport: {conn.get('transport', '')}")
    print(f"connection_file: {data_dir / 'connection.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crawl4ai-mcp")
    sub = parser.add_subparsers(dest="command", required=True)
    info = sub.add_parser("info", help="Show persisted MCP connection details")
    info.set_defaults(func=cmd_info)
    return parser


def register_serve(parser: argparse.ArgumentParser, handler) -> None:
    sub = next(
        action
        for action in parser._subparsers._group_actions  # type: ignore[attr-defined]
        if action.dest == "command"
    )
    serve = sub.add_parser("serve", help="Run the Streamable HTTP MCP server")
    serve.set_defaults(func=handler)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        from .server import cmd_serve

        register_serve(parser, cmd_serve)
    except ImportError:
        pass
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
