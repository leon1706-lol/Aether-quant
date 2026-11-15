# OpenSSF Best Practices: the answers, ready to enter

The OpenSSF Scorecard's CII-Best-Practices check reads the badge level that https://www.bestpractices.dev holds for this repository: none 0, in progress 2, passing 5, silver 7, gold 10.

Registering is a sign-up, so the owner does it. An agent never creates the account (`AGENTS.md`).

**Steps:**
1. Sign in at https://www.bestpractices.dev with GitHub.
2. Choose "Add project" and enter `https://github.com/leon1706-lol/Aether-quant`.
3. Answer the passing criteria below. Each line names the evidence to paste.
4. Add the badge it gives you to the README, beside the Scorecard badge.

Status as of V6.6.7 (2026-11-14). A criterion the project does not meet is marked so; nothing here is claimed that is not true.

## Basics

| Criterion | Answer | Evidence |
|---|---|---|
| `description_good` | Met | README first section; the GitHub About text |
| `interact` | Met | README, `CONTRIBUTING.md` (how to obtain, give feedback, contribute) |
| `contribution` | Met | `CONTRIBUTING.md` |
| `contribution_requirements` | Met | `CONTRIBUTING.md` and `AGENTS.md` "Non-negotiables" (tests, ruff, 100% coverage, docs move with code) |
| `floss_license` | **Unmet** for the repository as a whole (Met for the library) | `LICENSE` and `LICENSES/`: the library and everything the wheel ships is Apache-2.0 (FLOSS); the trading system (`main.py`, the trainers, models, research scripts) is PolyForm Noncommercial 1.0.0, which forbids commercial use and so is not FLOSS. This is a MUST: while it is Unmet the badge stays "in progress" (2 on the Scorecard check) and cannot reach "passing". Answering Met would be untrue. Only a relicensing of the trading system under an OSI licence (the owner's decision, not a documentation fix) changes it. |
| `floss_license_osi` | Unmet for the whole repository (SUGGESTED, so it does not block) | Apache-2.0 is OSI-approved and covers the published package `aether-quant`; PolyForm Noncommercial 1.0.0 is not OSI-approved |
| `license_location` | Met | `LICENSE` at the top level, `REUSE.toml` per path |
| `documentation_basics` | Met | README, `docs/` (https://leon1706-lol.github.io/Aether-quant/), `RUNBOOK.md` |
| `documentation_interface` | Met | API reference generated from docstrings (`scripts/build_docs.py`, mkdocstrings) |
| `sites_https` | Met | GitHub, GitHub Pages and PyPI all serve HTTPS |
| `discussion` | Met | GitHub issues and pull requests |
| `english` | Met | |
| `maintained` | Met | `development/Changelog.md`, regular releases |

## Change control

| Criterion | Answer | Evidence |
|---|---|---|
| `repo_public` | Met | https://github.com/leon1706-lol/Aether-quant |
| `repo_track` | Met | git |
| `repo_interim` | Met | every commit on `main` is public, not only releases |
| `repo_distributed` | Met | git |
| `version_unique` | Met | setuptools-scm from tags `vX.Y.Z` |
| `version_semver` | Met | `vMAJOR.MINOR.PATCH` |
| `version_tags` | Met | `git tag` |
| `release_notes` | Met | `development/Changelog.md`, one phase per release, and `docs/about/changelog.md` |
| `release_notes_vulns` | N/A | the criterion covers run-time vulnerabilities of the project's own code that already had a CVE, not those of its dependencies; none has been fixed (the V6.6.7 advisories were torch and pyarrow, and the parser bugs it fixed had no CVE). The Changelog still names them (Problems #362, #363) |

## Reporting

| Criterion | Answer | Evidence |
|---|---|---|
| `report_process` | Met | GitHub issues |
| `report_tracker` | Met | GitHub issues |
| `report_responses` | Met | |
| `enhancement_responses` | Met | |
| `report_archive` | Met | GitHub issues are public and kept |
| `vulnerability_report_process` | Met | `SECURITY.md` |
| `vulnerability_report_private` | Met | `SECURITY.md`: a private GitHub Security Advisory |
| `vulnerability_report_response` | Met | `SECURITY.md`: about a week |

## Quality

| Criterion | Answer | Evidence |
|---|---|---|
| `build` | Met | `pip install -e .`, `python -m build` (`pyproject.toml`) |
| `build_common_tools` | Met | setuptools, pip, npm |
| `build_floss_tools` | Met | the same |
| `test` | Met | `aq test` (pytest), the webui's vitest, documented in `tests/README.md` |
| `test_invocation` | Met | `aq test`, or `pytest` from the root |
| `test_most` | Met | every tracked module at 100% line coverage (`aq test --coverage`, CI `python-tests`) |
| `test_continuous_integration` | Met | `.github/workflows/ci.yml` on every push and pull request |
| `test_policy` | Met | `AGENTS.md` "Coverage: 100% after every commit" and "Non-negotiables" 1 and 2 |
| `tests_are_added` | Met | the coverage gate fails on any uncovered new line (CI and the pre-commit hook) |
| `tests_documented_added` | Met | `CONTRIBUTING.md`, `AGENTS.md` |
| `warnings` | Met | ruff (`ruff check .`), `tsc`, oxlint |
| `warnings_fixed` | Met | CI fails on any ruff finding |
| `warnings_strict` | Met | ruff, CodeQL, bandit (high severity fails) |

## Security

| Criterion | Answer | Evidence |
|---|---|---|
| `know_secure_design` | Met | `SECURITY.md`, the kill switch, order gate and audit chain (with Lean 4 proofs in `formal/`) |
| `know_common_errors` | Met | NaN/inf guards (`json_safety.py`), secrets never in config (`execution/secrets.py`), least-privilege workflow tokens |
| `crypto_published` | Met | sha256 (hash chain), PBKDF2-SHA256 (API tokens), Sigstore signatures; no custom cryptography |
| `crypto_call` | Met | Python's `hashlib`, `secrets`, `hmac` |
| `crypto_floss` | Met | |
| `crypto_keylength` | Met | 32-byte tokens, sha256 |
| `crypto_working` | Met | no MD5 or SHA-1 for security |
| `crypto_weaknesses` | Met | |
| `crypto_pfs` | N/A | the project runs no TLS endpoint of its own |
| `crypto_password_storage` | Met | `monitoring/auth.py`: salted PBKDF2-SHA256, never the token |
| `crypto_random` | Met | `secrets.token_urlsafe` |
| `delivery_mitm` | Met | PyPI over HTTPS with Trusted Publishing; Sigstore-signed release files and SLSA provenance |
| `delivery_unsigned` | Met | hashes are never fetched over HTTP |
| `vulnerabilities_fixed_60_days` | Met | Dependabot plus `pip-audit` and `npm audit` in CI |
| `vulnerabilities_critical_fixed` | Met | trivy blocks a fixable critical in the tree and the dashboard image |
| `no_leaked_credentials` | Met | gitleaks in CI (blocking on the tree), `aq secrets-check` in the pre-commit hook |

## Analysis

| Criterion | Answer | Evidence |
|---|---|---|
| `static_analysis` | Met | CodeQL (Python, TypeScript, workflows), bandit, ruff |
| `static_analysis_common_vulnerabilities` | Met | CodeQL security queries, bandit |
| `static_analysis_fixed` | Met | |
| `static_analysis_often` | Met | every push |
| `dynamic_analysis` | Met | Atheris fuzzing (`fuzz/`, `.github/workflows/fuzz.yml`) and hypothesis property tests |
| `dynamic_analysis_unsafe` | N/A | no memory-unsafe language in the shipped code (the optional C++ accelerator falls back to NumPy) |
| `dynamic_analysis_enable_assertions` | Met | the fuzz targets assert invariants; the suite runs with assertions on |
| `dynamic_analysis_fixed` | Met | the first fuzz run found five robustness bugs, fixed in V6.6.7 (Problems #363) |

## What stops "passing"

One MUST criterion, `floss_license`, is Unmet by the repository's own licence choice (the trading system is PolyForm Noncommercial). Everything else on this sheet is Met or not applicable, so the badge can only reach "passing" if the owner relicenses the trading system under an OSI-approved licence, or registers a repository that holds only the Apache-2.0 library. Until then it stays "in progress".

## Beyond passing (for later)

Silver also asks for:
- a second maintainer or a bus-factor plan;
- signed commits (`gpg`/`ssh` signing);
- a documented roadmap;
- DCO or a CLA.

Each is an owner decision. The Scorecard's Code-Review and Contributors checks stay at 0 for the same reason: one maintainer.
