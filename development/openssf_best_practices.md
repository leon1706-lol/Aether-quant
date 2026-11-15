# OpenSSF Best Practices: the answers, ready to enter

The OpenSSF Scorecard's CII-Best-Practices check reads the badge level that https://www.bestpractices.dev holds for this repository: none 0, in progress 2, passing 5, silver 7, gold 10.

Registering is a sign-up, so the owner did it: project [16720](https://www.bestpractices.dev/projects/16720), registered 2026-11-15, badge in the README beside the Scorecard badge. An agent never signs in or edits the answers (`AGENTS.md`); it reads the project's public JSON (the project page's URL plus `.json`) to check them.

Status as of V6.6.8 (2026-11-15): the project read 99% of the passing criteria, "in progress", with `floss_license`, `floss_license_osi` and `dynamic_analysis_unsafe` open. The trading system moved to AGPL-3.0 the same day (#381), so the two licence rows below are now Met; `dynamic_analysis_unsafe` is Met once CI job `cpp-sanitizers` has run green on `main` (#380). A criterion the project does not meet is marked so; nothing here is claimed that is not true.

**Metadata fields** (not criteria, but empty on the site): home page `https://leon1706-lol.github.io/Aether-quant/`, bug-report URL `https://github.com/leon1706-lol/Aether-quant/issues`.

## Basics

| Criterion | Answer | Evidence |
|---|---|---|
| `description_good` | Met | README first section; the GitHub About text |
| `interact` | Met | README, `CONTRIBUTING.md` (how to obtain, give feedback, contribute) |
| `contribution` | Met | `CONTRIBUTING.md` |
| `contribution_requirements` | Met | `CONTRIBUTING.md` and `AGENTS.md` "Non-negotiables" (tests, ruff, 100% coverage, docs move with code) |
| `floss_license` | Met | `LICENSE` is the GNU AGPL-3.0 (OSI-approved) and covers the trading system; the library and everything the wheel ships is Apache-2.0 (`LICENSES/`, `LICENSING.md`, `REUSE.toml` map every path). Changed 2026-11-15 from PolyForm Noncommercial, which was not FLOSS (#381); releases up to 6.6.7 keep the terms they shipped under |
| `floss_license_osi` | Met | AGPL-3.0 and Apache-2.0 are both OSI-approved |
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
| `warnings_strict` | Met | ruff with 14 rule sets (E, F, W, PLE, PIE, SIM, PERF, N, UP, PLW, C4, I, B, RUF; `pyproject.toml` `[tool.ruff.lint]`, every exclusion with its reason, pinned by `tests/test_ruff_config.py`, #379); CI `python-lint` fails on any finding; CodeQL; bandit (high severity fails) |

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
| `dynamic_analysis_unsafe` | Met | the only memory-unsafe code, the optional C++ accelerator `cpp_inference_ext`, is built with AddressSanitizer and UBSan by CI job `cpp-sanitizers` on every push (#380): a canary heap overflow must abort first, then hypothesis property tests (random shapes, dtypes, layouts, NaN and inf) and the exported-model parity run against the sanitized build |
| `dynamic_analysis_enable_assertions` | Met | the fuzz targets assert invariants; the suite runs with assertions on |
| `dynamic_analysis_fixed` | Met | the first fuzz run found five robustness bugs, fixed in V6.6.7 (Problems #363) |

## What stops "passing"

Nothing is open at the passing level once `cpp-sanitizers` is green and the owner has entered the answers below. `floss_license` and `floss_license_osi` became Met when the trading system moved to AGPL-3.0 (#381, 2026-11-15); `dynamic_analysis_unsafe` is Met by the job in #380 (its first run on `main` is the proof). The badge then reads "passing" (5 on the Scorecard check instead of 2).

## Beyond passing (for later)

Silver also asks for:
- a second maintainer or a bus-factor plan;
- signed commits (`gpg`/`ssh` signing);
- a documented roadmap;
- DCO or a CLA.

Each is an owner decision. The Scorecard's Code-Review and Contributors checks stay at 0 for the same reason: one maintainer.
