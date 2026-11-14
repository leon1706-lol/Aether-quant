# Changelog

The full record of every phase lives in the repository: [`development/Changelog.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md). Every problem found and how it was closed is in [`development/Problems.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Problems.md).

The latest phases, generated from that file by `aq docs sync`:

<!-- AQ:CHANGELOG_LATEST_START -->
- [Phase V6.6.6 — Cleanup: the Scorecard sees releases, the public pages stop quoting by hand, coverage measures everything](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v666--cleanup-the-scorecard-sees-releases-the-public-pages-stop-quoting-by-hand-coverage-measures-everything)
- [Phase V6.6.5 — Open the door: a five-minute start, a first-class library, a hardened live path](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v665--open-the-door-a-five-minute-start-a-first-class-library-a-hardened-live-path)
- [Phase V6.6.4 — Everything open that needs no broker key: a fourth alpha round, the open problems, verification of every kind](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md#phase-v664--everything-open-that-needs-no-broker-key-a-fourth-alpha-round-the-open-problems-verification-of-every-kind)
<!-- AQ:CHANGELOG_LATEST_END -->

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
