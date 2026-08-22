# Security Policy

## Supported state

Aether Quant is a **research project**, not production trading
infrastructure. There is a single maintained branch: `main`. Only issues
reproducible against `main` are addressed; no other versions or branches
receive security fixes.

## Scope

In scope — please report:

- **Credential leakage**: secrets, API keys, broker credentials, tokens, or
  connection strings committed to the repo, logged by default, written to
  artifacts/audit trails in plaintext, or exposed via the FastAPI server.
- **Unsafe code execution paths**: injection through config values, CLI
  arguments, fetched data, or web inputs; arbitrary file read/write;
  anything that lets untrusted input become code or shell.
- **Dependency vulnerabilities** in anything under `requirements/*.txt`.
- **Trading-safety machinery bypassable**:
  `risk/kill_switch.py`, `execution/reconciliation.py`,
  `retraining/auto_rollback.py`, and the trade-lock override path. A bug
  that lets a tripped kill switch be silently ignored, reconciliation
  report false-clean, or rollback fail without surfacing is a security
  issue for this project.

Out of scope:

- **Results and backtest claims.** Disputes about Sharpe ratios, offline
  evaluation gaps, or whether the model is any good belong in issues and
  `development/Problems.md`, not here.
- **Interactive Brokers live-trading risk.** The project is documented as
  not paper/live-deployable (`README.md` → Current Status / Known
  Limitations); IB has never been tested against a real Gateway. Do not run
  it live, and do not report losses from doing so.
- **Any financial losses from using this code.** It exists to test a thesis;
  it carries no warranty.

## Reporting

Report privately. For exploitable bugs, do **not** open a public issue,
PR, or discussion describing the vulnerability.

Preferred channels, in order:

1. A private [GitHub Security Advisory](https://github.com/leon1706-lol/Aether-quant/security/advisories/new)
   ("Report a vulnerability") on this repository.
2. Direct contact with the maintainers (via the GitHub profile of the
   primary maintainer).

Include: affected files/modules on `main`, reproduction steps or a minimal
proof of concept, and your assessment of impact. Response is best-effort
within roughly one week; you will get an acknowledgement, then updates as
triage proceeds. Please allow time for a fix before any public disclosure.

## Secrets handling convention

Secrets never belong in the repo. Follow the existing pattern from
`.env.compose.example` / `.env.live.example`: copy the example to an
untracked, gitignored `.env`, fill in real values there, and reference them
as environment variables (`${VAR}` substitutions in `docker-compose.yml`).
Example files ship with empty placeholder values only. If you believe a
real credential was ever committed, rotate it first, then report it.
