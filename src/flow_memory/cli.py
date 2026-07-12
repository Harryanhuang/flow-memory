"""Standalone command-line interface for Flow Memory."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flow-memory")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize the configured storage backend")

    items = commands.add_parser("items", help="Manage memory items").add_subparsers(
        dest="action", required=True
    )
    add = items.add_parser("add")
    add.add_argument("scope")
    add.add_argument("kind")
    add.add_argument("content")
    add.add_argument("--layer", default="episode")
    add.add_argument("--importance", type=int, default=5)
    add.add_argument("--status", default="confirmed")
    listing = items.add_parser("list")
    listing.add_argument("--scope")
    listing.add_argument("--kind")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=100)
    get = items.add_parser("get")
    get.add_argument("memory_id")

    search = commands.add_parser("search", help="Search confirmed memories")
    search.add_argument("query")
    search.add_argument("--scope")
    search.add_argument("--kind")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--hybrid", action="store_true")

    profile = commands.add_parser("profile", help="Manage user profile").add_subparsers(
        dest="action", required=True
    )
    profile_set = profile.add_parser("set")
    profile_set.add_argument("key")
    profile_set.add_argument("value")
    profile_get = profile.add_parser("get")
    profile_get.add_argument("key")
    profile_list = profile.add_parser("list")
    profile_list.add_argument("--prefix")
    profile_list.add_argument("--limit", type=int, default=100)

    candidate = commands.add_parser("candidate", help="Add a candidate")
    candidate.add_argument("scope")
    candidate.add_argument("kind")
    candidate.add_argument("content")
    candidate.add_argument("--reason", default="")
    candidates = commands.add_parser("candidates", help="List candidates")
    candidates.add_argument("--scope")
    candidates.add_argument("--status", default="proposed")
    candidates.add_argument("--limit", type=int, default=50)
    promote = commands.add_parser("promote", help="Promote a candidate")
    promote.add_argument("candidate_id")
    promote.add_argument("--reviewer", default="")
    reject = commands.add_parser("reject", help="Reject a candidate")
    reject.add_argument("candidate_id")
    reject.add_argument("--reason", default="")

    pin = commands.add_parser("pin", help="Pin a memory")
    pin.add_argument("memory_id")
    unpin = commands.add_parser("unpin", help="Unpin a memory")
    unpin.add_argument("memory_id")
    dashboard = commands.add_parser("dashboard", help="Render memory health")
    dashboard.add_argument("--days", type=int, default=7)
    stats = commands.add_parser("stats", help="Render usage statistics")
    stats.add_argument("--days", type=int, default=7)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        from flow_memory.storage import get_backend

        backend = get_backend()
        backend.init_schema()
        print(f"Initialized {backend.dialect()} storage")
    elif args.command == "items":
        from flow_memory.items import add_memory, get_memory, list_memories

        if args.action == "add":
            print(
                add_memory(
                    args.scope,
                    args.kind,
                    args.content,
                    layer=args.layer,
                    importance=args.importance,
                    status=args.status,
                )
            )
        elif args.action == "get":
            _print(get_memory(args.memory_id))
        else:
            _print(
                list_memories(
                    scope=args.scope,
                    kind=args.kind,
                    status=args.status,
                    limit=args.limit,
                )
            )
    elif args.command == "search":
        from flow_memory.search import hybrid_search, search_memories

        if args.hybrid:
            result = hybrid_search(
                args.query, scope=args.scope, kind=args.kind, limit=args.limit
            )
        else:
            result = search_memories(
                args.query,
                scope=args.scope,
                kind=args.kind,
                status="confirmed",
                limit=args.limit,
            )
        _print(result)
    elif args.command == "profile":
        from flow_memory.user_profile import get_profile, list_profile, set_profile

        if args.action == "set":
            set_profile(args.key, args.value)
            print(args.key)
        elif args.action == "get":
            _print(get_profile(args.key))
        else:
            _print(list_profile(prefix=args.prefix, limit=args.limit))
    elif args.command == "candidate":
        from flow_memory.candidates import add_candidate

        print(
            add_candidate(
                scope=args.scope,
                kind=args.kind,
                content=args.content,
                source_type="manual",
                reason=args.reason,
            )
        )
    elif args.command == "candidates":
        from flow_memory.candidates import list_candidates

        _print(list_candidates(scope=args.scope, status=args.status, limit=args.limit))
    elif args.command == "promote":
        from flow_memory.candidates import promote_candidate

        print(promote_candidate(args.candidate_id, reviewer=args.reviewer))
    elif args.command == "reject":
        from flow_memory.candidates import reject_candidate

        _print({"rejected": reject_candidate(args.candidate_id, reason=args.reason)})
    elif args.command in {"pin", "unpin"}:
        from flow_memory.items import pin_memory, unpin_memory

        operation = pin_memory if args.command == "pin" else unpin_memory
        _print({args.command: operation(args.memory_id)})
    elif args.command == "dashboard":
        from flow_memory.dashboard import render_dashboard

        print(render_dashboard(days=args.days))
    elif args.command == "stats":
        from flow_memory.memory.usage_stats import get_usage_stats, render_stats_report

        print(render_stats_report(get_usage_stats(days=args.days)))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(_parser().parse_args(argv))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"flow-memory: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
