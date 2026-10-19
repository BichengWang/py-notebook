# Decision model evaluation: FAIL

- evaluation.json SHA-256: `3ec938a8f2eb388bd44dcd3d6d3746201dd33070266d7f1fc8af33820ac244cc`
- jevdecision 0.1.0; backend jev; model jev-example; source live
- 3 cases, 1 answered, 2 errors (rate 0.6667)

| Question | Type | n | Metrics |
|---|---|---:|---|
| refund | noul | 1 | accuracy 1, accuracy_lower 0.2065, accuracy_upper 1, brier 0.0064, log_loss 0.08338, ece 0.08, base_rate 0, mean_probability 0.08, refusals 0, refusal_rate 0 |
| department | choice | 1 | accuracy 1, accuracy_lower 0.2065, accuracy_upper 1, brier 0.035, log_loss 0.1625, ece 0.15, refusals 0, refusal_rate 0 |
| frustration | score | 1 | accuracy 1, accuracy_lower 0.2065, accuracy_upper 1, within_one 1, mae 0.05, brier 0.035, log_loss 0.1625, ece 0.15, refusals 0, refusal_rate 0 |

| Requirement | Bound | Value | Result |
|---|---|---:|---|
| error_rate | max 0 | 0.6667 | FAIL |

Errors:

- `t02`: HTTP 500 from provider
- `t03`: answers['refund']: probability 4.0 is outside [0, 1]
