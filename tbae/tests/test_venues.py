"""Tests for :mod:`engine.venues` — per-symbol cost calibration.

The engine used to charge every symbol the same market impact and the same
spread floor, which made cross-symbol comparisons quietly unfair.  These tests
pin the two measurements that replaced those placeholders, and — more
importantly — pin the *direction*: a thin or coarse-tick symbol must come out
more expensive, never cheaper, than the deep fine-tick one.
"""

from __future__ import annotations

import os

import pytest

_TBAE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.models import MinuteBar
from engine.risk import CostConfig
from engine.venues import (calibrate_costs, estimate_adv_notional,
                           estimate_tick_size, friction_per_r, symbol_from_path)

MIN = 60_000


def series(price0: float, tick: float, quote_per_min: float, n: int = 4000,
           start: int = 1_700_000_000_000) -> list[MinuteBar]:
    """A synthetic series whose prices sit exactly on multiples of ``tick``."""
    out = []
    for i in range(n):
        p = price0 + (i % 9) * tick
        out.append(MinuteBar(ts=start + i * MIN, open=p, high=p + 8 * tick,
                             low=max(tick, p - 8 * tick), close=p, volume=10.0,
                             quote_volume=quote_per_min, trades=4))
    return out


BTC = series(100_000.0, 0.01, 100_000.0)      # deep, fine tick
XRP = series(2.5, 0.0001, 2_500.0)            # thin, coarse tick


# --------------------------------------------------------------------------- #
# tick estimation
# --------------------------------------------------------------------------- #
def test_tick_is_recovered_exactly_despite_float_error():
    """100000.03 − 100000.02 is 0.00999999999476131 in binary floating point.

    Without significant-digit rounding the estimator returns that residue
    instead of 0.01, and every downstream spread number inherits the noise.
    """
    assert estimate_tick_size(BTC) == pytest.approx(0.01)
    assert estimate_tick_size(XRP) == pytest.approx(0.0001)


def test_tick_estimation_is_scale_independent():
    """The same relative tick at wildly different price scales."""
    assert estimate_tick_size(series(1.0, 1e-6, 10.0)) == pytest.approx(1e-6)
    assert estimate_tick_size(series(1e6, 0.1, 10.0)) == pytest.approx(0.1)


def test_tick_on_empty_or_flat_series_is_none():
    assert estimate_tick_size([]) is None
    flat = series(5.0, 0.0, 10.0, n=50)       # every price identical
    assert estimate_tick_size(flat) is None


# --------------------------------------------------------------------------- #
# ADV estimation
# --------------------------------------------------------------------------- #
def test_adv_is_a_full_day_not_a_partial_one():
    """A window that starts and ends mid-day carries two stubs.

    Measured on a 3-day sample this read 77M instead of 144M — a 46% error in
    the impact term, purely from where the window happened to be cut.
    """
    got = estimate_adv_notional(BTC)
    assert got == pytest.approx(144_000_000.0, rel=0.02)


def test_adv_scales_with_the_symbol():
    assert estimate_adv_notional(BTC) > 10 * estimate_adv_notional(XRP)


def test_adv_on_empty_series_is_none():
    assert estimate_adv_notional([]) is None


# --------------------------------------------------------------------------- #
# calibration
# --------------------------------------------------------------------------- #
def test_calibration_replaces_both_placeholders():
    costs, info = calibrate_costs(XRP)
    assert costs.adv_notional == pytest.approx(estimate_adv_notional(XRP))
    assert info["measured"] == ["adv_notional"]
    assert info["tick_size"] == pytest.approx(0.0001)
    assert info["slippage_bps"] == costs.slippage_bps


def test_calibration_leaves_the_fee_schedule_alone():
    """Fees depend on the account's VIP tier, not on the market — the estimator
    must not invent them."""
    base = CostConfig(commission_bps=7.5, maker_bps=2.0)
    costs, info = calibrate_costs(XRP, base)
    assert costs.commission_bps == 7.5
    assert costs.maker_bps == 2.0
    assert "commission_bps" in info["assumed"]


def test_calibration_does_not_mutate_its_input():
    base = CostConfig()
    before = base.adv_notional
    calibrate_costs(XRP, base)
    assert base.adv_notional == before


def test_thin_symbol_is_charged_more_impact_not_less():
    """The whole point of measuring: with a constant ADV, XRP looked as liquid
    as BTC and its impact was understated by ~6x."""
    cb, _ = calibrate_costs(BTC)
    cx, _ = calibrate_costs(XRP)
    notional = 50_000.0
    assert cx.impact_bps(notional) > cb.impact_bps(notional)
    ratio = cx.impact_bps(notional) / cb.impact_bps(notional)
    assert ratio == pytest.approx(6.3, rel=0.1)


def test_tick_floor_raises_slippage_when_the_tick_is_coarse():
    """A symbol whose tick is a large fraction of its price cannot be crossed
    for less than half of it, however liquid it is."""
    coarse = series(1.0, 0.01, 10_000.0)      # tick is ~1% of the price
    costs, info = calibrate_costs(coarse, CostConfig(slippage_bps=2.0))
    assert info["slippage_raised_by_tick"] is True
    expected = 0.5 * info["tick_size"] / info["median_price"] * 10_000.0
    assert costs.slippage_bps == pytest.approx(expected, rel=1e-6)
    assert costs.slippage_bps > 40.0, "a 1%-of-price tick is nowhere near 2 bp"
    assert "slippage_bps" in info["measured"]


def test_declared_slippage_survives_when_it_is_already_wider():
    costs, info = calibrate_costs(BTC, CostConfig(slippage_bps=5.0))
    assert info["slippage_raised_by_tick"] is False
    assert costs.slippage_bps == 5.0
    assert "slippage_bps" in info["assumed"]


def test_calibration_is_disabled_on_request():
    costs, _ = calibrate_costs(XRP, apply_tick_floor=False)
    assert costs.adv_notional == pytest.approx(estimate_adv_notional(XRP))


def test_calibration_validates_the_result():
    costs, _ = calibrate_costs(XRP)
    costs.validate()                 # raises if ADV went non-positive


# --------------------------------------------------------------------------- #
# friction in R — the unit comparisons must be made in
# --------------------------------------------------------------------------- #
def test_friction_per_r_shrinks_as_the_stop_widens():
    c = CostConfig(commission_bps=4.0, maker_bps=1.0, slippage_bps=2.0)
    tight = friction_per_r(c, 0.5)      # 0.5% stop
    wide = friction_per_r(c, 2.0)       # 2% stop
    assert tight == pytest.approx(4 * wide)
    assert tight == pytest.approx(0.18, abs=1e-9)


def test_friction_per_r_rejects_a_non_positive_stop():
    assert friction_per_r(CostConfig(), 0.0) is None
    assert friction_per_r(CostConfig(), -1.0) is None


# --------------------------------------------------------------------------- #
# label
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,expected", [
    ("data/binance/XRPUSDT_1m_20230101_20260918.csv.gz", "XRPUSDT"),
    ("BTCUSDT_1m_20230101_20230102.csv", "BTCUSDT"),
    ("/abs/path/ETHUSDT_1m.csv", "ETHUSDT"),
])
def test_symbol_from_path(path, expected):
    assert symbol_from_path(path) == expected


# --------------------------------------------------------------------------- #
# how the CLI decides — the synthetic study must not silently move
# --------------------------------------------------------------------------- #
def test_cli_leaves_synthetic_on_the_declared_placeholders(tmp_path):
    """The published synthetic study is a baseline.  Calibrating it would shift
    every one of its numbers and make old reports non-comparable, and its
    "tick" would be float residue off the generator rather than a venue rule."""
    import sys
    sys.path.insert(0, str(_TBAE))
    from app import cli

    args = cli.build_parser().parse_args(["backtest", "--tf", "60", "--days", "20"])
    res = cli._build(args)
    rcfg = cli._risk_config(args, res)
    assert rcfg.cost_calibration == {}
    assert rcfg.costs.adv_notional == 2.0e8


def test_cli_calibrates_a_real_csv_and_records_provenance(tmp_path):
    import sys
    sys.path.insert(0, str(_TBAE))
    from app import cli
    from engine.feeds import write_minutes_csv

    path = tmp_path / "XRPUSDT_1m_20230101_20230131.csv"
    write_minutes_csv(series(2.5, 0.0001, 2500.0, n=3000), str(path))

    args = cli.build_parser().parse_args(
        ["backtest", "--feed", f"csv:{path}", "--tf", "60"])
    res = cli._build(args)
    rcfg = cli._risk_config(args, res)
    assert rcfg.cost_calibration["symbol"] == "XRPUSDT"
    assert rcfg.cost_calibration["measured"] == ["adv_notional"]
    assert rcfg.costs.adv_notional == pytest.approx(3_600_000.0, rel=0.05)
    assert rcfg.costs.commission_bps == 4.0, "fees stay declared, never measured"


def test_cli_honours_no_calibrate_costs(tmp_path):
    import sys
    sys.path.insert(0, str(_TBAE))
    from app import cli
    from engine.feeds import write_minutes_csv

    path = tmp_path / "XRPUSDT_1m_20230101_20230131.csv"
    write_minutes_csv(series(2.5, 0.0001, 2500.0, n=3000), str(path))
    args = cli.build_parser().parse_args(
        ["backtest", "--feed", f"csv:{path}", "--tf", "60", "--no-calibrate-costs"])
    res = cli._build(args)
    rcfg = cli._risk_config(args, res)
    assert rcfg.cost_calibration == {}
    assert rcfg.costs.adv_notional == 2.0e8


def test_calibration_reaches_the_run_manifest(tmp_path):
    """A report that says which costs it used is reproducible; one that does
    not is a number looking for an assumption."""
    import sys
    sys.path.insert(0, str(_TBAE))
    from app import cli
    from engine import backtest as BT
    from engine.feeds import write_minutes_csv

    path = tmp_path / "XRPUSDT_1m_20230101_20230131.csv"
    write_minutes_csv(series(2.5, 0.0001, 2500.0, n=6000), str(path))
    args = cli.build_parser().parse_args(
        ["backtest", "--feed", f"csv:{path}", "--tf", "60"])
    res = cli._build(args)
    rcfg = cli._risk_config(args, res)
    r = BT.run_backtest(res, risk_cfg=rcfg)
    assert r.manifest["cost_calibration"]["symbol"] == "XRPUSDT"
    assert r.manifest["costs"]["adv_notional"] == pytest.approx(3_600_000.0, rel=0.05)
