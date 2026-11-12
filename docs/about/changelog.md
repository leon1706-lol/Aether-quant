# Changelog

The full record of every phase lives in the repository: [`development/Changelog.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md). Every problem found and how it was closed is in [`development/Problems.md`](https://github.com/leon1706-lol/Aether-quant/blob/main/development/Problems.md).

**6.6.5: open the door.**

- **Getting started.** `pip install aether-quant` is now a light install, and `aq hello` runs end to end in one command.
- **Learning and looking things up.** Four Colab notebooks, this documentation site, and a dashboard in one Docker command.
- **The library.** New tools: Kelly sizing, beta and factor neutrality, composable cost models, `backtest()`, the minimum track record and the haircut Sharpe. Every export is now typed and documented.
- **Licensing.** The library is now Apache-2.0.
- **Production.** Secret management, accounts, users with roles, a field test on Lean's paper brokerage, and the measured paper-to-live scorecard.
- **CI.** CodeQL, Scorecard, bandit, trivy, SBOMs and provenance.
