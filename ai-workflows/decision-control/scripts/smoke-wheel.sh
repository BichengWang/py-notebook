#!/usr/bin/env bash
# Run installed console commands against copied repository examples outside the source tree.
set -euo pipefail
unset PYTHONPATH
venv=$1
out=$2
examples=$3
conformance=${4:-}
mkdir -p "$out"
cp -R "$examples" "$out/examples"
cd "$out"
cli="$venv/bin/decision-control"
expect_code() {
  expected=$1
  shift
  actual=0
  "$@" || actual=$?
  test "$actual" -eq "$expected"
  printf '%s: expected %s, observed %s\n' "$*" "$expected" "$actual" >&2
}
expect_code 0 "$cli" demo --out demo > demo-result.json
expect_code 0 "$cli" replay --record demo/record-review.json
expect_code 1 "$cli" evaluate --cases examples/evaluation-cases.jsonl \
  --policy examples/policy.json --require examples/evaluation-requirements.json \
  --out gated > evaluation-result.json
expect_code 0 "$cli" replay-evaluation --record gated/evaluation.json
expect_code 0 "$cli" --db self.sqlite3 ticket-create --ticket-id T-100 --department intake > ticket.json
expect_code 0 "$cli" --db self.sqlite3 submit --proposal examples/proposal.json \
  --policy examples/policy.json --proposed-by local-reviewer > submission.json
id=$("$venv/bin/python" -c 'import json; print(json.load(open("submission.json"))["id"])')
expect_code 1 "$cli" --db self.sqlite3 approve "$id" --reviewer local-reviewer --note checked
expect_code 0 "$cli" --db self.sqlite3 show "$id" > unchanged.json
"$venv/bin/python" -c 'import json; r=json.load(open("unchanged.json")); assert r["status"] == "PENDING_REVIEW" and r["review"] is None'
"$venv/bin/python" - <<'PY'
import json
from importlib import resources
names = sorted(path.name for path in (resources.files("decisioncontrol") / "schema").iterdir())
expected = sorted([f"record.v{n}.json" for n in (1, 2, 3, 4)] + [f"evaluation.v{n}.json" for n in (1, 2)])
assert names == expected, names
for name in names:
    assert json.loads((resources.files("decisioncontrol") / "schema" / name).read_text(encoding="utf-8"))["$id"].endswith("/" + name)
assert json.load(open("demo/record-review.json"))["record"]["schema_version"] == 4
assert json.load(open("gated/evaluation.json"))["report"]["schema_version"] == 2
PY
if [ -n "$conformance" ]; then
  # Replay every conformance vector with the installed console script.
  "$venv/bin/python" - "$cli" "$conformance" <<'PY'
import json, subprocess, sys
cli, root = sys.argv[1], sys.argv[2]
manifest = json.load(open(f"{root}/manifest.json"))
for vector in manifest["vectors"]:
    command = [cli if part == "decision-control" else f"{root}/{vector['path']}" if part == "{path}" else part
               for part in vector["verify"]["command"]]
    code = subprocess.run(command, capture_output=True).returncode
    assert code == vector["verify"]["exit_code"], (vector["path"], code)
print(f"{len(manifest['vectors'])} conformance vectors verified", file=sys.stderr)
PY
fi
