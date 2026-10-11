import unittest

from decisioncontrol import DecisionError, Recommendation, RoutingPolicy, Ticket, Verdict, evaluate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.ticket = Ticket("t1", "unassigned")
        self.policy = RoutingPolicy("routing/v1", ("technical", "billing"), ("billing",), ("operator",), 0.8)

    def proposal(self, **changes):
        fields = {"action": "reassign_ticket", "ticket_id": "t1", "destination": "technical",
                  "probability": 0.95, "model": "recorded/v1", "question_version": "route/v1"}
        fields.update(changes)
        return Recommendation.from_dict(fields)

    def test_missing_probability_never_becomes_certainty(self):
        raw = self.proposal().to_dict()
        del raw["probability"]
        proposal = Recommendation.from_dict(raw)
        result = evaluate(proposal, self.ticket, self.policy)
        self.assertEqual(result.verdict, Verdict.ABSTAIN)
        self.assertEqual(result.reasons, ("probability_unknown",))

    def test_policy_denial_outranks_model_uncertainty(self):
        result = evaluate(self.proposal(destination="administrators", probability=None, refused=True),
                          self.ticket, self.policy)
        self.assertEqual(result.verdict, Verdict.DENY)

    def test_model_cannot_authorize_another_tool(self):
        result = evaluate(self.proposal(action="issue_refund", probability=1.0), self.ticket, self.policy)
        self.assertEqual(result.verdict, Verdict.DENY)
        self.assertEqual(result.reasons, ("action_not_permitted",))

    def test_proposal_cannot_change_another_ticket(self):
        self.assertEqual(evaluate(self.proposal(ticket_id="t2"), self.ticket, self.policy).verdict, Verdict.DENY)

    def test_noop_reassignment_is_denied(self):
        assigned = Ticket("t1", "technical", 2)
        self.assertEqual(evaluate(self.proposal(), assigned, self.policy).verdict, Verdict.DENY)

    def test_probability_threshold_includes_its_boundary(self):
        self.assertEqual(evaluate(self.proposal(probability=0.799), self.ticket, self.policy).verdict,
                         Verdict.ABSTAIN)
        self.assertEqual(evaluate(self.proposal(probability=0.8), self.ticket, self.policy).verdict, Verdict.ALLOW)

    def test_high_probability_does_not_bypass_required_review(self):
        self.assertEqual(evaluate(self.proposal(destination="billing", probability=1.0), self.ticket,
                                  self.policy).verdict, Verdict.REVIEW)

    def test_provider_refusal_blocks_otherwise_permitted_action(self):
        self.assertEqual(evaluate(self.proposal(refused=True), self.ticket, self.policy).verdict, Verdict.ABSTAIN)

    def test_invalid_probability_inputs_are_rejected(self):
        for value in (True, "0.9", float("nan"), float("inf"), -0.1, 1.1, 10 ** 1000):
            with self.subTest(value=repr(value)):
                with self.assertRaises(DecisionError):
                    self.proposal(probability=value)

    def test_model_cannot_smuggle_policy_fields(self):
        raw = self.proposal().to_dict()
        raw["reviewers"] = ["attacker"]
        with self.assertRaises(DecisionError):
            Recommendation.from_dict(raw)

    def test_policy_cannot_review_a_prohibited_destination(self):
        with self.assertRaises(DecisionError):
            RoutingPolicy("routing/v2", ("technical",), ("billing",), ("operator",))

    def test_boolean_revision_is_not_a_valid_ticket_snapshot(self):
        with self.assertRaises(DecisionError):
            Ticket("t1", "unassigned", True)


if __name__ == "__main__":
    unittest.main()
