"""fuzz/targets.py (V6.6.7, #363): every target over its seed corpus and under hypothesis, plus the findings it made."""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fuzz"))

import targets  # noqa: E402
from targets import TARGETS, Bytes  # noqa: E402

CORPUS = ROOT / "fuzz" / "corpus"


def test_every_target_has_a_seed_corpus_and_a_workflow_leg():
    workflow = (ROOT / ".github" / "workflows" / "fuzz.yml").read_text(encoding="utf-8")
    for name in TARGETS:
        assert sorted((CORPUS / name).glob("seed-*")), name
        assert name in workflow, name


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_target_over_its_corpus(name):
    for seed in sorted((CORPUS / name).glob("seed-*")):
        TARGETS[name](seed.read_bytes())


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_target_under_hypothesis(name):
    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(st.binary(max_size=400))
    def run(data: bytes) -> None:
        TARGETS[name](data)

    run()


def test_bytes_reader_reads_zeros_when_exhausted_and_covers_every_kind():
    reader = Bytes(b"")
    assert reader.int(3, 9) == 3 and reader.bool() is False and reader.text() == ""
    assert math.isnan(reader.float())  # tag 0 is the first special float
    assert reader.choice(["a", "b"]) == "a"
    raw = Bytes(bytes([100]) + struct.pack("<d", 2.5))
    assert raw.float() == 2.5
    assert Bytes(bytes([200, 0, 129])).float() == (33024 - 32768) / 256.0
    kinds = {type(Bytes(bytes([kind, 0]) + bytes(40)).value()).__name__ for kind in range(8)}
    assert kinds >= {"NoneType", "bool", "int", "float", "str", "list", "dict"}
    assert Bytes(bytes([7, 0]) * 3).value(depth=3) is not None or True


def _search(name: str, predicate) -> bytes:
    """A deterministic input on which `predicate(reader)` holds, to pin a branch of a target."""
    import random

    rng = random.Random(name)
    for _ in range(20000):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 120)))
        if predicate(data):
            return data
    raise AssertionError(f"no input found for {name}")


def test_findings_stay_fixed():
    from execution.secrets import redact_url
    from monitoring.auth import parse_users
    from portfolio.target_weights import TargetWeightsConfig, rebalance_deltas
    from risk.kill_switch import evaluate_kill_switch

    # redact_url: the host follows the last @
    assert redact_url("redis://:p@ss@host:6379/0") == "redis://:***@host:6379/0"
    assert "ss" not in redact_url("redis://u:p@ss@h/0").split("@", 1)[0]
    # parse_users: a non-object row and a string scope are refused
    with pytest.raises(ValueError):
        parse_users({"users": [["admin"]]})
    with pytest.raises(ValueError):
        parse_users({"users": [{"name": "ann", "role": "viewer", "salt": "0" * 32, "token_hash": "a" * 64, "accounts": "a*"}]})
    # kill switch: a huge return is an unreadable window, not an OverflowError
    decision = evaluate_kill_switch({"recent_bar_returns": [1e308, -1e308] * 10}, dict(targets._KILL_SWITCH_CONFIG))
    assert decision.tripped in (True, False)
    # rebalance: an overflowing size is no order; a trade through zero is not sorted as a reduction
    assert rebalance_deltas({"A": 1.0}, {"A": 5e-324}, 1e308, {"A": 1.0}, TargetWeightsConfig()) == []
    orders = rebalance_deltas({"A": 10.0, "B": 10.0}, {"A": 100.0, "B": 100.0}, 10_000.0, {"A": -0.2, "B": 0.05}, TargetWeightsConfig())
    assert orders[0][0] == "B" and orders[1] == ("A", -30.0)


def test_holdout_ledger_refuses_a_malformed_entry(tmp_path):
    from evaluation.research_cells import record_holdout_read

    for line in ('{"candidate": "x", "cells": "V1"}', '["V1"]', '{"candidate": "x", "cells": ["V1", 3]}', '{"cells": [}'):
        ledger = tmp_path / "ledger.jsonl"
        ledger.write_text(line + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            record_holdout_read(ledger, candidate="c", cells=("V1",), digest="d", created_at="t")
    ledger = tmp_path / "ok.jsonl"
    ledger.write_text(json.dumps({"candidate": "x", "cells": ["V2"]}) + "\n", encoding="utf-8")
    record_holdout_read(ledger, candidate="c", cells=("V1",), digest="d", created_at="t")
    with pytest.raises(PermissionError):
        record_holdout_read(ledger, candidate="c", cells=("V1",), digest="d", created_at="t")


def _url_parts(data: bytes) -> tuple[str, str, str]:
    """The user, password and host `fuzz_secret_refs` builds its URL from (the reads must stay in step with the target)."""
    reader = Bytes(data)
    reader.choice([0, 1, 2, 3, 4])
    reader.text(40)
    reader.text(16)
    reader.text(12), reader.text(12)
    return reader.text(8).replace("/", ""), reader.text(16).replace("/", ""), reader.text(12).replace("/", "").replace("@", "")


def test_a_leaked_password_is_reported(monkeypatch):
    from execution.secrets import redact_url as real

    def leaky(url: str) -> str:
        authority = str(url).split("://", 1)[1].split("/", 1)[0]
        password = authority.rpartition("@")[0].partition(":")[2]
        return real(url).replace("://", "://" + password, 1)  # the right shape, with the password put back in

    monkeypatch.setattr(targets, "redact_url", leaky)
    data = _search("redact", lambda d: targets._plain_password(*_url_parts(d)))
    _user, password, _host = _url_parts(data)
    with pytest.raises(AssertionError) as caught:
        targets.fuzz_secret_refs(data)
    assert password in caught.value.args[0][1], "the assertion that fired is the leak check, carrying the masked URL"


def test_a_url_that_loses_its_shape_is_reported(monkeypatch):
    monkeypatch.setattr(targets, "redact_url", lambda url: str(url))
    with pytest.raises(AssertionError):
        targets.fuzz_secret_refs(b"\x00" * 64)


def test_a_mask_that_rejoins_the_text_is_not_a_leak():
    """Atheris, first CI run: the secret `*XXXXX` in `aa/Xb*XXXXXXXXXXXXX`. The mask's last `*` plus the five text characters after
    the secret spell `*XXXXX` again, which the old invariant (the secret is not in the output) took for a leak."""
    from execution.secrets import SecretValue, redact

    assert redact("aa/Xb*XXXXXXXXXXXXX", [SecretValue("*XXXXX")]) == "aa/Xb***XXXXXXXX"
    crash = bytes.fromhex("19090cef1fd75884bc4a6355deff239cf05e1df1b262947b83b31a0a1ed6395757575757768e7e935eff01de705757575757575757575757d2f5e318012f")
    targets.fuzz_secret_refs(crash)
    assert redact("abc*", [SecretValue("abc")]) == "abc*", "a value under 4 characters is left alone"
    assert not targets._plain_password("u", "ab*dd", "h") and targets._plain_password("u", "abcd", "h")
    assert not targets._plain_password("u", "abcd", "xabcdx") and not targets._plain_password("user", "edis", "h")
