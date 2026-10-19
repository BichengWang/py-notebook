"""Command line: ask a question set about a state and print the decision as JSON.

    python -m jevdecision --questions examples/support-ticket.json \
        --state "Help! My payouts have been failing for 3 days."

`--dry-run` prints the provider request instead of sending it, so a question
set can be checked without an API key. The printed answer record is schema 2 by
default: it embeds the question definitions and the raw provider response under an
RFC 8785 digest so `jev-decision-verify` can re-check it offline; `--schema-version 1`
prints the earlier typed-answers-only record. `--out FILE` writes the record to a new file instead of
stdout, and with `--sign-key KEYFILE` also writes the HMAC-SHA256 DSSE envelope `FILE.dsse.json` over the
exact bytes of FILE; `--generate-key KEYFILE` creates such a key. Exit codes: 0 success, 1 provider or
response error (or a response that cannot be recorded canonically), 2 invalid input.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import attestation, signing
from .answers import RefusalAnswer
from .backends import BACKENDS, _check_state, create_backend
from .core import BACKEND_ENV, DEFAULT_BACKEND, DecisionModel
from .errors import DecisionError
from .questions import check_question_set, questions_from_spec
from .records import answer_record, dumps_record


def positive_seconds(text):
    """argparse type for --timeout: a finite number of seconds above zero."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {text!r}") from None
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return value


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m jevdecision", description=__doc__.split("\n")[0])
    parser.add_argument("--questions", type=Path, help="JSON file in Jev's question map format (required)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--state", help="state text")
    source.add_argument("--state-file", type=Path,
                        help="state file; a .json file is sent as a JSON object or list of strings")
    parser.add_argument("--backend", choices=sorted(BACKENDS),
                        default=os.environ.get(BACKEND_ENV) or DEFAULT_BACKEND,
                        help=f"provider (default: ${BACKEND_ENV} or {DEFAULT_BACKEND})")
    parser.add_argument("--model", help="model id (default: the backend's)")
    parser.add_argument("--base-url", help="provider or gateway base URL")
    parser.add_argument("--path", help="endpoint path, e.g. /v1/decisions on a gateway")
    parser.add_argument("--timeout", type=positive_seconds, default=30.0, help="seconds (default: 30)")
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=2,
                        help="answer record schema: 2 embeds questions and the raw response for "
                             "jev-decision-verify (default); 1 holds typed answers only")
    parser.add_argument("--out", type=Path,
                        help="write the answer record to this new file instead of stdout")
    parser.add_argument("--sign-key", type=Path,
                        help="HMAC key file; writes OUT.dsse.json, a DSSE envelope over the exact bytes of OUT "
                             "(needs --out)")
    parser.add_argument("--generate-key", type=Path, metavar="KEYFILE",
                        help="write a new random HMAC signing key (mode 0600; never overwrites) and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the request; send nothing")
    args = parser.parse_args(argv)
    if args.generate_key is not None:
        others = [flag for flag, given in (("--questions", args.questions), ("--state", args.state),
                                          ("--state-file", args.state_file), ("--out", args.out),
                                          ("--sign-key", args.sign_key)) if given is not None]
        if others or args.dry_run:
            parser.error("--generate-key cannot be combined with " + ", ".join(others or ["--dry-run"]))
        return args
    if args.questions is None or (args.state is None and args.state_file is None):
        parser.error("--questions and one of --state or --state-file are required")
    if args.sign_key is not None and args.out is None:
        parser.error("--sign-key needs --out: the signature covers the written file's exact bytes")
    if args.dry_run and (args.out is not None or args.sign_key is not None):
        parser.error("--dry-run sends nothing, so there is no record to write or sign")
    return args


def load_state(args):
    if args.state is not None:
        return args.state
    text = args.state_file.read_text(encoding="utf-8")
    return json.loads(text) if args.state_file.suffix == ".json" else text


def _write_record(out, data, version, key):
    """Write the record file (never over an existing one) and, with a key, its DSSE envelope.

    Neither is left behind without the other.
    """
    with open(out, "xb") as stream:
        stream.write(data)
    if key is None:
        return
    try:
        envelope = attestation.sign_bytes(data, Path(out).name, "answer", version, key)
        with open(attestation.envelope_path(out), "x", encoding="utf-8") as stream:
            stream.write(attestation.render_envelope(envelope))
    except BaseException:
        Path(out).unlink(missing_ok=True)
        raise


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.generate_key is not None:
        try:
            key_id = signing.generate_key(args.generate_key)
        except OSError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(json.dumps({"key_file": str(args.generate_key), "key_id": key_id}))
        return 0
    try:
        key = signing.load_key(args.sign_key) if args.sign_key is not None else None
        if args.out is not None:
            for target in (args.out, attestation.envelope_path(args.out) if key is not None else None):
                if target is not None and (target.exists() or target.is_symlink()):
                    raise DecisionError(f"{target} exists; refusing to overwrite")
        spec = json.loads(args.questions.read_text(encoding="utf-8"))
        questions = check_question_set(questions_from_spec(spec))
        state = _check_state(load_state(args))
        backend = create_backend(args.backend, model=args.model, base_url=args.base_url,
                                 path=args.path, timeout=args.timeout)
    except (OSError, ValueError, DecisionError) as error:
        # ValueError covers malformed JSON, undecodable text, invalid questions and key files.
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        request = {"url": backend.url, "body": backend.build_request(state, questions)}
        print(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    try:
        decision = DecisionModel(backend).decide(state, questions)
    except DecisionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.schema_version == 1:
        text = json.dumps(decision.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        try:
            text = dumps_record(answer_record(decision, questions))
        except ValueError as error:
            print(f"error: the provider response cannot be recorded as canonical JSON: {error}", file=sys.stderr)
            return 1
    if args.out is None:
        print(text)
    else:
        try:
            _write_record(args.out, (text + "\n").encode("utf-8"), args.schema_version, key)
        except OSError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    return 1 if any(isinstance(a, RefusalAnswer) for a in decision.answers.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
