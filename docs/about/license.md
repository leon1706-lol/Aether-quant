# License

Aether Quant is under two licenses, by path. `REUSE.toml` in the repository maps every file.

| | License | Covers |
|---|---|---|
| **The library** | [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | everything the PyPI wheel and the dashboard image ship (`aether_quant` and the packages it re-exports, the `aq` CLI), the web UI, the notebooks, the docs, the examples and the Lean 4 proofs |
| **The trading system** | [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) | `main.py`, the trainers, the trained models and `ml/`, `config.json`, `scripts/`, the data, the research records and the backtests |

So an institution can use, change and ship the library commercially under Apache-2.0, with its patent grant and the `NOTICE` file. The trading system is AGPL-3.0: commercial use is allowed, and anyone who changes it and lets others use it, including over a network, must offer those users the source of the changed version. A commercial license without that condition is available on request through the repository's GitHub page. The trading system was PolyForm Noncommercial 1.0.0 from release 6.6.5 to 6.6.7, and releases up to 6.6.4 were entirely PolyForm Noncommercial; those releases keep the terms they shipped under.

Contributions take the license of the path they change (inbound equals outbound).

