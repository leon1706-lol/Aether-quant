"""Lean smoke scenarios for main.py's option paths on Lean's sample AAPL chain (V6.6.4, Problems #58, #59, #60, #61).

Every scenario drives the real algorithm class: a subclass calls `_apply_option_multi_leg_order` (and the sweeps) with decisions built by the real sizing functions, once a chain has arrived. It
is plumbing, not evidence: `options_risk.enabled` stays false in the shipped config, and the sample is a month of one underlying. `SMOKE_JSON {...}` lines report what happened; a step that
raises is reported and the next step still runs, so one defect doesn't hide the rest. The sample chain is thin on its first days (most structures find no legs), so a structure is tried on
every bar of the month until it builds, and the scenarios that need a decision wait for the first bar a vertical builds on.

Project layout (scripts/lean_smoke/run_main_option_scenarios.sh): the repo's main.py is `aq_main.py`, this file is `main.py`, and `scenario.txt` names the scenario:

    scale   #58  sell-side scale-down, scale-up, a second position under max_positions_per_underlying = 2, rotation
    all43   #59  every registered structure through the real order path, with the margin Lean charged beside the module's own
    arb     #60  the arbitrage detector enabled inside main.py, on the live chain payload
    assign  #61  the assignment sweep over a held short call, then the same position held to its expiry with the auto-close off
"""

from AlgorithmImports import *  # noqa: F403

import dataclasses
import json
from builtins import Exception
from pathlib import Path

import aq_main
from portfolio.options_margin_sizing import build_margin_position_sizing
from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY, build_multi_leg_position_sizing, build_vertical_spread_position_sizing

SCENARIO = (Path(__file__).with_name("scenario.txt").read_text(encoding="utf-8").strip() if Path(__file__).with_name("scenario.txt").exists() else "scale")


class OptionScenario(aq_main.AetherQuantAlgorithm):
    _steps_done = False
    _probes = 0

    def _smoke(self, **fields):
        self.Debug("SMOKE_JSON " + json.dumps({"scenario": SCENARIO, **fields}, default=str))

    def _attempt(self, step, function):
        try:
            result = function()
            self._smoke(kind="step", step=step, result=result)
            return result
        except Exception as error:
            self._smoke(kind="step_raised", step=step, error=f"{type(error).__name__}: {error}")
            return None

    def _chain(self):
        for symbol in self.symbols:
            asset = self.asset_lookup[str(symbol)]
            if asset.get("security_type") != "option":
                continue
            rows = (self.latest_options_chains_payload or {}).get(str(asset["underlying_ticker"])) or []
            if rows:
                return symbol, str(symbol), rows
        return None, None, []

    def _positions(self, key):
        return [{"kind": r.get("kind"), "strategy": r.get("strategy_name"), "contracts": r.get("contracts")} for r in self.option_positions_by_symbol.get(key, [])]

    def _order(self, symbol, key, decision, rows, label):
        before = self.Transactions.OrdersCount
        result = self._apply_option_multi_leg_order(symbol, key, decision, 0.01, float(rows[0].get("underlying_price") or 0.0), True, label)
        return {"result": result, "orders_placed": self.Transactions.OrdersCount - before, "positions": self._positions(key), "margin_used": float(self.Portfolio.TotalMarginUsed)}

    def on_data(self, slice):
        super().on_data(slice)
        if self.is_warming_up:
            return
        symbol, key, rows = self._chain()
        if not rows:
            return
        self.limit_orders_enabled = False  # market branch: the thin sample leaves limits unfilled
        nav = float(self.Portfolio.TotalPortfolioValue)
        if SCENARIO == "all43":
            self._all43_bar(symbol, key, rows, nav)
            return
        if self._steps_done:
            return
        if SCENARIO in ("arb", "assign"):
            probe = build_multi_leg_position_sizing("bull_call_spread", "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        else:
            probe = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        if probe is None:
            self._probes += 1
            if self._probes <= 3:
                self._smoke(kind="no_decision_yet", bar=str(self.Time.date()), rows=len(rows))
            return
        self._steps_done = True
        self._smoke(kind="chain", bar=str(self.Time.date()), rows=len(rows), nav=nav, expiries=sorted({str(r.get("expiry")) for r in rows})[:6], bars_waited=self._probes)
        getattr(self, f"_scenario_{SCENARIO}")(symbol, key, rows, nav)

    # --- #58 -------------------------------------------------------------------------------------------------------------
    def _scenario_scale(self, symbol, key, rows, nav):
        def vertical(confidence, vega):
            return build_vertical_spread_position_sizing("buy", confidence, rows, nav, max_vega_budget_pct_of_equity=vega)

        first = vertical(0.8, 0.02)
        self._attempt("enter", lambda: self._order(symbol, key, first, rows, "enter"))
        bigger = vertical(0.8, 0.05)
        self._attempt("scale_up", lambda: self._order(symbol, key, bigger, rows, "scale_up"))
        smaller = vertical(0.8, 0.01)
        self._attempt("scale_down", lambda: self._order(symbol, key, smaller, rows, "scale_down"))
        self.options_max_positions_per_underlying = 2
        other = build_multi_leg_position_sizing("straddle", "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        self._attempt("second_position_under_cap_2", lambda: self._order(symbol, key, other, rows, "second") if other else "no straddle decision")
        third = build_multi_leg_position_sizing("strangle", "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        self._attempt("third_position_at_cap", lambda: self._order(symbol, key, third, rows, "third") if third else "no strangle decision")
        self._smoke(kind="final", positions=self._positions(key), orders=self.Transactions.OrdersCount)

    # --- #59 -------------------------------------------------------------------------------------------------------------
    _remaining = None
    _built = None

    def _all43_bar(self, symbol, key, rows, nav):
        if self._remaining is None:
            self._remaining = list(MULTI_LEG_STRATEGY_REGISTRY)
            self._built = {}
        price = float(rows[0].get("underlying_price") or 0.0)
        for name in list(self._remaining):
            spec = MULTI_LEG_STRATEGY_REGISTRY[name]

            def one(name=name, spec=spec):
                if spec.risk_tier == "vega_budget":
                    decision = build_multi_leg_position_sizing(name, "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
                else:
                    decision = build_margin_position_sizing(name, "buy", 0.8, rows, price, nav)
                if decision is None:
                    return None
                decision = dataclasses.replace(decision, contracts=1) if hasattr(decision, "contracts") else decision
                before_margin = float(self.Portfolio.TotalMarginUsed)
                outcome = self._order(symbol, key, decision, rows, name)
                outcome.update({"tier": spec.risk_tier, "own_margin_estimate": getattr(decision, "margin_requirement", None), "lean_margin_delta": outcome["margin_used"] - before_margin, "bar": str(self.Time.date())})
                for record in list(self.option_positions_by_symbol.get(key, [])):
                    self._liquidate_option_record(key, record)
                return outcome

            try:
                outcome = one()
            except Exception as error:
                self._smoke(kind="step_raised", step=name, error=f"{type(error).__name__}: {error}")
                self._remaining.remove(name)
                self._built[name] = {"raised": f"{type(error).__name__}: {error}"}
                continue
            if outcome is not None:
                self._remaining.remove(name)
                self._built[name] = outcome
                self._smoke(kind="step", step=name, result=outcome)

    # --- #60 -------------------------------------------------------------------------------------------------------------
    def _scenario_arb(self, symbol, key, rows, nav):
        from risk.asset_class_router import route_multi_leg_option_sizing

        arbitrage = [name for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items() if spec.risk_tier == "unreachable_arbitrage"]
        self._smoke(kind="detector_flag", enabled=bool(self.options_arbitrage_detector_enabled), min_bps=self.options_arbitrage_min_mispricing_bps, rows=len(rows), arbitrage_structures=arbitrage)
        price = float(rows[0].get("underlying_price") or 0.0)

        def routed(enabled):
            # the same call main.py makes in _build_dynamic_sizing_payload, with the flags read from the live algorithm object
            result = route_multi_leg_option_sizing(
                arbitrage, "buy", 0.8, rows, nav, price, "neutral", self.options_risk_tier_preference, False,
                target_delta_at_full_confidence=self.options_target_delta_at_full_confidence, max_vega_budget_pct_of_equity=self.options_max_vega_budget_pct_of_equity,
                short_leg_delta_offset=self.options_short_leg_delta_offset, contract_multiplier=100.0, target_margin_utilization=self.options_margin_target_utilization,
                max_margin_utilization=self.options_margin_max_utilization, pct_of_underlying_value=self.options_margin_pct_of_underlying_value,
                min_pct_of_underlying_value=self.options_margin_min_pct_of_underlying_value, current_date=self.Time.date(), risk_free_rate=self.options_risk_free_rate,
                arbitrage_detector_enabled=enabled, min_mispricing_bps=self.options_arbitrage_min_mispricing_bps,
            )
            if result is None:
                return {"routed": None}
            decision, extra = result
            return {"routed": decision.to_dict().get("strategy_name"), "extra": extra}

        self._attempt("detector_on_as_configured", lambda: routed(bool(self.options_arbitrage_detector_enabled)))
        self._attempt("detector_off_for_contrast", lambda: routed(False))
        payload = self._build_options_chains_payload(self.CurrentSlice) if hasattr(self, "_build_options_chains_payload") else None
        self._smoke(kind="payload", built=payload is not None, underlyings=sorted(payload) if isinstance(payload, dict) else None)

    # --- #61 -------------------------------------------------------------------------------------------------------------
    def _scenario_assign(self, symbol, key, rows, nav):
        entry = build_multi_leg_position_sizing("bull_call_spread", "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        self._attempt("enter_short_call_structure", lambda: self._order(symbol, key, entry, rows, "assign") if entry else "no decision")
        self._attempt("assignment_sweep", lambda: (self._apply_option_assignment_risk_sweep(), {"latest": self.latest_assignment_risk_by_symbol, "positions": self._positions(key)})[1])
        self.options_auto_close_days_before_expiry = -1  # hold to expiry: Lean's own exercise and assignment model acts, or the position expires
        self._smoke(kind="held_to_expiry", positions=self._positions(key), expiries=[r.get("expiries") for r in self.option_positions_by_symbol.get(key, [])])

    def on_end_of_algorithm(self):
        if SCENARIO == "all43" and self._built is not None:
            self._smoke(kind="coverage", built=sorted(self._built), never_built=sorted(self._remaining or []), total=len(MULTI_LEG_STRATEGY_REGISTRY))
        self._smoke(kind="end", orders=self.Transactions.OrdersCount, holdings=[str(h.Symbol) for h in self.Portfolio.Values if h.Invested], cash=float(self.Portfolio.Cash))
        if hasattr(super(), "on_end_of_algorithm"):
            super().on_end_of_algorithm()

    def on_order_event(self, order_event):
        super().on_order_event(order_event)
        if order_event.Symbol.SecurityType == SecurityType.Option:  # noqa: F405
            self._smoke(kind="option_event", symbol=str(order_event.Symbol), status=str(order_event.Status), quantity=float(order_event.FillQuantity), price=float(order_event.FillPrice), message=str(order_event.Message))
