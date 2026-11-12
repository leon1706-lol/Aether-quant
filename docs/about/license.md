# License

Aether Quant is under two licenses, by path. `REUSE.toml` in the repository maps every file.

| | License | Covers |
|---|---|---|
| **The library** | [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | everything the PyPI wheel and the dashboard image ship (`aether_quant` and the packages it re-exports, the `aq` CLI), the web UI, the notebooks, the docs, the examples and the Lean 4 proofs |
| **The trading system** | [PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) | `main.py`, the trainers, the trained models and `ml/`, `config.json`, `scripts/`, the data, the research records and the backtests |

So an institution can use, change and ship the library commercially under Apache-2.0, with its patent grant and the `NOTICE` file. The trading system stays noncommercial; a commercial license for it is available on request through the repository's GitHub page. Releases up to 6.6.4 were entirely under PolyForm Noncommercial.

Contributions take the license of the path they change (inbound equals outbound).
