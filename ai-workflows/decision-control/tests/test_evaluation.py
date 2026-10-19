from copy import deepcopy
import hashlib
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from decisioncontrol import (DecisionError, EvaluationCase, Recommendation, RoutingPolicy, Ticket,
                             evaluate_cases, load_cases, replay_evaluation, write_evaluation)
from decisioncontrol.evaluation import parse_envelope
from decisioncontrol.evidence import RecordMismatch
from decisioncontrol.jcs import canonicalize
from dc_support import python_json_v1, rehash_report


class PolicyEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.policy = RoutingPolicy("p1", ("support", "engineering"), ("engineering",), ("alice",), 0.8)

    def case(self, name, destination="support", probability=0.95, safe=True, required=False,
             correct=None, outcome=None):
        return EvaluationCase(name, Ticket(name, "intake"),
                              Recommendation("reassign_ticket", name, destination, probability,
                                             "supplied-test-response", "routing/v1"),
                              safe, required, correct or destination, outcome)

    def envelope(self, report):
        return rehash_report({"report": report, "sha256": ""})

    def test_metrics_use_their_own_exposure_denominators(self):
        cases = [
            self.case("auto-good"), self.case("auto-unsafe", safe=False),
            self.case("auto-review-bypass", required=True),
            self.case("auto-wrong", correct="engineering"),
            self.case("review-good", "engineering", required=True, outcome="APPROVED"),
            self.case("review-unsafe", "engineering", safe=False, required=True, outcome="APPROVED"),
            self.case("review-extra", "engineering"), self.case("unknown", probability=None),
            self.case("low", probability=0.2), self.case("deny", "finance", safe=False),
        ]
        report = evaluate_cases(cases, self.policy)
        expected = {
            "auto_allow_rate": (4, 10), "unsafe_auto_allow_rate": (2, 4),
            "auto_route_error_rate": (1, 4), "review_rate": (3, 10),
            "abstain_rate": (2, 10), "deny_rate": (1, 10),
            "required_review_recall": (2, 3), "review_precision": (2, 3),
            "incorrect_approval_rate": (1, 2), "review_observation_rate": (2, 3),
        }
        for name, (numerator, denominator) in expected.items():
            with self.subTest(metric=name):
                metric = report["metrics"][name]
                self.assertEqual((metric["numerator"], metric["denominator"]), (numerator, denominator))
                self.assertAlmostEqual(metric["value"], numerator / denominator)
        self.assertEqual(report["disposition"], "UNGATED")

    def test_approval_error_includes_wrong_destination_even_if_safe(self):
        case = self.case("wrong-approval", "engineering", required=True,
                         correct="support", outcome="APPROVED")
        report = evaluate_cases([case], self.policy)
        self.assertEqual(report["metrics"]["incorrect_approval_rate"]["value"], 1)
        self.assertTrue(report["case_results"][0]["approval_incorrect"])

    def test_review_observations_do_not_score_automatic_or_rejected_actions_as_approvals(self):
        cases = [self.case("auto", outcome="APPROVED"),
                 self.case("rejected", "engineering", safe=False, required=True, outcome="REJECTED")]
        report = evaluate_cases(cases, self.policy)
        self.assertEqual(report["metrics"]["review_observation_rate"]["value"], 1)
        self.assertIsNone(report["metrics"]["incorrect_approval_rate"]["value"])
        self.assertEqual(report["metrics"]["incorrect_approval_rate"]["denominator"], 0)

    def test_zero_exposure_is_unmeasured_and_cannot_pass_a_zero_error_gate(self):
        cases = [self.case("denied", "finance", safe=False)]
        requirements = {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"max": 0}}}
        report = evaluate_cases(cases, self.policy, requirements)
        metric = report["metrics"]["unsafe_auto_allow_rate"]
        self.assertEqual((metric["value"], metric["lower"], metric["upper"]), (None, None, None))
        self.assertEqual(report["disposition"], "FAIL")
        self.assertFalse(next(g for g in report["gates"] if g["metric"] == "unsafe_auto_allow_rate")["passed"])

    def test_zero_observed_errors_still_have_a_nonzero_uncertainty_upper_bound(self):
        report = evaluate_cases([self.case(f"case-{i}") for i in range(10)], self.policy)
        metric = report["metrics"]["unsafe_auto_allow_rate"]
        self.assertEqual(metric["value"], 0)
        self.assertEqual(metric["lower"], 0)
        self.assertAlmostEqual(metric["upper"], 0.2775327998628892)

    def test_upper_bound_gate_requires_evidence_not_only_zero_observed_errors(self):
        requirements = {"min_cases": 10, "bounds": {
            "unsafe_auto_allow_rate": {"max": 0.05, "statistic": "upper", "min_denominator": 20}}}
        small = evaluate_cases([self.case(f"small-{i}") for i in range(40)], self.policy, requirements)
        enough = evaluate_cases([self.case(f"large-{i}") for i in range(100)], self.policy, requirements)
        self.assertEqual(small["metrics"]["unsafe_auto_allow_rate"]["value"], 0)
        self.assertEqual(small["disposition"], "FAIL")
        self.assertEqual(enough["disposition"], "PASS")

    def test_minimum_denominator_is_distinct_from_total_case_count(self):
        cases = [self.case("auto")] + [self.case(f"deny-{i}", "finance", safe=False) for i in range(20)]
        requirements = {"min_cases": 20, "bounds": {
            "unsafe_auto_allow_rate": {"max": 0, "min_denominator": 2}}}
        report = evaluate_cases(cases, self.policy, requirements)
        self.assertEqual(report["cases"], 21)
        self.assertEqual(report["disposition"], "FAIL")
        self.assertTrue(next(g for g in report["gates"] if g["metric"] == "cases")["passed"])

    def test_total_sample_gate_can_block_otherwise_satisfied_metric_bounds(self):
        requirements = {"min_cases": 3, "bounds": {"unsafe_auto_allow_rate": {"max": 0}}}
        report = evaluate_cases([self.case("one"), self.case("two")], self.policy, requirements)
        self.assertEqual(report["disposition"], "FAIL")
        self.assertFalse(next(g for g in report["gates"] if g["metric"] == "cases")["passed"])
        self.assertTrue(next(g for g in report["gates"] if g["metric"] == "unsafe_auto_allow_rate")["passed"])

    def test_bounds_include_the_boundary_and_can_use_lower_confidence(self):
        cases = [self.case("safe"), self.case("unsafe", safe=False)]
        exact = {"min_cases": 2, "bounds": {"unsafe_auto_allow_rate": {"min": 0.5, "max": 0.5}}}
        self.assertEqual(evaluate_cases(cases, self.policy, exact)["disposition"], "PASS")
        reviews = [self.case("r1", "engineering", required=True),
                   self.case("r2", "engineering", required=True)]
        lower = {"min_cases": 2, "bounds": {"required_review_recall": {"min": 0.8, "statistic": "lower"}}}
        self.assertEqual(evaluate_cases(reviews, self.policy, lower)["metrics"]["required_review_recall"]["value"], 1)
        self.assertEqual(evaluate_cases(reviews, self.policy, lower)["disposition"], "FAIL")

    def test_duplicate_cases_and_empty_inputs_cannot_manufacture_evidence(self):
        case = self.case("same")
        for cases in ([], [case, case], [case, {}]):
            with self.subTest(cases=cases):
                with self.assertRaises(DecisionError):
                    evaluate_cases(cases, self.policy)

    def test_invalid_labels_and_requirements_are_rejected(self):
        raw = self.case("case").to_dict()
        raw["labels"]["requires_review"] = 1
        with self.assertRaises(DecisionError):
            EvaluationCase.from_dict(raw)
        with self.assertRaises(DecisionError):
            replace(self.case("case"), review_outcome="UNKNOWN")
        invalid = [
            {"min_cases": True, "bounds": {"unsafe_auto_allow_rate": {"max": 0}}},
            {"min_cases": 1, "bounds": {}},
            {"min_cases": 1, "bounds": {"made_up_metric": {"max": 0}}},
            {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {}}},
            {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"max": float("nan")}}},
            {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"max": 0, "statistic": "median"}}},
            {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"min": 0.8, "max": 0.2}}},
            {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"max": 0, "min_denominator": 0}}},
        ]
        for requirements in invalid:
            with self.subTest(requirements=requirements):
                with self.assertRaises(DecisionError):
                    evaluate_cases([self.case("one")], self.policy, requirements)

    def test_invalid_json_lines_are_not_silently_excluded_from_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(json.dumps(self.case("valid").to_dict()) + "\n{broken\n", encoding="utf-8")
            with self.assertRaises(DecisionError):
                load_cases(path)

    def test_failed_reports_replay_and_existing_evidence_is_preserved(self):
        report = evaluate_cases([self.case("unsafe", safe=False)], self.policy,
                                {"min_cases": 1, "bounds": {"unsafe_auto_allow_rate": {"max": 0}}})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evaluation"
            write_evaluation(report, out)
            before = (out / "evaluation.json").read_bytes()
            replayed = replay_evaluation(json.loads(before))
            self.assertEqual(replayed, {"valid": True, "cases": 1, "disposition": "FAIL"})
            with self.assertRaises(DecisionError):
                write_evaluation(evaluate_cases([self.case("safe")], self.policy), out)
            self.assertEqual((out / "evaluation.json").read_bytes(), before)

    def test_checksum_and_semantic_replay_reject_inconsistent_reports(self):
        report = evaluate_cases([self.case("unsafe", safe=False)], self.policy)
        envelope = self.envelope(deepcopy(report))
        envelope["report"]["metrics"]["unsafe_auto_allow_rate"]["value"] = 0
        with self.assertRaises(DecisionError):
            replay_evaluation(envelope)
        with self.assertRaises(DecisionError):
            replay_evaluation(self.envelope(envelope["report"]))
        changed = deepcopy(report)
        changed["case_results"][0]["case"]["labels"]["safe_to_execute"] = True
        with self.assertRaises(DecisionError):
            replay_evaluation(self.envelope(changed))

    def test_schema_two_digest_is_rfc8785_and_schema_one_keeps_python_json(self):
        cases = [self.case("one"), self.case("two", "engineering", outcome="APPROVED")]
        current = evaluate_cases(cases, self.policy)
        legacy = evaluate_cases(cases, self.policy, schema_version=1)
        self.assertEqual((current["schema_version"], legacy["schema_version"]), (2, 1))
        self.assertEqual({**current, "schema_version": 1}, legacy)
        self.assertNotEqual(canonicalize(current), python_json_v1(current))
        for report, form in ((current, canonicalize), (legacy, python_json_v1)):
            envelope = {"report": report, "sha256": hashlib.sha256(form(report)).hexdigest()}
            self.assertEqual(replay_evaluation(envelope)["cases"], 2)
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(write_evaluation(report, Path(tmp) / "out")["sha256"], envelope["sha256"])
        wrong = {"report": current, "sha256": hashlib.sha256(python_json_v1(current)).hexdigest()}
        with self.assertRaises(RecordMismatch):
            replay_evaluation(wrong)
        wrong = {"report": legacy, "sha256": hashlib.sha256(canonicalize(legacy)).hexdigest()}
        with self.assertRaises(RecordMismatch):
            replay_evaluation(wrong)

    def test_unsupported_schema_is_rejected_for_producer_and_replay(self):
        with self.assertRaises(DecisionError):
            evaluate_cases([self.case("one")], self.policy, schema_version=3)
        report = evaluate_cases([self.case("one")], self.policy)
        report["schema_version"] = 3
        with self.assertRaises(DecisionError) as raised:
            replay_evaluation(self.envelope(report))
        self.assertNotIsInstance(raised.exception, RecordMismatch)

    def test_schema_two_parse_rejects_duplicate_keys_but_schema_one_does_not(self):
        for schema, rejected in ((2, True), (1, False)):
            report = evaluate_cases([self.case("one")], self.policy, schema_version=schema)
            text = json.dumps(self.envelope(report))
            duplicate = text.replace('"kind": "policy_evaluation"', '"kind": "x", "kind": "policy_evaluation"', 1)
            self.assertNotEqual(text, duplicate)
            if rejected:
                with self.assertRaisesRegex(DecisionError, "duplicate"):
                    parse_envelope(duplicate)
            else:
                self.assertEqual(replay_evaluation(parse_envelope(duplicate))["cases"], 1)

    def test_future_evaluation_schema_is_not_silently_reinterpreted(self):
        report = evaluate_cases([self.case("one")], self.policy)
        report["schema_version"] = 3
        with self.assertRaises(DecisionError):
            replay_evaluation(self.envelope(report))


class FloatingPointPortabilityGuard(unittest.TestCase):
    """Replay compares recomputed metrics exactly; that is only portable without libm functions.

    Wilson bounds use integer counts, + - * / (correctly rounded IEEE 754) and math.sqrt
    (correctly rounded); ``denominator ** 2`` is exact integer arithmetic (denominator is a
    count). log, exp, erf, pow on floats or an inverse CDF come from the platform libm and may
    differ in the last digits. The guard resolves ``import math as m`` and ``from math import``,
    and allows ``**`` only as ``denominator ** 2``; it cannot prove types, so a float
    ``denominator`` would not be caught.
    """
    BANNED_MODULES = {"statistics", "numpy", "scipy", "cmath", "random", "decimal", "fractions"}
    ALLOWED_MATH = {"sqrt"}

    def tree(self):
        import ast
        source = Path(__file__).resolve().parents[1] / "decisioncontrol" / "evaluation.py"
        return ast.parse(source.read_text(encoding="utf-8"))

    def test_evaluation_module_only_uses_correctly_rounded_math(self):
        import ast
        tree = self.tree()
        aliases, imported = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(root, self.BANNED_MODULES)
                    self.assertNotEqual(root, "importlib")
                    if root == "math":
                        aliases.add(alias.asname or "math")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                self.assertNotIn(root, self.BANNED_MODULES)
                self.assertNotEqual(root, "importlib")
                if root == "math":
                    imported.update(alias.name for alias in node.names)
                    self.assertTrue(all(alias.name in self.ALLOWED_MATH for alias in node.names),
                                    "only math.sqrt may be imported by name")
        self.assertTrue(aliases, "expected the math module to be imported")
        used = set(imported)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                used.add(node.attr)
            if isinstance(node, ast.Name) and node.id in aliases:
                # Any use of the module object other than attribute access (e.g. getattr(m, ...)) is rejected.
                parents = [p for p in ast.walk(tree) if any(child is node for child in ast.iter_child_nodes(p))]
                self.assertTrue(all(isinstance(p, (ast.Attribute, ast.Import)) for p in parents),
                                "math may only be used through attribute access")
        self.assertIn("sqrt", used, "expected math.sqrt in the Wilson interval")
        self.assertLessEqual(used, self.ALLOWED_MATH, "evaluation replay must stay bit-portable")

    def test_evaluation_module_has_no_float_power_or_dynamic_calls(self):
        import ast
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"pow", "getattr", "eval", "exec", "__import__"})
            powers = []
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                powers.append((node.left, node.right))
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
                powers.append((node.target, node.value))
            for left, right in powers:
                # The one exact case is the integer count squared (int ** 2 is integer arithmetic).
                self.assertTrue(isinstance(left, ast.Name) and left.id == "denominator"
                                and isinstance(right, ast.Constant) and right.value == 2
                                and type(right.value) is int,
                                f"line {node.lineno}: ** is only allowed as `denominator ** 2` on an integer count")


if __name__ == "__main__":
    unittest.main()
