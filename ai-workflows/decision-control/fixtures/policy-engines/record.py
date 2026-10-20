#!/usr/bin/env python3
"""Record decision records whose external policy decisions came from the real OPA and Cedar tools.

Usage: python3 fixtures/policy-engines/record.py [--out DIR]

For every case below this script drives the installed ``decision-control`` CLI end to end:
it creates a ticket in a scratch SQLite queue, asks the CLI for the OPA input or Cedar
request of the proposal (``policy-input``), obtains the decision from the real tool, freezes it
(``freeze-opa`` / ``freeze-cedar``), submits it with the built-in policy, completes the review and
execution where the verdict allows, exports the record and replays it.

* OPA: ``opa run --server`` serves ``opa/bundle`` with console decision logs; each decision is
  one HTTP query to the local server. The decision-log lines are saved unchanged in
  ``opa/decision-log.jsonl`` and ``freeze-opa`` freezes the entry with the matching ``decision_id``.
* Cedar: ``freeze-cedar`` runs ``cedar authorize --verbose``; the raw output of the same command is
  saved in ``cedar/<case>.authorize.txt``.

The records contain real decision ids and timestamps, so a rerun produces different bytes; the
committed files are one recording. ``tool-versions.txt`` names the tools used. This script is
development tooling: it queries a loopback OPA server and is not part of the installed package.
Not run by the unit tests; ``conformance/generate.py`` reads the committed records.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT))

from decisioncontrol import __version__  # noqa: E402

POLICY = HERE / "policy.json"
BUNDLE = HERE / "opa" / "bundle"
CEDAR_POLICIES = HERE / "cedar" / "policies.cedar"
CEDAR_ENTITIES = HERE / "cedar" / "entities.json"

# (name, engine, ticket id, ticket department, ticket priority, proposal members, proposer, reviewer or None)
CASES = [
    ("opa-reassign-allow-executed", "opa", "T-201", "intake", None,
     {"action": "reassign_ticket", "destination": "support"}, "alice", None),
    ("opa-reassign-review-approved-executed", "opa", "T-202", "intake", None,
     {"action": "reassign_ticket", "destination": "engineering"}, "alice", "bob"),
    ("opa-reassign-denied", "opa", "T-203", "intake", None,
     {"action": "reassign_ticket", "destination": "support"}, "mallory", None),
    ("opa-priority-allow-executed", "opa", "T-204", "support", "normal",
     {"action": "set_ticket_priority", "priority": "high"}, "alice", None),
    ("cedar-reassign-allow-executed", "cedar", "T-211", "intake", None,
     {"action": "reassign_ticket", "destination": "support"}, "alice", None),
    ("cedar-reassign-denied", "cedar", "T-212", "intake", None,
     {"action": "reassign_ticket", "destination": "support"}, "mallory", None),
    ("cedar-reassign-forbidden", "cedar", "T-213", "legal", None,
     {"action": "reassign_ticket", "destination": "support"}, "alice", None),
    ("cedar-priority-review-approved-executed", "cedar", "T-214", "support", "high",
     {"action": "set_ticket_priority", "priority": "urgent"}, "alice", "bob"),
]


def cli(*args, db=None, expect=0):
    command = [sys.executable, "-m", "decisioncontrol"] + (["--db", str(db)] if db else []) + [str(a) for a in args]
    done = subprocess.run(command, cwd=PROJECT, env={**os.environ, "PYTHONPATH": str(PROJECT)},
                          capture_output=True, text=True)
    if done.returncode != expect:
        raise SystemExit(f"{' '.join(command)} exited {done.returncode}, expected {expect}\n{done.stderr}")
    return json.loads(done.stdout) if done.stdout.strip() else None


def versions():
    opa = subprocess.run(["opa", "version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    cedar = subprocess.run(["cedar", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    return [f"opa {opa.split(':', 1)[1].strip()}", cedar, f"decisioncontrol {__version__}",
            f"python {sys.version.split()[0]}"]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OpaServer:
    """``opa run --server`` over the bundle directory with decision logs on the console."""

    def __init__(self, log_path):
        self.port = free_port()
        self.log = open(log_path, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            ["opa", "run", "--server", "--addr", f"127.0.0.1:{self.port}", "--bundle", BUNDLE.name,
             "--set", "decision_logs.console=true", "--log-format", "json", "--skip-version-check"],
            cwd=BUNDLE.parent, stdout=self.log, stderr=subprocess.STDOUT)  # relative path: the bundle is named "bundle"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health?bundles=true", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        raise SystemExit("opa server did not become healthy")

    def decide(self, path, document):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/data/{path}", method="POST",
            data=json.dumps({"input": document}).encode(), headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=10).read())

    def close(self):
        time.sleep(0.5)  # console decision logs are written asynchronously
        self.process.terminate()
        self.process.wait()
        self.log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(HERE))
    out = Path(parser.parse_args(argv).out)
    records, raw_cedar = out / "records", out / "cedar"
    for directory in (records, raw_cedar, out / "opa"):
        directory.mkdir(parents=True, exist_ok=True)
    (out / "tool-versions.txt").write_text("\n".join(versions()) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        db = scratch / "queue.sqlite3"
        console = scratch / "opa-console.log"
        server = OpaServer(console)
        decision_ids = {}
        try:
            for name, engine, ticket, department, priority, members, proposer, reviewer in CASES:
                create = ["ticket-create", "--ticket-id", ticket, "--department", department]
                cli(*create, *(["--priority", priority] if priority else []), db=db)
                proposal = {"ticket_id": ticket, "probability": 0.95, "model": "recorded-fixture-not-a-provider",
                            "question_version": "routing-question-1", **members}
                (scratch / f"{name}.proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
                document = cli("policy-input", "--engine", engine, "--proposal", scratch / f"{name}.proposal.json",
                               "--proposed-by", proposer, db=db)
                if engine == "opa":
                    decision_ids[name] = server.decide("ticket/routing/decision", document)["decision_id"]
                else:
                    (scratch / f"{name}.request.json").write_text(json.dumps(document), encoding="utf-8")
                    raw = subprocess.run(
                        ["cedar", "authorize", "--policies", CEDAR_POLICIES, "--entities", CEDAR_ENTITIES,
                         "--request-json", scratch / f"{name}.request.json", "--verbose"],
                        capture_output=True, text=True)
                    (raw_cedar / f"{name}.authorize.txt").write_text(
                        f"exit {raw.returncode}\n{raw.stdout}", encoding="utf-8")
        finally:
            server.close()
        # Keep the decision-log lines OPA wrote, byte for byte, and nothing else from the console.
        lines = [line for line in console.read_text(encoding="utf-8").splitlines()
                 if '"type":"openpolicyagent.org/decision_logs"' in line]
        (out / "opa" / "decision-log.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        if len(lines) != len(decision_ids):
            raise SystemExit(f"expected {len(decision_ids)} decision log entries, found {len(lines)}")
        for name, engine, ticket, _, _, _, proposer, reviewer in CASES:
            frozen = scratch / f"{name}.external.json"
            if engine == "opa":
                cli("freeze-opa", "--decision-log", out / "opa" / "decision-log.jsonl",
                    "--decision-id", decision_ids[name], "--policy-dir", BUNDLE, "--out", frozen)
            else:
                cli("freeze-cedar", "--policies", CEDAR_POLICIES, "--entities", CEDAR_ENTITIES,
                    "--request", scratch / f"{name}.request.json", "--out", frozen)
            submitted = cli("submit", "--proposal", scratch / f"{name}.proposal.json", "--policy", POLICY,
                            "--proposed-by", proposer, "--external-policy", frozen, db=db)
            if reviewer:
                cli("approve", submitted["id"], "--reviewer", reviewer, "--note", "checked the frozen decision", db=db)
            if submitted["status"] != "DENIED" and (reviewer or submitted["status"] == "READY"):
                cli("execute", submitted["id"], db=db)
            target = records / f"{name}.json"
            if target.exists():
                target.unlink()
            cli("export", submitted["id"], "--out", target, db=db)
            replayed = cli("replay", "--record", target)
            print(f"{name}: {replayed['verdict']} {replayed['status']} "
                  f"{replayed['external_policy']['verification']}", file=sys.stderr)


if __name__ == "__main__":
    main()
