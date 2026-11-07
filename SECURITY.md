# Security Policy

Aether Quant is a research project with one maintained branch, `main`. Only issues reproducible there are addressed.

## In scope

- **Credential leakage:** secrets committed, logged by default, written in plaintext to artifacts or audit trails, or exposed by the API.
- **Unsafe execution:** injection through config, CLI arguments, fetched data or web inputs; arbitrary file access.
- **Dependency vulnerabilities** in `requirements/*.txt`.
- **Bypassing trading safety:** a tripped kill switch silently ignored (`risk/kill_switch.py`), reconciliation reporting false-clean (`execution/reconciliation.py`), or rollback failing silently (`retraining/auto_rollback.py`).

## Out of scope

- **Results and backtest claims:** those belong in issues.
- **Live-trading risk and financial losses.** The system is paper only and has never met a real IB Gateway ([Known Limitations](README.md#known-limitations)). It carries no warranty.

## Reporting

Report privately, not in a public issue or PR:

1. A private [GitHub Security Advisory](https://github.com/leon1706-lol/Aether-quant/security/advisories/new).
2. Or contact the maintainer through their GitHub profile.

Include the affected files, reproduction steps and your view of the impact. Responses are best-effort, within about a week. Please allow time for a fix before disclosing.

## Secrets

Secrets never belong in the repo. Copy `.env.compose.example` or `.env.live.example` to a gitignored `.env`, fill it in, and reference values as `${VAR}`. `aq secrets-check` guards commits. If a real credential was ever committed, rotate it first, then report it.
