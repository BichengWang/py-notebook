"""Signed records: HMAC DSSE envelopes over exact file bytes, and --require-signature."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from decisioncontrol import attestation, signing
from decisioncontrol.cli import main
from decisioncontrol.evidence import export_record
from dc_support import load_schema, rehash_record

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / "signing.key"
        self.other_key = self.root / "other.key"
        self.assertEqual(self.call("keygen", str(self.key))[0], 0)
        self.assertEqual(self.call("keygen", str(self.other_key))[0], 0)
        self.assertEqual(self.call("demo", "--out", str(self.root / "demo"), "--sign-key", str(self.key))[0], 0)
        self.record = self.root / "demo" / "record-review.json"

    def call(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def replay(self, record=None, *extra, key=None):
        return self.call("replay", "--record", str(record or self.record), "--require-signature",
                         "--key", str(key or self.key), *extra)

    def test_signed_record_verifies_and_envelope_is_in_toto_dsse(self):
        code, out, _ = self.replay()
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["valid"])
        envelope = json.loads(Path(str(self.record) + ".dsse.json").read_text(encoding="utf-8"))
        self.assertEqual(envelope["payloadType"], "application/vnd.in-toto+json")
        statement = json.loads(base64.b64decode(envelope["payload"]))
        self.assertEqual(statement["_type"], "https://in-toto.io/Statement/v1")
        self.assertEqual(statement["subject"][0]["name"], "record-review.json")
        import hashlib
        self.assertEqual(statement["subject"][0]["digest"]["sha256"], hashlib.sha256(self.record.read_bytes()).hexdigest())
        self.assertEqual(statement["predicateType"],
                         "https://github.com/BichengWang/ai-decision-system/predicate/decisioncontrol/record/v5")
        self.assertEqual(statement["predicate"], {"schema": load_schema("record.v5.json")["$id"]})
        self.assertEqual(envelope["signatures"][0]["keyid"], signing.key_id(signing.load_key(self.key)))

    def test_unchanged_behavior_without_the_flag(self):
        record = self.root / "plain.json"
        record.write_bytes(self.record.read_bytes())
        self.assertEqual(self.call("replay", "--record", str(record))[0], 0)

    def test_record_edited_and_rehashed_passes_checksum_but_fails_signature(self):
        document = json.loads(self.record.read_text(encoding="utf-8"))
        document["record"]["review"]["note"] = "edited after signing"
        forged = self.root / "forged.json"
        forged.write_text(json.dumps(rehash_record(document), indent=2) + "\n", encoding="utf-8")
        Path(str(forged) + ".dsse.json").write_bytes(Path(str(self.record) + ".dsse.json").read_bytes())
        self.assertEqual(self.call("replay", "--record", str(forged))[0], 0)
        code, _, error = self.replay(forged)
        self.assertEqual(code, 1)
        self.assertIn("different record bytes", error)

    def test_whitespace_only_change_to_the_file_breaks_the_signature(self):
        reformatted = self.root / "reformatted.json"
        reformatted.write_text(json.dumps(json.loads(self.record.read_text(encoding="utf-8"))), encoding="utf-8")
        Path(str(reformatted) + ".dsse.json").write_bytes(Path(str(self.record) + ".dsse.json").read_bytes())
        self.assertEqual(self.replay(reformatted)[0], 1)

    def test_wrong_key_exits_one(self):
        code, _, error = self.replay(key=self.other_key)
        self.assertEqual(code, 1)
        self.assertIn("no valid signature", error)

    def test_unsigned_record_exits_one_under_the_flag(self):
        unsigned = self.root / "unsigned.json"
        unsigned.write_bytes(self.record.read_bytes())
        code, _, error = self.replay(unsigned)
        self.assertEqual(code, 1)
        self.assertIn("unsigned", error)
        self.assertEqual(self.call("replay", "--record", str(unsigned))[0], 0)

    def test_explicit_signature_path(self):
        moved = self.root / "elsewhere.dsse.json"
        moved.write_bytes(Path(str(self.record) + ".dsse.json").read_bytes())
        Path(str(self.record) + ".dsse.json").unlink()
        self.assertEqual(self.replay()[0], 1)
        self.assertEqual(self.replay(None, "--signature", str(moved))[0], 0)

    def test_wrong_predicate_type_exits_one(self):
        key = signing.load_key(self.key)
        data = self.record.read_bytes()
        document = json.loads(data)
        for kind, version in (("evaluation", 2), ("record", 3), ("record", 4)):
            envelope = signing.sign(data, self.record.name, attestation.predicate_type(kind, version),
                                    attestation.predicate(kind, version), key)
            Path(str(self.record) + ".dsse.json").write_text(json.dumps(envelope), encoding="utf-8")
            with self.subTest(predicate=f"{kind}/v{version}"):
                code, _, error = self.replay()
                self.assertEqual(code, 1)
                self.assertIn("predicate type", error)
        self.assertEqual(document["record"]["schema_version"], 5)

    def test_evaluation_envelope_cannot_vouch_for_a_record_and_back(self):
        out = self.root / "evaluation"
        self.call("evaluate", "--cases", str(EXAMPLES / "evaluation-cases.jsonl"), "--policy",
                  str(EXAMPLES / "policy.json"), "--out", str(out), "--sign-key", str(self.key))
        evaluation = out / "evaluation.json"
        self.assertTrue((out / "evaluation.json.dsse.json").is_file())
        code, output, _ = self.call("replay-evaluation", "--record", str(evaluation), "--require-signature",
                                    "--key", str(self.key))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["valid"], True)
        swapped = self.root / "swapped.json"
        swapped.write_bytes(evaluation.read_bytes())
        Path(str(swapped) + ".dsse.json").write_bytes((out / "evaluation.json.dsse.json").read_bytes())
        self.assertEqual(self.call("replay-evaluation", "--record", str(swapped), "--require-signature",
                                   "--key", str(self.key))[0], 0)
        self.assertEqual(self.replay(swapped)[0], 2)  # not a record: input error before any signature check
        statement = json.loads(base64.b64decode(json.loads(
            (out / "evaluation.json.dsse.json").read_text(encoding="utf-8"))["payload"]))
        self.assertTrue(statement["predicateType"].endswith("/evaluation/v2"))
        Path(str(evaluation) + ".dsse.json").write_bytes(Path(str(self.record) + ".dsse.json").read_bytes())
        self.assertEqual(self.call("replay-evaluation", "--record", str(evaluation), "--require-signature",
                                   "--key", str(self.key))[0], 1)

    def test_evaluation_edited_and_rehashed_fails_signature(self):
        out = self.root / "evaluation"
        self.call("evaluate", "--cases", str(EXAMPLES / "evaluation-cases.jsonl"), "--policy",
                  str(EXAMPLES / "policy.json"), "--out", str(out), "--sign-key", str(self.key))
        document = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
        document["sha256"] = "0" * 64
        forged = self.root / "forged-evaluation.json"
        forged.write_text(json.dumps(document), encoding="utf-8")
        Path(str(forged) + ".dsse.json").write_bytes((out / "evaluation.json.dsse.json").read_bytes())
        self.assertEqual(self.call("replay-evaluation", "--record", str(forged), "--require-signature",
                                   "--key", str(self.key))[0], 1)

    def test_malformed_envelope_exits_one(self):
        bad = {
            "not json": "{nope",
            "not an object": "[]",
            "wrong payload type": json.dumps({"payloadType": "text/plain", "payload": "", "signatures": []}),
            "payload not base64": json.dumps({"payloadType": signing.PAYLOAD_TYPE, "payload": "***", "signatures": []}),
            "missing signatures": json.dumps({"payloadType": signing.PAYLOAD_TYPE, "payload": ""}),
            "signatures not a list": json.dumps({"payloadType": signing.PAYLOAD_TYPE, "payload": "", "signatures": 7}),
            "payload not a statement": json.dumps(self.forge_payload(b"[]")),
            "payload not json": json.dumps(self.forge_payload(b"\xff")),
        }
        envelope_file = Path(str(self.record) + ".dsse.json")
        for name, text in bad.items():
            envelope_file.write_text(text, encoding="utf-8")
            with self.subTest(name):
                self.assertEqual(self.replay()[0], 1)

    def forge_payload(self, payload):
        """An envelope with a valid HMAC over a payload that is not an in-toto statement."""
        key = signing.load_key(self.key)
        import hashlib
        import hmac
        signature = hmac.new(key, signing.pae(signing.PAYLOAD_TYPE, payload), hashlib.sha256).digest()
        return {"payloadType": signing.PAYLOAD_TYPE, "payload": base64.b64encode(payload).decode(),
                "signatures": [{"keyid": signing.key_id(key), "sig": base64.b64encode(signature).decode()}]}


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
            "high surrogate digest": signed({**statement, "subject": [{"name": "x", "digest": {"sha256": "\ud800"}}]}),
            "low surrogate digest": signed({**statement, "subject": [{"name": "x", "digest": {"sha256": "\udc00" * 64}}]}),
            "uppercase hex digest": signed({**statement, "subject": [
                {"name": "x", "digest": {"sha256": statement["subject"][0]["digest"]["sha256"].upper()}}]}),
            "63 character digest": signed({**statement, "subject": [
                {"name": "x", "digest": {"sha256": statement["subject"][0]["digest"]["sha256"][:63]}}]}),
            "65 character digest": signed({**statement, "subject": [
                {"name": "x", "digest": {"sha256": statement["subject"][0]["digest"]["sha256"] + "0"}}]}),
            "deeply nested list digest": signed(json.dumps({**statement, "subject": [
                {"name": "x", "digest": {"sha256": "NESTED"}}]}).encode().replace(
                    b'"NESTED"', b"[" * 100000 + b"]" * 100000)),
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

    def test_null_and_odd_typed_signature_fields_exit_one(self):
        envelope_file = Path(str(self.record) + ".dsse.json")
        good = json.loads(envelope_file.read_text(encoding="utf-8"))
        key = signing.load_key(self.key)
        cases = {name: {**good, "signatures": entries} for name, entries in self.sig_field_variants(good).items()}
        cases.update({"payload is a number": {**good, "payload": 5}, "payload is null": {**good, "payload": None},
                      "payload is a list": {**good, "payload": ["a"]}, "payload is non-ASCII": {**good, "payload": "\u00e9"}})
        cases.update(self.odd_signed_envelopes(good, key))
        for name, envelope in cases.items():
            envelope_file.write_text(json.dumps(envelope), encoding="utf-8")
            with self.subTest(name):
                code, _, error = self.replay()
                self.assertEqual(code, 1, error)
                self.assertNotIn("Traceback", error)
        envelope_file.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.replay()[0], 0)

    def test_export_with_a_bad_key_creates_no_database(self):
        for name, key in (("missing", self.root / "nope.key"), ("short", self.root / "short.key")):
            key.parent.mkdir(exist_ok=True)
            if name == "short":
                key.write_text("abcd\n", encoding="ascii")
            db = self.root / f"{name}.sqlite3"
            out = self.root / f"{name}-record.json"
            with self.subTest(key=name):
                code, _, _ = self.call("--db", str(db), "export", "any-id", "--out", str(out), "--sign-key", str(key))
                self.assertEqual(code, 2)
                self.assertFalse(db.exists())
                self.assertFalse(out.exists())
        db = self.root / "no-out.sqlite3"
        self.assertEqual(self.call("--db", str(db), "export", "any-id", "--sign-key", str(self.key))[0], 2)
        self.assertFalse(db.exists())

    def test_bad_key_file_exits_two(self):
        missing = self.root / "missing.key"
        short = self.root / "short.key"
        short.write_text("abcd\n", encoding="ascii")
        garbage = self.root / "garbage.key"
        garbage.write_text("not hex at all\n", encoding="ascii")
        binary = self.root / "binary.key"
        binary.write_bytes(b"\xff\xfe\x00")
        for key in (missing, short, garbage, binary):
            with self.subTest(key=key.name):
                self.assertEqual(self.replay(key=key)[0], 2)
        out = self.root / "should-not-exist"
        self.assertEqual(self.call("demo", "--out", str(out), "--sign-key", str(short))[0], 2)
        self.assertFalse(out.exists())

    def test_key_generation_is_mode_0600_and_never_overwrites(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        before = self.key.read_bytes()
        code, _, error = self.call("keygen", str(self.key))
        self.assertEqual(code, 2)
        self.assertIn("exists", error)
        self.assertEqual(self.key.read_bytes(), before)
        link = self.root / "link.key"
        link.symlink_to(self.root / "dangling.key")
        self.assertEqual(self.call("keygen", str(link))[0], 2)
        self.assertFalse((self.root / "dangling.key").exists())
        self.assertGreaterEqual(len(bytes.fromhex(self.key.read_text().strip())), 32)
        self.assertNotEqual(self.key.read_bytes(), self.other_key.read_bytes())

    def test_flag_combinations_are_input_errors(self):
        record = str(self.record)
        cases = [
            ["--key", str(self.key)],
            ["--signature", "x.dsse.json"],
            ["--sigstore-bundle", "b.json"],
            ["--require-signature"],
            ["--require-signature", "--key", str(self.key), "--sigstore-bundle", "b.json"],
            ["--require-signature", "--key", str(self.key), "--certificate-identity", "id"],
            ["--require-signature", "--sigstore-bundle", "b.json"],
            ["--require-signature", "--sigstore-bundle", "b.json", "--certificate-identity", "id"],
            ["--require-signature", "--sigstore-bundle", "b.json", "--signature", "s", "--certificate-identity", "i",
             "--certificate-oidc-issuer", "u"],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertEqual(self.call("replay", "--record", record, *extra)[0], 2)

    def test_export_signs_the_file_and_does_not_overwrite(self):
        out = self.root / "exports"
        out.mkdir()
        db = str(self.root / "queue.sqlite3")
        call = lambda *args: self.call("--db", db, *args)
        self.assertEqual(call("ticket-create", "--ticket-id", "T1", "--department", "intake")[0], 0)
        proposal = self.root / "proposal.json"
        proposal.write_text(json.dumps({"action": "reassign_ticket", "ticket_id": "T1", "destination": "support",
                                        "probability": 0.95, "model": "hand-authored", "question_version": "q1"}))
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"version": "p1", "allowed_destinations": ["support"],
                                      "review_destinations": [], "reviewers": ["alice"], "min_probability": 0.8}))
        decision = json.loads(call("submit", "--proposal", str(proposal), "--policy", str(policy),
                                   "--proposed-by", "proposer")[1])["id"]
        target = out / "record.json"
        self.assertEqual(call("export", decision)[0], 0)
        self.assertEqual(call("export", decision, "--sign-key", str(self.key))[0], 2)
        self.assertEqual(call("export", decision, "--out", str(target), "--sign-key", str(self.key))[0], 0)
        self.assertEqual(self.replay(target)[0], 0)
        stored = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(stored, export_record(stored["record"]))
        before = (target.read_bytes(), Path(str(target) + ".dsse.json").read_bytes())
        self.assertEqual(call("export", decision, "--out", str(target), "--sign-key", str(self.key))[0], 2)
        self.assertEqual((target.read_bytes(), Path(str(target) + ".dsse.json").read_bytes()), before)
        # An existing envelope blocks signed export without touching the new record file.
        lone = out / "lone.json"
        Path(str(lone) + ".dsse.json").write_text("{}", encoding="utf-8")
        self.assertEqual(call("export", decision, "--out", str(lone), "--sign-key", str(self.key))[0], 2)
        self.assertFalse(lone.exists())

    def test_signing_failure_leaves_no_half_signed_export(self):
        out = self.root / "exports"
        out.mkdir()
        db = str(self.root / "queue.sqlite3")
        call = lambda *args: self.call("--db", db, *args)
        call("ticket-create", "--ticket-id", "T1", "--department", "intake")
        proposal = self.root / "proposal.json"
        proposal.write_text(json.dumps({"action": "reassign_ticket", "ticket_id": "T1", "destination": "support",
                                        "probability": 0.95, "model": "m", "question_version": "q"}))
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"version": "p1", "allowed_destinations": ["support"],
                                      "review_destinations": [], "reviewers": ["a"], "min_probability": 0.8}))
        decision = json.loads(call("submit", "--proposal", str(proposal), "--policy", str(policy),
                                   "--proposed-by", "p")[1])["id"]
        target = out / "record.json"
        with mock.patch("decisioncontrol.attestation.render_envelope", side_effect=OSError("injected")):
            self.assertEqual(call("export", decision, "--out", str(target), "--sign-key", str(self.key))[0], 2)
        self.assertFalse(target.exists())
        self.assertEqual(call("export", decision, "--out", str(target), "--sign-key", str(self.key))[0], 0)

    def test_sigstore_path_without_cosign_exits_two_and_missing_bundle_exits_one(self):
        flags = ["--require-signature", "--certificate-identity", "https://example.test/id",
                 "--certificate-oidc-issuer", "https://issuer.test"]
        bundle = self.root / "record.sigstore.json"
        self.assertEqual(self.call("replay", "--record", str(self.record), "--sigstore-bundle", str(bundle), *flags)[0], 1)
        bundle.write_text("{}", encoding="utf-8")
        with mock.patch("decisioncontrol.signing.shutil.which", return_value=None):
            code, _, error = self.call("replay", "--record", str(self.record), "--sigstore-bundle", str(bundle), *flags)
        self.assertEqual(code, 2)
        self.assertIn("cosign", error)

    def test_sigstore_verification_delegates_to_cosign_with_the_expected_arguments(self):
        bundle = self.root / "record.sigstore.json"
        bundle.write_text("{}", encoding="utf-8")
        flags = ["--require-signature", "--sigstore-bundle", str(bundle), "--certificate-identity",
                 "https://example.test/id", "--certificate-oidc-issuer", "https://issuer.test"]
        completed = mock.Mock(returncode=0, stderr="")
        with mock.patch("decisioncontrol.signing.shutil.which", return_value="/bin/cosign"), \
                mock.patch("decisioncontrol.signing.subprocess.run", return_value=completed) as run:
            self.assertEqual(self.call("replay", "--record", str(self.record), *flags)[0], 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["/bin/cosign", "verify-blob-attestation"])
        self.assertIn("https://github.com/BichengWang/ai-decision-system/predicate/decisioncontrol/record/v5", command)
        self.assertEqual(Path(command[-1]).name, self.record.name)
        self.assertNotEqual(Path(command[-1]), self.record)
        completed = mock.Mock(returncode=1, stderr="no matching signatures")
        with mock.patch("decisioncontrol.signing.shutil.which", return_value="/bin/cosign"), \
                mock.patch("decisioncontrol.signing.subprocess.run", return_value=completed):
            code, _, error = self.call("replay", "--record", str(self.record), *flags)
        self.assertEqual(code, 1)
        self.assertIn("no matching signatures", error)

    def test_sigstore_verifies_the_same_bytes_that_replay_consumes(self):
        """A file swapped back to the signed bytes after the read must not satisfy cosign."""
        import hashlib
        signed = self.record.read_bytes()
        document = json.loads(signed)
        document["record"]["id"] = "00000000-0000-4000-8000-000000000000"
        forged = json.dumps(rehash_record(document), indent=2).encode() + b"\n"
        self.assertEqual(self.call("replay", "--record", str(self.record))[0], 0)
        bundle = self.root / "record.sigstore.json"
        bundle.write_text("{}", encoding="utf-8")
        flags = ["--require-signature", "--sigstore-bundle", str(bundle), "--certificate-identity", "id",
                 "--certificate-oidc-issuer", "issuer"]
        seen = []

        def fake_cosign(command, **kwargs):
            blob = Path(command[-1])
            seen.append((blob, stat.S_IMODE(blob.parent.stat().st_mode), stat.S_IMODE(blob.stat().st_mode)))
            ok = hashlib.sha256(blob.read_bytes()).digest() == hashlib.sha256(signed).digest()
            return mock.Mock(returncode=0 if ok else 1, stderr="" if ok else "digest mismatch")

        real_describe = attestation.describe

        def swap_back_after_read(*args, **kwargs):
            self.record.write_bytes(signed)  # cosign's later read of the path would see signed bytes
            return real_describe(*args, **kwargs)

        self.record.write_bytes(forged)
        self.assertEqual(self.call("replay", "--record", str(self.record))[0], 0)  # forged but self-consistent
        with mock.patch("decisioncontrol.signing.shutil.which", return_value="/bin/cosign"), \
                mock.patch("decisioncontrol.signing.subprocess.run", side_effect=fake_cosign), \
                mock.patch("decisioncontrol.attestation.describe", side_effect=swap_back_after_read):
            code, out, error = self.call("replay", "--record", str(self.record), *flags)
        self.assertEqual(code, 1, out)
        self.assertIn("digest mismatch", error)
        blob, directory_mode, file_mode = seen[0]
        self.assertNotEqual(blob, self.record)
        self.assertEqual((directory_mode, file_mode), (0o700, 0o600))
        self.assertFalse(blob.exists())
        # Unswapped signed bytes still verify through the private copy.
        self.record.write_bytes(signed)
        with mock.patch("decisioncontrol.signing.shutil.which", return_value="/bin/cosign"), \
                mock.patch("decisioncontrol.signing.subprocess.run", side_effect=fake_cosign):
            self.assertEqual(self.call("replay", "--record", str(self.record), *flags)[0], 0)

    def test_hmac_verifies_and_replays_one_snapshot(self):
        signed = self.record.read_bytes()
        document = json.loads(signed)
        document["record"]["id"] = "00000000-0000-4000-8000-000000000000"
        forged = json.dumps(rehash_record(document), indent=2).encode() + b"\n"
        self.record.write_bytes(forged)
        real_describe = attestation.describe

        def swap_back_after_read(*args, **kwargs):
            self.record.write_bytes(signed)
            return real_describe(*args, **kwargs)

        with mock.patch("decisioncontrol.attestation.describe", side_effect=swap_back_after_read):
            self.assertEqual(self.replay()[0], 1)
        self.record.write_bytes(signed)
        self.assertEqual(self.replay()[0], 0)

    def test_predicate_command_writes_the_attest_blob_predicate(self):
        pred = self.root / "pred.json"
        code, out, _ = self.call("predicate", "--record", str(self.record), "--out", str(pred))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(pred.read_text()), {"schema": load_schema("record.v5.json")["$id"]})
        self.assertEqual(json.loads(out)["predicate_type"], attestation.predicate_type("record", 5))
        self.assertEqual(self.call("predicate", "--record", str(self.record), "--out", str(pred))[0], 2)
        document = json.loads(self.record.read_text())
        document["record"]["schema_version"] = 9
        bad = self.root / "bad.json"
        bad.write_text(json.dumps(document))
        self.assertEqual(self.call("predicate", "--record", str(bad), "--out", str(self.root / "p2.json"))[0], 2)

    def test_every_supported_schema_has_a_predicate_naming_its_schema_file(self):
        for kind, versions in attestation.SUPPORTED.items():
            for version in versions:
                with self.subTest(kind=kind, version=version):
                    self.assertEqual(attestation.predicate(kind, version)["schema"],
                                     load_schema(f"{kind}.v{version}.json")["$id"])

    def test_signing_module_is_the_shared_reference(self):
        source = Path(signing.__file__).read_text(encoding="utf-8")
        self.assertIn("from .jcs import canonicalize", source)
        self.assertIn("def verify_sigstore", source)


if __name__ == "__main__":
    unittest.main()
