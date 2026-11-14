"""The Lean API surface `main.py` touches, as plain Python (V6.6.6, #359): symbols, securities, a portfolio that fills market orders at the security's price, tickets,
transactions, slices, and a seeded market that delivers bars. Anything not modelled here is a permissive MagicMock, so a typo in main.py's own private state still fails."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np


class PermissiveQC:
    """Stands in for QCAlgorithm's large public surface: any PUBLIC attribute is a MagicMock. Private attributes must be set by main.py, so a typo there still fails."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value


class FakeSymbol:
    """One Lean Symbol per ticker. Hashable by identity, printable as the ticker, with the few attributes main.py reads."""

    def __init__(self, text: str, security_type: str = "equity", underlying=None):
        self.Value = self.value = text
        self.SecurityType = security_type
        self.Underlying = self.underlying = underlying
        self.ID = SimpleNamespace(Symbol=text, StrikePrice=0.0, OptionRight="Call", Date=None, Market="usa", OptionStyle="American")

    def __str__(self) -> str:
        return self.Value

    __repr__ = __str__


class FakeHolding:
    def __init__(self, symbol, security=None):
        self.Symbol = self.symbol = symbol
        self.Quantity = self.quantity = 0.0
        self.AveragePrice = self.average_price = 0.0
        self.NetProfit = 0.0
        self._security = security

    @property
    def Price(self) -> float:
        return float(self._security.Price) if self._security is not None else self.AveragePrice

    @property
    def Invested(self) -> bool:
        return abs(self.Quantity) > 1e-12

    @property
    def HoldingsValue(self) -> float:
        return self.Quantity * self.Price

    @property
    def IsLong(self) -> bool:
        return self.Quantity > 0

    @property
    def IsShort(self) -> bool:
        return self.Quantity < 0

    @property
    def UnrealizedProfit(self) -> float:
        return self.Quantity * (self.Price - self.AveragePrice)


class FakePortfolio:
    def __init__(self, cash: float):
        self.Cash = float(cash)
        self.holdings: dict = {}
        self.securities = None
        self.TotalMarginUsed = 0.0

    def __getitem__(self, symbol):
        if symbol not in self.holdings:
            self.holdings[symbol] = FakeHolding(symbol, self.securities.get(symbol) if self.securities is not None else None)
        return self.holdings[symbol]

    @property
    def Values(self) -> list:
        return list(self.holdings.values())

    @property
    def TotalHoldingsValue(self) -> float:
        return sum(holding.HoldingsValue for holding in self.holdings.values())

    @property
    def TotalPortfolioValue(self) -> float:
        return self.Cash + self.TotalHoldingsValue

    @property
    def CashBook(self) -> dict:
        return {"USD": SimpleNamespace(Amount=self.Cash, ValueInAccountCurrency=self.Cash, ConversionRate=1.0, Symbol="USD", AddAmount=self._add_cash)}

    def _add_cash(self, amount: float) -> None:
        self.Cash += float(amount)

    @property
    def MarginRemaining(self) -> float:
        return self.TotalPortfolioValue

    @property
    def Invested(self) -> bool:
        return any(holding.Invested for holding in self.holdings.values())

    def apply(self, symbol, quantity: float, price: float) -> None:
        holding = self[symbol]
        new_quantity = holding.Quantity + quantity
        if abs(new_quantity) < 1e-12:
            holding.AveragePrice = 0.0
        elif holding.Quantity == 0 or (holding.Quantity > 0) != (new_quantity > 0):
            holding.AveragePrice = price
        elif (holding.Quantity > 0) == (quantity > 0):
            holding.AveragePrice = (holding.AveragePrice * abs(holding.Quantity) + price * abs(quantity)) / abs(new_quantity)
        holding.Quantity = holding.quantity = new_quantity
        self.Cash -= quantity * price


class FakeSecurity:
    def __init__(self, symbol, price: float, security_type: str):
        self.Symbol = self.symbol = symbol
        self.Price = self.price = self.Close = self.close = float(price)
        self.Open = self.High = self.Low = float(price)
        self.Volume = 1_000_000.0
        self.SecurityType = security_type
        self.SymbolProperties = SimpleNamespace(LotSize=1.0, MinimumPriceVariation=0.01, ContractMultiplier=1.0, QuoteCurrency="USD")
        self.QuoteCurrency = SimpleNamespace(Symbol="USD", ConversionRate=1.0)
        self.DataNormalizationMode = "Raw"
        self.BuyingPowerModel = MagicMock(name="BuyingPowerModel")
        self.Underlying = None
        self.fee_model = None

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value

    def SetFilter(self, *args, **kwargs) -> None:
        return None

    def SetSlippageModel(self, model) -> None:
        self.slippage_model = model

    def SetFeeModel(self, model) -> None:
        self.fee_model = model

    def SetBuyingPowerModel(self, model) -> None:
        self.BuyingPowerModel = model

    set_filter, set_slippage_model, set_fee_model, set_buying_power_model = SetFilter, SetSlippageModel, SetFeeModel, SetBuyingPowerModel


class FakeTicket:
    def __init__(self, order_id: int, symbol, quantity: float, status: str, *, limit_price: float | None = None, tag: str = ""):
        self.OrderId = order_id
        self.Symbol = symbol
        self.Quantity = quantity
        self.QuantityFilled = quantity if status == "Filled" else 0.0
        self.QuantityRemaining = 0.0 if status == "Filled" else quantity
        self.Status = status
        self.LimitPrice = limit_price
        self.Tag = tag
        self.cancelled = False

    def Cancel(self, *args, **kwargs):
        self.cancelled = True
        self.Status = "Canceled"
        self.QuantityRemaining = 0.0
        return SimpleNamespace(IsSuccess=True)

    def Update(self, *args, **kwargs):
        return SimpleNamespace(IsSuccess=True)

    def GetMostRecentOrderResponse(self):
        return SimpleNamespace(IsSuccess=True, ErrorMessage="")


class FakeTransactions:
    def __init__(self):
        self.tickets: list = []
        self.orders: dict = {}

    @property
    def OrdersCount(self) -> int:
        return len(self.tickets)

    def GetOrderById(self, order_id):
        return self.orders.get(order_id)

    def GetOpenOrderTickets(self, *args, **kwargs):
        return [ticket for ticket in self.tickets if ticket.Status in ("Submitted", "New")]

    GetOpenOrders = GetOpenOrderTickets


class FakeSecurities(dict):
    """Securities by symbol; an option contract main.py orders without subscribing it gets a security on first use."""

    def __missing__(self, symbol):
        security = FakeSecurity(symbol, 5.0, getattr(symbol, "SecurityType", "option"))
        self[symbol] = security
        return security


class FakeStrategy:
    """What `OptionStrategies.<name>(canonical, *strikes, expiry)` returns: the factory name and its arguments, and the legs Lean would build from them."""

    def __init__(self, name: str, canonical, args: tuple):
        self.name, self.canonical, self.args = name, canonical, args
        self.CanonicalOption = canonical

    def _spec(self):
        from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY

        return next(item for item in MULTI_LEG_STRATEGY_REGISTRY.values() if item.factory_name == self.name)

    @property
    def OptionLegs(self) -> list:
        spec = self._spec()
        strikes = {role: float(value) for role, value in zip(spec.arg_order, self.args)}
        expiries = [argument for argument in self.args if isinstance(argument, datetime.datetime)]
        legs = []
        for index, leg in enumerate(spec.legs):
            expiry = expiries[min(index % max(len(expiries), 1), len(expiries) - 1)] if expiries else None
            legs.append(SimpleNamespace(Right="Call" if leg.right == "call" else "Put", Strike=strikes[leg.strike_role], Expiration=expiry, Quantity=(1 if leg.side == "long" else -1) * leg.ratio))
        return legs

    @property
    def UnderlyingLegs(self) -> list:
        side = self._spec().covering_equity_side
        return [SimpleNamespace(Quantity=100 if side == "long" else -100)] if side else []


LATEST_CHAINS: dict = {}


def create_option(underlying, market, style, right, strike, expiry):
    """Lean's `Symbol.CreateOption`: the contract of the chain this world last published (the same symbol object its rows carry)."""
    for chain in LATEST_CHAINS.values():
        for contract in chain.contracts.values():
            if contract.right == right and abs(contract.strike - float(strike)) < 1e-6 and (expiry is None or contract.expiry.date() == expiry.date()):
                return contract.symbol
    return FakeSymbol(f"{right}{strike}", "option")


class FakeOptionStrategies:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda canonical, *args: FakeStrategy(name, canonical, args)


class FakeLean(PermissiveQC):
    """QCAlgorithm's portfolio, securities, order and subscription surface, with instant market fills at the security's price. Everything else stays permissive."""

    def __init__(self):
        object.__setattr__(self, "Securities", FakeSecurities())
        object.__setattr__(self, "chains", {})
        object.__setattr__(self, "securities", self.Securities)
        portfolio = FakePortfolio(100_000.0)
        portfolio.securities = self.Securities
        object.__setattr__(self, "Portfolio", portfolio)
        object.__setattr__(self, "portfolio", portfolio)
        object.__setattr__(self, "Transactions", FakeTransactions())
        object.__setattr__(self, "transactions", self.Transactions)
        object.__setattr__(self, "IsWarmingUp", False)
        object.__setattr__(self, "is_warming_up", False)
        object.__setattr__(self, "Time", datetime.datetime(2019, 1, 2))
        object.__setattr__(self, "time", self.Time)
        object.__setattr__(self, "order_log", [])
        object.__setattr__(self, "_order_id", 0)
        object.__setattr__(self, "_events", [])

    def set_cash(self, amount: float) -> None:
        self.Portfolio.Cash = float(amount)

    SetCash = set_cash

    def _add(self, ticker: str, security_type: str, price: float = 100.0):
        symbol = FakeSymbol(ticker, security_type)
        security = FakeSecurity(symbol, price, security_type)
        self.Securities[symbol] = security
        return security

    def add_equity(self, ticker, resolution=None, *args, **kwargs):
        return self._add(ticker, "equity")

    def add_crypto(self, ticker, resolution=None, market=None, *args, **kwargs):
        return self._add(ticker, "crypto")

    def add_forex(self, ticker, resolution=None, market=None, *args, **kwargs):
        return self._add(ticker, "forex", 1.1)

    def add_future(self, ticker, resolution=None, *args, **kwargs):
        return self._add(ticker, "future", 4000.0)

    def add_option(self, ticker, resolution=None, *args, **kwargs):
        return self._add(f"?{ticker}", "option")

    def _ticket(self, symbol, quantity: float, status: str, *, limit_price: float | None = None, tag: str = "") -> FakeTicket:
        object.__setattr__(self, "_order_id", self._order_id + 1)
        ticket = FakeTicket(self._order_id, symbol, quantity, status, limit_price=limit_price, tag=tag)
        self.Transactions.tickets.append(ticket)
        self.Transactions.orders[ticket.OrderId] = SimpleNamespace(Id=ticket.OrderId, Symbol=symbol, Quantity=quantity, CreatedTime=self.Time,
                                                                   OrderSubmissionData=SimpleNamespace(BidPrice=0.0, AskPrice=0.0, LastPrice=0.0))
        self.order_log.append((str(symbol), quantity, status, tag))
        return ticket

    def _event(self, ticket, status: str, quantity: float, price: float) -> None:
        self._events.append(SimpleNamespace(Symbol=ticket.Symbol, Status=status, FillQuantity=quantity, FillPrice=price, OrderId=ticket.OrderId, UtcTime=self.Time, Message="", Direction="Buy" if quantity > 0 else "Sell"))

    def flush_events(self) -> None:
        """Deliver the order events queued since the last call, as Lean does after the algorithm returns from `on_data`."""
        queued, self._events[:] = list(self._events), []
        for event in queued:
            self.on_order_event(event)

    def MarketOrder(self, symbol, quantity, asynchronous=False, tag="", *args, **kwargs):
        quantity = float(quantity)
        if quantity == 0:
            return self._ticket(symbol, 0.0, "Invalid", tag=tag)
        price = float(self.Securities[symbol].Price)
        self.Portfolio.apply(symbol, quantity, price)
        ticket = self._ticket(symbol, quantity, "Filled", tag=tag)
        self._event(ticket, "Filled", quantity, price)
        return ticket

    market_order = MarketOrder

    def LimitOrder(self, symbol, quantity, limit_price, tag="", *args, **kwargs):
        return self._ticket(symbol, float(quantity), "Submitted", limit_price=float(limit_price), tag=tag)

    limit_order = LimitOrder

    def ComboLimitOrder(self, legs, quantity, limit_price, tag="", *args, **kwargs):
        return [self._ticket(leg.Symbol if hasattr(leg, "Symbol") else leg, float(quantity), "Submitted", limit_price=float(limit_price), tag=tag) for leg in legs]

    def Liquidate(self, symbol=None, tag="", *args, **kwargs):
        tickets = []
        for held, holding in list(self.Portfolio.holdings.items()):
            if (symbol is None or held == symbol) and holding.Invested:
                tickets.append(self.MarketOrder(held, -holding.Quantity, tag=tag))
        return tickets

    liquidate = Liquidate

    def CalculateOrderQuantity(self, symbol, weight):
        price = float(self.Securities[symbol].Price)
        return round(weight * self.Portfolio.TotalPortfolioValue / price, 0) - self.Portfolio[symbol].Quantity

    def SetHoldings(self, symbol, weight, liquidate_existing_holdings=False, tag="", *args, **kwargs):
        quantity = self.CalculateOrderQuantity(symbol, weight)
        return [self.MarketOrder(symbol, quantity, tag=tag)] if quantity else []

    set_holdings = SetHoldings

    def _strategy_legs(self, strategy: FakeStrategy) -> list:
        """(contract symbol, signed ratio) of each leg of a multi-leg strategy, matched to the chain this world last published."""
        from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY

        spec = next(item for item in MULTI_LEG_STRATEGY_REGISTRY.values() if item.factory_name == strategy.name)
        chain = self.chains.get(str(strategy.canonical))
        expiries = [argument for argument in strategy.args if isinstance(argument, datetime.datetime)]
        strikes = {role: value for role, value in zip(spec.arg_order, strategy.args)}
        legs = []
        for leg in spec.legs:
            strike = strikes[leg.strike_role]
            wanted = "Call" if leg.right == "call" else "Put"
            matches = [contract for contract in (chain.contracts.values() if chain is not None else []) if contract.right == wanted and abs(contract.strike - float(strike)) < 1e-6
                       and (not expiries or contract.expiry.date() in {expiry.date() for expiry in expiries})]
            if matches:
                legs.append((matches[0].symbol, (1 if leg.side == "long" else -1) * leg.ratio))
        return legs

    def _trade_strategy(self, strategy: FakeStrategy, quantity: float, sign: int) -> list:
        return [self.MarketOrder(contract_symbol, sign * ratio * quantity) for contract_symbol, ratio in self._strategy_legs(strategy)]

    def Buy(self, symbol, quantity=1, *args, **kwargs):
        if isinstance(symbol, FakeStrategy):
            return self._trade_strategy(symbol, quantity, 1)
        return [self.MarketOrder(symbol, quantity)] if hasattr(symbol, "Value") else []

    def Sell(self, symbol, quantity=1, *args, **kwargs):
        if isinstance(symbol, FakeStrategy):
            return self._trade_strategy(symbol, quantity, -1)
        return [self.MarketOrder(symbol, -quantity)] if hasattr(symbol, "Value") else []

    def option_leg(self, canonical_key: str, right: str, strike: float, days: int = 30):
        """The chain contract of `canonical_key` with this right, strike and (roughly) this many days to expiry."""
        chain = self.chains[canonical_key]
        return min((c for c in chain.contracts.values() if c.right == right and abs(c.strike - strike) < 1e-6), key=lambda c: abs((c.expiry - self.Time).days - days))

    def fill_limit_orders(self) -> list:
        """Fill every resting limit order at its limit price."""
        filled = []
        for ticket in self.Transactions.GetOpenOrderTickets():
            ticket.Status, ticket.QuantityFilled, ticket.QuantityRemaining = "Filled", ticket.Quantity, 0.0
            self.Portfolio.apply(ticket.Symbol, ticket.Quantity, ticket.LimitPrice)
            self._event(ticket, "Filled", ticket.Quantity, ticket.LimitPrice)
            filled.append(ticket)
        return filled

    def advance(self, when: datetime.datetime, prices: dict) -> None:
        object.__setattr__(self, "Time", when)
        for symbol, security in self.Securities.items():
            price = prices.get(str(symbol))
            if price is not None:
                security.Price = security.price = security.Close = security.close = security.Open = security.High = security.Low = float(price)


def bar_of(price: float, when: datetime.datetime, volume: float = 1_000_000.0, spread: float = 0.01) -> SimpleNamespace:
    return SimpleNamespace(open=price * (1 - spread / 2), high=price * (1 + spread), low=price * (1 - spread), close=price, volume=volume, Time=when, EndTime=when, is_fill_forward=False,
                           Open=price * (1 - spread / 2), High=price * (1 + spread), Low=price * (1 - spread), Close=price, Volume=volume)


def quote_of(price: float, when: datetime.datetime, spread: float = 0.0002, fill_forward: bool = False) -> SimpleNamespace:
    """A forex QuoteBar: a bid side and an ask side, each with its own OHLC."""
    def side(factor: float) -> SimpleNamespace:
        value = price * factor
        return SimpleNamespace(Open=value, High=value * 1.001, Low=value * 0.999, Close=value)

    return SimpleNamespace(Bid=side(1 - spread), Ask=side(1 + spread), IsFillForward=fill_forward, EndTime=when)


def option_chain(canonical, ticker: str, underlying, spot: float, when: datetime.datetime, *, days=(30, 60), moneyness=(0.9, 0.95, 1.0, 1.05, 1.1)) -> SimpleNamespace:
    """A small chain: calls and puts at each strike and expiry, priced by a rough intrinsic-plus-time-value rule, with no greeks (main.py solves them)."""
    contracts = {}
    for offset in days:
        expiry = when + datetime.timedelta(days=offset)
        for pct in moneyness:
            strike = float(round(spot * pct))
            for right in ("Call", "Put"):
                symbol = FakeSymbol(f"{ticker} {expiry:%y%m%d}{right[0]}{int(strike)}", "option", underlying=underlying)
                symbol.ID = SimpleNamespace(Symbol=ticker, StrikePrice=strike, OptionRight=right, Date=expiry)
                intrinsic = max(spot - strike, 0.0) if right == "Call" else max(strike - spot, 0.0)
                mid = intrinsic + 0.04 * spot * (offset / 365.0) ** 0.5 + 0.05
                contracts[symbol] = SimpleNamespace(symbol=symbol, right=right, expiry=expiry, strike=strike, bid_price=round(mid * 0.98, 2), ask_price=round(mid * 1.02, 2), last_price=round(mid, 2),
                                                    volume=200.0, open_interest=800.0, greeks=None, implied_volatility=0.0, underlying_last_price=spot)
    return SimpleNamespace(contracts=contracts, underlying=underlying)


class Market:
    """A seeded random walk per symbol, delivered as Lean slices: equity bars on weekdays, crypto and forex every day."""

    def __init__(self, algorithm, seed: int = 0, start: datetime.datetime = datetime.datetime(2019, 1, 2)):
        self.algorithm = algorithm
        self.rng = np.random.default_rng(seed)
        self.when = start
        self.index = 0
        self.prices = {str(symbol): 100.0 + 10 * position for position, symbol in enumerate(algorithm.symbols)}

    def slice(self, *, drop: tuple[str, ...] = (), forex_quotes: bool = False, extra: dict | None = None, fill_forward: tuple[str, ...] = (), zero_volume: tuple[str, ...] = (),
              splits: dict | None = None) -> SimpleNamespace:
        bars, quotes = {}, {}
        for symbol in self.algorithm.symbols:
            key = str(symbol)
            self.prices[key] *= float(np.exp(self.rng.normal(0.0004, 0.012)))
            asset = self.algorithm.asset_lookup[key]
            kind = asset["security_type"]
            if kind == "option":
                underlying = asset.get("underlying_ticker")
                if underlying in self.prices:
                    self.prices[key] = self.prices[underlying]
            if key in drop or (kind == "equity" and self.when.weekday() >= 5):
                continue
            if kind == "forex" and forex_quotes:
                quotes[symbol] = quote_of(self.prices[key], self.when, fill_forward=key in fill_forward)
                continue
            bar = bar_of(self.prices[key], self.when, volume=0.0 if key in zero_volume else 1_000_000.0)
            bar.is_fill_forward = bar.IsFillForward = key in fill_forward
            bars[symbol] = bar
        self.algorithm.advance(self.when, self.prices)
        chains = {}
        for symbol in self.algorithm.symbols:
            asset = self.algorithm.asset_lookup[str(symbol)]
            if asset["security_type"] == "option" and str(symbol) not in drop:
                underlying = next((other for other in self.algorithm.symbols if self.algorithm.asset_lookup[str(other)]["ticker"] == asset.get("underlying_ticker")), None)
                chain = option_chain(symbol, asset["ticker"], underlying, self.prices[str(symbol)], self.when)
                chains[symbol] = chain
                self.algorithm.chains[str(symbol)] = chain
                LATEST_CHAINS[str(symbol)] = chain
                for contract in chain.contracts.values():
                    security = self.algorithm.Securities[contract.symbol]
                    security.Price = security.price = (contract.bid_price + contract.ask_price) / 2.0
        data = {"Bars": bars, "bars": bars, "QuoteBars": quotes, "quote_bars": quotes, "splits": splits or {}, "Splits": splits or {}, "option_chains": chains, "OptionChains": chains, "futures_chains": {},
                "future_chains": {}, "Time": self.when}
        data.update(extra or {})
        return SimpleNamespace(**data)

    def step(self, *, fill_limits: bool = True, **kwargs) -> SimpleNamespace:
        market_slice = self.slice(**kwargs)
        if fill_limits and self.index % 2 == 1:
            self.algorithm.fill_limit_orders()
        self.algorithm.on_data(market_slice)
        self.algorithm.flush_events()
        self.when += datetime.timedelta(days=1)
        self.index += 1
        return market_slice

    def run(self, days: int, **kwargs) -> None:
        for _ in range(days):
            self.step(**kwargs)
