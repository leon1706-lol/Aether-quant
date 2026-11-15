# Changelog

The full record of every phase lives in the repository: [`development/Changelog.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md). Every problem found and how it was closed is in [`development/Problems.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Problems.md).

The latest phases, generated from that file by `aq docs sync`:

<!-- AQ:CHANGELOG_LATEST_START -->
- [Phase V6.6.8 — Close the best-practices gaps: strict lint, the C++ accelerator under sanitizers, the licence decision](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v668--close-the-best-practices-gaps-strict-lint-the-c-accelerator-under-sanitizers-the-licence-decision)
- [Phase V6.6.7 — The last tidy-up: the Scorecard near its ceiling, fuzzing, coverage after every commit, ten more proofs](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v667--the-last-tidy-up-the-scorecard-near-its-ceiling-fuzzing-coverage-after-every-commit-ten-more-proofs)
- [Phase V6.6.6 — Cleanup: the Scorecard sees releases, the public pages stop quoting by hand, coverage measures everything](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v666--cleanup-the-scorecard-sees-releases-the-public-pages-stop-quoting-by-hand-coverage-measures-everything)
<!-- AQ:CHANGELOG_LATEST_END -->

**6.6.8: the best-practices gaps.**

- **Stricter lint.** ruff now runs 14 rule sets instead of two, and it targets Python 3.10, the oldest version the package supports. Every rule left out carries its reason in `pyproject.toml`.
- **The C++ accelerator under sanitizers.** A new CI job builds `cpp_inference_ext` with AddressSanitizer and UBSan. A deliberate overflow must abort first, which proves the sanitizers are on; then property tests and the exported-model parity run against the sanitized build.
- **The licence, decided.** The trading system stays PolyForm Noncommercial, so the OpenSSF Best Practices badge stays "in progress" at 99%. Relicensing is listed as a possible future step under Known Limitations.
- **The per-commit coverage gate** no longer refuses a change to `main.py`.

**6.6.7: the last tidy-up.**

- **Supply chain.** Every install in CI, the Docker images and the scripts is hash-pinned (`requirements/lock/`), and a new check keeps it that way. torch and pyarrow moved past their advisories.
- **Fuzzing.** The parsers and guards that take untrusted input are fuzzed with Atheris in CI. The first run found five bugs, including a password that leaked through `@` and a users file that granted every account.
- **Proofs.** Ten more Lean 4 specs (28 in all) with their differential tests; they closed nine fail-open cases, such as a drawdown guard that never tripped on NaN and an auto-rollback the string "false" switched on.
- **Coverage.** The 100% gate now has a fast per-commit form (`aq test --coverage --changed`) in the pre-commit hook.
- **Releases.** Each release's provenance is the build's own attestation, and older releases get theirs attached by `backfill_tag`.

**6.6.6: cleanup.**

- **Releases.** Every release now carries the wheel, sdist, SBOM, Sigstore signatures and SLSA provenance, so the OpenSSF Scorecard sees it.
- **Supply chain.** Actions are pinned by commit and base images by digest; write tokens sit only on the jobs that need them.
- **Coverage.** The gate is 100% over every tracked Python file, with no pragma, and it builds the coverage and test badges from CI.
- **Pages.** Numbers on the site and the README (trials, sample window, hello-world figures, the Lean pin) come from the data, not from text.
- **Two fixes in the offline simulator** found while testing the legacy sleeve's exits.

**6.6.5: open the door.**

- **Getting started.** `pip install aether-quant` is now a light install, and `aq hello` runs end to end in one command.
- **Learning and looking things up.** Four Colab notebooks, this documentation site, and a dashboard in one Docker command.
- **The library.** New tools: Kelly sizing, beta and factor neutrality, composable cost models, `backtest()`, the minimum track record and the haircut Sharpe. Every export is now typed and documented.
- **Licensing.** The library is now Apache-2.0.
- **Production.** Secret management, accounts, users with roles, a field test on Lean's paper brokerage, and the measured paper-to-live scorecard.
- **CI.** CodeQL, Scorecard, bandit, trivy, SBOMs and provenance.
