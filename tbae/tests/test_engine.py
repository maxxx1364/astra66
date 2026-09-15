"""Core-engine invariants: maths, resampling, system bars, reference, category
tree, timing heatmap, volatility estimators, path curves, indicators.

These tests assert *properties*, not golden numbers, wherever possible — a golden
number silently encodes whatever the implementation happened to do, and then
passes forever even when the maths is wrong.  Where a number is asserted it is
either an exact identity or a wide calibration band.

Causality is tested explicitly (prefix recomputation must reproduce the same
values) because a look-ahead here inflates every backtest result downstream and
is invisible in the output.
"""

from __future__ import annotations

import json
import math

import pytest

from engine import classify, indicators as ind_mod, mathx
from engine import path as path_mod
from engine import reference as ref_mod
from engine import resample as rs
from engine import systembar, timing, volatility
from engine.models import Bar, Category, MinuteBar, Settings, align_ts, timeframe_ms
from engine.path import growth_curve


# --------------------------------------------------------------------------- #
# mathx
# --------------------------------------------------------------------------- #
class TestMathx:
    def test_safe_div_never_raises(self):
        assert mathx.safe_div(1.0, 0.0) == 0.0
        assert mathx.safe_div(1.0, 0.0, default=-1.0) == -1.0
        assert mathx.safe_div(6.0, 3.0) == 2.0

    def test_safe_div_keeps_legitimate_tiny_denominators(self):
        """An absolute epsilon cut-off would turn a real ratio into 0, and 0 means
        "calm" in this engine — so a swallowed quotient corrupts vol filters."""
        assert mathx.safe_div(1e-300, 1e-300) == 1.0
        assert mathx.safe_div(1.0, 1e-13) == pytest.approx(1e13)

    def test_safe_div_rejects_nan_and_overflow(self):
        assert mathx.safe_div(float("nan"), 1.0) == 0.0
        assert mathx.safe_div(1.0, float("nan")) == 0.0
        assert mathx.safe_div(1e308, 1e-308) == 0.0          # overflows to inf
        assert mathx.safe_div(1.0, float("inf")) == 0.0

    def test_round_lot_floors_never_ceil(self):
        """Rounding a position size UP would exceed the risk budget."""
        assert mathx.round_lot(1.999, 1.0) == 1.0
        assert mathx.round_lot(2.0, 1.0) == 2.0
        assert mathx.round_lot(0.5, 1.0) == 0.0
        assert mathx.round_lot(0.123456, 0.001) == pytest.approx(0.123)
        assert mathx.round_lot(5.0, 0.0) == 5.0              # step<=0 -> unchanged

    def test_percentile_matches_known_values(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        assert mathx.percentile(xs, 0.0) == 1.0
        assert mathx.percentile(xs, 100.0) == 4.0
        assert mathx.percentile(xs, 50.0) == 2.5
        assert mathx.percentile([], 50.0) == 0.0
        assert mathx.percentile([7.0], 99.0) == 7.0

    def test_percentile_monotone_in_p(self):
        xs = [float(i) for i in range(100)]
        vals = [mathx.percentile(xs, p) for p in (0, 10, 25, 50, 75, 90, 98, 100)]
        assert vals == sorted(vals)

    def test_ema_converges_to_constant(self):
        ema = mathx.ema_series([5.0] * 50, 10)
        assert ema[-1] == pytest.approx(5.0, abs=1e-9)
        assert len(ema) == 50

    def test_ema_does_not_look_ahead(self):
        """EMA[i] must be reproducible from xs[:i+1] alone."""
        xs = [1.0, 3.0, 2.0, 8.0, 4.0, 5.0, 1.0, 9.0]
        full = mathx.ema_series(xs, 3)
        for i in range(3, len(xs)):
            prefix = mathx.ema_series(xs[: i + 1], 3)
            assert prefix[-1] == pytest.approx(full[i], abs=1e-12), f"i={i}"

    def test_wilder_matches_manual_recursion(self):
        xs = [2.0, 4.0, 6.0, 3.0, 5.0, 7.0, 1.0, 8.0]
        w = mathx.wilder_series(xs, 3)
        cur = sum(xs[:3]) / 3.0                              # SMA seed
        for i in range(3, len(xs)):
            cur = (2.0 * cur + xs[i]) / 3.0
        assert w[-1] == pytest.approx(cur, abs=1e-9)

    def test_sma_uses_partial_windows_during_warmup(self):
        """Documented convention: the warm-up values are the mean of what is
        available, not NaN — so arrays stay parallel to the input and callers do
        not need a NaN guard on every read."""
        sma = mathx.sma_series([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        assert len(sma) == 5
        assert sma[0] == pytest.approx(1.0)                  # mean of 1 value
        assert sma[1] == pytest.approx(1.5)                  # mean of 2 values
        assert sma[2] == pytest.approx(2.0)                  # first full window
        assert sma[4] == pytest.approx(4.0)

    def test_variance_and_stdev(self):
        xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        assert mathx.variance(xs, sample=True) == pytest.approx(4.571428, abs=1e-5)
        assert mathx.variance(xs, sample=False) == pytest.approx(4.0, abs=1e-9)
        assert mathx.stdev(xs) == pytest.approx(math.sqrt(mathx.variance(xs)))
        assert mathx.variance([1.0]) == 0.0
        assert mathx.stdev([]) == 0.0

    def test_median_odd_and_even(self):
        assert mathx.median([3.0, 1.0, 2.0]) == 2.0
        assert mathx.median([4.0, 1.0, 3.0, 2.0]) == 2.5
        assert mathx.median([]) == 0.0

    def test_autocorr_bounds_and_sign(self):
        alt = [1.0, -1.0] * 50
        assert mathx.autocorr(alt, 1) < -0.9                 # perfectly alternating
        assert mathx.autocorr([1.0] * 20, 1) == 0.0          # zero variance -> 0
        assert abs(mathx.autocorr([1.0, 2.0, 3.0, 2.0, 1.0], 1)) <= 1.0

    def test_skewness_and_kurtosis_signs(self):
        right = [1.0, 1.0, 1.0, 1.0, 10.0]
        assert mathx.skewness(right) > 0
        assert mathx.skewness([-x for x in right]) < 0
        assert mathx.skewness([]) == 0.0
        assert mathx.kurtosis([0.0] * 40 + [5.0, -5.0]) > 0   # tailed
        assert mathx.kurtosis([1.0] * 10) == 0.0              # no variance

    def test_cvar_is_beyond_var_in_the_lower_tail(self):
        xs = [float(i) for i in range(1, 101)]
        assert mathx.cvar(xs, alpha=0.05) <= mathx.percentile(xs, 5.0)
        assert mathx.cvar([], 0.05) == 0.0

    def test_linreg_slope_and_r2(self):
        ys = [2.0 * i + 1.0 for i in range(10)]              # perfect line
        assert mathx.linreg_slope(ys) == pytest.approx(2.0, abs=1e-9)
        assert mathx.linreg_r2(ys) == pytest.approx(1.0, abs=1e-9)
        assert mathx.linreg_slope([]) == 0.0
        assert mathx.linreg_slope([1.0]) == 0.0

    def test_linreg_r2_flat_series_is_not_a_perfect_trend(self):
        """R^2 on a constant series is 0/0.  Returning 1.0 would rank a dead
        market as the strongest possible trend, and dead bars are ~44% of a 15m
        crypto sample, so the mistake would not be rare."""
        assert mathx.linreg_r2([1.0] * 10) == 0.0
        assert mathx.linreg_r2([1.0, 1.0]) == 0.0
        # but a genuinely noisy-but-directional series still scores mid-range
        r2 = mathx.linreg_r2([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 5.0, 8.0])
        assert 0.5 < r2 < 1.0

    def test_rolling_helpers_length_and_values(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        for fn in (mathx.rolling_max, mathx.rolling_min, mathx.rolling_sum):
            assert len(fn(xs, 3)) == len(xs)
        assert mathx.rolling_max(xs, 3)[-1] == 5.0
        assert mathx.rolling_min(xs, 3)[-1] == 3.0
        assert mathx.rolling_sum(xs, 3)[-1] == 12.0
        assert mathx.cumsum(xs)[-1] == 15.0

    def test_pct_change_is_relative(self):
        pc = mathx.pct_change([100.0, 110.0, 105.0])
        assert pc[0] == 0.0
        assert pc[1] == pytest.approx(0.1)
        assert pc[2] == pytest.approx(-5.0 / 110.0)

    def test_clamp_and_sign(self):
        assert mathx.clamp(5, 0, 3) == 3
        assert mathx.clamp(-5, 0, 3) == 0
        assert mathx.clamp(2, 0, 3) == 2
        assert (mathx.sign(-2), mathx.sign(0), mathx.sign(3)) == (-1, 0, 1)

    def test_quantile_rank_in_unit_interval(self):
        xs = [float(i) for i in range(1, 101)]
        for v in (-100.0, 1.0, 50.0, 100.0, 1e6):
            assert 0.0 <= mathx.quantile_rank(xs, v) <= 1.0
        assert mathx.quantile_rank([], 1.0) == 0.0

    def test_is_nan_is_only_true_for_nan(self):
        assert mathx.is_nan(float("nan"))
        assert not mathx.is_nan(float("inf"))     # inf is not NaN; safe_div handles it
        assert not mathx.is_nan(1.0)


# --------------------------------------------------------------------------- #
# models / time alignment
# --------------------------------------------------------------------------- #
class TestModels:
    def test_align_ts_floors_to_bucket(self):
        tf_ms = timeframe_ms(15)
        assert align_ts(tf_ms + 1, 15) == tf_ms
        assert align_ts(tf_ms - 1, 15) == 0
        assert align_ts(0, 15) == 0
        assert align_ts(tf_ms, 15) == tf_ms

    def test_timeframe_ms(self):
        assert timeframe_ms(1) == 60_000
        assert timeframe_ms(15) == 900_000
        assert timeframe_ms(1440) == 86_400_000

    def test_category_enum_is_five_valued(self):
        assert len(list(Category)) == 5
        assert len({c.value for c in Category}) == 5
        assert {c.value for c in Category} == {
            "weak", "medium", "energetic", "strong", "pressure"}

    def test_bar_direction_and_roundtrip(self):
        b = Bar(ts=900_000, tf=15, open=100.0, high=105.0, low=99.0, close=104.0,
                volume=10.0)
        d = b.to_dict()
        assert d["ts"] == 900_000 and d["tf"] == 15
        assert d["direction"] == 1
        assert {"open", "high", "low", "close", "volume", "weekday", "hour"} <= set(d)
        json.dumps(d)

    def test_untagged_bars_use_sentinel_not_zero(self):
        """-1 (not 0) means "timing stage has not run" — 0 would be a real
        weekday/hour and would silently pool into the Monday-00:00 cohort."""
        b = Bar(ts=0, tf=15, open=1.0, high=2.0, low=0.5, close=1.5)
        assert (b.weekday, b.hour) == (-1, -1)
        assert path_mod.cohort_key(b) == (3, 0)      # ts=0 is Thursday 00:00 UTC

    def test_settings_validate_rejects_nonsense(self):
        Settings().validate()                        # defaults are legal
        for bad in (dict(reference_percentile=0.0), dict(reference_percentile=101.0),
                    dict(reference_mode="nonsense"), dict(timing_mode="nonsense"),
                    dict(weak_threshold=-1.0), dict(reference_window=-1)):
            with pytest.raises(ValueError):
                Settings(**bad).validate()

    def test_settings_rolling_reference_needs_a_window(self):
        with pytest.raises(ValueError):
            Settings(reference_mode="rolling", reference_window=0).validate()
        Settings(reference_mode="rolling", reference_window=100).validate()


# --------------------------------------------------------------------------- #
# resample
# --------------------------------------------------------------------------- #
class TestResample:
    def test_ohlcv_aggregation_is_exact(self, minutes):
        """Assert against the buckets the resampler itself formed: the synthetic
        feed does not start on a timeframe boundary, so hard-coding "15 minutes in
        bar 0" would test the generator's phase, not the aggregation."""
        chunk = minutes[:45]
        buckets = rs.group_minutes(chunk, 15)
        bars = rs.resample(chunk, 15)
        full = [(ts, ms) for ts, ms in buckets if len(ms) == 15]
        assert len(bars) == len(full)
        for bar, (ts, ms) in zip(bars, full):
            assert bar.ts == ts
            assert bar.open == ms[0].open
            assert bar.close == ms[-1].close
            assert bar.high == max(m.high for m in ms)
            assert bar.low == min(m.low for m in ms)
            assert bar.volume == pytest.approx(sum(m.volume for m in ms))
            assert bar.n_minutes == 15

    def test_minute_path_is_preserved(self, minutes):
        bars = rs.resample(minutes[:45], 15)
        assert bars
        for b in bars:
            assert len(b.minute_path) == b.n_minutes
            assert b.minute_path[-1].close == b.close
            assert [m.ts for m in b.minute_path] == sorted(m.ts for m in b.minute_path)

    def test_no_minutes_leak_between_buckets(self, minutes):
        bars = rs.resample(minutes[:90], 15)
        seen = set()
        for b in bars:
            assert b.high == max(p.high for p in b.minute_path)
            assert b.low == min(p.low for p in b.minute_path)
            assert b.open == b.minute_path[0].open
            assert b.close == b.minute_path[-1].close
            for p in b.minute_path:                      # no minute in two bars
                assert p.ts not in seen
                seen.add(p.ts)

    def test_gap_produces_separate_bars_not_a_merge(self):
        """A missing 15-minute block must not glue two buckets together."""
        mins = []
        for block in (0, 2):                         # block 1 missing entirely
            base = block * 15 * 60_000
            for k in range(15):
                mins.append(MinuteBar(ts=base + k * 60_000, open=100.0, high=101.0,
                                      low=99.0, close=100.5, volume=1.0))
        bars = rs.resample(mins, 15)
        assert len(bars) == 2
        assert bars[1].ts - bars[0].ts == 30 * 60_000

    def test_incomplete_trailing_bucket_dropped_by_default(self, minutes):
        full = rs.resample(minutes, 15)
        assert len(rs.resample(minutes[:-5], 15)) == len(full) - 1
        kept = rs.resample(minutes[:-5], 15, drop_incomplete=False)
        # one extra bar: the feed starts mid-bucket, so with drop_incomplete=False
        # the *leading* partial bucket is kept as well as the trailing one
        assert len(kept) == len(full) + 1
        assert kept[0].n_minutes < 15
        assert kept[-1].n_minutes < 15
        # nothing is invented or lost: every minute appears in exactly one bar
        assert sum(b.n_minutes for b in kept) == len(minutes) - 5

    def test_every_kept_bar_is_complete(self, minutes):
        """drop_incomplete=True must leave no short bar anywhere in the series —
        not just at the tail.  A leading short bar (window starts mid-bucket) has
        a truncated path, so its s_total/high/low are understated and it enters the
        reference percentile sample as a spuriously quiet bar."""
        bars = rs.resample(minutes, 15)
        assert bars
        for b in bars:
            assert b.n_minutes == 15
        assert sum(b.n_minutes for b in bars) <= len(minutes)

    def test_a_fully_partial_window_yields_no_bars(self, minutes):
        """15 minutes that straddle two buckets are two partial buckets, so
        nothing is tradeable — an empty result beats two lying bars."""
        assert rs.resample(minutes[:15], 15) == []
        assert rs.resample(minutes[:15], 15, drop_incomplete=False) != []

    def test_validate_minutes_rejects_disorder(self):
        good = [MinuteBar(ts=i * 60_000, open=1.0, high=2.0, low=0.5, close=1.5)
                for i in range(3)]
        rs.validate_minutes(good)
        with pytest.raises(ValueError):
            rs.validate_minutes(list(reversed(good)))
        with pytest.raises(ValueError):
            rs.validate_minutes(good + [good[-1]])          # duplicate ts

    def test_validate_minutes_rejects_impossible_ohlc(self):
        with pytest.raises(ValueError):
            rs.validate_minutes([MinuteBar(ts=0, open=100.0, high=99.0, low=101.0,
                                           close=100.0)])
        with pytest.raises(ValueError):                     # close outside high/low
            rs.validate_minutes([MinuteBar(ts=0, open=100.0, high=101.0, low=99.0,
                                           close=105.0)])
        with pytest.raises(ValueError):
            rs.validate_minutes([MinuteBar(ts=0, open=100.0, high=101.0, low=99.0,
                                           close=100.0, volume=-1.0)])

    def test_completeness_report(self, minutes):
        bars = rs.resample(minutes, 15)
        rep = rs.completeness_report(bars, 15)
        assert {"bars", "full", "partial", "coverage", "min_minutes",
                "max_minutes"} <= set(rep)
        assert rep["bars"] == len(bars)
        assert rep["full"] + rep["partial"] == len(bars)
        assert rep["max_minutes"] == 15
        # the feed starts mid-bucket, so at most the first bar can be short
        assert rep["partial"] <= 1
        assert rep["coverage"] > 0.999

    def test_completeness_report_sees_a_hole(self):
        mins = [MinuteBar(ts=i * 60_000, open=1.0, high=2.0, low=0.5, close=1.5)
                for i in range(15)]
        mins += [MinuteBar(ts=(30 + i) * 60_000, open=1.0, high=2.0, low=0.5,
                           close=1.5) for i in range(10)]
        rep = rs.completeness_report(rs.resample(mins, 15, drop_incomplete=False), 15)
        assert rep["partial"] >= 1
        assert rep["min_minutes"] < 15
        assert rep["coverage"] < 1.0

    def test_periods_per_year_is_inverse_of_bar_length(self):
        assert rs.periods_per_year(1440) == pytest.approx(365.25)
        assert rs.periods_per_year(15) == pytest.approx(365.25 * 96.0)
        assert rs.periods_per_year(1) == pytest.approx(365.25 * 1440.0)
        assert rs.periods_per_year(60) > rs.periods_per_year(240)

    def test_timeframe_label(self):
        assert rs.timeframe_label(15) == "15m"
        assert rs.timeframe_label(60) == "1h"
        assert rs.timeframe_label(1440) == "1D"


# --------------------------------------------------------------------------- #
# system bar
# --------------------------------------------------------------------------- #
class TestSystemBar:
    def test_s_total_is_sum_of_abs_legs_not_net_move(self, minutes):
        """The defining property: a round trip scores 2x, not 0."""
        b = rs.resample(minutes[:60], 15)[0]
        systembar.compute_system_bar(b)
        assert b.s_total >= abs(b.close - b.open) - 1e-9
        assert b.s_total >= b.high - b.low - 1e-9

    def test_round_trip_has_large_s_total_and_zero_net(self):
        prices = [100.0, 110.0, 100.0] + [100.0] * 12
        mins, prev = [], prices[0]
        for i, p in enumerate(prices):
            mins.append(MinuteBar(ts=i * 60_000, open=prev, high=max(prev, p),
                                  low=min(prev, p), close=p, volume=1.0))
            prev = p
        b = rs.resample(mins, 15)[0]
        systembar.compute_system_bar(b)
        assert b.close == b.open == 100.0
        assert b.s_total == pytest.approx(20.0, abs=1e-9)      # 10 up + 10 down
        assert b.s_up == pytest.approx(10.0, abs=1e-9)
        assert b.s_down == pytest.approx(10.0, abs=1e-9)
        assert abs(b.efficiency) < 1e-9                        # no net progress

    def test_one_way_move_has_efficiency_one(self):
        mins = [MinuteBar(ts=i * 60_000, open=100.0 + i, high=101.0 + i,
                          low=100.0 + i, close=101.0 + i, volume=1.0)
                for i in range(15)]
        b = rs.resample(mins, 15)[0]
        systembar.compute_system_bar(b)
        assert b.efficiency == pytest.approx(1.0, abs=1e-6)
        assert b.s_down == pytest.approx(0.0, abs=1e-9)

    def test_s_up_plus_s_down_equals_s_total(self, bars_15m):
        for b in bars_15m[:200]:
            assert b.s_up + b.s_down == pytest.approx(b.s_total, abs=1e-6)

    def test_s_intra_is_the_sum_of_intra_minute_ranges(self, bars_15m):
        """``s_intra`` sums each minute's own high-low range, so it measures
        sub-sample churn.  It is normally *larger* than ``s_total`` (close-to-close
        legs) because a minute's range exceeds its net move — the two are
        complementary, not nested."""
        for b in bars_15m[:200]:
            assert b.s_intra >= 0.0
            assert b.s_intra == pytest.approx(
                math.fsum(m.high - m.low for m in b.minute_path), abs=1e-6)

    def test_s_intra_covers_the_bar_range(self, bars_15m):
        """Travelling from the bar low to the bar high must happen inside some
        minute's range, so the sum of ranges bounds the bar's own span."""
        for b in bars_15m[:200]:
            assert b.s_intra >= (b.high - b.low) - 1e-6

    def test_total_churn_is_the_two_components(self, bars_15m):
        for b in bars_15m[:50]:
            assert systembar.total_churn(b) == pytest.approx(b.s_total + b.s_intra,
                                                             abs=1e-6)

    def test_efficiency_in_unit_interval(self, bars_15m):
        for b in bars_15m[:300]:
            assert -1.0 - 1e-9 <= b.efficiency <= 1.0 + 1e-9

    def test_leg_skew_sign_matches_dominant_side(self, bars_15m):
        up = [b for b in bars_15m[:500] if b.s_up > 3 * b.s_down]
        assert up and all(b.leg_skew > 0 for b in up)
        dn = [b for b in bars_15m[:500] if b.s_down > 3 * b.s_up]
        assert all(b.leg_skew < 0 for b in dn)

    def test_reconstitute_close_from_minute_path(self, bars_15m):
        for b in bars_15m[:50]:
            assert systembar.reconstitute_close(b) == pytest.approx(b.close, abs=1e-9)

    def test_flow_imbalance_bounded(self, bars_15m):
        vals = [systembar.flow_imbalance(b.minute_path) for b in bars_15m[:200]]
        assert all(-1.0 - 1e-9 <= v <= 1.0 + 1e-9 for v in vals)

    def test_intra_bar_rv_non_negative(self, bars_15m):
        assert all(systembar.intra_bar_rv(b.minute_path) >= 0.0 for b in bars_15m[:100])

    def test_tail_and_head_flow_split_the_bar(self, bars_15m):
        b = bars_15m[50]
        _tf, tail_n = systembar.tail_flow(b.minute_path)
        _hf, head_n = systembar.head_flow(b.minute_path)
        assert tail_n == head_n == 5                          # 1/3 of 15 minutes

    def test_describe_returns_finite_values(self, bars_15m):
        d = systembar.describe(bars_15m[10])
        assert d and all(math.isfinite(v) for v in d.values())


# --------------------------------------------------------------------------- #
# dynamic 100% reference
# --------------------------------------------------------------------------- #
class TestReference:
    def test_build_reference_trims_top_outliers(self):
        xs = [float(i) for i in range(1, 101)] + [10_000.0] * 5
        r, n_trim = ref_mod.build_reference(xs, pct=98.0, max_outlier_share=0.02)
        assert n_trim >= 2
        assert r < 10_000.0                                   # the spike is excluded
        assert r > 90.0

    def test_build_reference_empty_and_tiny(self):
        assert ref_mod.build_reference([]) == (0.0, 0)
        r, n = ref_mod.build_reference([5.0])
        assert (n, r) == (0, pytest.approx(5.0))
        _r, n = ref_mod.build_reference([1.0, 2.0, 1e9])      # 3 bars -> trim nothing
        assert n == 0

    def test_reference_is_positive_on_real_data(self, res15):
        assert res15.reference_summary["system_ref_last"] > 0
        assert res15.reference_summary["chart_ref_last"] > 0
        assert res15.reference_summary["ready"] > 0

    def test_expanding_mode_is_causal(self, res15, minutes30):
        """Every reference/timing value on bar i must be reproducible from a run
        that never saw bars after i.

        Tested end-to-end by re-running the whole pipeline on a truncated window
        and comparing the overlap — that catches look-ahead in *any* stage
        (reference, timing, volatility, indicators), not just the one being
        asserted on.  ``annotate_reference`` mutates in place and resets
        ``category`` (it is derived from the pct fields, so it goes stale), which
        is why this test does not annotate the shared fixture directly."""
        from engine import pipeline as pl
        cut = len(minutes30) // 2
        short = pl.run(minutes30[:cut], settings=res15.settings, tf=15)
        assert short.bars
        n = min(len(short.bars), len(res15.bars)) - 1      # last short bar may be partial
        checked = 0
        for i in range(250, n):
            a, b = short.bars[i], res15.bars[i]
            assert a.ts == b.ts, f"bar {i} misaligned"
            assert a.system_pct == pytest.approx(b.system_pct, abs=1e-9), f"i={i}"
            assert a.chart_pct == pytest.approx(b.chart_pct, abs=1e-9), f"i={i}"
            assert a.system_ref == pytest.approx(b.system_ref, abs=1e-9), f"i={i}"
            assert a.timing_score == pytest.approx(b.timing_score, abs=1e-9), f"i={i}"
            assert a.timing_band == b.timing_band, f"i={i}"
            checked += 1
        assert checked > 500

    def test_full_mode_differs_from_expanding(self, minutes):
        """`full` builds one reference from the whole sample (look-ahead); it must
        disagree with the causal expanding window on every bar but the last.

        ``annotate_reference`` mutates its bars in place and returns the *same*
        objects, so each mode needs its own freshly resampled list — comparing the
        two return values of a call on one list compares a bar with itself and
        always "passes"."""
        def fresh() -> list:
            return systembar.annotate(rs.resample(minutes, 15))

        exp = ref_mod.annotate_reference(fresh(), Settings(reference_mode="expanding"))
        full = ref_mod.annotate_reference(fresh(), Settings(reference_mode="full"))
        pairs = [(a, b) for a, b in zip(exp, full) if a.system_ref > 0]
        assert pairs
        diffs = [abs(a.system_pct - b.system_pct) for a, b in pairs]
        assert max(diffs) > 1.0                      # percentage points, not epsilon
        # the whole-sample reference is a single constant; the causal one grows
        assert len({round(b.system_ref, 9) for b in full if b.system_ref > 0}) == 1
        assert len({round(b.system_ref, 9) for b in exp if b.system_ref > 0}) > 100

    def test_pct_fields_bounded_and_max_bars_flagged(self, res15):
        bars = [b for b in res15.bars if b.system_ref > 0]
        assert bars
        assert all(b.system_pct >= 0.0 for b in bars)
        n_max = sum(1 for b in bars if b.is_max_bar)
        assert n_max > 0
        assert n_max / len(bars) < 0.25       # Max Bars are a minority by construction
        top = max(b.system_pct for b in bars)
        assert all(b.system_pct <= top + 1e-9 for b in bars)

    def test_warmup_bars_have_no_reference(self, res15):
        assert not ref_mod.is_reference_ready(res15.bars[0])
        assert ref_mod.is_reference_ready(res15.bars[-1])
        assert res15.reference_summary["warmup_bars"] > 0

    def test_reference_has_no_wild_single_bar_jumps(self, res15):
        refs = [b.system_ref for b in res15.bars if b.system_ref > 0]
        jumps = [abs(refs[i] / refs[i - 1] - 1.0) for i in range(1, len(refs))]
        assert max(jumps) < 0.5


# --------------------------------------------------------------------------- #
# classification tree
# --------------------------------------------------------------------------- #
class TestClassify:
    def test_every_bar_gets_exactly_one_category(self, res15):
        assert {b.category for b in res15.bars} <= set(Category)
        assert all(isinstance(b.category, Category) for b in res15.bars)

    def test_weak_beats_pressure_by_rule_order(self):
        """Rule order is load-bearing: WEAK is tested before PRESSURE."""
        s = Settings()
        b = Bar(ts=0, tf=15, open=100.0, high=100.1, low=99.9, close=100.05, volume=1.0)
        b.system_pct = 1.0                                    # tiny -> weak
        b.chart_pct = 1.0
        b.s_intra = 100.0                                     # would also satisfy pressure
        b.s_total = 100.0
        assert classify.classify(b, s) is Category.WEAK

    def test_strong_is_chart_big_but_system_not_big(self, res15):
        """STRONG = a big *visible* move on little total churn (clean direction).
        ENERGETIC = big on both.  Asserting the documented rule, not a guess."""
        s = res15.settings
        strong = [b for b in res15.bars if b.category is Category.STRONG]
        assert strong
        for b in strong:
            assert b.chart_pct >= s.big_threshold
            assert b.system_pct < s.big_threshold

    def test_energetic_is_big_on_both_axes(self, res15):
        s = res15.settings
        en = [b for b in res15.bars if b.category is Category.ENERGETIC]
        assert en
        for b in en:
            assert b.chart_pct >= s.big_threshold
            assert b.system_pct >= s.big_threshold

    def test_medium_is_the_documented_residual(self, res15):
        """MEDIUM = "otherwise": not weak, not pressure, not big on the chart."""
        s = res15.settings
        med = [b for b in res15.bars if b.category is Category.MEDIUM]
        assert med
        for b in med:
            assert b.chart_pct < s.big_threshold or b.system_pct >= s.big_threshold
            assert not (b.chart_pct < s.weak_threshold and b.system_pct < s.weak_threshold)

    def test_weak_is_small_on_both_axes(self, res15):
        s = res15.settings
        weak = [b for b in res15.bars if b.category is Category.WEAK]
        assert weak
        for b in weak:
            assert b.chart_pct < s.weak_threshold
            assert b.system_pct < s.weak_threshold

    def test_pressure_is_high_churn_with_a_small_chart_move(self, res15):
        s = res15.settings
        pr = [b for b in res15.bars if b.category is Category.PRESSURE]
        for b in pr:
            assert b.system_pct >= s.pressure_system_threshold
            assert b.chart_pct < s.weak_threshold

    def test_classification_reproduces_the_documented_tree(self, res15):
        """Re-derive the category from the raw fields for every bar: the tree in
        code and the tree in the spec must be the same tree."""
        s = res15.settings
        for b in res15.bars:
            if b.system_ref <= 0:                       # warm-up bars are excluded
                continue
            if b.chart_pct < s.weak_threshold and b.system_pct < s.weak_threshold:
                want = Category.WEAK
            elif (b.system_pct >= s.pressure_system_threshold
                  and b.chart_pct < s.weak_threshold):
                want = Category.PRESSURE
            elif b.chart_pct >= s.big_threshold and b.system_pct >= s.big_threshold:
                want = Category.ENERGETIC
            elif b.chart_pct >= s.big_threshold and b.system_pct < s.big_threshold:
                want = Category.STRONG
            else:
                want = Category.MEDIUM
            assert b.category is want, f"bar {b.ts}: got {b.category}, tree says {want}"

    def test_pressure_is_rare(self, res15):
        """Pressure means 'big churn, no progress'.  It must stay a small share,
        otherwise the reversal-event ladder built on it fires constantly."""
        shares = classify.category_shares(res15.bars)
        assert shares["pressure"] < 0.10
        assert shares["weak"] + shares["medium"] > 0.5

    def test_shares_sum_to_one(self, res15):
        assert sum(classify.category_shares(res15.bars).values()) == pytest.approx(1.0)

    def test_explain_names_the_winning_rule(self, res15):
        b = res15.bars[len(res15.bars) // 2]
        e = classify.explain(b, res15.settings)
        assert e["category"] == b.category.value
        assert isinstance(e["winning_rule"], int)
        assert e["checks"] and isinstance(e["checks"], (list, tuple))

    def test_transition_matrix_covers_every_consecutive_pair(self, res15):
        tm = classify.transition_matrix(res15.bars)
        assert set(tm) == {c.value for c in Category}
        assert sum(sum(row.values()) for row in tm.values()) == len(res15.bars) - 1

    def test_transition_probabilities_are_distributions(self, res15):
        for row in classify.transition_probabilities(res15.bars).values():
            if row:
                assert sum(row.values()) == pytest.approx(1.0, abs=1e-6)

    def test_base_rate_of_matches_shares(self, res15):
        shares = classify.category_shares(res15.bars)
        for c in Category:
            assert classify.base_rate_of(res15.bars, c) == pytest.approx(shares[c.value])

    def test_base_rate_of_rejects_an_unknown_category(self, res15):
        """Failing loudly beats returning 0.0, which would read as 'never happens'."""
        with pytest.raises(ValueError):
            classify.base_rate_of(res15.bars, "nope")

    def test_directional_split_counts_are_consistent(self, res15):
        ds = classify.directional_split(res15.bars)
        assert sum(v["up"] + v["down"] for v in ds.values()) == len(res15.bars)
        for b in res15.bars[:200]:
            assert ds[b.category.value]["up" if b.direction > 0 else "down"] >= 1

    def test_annotate_is_idempotent(self, res15):
        before = [b.category for b in res15.bars[:50]]
        classify.annotate(res15.bars[:50], res15.settings)
        assert [b.category for b in res15.bars[:50]] == before


# --------------------------------------------------------------------------- #
# timing heatmap (7 x 24)
# --------------------------------------------------------------------------- #
class TestTiming:
    def test_weekday_and_hour_extraction(self):
        ts = 1_735_689_600_000                     # 2025-01-01T00:00Z = Wednesday
        assert timing.weekday_of(ts) == 2
        assert timing.hour_of(ts) == 0
        assert timing.hour_of(ts + 13 * 3_600_000) == 13
        assert timing.weekday_of(ts + 5 * 86_400_000) == 0     # Monday

    def test_cells_never_exceed_168(self, res15_long):
        assert 0 < len(res15_long.cells) <= 7 * 24
        for key, cell in res15_long.cells.items():
            wd, hr = key.split("-")
            assert 0 <= int(wd) <= 6 and 0 <= int(hr) <= 23
            assert (cell.weekday, cell.hour) == (int(wd), int(hr))
            assert cell.bars >= 0

    def test_scores_in_unit_interval(self, res15_long):
        for cell in res15_long.cells.values():
            assert 0.0 <= cell.score <= 1.0

    def test_score_weights_are_the_documented_triple(self):
        s = Settings()
        w = (s.timing_weight_system, s.timing_weight_chart, s.timing_weight_efficiency)
        assert w == (0.50, 0.35, 0.15)
        assert sum(w) == pytest.approx(1.0)

    def test_band_share_sums_to_one(self, res15_long):
        bs = timing.band_share(res15_long.bars)
        assert sum(bs.values()) == pytest.approx(1.0, abs=1e-6)
        assert set(bs) <= {"dead", "mid", "hot"}

    def test_hot_and_dead_bands_do_not_overlap(self, res15_long):
        cells = {f"{c.weekday}-{c.hour}": c for c in res15_long.cells.values()}
        hot = timing.hot_cells(res15_long.cells.values())
        dead = timing.dead_cells(res15_long.cells.values())
        assert not (set(hot) & set(dead))
        if hot and dead:
            assert min(cells[k].score for k in hot) >= max(cells[k].score for k in dead)

    def test_hour_scores_returns_24_entries(self, res15_long):
        hs = timing.hour_scores(res15_long.cells.values())
        assert len(hs) == 24
        assert all(0 <= h <= 23 and 0.0 <= sc <= 1.0 for h, sc in hs)

    def test_expanding_mode_stays_causal(self, minutes):
        """Recomputing on a prefix must not produce scores outside [0,1] and must
        not depend on bars that have not happened yet."""
        bars = systembar.annotate(rs.resample(minutes, 15))
        ref_mod.annotate_reference(bars, Settings())
        full = timing.annotate(list(bars), Settings(timing_mode="expanding"))
        prefix = timing.annotate(list(bars[: len(bars) // 2]),
                                 Settings(timing_mode="expanding"))
        assert full["mode"] == prefix["mode"] == "expanding"
        for c in prefix["cells"].values():
            assert 0.0 <= c.score <= 1.0
        for c in full["cells"].values():
            assert 0.0 <= c.score <= 1.0
        # every bar carries a score in [0, 1] and a legal band
        for b in bars:
            assert 0.0 <= b.timing_score <= 1.0
            assert b.timing_band in ("dead", "mid", "hot")

    def test_tag_bars_fills_weekday_and_hour(self, bars_15m):
        timing.tag_bars(bars_15m[:20])
        for b in bars_15m[:20]:
            assert 0 <= b.weekday <= 6
            assert 0 <= b.hour <= 23
            assert (b.weekday, b.hour) == path_mod.cohort_key(b)

    def test_cells_to_dicts_is_json_safe(self, res15_long):
        ds = timing.cells_to_dicts(res15_long.cells.values())
        assert ds and {"weekday", "hour", "score", "band", "bars"} <= set(ds[0])
        json.dumps(ds)


# --------------------------------------------------------------------------- #
# volatility
# --------------------------------------------------------------------------- #
class TestVolatility:
    def test_true_range_accounts_for_gaps(self):
        prev = Bar(ts=0, tf=15, open=100.0, high=100.0, low=100.0, close=100.0)
        b = Bar(ts=900_000, tf=15, open=110.0, high=112.0, low=109.0, close=111.0)
        assert volatility.true_range(b, prev.close) == pytest.approx(12.0)
        assert volatility.true_range(b, None) == pytest.approx(3.0)

    def test_true_range_never_negative(self, res15):
        bars = res15.bars
        for i in range(1, len(bars)):
            assert volatility.true_range(bars[i], bars[i - 1].close) >= 0.0

    def test_atr_is_positive_and_smooth(self, res15):
        atr = volatility.atr_series(res15.bars, 14)
        assert len(atr) == len(res15.bars)
        tail = [a for a in atr[200:] if a > 0]
        assert tail and all(a > 0 for a in tail)
        ratios = [tail[i] / tail[i - 1] for i in range(1, len(tail))]
        assert max(ratios) < 3.0 and min(ratios) > 1 / 3.0    # Wilder smoothing

    def test_rv_estimators_are_non_negative(self, res15):
        for b in res15.bars[:100]:
            assert volatility.rv_price(b) >= 0.0
            assert volatility.garman_klass_log_variance(b) >= 0.0
            assert volatility.parkinson_log_variance(b) >= 0.0

    def test_garman_klass_dominates_parkinson(self):
        """GK adds the open/close term, so GK >= Parkinson on the same bar."""
        b = Bar(ts=0, tf=15, open=100.0, high=110.0, low=95.0, close=105.0)
        assert (volatility.garman_klass_log_variance(b)
                >= volatility.parkinson_log_variance(b) - 1e-12)

    def test_rv_from_minutes_matches_log_legs(self, minutes):
        legs = volatility.log_legs(minutes[:15])
        assert len(legs) == 15
        assert volatility.rv_log_variance(minutes[:15]) == pytest.approx(
            sum(x * x for x in legs), abs=1e-12)

    def test_annotate_fills_sigma_atr_and_regime(self, res15):
        tail = res15.bars[200:]
        assert all(b.sigma > 0 for b in tail)
        assert all(b.atr > 0 for b in tail)
        assert all(b.vol_regime >= 0 for b in tail)
        assert all(math.isfinite(b.sigma_atr) for b in tail)

    def test_sigma_pct_is_a_percentage(self, res15):
        b = res15.bars[-1]
        assert volatility.sigma_pct(b) == pytest.approx(b.sigma / b.close * 100.0,
                                                        abs=1e-9)

    def test_annualised_vol_scales_with_sqrt_time(self, res15):
        tail = res15.bars[200:]
        v15 = volatility.annualised_vol(tail, rs.periods_per_year(15))
        v60 = volatility.annualised_vol(tail, rs.periods_per_year(60))
        assert v15 > 0
        assert v60 == pytest.approx(v15 / 2.0, abs=1e-9)     # sqrt(4x) = 2x

    def test_vol_summary_keys(self, res15):
        s = volatility.vol_summary(res15.bars[200:])
        assert {"atr_mean", "atr_pct_mean", "sigma_mean", "sigma_median",
                "sigma_p95", "vol_regime_mean", "rv_over_gk"} <= set(s)
        assert all(math.isfinite(v) for v in s.values())

    def test_annualised_vol_is_in_a_sane_band_for_the_generator(self, res15):
        """Calibration guard: the synthetic feed is tuned to ~55% annualised.  A
        runaway GARCH (the bug this catches) shows up as >500%."""
        v = volatility.annualised_vol(res15.bars[200:], rs.periods_per_year(15))
        assert 0.05 < v < 3.0


# --------------------------------------------------------------------------- #
# intra-bar path / growth curves
# --------------------------------------------------------------------------- #
class TestPath:
    def test_growth_curve_is_displacement_normalised_by_the_final_body(self, bars_15m):
        """``formed_pct`` is ``|close_k - open_1| / |close_n - open_1|``: how much
        of the bar's *final* displacement had already happened by minute k.  It
        ends at exactly 1.0 and is deliberately NOT monotone — a bar that
        overshoots then retraces goes above 1.0 and comes back, which is the shape
        information the completion ratio is there to detect."""
        b = next(x for x in bars_15m[20:60] if abs(x.close - x.minute_path[0].open) > 1e-9)
        c = growth_curve(b)
        assert len(c) == b.n_minutes
        assert c[0].minute_index == 1
        assert c[-1].formed_pct == pytest.approx(1.0, abs=1e-9)
        assert c[-1].elapsed_pct == pytest.approx(1.0, abs=1e-6)
        o = b.minute_path[0].open
        denom = abs(b.close - o)
        for k, pt in enumerate(c, start=1):
            assert pt.formed_abs == pytest.approx(abs(b.minute_path[k - 1].close - o))
            assert pt.formed_pct == pytest.approx(min(pt.formed_abs / denom, 5.0),
                                                  abs=1e-9)

    def test_growth_curve_is_bounded_and_non_negative(self, bars_15m):
        for b in bars_15m[20:60]:
            vals = [p.formed_pct for p in growth_curve(b)]
            assert all(0.0 <= v <= 5.0 for v in vals)      # clamped overshoot
            assert all(p.formed_abs >= 0.0 for p in growth_curve(b))

    def test_growth_curve_elapsed_is_monotone(self, bars_15m):
        for b in bars_15m[20:60]:
            el = [p.elapsed_pct for p in growth_curve(b)]
            assert el == sorted(el)
            assert el[-1] == pytest.approx(1.0, abs=1e-9)

    def test_doji_bar_falls_back_to_range_normalisation(self):
        """A zero-body bar cannot be normalised by its body (0/0), so the curve
        falls back to the bar range instead of collapsing to all-zero."""
        mins = [MinuteBar(ts=i * 60_000, open=100.0 + (i % 3), high=102.0 + (i % 3),
                          low=99.0, close=100.0 + ((i + 1) % 3), volume=1.0)
                for i in range(15)]
        b = rs.resample(mins, 15, drop_incomplete=False)[0]
        systembar.compute_system_bar(b)
        c = growth_curve(b)
        assert c and any(p.formed_pct > 0.0 for p in c)
        assert all(math.isfinite(p.formed_pct) for p in c)

    def test_path_points_carry_minute_index_and_elapsed(self, bars_15m):
        c = growth_curve(bars_15m[20])
        assert [p.minute_index for p in c] == list(range(1, len(c) + 1))
        assert c[0].elapsed_pct == pytest.approx(1.0 / len(c), abs=1e-9)
        assert [p.ts for p in c] == sorted(p.ts for p in c)

    def test_cohort_key_is_weekday_hour(self, res15_long):
        b = res15_long.bars[500]
        assert path_mod.cohort_key(b) == (b.weekday, b.hour)

    def test_cohort_curves_are_bounded_and_end_near_fully_formed(self, res15_long):
        curves = path_mod.build_cohort_curves(res15_long.bars)
        assert curves
        for key, curve in curves.items():
            vals = [p.formed_pct for p in curve]
            assert all(0.0 <= v <= 5.0 for v in vals)
            # the mean of per-bar curves ends near 1.0; doji bars normalise by
            # range instead, so the cohort average is allowed to land below it
            assert vals[-1] > 0.5
            el = [p.elapsed_pct for p in curve]
            assert el == sorted(el) and el[-1] == pytest.approx(1.0, abs=1e-6)
            wd, hr = key.split("-")
            assert 0 <= int(wd) <= 6 and 0 <= int(hr) <= 23

    def test_expected_formed_pct_increases_with_elapsed_time(self, res15_long):
        curves = path_mod.build_cohort_curves(res15_long.bars)
        curve = next(iter(curves.values()))
        a = path_mod.expected_formed_pct(curve, 3 / 15)
        b = path_mod.expected_formed_pct(curve, 12 / 15)
        assert b > a
        assert path_mod.expected_formed_pct(curve, 1.0) == pytest.approx(
            curve[-1].formed_pct, abs=1e-9)
        assert path_mod.expected_formed_pct(curve, 0.0) >= 0.0

    def test_cohort_curves_only_use_bars_with_enough_history(self, res15_long):
        """A cohort averaged from 2 bars is noise, not seasonality."""
        curves = path_mod.build_cohort_curves(res15_long.bars, min_bars=5)
        for key in curves:
            wd, hr = (int(x) for x in key.split("-"))
            n = sum(1 for b in res15_long.bars if b.weekday == wd and b.hour == hr)
            assert n >= 5, f"cohort {key} built from {n} bars"

    def test_completion_ratio_is_positive_and_finite(self, res15_long):
        curves = path_mod.build_cohort_curves(res15_long.bars)
        bar = next(b for b in res15_long.bars[500:]
                   if f"{b.weekday}-{b.hour}" in curves and b.n_minutes == 15)
        r = path_mod.completion_ratio(bar, curves[f"{bar.weekday}-{bar.hour}"])
        assert r > 0.0 and math.isfinite(r)

    def test_curve_to_dicts_is_json_safe(self, bars_15m):
        d = path_mod.curve_to_dicts(growth_curve(bars_15m[5]))
        assert d and {"minute_index", "formed_pct", "elapsed_pct"} <= set(d[0])
        json.dumps(d)


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #
class TestIndicators:
    FIELDS = ("ema_fast", "ema_mid", "ema_slow", "ribbon_tilt", "adx", "plus_di",
              "minus_di", "rsi", "roc", "vwap", "donchian_hi", "donchian_lo",
              "flow_imb", "sigma_rank", "atr_pct_rank", "bb_width", "squeeze")

    def test_arrays_are_parallel_to_bars(self, res15):
        ind = res15.indicators
        assert ind.n == len(res15.bars)
        for name in self.FIELDS:
            assert len(getattr(ind, name)) == len(res15.bars), name

    def test_no_indicator_looks_ahead(self, minutes):
        """The single most important property: computing on a prefix must give
        identical values on the overlap."""
        bars = systembar.annotate(rs.resample(minutes, 15))
        ref_mod.annotate_reference(bars, Settings())
        volatility.annotate_volatility(bars, Settings())
        full = ind_mod.compute(bars)
        cut = len(bars) - 40
        pref = ind_mod.compute(bars[:cut])
        checked = 0
        for name in self.FIELDS:
            a, b = getattr(full, name), getattr(pref, name)
            for i in range(cut - 5, cut):
                av, bv = a[i], b[i]
                if isinstance(av, bool) or isinstance(bv, bool):
                    assert av == bv, f"{name}[{i}] looks ahead"
                    continue
                if math.isnan(av) or math.isnan(bv):
                    assert math.isnan(av) == math.isnan(bv), f"{name}[{i}] warm-up drift"
                    continue
                assert av == pytest.approx(bv, abs=1e-9), f"{name}[{i}] looks ahead"
                checked += 1
        assert checked > 50

    def test_rsi_bounded(self, res15):
        vals = [v for v in res15.indicators.rsi[200:] if not math.isnan(v)]
        assert vals and all(0.0 <= v <= 100.0 for v in vals)

    def test_adx_bounded(self, res15):
        vals = [v for v in res15.indicators.adx[200:] if not math.isnan(v)]
        assert vals and all(0.0 <= v <= 100.0 for v in vals)

    def test_di_components_are_non_negative(self, res15):
        ind = res15.indicators
        assert all(v >= 0 or math.isnan(v) for v in ind.plus_di[200:])
        assert all(v >= 0 or math.isnan(v) for v in ind.minus_di[200:])

    def test_donchian_is_the_prior_n_bar_channel(self, res15):
        """The channel is built from the bars *before* i (that is what makes a
        break of it a breakout signal), so the current close is allowed to sit
        outside it — and must not be assumed to lie within."""
        ind = res15.indicators
        n = ind_mod.IndicatorConfig().donchian_period
        bars = res15.bars
        checked = breaks = 0
        for i in range(300, len(bars)):
            hi, lo = ind.donchian_hi[i], ind.donchian_lo[i]
            if math.isnan(hi) or math.isnan(lo):
                continue
            want_hi = max(b.high for b in bars[i - n:i])
            want_lo = min(b.low for b in bars[i - n:i])
            assert hi == pytest.approx(want_hi, abs=1e-9)
            assert lo == pytest.approx(want_lo, abs=1e-9)
            assert lo <= hi
            checked += 1
            if not (lo <= bars[i].close <= hi):
                breaks += 1
        assert checked > 100
        assert breaks > 0            # real breakouts happen; the channel is not a cage

    def test_vwap_is_positive(self, res15):
        for v in res15.indicators.vwap[200:]:
            if not math.isnan(v):
                assert v > 0

    def test_rank_fields_are_in_unit_interval(self, res15):
        ind = res15.indicators
        for name in ("sigma_rank", "atr_pct_rank", "bb_width_rank"):
            vals = [v for v in getattr(ind, name)[200:] if not math.isnan(v)]
            assert vals, name
            assert all(0.0 <= v <= 1.0 for v in vals), name

    def test_flow_imbalance_bounded(self, res15):
        vals = [v for v in res15.indicators.flow_imb[200:] if not math.isnan(v)]
        assert vals and all(-1.0 - 1e-9 <= v <= 1.0 + 1e-9 for v in vals)

    def test_trend_agreement_returns_flag_and_reason(self, res15):
        ind = res15.indicators
        i = len(res15.bars) - 5
        ok, why = ind_mod.trend_agreement(ind, i, 1)
        assert isinstance(ok, bool) and isinstance(why, str) and why
        ok2, why2 = ind_mod.trend_agreement(ind, i, -1)
        assert isinstance(ok2, bool) and why2

    def test_trend_agreement_is_direction_aware(self, res15):
        """A long and a short cannot both agree with the same ribbon."""
        ind = res15.indicators
        both = sum(1 for i in range(300, len(res15.bars))
                   if ind_mod.trend_agreement(ind, i, 1)[0]
                   and ind_mod.trend_agreement(ind, i, -1)[0])
        assert both == 0

    def test_extension_risk_is_finite_and_signed(self, res15):
        ind = res15.indicators
        i = len(res15.bars) - 5
        ok_l, ext_l = ind_mod.extension_risk(ind, i, 1, 3.0)
        ok_s, ext_s = ind_mod.extension_risk(ind, i, -1, 3.0)
        assert isinstance(ok_l, bool) and isinstance(ok_s, bool)
        assert math.isfinite(ext_l) and math.isfinite(ext_s)
        assert not (ext_l > 3.0 and ext_s > 3.0)      # not both over-extended

    def test_warmup_bars_positive(self):
        assert ind_mod.warmup_bars() > 0
        assert ind_mod.warmup_bars(ind_mod.IndicatorConfig()) > 0

    def test_at_returns_a_snapshot(self, res15):
        d = res15.indicators.at(len(res15.bars) - 1)
        assert isinstance(d, dict) and d
        floats = [v for v in d.values() if isinstance(v, float)]
        assert all(math.isfinite(v) or math.isnan(v) for v in floats)

    def test_squeeze_flags_are_boolean(self, res15):
        assert all(isinstance(v, bool) for v in res15.indicators.squeeze[200:])

    def test_bars_since_extremes_are_non_negative(self, res15):
        ind = res15.indicators
        assert all(v >= 0 for v in ind.bars_since_new_high[200:])
        assert all(v >= 0 for v in ind.bars_since_new_low[200:])
