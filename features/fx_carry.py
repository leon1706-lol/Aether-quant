"""FX carry feature (V5.7.0): the 3-month interest-rate differential of a currency pair, in percentage points.

Long the base currency of a pair earns (r_base - r_quote) of carry per year; the gap is the one slow, economically
grounded driver the forex rows of the model had no input for (they carried only price features and an all-zero asset
class). 0.0 for every non-forex row, so the column is constant outside the 15 pairs and the existing scaler / schema
handle it like any other feature.

Rates come from FRED (OECD 3-month interbank, monthly, plus the daily US Treasury 3-month bill), looked up through the
publication-lag-aware `series_value_asof()` that every other FRED-backed feature shares: a monthly observation dated the
1st of month M is published weeks later, so it is only used `FX_RATE_PUBLICATION_LAG_DAYS` after its date. One
definition for `train.py` and `main.py`: no formula is duplicated.
"""

from __future__ import annotations

from data_pipeline.fred_backfill import series_value_asof

FX_CARRY_FEATURE_NAME = "fx_carry_3m"

# currency -> friendly FRED series key (data/reference/fred_series/<key>.csv)
CURRENCY_RATE_SERIES = {
    "USD": "treasury_3mo",
    "EUR": "interbank_3m_eur",
    "GBP": "interbank_3m_gbp",
    "JPY": "interbank_3m_jpy",
    "AUD": "interbank_3m_aud",
    "CAD": "interbank_3m_cad",
    "CHF": "interbank_3m_chf",
    "NZD": "interbank_3m_nzd",
}
# Days between an observation's date and the day it may be used. The OECD monthly series is dated the 1st and published
# in the following month; 45 days is the conservative figure the plan fixed. The daily Treasury bill is a same-day mark.
FX_RATE_PUBLICATION_LAG_DAYS = {"treasury_3mo": 0, **{key: 45 for currency, key in CURRENCY_RATE_SERIES.items() if currency != "USD"}}


def split_forex_ticker(ticker: str) -> tuple[str, str] | None:
    """('EUR', 'USD') for 'EURUSD'; None unless the ticker is two known 3-letter currency codes."""
    text = str(ticker).upper()
    if len(text) != 6:
        return None
    base, quote = text[:3], text[3:]
    return (base, quote) if base in CURRENCY_RATE_SERIES and quote in CURRENCY_RATE_SERIES else None


def fx_carry_3m(
    ticker: str,
    asset_class: str | None,
    current_date,
    fred_series: dict[str, list[dict]],
    publication_lag_days: dict[str, int] | None = None,
) -> float:
    """r_base - r_quote at `current_date` (percentage points), 0.0 for a non-forex asset, an unparseable pair, or when
    either rate has no published observation yet (a missing rate must read as "no carry", never as a guessed rate)."""
    if asset_class != "forex":
        return 0.0
    pair = split_forex_ticker(ticker)
    if pair is None:
        return 0.0
    lags = {**FX_RATE_PUBLICATION_LAG_DAYS, **(publication_lag_days or {})}
    rates = []
    for currency in pair:
        key = CURRENCY_RATE_SERIES[currency]
        rate = series_value_asof(fred_series.get(key, []), current_date, lags.get(key, 0))
        if rate is None:
            return 0.0
        rates.append(rate)
    return float(rates[0] - rates[1])
