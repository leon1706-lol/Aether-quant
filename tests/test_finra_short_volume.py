"""data_pipeline/finra_short_volume.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.finra_short_volume import finra_symbol, parse_day


def test_symbols_and_a_day_file():
    assert finra_symbol("BRK.B") == "BRK/B" and finra_symbol("SPY") == "SPY"
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260102|SPY|40|0|100|B\n20260102|ZZZ|1|0|0|B\n1\n"
    ratios = parse_day(text)
    assert ratios.get("SPY") == 0.4 and "ZZZ" not in ratios
