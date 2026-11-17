# Changelog

The full record of every phase lives in the repository: [`development/Changelog.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md). Every problem found and how it was closed is in [`development/Problems.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Problems.md).

The latest phases, generated from that file by `aq docs sync`:

<!-- AQ:CHANGELOG_LATEST_START -->
- [Phase V6.6.9 — The multi-asset model book back on the trusted path, an optimizer, a docs pass](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v669--the-multi-asset-model-book-back-on-the-trusted-path-an-optimizer-a-docs-pass)
- [Phase V6.6.8 — Close the best-practices gaps: strict lint, the C++ accelerator under sanitizers, the licence decision](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v668--close-the-best-practices-gaps-strict-lint-the-c-accelerator-under-sanitizers-the-licence-decision)
- [Phase V6.6.7 — The last tidy-up: the Scorecard near its ceiling, fuzzing, coverage after every commit, ten more proofs](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v667--the-last-tidy-up-the-scorecard-near-its-ceiling-fuzzing-coverage-after-every-commit-ten-more-proofs)
<!-- AQ:CHANGELOG_LATEST_END -->

**6.6.9: the multi-asset model book is back.**

- **Two parts on paper.** The book is now a crypto trend sleeve (70%) beside a model book (30%) over equities, bond ETFs, crypto and forex, installed by the owner's rule as "reinstated, not verified". No pre-registered trial survived, and the Lean Sharpe fell from 0.65 to 0.57.
- **A real optimizer.** `portfolio/book_optimizer.py` has seven ways to size a model's scores, a no-trade band and a forex loss guard. Twelve optimizers and six signal mixes were tried on pre-registered rules; none survived, and the model-free core did as well.
- **Computed inside Lean, off by default.** `phase_v2.target_weights.source: "model_book"` lets `main.py` score the universe and decide the row itself. A parity run matched the file's 209 decision dates and 0.998 of its daily returns.
- **Fixes.** The installed scaler had been overwritten under the models (restored and pinned, and the suite now fails on any change to the model files); HRP correlated different dates; a forex name was opened and swept the next bar; score tables for crypto and forex were used a bar early.
- **A retrain that cannot overwrite.** `aq cycle retrain --procedure stack` refits the models into `ml/versions/`, after zipping the installed set, and `aq cycle status` suggests it 30 days before the models reach the kill switch's age limit.

**6.6.8: the best-practices gaps.**

- **Stricter lint.** ruff now runs 14 rule sets instead of two, and it targets Python 3.10, the oldest version the package supports. Every rule left out carries its reason in `pyproject.toml`.
- **The C++ accelerator under sanitizers.** A new CI job builds `cpp_inference_ext` with AddressSanitizer and UBSan. A deliberate overflow must abort first, which proves the sanitizers are on; then property tests and the exported-model parity run against the sanitized build.
- **The trading system is AGPL-3.0.** It was PolyForm Noncommercial, which is not an open-source license. AGPL-3.0 is OSI-approved, so the repository is open source as a whole and the OpenSSF Best Practices badge no longer stops on its license.
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
