"""In-memory simulated portfolio for Phase V2-15 (Observation Mode).

SimulatedPortfolioState never references self.Portfolio, QCAlgorithm, or any
broker/Lean object - it is a plain Python bookkeeping class fed hypothetical
fill prices computed by execution.order_gate.simulate_fill. Its snapshot()
output is a strict superset of the real portfolio dict already passed to
experience.redis_queue.build_experience_event(portfolio=...), so that
function's signature never needs to change.
"""

from __future__ import annotations

from execution.order_gate import simulate_fill


class SimulatedPortfolioState:
    """Tracks fake cash/holdings/equity for a single algorithm run."""

    def __init__(self, initial_cash: float) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.holdings: dict[str, dict[str, float]] = {}
        self.peak_equity = float(initial_cash)
        self.cumulative_turnover = 0.0
        self.equity_curve: list[dict] = []
        self.trade_log: list[dict] = []
        self._last_prices: dict[str, float] = {}
        self._last_realized_pnl: float | None = None

    def _equity(self) -> float:
        holdings_value = sum(
            holding["quantity"] * self._last_prices.get(symbol_key, holding["avg_price"])
            for symbol_key, holding in self.holdings.items()
        )
        return self.cash + holdings_value

    def _exposure(self) -> float:
        equity = self._equity()
        if equity <= 0:
            return 0.0
        holdings_value = sum(
            abs(holding["quantity"] * self._last_prices.get(symbol_key, holding["avg_price"]))
            for symbol_key, holding in self.holdings.items()
        )
        return holdings_value / equity

    def enter_long(
        self,
        symbol_key: str,
        close_price: float,
        target_weight: float,
        bar_index: int,
        slippage_bps: float = 0.0,
    ) -> None:
        self._last_prices[symbol_key] = close_price
        equity = self._equity()
        fill = simulate_fill(
            close_price=close_price, target_weight=target_weight, equity=equity, slippage_bps=slippage_bps
        )

        existing = self.holdings.get(symbol_key, {"quantity": 0.0, "avg_price": close_price})
        delta_quantity = fill["quantity"] - existing["quantity"]
        self.cash -= delta_quantity * fill["fill_price"]
        self.cumulative_turnover += abs(delta_quantity * fill["fill_price"])

        self.holdings[symbol_key] = {"quantity": fill["quantity"], "avg_price": fill["fill_price"]}
        self._last_realized_pnl = None
        self.trade_log.append(
            {
                "bar_index": bar_index,
                "symbol": symbol_key,
                "action": "enter_long",
                "quantity": fill["quantity"],
                "price": fill["fill_price"],
                "realized_pnl": None,
            }
        )

    def exit(self, symbol_key: str, close_price: float, bar_index: int) -> None:
        self._last_prices[symbol_key] = close_price
        holding = self.holdings.pop(symbol_key, None)
        if holding is None or holding["quantity"] == 0:
            return

        realized_pnl = (close_price - holding["avg_price"]) * holding["quantity"]
        proceeds = holding["quantity"] * close_price
        self.cash += proceeds
        self.cumulative_turnover += abs(proceeds)
        self._last_realized_pnl = realized_pnl

        self.trade_log.append(
            {
                "bar_index": bar_index,
                "symbol": symbol_key,
                "action": "exit",
                "quantity": holding["quantity"],
                "price": close_price,
                "realized_pnl": realized_pnl,
            }
        )

    def liquidate_all(self, bar_index: int) -> None:
        total_realized_pnl = 0.0
        for symbol_key in list(self.holdings.keys()):
            holding = self.holdings.pop(symbol_key)
            close_price = self._last_prices.get(symbol_key, holding["avg_price"])
            realized_pnl = (close_price - holding["avg_price"]) * holding["quantity"]
            proceeds = holding["quantity"] * close_price
            self.cash += proceeds
            self.cumulative_turnover += abs(proceeds)
            total_realized_pnl += realized_pnl
            self.trade_log.append(
                {
                    "bar_index": bar_index,
                    "symbol": symbol_key,
                    "action": "liquidate_all",
                    "quantity": holding["quantity"],
                    "price": close_price,
                    "realized_pnl": realized_pnl,
                }
            )

        if self.trade_log and self.trade_log[-1]["bar_index"] == bar_index:
            self._last_realized_pnl = total_realized_pnl

    def mark_to_market(self, prices_by_symbol: dict[str, float], bar_index: int | None = None) -> None:
        self._last_prices.update(prices_by_symbol)
        equity = self._equity()
        self.peak_equity = max(self.peak_equity, equity)
        self.equity_curve.append(
            {
                "bar_index": bar_index,
                "equity": equity,
                "cash": self.cash,
                "exposure": self._exposure(),
                "drawdown": self._drawdown(equity),
            }
        )

    def position_value(self, symbol_key: str) -> float:
        """Current mark-to-market notional value of a held symbol, 0.0 if flat."""
        holding = self.holdings.get(symbol_key)
        if holding is None:
            return 0.0
        price = self._last_prices.get(symbol_key, holding["avg_price"])
        return holding["quantity"] * price

    def _drawdown(self, equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return equity / self.peak_equity - 1.0

    def snapshot(self, consume_realized_pnl: bool = True) -> dict:
        """Portfolio snapshot compatible with build_experience_event(portfolio=...).

        By default this consumes (clears) the pending realized-PnL value so
        it is attributed to exactly one experience event rather than bleeding
        into later, unrelated snapshots.
        """
        equity = self._equity()
        last_realized_pnl = self._last_realized_pnl
        if consume_realized_pnl:
            self._last_realized_pnl = None

        return {
            "total_value": equity,
            "cash": self.cash,
            "current_drawdown": self._drawdown(equity),
            "simulated": True,
            "holdings_value": equity - self.cash,
            "exposure": self._exposure(),
            "turnover_to_date": self.cumulative_turnover,
            "peak_equity": self.peak_equity,
            "last_realized_pnl": last_realized_pnl,
        }
