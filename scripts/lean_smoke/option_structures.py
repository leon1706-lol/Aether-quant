"""Lean smoke test of the options code (V6.5.0, Problems.md #38, #58-#61): every structure of MULTI_LEG_STRATEGY_REGISTRY, built by
the repo's own leg selectors, ordered through Lean's OptionStrategies on the sample AAPL chain; then the arbitrage and
assignment-risk detectors on the same chain. Runs as a project's main.py (scripts/lean_smoke/run.sh).

Results are one `SMOKE_JSON {...}` debug line per structure. Fills and margin here are Lean's model on 2014 sample data: this
proves the calls work, not what IB would do.
"""

from AlgorithmImports import *  # noqa: F403

import json
from datetime import datetime

from portfolio.options_arbitrage_detector import select_arbitrage_signal
from portfolio.options_assignment_risk import assignment_risk_flag, assignment_risk_score, extrinsic_value
from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY, select_single_leg_contract, select_strategy_legs
from features.options_greeks import compute_greeks, implied_volatility

RISK_FREE = 0.01
RETRY_DELTAS = (0.5, 0.3, 0.6, 0.25)
ARBITRAGE_NAMES = ("box_spread", "short_box_spread", "conversion", "reverse_conversion", "jelly_roll", "short_jelly_roll")


class OptionStructuresSmoke(QCAlgorithm):  # noqa: F405
    def initialize(self):
        self.set_start_date(2014, 6, 6)
        self.set_end_date(2014, 6, 9)
        self.set_cash(50_000_000)
        self.underlying = self.add_equity("AAPL", Resolution.MINUTE).symbol  # noqa: F405
        option = self.add_option("AAPL", Resolution.MINUTE)  # noqa: F405
        option.set_filter(-12, 12, timedelta(0), timedelta(180))  # noqa: F405
        self.canonical = option.symbol
        self.queue = [(name, 0.4) for name in MULTI_LEG_STRATEGY_REGISTRY]
        self.retries = {}
        self.results = {}
        self.current = None
        self.detectors_done = False

    def rows_from(self, chain):
        rows = []
        spot = float(self.securities[self.underlying].price)
        for contract in chain:
            right = "call" if contract.right == OptionRight.CALL else "put"  # noqa: F405
            bid, ask = float(contract.bid_price or 0.0), float(contract.ask_price or 0.0)
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(contract.last_price or 0.0)
            years = max((contract.expiry.date() - self.time.date()).days, 0) / 365.0
            if mid <= 0 or spot <= 0 or years <= 0:
                continue
            solved = implied_volatility(option_price=mid, spot=spot, strike=float(contract.strike), time_to_expiry_years=years,
                                        risk_free_rate=RISK_FREE, dividend_yield=0.0, right=right, max_iterations=100, tolerance=1e-6)
            if solved is None:
                continue
            greeks = compute_greeks(spot=spot, strike=float(contract.strike), time_to_expiry_years=years, risk_free_rate=RISK_FREE,
                                    volatility=solved, dividend_yield=0.0, right=right)
            rows.append({"symbol": contract.symbol, "strike": float(contract.strike), "right": right,
                         "expiry": contract.expiry.date().isoformat(), "bid": bid, "ask": ask, "volume": float(contract.volume or 0.0),
                         "open_interest": float(contract.open_interest or 0.0), "iv": solved, "underlying_price": spot, **greeks})
        return rows

    def build(self, name, legs):
        spec = MULTI_LEG_STRATEGY_REGISTRY[name]
        strikes_by_role = {}
        expiries = {}
        for leg in spec.legs:
            row = legs[leg.role]
            strikes_by_role[leg.strike_role] = row["strike"]
            expiries[leg.expiry_role] = row["expiry"]
        args = [strikes_by_role[role] for role in spec.arg_order]
        factory = getattr(OptionStrategies, spec.factory_name)  # noqa: F405
        if spec.has_expiry_pair:
            near, far = sorted(expiries.values())[:2]
            return factory(self.canonical, *args, datetime.fromisoformat(near), datetime.fromisoformat(far))
        return factory(self.canonical, *args, datetime.fromisoformat(next(iter(expiries.values()))))

    def report(self, payload):
        self.debug("SMOKE_JSON " + json.dumps(payload, default=str))

    def run_detectors(self, rows):
        arbitrage = {}
        for name in ARBITRAGE_NAMES:
            try:
                arbitrage[name] = bool(select_arbitrage_signal(name, rows, self.time.date(), RISK_FREE, 5.0))
            except Exception as error:
                arbitrage[name] = f"raised {type(error).__name__}: {error}"
        assignment = {}
        call = select_single_leg_contract(rows, 0.8, "call")
        if call is not None:
            spot = float(call["underlying_price"])
            extrinsic = extrinsic_value((call["bid"] + call["ask"]) / 2.0, spot, call["strike"], "call")
            score = assignment_risk_score(spot / call["strike"], "call", extrinsic, 3.29, 5, 10)
            assignment = {"strike": call["strike"], "extrinsic": extrinsic, "score": score, "flag": assignment_risk_flag(score, 0.5)}
        self.report({"kind": "detectors", "arbitrage": arbitrage, "assignment": assignment, "chain_rows": len(rows)})

    def on_data(self, slice):
        chain = slice.option_chains.get(self.canonical)
        if chain is None or self.is_warming_up:
            return
        if self.current is not None:
            name, tickets, margin = self.current
            statuses = [str(ticket.status) for ticket in tickets]
            self.results[name] = {"status": "ordered", "legs": len(tickets), "ticket_status": statuses,
                                  "margin_used": margin, "messages": [str(t.get_most_recent_order_response().error_message) for t in tickets]}
            self.report({"kind": "structure", "name": name, **self.results[name]})
            self.liquidate()
            self.current = None
            return
        rows = self.rows_from(chain)
        if not rows:
            return
        if not self.detectors_done:
            self.detectors_done = True
            self.run_detectors(rows)
        if not self.queue:
            return
        name, target_delta = self.queue.pop(0)
        try:
            legs = select_strategy_legs(name, rows, target_delta)
            if legs is None:
                # the anchor's expiry may lack an outer strike; another delta picks another contract
                retry = RETRY_DELTAS[self.retries.get(name, 0):]
                if retry:
                    self.retries[name] = self.retries.get(name, 0) + 1
                    self.queue.append((name, retry[0]))
                    return
                self.results[name] = {"status": "no_legs_on_this_chain"}
                self.report({"kind": "structure", "name": name, **self.results[name]})
                return
            tickets = self.buy(self.build(name, legs), 1)
            self.current = (name, list(tickets), float(self.portfolio.total_margin_used))
        except Exception as error:
            self.results[name] = {"status": "raised", "error": f"{type(error).__name__}: {error}"}
            self.report({"kind": "structure", "name": name, **self.results[name]})

    def on_end_of_algorithm(self):
        for name, _ in self.queue:
            self.results[name] = {"status": "not_reached"}
        self.report({"kind": "summary", "results": self.results})
