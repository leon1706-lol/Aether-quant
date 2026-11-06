"""Lean smoke test of main.py's own multi-leg option order (V6.6.0, Problems.md #38).

V6.5.0 ran main.py with an option asset on Lean's sample AAPL chain, but that month produced no signal, so the order path never
ran. This forces one signal: a subclass of the real algorithm calls `_apply_option_multi_leg_order` with a decision built by the
real sizing function once a chain has arrived. Run it with the config from `make_option_main_config.py`:

    bash scripts/lean_smoke/run_main_option_order.sh

The project holds the repo's main.py as `aq_main.py` and this file as main.py. It imports the module, not the class, so Lean finds
one algorithm class here. `SMOKE_JSON {...}` lines report what happened.
"""

from AlgorithmImports import *  # noqa: F403

import dataclasses
import json
from builtins import Exception

import aq_main
from portfolio.options_strategy import build_vertical_spread_position_sizing


class MainOptionOrderSmoke(aq_main.AetherQuantAlgorithm):
    _forced = False

    def _smoke(self, **fields):
        self.Debug("SMOKE_JSON " + json.dumps(fields, default=str))

    def on_data(self, slice):
        super().on_data(slice)
        if self._forced or self.is_warming_up:
            return
        for symbol in self.symbols:
            asset = self.asset_lookup[str(symbol)]
            if asset.get("security_type") != "option":
                continue
            rows = (self.latest_options_chains_payload or {}).get(str(asset["underlying_ticker"])) or []
            if not rows:
                continue
            nav = float(self.Portfolio.TotalPortfolioValue)
            decision = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
            if decision is None:
                self._smoke(kind="no_decision", rows=len(rows))
                continue
            self._forced = True
            orders_before = self.Transactions.OrdersCount
            try:
                result = self._apply_option_multi_leg_order(symbol, str(symbol), decision, 0.01, float(rows[0].get("underlying_price") or 0.0), True, "smoke")
            except Exception as error:
                self._smoke(kind="order_raised", error=f"{type(error).__name__}: {error}")
                raise
            self._smoke(
                kind="forced_order", result=result, strategy=decision.strategy_name, contracts=decision.contracts,
                legs=[str(leg.contract_symbol) for leg in decision.legs], orders_placed=self.Transactions.OrdersCount - orders_before,
            )
            # The limit above often rests unfilled on this thin sample, so one contract goes through the market branch as well: that one must fill.
            self.limit_orders_enabled = False
            orders_before = self.Transactions.OrdersCount
            result = self._apply_option_multi_leg_order(
                symbol, str(symbol), dataclasses.replace(decision, contracts=1), 0.01, float(rows[0].get("underlying_price") or 0.0), True, "smoke",
            )
            self.limit_orders_enabled = True
            self._smoke(kind="forced_market_order", result=result, orders_placed=self.Transactions.OrdersCount - orders_before)
            return

    def on_order_event(self, order_event):
        super().on_order_event(order_event)
        if order_event.Symbol.SecurityType == SecurityType.Option:  # noqa: F405
            self._smoke(kind="option_fill_event", symbol=str(order_event.Symbol), status=str(order_event.Status), quantity=float(order_event.FillQuantity), price=float(order_event.FillPrice))
