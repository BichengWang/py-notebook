"""Freeze an Open Policy Agent decision, as recorded in an OPA decision log entry.

The frozen block keeps the decision-log members ``decision_id``, ``path``, ``bundles``
(with each bundle ``revision``), ``input`` and ``result`` (plus ``timestamp`` and
``labels`` when present) and adds the policy ``modules`` and ``data`` that produced
the decision, because a log entry carries a bundle revision, not the bundle.

Mapping to a verdict: a boolean result is ALLOW or DENY; an object result with a
``verdict`` member (ALLOW, DENY, REVIEW or ABSTAIN) and optional ``reasons`` list is
that verdict. Other result shapes are rejected. Replay re-evaluates the frozen modules,
data and input with ``opa eval`` when ``opa`` is on PATH, with the network, DNS and
runtime-environment built-ins removed from the capabilities.
"""

from collections.abc import Mapping
import json
from pathlib import Path
import re
import tempfile

from .. import jcs
from ..models import DecisionError, Evaluation, RecordMismatch, Verdict, _fields, _text
from . import _binding, _tools

NAME = "opa"
REQUIRED = {"engine", "decision_id", "path", "bundles", "input", "result", "modules", "data"}
OPTIONAL = {"timestamp", "labels"}
# Built-ins that reach the network or the host environment have no place in a replay.
DISABLED_BUILTINS = ("http.send", "net.lookup_ip_addr", "opa.runtime")
_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_KEYWORDS = {"as", "contains", "data", "default", "else", "every", "false", "if", "import", "in",
             "input", "not", "null", "package", "some", "true", "with"}
_MODULE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def decision_input(recommendation, ticket, proposed_by):
    """The OPA ``input`` document for a proposal; replay requires the frozen input to equal it."""
    return _binding.proposal(recommendation, ticket, proposed_by)


def _canonical(value):
    try:
        return jcs.canonicalize(value)
    except ValueError as error:
        raise DecisionError(f"OPA decision must be RFC 8785 canonicalizable JSON: {error}") from error


def _module_name(name):
    parts = name.split("/") if isinstance(name, str) else []
    if not parts or not name.endswith(".rego") or not all(_MODULE_PART.match(part) for part in parts):
        raise DecisionError(f"invalid policy module name: {name!r}")


def _path(path):
    _text(path, "OPA decision path")
    segments = path.strip("/").split("/")
    if not all(segments):
        raise DecisionError("OPA decision path must be slash-separated nonempty names")
    return segments


def query(path):
    """The Rego reference for a decision-log ``path``, e.g. ``data.ticket.routing.decision``."""
    ref = "data"
    for segment in _path(path):
        plain = _SEGMENT.match(segment) and segment not in _KEYWORDS
        ref += f".{segment}" if plain else f"[{json.dumps(segment)}]"
    return ref


def validate(frozen):
    raw = _fields(frozen, REQUIRED, OPTIONAL)
    if raw["engine"] != NAME:
        raise DecisionError("not an OPA decision")
    _text(raw["decision_id"], "decision_id")
    _path(raw["path"])
    bundles = raw["bundles"]
    if not isinstance(bundles, Mapping):
        raise DecisionError("bundles must be an object of bundle name to revision")
    for name, bundle in bundles.items():
        _text(name, "bundle name")
        if not isinstance(_fields(bundle, {"revision"})["revision"], str):
            raise DecisionError("bundle revision must be a string")
    for name in ("input", "data"):
        if not isinstance(raw[name], Mapping):
            raise DecisionError(f"{name} must be a JSON object")
    modules = raw["modules"]
    if not isinstance(modules, Mapping) or not modules:
        raise DecisionError("modules must be a nonempty object of module name to Rego source")
    for name, source in modules.items():
        _module_name(name)
        if not isinstance(source, str):
            raise DecisionError("module source must be text")
    if "timestamp" in raw:
        _text(raw["timestamp"], "timestamp")
    if "labels" in raw and not isinstance(raw["labels"], Mapping):
        raise DecisionError("labels must be an object")
    _canonical(raw)
    return raw


def bind(frozen, recommendation, ticket, proposed_by):
    """Reject a frozen decision that was taken for a different proposal, ticket or proposer."""
    _binding.require_equal(frozen["input"], decision_input(recommendation, ticket, proposed_by), "OPA", "input")


def evaluation(frozen):
    """The verdict and reasons a frozen OPA result maps to."""
    result = frozen["result"]
    if isinstance(result, bool):
        return Evaluation(Verdict.ALLOW if result else Verdict.DENY, ("opa:allow" if result else "opa:deny",))
    if isinstance(result, Mapping) and "verdict" in result:
        try:
            verdict = Verdict(result["verdict"])
        except (ValueError, TypeError) as error:
            raise DecisionError("OPA result verdict must be ALLOW, DENY, REVIEW or ABSTAIN") from error
        reasons = result.get("reasons", ["policy_decision"])
        if not isinstance(reasons, list) or not reasons:
            raise DecisionError("OPA result reasons must be a nonempty list")
        return Evaluation(verdict, tuple(f"opa:{_text(reason, 'reason')}" for reason in reasons))
    raise DecisionError("OPA result must be a boolean or an object with a verdict member")


def _version(binary, cwd):
    completed = _tools.run([binary, "version"], cwd=cwd)
    for line in completed.stdout.splitlines():
        if line.startswith("Version:"):
            return f"opa {line.split(':', 1)[1].strip()}"
    return "opa (unknown version)"


def reevaluate(frozen):
    """Re-evaluate the frozen decision. ``None`` when opa is absent, else the tool version.

    Raises RecordMismatch when the frozen modules, data and input do not produce the frozen result.
    """
    binary = _tools.find("opa")
    if binary is None:
        return None
    with tempfile.TemporaryDirectory(prefix="decisioncontrol-opa-") as temporary:
        root = Path(temporary)
        policies = root / "policy"
        for name, source in frozen["modules"].items():
            target = policies / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        (policies / "data.json").write_text(json.dumps(frozen["data"]), encoding="utf-8")
        listed = _tools.run([binary, "capabilities", "--current"], cwd=root)
        if listed.returncode != 0:
            raise DecisionError(f"opa capabilities failed: {_tools.first_line(listed.stderr or listed.stdout)}")
        capabilities = json.loads(listed.stdout)
        capabilities["builtins"] = [item for item in capabilities["builtins"]
                                    if item["name"] not in DISABLED_BUILTINS]
        (root / "capabilities.json").write_text(json.dumps(capabilities), encoding="utf-8")
        completed = _tools.run(
            [binary, "eval", "--format", "json", "--data", str(policies), "--stdin-input",
             "--capabilities", str(root / "capabilities.json"), query(frozen["path"])],
            cwd=root, stdin=json.dumps(frozen["input"], allow_nan=False))
        if completed.returncode != 0:
            raise RecordMismatch("opa could not evaluate the frozen policy: "
                                 + _tools.first_line(completed.stdout or completed.stderr))
        try:
            expressions = json.loads(completed.stdout).get("result")
            if expressions is None:
                raise RecordMismatch("the frozen policy defines no result for the frozen input")
            value = expressions[0]["expressions"][0]["value"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise DecisionError(f"unexpected opa output: {_tools.first_line(completed.stdout)}") from error
        if _canonical(value) != _canonical(frozen["result"]):
            raise RecordMismatch("re-evaluating the frozen OPA policy gives a different result than the frozen result")
        return _version(binary, root)


def entries_from_log(text):
    """Decision log entries (objects with a ``decision_id``) from JSON, a JSON array or JSON Lines."""
    try:
        documents = [json.loads(text)]
    except json.JSONDecodeError:
        documents = []
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    documents.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise DecisionError(f"decision log line {number} is not JSON: {error}") from error
    entries = []
    for document in documents:
        for item in document if isinstance(document, list) else [document]:
            if isinstance(item, Mapping) and "decision_id" in item:
                entries.append(item)
    return entries


def select_entry(entries, decision_id=None):
    if decision_id is not None:
        found = [entry for entry in entries if entry.get("decision_id") == decision_id]
        if len(found) != 1:
            raise DecisionError(f"decision log has {len(found)} entries with decision_id {decision_id}")
        return found[0]
    if len(entries) != 1:
        raise DecisionError(f"decision log has {len(entries)} entries; select one with --decision-id")
    return entries[0]


def load_policy_dir(directory):
    """``(modules, data, revision)`` from a directory of ``.rego`` files with an optional root
    ``data.json`` and ``.manifest``. Nested data files are rejected rather than ignored."""
    root = Path(directory)
    if not root.is_dir():
        raise DecisionError(f"policy directory not found: {directory}")
    modules, data, revision = {}, {}, None
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise DecisionError(f"policy directory must not contain symbolic links: {relative}")
        if not path.is_file():
            continue
        if path.suffix == ".rego":
            modules[relative.as_posix()] = path.read_text(encoding="utf-8")
        elif relative.as_posix() == "data.json":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif path.name in ("data.json", "data.yaml", "data.yml"):
            raise DecisionError(f"only a root data.json is frozen; found {relative}")
        elif relative.as_posix() == ".manifest":
            revision = json.loads(path.read_text(encoding="utf-8")).get("revision")
    if not modules:
        raise DecisionError(f"no .rego files in {directory}")
    return modules, data, revision


def freeze(entry, modules, data=None, *, bundle_revision=None):
    """Build the frozen block from a decision log entry and the policy that produced it.

    Masked or erased entries are refused: their input or result no longer matches
    what OPA evaluated. ``bundle_revision`` (for example the ``.manifest`` revision of the policy
    directory) must be one of the entry's bundle revisions.
    """
    if not isinstance(entry, Mapping):
        raise DecisionError("a decision log entry must be a JSON object")
    if entry.get("erased") or entry.get("masked"):
        raise DecisionError("decision log entry has erased or masked fields; freeze an unmasked entry")
    for name in ("decision_id", "path", "input", "result"):
        if name not in entry:
            raise DecisionError(f"decision log entry has no {name}")
    frozen = {"engine": NAME, "decision_id": entry["decision_id"], "path": entry["path"],
              "bundles": entry.get("bundles", {}), "input": entry["input"], "result": entry["result"],
              "modules": dict(modules), "data": {} if data is None else data}
    for name in OPTIONAL:
        if name in entry:
            frozen[name] = entry[name]
    validate(frozen)
    revisions = {bundle["revision"] for bundle in frozen["bundles"].values()}
    if bundle_revision is not None and bundle_revision not in revisions:
        raise DecisionError(f"policy revision {bundle_revision!r} is not a bundle revision of the decision log "
                            f"entry ({sorted(revisions)})")
    return frozen
