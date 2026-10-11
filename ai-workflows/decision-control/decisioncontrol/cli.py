"""JSON command line interface for trusted local operators."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .evidence import export_record, replay
from .models import DecisionError, Recommendation, RoutingPolicy, StateError
from .store import TicketStore


def _json_file(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def _parser():
    parser = argparse.ArgumentParser(prog="decision-control")
    parser.add_argument("--db", help="SQLite database path (required for storage commands)")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("ticket-create")
    create.add_argument("--ticket-id", required=True)
    create.add_argument("--department", required=True)
    for name in ("ticket-show", "show", "execute"):
        commands.add_parser(name).add_argument("id")
    submit = commands.add_parser("submit")
    submit.add_argument("--proposal", required=True)
    submit.add_argument("--policy", required=True)
    commands.add_parser("pending")
    for name in ("approve", "reject"):
        review = commands.add_parser(name)
        review.add_argument("id")
        review.add_argument("--reviewer", required=True)
        review.add_argument("--note", default="")
    export = commands.add_parser("export")
    export.add_argument("id")
    export.add_argument("--out")
    commands.add_parser("replay").add_argument("--record", required=True)
    commands.add_parser("demo").add_argument("--out", required=True)
    return parser


def _run(args):
    if args.command == "replay":
        return replay(_json_file(args.record))
    if args.command == "demo":
        from .demo import run_demo
        return run_demo(args.out)
    if not args.db:
        raise DecisionError("--db is required for storage commands")
    with TicketStore(args.db) as store:
        if args.command == "ticket-create":
            return store.create_ticket(args.ticket_id, args.department).to_dict()
        if args.command == "ticket-show":
            return store.get_ticket(args.id).to_dict()
        if args.command == "submit":
            return store.submit(Recommendation.from_dict(_json_file(args.proposal)),
                                RoutingPolicy.from_dict(_json_file(args.policy)))
        if args.command == "pending":
            return store.pending()
        if args.command == "show":
            return store.get(args.id)
        if args.command in ("approve", "reject"):
            return getattr(store, args.command)(args.id, args.reviewer, args.note)
        if args.command == "execute":
            return store.execute(args.id)
        if args.command == "export":
            envelope = export_record(store.get(args.id))
            if args.out:
                with Path(args.out).open("x", encoding="utf-8") as stream:
                    json.dump(envelope, stream, indent=2, allow_nan=False)
                    stream.write("\n")
            return envelope
    raise DecisionError("unknown command")


def main(argv=None):
    """Run commands; return 0, input/IO error 2, or lifecycle error 1."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        result = _run(args)
    except StateError as error:
        print(f"decision-control: {error}", file=sys.stderr)
        return 1
    except (DecisionError, OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error) as error:
        print(f"decision-control: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0
