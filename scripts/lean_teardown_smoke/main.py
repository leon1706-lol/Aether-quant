"""Problems.md #104 smoke test: the smallest Lean algorithm (SPY daily, no custom objects, nothing of this project).

Run it with `aq teardown-smoke --image <engine image>` (or `lean backtest scripts/lean_teardown_smoke --image <image>`) and
read the ENGINE log (`backtests/<run>/log.txt`): a clean exit shows `PythonInitializer.Shutdown(): ended`; the known hang shows
`Operation timed out` / `Failed to shutdown python` after the results were written. If the trivial algorithm hangs, so does
every algorithm on that image, whatever this project does.
"""

from AlgorithmImports import *


class TeardownSmoke(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 2)
        self.set_end_date(2020, 3, 31)
        self.set_cash(100000)
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol

    def on_data(self, data):
        if not self.portfolio.invested and data.contains_key(self.symbol):
            self.set_holdings(self.symbol, 1.0)
