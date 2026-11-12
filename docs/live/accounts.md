# Accounts

One Lean process trades one brokerage account, so an account is a deployment. `accounts.json` (gitignored; `accounts.example.json` is the template) lists them:

```json
{"accounts": [
  {"id": "paper-b", "broker": "paper", "lean_environment": "live-paper", "mode": "observation",
   "risk_overrides": {"live.max_allowed_total_drawdown_pct": 0.08, "dynamic_risk.max_leverage": 0.5}}
]}
```

- **Only tighter.** An override may only tighten the base config:
    - a lower drawdown limit, leverage, or kill-switch maximum
    - a higher kill-switch minimum Sharpe
    - live orders switched off
    - a lower runtime mode

    Anything looser is refused when the registry is read and again when it is applied (proved in `AccountOverrides.lean`).
- **The default account is today's deployment.** Resolving it changes nothing: the same config, the same paths, and no `account_id` in the audit payloads.
- **A named account** reads its secrets from `AETHER_<ID>_*`, writes its state and overrides under `state/accounts/<id>/`, and tags every audit event with its id.

```bash
aq accounts validate                     # every id, broker, environment and override checked against config.json
aq accounts status                       # each account's secrets (resolved or not) and last state
aq render-lean-config --account paper-b
aq live up --account paper-b             # docker compose run, AQ_ACCOUNT=paper-b, restart unless-stopped
aq trade-lock --on --account paper-b     # its own override file, not config.json
aq evaluate --account paper-b            # the offline evaluation on that account's limits (the same apply_risk_overrides)
aq live-readiness --account paper-b
```

`AQ_ACCOUNT` (or the Lean parameter `aq-account`) selects the account inside `main.py`. An unknown id stops the deployment rather than running it on another account's settings.
