"""JSON command line interface for trusted local operators."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ._outputs import staged_output
from .evidence import RecordMismatch, export_record, replay
from .evaluation import evaluate_cases, load_cases, replay_evaluation, write_evaluation
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
    submit.add_argument("--proposed-by", required=True)
    commands.add_parser("pending")
    for name in ("approve", "reject", "cancel"):
        review = commands.add_parser(name)
        review.add_argument("id")
        review.add_argument("--reviewer", required=True)
        review.add_argument("--note", default="", required=name == "cancel")
    export = commands.add_parser("export")
    export.add_argument("id")
    export.add_argument("--out")
    commands.add_parser("replay").add_argument("--record", required=True)
    commands.add_parser("demo").add_argument("--out", required=True)
    evaluation = commands.add_parser("evaluate", help="score supplied labeled recommendations; execute nothing")
    evaluation.add_argument("--cases", required=True, help="labeled JSON Lines cases")
    evaluation.add_argument("--policy", required=True)
    evaluation.add_argument("--require", help="metric/support gates; omitted means UNGATED")
    evaluation.add_argument("--out", required=True, help="new or empty output directory")
    commands.add_parser("replay-evaluation").add_argument("--record", required=True)
    return parser


def _run(args):
    if args.command == "replay":
        return replay(_json_file(args.record))
    if args.command == "demo":
        from .demo import run_demo
        return run_demo(args.out)
    if args.command == "evaluate":
        requirements = _json_file(args.require) if args.require else None
        report = evaluate_cases(load_cases(args.cases), RoutingPolicy.from_dict(_json_file(args.policy)), requirements)
        return write_evaluation(report, args.out)
    if args.command == "replay-evaluation":
        return replay_evaluation(_json_file(args.record))
    if not args.db:
        raise DecisionError("--db is required for storage commands")
    with TicketStore(args.db) as store:
        if args.command == "ticket-create":
            return store.create_ticket(args.ticket_id, args.department).to_dict()
        if args.command == "ticket-show":
            return store.get_ticket(args.id).to_dict()
        if args.command == "submit":
            return store.submit(Recommendation.from_dict(_json_file(args.proposal)),
                                RoutingPolicy.from_dict(_json_file(args.policy)), args.proposed_by)
        if args.command == "pending":
            return store.pending()
        if args.command == "show":
            return store.get(args.id)
        if args.command in ("approve", "reject", "cancel"):
            return getattr(store, args.command)(args.id, args.reviewer, args.note)
        if args.command == "execute":
            return store.execute(args.id)
        if args.command == "export":
            envelope = export_record(store.get(args.id))
            if args.out:
                with staged_output(args.out, directory=False) as staging:
                    with staging.open("x", encoding="utf-8") as stream:
                        json.dump(envelope, stream, indent=2, allow_nan=False)
                        stream.write("\n")
            return envelope
    raise DecisionError("unknown command")


def main(argv=None):
    """Return 0, invalid input/IO 2, or blocked lifecycle/evaluation gate 1."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        result = _run(args)
    except RecordMismatch as error:
        print(f"decision-control: {error}", file=sys.stderr)
        return 1 if args.command in ("replay", "replay-evaluation") else 2
    except StateError as error:
        print(f"decision-control: {error}", file=sys.stderr)
        return 1
    except (DecisionError, OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error) as error:
        print(f"decision-control: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.command == "pending" and result.skipped:
        for row in result.skipped:
            print(f"decision-control: skipped corrupt decision {row['id']}: {row['error']}", file=sys.stderr)
        return 1
    if args.command == "execute" and result["status"] == "STALE":
        return 1
    return 1 if args.command == "evaluate" and result["report"]["disposition"] == "FAIL" else 0
