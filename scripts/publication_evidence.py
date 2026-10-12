#!/usr/bin/env python3
"""Run existing project workflows and retain auditable local publication evidence.

No provider calls, release acceptance, rights clearance, or impact claim is made.
Python 3.11+; uv is required for RELIA's separate frozen environment.
"""
import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from workspace import ROOT, git, load_manifest, test_plan

PROJECTS = {"relia", "experiment-gate", "jev-decision", "decision-control"}
SCENARIOS = {"win": "SHIP", "flat": "HOLD", "guardrail-breach": "ROLLBACK",
             "regression": "ROLLBACK", "srm": "INVALID", "cuped": "HOLD",
             "early-regression": "ROLLBACK"}
THREADS = {key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                               "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def source_inventory(root):
    # This identifies the actual worktree, not merely HEAD. Private legacy notes
    # and root data are deliberately outside the four-project verification scope.
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                "--", "ai-workflows", "scripts", ".github/workflows", "workspace.json", "Makefile").split("\0")
    inventory = {}
    for name in sorted(set(paths) - {""}):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"source must be a regular existing file: {name}")
        inventory[name] = sha256(path)
    return inventory


def observe(out):
    """Require actual adverse dispositions and queue state, not just exit zero."""
    def read(name):
        return json.loads((out / name).read_text(encoding="utf-8"))

    first = read("relia/repro-a/results.json")
    second = read("relia/repro-b/results.json")
    for name in ("results.json", "MANIFEST.json"):
        if (out / "relia/repro-a" / name).read_bytes() != (out / "relia/repro-b" / name).read_bytes():
            raise ValueError(f"RELIA repeat mismatch: {name}")
    for result in (first, second):
        if result["gate_report"]["release_decision"] != "PASS":
            raise ValueError("RELIA primary gates did not pass")
        if result["incremental_cycle"]["decision"] != "REJECT_UPDATE_KEEP_CURRENT_REFERENCE":
            raise ValueError("RELIA did not retain the rejected update")
    scenarios = {name: read(f"experiment-gate/{name}/decision.json")["decision"] for name in SCENARIOS}
    if scenarios != SCENARIOS:
        raise ValueError(f"unexpected experiment dispositions: {scenarios}")
    jev = read("jev-decision/evaluation.json")
    if jev["source"] != "replay" or jev["status"] != "PASS":
        raise ValueError("Jev explicit fixture gate failed or was not replayed")
    ungated = read("jev-ungated/evaluation.json")
    if ungated["status"] != "UNGATED":
        raise ValueError("Jev ungated demonstration was mislabeled")
    demo = read("decision-control/summary.json")
    expected = {"allow": ("ALLOW", "EXECUTED", "support", 1),
                "review": ("REVIEW", "EXECUTED", "engineering", 1),
                "deny": ("DENY", "DENIED", "intake", 0),
                "abstain": ("ABSTAIN", "ABSTAINED", "intake", 0)}
    for name, (verdict, status, department, revision) in expected.items():
        decision, ticket = demo["decisions"][name], demo["tickets"][name]
        if (decision["verdict"], decision["status"], ticket["department"], ticket["revision"]) != (verdict, status, department, revision):
            raise ValueError(f"unexpected decision-control state: {name}")
    if not demo["repeat_execution_same_record"] or not demo["reopened_before_approval"]:
        raise ValueError("decision-control persistence/idempotency failed")
    adverse = read("decision-control-gated/evaluation.json")["report"]
    if adverse["disposition"] != "FAIL":
        raise ValueError("adverse decision-control fixture did not fail")
    return {"relia": {"primary": first["gate_report"]["release_decision"],
                      "update": first["incremental_cycle"]["decision"],
                      "repeat_bytes_match": True, "summary": first["summary"]},
            "experiment-gate": scenarios,
            "jev-decision": {"gated": jev["status"], "ungated": ungated["status"],
                             "cases": jev["cases"], "origin": "hand-authored bundled responses; no provider call"},
            "decision-control": {"states": {name: list(values) for name, values in expected.items()},
                                 "adverse_gate": adverse["disposition"], "execution": "local SQLite only"}}


def render(record):
    lines = ["# Portfolio local verification report", "",
             f"Recorded UTC: {record['recorded_at']}",
             f"**Verification: {'PASS' if record['verified'] else 'FAIL'}**", "",
             "Local author-side software verification, not independent reproduction, model quality,",
             "production impact, release acceptance, rights clearance, or NIW eligibility.", "",
             f"Source HEAD (not a claim of a clean checkout): `{record['head']}`.",
             "Exact verified project/tooling worktree file hashes are in `EVIDENCE.json`.",
             "Legacy `src/` research is outside this command's verification scope.", "",
             "| Step | Actual exit | Expected exit | Seconds | Log |", "| --- | ---: | ---: | ---: | --- |"]
    for step in record["steps"]:
        lines.append(f"| {step['name']} | {step['exit']} | {step['expected_exit']} | {step['seconds']:.2f} | `{step['log']}` |")
    if record.get("error"):
        lines.extend(["", f"Failure retained: {record['error']}"])
    if record.get("observations"):
        lines.extend(["", "## Observed outcomes", "", "```json",
                      json.dumps(record["observations"], indent=2, sort_keys=True), "```"])
    lines.extend(["", "Artifact SHA-256 values are retained in `EVIDENCE.json`; verify with",
                  "`python3 scripts/publication_evidence.py --verify /path/to/evidence`.",
                  "Hashes detect later changes, not forgery or author identity.", ""])
    return "\n".join(lines)


def collect(root, out):
    manifest = load_manifest(root)
    actual = {name for name, component in manifest["components"].items() if component["kind"] == "project"}
    if actual != PROJECTS:
        raise ValueError(f"update the evidence protocol for registered projects: {sorted(actual)}")
    if out == root or root in out.parents:
        raise ValueError("--out must be outside the source repository")
    out.mkdir()  # Refuse existing paths, including old failures.
    (out / "logs").mkdir()
    record = {"schema_version": 1, "recorded_at": datetime.now(timezone.utc).isoformat(),
              "head": git(root, "rev-parse", "HEAD").strip(),
              "python": sys.version, "platform": platform.platform(),
              "scope": sorted(PROJECTS | {"workspace-tooling"}),
              "source_files": source_inventory(root), "steps": [], "verified": False}

    def step(name, cwd, argv, expected=0, env=None):
        log = f"logs/{len(record['steps']) + 1:02d}-{name}.txt"
        start = time.monotonic()
        print(f"[{name}] {shlex.join(map(str, argv))}", flush=True)
        with (out / log).open("wb") as stream:
            try:
                result = subprocess.run(argv, cwd=cwd, env={**os.environ, **(env or {})},
                                        stdout=stream, stderr=subprocess.STDOUT, check=False)
                code = result.returncode
            except OSError as error:
                stream.write(str(error).encode("utf-8"))
                code = 127
        record["steps"].append({"name": name, "cwd": str(cwd.relative_to(root)) or ".",
                                "argv": list(map(str, argv)), "exit": code, "expected_exit": expected,
                                "seconds": time.monotonic() - start, "log": log})
        if code != expected:
            raise ValueError(f"{name} exited {code}, expected {expected}; see {log}")

    try:
        for name, cwd, argv, defaults, _ in test_plan(root, manifest, sorted(PROJECTS - {"relia"}) + ["workspace-tooling"]):
            step(f"test-{name}", cwd, argv, env=defaults)
        # RELIA's existing helper owns frozen setup, tests, two runs and environment capture.
        relia = root / manifest["components"]["relia"]["path"]
        step("relia-reproduce", relia, ["bash", "scripts/reproduce.sh", str(out / "relia")], env=THREADS)
        step("relia-export-tests", root, [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_export_relia.py"])
        expgate = root / manifest["components"]["experiment-gate"]["path"]
        step("experiment-scenarios", expgate, [sys.executable, "-m", "expgate.run", "--all-scenarios", "--out", str(out / "experiment-gate")])
        jev = root / manifest["components"]["jev-decision"]["path"]
        replay = [sys.executable, "-m", "jevdecision.evaluation", "--questions", "examples/support-ticket.json",
                  "--cases", "examples/support-ticket-cases.jsonl", "--responses", "examples/support-ticket-responses.jsonl"]
        step("jev-gated-replay", jev, replay + ["--require", "examples/support-ticket-requirements.json", "--out", str(out / "jev-decision")])
        step("jev-ungated-replay", jev, replay + ["--out", str(out / "jev-ungated")], expected=3)
        control = root / manifest["components"]["decision-control"]["path"]
        step("decision-control-demo", control, [sys.executable, "-m", "decisioncontrol", "demo", "--out", str(out / "decision-control")])
        step("decision-control-adverse", control, [sys.executable, "-m", "decisioncontrol", "evaluate", "--cases", "examples/evaluation-cases.jsonl",
                                                  "--policy", "examples/policy.json", "--require", "examples/evaluation-requirements.json",
                                                  "--out", str(out / "decision-control-gated")], expected=1)
        step("decision-control-replay", control, [sys.executable, "-m", "decisioncontrol", "replay-evaluation",
                                                 "--record", str(out / "decision-control-gated/evaluation.json")])
        record["observations"] = observe(out)
        if source_inventory(root) != record["source_files"]:
            raise ValueError("source changed during verification; retain this attempt and run a new snapshot")
        record["verified"] = True
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        record["error"] = str(error)
    (out / "VERIFICATION.md").write_text(render(record), encoding="utf-8")
    record["artifacts"] = {str(path.relative_to(out)): sha256(path) for path in sorted(out.rglob("*")) if path.is_file()}
    save(out / "EVIDENCE.json", record)
    print(f"{'PASS' if record['verified'] else 'FAIL'} {out / 'VERIFICATION.md'}", flush=True)
    return 0 if record["verified"] else 1


def verify(out):
    record = json.loads((out / "EVIDENCE.json").read_text(encoding="utf-8"))
    if not record["verified"]:
        raise ValueError("record describes an unsuccessful verification")
    for name, digest in record["artifacts"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe artifact path: {name}")
        path = out / relative
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError(f"artifact missing or changed: {name}")
    print(f"PASS {len(record['artifacts'])} retained artifact hashes; origin/identity unverified")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--out", type=Path, help="new external evidence directory; parent must exist")
    modes.add_argument("--verify", type=Path, help="verify a previously retained evidence directory")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ required; project runtimes remain independent")
    try:
        return verify(args.verify.resolve()) if args.verify else collect(ROOT, args.out.resolve())
    except (ValueError, KeyError, OSError) as error:
        print(f"publication-evidence: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
