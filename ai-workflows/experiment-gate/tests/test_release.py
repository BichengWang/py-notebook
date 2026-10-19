import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from expgate.decision import evaluate
from expgate.jcs import canonicalize
from expgate.run import main

def example():
    path = Path(__file__).resolve().parents[1] / "examples" / "offer-ranker-v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def status_of(report, metric):
    return next(row for row in report["metrics"] if row["metric"] == metric)



class ValidationReleaseTest(unittest.TestCase):
    def test_unknown_summary_and_spec_keys_exit_2(self):
        for location in ('summary', 'spec'):
            summary = example()
            target = summary if location == 'summary' else summary['metrics']['conversion']
            target['polcy' if location == 'summary' else 'sequental'] = {}
            with self.subTest(location=location), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, 'input.json')
                path.write_text(json.dumps(summary))
                with redirect_stderr(io.StringIO()) as err:
                    code = main(['--input', str(path), '--out', str(Path(tmp, 'out'))])
                self.assertEqual(code, 2)
                self.assertIn('unknown keys', err.getvalue())

    def test_undeclared_arm_metric_rejected(self):
        for arm in ('control', 'treatment'):
            summary = example()
            summary['arms'][arm]['metrics']['typo'] = {'successes': 0}
            with self.subTest(arm=arm), self.assertRaisesRegex(ValueError, 'unknown keys'):
                evaluate(summary)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, 'input.json')
                path.write_text(json.dumps(summary))
                with redirect_stderr(io.StringIO()) as err:
                    code = main(['--input', str(path), '--out', str(Path(tmp, 'out'))])
                self.assertEqual(code, 2)
                self.assertIn(arm, err.getvalue())

    def test_zero_error_guardrails_never_allow_ship(self):
        for events in (0, 1):
            summary = example()
            for arm in summary['arms'].values():
                arm['metrics']['refund_rate']['successes'] = events * arm['units']
            report = evaluate(summary)
            self.assertEqual(status_of(report, 'refund_rate')['status'], 'INCONCLUSIVE')
            self.assertEqual(report['decision'], 'HOLD')

    def test_tiny_zero_event_guardrail_is_inconclusive(self):
        summary = {
            "metrics": {
                "value": {"type": "mean", "role": "primary", "direction": "increase"},
                "harm": {"type": "proportion", "role": "guardrail", "direction": "decrease", "margin": 0.1},
            },
            "arms": {
                arm: {"units": 2, "metrics": {"value": {"mean": mean, "sd": 0.1}, "harm": {"successes": 0}}}
                for arm, mean in (("control", 1.0), ("treatment", 2.0))
            },
        }
        report = evaluate(summary)
        self.assertEqual(status_of(report, "value")["status"], "IMPROVED")
        self.assertEqual(status_of(report, "harm")["status"], "INCONCLUSIVE")
        self.assertEqual(report["decision"], "HOLD")

    def test_zero_error_mean_ratio_and_cuped_are_inconclusive(self):
        for kind in ("mean", "ratio", "cuped"):
            with self.subTest(kind=kind):
                summary = {"metrics": {"y": {"type": "ratio" if kind == "ratio" else "mean", "role": "primary", "direction": "increase"}}, "arms": {}}
                for arm, mean in (("control", 1.0), ("treatment", 2.0)):
                    if kind == "ratio":
                        stat = {"numerator": {"mean": mean, "sd": 0.0}, "denominator": {"mean": 1.0, "sd": 0.0}, "corr": 0.0}
                    else:
                        stat = {"mean": mean, "sd": 1.0 if kind == "cuped" else 0.0}
                        if kind == "cuped":
                            stat["covariate"] = {"mean": 1.0, "sd": 1.0, "corr": 1.0}
                    summary["arms"][arm] = {"units": 10, "metrics": {"y": stat}}
                report = evaluate(summary)
                self.assertEqual(report["metrics"][0]["se"], 0.0)
                self.assertEqual(report["decision"], "HOLD")
                self.assertIn("detectability cannot be inferred", report["reasons"][0])

    def test_zero_error_primary_never_significant(self):
        for c, t in ((0, 1), (1, 0), (0, 0), (1, 1)):
            summary = example()
            for arm, count in zip(summary['arms'].values(), (c, t)):
                arm['metrics']['conversion']['successes'] = count * arm['units']
            with self.subTest(c=c, t=t):
                self.assertEqual(status_of(evaluate(summary), 'conversion')['status'], 'INCONCLUSIVE')

    def test_sequential_mde_labels_current_look_approximation(self):
        summary = example()
        summary['policy']['sequential'] = {'planned_units': 200000}
        row = status_of(evaluate(summary), 'conversion')
        self.assertEqual(row['mde_basis'], 'current_look_normal_approximation')
        self.assertAlmostEqual(row['mde'], (row['z'] + 0.8416212335729143) * row['se'])


class RecordReleaseTest(unittest.TestCase):
    def verify_cli(self, *paths):
        from contextlib import redirect_stdout
        from expgate.verify import main as verify_main
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = verify_main(list(map(str, paths)))
        return code, out.getvalue() + err.getvalue()

    def test_record_embeds_input_and_canonical_digest(self):
        import hashlib
        from expgate import __version__, verify_record
        summary = example()
        summary['description'] = '例子'
        record = evaluate(summary)
        expected = hashlib.sha256(canonicalize(summary)).hexdigest()
        self.assertEqual(record['input_sha256'], expected)
        self.assertEqual(record['schema_version'], 3)
        self.assertEqual(record['produced_by'], {'name': 'expgate', 'version': __version__})
        self.assertEqual(record['input'], summary)
        self.assertEqual(verify_record(record), [])
        summary['arms']['control']['metrics']['conversion']['successes'] += 1
        self.assertNotEqual(record['input'], summary)

    def test_tampering_is_named_and_exits_1(self):
        import copy
        record = evaluate(example())
        for field in ('input', 'decision', 'reasons', 'metrics', 'policy', 'sample_ratio'):
            tampered = copy.deepcopy(record)
            if field == 'input':
                tampered['input']['arms']['control']['metrics']['conversion']['successes'] += 1
                expected = 'input_sha256'
            elif field == 'decision':
                tampered[field] = 'HOLD'
                expected = field
            else:
                tampered[field] = [] if field in ('reasons', 'metrics') else {}
                expected = field
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, 'record.json')
                path.write_text(json.dumps(tampered))
                code, message = self.verify_cli(path)
                self.assertEqual(code, 1)
                self.assertIn(expected, message)

    def test_legacy_invalid_unreadable_and_batch_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good, legacy, bad, changed = (Path(tmp, n) for n in ('good', 'legacy', 'bad', 'changed'))
            good.write_text(json.dumps(evaluate(example())))
            legacy.write_text(json.dumps({'decision': 'SHIP'}))
            bad.write_text('{')
            record = evaluate(example())
            record['decision'] = 'HOLD'
            changed.write_text(json.dumps(record))
            self.assertEqual(self.verify_cli(good)[0], 0)
            self.assertEqual(self.verify_cli(good, changed)[0], 1)
            code, message = self.verify_cli(legacy)
            self.assertEqual(code, 2)
            self.assertIn('schema 1 cannot be verified', message)
            for path in (bad, Path(tmp, 'missing')):
                self.assertEqual(self.verify_cli(path)[0], 2)
            self.assertEqual(self.verify_cli(changed, bad)[0], 2)

    def test_json_bytes_digest_is_shown_in_markdown(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            main(['--scenario', 'win', '--out', tmp])
            digest = hashlib.sha256(Path(tmp, 'decision.json').read_bytes()).hexdigest()
            self.assertIn(digest, Path(tmp, 'DECISION.md').read_text())
            self.assertEqual(self.verify_cli(Path(tmp, 'decision.json'))[0], 0)

    def test_failed_batch_write_leaves_target_untouched_and_can_retry(self):
        from unittest.mock import patch
        from expgate.run import write_record
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp, 'out')
                if existing:
                    out.mkdir()
                calls = 0
                def failing_write(report, target):
                    nonlocal calls
                    calls += 1
                    digest = write_record(report, target)
                    if calls == 2:
                        raise OSError('disk write failure')
                    return digest
                with patch('expgate.run.write_record', side_effect=failing_write), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--all-scenarios', '--out', str(out)]), 2)
                self.assertEqual(out.exists(), existing)
                if existing:
                    self.assertEqual(list(out.iterdir()), [])
                self.assertEqual(list(Path(tmp).iterdir()), [out] if existing else [])
                self.assertEqual(main(['--all-scenarios', '--out', str(out)]), 0)

    def test_boolean_cannot_impersonate_numeric_metric_content(self):
        from expgate import verify_record
        summary = example()
        for arm in summary['arms'].values():
            arm['metrics']['conversion']['successes'] = 0
        record = evaluate(summary)
        record['metrics'][0]['se'] = False
        self.assertIn('metrics', verify_record(record))

    def test_invalid_record_shapes_exit_2(self):
        record = evaluate(example())
        cases = [[], {**record, 'schema_version': 4},
                 {**record, 'schema_version': '2'},
                 {**record, 'input': []},
                 {**record, 'produced_by': {}},
                 {k: v for k, v in record.items() if k != 'metrics'}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'record.json')
            for case in cases:
                with self.subTest(case=case):
                    path.write_text(json.dumps(case))
                    self.assertEqual(self.verify_cli(path)[0], 2)
