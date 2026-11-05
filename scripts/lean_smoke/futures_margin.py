"""Lean smoke test of phase_v2.futures_risk.margin_source "live" (V6.5.0, Problems.md #67): the calls main.py makes, on sample ES data.

This is Lean's local IB margin model, not IB's servers: it proves the API is the one main.py calls and the value is usable.
Runs as a project's main.py (scripts/lean_smoke/run.sh).
"""

from AlgorithmImports import *  # noqa: F403

import json

from risk.futures_risk import build_live_contract_spec


class FuturesMarginSmoke(QCAlgorithm):  # noqa: F405
    def initialize(self):
        self.set_start_date(2013, 10, 7)
        self.set_end_date(2013, 10, 8)
        self.set_cash(10_000_000)
        self.future = self.add_future("ES", Resolution.MINUTE)  # noqa: F405
        self.future.set_filter(0, 90)
        model = InteractiveBrokersBrokerageModel(AccountType.MARGIN)  # noqa: F405
        self.future.set_buying_power_model(model.get_buying_power_model(self.future))
        self.done = False

    def on_data(self, slice):
        if self.done:
            return
        chain = slice.future_chains.get(self.future.symbol)
        if chain is None:
            return
        contracts = sorted(chain, key=lambda contract: contract.expiry)
        if not contracts:
            return
        self.done = True
        security = self.securities[contracts[0].symbol]
        payload = {"kind": "futures", "contract": str(contracts[0].symbol), "price": float(security.price)}
        try:
            # the exact calls of main.py::_resolve_futures_contract_spec
            multiplier = float(security.SymbolProperties.ContractMultiplier)
            margin = float(security.BuyingPowerModel.GetInitialMarginRequirement(InitialMarginParameters(security, 1)).Value)  # noqa: F405
            payload.update(multiplier=multiplier, initial_margin=margin, spec=build_live_contract_spec(multiplier=multiplier, initial_margin_usd=abs(margin)))
            ticket = self.market_order(contracts[0].symbol, 1)
            payload.update(order_status=str(ticket.status))
        except Exception as error:
            payload.update(raised=f"{type(error).__name__}: {error}")
        self.debug("SMOKE_JSON " + json.dumps(payload, default=str))
