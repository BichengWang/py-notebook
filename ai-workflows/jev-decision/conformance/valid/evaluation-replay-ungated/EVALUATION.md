# Decision model evaluation: UNGATED

- evaluation.json SHA-256: `5d6577d705cf4c77a2c037ad1b7b9455fdba471f849bb09246e6f3c040871cb6`
- jevdecision 0.1.0; backend jev; model jev-example; source replay
- 12 cases, 12 answered, 0 errors (rate 0)

- Replay origin is unverified; response model fields are supplied metadata, not proof of provider output.

- No explicit question metric bounds: metrics are descriptive, not a quality gate.

| Question | Type | n | Metrics |
|---|---|---:|---|
| refund | noul | 12 | accuracy 0.9167, accuracy_lower 0.6461, accuracy_upper 0.9851, brier 0.03464, log_loss 0.1363, ece 0.1075, base_rate 0.4167, mean_probability 0.3758, refusals 0, refusal_rate 0 |
| department | choice | 12 | accuracy 0.9167, accuracy_lower 0.6461, accuracy_upper 0.9851, brier 0.1198, log_loss 0.2456, ece 0.1158, refusals 0, refusal_rate 0 |
| frustration | score | 12 | accuracy 1, accuracy_lower 0.7575, accuracy_upper 1, within_one 1, mae 0.1842, brier 0.1261, log_loss 0.2742, ece 0.2275, refusals 0, refusal_rate 0 |

| Requirement | Bound | Value | Result |
|---|---|---:|---|
| error_rate | max 0 | 0 | pass |

Incorrect answers (2; every case is in `cases.jsonl`):

- `t10` refund: expected true, got false
- `t10` department: expected "sales", got "billing"
