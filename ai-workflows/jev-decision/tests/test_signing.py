"""Signed records: HMAC DSSE envelopes over exact file bytes, and --require-signature."""

import base64
import copy
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jevdecision import JevBackend, attestation, questions_from_spec, signing
from jevdecision.__main__ import main as decide_main
from jevdecision.evaluation import main as eval_main
from jevdecision.jcs import canonicalize
from jevdecision.records import DIGEST_FIELD, answer_record, dumps_record, record_digest
from jevdecision.verify import main as verify_main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
QUESTIONS_FILE = EXAMPLES / "support-ticket.json"
CASES_FILE = EXAMPLES / "support-ticket-cases.jsonl"
RESPONSES_FILE = EXAMPLES / "support-ticket-responses.jsonl"
REQUIRE_FILE = EXAMPLES / "support-ticket-requirements.json"
QUESTIONS = questions_from_spec(json.loads(QUESTIONS_FILE.read_text()))
RESPONSE = json.loads(RESPONSES_FILE.read_text().splitlines()[0])["response"]
STATE = "Help! My payouts have been failing for 3 days."


def run(main, *args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


def make_record():
    backend = JevBackend(api_key="k", transport=lambda *a: copy.deepcopy(RESPONSE), env={})
    return answer_record(backend.decide(STATE, QUESTIONS), QUESTIONS)


def write_provenance(directory):
    """Rewrite provenance.json so every listed output hash matches the files in the directory."""
    provenance = json.loads((directory / "provenance.json").read_text())
    for name in provenance["outputs"]:
        provenance["outputs"][name]["sha256"] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    (directory / "provenance.json").write_text(
        json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


PREDICATE_BASE = "https://github.com/BichengWang/ai-decision-system/predicate/jevdecision/"


def reseal(record):
    record[DIGEST_FIELD] = record_digest(record)
    return record


def envelope_with(data, name, kind, version, key, *, predicate_type=None):
    """An envelope over `data`, optionally with another predicate type."""
    return signing.sign(data, name, predicate_type or attestation.predicate_type(kind, version),
                        attestation.predicate(kind, version), key)


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.key_file = self.root / "signing.key"
        self.key_id = signing.generate_key(self.key_file)
        self.key = signing.load_key(self.key_file)
        self.other_file = self.root / "other.key"
        signing.generate_key(self.other_file)

    def decide(self, *extra, response=RESPONSE, schema=2):
        backend = JevBackend(api_key="k", transport=lambda *a: copy.deepcopy(response), env={})
        with unittest.mock.patch("jevdecision.__main__.create_backend", return_value=backend):
            return run(decide_main, "--questions", QUESTIONS_FILE, "--state", STATE,
                       "--schema-version", schema, *extra)

    def signed_answer(self, name="answer.json"):
        out = self.root / name
        code, stdout, stderr = self.decide("--out", out, "--sign-key", self.key_file)
        self.assertEqual((code, stdout, stderr), (0, "", ""))
        return out

    def verify(self, *args):
        return run(verify_main, *args)


class KeyTests(Workspace):
    def test_generated_key_is_private_random_hex_and_never_overwritten(self):
        path = self.root / "new.key"
        code, out, _ = run(decide_main, "--generate-key", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["key_id"], signing.key_id(signing.load_key(path)))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(len(bytes.fromhex(path.read_text().strip())), signing.KEY_BYTES)
        before = path.read_bytes()
        code, _, err = run(decide_main, "--generate-key", path)
        self.assertEqual(code, 2)
        self.assertIn("exists", err)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(self.key_file.read_bytes(), self.other_file.read_bytes())
        self.assertEqual(stat.S_IMODE(os.stat(self.key_file).st_mode), 0o600)

    def test_generate_key_cannot_be_combined_with_other_work(self):
        for extra in (["--questions", QUESTIONS_FILE], ["--state", "x"], ["--out", self.root / "o"], ["--dry-run"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as raised:
                run(decide_main, "--generate-key", self.root / "k", *extra)
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse((self.root / "k").exists())

    def test_bad_key_files_exit_2_before_any_output(self):
        bad = {"missing": None, "empty": "", "short": "ab" * 16 + "\n", "not hex": "zz" * 32 + "\n",
               "binary": "\u00e9" * 40}
        for name, text in bad.items():
            path = self.root / f"bad-{name}.key"
            if text is not None:
                path.write_text(text, encoding="utf-8")
            with self.subTest(name=name):
                out = self.root / f"out-{name}.json"
                code, _, err = self.decide("--out", out, "--sign-key", path)
                self.assertEqual(code, 2, err)
                self.assertFalse(out.exists())
                record = self.root / f"record-{name}.json"
                record.write_text(dumps_record(make_record()))
                self.assertEqual(self.verify(record, "--require-signature", "--key", path)[0], 2)
                evaluation = self.root / f"eval-{name}"
                code, _, err = run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE,
                                   "--responses", RESPONSES_FILE, "--out", evaluation, "--sign-key", path)
                self.assertEqual(code, 2, err)
                self.assertFalse(evaluation.exists())

    def test_longer_keys_are_accepted(self):
        path = self.root / "long.key"
        path.write_text(os.urandom(48).hex() + "\n")
        out = self.root / "a.json"
        self.assertEqual(self.decide("--out", out, "--sign-key", path)[0], 0)
        self.assertEqual(self.verify(out, "--require-signature", "--key", path)[0], 0)


class AnswerSigningTests(Workspace):
    def test_sign_and_verify_round_trip(self):
        out = self.signed_answer()
        envelope = json.loads(Path(str(out) + ".dsse.json").read_text())
        self.assertEqual(envelope["payloadType"], "application/vnd.in-toto+json")
        self.assertEqual(envelope["signatures"][0]["keyid"], self.key_id)
        statement = json.loads(base64.b64decode(envelope["payload"]))
        self.assertEqual(statement["_type"], "https://in-toto.io/Statement/v1")
        self.assertEqual(statement["predicateType"], PREDICATE_BASE + "answer/v2")
        self.assertEqual(statement["predicate"],
                         {"schema": "https://github.com/BichengWang/ai-decision-system/schema/jevdecision/answer.v2.json"})
        self.assertEqual(statement["subject"], [{"name": "answer.json",
                                                 "digest": {"sha256": hashlib.sha256(out.read_bytes()).hexdigest()}}])
        self.assertEqual(canonicalize(statement), base64.b64decode(envelope["payload"]))
        code, stdout, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual((code, stdout, stderr), (0, f"{out}: verified\n", ""))

    def test_the_written_record_is_the_stdout_record_plus_newline(self):
        _, stdout, _ = self.decide()
        out = self.root / "answer.json"
        self.decide("--out", out)
        self.assertEqual(out.read_text(), stdout)

    def test_unsigned_record_exits_1_only_when_a_signature_is_required(self):
        out = self.root / "plain.json"
        self.assertEqual(self.decide("--out", out)[0], 0)
        self.assertEqual(self.verify(out)[0], 0)  # unchanged without --require-signature
        code, stdout, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn("unsigned", stderr)

    def test_edited_and_rehashed_record_passes_the_digest_check_but_not_the_signature(self):
        out = self.signed_answer()
        record = json.loads(out.read_text())
        record["produced_by"]["version"] = "9.9.9"  # not derivable from the response
        reseal(record)
        out.write_text(dumps_record(record) + "\n")
        self.assertEqual(self.verify(out)[0], 0)  # today's digest and re-parse checks pass
        code, _, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual(code, 1)
        self.assertIn("different record bytes", stderr)

    def test_reformatting_the_signed_file_breaks_the_signature(self):
        out = self.signed_answer()
        out.write_text(json.dumps(json.loads(out.read_text()), indent=2))
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 1)

    def test_wrong_key_exits_1(self):
        out = self.signed_answer()
        code, _, stderr = self.verify(out, "--require-signature", "--key", self.other_file)
        self.assertEqual(code, 1)
        self.assertIn("no valid signature", stderr)

    def test_wrong_predicate_type_exits_1(self):
        out = self.root / "answer.json"
        self.decide("--out", out)
        data = out.read_bytes()
        record = json.loads(data)
        wrong = {
            "other record kind": attestation.predicate_type("provenance", 2),
            "other schema version": attestation.predicate_type("answer", 1),
            "other package": PREDICATE_BASE.replace("jevdecision", "expgate") + "answer/v2",
            "unrelated": "https://example.com/predicate/v1",
        }
        self.assertEqual(record["schema_version"], 2)
        for name, predicate_type in wrong.items():
            envelope = envelope_with(data, out.name, "answer", 2, self.key, predicate_type=predicate_type)
            Path(str(out) + ".dsse.json").write_text(json.dumps(envelope))
            with self.subTest(name=name):
                code, _, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
                self.assertEqual(code, 1)
                self.assertIn("predicate type", stderr)


    def odd_signed_envelopes(self, good, key):
        """Envelopes whose HMAC is valid but whose statement has fields of unexpected types."""
        import hashlib
        import hmac
        statement = json.loads(base64.b64decode(good["payload"]))

        def signed(body):
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            mac = hmac.new(key, signing.pae(signing.PAYLOAD_TYPE, payload), hashlib.sha256).digest()
            return {"payloadType": signing.PAYLOAD_TYPE, "payload": base64.b64encode(payload).decode(),
                    "signatures": [{"keyid": signing.key_id(key), "sig": base64.b64encode(mac).decode()}]}

        subject = statement["subject"]
        return {
            "predicateType is a list": signed({**statement, "predicateType": ["x"]}),
            "predicateType is a dict": signed({**statement, "predicateType": {"x": 1}}),
            "subject is a number": signed({**statement, "subject": 7}),
            "subject is a string": signed({**statement, "subject": "abc"}),
            "subject is null": signed({**statement, "subject": None}),
            "subject entries are not objects": signed({**statement, "subject": [1, "x", None, [], True]}),
            "digest is not an object": signed({**statement, "subject": [{"name": "x", "digest": "abc"}]}),
            "digest value is a number": signed({**statement, "subject": [{"name": "x", "digest": {"sha256": 5}}]}),
            "digest value is a list": signed({**statement, "subject": [{"name": "x", "digest": {"sha256": [1]}}]}),
            "digest value is non-ASCII": signed({**statement, "subject": [{"name": "x", "digest": {"sha256": "\u00e9" * 64}}]}),
            "deeply nested payload": signed(b"[" * 100000),
            "statement _type is a list": signed({**statement, "_type": []}),
            "subject is an object": signed({**statement, "subject": subject[0]}),
        }

    def sig_field_variants(self, good):
        keyid = good["signatures"][0]["keyid"]
        return {
            "sig is null": [{"keyid": keyid, "sig": None}],
            "sig missing": [{"keyid": keyid}],
            "sig is a number": [{"keyid": keyid, "sig": 7}],
            "sig is a list": [{"keyid": keyid, "sig": ["a"]}],
            "sig is an object": [{"keyid": keyid, "sig": {"a": 1}}],
            "sig is true": [{"keyid": keyid, "sig": True}],
            "keyid is a list": [{"keyid": ["a"], "sig": good["signatures"][0]["sig"]}],
            "entry is null": [None],
        }

    def test_null_and_odd_typed_signature_fields_exit_1(self):
        out = self.signed_answer()
        envelope_path = Path(str(out) + ".dsse.json")
        good = json.loads(envelope_path.read_text())
        key = signing.load_key(self.key_file)
        cases = {name: {**good, "signatures": entries} for name, entries in self.sig_field_variants(good).items()}
        cases.update({"payload is a number": {**good, "payload": 5}, "payload is null": {**good, "payload": None},
                      "payload is a list": {**good, "payload": ["a"]}, "payload is non-ASCII": {**good, "payload": "\u00e9"}})
        cases.update(self.odd_signed_envelopes(good, key))
        for name, envelope in cases.items():
            envelope_path.write_text(json.dumps(envelope))
            with self.subTest(name=name):
                code, _, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
                self.assertEqual(code, 1, stderr)
                self.assertNotIn("Traceback", stderr)
        envelope_path.write_text(json.dumps(good))
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 0)

    def test_malformed_envelopes_exit_1(self):
        out = self.signed_answer()
        envelope_path = Path(str(out) + ".dsse.json")
        good = json.loads(envelope_path.read_text())
        payload = json.loads(base64.b64decode(good["payload"]))
        broken = {
            "not json": "{",
            "empty": "",
            "list": "[]",
            "null": "null",
            "wrong payload type": json.dumps({**good, "payloadType": "text/plain"}),
            "no payload": json.dumps({k: v for k, v in good.items() if k != "payload"}),
            "bad base64": json.dumps({**good, "payload": "!!!"}),
            "no signatures": json.dumps({**good, "signatures": []}),
            "signatures not a list": json.dumps({**good, "signatures": "x"}),
            "signature not an object": json.dumps({**good, "signatures": ["x"]}),
            "bad signature bytes": json.dumps({**good, "signatures": [{"keyid": self.key_id, "sig": "!!!"}]}),
            "forged signature": json.dumps({**good, "signatures": [{"keyid": self.key_id, "sig": "AAAA"}]}),
            "payload swapped": json.dumps({**good, "payload": base64.b64encode(json.dumps(
                {**payload, "predicateType": "x"}).encode()).decode()}),
            "payload not a statement": json.dumps(
                {**good, "payload": base64.b64encode(b"[]").decode()}),
        }
        for name, text in broken.items():
            envelope_path.write_text(text)
            with self.subTest(name=name):
                self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 1)
        # A statement of another type signed correctly is rejected too.
        statement = {**payload, "_type": "https://in-toto.io/Statement/v0.1"}
        body = canonicalize(statement)
        envelope_path.write_text(json.dumps({
            "payloadType": signing.PAYLOAD_TYPE, "payload": base64.b64encode(body).decode(),
            "signatures": [{"keyid": self.key_id, "sig": base64.b64encode(
                __import__("hmac").new(self.key, signing.pae(signing.PAYLOAD_TYPE, body), "sha256").digest()
            ).decode()}]}))
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 1)

    def test_signature_of_another_record_does_not_verify(self):
        first, second = self.signed_answer("first.json"), self.root / "second.json"
        record = make_record()
        record["id"] = "different"
        record["response"]["id"] = "different"
        second.write_text(dumps_record(reseal(record)) + "\n")
        Path(str(second) + ".dsse.json").write_bytes(Path(str(first) + ".dsse.json").read_bytes())
        self.assertEqual(self.verify(second)[0], 0)
        self.assertEqual(self.verify(second, "--require-signature", "--key", self.key_file)[0], 1)

    def test_signature_is_checked_before_verification_and_verification_still_runs_after(self):
        out = self.signed_answer()
        record = json.loads(out.read_text())
        record["answers"]["refund"]["probability"] = 0.99  # edited, digest left
        edited = dumps_record(record) + "\n"
        out.write_text(edited)
        code, stdout, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn("signature", stderr)
        # Validly signed but internally inconsistent content: the normal check still fails it.
        Path(str(out) + ".dsse.json").write_text(
            attestation.render_envelope(attestation.sign_bytes(edited.encode(), out.name, "answer", 2, self.key)))
        code, stdout, _ = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual(code, 1)
        self.assertIn("mismatch", stdout)

    def test_schema_1_record_can_be_signed_and_stays_unverifiable(self):
        out = self.root / "v1.json"
        self.assertEqual(self.decide("--out", out, "--sign-key", self.key_file, schema=1)[0], 0)
        statement = json.loads(base64.b64decode(json.loads(Path(str(out) + ".dsse.json").read_text())["payload"]))
        self.assertEqual(statement["predicateType"], PREDICATE_BASE + "answer/v1")
        code, _, stderr = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual(code, 2)
        self.assertIn("schema 1 cannot be verified", stderr)

    def test_explicit_signature_path_and_several_records(self):
        out = self.signed_answer()
        moved = self.root / "elsewhere.dsse.json"
        Path(str(out) + ".dsse.json").rename(moved)
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 1)
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file, "--signature", moved)[0], 0)
        other = self.signed_answer("other.json")
        self.assertEqual(self.verify(moved.parent / "other.json", out.parent / "x.json", "--require-signature",
                                     "--key", self.key_file)[0], 2)  # x.json is missing
        self.assertEqual(self.verify(other, "--require-signature", "--key", self.key_file)[0], 0)
        with self.assertRaises(SystemExit) as raised:
            self.verify(out, other, "--require-signature", "--key", self.key_file, "--signature", moved)
        self.assertEqual(raised.exception.code, 2)

    def test_option_combinations_are_usage_errors(self):
        out = self.signed_answer()
        for args in (("--key", self.key_file), ("--signature", "s"), ("--sigstore-bundle", "b"),
                     ("--require-signature",),
                     ("--require-signature", "--key", self.key_file, "--sigstore-bundle", "b"),
                     ("--require-signature", "--key", self.key_file, "--certificate-identity", "i"),
                     ("--require-signature", "--sigstore-bundle", "b"),
                     ("--require-signature", "--sigstore-bundle", "b", "--certificate-identity", "i"),
                     ("--require-signature", "--sigstore-bundle", "b", "--certificate-identity", "i",
                      "--certificate-oidc-issuer", "u", "--signature", "s")):
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.verify(out, *args)
            self.assertEqual(raised.exception.code, 2)

    def test_signing_requires_out_and_never_overwrites(self):
        for args in (("--sign-key", self.key_file), ("--dry-run", "--out", self.root / "d.json")):
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.decide(*args)
            self.assertEqual(raised.exception.code, 2)
        out = self.signed_answer()
        before = (out.read_bytes(), Path(str(out) + ".dsse.json").read_bytes())
        code, _, err = self.decide("--out", out, "--sign-key", self.key_file)
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", err)
        self.assertEqual(before, (out.read_bytes(), Path(str(out) + ".dsse.json").read_bytes()))
        # A leftover envelope blocks signing a new file under that name.
        fresh = self.root / "fresh.json"
        Path(str(fresh) + ".dsse.json").write_text("{}")
        code, _, err = self.decide("--out", fresh, "--sign-key", self.key_file)
        self.assertEqual(code, 2)
        self.assertFalse(fresh.exists())
        # An unsigned write also refuses an existing file.
        self.assertEqual(self.decide("--out", out)[0], 2)

    def test_a_failure_while_signing_leaves_neither_file(self):
        out = self.root / "answer.json"
        with unittest.mock.patch("jevdecision.attestation.sign_bytes", side_effect=OSError("disk full")):
            code, _, err = self.decide("--out", out, "--sign-key", self.key_file)
        self.assertEqual(code, 2)
        self.assertIn("disk full", err)
        self.assertFalse(out.exists())
        self.assertFalse(Path(str(out) + ".dsse.json").exists())

    def test_refusal_record_is_still_written_and_signed_with_exit_1(self):
        response = {"id": "r", "answers": {"refund": {"type": "refusal"}, "department": {
            "choice": "billing", "probabilities": {"billing": 1.0, "technical": 0.0, "sales": 0.0}},
            "frustration": {"score": 2.0}}}
        out = self.root / "refusal.json"
        code, _, _ = self.decide("--out", out, "--sign-key", self.key_file, response=response)
        self.assertEqual(code, 1)
        self.assertEqual(self.verify(out, "--require-signature", "--key", self.key_file)[0], 0)

    def test_predicate_output_for_cosign(self):
        out = self.signed_answer()
        pred = self.root / "pred.json"
        code, stdout, _ = self.verify(out, "--predicate-out", pred)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["predicate_type"], PREDICATE_BASE + "answer/v2")
        self.assertEqual(json.loads(pred.read_text()), attestation.predicate("answer", 2))
        self.assertEqual(self.verify(out, "--predicate-out", pred)[0], 2)  # never overwrites
        with self.assertRaises(SystemExit):
            self.verify(out, "--predicate-out", self.root / "p2.json", "--require-signature", "--key", self.key_file)
        directory = self.root / "evaluation"
        self.assertEqual(run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE,
                             "--responses", RESPONSES_FILE, "--out", directory)[0], 3)
        code, stdout, _ = self.verify("--evaluation", directory, "--predicate-out", self.root / "p3.json")
        self.assertEqual(json.loads(stdout)["predicate_type"], PREDICATE_BASE + "provenance/v2")


class EvaluationSigningTests(Workspace):
    def setUp(self):
        super().setUp()
        self.out = self.root / "run"
        code, _, err = run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE,
                           "--responses", RESPONSES_FILE, "--require", REQUIRE_FILE, "--out", self.out,
                           "--sign-key", self.key_file)
        self.assertEqual((code, err), (0, ""))
        self.envelope = self.out / "provenance.json.dsse.json"

    def copy(self, name):
        target = self.root / name
        target.mkdir()
        for path in self.out.iterdir():
            (target / path.name).write_bytes(path.read_bytes())
        return target

    def verify_dir(self, directory, *extra, key=None):
        return self.verify("--evaluation", directory, "--require-signature", "--key", key or self.key_file, *extra)

    def test_sign_and_verify_round_trip(self):
        statement = json.loads(base64.b64decode(json.loads(self.envelope.read_text())["payload"]))
        data = (self.out / "provenance.json").read_bytes()
        self.assertEqual(statement["subject"], [{"name": "provenance.json",
                                                 "digest": {"sha256": hashlib.sha256(data).hexdigest()}}])
        self.assertEqual(statement["predicateType"], PREDICATE_BASE + "provenance/v2")
        code, stdout, stderr = self.verify_dir(self.out)
        self.assertEqual((code, stdout, stderr), (0, f"{self.out}: verified\n", ""))
        # The unsigned outputs are unchanged by signing: the envelope is not part of provenance.json.
        provenance = json.loads(data)
        self.assertNotIn("provenance.json.dsse.json", provenance["outputs"])

    def test_unsigned_directory_exits_1_only_when_a_signature_is_required(self):
        plain = self.root / "plain"
        run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
            "--require", REQUIRE_FILE, "--out", plain)
        self.assertFalse((plain / "provenance.json.dsse.json").exists())
        self.assertEqual(self.verify("--evaluation", plain)[0], 0)
        code, _, stderr = self.verify_dir(plain)
        self.assertEqual(code, 1)
        self.assertIn("unsigned", stderr)

    def test_edited_and_rehashed_directory_passes_the_hash_checks_but_not_the_signature(self):
        directory = self.copy("rehashed")
        path = directory / "responses.jsonl"
        # Same content, different bytes: re-scoring and every recorded value still agree.
        path.write_text("".join(json.dumps(json.loads(line), indent=None) + "\n"
                                for line in path.read_text().splitlines()))
        write_provenance(directory)
        self.assertEqual(self.verify("--evaluation", directory)[0], 0)
        code, stdout, stderr = self.verify_dir(directory)
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn("different record bytes", stderr)

    def test_a_signed_directory_with_an_edited_file_fails_on_the_hash_after_the_signature(self):
        directory = self.copy("edited")
        (directory / "responses.jsonl").write_bytes((directory / "responses.jsonl").read_bytes() + b" ")
        code, stdout, _ = self.verify_dir(directory)
        self.assertEqual(code, 1)
        self.assertIn("responses.jsonl", stdout)  # signature passed; the hash check caught the file
        # Re-scoring runs too: a re-hashed edit that changes a score, signed with the same key, is caught.
        rescored = self.copy("rescored")
        path = rescored / "responses.jsonl"
        path.write_text(path.read_text().replace("0.08", "0.8", 1))
        write_provenance(rescored)
        (rescored / "provenance.json.dsse.json").write_text(attestation.render_envelope(attestation.sign_bytes(
            (rescored / "provenance.json").read_bytes(), "provenance.json", "provenance", 2, self.key)))
        code, stdout, _ = self.verify_dir(rescored)
        self.assertEqual(code, 1)
        self.assertIn("mismatch", stdout)

    def test_wrong_key_and_wrong_predicate_and_malformed_envelope_exit_1(self):
        self.assertEqual(self.verify_dir(self.out, key=self.other_file)[0], 1)
        directory = self.copy("wrong-predicate")
        data = (directory / "provenance.json").read_bytes()
        for name, envelope in {
            "answer predicate": envelope_with(data, "provenance.json", "answer", 2, self.key),
            "provenance v1": envelope_with(data, "provenance.json", "provenance", 1, self.key),
        }.items():
            (directory / "provenance.json.dsse.json").write_text(json.dumps(envelope))
            with self.subTest(name=name):
                code, _, stderr = self.verify_dir(directory)
                self.assertEqual(code, 1)
                self.assertIn("predicate type", stderr)
        for text in ("{", "[]", json.dumps({"payloadType": "x"})):
            (directory / "provenance.json.dsse.json").write_text(text)
            with self.subTest(text=text):
                self.assertEqual(self.verify_dir(directory)[0], 1)

    def test_an_answer_envelope_cannot_vouch_for_provenance(self):
        answer = self.root / "answer.json"
        self.decide_and_sign(answer)
        directory = self.copy("swapped")
        (directory / "provenance.json.dsse.json").write_bytes(Path(str(answer) + ".dsse.json").read_bytes())
        self.assertEqual(self.verify_dir(directory)[0], 1)

    def decide_and_sign(self, out):
        backend = JevBackend(api_key="k", transport=lambda *a: copy.deepcopy(RESPONSE), env={})
        with unittest.mock.patch("jevdecision.__main__.create_backend", return_value=backend):
            self.assertEqual(run(decide_main, "--questions", QUESTIONS_FILE, "--state", STATE, "--out", out,
                                 "--sign-key", self.key_file)[0], 0)

    def test_explicit_signature_and_missing_provenance(self):
        directory = self.copy("moved")
        moved = self.root / "prov.dsse.json"
        (directory / "provenance.json.dsse.json").rename(moved)
        self.assertEqual(self.verify_dir(directory)[0], 1)
        self.assertEqual(self.verify_dir(directory, "--signature", moved)[0], 0)
        (directory / "provenance.json").unlink()
        self.assertEqual(self.verify_dir(directory, "--signature", moved)[0], 2)

    def test_signing_does_not_leave_a_directory_on_a_bad_key(self):
        target = self.root / "never"
        code, _, _ = run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE,
                         "--responses", RESPONSES_FILE, "--out", target, "--sign-key", self.root / "absent.key")
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".never-")], [])


class ReadOnceTests(Workspace):
    """Each signed file is read once; the signature, parsing and every later check use those bytes."""

    def swap_after_first_read(self, path, replacement):
        """Patch Path.read_bytes so that `path` is replaced on disk right after it is first read."""
        original = Path.read_bytes
        reads = {}

        def read_bytes(candidate):
            data = original(candidate)
            reads[str(candidate)] = reads.get(str(candidate), 0) + 1
            if candidate == path and reads[str(candidate)] == 1:
                path.write_bytes(replacement)
            return data

        patch = unittest.mock.patch.object(Path, "read_bytes", read_bytes)
        patch.start()
        self.addCleanup(patch.stop)
        return reads

    def tampered_signed_answer(self):
        """A signed answer whose content fails normal verification, and a pristine record to swap in."""
        pristine = dumps_record(make_record()) + "\n"
        record = make_record()
        record["answers"]["refund"]["probability"] = 0.99  # edited, digest left
        out = self.root / "answer.json"
        out.write_text(dumps_record(record) + "\n")
        envelope = attestation.sign_bytes(out.read_bytes(), out.name, "answer", 2, self.key)
        Path(str(out) + ".dsse.json").write_text(attestation.render_envelope(envelope))
        return out, pristine.encode()

    def test_hmac_answer_is_verified_from_the_bytes_that_were_signed_even_if_the_file_is_swapped(self):
        out, pristine = self.tampered_signed_answer()
        reads = self.swap_after_first_read(out, pristine)
        code, stdout, _ = self.verify(out, "--require-signature", "--key", self.key_file)
        self.assertEqual(code, 1)  # the signed bytes are the tampered ones
        self.assertIn("mismatch", stdout)
        self.assertEqual(reads[str(out)], 1)

    def test_sigstore_answer_is_verified_from_the_bytes_cosign_saw_even_if_the_file_is_swapped(self):
        out, pristine = self.tampered_signed_answer()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        cosign = bin_dir / "cosign"
        cosign.write_text(FAKE_COSIGN + 'cp "$last" "$COSIGN_SEEN"\n')
        cosign.chmod(0o755)
        bundle = self.root / "bundle.sigstore.json"
        bundle.write_text("{}")
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "COSIGN_ARGS": str(self.root / "args"),
               "COSIGN_BLOB": str(self.root / "blob"), "COSIGN_MODE": str(self.root / "mode"),
               "COSIGN_BUNDLE": str(self.root / "bundle-copy"), "COSIGN_SEEN": str(self.root / "seen")}
        signed = out.read_bytes()
        reads = self.swap_after_first_read(out, pristine)
        with unittest.mock.patch.dict(os.environ, env):
            code, stdout, _ = self.verify(out, "--require-signature", "--sigstore-bundle", bundle,
                                          "--certificate-identity", "i", "--certificate-oidc-issuer", "u")
        self.assertEqual(code, 1)
        self.assertIn("mismatch", stdout)
        self.assertEqual((self.root / "seen").read_bytes(), signed)  # cosign checked the bytes that were parsed
        self.assertEqual(reads[str(out)], 1)

    def test_evaluation_directory_files_are_read_once_and_rescored_from_the_hashed_bytes(self):
        directory = self.root / "run"
        run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
            "--require", REQUIRE_FILE, "--out", directory, "--sign-key", self.key_file)
        responses = directory / "responses.jsonl"
        genuine = responses.read_bytes()
        responses.write_text(genuine.decode().replace("0.08", "0.8", 1))
        provenance = json.loads((directory / "provenance.json").read_text())
        provenance["outputs"]["responses.jsonl"]["sha256"] = hashlib.sha256(responses.read_bytes()).hexdigest()
        (directory / "provenance.json").write_text(
            json.dumps(provenance, sort_keys=True, separators=(",", ":")))
        envelope = attestation.sign_bytes((directory / "provenance.json").read_bytes(), "provenance.json",
                                          "provenance", 2, self.key)
        (directory / "provenance.json.dsse.json").write_text(attestation.render_envelope(envelope))
        reads = self.swap_after_first_read(responses, genuine)
        code, stdout, _ = self.verify("--evaluation", directory, "--require-signature", "--key", self.key_file)
        self.assertEqual(code, 1)  # hashed and re-scored as signed, not as swapped in afterwards
        self.assertIn("mismatch", stdout)
        for name in ("provenance.json", "responses.jsonl", "cases.jsonl", "evaluation.json", "EVALUATION.md",
                     "questions.json", "requirements.json"):
            self.assertEqual(reads.get(str(directory / name)), 1, name)

    def test_provenance_is_read_once_for_the_signature_and_the_checks(self):
        directory = self.root / "run"
        run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
            "--out", directory, "--sign-key", self.key_file)
        provenance = directory / "provenance.json"
        reads = self.swap_after_first_read(provenance, b"{}")
        code, stdout, _ = self.verify("--evaluation", directory, "--require-signature", "--key", self.key_file)
        self.assertEqual((code, stdout), (0, f"{directory}: verified\n"))
        self.assertEqual(reads[str(provenance)], 1)


FAKE_COSIGN = """#!/bin/sh
printf '%s\\n' "$@" > "$COSIGN_ARGS"
for last; do :; done
cp "$last" "$COSIGN_BLOB"
[ -n "$(find "$last" -perm 0600 -print)" ] && echo 600 > "$COSIGN_MODE"
bundle=""; while [ $# -gt 0 ]; do [ "$1" = --bundle ] && bundle="$2"; shift; done
cp "$bundle" "$COSIGN_BUNDLE"
[ -z "$COSIGN_HOOK" ] || sh -c "$COSIGN_HOOK"
[ "${COSIGN_EXIT:-0}" = 0 ] || { echo "no matching attestations" >&2; exit "$COSIGN_EXIT"; }
"""


@unittest.skipIf(os.name == "nt", "uses a shell script as a stand-in for cosign")
class SigstoreTests(Workspace):
    """The package shells out to `cosign verify-blob-attestation`; a stand-in records the arguments."""

    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        cosign = self.bin / "cosign"
        cosign.write_text(FAKE_COSIGN)
        cosign.chmod(0o755)
        self.args_file = self.root / "cosign-args"
        patch = unittest.mock.patch.dict(os.environ, {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "COSIGN_ARGS": str(self.args_file),
            "COSIGN_BLOB": str(self.root / "cosign-blob"), "COSIGN_MODE": str(self.root / "cosign-mode"),
            "COSIGN_BUNDLE": str(self.root / "cosign-bundle")})
        patch.start()
        self.addCleanup(patch.stop)
        self.bundle = self.root / "bundle.sigstore.json"
        self.bundle.write_text("{}")
        self.identity_args = ("--certificate-identity", "https://github.com/o/r/.github/workflows/w.yml@refs/heads/main",
                              "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com")

    def test_answer_bundle_is_verified_by_cosign_with_the_expected_arguments(self):
        out = self.root / "answer.json"
        self.decide("--out", out)
        code, _, _ = self.verify(out, "--require-signature", "--sigstore-bundle", self.bundle, *self.identity_args)
        self.assertEqual(code, 0)
        args = self.args_file.read_text().split("\n")
        self.assertEqual(args[0], "verify-blob-attestation")
        self.assertEqual(args[args.index("--type") + 1], PREDICATE_BASE + "answer/v2")
        # cosign gets private copies of the bytes that were read, not the original paths.
        self.assertNotEqual(args[args.index("--bundle") + 1], str(self.bundle))
        self.assertEqual((self.root / "cosign-bundle").read_bytes(), self.bundle.read_bytes())
        self.assertEqual(args[args.index("--certificate-identity") + 1], self.identity_args[1])
        self.assertEqual(args[args.index("--certificate-oidc-issuer") + 1], self.identity_args[3])
        self.assertNotEqual(args[-2], str(out))
        self.assertEqual(Path(args[-2]).name, out.name)
        self.assertEqual((self.root / "cosign-blob").read_bytes(), out.read_bytes())
        self.assertEqual((self.root / "cosign-mode").read_text().strip(), "600")
        self.assertFalse(Path(args[-2]).exists())  # the private copy is removed afterwards

    def test_a_record_named_like_the_bundle_copy_still_verifies(self):
        for name in ("bundle.sigstore.json", "record", "bundle"):
            out = self.root / name
            out.unlink(missing_ok=True)
            self.decide("--out", out)
            with self.subTest(name=name):
                code, _, stderr = self.verify(out, "--require-signature", "--sigstore-bundle", self.bundle,
                                              *self.identity_args)
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual((self.root / "cosign-blob").read_bytes(), out.read_bytes())
                self.assertEqual((self.root / "cosign-bundle").read_bytes(), self.bundle.read_bytes())
        # The bundle itself may even be the record's neighbour under the same name.
        directory = self.root / "other"
        directory.mkdir()
        out = directory / "bundle.sigstore.json"
        self.decide("--out", out)
        self.assertEqual(self.verify(out, "--require-signature", "--sigstore-bundle", out, *self.identity_args)[0], 0)

    def test_evaluation_bundle_verifies_provenance_json(self):
        directory = self.root / "run"
        run(eval_main, "--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
            "--out", directory)
        code, _, _ = self.verify("--evaluation", directory, "--require-signature", "--sigstore-bundle", self.bundle,
                                 *self.identity_args)
        self.assertEqual(code, 0)
        args = self.args_file.read_text().split("\n")
        self.assertEqual(args[args.index("--type") + 1], PREDICATE_BASE + "provenance/v2")
        self.assertEqual(Path(args[-2]).name, "provenance.json")
        self.assertNotEqual(args[-2], str(directory / "provenance.json"))
        self.assertEqual((self.root / "cosign-blob").read_bytes(), (directory / "provenance.json").read_bytes())

    def test_rejection_missing_bundle_and_absent_cosign(self):
        out = self.root / "answer.json"
        self.decide("--out", out)
        options = ("--require-signature", "--sigstore-bundle", self.bundle, *self.identity_args)
        with unittest.mock.patch.dict(os.environ, {"COSIGN_EXIT": "1"}):
            code, _, stderr = self.verify(out, *options)
        self.assertEqual(code, 1)
        self.assertIn("cosign rejected the attestation", stderr)
        missing = self.root / "missing.sigstore.json"
        code, _, stderr = self.verify(out, "--require-signature", "--sigstore-bundle", missing, *self.identity_args)
        self.assertEqual(code, 1)
        self.assertIn("unsigned", stderr)
        with unittest.mock.patch("jevdecision.signing.shutil.which", return_value=None):
            code, _, stderr = self.verify(out, *options)
        self.assertEqual(code, 2)
        self.assertIn("cosign is not installed", stderr)

    def test_edited_record_is_still_rejected_by_the_package_verifier_after_cosign_accepts(self):
        out = self.root / "answer.json"
        self.decide("--out", out)
        record = json.loads(out.read_text())
        record["answers"]["refund"]["probability"] = 0.99
        out.write_text(dumps_record(record) + "\n")
        code, stdout, _ = self.verify(out, "--require-signature", "--sigstore-bundle", self.bundle,
                                      *self.identity_args)
        self.assertEqual(code, 1)
        self.assertIn("mismatch", stdout)


if __name__ == "__main__":
    unittest.main()
