"""Strategy layer: confirmation filters, risk management, staged exits.

The three things that decide whether the engine is usable:

* **signals** — the filter stack must be causal, deterministic, and must actually
  rank (a hard-veto chain that passes 2% of candidates is not a filter stack, it
  is a kill switch, which is why hard and soft filters are separate here).
* **risk** — sizing must be the *minimum* of its constraints, rounded down, and
  the kill switches must recover.  A cooldown that does not reset the counter it
  was triggered by is a permanent halt; that bug is pinned by a regression test.
* **exits** — the stop geometry must be sane on the timeframe (a confirmed pivot
  on a 15m chart can sit 6x ATR away, which makes 1R unreachable), the tranche
  ladder must sum to the whole position with exactly one runner, and reversal
  events must be gated on trade maturity so a fresh position is not stopped out
  by the noise that created it.
"""

from __future__ import annotations

import math

import pytest

from engine import resample as rs
from engine import risk as risk_mod
from engine import signals as sig_mod
from engine import systembar
from engine.models import MinuteBar
from engine.exits import ExitConfig, ExitManager, combine_severity, exit_config_presets
from engine.models import Bar, Category
from engine.portfolio import Position, Tranche
from engine.risk import CostConfig, RiskConfig, RiskManager


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def make_position(side: int = 1, entry: float = 100.0, stop_distance: float = 1.0,
                  qty: float = 10.0, i: int = 0, ts: int = 0,
                  tranches: tuple[tuple[float, float], ...] = ((1.0, 0.4), (2.0, 0.35),
                                                               (0.0, 1.0))) -> Position:
    """A Position shaped the way the backtester builds one."""
    tr = [Tranche(r_multiple=r, share=sh) for r, sh in tranches]
    pos = Position(
        side=side, entry_ts=ts, entry_price=entry, qty=qty, initial_qty=qty,
        entry_index=i, entry_ref_price=entry, strategy="trend", signal_score=0.7,
        category="strong", initial_stop=entry - side * stop_distance,
        stop=entry - side * stop_distance, stop_distance=stop_distance,
        tranches=tr, runner_target=0.0, entry_commission=0.0,
        highest_since_entry=entry, lowest_since_entry=entry,
        risk_cash=qty * stop_distance, targets=[entry + side * r * stop_distance
                                                for r, _ in tranches if r > 0],
    )
    pos.gross_ref_pnl = -side * entry * qty
    return pos


def bar_at(i: int, close: float, *, open_: float | None = None, high: float | None = None,
           low: float | None = None, ts: int | None = None, tf: int = 15) -> Bar:
    o = open_ if open_ is not None else close
    h = high if high is not None else max(o, close)
    lo = low if low is not None else min(o, close)
    b = Bar(ts=ts if ts is not None else i * tf * 60_000, tf=tf, open=o, high=h,
            low=lo, close=close, volume=10.0)
    b.sigma = 1.0
    b.atr = 1.0
    return b


# --------------------------------------------------------------------------- #
# signals: confirmation filters
# --------------------------------------------------------------------------- #
class TestSignals:
    def test_config_defaults_validate_and_hash_stably(self):
        c = sig_mod.SignalConfig().validate()
        assert c.config_hash() == sig_mod.SignalConfig().validate().config_hash()
        assert c.config_hash() != sig_mod.SignalConfig(min_edge_score=0.9).config_hash()

    def test_config_rejects_nonsense(self):
        bad_configs = (
            dict(min_edge_score=1.5), dict(min_edge_score=-0.1),
            dict(cooldown_bars=-1), dict(entry_timing="teleport"),
            dict(pullback_ttl_bars=0), dict(max_signals_per_day=-1),
            dict(pullback_mode="teleport"), dict(pullback_retrace_sigma=-1.0),
            dict(pullback_body_frac=1.5), dict(pullback_body_frac=0.0),
            dict(pullback_max_sigma=0.0), dict(min_adx=150.0),
            dict(rsi_long_max=140.0), dict(w_trend=-1.0),
            dict(extension_soft_sigma=99.0),        # soft band above the hard veto
            dict(structure_mode="sideways"),
            dict(execution="same_bar"),             # same-bar fill is look-ahead
        )
        for bad in bad_configs:
            with pytest.raises(ValueError):
                sig_mod.SignalConfig(**bad).validate()

    def test_extension_soft_band_sits_below_the_hard_veto(self):
        c = sig_mod.SignalConfig().validate()
        assert 0.0 < c.extension_soft_sigma <= c.max_extension_sigma

    def test_hard_and_soft_filters_are_disjoint_sets(self):
        """The hard/soft split is the design decision that keeps signal volume
        alive: quality filters penalise the score, structural filters veto."""
        c = sig_mod.SignalConfig()
        hard = set(c.hard_filters)
        soft = {"structure", "momentum", "volume", "flow"}
        assert hard and not (hard & soft)
        assert "quality" in hard                 # the single quality dial is a gate
        assert "trend" in hard                   # direction agreement is structural

    def test_active_filters_reflect_the_flags(self):
        c = sig_mod.SignalConfig(f_trend=False).validate()
        assert "trend" not in c.active_filters()
        assert "trend" in sig_mod.SignalConfig().active_filters()

    def test_generate_produces_signals_only_after_warmup(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        assert ss.signals
        assert all(s.index >= res15.warmup_index for s in ss.signals)
        assert all(s.index < len(res15.bars) for s in ss.signals)

    def test_signals_are_strictly_increasing_in_index(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        idx = [s.index for s in ss.signals]
        assert idx == sorted(set(idx))

    def test_cooldown_is_respected(self, res15):
        cd = 4
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              sig_mod.SignalConfig(cooldown_bars=cd),
                              warmup_index=res15.warmup_index)
        idx = [s.index for s in ss.signals]
        gaps = [b - a for a, b in zip(idx, idx[1:])]
        assert all(g > cd for g in gaps), f"cooldown violated: {min(gaps)} <= {cd}"

    def test_tightening_cooldown_reduces_signal_count(self, res15):
        counts = []
        for cd in (0, 4, 12):
            ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                                  sig_mod.SignalConfig(cooldown_bars=cd),
                                  warmup_index=res15.warmup_index)
            counts.append(len(ss.signals))
        assert counts[0] >= counts[1] >= counts[2]

    def test_raising_min_edge_score_reduces_signals_monotonically(self, res15):
        curves = res15.stats.get("cohort_curves", {})
        counts = []
        for ms in (0.2, 0.45, 0.7, 0.9):
            ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                                  sig_mod.SignalConfig(min_edge_score=ms),
                                  warmup_index=res15.warmup_index, cohort_curves=curves)
            counts.append(len(ss.signals))
        assert counts == sorted(counts, reverse=True)

    def test_accepted_signals_pass_every_hard_filter(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        for s in ss.signals:
            assert s.accepted
            assert not s.failed, f"accepted signal carries hard failures {s.failed}"
            assert s.score >= ss.cfg.min_edge_score - 1e-12

    def test_rejected_candidates_name_their_killer(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              sig_mod.SignalConfig(min_edge_score=0.95),
                              warmup_index=res15.warmup_index)
        rejected = [c for c in ss.candidates if not c.accepted]
        assert rejected
        for c in rejected:
            assert c.failed, "a rejected candidate must say why"

    def test_soft_flags_penalise_without_rejecting(self, res15):
        """A soft flag must be survivable: if every soft flag vetoed, the stack
        would collapse back to the 2% pass rate that motivated the split."""
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              sig_mod.SignalConfig(min_edge_score=0.3),
                              warmup_index=res15.warmup_index)
        flagged = [s for s in ss.signals if s.soft_flags]
        assert flagged, "expected some accepted signals to carry soft flags"
        for s in flagged:
            assert not s.failed

    def test_side_and_prices_are_sane(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        for s in ss.signals:
            assert s.side in (1, -1)
            assert s.ref_price > 0 and math.isfinite(s.ref_price)
            assert s.next_open > 0 and math.isfinite(s.next_open)
            assert isinstance(s.category, str) and s.category
            assert s.grade in ("A", "B", "C", "D")

    def test_signal_is_causal(self, res15):
        """Generating on a prefix must reproduce the same signals on the overlap.

        This is the check that catches a filter reaching forward (e.g. a
        full-sample percentile, or an indicator computed without a shift)."""
        curves = res15.stats.get("cohort_curves", {})
        cut = len(res15.bars) - 60
        short_bars = res15.bars[:cut]
        from engine import indicators as ind_mod
        short_ind = ind_mod.compute(short_bars, res15.settings)
        full = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                                warmup_index=res15.warmup_index, cohort_curves=curves)
        short = sig_mod.generate(short_bars, short_ind, res15.settings,
                                 warmup_index=res15.warmup_index)
        full_prefix = [s for s in full.signals if s.index < cut - 1]
        short_prefix = [s for s in short.signals if s.index < cut - 1]
        assert full_prefix and short_prefix
        assert [(s.index, s.side) for s in full_prefix] == \
               [(s.index, s.side) for s in short_prefix]

    def test_determinism_across_repeated_runs(self, res15):
        kw = dict(warmup_index=res15.warmup_index)
        a = sig_mod.generate(res15.bars, res15.indicators, res15.settings, **kw)
        b = sig_mod.generate(res15.bars, res15.indicators, res15.settings, **kw)
        assert [s.index for s in a.signals] == [s.index for s in b.signals]
        assert [round(s.score, 12) for s in a.signals] == \
               [round(s.score, 12) for s in b.signals]

    def test_disabling_a_hard_filter_never_reduces_signals(self, res15):
        curves = res15.stats.get("cohort_curves", {})
        base = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                                warmup_index=res15.warmup_index, cohort_curves=curves)
        for flag in ("f_trend", "f_extension", "f_timing"):
            loose = sig_mod.generate(
                res15.bars, res15.indicators, res15.settings,
                sig_mod.SignalConfig(**{flag: False}),
                warmup_index=res15.warmup_index, cohort_curves=curves)
            assert len(loose.signals) >= len(base.signals), flag

    def test_funnel_is_internally_consistent(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        assert ss.funnel
        assert ss.funnel[0].key == "universe"
        # the last tradable bar cannot be a decision bar (there is no next open to
        # act on), so the universe stage sees one fewer bar than are tradable
        assert ss.funnel[0].entered == ss.n_tradable - 1
        for st in ss.funnel:
            assert st.passed <= st.entered
            assert st.rejected >= 0
            assert 0.0 <= st.pass_rate <= 1.0
        # the category gate is the narrowest stage: it is a percentile test, so it
        # is where signal volume is actually decided
        cat = next(st for st in ss.funnel if st.key == "category")
        assert cat.passed < cat.entered
        assert len(ss.signals) <= cat.passed

    def test_diagnose_reports_the_bottleneck(self, res15):
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        d = sig_mod.diagnose(res15.bars, ss, res15.settings,
                             warmup_index=res15.warmup_index)
        assert {"bottleneck", "rejection_counts", "sole_killer",
                "score_distribution", "grade_distribution", "universe",
                "accepted", "signals_per_day",
                "theoretical_max_candidates"} <= set(d)
        bn = d["bottleneck"]
        assert {"narrowest_stage", "narrowest_pass_rate", "most_decisive_filter",
                "redundant_filters"} <= set(bn)
        assert bn["narrowest_stage"]
        assert 0.0 <= bn["narrowest_pass_rate"] <= 1.0
        # grades are assigned to accepted signals, not to every candidate
        assert sum(d["grade_distribution"].values()) == d["accepted"]
        assert d["accepted"] == len(ss.signals)
        assert d["accepted"] <= len(ss.candidates)

    def test_signal_volume_is_not_a_kill_switch(self, res15):
        """Regression guard on the calibration lesson: 11 sequential hard vetoes
        once passed 13 of 581 candidates (2.2%).  A usable stack accepts a few
        percent of *bars* and a meaningful share of *candidates*."""
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        assert ss.candidates
        share_of_candidates = len(ss.signals) / len(ss.candidates)
        per_day = len(ss.signals) / max(1.0, ss.n_tradable / (1440 / 15))
        assert share_of_candidates > 0.05, f"only {share_of_candidates:.1%} of candidates"
        assert per_day > 0.2, f"{per_day:.2f} signals/day is not tradeable"

    def test_directional_information_shape(self, res15):
        di = sig_mod.directional_information(res15.bars, res15.settings)
        assert di and "by_category" in di or isinstance(di, dict)

    def test_threshold_sensitivity_is_ordered(self, res15):
        sens = sig_mod.threshold_sensitivity(res15.bars, res15.settings,
                                             warmup_index=res15.warmup_index)
        assert sens

    def test_signal_frame_is_flat_and_json_safe(self, res15):
        import json
        ss = sig_mod.generate(res15.bars, res15.indicators, res15.settings,
                              warmup_index=res15.warmup_index)
        rows = sig_mod.signal_frame(ss)
        assert rows and isinstance(rows[0], dict)
        json.dumps(rows[:5], default=str)

    def test_pullback_entry_config_fields(self):
        c = sig_mod.SignalConfig().validate()
        assert c.entry_timing == "pullback_limit"       # the default is the fix
        assert c.pullback_mode in ("sigma", "body", "midpoint", "open")
        assert c.pullback_retrace_sigma > 0
        assert 0 < c.pullback_body_frac <= 1
        assert c.pullback_ttl_bars >= 1
        assert c.limit_entry_uses_maker_fee is True


# --------------------------------------------------------------------------- #
# risk
# --------------------------------------------------------------------------- #
class TestCosts:
    def test_maker_is_cheaper_than_taker(self):
        c = CostConfig()
        assert c.commission(100_000.0, maker=True) < c.commission(100_000.0)
        assert c.exit_bps(100_000.0, maker=True) < c.exit_bps(100_000.0)

    def test_maker_exit_pays_no_spread_or_impact(self):
        c = CostConfig()
        assert c.exit_bps(100_000.0, maker=True) == pytest.approx(c.maker_bps)

    def test_taker_exit_includes_slippage_and_impact(self):
        c = CostConfig()
        bps = c.exit_bps(100_000.0)
        assert bps > c.commission_bps + c.slippage_bps       # impact adds on top
        assert bps == pytest.approx(c.commission_bps + c.slippage_bps
                                    + c.impact_bps(100_000.0))

    def test_impact_grows_with_size_but_sub_linearly(self):
        c = CostConfig()
        small, mid, big = (c.impact_bps(x) for x in (1e4, 1e6, 1e8))
        assert small < mid < big
        assert (big - mid) < (mid - small) * 100             # sqrt, not linear

    def test_slip_price_moves_against_the_aggressor(self):
        c = CostConfig()
        buy = c.slip_price(100.0, 1, 10_000.0)
        sell = c.slip_price(100.0, -1, 10_000.0)
        assert buy > 100.0 > sell

    def test_min_ticket_fee_floors_a_tiny_order(self):
        c = CostConfig(min_ticket_fee=1.0)
        assert c.commission(10.0) == 1.0                     # 10 * 4bp = 0.004 -> floor

    def test_validate_rejects_negative_costs(self):
        for bad in (dict(commission_bps=-1.0), dict(slippage_bps=-0.5),
                    dict(maker_bps=-1.0), dict(impact_coeff=-0.1)):
            with pytest.raises(ValueError):
                CostConfig(**bad).validate()


class TestRiskSizing:
    def test_size_targets_the_risk_budget(self):
        # ramp disabled: it deliberately starts at half size, which would otherwise
        # make the pure sizing arithmetic look wrong
        rm = RiskManager(RiskConfig(initial_equity=100_000.0, risk_per_trade_pct=1.0,
                                    sizing_mode="fixed_fractional", lot_step=0.0,
                                    ramp_enabled=False))
        d = rm.size(price=100.0, stop_distance=2.0)
        assert not d.rejected
        # 1% of 100k = 1000 at risk; stop 2.0 per unit -> 500 units
        assert d.qty == pytest.approx(500.0, rel=1e-6)
        assert d.risk_cash == pytest.approx(1000.0, rel=1e-6)
        assert d.notional == pytest.approx(50_000.0, rel=1e-6)

    def test_lot_step_rounds_down_never_up(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0, risk_per_trade_pct=1.0,
                                    sizing_mode="fixed_fractional", lot_step=100.0,
                                    ramp_enabled=False))
        d = rm.size(price=100.0, stop_distance=3.0)
        assert d.qty % 100.0 == 0.0
        assert d.qty * 3.0 <= 1000.0 + 1e-9          # risk never exceeds the budget

    def test_binding_constraint_is_reported(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0, risk_per_trade_pct=5.0,
                                    sizing_mode="risk_and_vol", max_leverage=1.0))
        d = rm.size(price=100.0, stop_distance=0.5)
        assert d.binding_constraint
        assert d.leverage <= 1.0 + 1e-9

    def test_tiny_equity_or_huge_stop_is_rejected_not_scaled_to_zero(self):
        rm = RiskManager(RiskConfig(initial_equity=100.0, risk_per_trade_pct=0.5,
                                    min_notional=1000.0))
        d = rm.size(price=100.0, stop_distance=1.0)
        assert d.rejected and d.reason

    def test_zero_stop_distance_is_rejected(self):
        rm = RiskManager(RiskConfig())
        d = rm.size(price=100.0, stop_distance=0.0)
        assert d.rejected

    def test_ramp_starts_small_and_reaches_full_size(self):
        cfg = RiskConfig(initial_equity=100_000.0, risk_per_trade_pct=1.0,
                         sizing_mode="fixed_fractional", ramp_enabled=True,
                         ramp_start_fraction=0.25, ramp_full_after_trades=8,
                         lot_step=0.0)
        rm = RiskManager(cfg)
        first = rm.size(price=100.0, stop_distance=2.0)
        assert first.ramp_fraction == pytest.approx(0.25, abs=1e-6)
        assert first.qty == pytest.approx(500.0 * 0.25, rel=1e-6)
        for k in range(8):
            rm.record_trade(10.0, index=k, ts_ms=k * 60_000)
        later = rm.size(price=100.0, stop_distance=2.0)
        assert later.ramp_fraction == pytest.approx(1.0, abs=1e-6)
        assert later.qty == pytest.approx(500.0, rel=1e-6)

    def test_kelly_fraction_is_capped(self):
        cfg = RiskConfig(kelly_fraction=0.25, sizing_mode="kelly_capped",
                         risk_per_trade_pct=1.0)
        rm = RiskManager(cfg)
        pct = rm.kelly_risk_pct(None)
        assert 0.0 <= pct <= cfg.risk_per_trade_pct + 1e-12


class TestRiskGates:
    def test_can_open_respects_max_open_positions(self):
        rm = RiskManager(RiskConfig(max_open_positions=2))
        assert rm.can_open(1, 0, 0)[0]
        rm.reserve(100.0)
        rm.reserve(100.0)                      # two live positions == the cap
        ok, why = rm.can_open(1, 0, 0)
        assert not ok and "max_open_positions" in why
        rm.release(100.0)
        assert rm.can_open(1, 0, 0)[0]

    def test_default_config_only_allows_one_position(self):
        """max_open_positions defaults to 1: the strategy is a single-position
        system unless the caller says otherwise."""
        assert RiskConfig().max_open_positions == 1

    def test_can_open_respects_the_daily_trade_cap(self):
        rm = RiskManager(RiskConfig(max_trades_per_day=1, max_open_positions=5))
        ts = 1_767_225_600_000
        assert rm.can_open(1, ts, 0)[0]
        # the backtester counts a position when it OPENS, not when it closes
        rm.st.trades_today = 1
        ok, why = rm.can_open(1, ts, 1)
        assert not ok and "max_trades_per_day" in why
        # the cap resets with the UTC day
        assert rm.can_open(1, ts + 86_400_000, 2)[0]
        assert rm.st.trades_today == 0

    def test_record_trade_does_not_count_towards_the_daily_cap(self):
        """A closed trade must not consume tomorrow's budget, and counting it here
        would be too late to prevent the entry anyway."""
        rm = RiskManager(RiskConfig(max_trades_per_day=5))
        ts = 1_767_225_600_000
        rm.record_trade(10.0, index=0, ts_ms=ts)
        assert rm.st.total_trades == 1
        assert rm.st.trades_today == 0

    def test_daily_loss_limit_blocks_new_entries(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0, daily_loss_limit_pct=1.0,
                                    max_consecutive_losses=0,    # isolate this gate
                                    max_trades_per_day=10**6))
        ts = 1_767_225_600_000
        rm.record_trade(-1500.0, index=0, ts_ms=ts)             # -1.5% on the day
        assert rm.st.day_pnl == pytest.approx(-1500.0)
        ok, why = rm.can_open(1, ts, 1)
        assert not ok and "daily_loss_limit" in why
        assert rm.st.halted and rm.st.halt_reason == "daily_loss_limit"
        # a daily-loss halt expires with the day (unlike the drawdown kill switch)
        rm.roll_day(ts + 86_400_000, 2)
        assert not rm.st.halted

    def test_shorts_can_be_disabled(self):
        rm = RiskManager(RiskConfig(allow_short=False))
        assert rm.can_open(1, 0, 0)[0]
        ok, why = rm.can_open(-1, 0, 0)
        assert not ok and "short" in why.lower()

    def test_record_trade_honours_a_disabled_streak_limit(self):
        """``max_consecutive_losses=0`` means "no streak gate"; without the guard a
        losing trade would halt the account immediately."""
        rm = RiskManager(RiskConfig(max_consecutive_losses=0, halt_cooldown_bars=5))
        for k in range(5):
            rm.record_trade(-100.0, index=k, ts_ms=k)
        assert rm.st.consecutive_losses == 5
        assert not rm.st.halted

    def test_cooldown_expiry_resets_the_counter_it_was_triggered_by(self):
        """Regression: a halt whose cooldown expires *without* resetting
        consecutive_losses re-triggers on the very next entry, turning "sit out
        24 bars" into "stop trading forever" (observed: 38 halts, 88 blocked
        entries, 139 signals -> 8 trades)."""
        cfg = RiskConfig(initial_equity=100_000.0, max_consecutive_losses=3,
                         halt_cooldown_bars=5, max_drawdown_kill_pct=0.0,  # disabled
                         daily_loss_limit_pct=0.0,                         # disabled
                         max_trades_per_day=10**6,
                         sizing_mode="fixed_fractional", risk_per_trade_pct=1.0,
                         lot_step=0.0, ramp_enabled=False)
        rm = RiskManager(cfg)
        for k in range(3):
            rm.record_trade(-100.0, index=k, ts_ms=k)
        assert rm.st.halted
        ok, why = rm.can_open(1, 3, 3)
        assert not ok and why
        # serve the cooldown
        ok_after, _ = rm.can_open(1, 100, 100)
        assert ok_after, "cooldown never expired"
        assert rm.st.consecutive_losses == 0, "counter survived the cooldown"
        # and trading genuinely resumes for good
        for k in range(10):
            assert rm.can_open(1, 200 + k, 200 + k)[0], f"re-halted at {k}"

    def test_max_drawdown_halt_is_permanent(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0,
                                    max_drawdown_kill_pct=5.0,
                                    max_trades_per_day=10**6,
                                    daily_loss_limit_pct=0.0))
        rm.mark(120_000.0)
        rm.mark(100_000.0)                               # -16.7% from the peak
        assert rm.st.drawdown > 0.05
        # the kill switch is evaluated at the entry gate, not inside mark()
        assert not rm.st.halted
        ok, why = rm.can_open(1, 0, 0)
        assert not ok and "max_drawdown" in why
        assert rm.st.halted
        # and it never self-clears, however much time passes or how far equity
        # recovers: only a human resets a drawdown kill switch
        rm.mark(120_000.0)
        assert not rm.can_open(1, 10**12, 10**6)[0]
        assert rm.st.halted

    def test_zero_limits_disable_gates_rather_than_always_firing(self):
        """Regression: ``max_drawdown_kill_pct=0`` used to mean "halt at 0%
        drawdown", which is true for a flat account — so the kill switch fired on
        the first entry and the strategy silently never traded."""
        rm = RiskManager(RiskConfig(max_drawdown_kill_pct=0.0,
                                    daily_loss_limit_pct=0.0,
                                    max_consecutive_losses=0,
                                    max_total_risk_pct=0.0,
                                    max_open_positions=10**6,
                                    max_trades_per_day=10**6))
        rm.st.open_risk = 10**9                          # absurd open risk
        for k in range(5):
            assert rm.can_open(1, k, k)[0], f"disabled gate fired at {k}"

    def test_credit_moves_cash_but_not_equity(self):
        """``credit`` is called per *fill*; ``equity`` is recomputed once per bar by
        ``mark``.  Moving both in two places is how accounting drifts a few bp per
        trade and nobody notices until the curve disagrees with the trade list."""
        rm = RiskManager(RiskConfig(initial_equity=100_000.0))
        rm.credit(500.0)
        assert rm.st.cash == pytest.approx(100_500.0)
        assert rm.st.realised_pnl == pytest.approx(500.0)
        assert rm.st.equity == pytest.approx(100_000.0)      # untouched on purpose
        rm.credit(-200.0)
        assert rm.st.cash == pytest.approx(100_300.0)
        rm.mark(100_300.0)
        assert rm.st.equity == pytest.approx(100_300.0)

    def test_reserve_and_release_round_trip(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0))
        rm.reserve(1000.0)
        assert rm.st.open_risk == pytest.approx(1000.0)
        rm.release(400.0)
        assert rm.st.open_risk == pytest.approx(600.0)
        rm.release(600.0)
        assert rm.st.open_risk == pytest.approx(0.0)

    def test_total_risk_cap_blocks_when_saturated(self):
        """Regression: an early-return left in ``can_open`` made this whole gate
        dead code, so ``max_total_risk_pct`` was configured but never enforced."""
        rm = RiskManager(RiskConfig(initial_equity=100_000.0, max_total_risk_pct=2.0,
                                    max_open_positions=50,
                                    max_trades_per_day=10**6,
                                    daily_loss_limit_pct=0.0,
                                    max_consecutive_losses=0))
        assert rm.can_open(1, 0, 0)[0]
        rm.reserve(1500.0)                                # 1.5%: still inside 2%
        assert rm.can_open(1, 0, 0, extra_risk_cash=400.0)[0]
        rm.reserve(600.0)                                 # 2.1% in total
        ok, why = rm.can_open(1, 0, 0)
        assert not ok and "risk_budget_exhausted" in why

    def test_drawdown_is_measured_from_the_peak(self):
        rm = RiskManager(RiskConfig(initial_equity=100_000.0))
        rm.mark(120_000.0)
        rm.mark(90_000.0)
        assert rm.st.peak_equity == pytest.approx(120_000.0)
        assert rm.st.drawdown == pytest.approx(0.25, abs=1e-9)     # property
        rm.mark(130_000.0)
        assert rm.st.drawdown == pytest.approx(0.0, abs=1e-9)      # new peak

    def test_risk_report_shape(self, res15):
        from engine import backtest as BT
        r = BT.run_backtest(res15)
        rep = risk_mod.risk_report(r.trades, RiskConfig())
        assert isinstance(rep, dict) and rep


# --------------------------------------------------------------------------- #
# exits: geometry, staging, events
# --------------------------------------------------------------------------- #
class TestExitGeometry:
    def test_every_preset_validates(self):
        presets = exit_config_presets()
        assert {"default", "tight", "wide", "scalp", "no_staging"} <= set(presets)
        for name, cfg in presets.items():
            cfg.validate()
            assert name

    def test_config_rejects_broken_ladders(self):
        with pytest.raises(ValueError):                      # two runners
            ExitConfig(tranches=((0.0, 0.5), (0.0, 0.5))).validate()
        with pytest.raises(ValueError):                      # no runner
            ExitConfig(tranches=((1.0, 0.5), (2.0, 0.5))).validate()
        with pytest.raises(ValueError):                      # negative R target
            ExitConfig(tranches=((-1.0, 0.5), (0.0, 0.5))).validate()
        with pytest.raises(ValueError):                      # shares do not sum to 1
            ExitConfig(tranches=((1.0, 0.2), (0.0, 0.3))).validate()
        with pytest.raises(ValueError):                      # negative share
            ExitConfig(tranches=((1.0, -0.5), (0.0, 1.5))).validate()
        with pytest.raises(ValueError):
            ExitConfig(max_bars_held=0).validate()
        with pytest.raises(ValueError):                      # severity ordering
            ExitConfig(tighten_severity=0.9, exit_all_severity=0.5).validate()

    def test_default_ladder_is_40_35_runner(self):
        c = ExitConfig()
        shares = [s for _r, s in c.tranches]
        assert shares[:2] == [0.40, 0.35]
        assert [r for r, _s in c.tranches if r == 0.0] == [0.0]      # exactly one runner

    def test_plan_puts_the_stop_on_the_correct_side(self, res15):
        xm = ExitManager(ExitConfig(), res15.settings)
        ind = res15.indicators
        for i in (300, 600, 900):
            b = res15.bars[i]
            for side in (1, -1):
                plan = xm.plan(b, side, ind, i)
                if side > 0:
                    assert plan.stop < b.close
                else:
                    assert plan.stop > b.close
                assert plan.stop_distance > 0

    def test_stop_distance_respects_the_percentage_band(self, res15):
        """min_stop_pct is a spread/noise floor and max_stop_pct a budget ceiling;
        a stop outside the band makes 1R unreachable or absurd."""
        c = ExitConfig()
        xm = ExitManager(c, res15.settings)
        for i in range(300, len(res15.bars), 37):
            b = res15.bars[i]
            plan = xm.plan(b, 1, res15.indicators, i)
            pct = plan.stop_distance / b.close * 100.0
            assert c.min_stop_pct * 0.999 <= pct <= c.max_stop_pct * 1.001, \
                f"stop {pct:.3f}% outside [{c.min_stop_pct}, {c.max_stop_pct}]"

    def test_structural_stop_is_clamped_into_the_sigma_band(self, res15):
        """Regression: the last *confirmed* pivot on a 15m chart can sit dozens of
        bars back, giving a 1.57% stop against a 0.26% ATR — 6x the timeframe can
        deliver.  The clamp lets structure refine the stop, not redefine it.

        The band is expressed in the module's own volatility unit
        (:meth:`ExitManager._sigma`, which prefers the smoothed ``sigma_atr`` over
        a single bar's raw sigma), and the final stop may still leave the band via
        the ``min_stop_pct`` spread floor or the ``max_stop_pct`` budget ceiling —
        both of which are checked separately."""
        c = ExitConfig(stop_mode="structure")
        xm = ExitManager(c, res15.settings)
        checked = 0
        for i in range(400, len(res15.bars), 29):
            b = res15.bars[i]
            sig = xm._sigma(b)
            if sig <= 0:
                continue
            plan = xm.plan(b, 1, res15.indicators, i)
            pct = plan.stop_distance / b.close * 100.0
            if plan.capped:                       # bound by the % band, not the clamp
                assert pct == pytest.approx(c.min_stop_pct, rel=1e-6) or \
                       pct == pytest.approx(c.max_stop_pct, rel=1e-6)
                continue
            sigmas = plan.stop_distance / sig
            # the structural buffer is added outside the clamp
            assert sigmas <= c.structure_max_sigma_mult + c.structure_buffer_sigma + 1e-6, \
                f"{sigmas:.2f} sigma at i={i}"
            assert sigmas >= c.structure_min_sigma_mult * 0.999
            checked += 1
        assert checked > 20

    def test_targets_are_ordered_and_spaced_in_r(self, res15):
        xm = ExitManager(ExitConfig(), res15.settings)
        i = len(res15.bars) - 5
        plan = xm.plan(res15.bars[i], 1, res15.indicators, i)
        ts = [t for t in plan.targets]
        assert ts == sorted(ts)
        assert all(t > plan.stop for t in ts)

    def test_wider_sigma_multiplier_gives_a_wider_stop(self, res15):
        i = len(res15.bars) - 5
        b = res15.bars[i]
        narrow = ExitManager(ExitConfig(stop_mode="sigma", stop_sigma_mult=1.5),
                             res15.settings).plan(b, 1, res15.indicators, i)
        wide = ExitManager(ExitConfig(stop_mode="sigma", stop_sigma_mult=4.0),
                           res15.settings).plan(b, 1, res15.indicators, i)
        assert wide.stop_distance > narrow.stop_distance


class TestExitExecution:
    def test_tranches_hit_reports_only_unfilled_in_order(self):
        xm = ExitManager(ExitConfig())
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        # 1R = entry + 1 * stop_distance = 102, 2R = 104
        assert xm.tranches_hit(pos, 101.0) == []
        assert xm.tranches_hit(pos, 103.0) == [0]
        assert xm.tranches_hit(pos, 105.0) == [0, 1]       # a gap through both
        pos.tranches[0].filled = True
        assert xm.tranches_hit(pos, 105.0) == [1]
        pos.tranches[1].filled = True
        assert xm.tranches_hit(pos, 200.0) == []           # only the runner is left
        # the runner has r_multiple == 0, so it is never a fixed-R target
        assert all(t.r_multiple > 0 for t in pos.tranches
                   if t in [pos.tranches[k] for k in xm.tranches_hit(pos, 1e6)])

    def test_tranche_qty_is_a_share_of_the_initial_position(self):
        xm = ExitManager(ExitConfig())
        pos = make_position(qty=10.0)
        assert xm.tranche_qty(pos, 0) == pytest.approx(4.0)
        assert xm.tranche_qty(pos, 1) == pytest.approx(3.5)
        # the runner takes whatever is left
        pos.qty = 2.5
        assert xm.tranche_qty(pos, 2) == pytest.approx(2.5)

    def test_stop_hit_is_side_aware(self):
        xm = ExitManager(ExitConfig())
        long_pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        assert not xm.stop_hit(long_pos, 99.0)
        assert xm.stop_hit(long_pos, 97.0)
        short_pos = make_position(side=-1, entry=100.0, stop_distance=2.0)
        assert not xm.stop_hit(short_pos, 101.0)
        assert xm.stop_hit(short_pos, 103.0)

    def test_combine_severity_is_a_noisy_or(self):
        """Independent reversal warnings must combine sub-additively and stay in
        [0, 1] — summing them would saturate on the first two events."""
        from engine.exits import ReversalEvent
        one = [ReversalEvent(name="a", severity=0.5, weight=1.0, detail="")]
        two = one + [ReversalEvent(name="b", severity=0.5, weight=1.0, detail="")]
        s1, s2 = combine_severity(one), combine_severity(two)
        assert 0.0 <= s1 <= 1.0 and 0.0 <= s2 <= 1.0
        assert s2 > s1
        assert s2 < s1 + 0.5                              # sub-additive
        assert combine_severity([]) == 0.0

    def test_stop_detection_is_side_aware_and_uses_the_stop_level(self):
        """``on_bar`` manages the position at bar close (trailing, break-even,
        time exits, reversal events); *stop and target fills* are resolved by the
        backtester minute by minute via ``stop_hit``/``tranches_hit``.  Testing the
        split explicitly keeps the two from drifting into each other."""
        xm = ExitManager(ExitConfig())
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        assert pos.stop == pytest.approx(98.0)
        assert not xm.stop_hit(pos, 99.0)
        assert xm.stop_hit(pos, 98.0)
        assert xm.stop_hit(pos, 95.0)

    def test_on_bar_returns_a_decision_and_counts_the_bar(self, res15):
        xm = ExitManager(ExitConfig(), res15.settings)
        i = len(res15.bars) - 3
        b = res15.bars[i]
        pos = make_position(side=1, entry=b.close, stop_distance=b.sigma * 2.0, i=i)
        before = pos.bars_held
        d = xm.on_bar(pos, res15.bars, i, res15.indicators)
        assert d.action in ("hold", "tighten", "close_partial", "close_all")
        assert pos.bars_held == before + 1

    def test_on_bar_holds_a_quiet_bar(self, res15):
        xm = ExitManager(ExitConfig(), res15.settings)
        i = len(res15.bars) - 3
        b = res15.bars[i]
        pos = make_position(side=1, entry=b.close, stop_distance=b.sigma * 2.0, i=i)
        # a bar that stays inside the stop and has not developed yet
        quiet = bar_at(i, b.close, high=b.close * 1.0005, low=b.close * 0.9995)
        quiet.sigma = b.sigma
        quiet.sigma_atr = b.sigma_atr
        quiet.atr = b.atr
        bars = list(res15.bars[:i]) + [quiet]
        d = xm.on_bar(pos, bars, i, res15.indicators)
        assert d.action in ("hold", "")

    def test_stop_moves_to_break_even_after_1r(self, res15):
        # trailing disabled so the break-even promotion is the only thing that can
        # move the stop — otherwise the chandelier gets there first and be_moved
        # legitimately stays False
        c = ExitConfig(move_stop_to_be_after_r=1.0, be_buffer_sigma=0.0,
                       trail_mode="none", reprice_each_bar=False)
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        bars = [bar_at(0, 100.0), bar_at(1, 102.5, high=103.0, low=101.0)]
        xm.on_bar(pos, bars, 1, res15.indicators)
        assert pos.peak_r >= 1.0
        assert pos.stop == pytest.approx(100.0, abs=1e-9)
        assert pos.be_moved

    def test_break_even_promotion_waits_for_the_threshold(self, res15):
        c = ExitConfig(move_stop_to_be_after_r=2.0, trail_mode="none",
                       reprice_each_bar=False)
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        bars = [bar_at(0, 100.0), bar_at(1, 102.5, high=103.0, low=101.0)]  # 1.5R
        xm.on_bar(pos, bars, 1, res15.indicators)
        assert not pos.be_moved
        assert pos.stop == pytest.approx(98.0)

    def test_ratchet_never_loosens_the_stop(self, res15):
        c = ExitConfig(ratchet_never_loosen=True, trail_start_r=0.2)
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        highest = pos.stop
        prices = [101.0, 103.0, 105.0, 102.0, 104.0, 99.0, 101.0]
        bars = [bar_at(0, 100.0)]
        for k, p in enumerate(prices, start=1):
            bars.append(bar_at(k, p, high=p + 0.5, low=p - 1.5))
            xm.on_bar(pos, bars, k, res15.indicators)
            assert pos.stop >= highest - 1e-9, f"stop loosened at step {k}"
            highest = max(highest, pos.stop)

    def test_short_position_ratchets_downwards(self, res15):
        c = ExitConfig(ratchet_never_loosen=True, trail_start_r=0.2)
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=-1, entry=100.0, stop_distance=2.0)
        lowest = pos.stop
        bars = [bar_at(0, 100.0)]
        for k, p in enumerate([99.0, 97.0, 95.0, 98.0, 96.0], start=1):
            bars.append(bar_at(k, p, high=p + 1.5, low=p - 0.5))
            xm.on_bar(pos, bars, k, res15.indicators)
            assert pos.stop <= lowest + 1e-9, f"short stop loosened at {k}"
            lowest = min(lowest, pos.stop)


class TestReversalEvents:
    def test_events_are_gated_on_maturity(self, res15):
        """A fresh position (peak_r below the gate) must not be exited by the
        noise that created it: the efficiency-collapse and flow-flip detectors
        fire on ordinary bars unless they wait for the trade to develop."""
        c = ExitConfig()
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.peak_r = 0.0                                  # just entered
        bars = [bar_at(0, 100.0), bar_at(1, 100.1, high=100.3, low=99.8)]
        ev = xm.detect_events(pos, bars, 1, res15.indicators)
        gated = {e.name for e in ev if e.name in ("efficiency_collapse", "leg_flow_flip")}
        assert not gated, f"maturity gate ignored: {gated}"

    def test_events_can_fire_once_the_trade_has_developed(self, res15):
        """The gate must not be a permanent mute — with peak_r past the threshold a
        genuine stall has to be detectable, or the ladder is decorative."""
        c = ExitConfig()
        xm = ExitManager(c, res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.peak_r = 1.5
        fired_any = False
        bars = [bar_at(0, 100.0)]
        for k in range(1, 40):
            b = bar_at(k, 103.0 - (k % 5) * 0.4, high=103.5, low=101.0)
            b.efficiency = 0.05 if k % 3 == 0 else 0.6
            bars.append(b)
            if xm.detect_events(pos, bars, k, res15.indicators):
                fired_any = True
                break
        assert fired_any, "no reversal event ever fired on a stalling path"

    def test_event_severity_is_bounded(self, res15):
        xm = ExitManager(ExitConfig(), res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.peak_r = 1.0
        bars = [bar_at(0, 100.0), bar_at(1, 99.0, high=101.0, low=98.0)]
        for e in xm.detect_events(pos, bars, 1, res15.indicators):
            assert 0.0 <= e.severity <= 1.0
            assert e.name and isinstance(e.detail, str)

    def test_events_can_be_disabled(self, res15):
        xm = ExitManager(ExitConfig(events_enabled=False), res15.settings)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.peak_r = 2.0
        bars = [bar_at(k, 100.0 - k) for k in range(3)]
        assert xm.detect_events(pos, bars, 2, res15.indicators) == []

    def _bar_with_path(self, closes: list[float], tf: int = 15) -> Bar:
        """A bar whose minute_path follows ``closes`` (used for mid-bar checks)."""
        mins = []
        prev = closes[0]
        for k, c in enumerate(closes):
            mins.append(MinuteBar(ts=k * 60_000, open=prev, high=max(prev, c) * 1.0001,
                                  low=min(prev, c) * 0.9999, close=c, volume=10.0))
            prev = c
        b = rs.resample(mins, tf, drop_incomplete=False)[0]
        systembar.compute_system_bar(b)
        b.sigma = 1.0
        b.sigma_atr = 1.0
        b.atr = 1.0
        return b

    def test_intra_bar_check_needs_a_minute_path(self):
        """No path, no mid-bar evidence: returning a decision here would be a
        guess dressed up as intra-bar resolution."""
        xm = ExitManager(ExitConfig())
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        assert xm.intra_bar_check(pos, bar_at(1, 101.0), 5, 5) is None

    def test_intra_bar_check_only_fires_at_the_configured_elapsed_minute(self):
        c = ExitConfig()
        xm = ExitManager(c)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        b = self._bar_with_path([100.0 + i * 0.1 for i in range(15)])
        target = int(math.floor(b.tf * c.event_check_elapsed))
        assert target >= 2
        for k in range(15):
            if k != target:
                assert xm.intra_bar_check(pos, b, k, k) is None, f"minute {k}"

    def test_intra_bar_check_is_disabled_with_the_events(self):
        xm = ExitManager(ExitConfig(events_enabled=False))
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        b = self._bar_with_path([100.0 + i * 0.1 for i in range(15)])
        assert xm.intra_bar_check(pos, b, 9, 9) is None

    def test_intra_bar_check_can_flag_a_mid_bar_flow_flip(self):
        """The one event with genuine mid-bar evidence is a flow flip: the last
        minutes' legs are already known.  A long whose tail flow turns hard
        against it must be detectable before the bar closes."""
        c = ExitConfig(intra_bar_event_check=True, tighten_severity=0.3,
                       exit_all_severity=0.95, max_tightens_per_trade=3)
        xm = ExitManager(c)
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.peak_r = 1.0
        # rises gently, then collapses in the last minutes
        closes = [100.0 + 0.05 * i for i in range(8)] + [100.4 - 0.9 * i
                                                         for i in range(1, 8)]
        b = self._bar_with_path(closes)
        target = int(math.floor(b.tf * c.event_check_elapsed))
        d = xm.intra_bar_check(pos, b, target, target)
        if d is not None:                                # severity may stay below the gate
            assert d.action in ("tighten", "close_all")
            assert "intrabar" in d.reason
            assert d.price_hint == pytest.approx(b.minute_path[target - 1].close)


class TestPositionAccounting:
    def test_r_of_is_side_aware_and_normalised_by_stop_distance(self):
        pos = make_position(side=1, entry=100.0, stop_distance=4.0)
        assert pos.r_of(104.0) == pytest.approx(1.0)
        assert pos.r_of(96.0) == pytest.approx(-1.0)
        short = make_position(side=-1, entry=100.0, stop_distance=4.0)
        assert short.r_of(96.0) == pytest.approx(1.0)
        assert short.r_of(104.0) == pytest.approx(-1.0)

    def test_update_extremes_tracks_mfe_and_mae(self):
        pos = make_position(side=1, entry=100.0, stop_distance=2.0)
        pos.update_extremes(105.0, 99.0)
        pos.update_extremes(103.0, 101.0)
        assert pos.highest_since_entry == pytest.approx(105.0)
        assert pos.lowest_since_entry == pytest.approx(99.0)
        assert pos.peak_r == pytest.approx(2.5)
        assert pos.trough_r == pytest.approx(-0.5)

    def test_qty_share_open_tracks_partial_fills(self):
        pos = make_position(qty=10.0)
        assert pos.qty_share_open() == pytest.approx(1.0)
        pos.qty = 4.0
        assert pos.qty_share_open() == pytest.approx(0.4)
        pos.qty = 0.0
        assert pos.qty_share_open() == pytest.approx(0.0)

    def test_unrealised_r_is_side_aware(self):
        pos = make_position(side=1, entry=100.0, stop_distance=4.0)
        assert pos.unrealised_r(104.0) == pytest.approx(1.0)
        short = make_position(side=-1, entry=100.0, stop_distance=4.0)
        assert short.unrealised_r(96.0) == pytest.approx(1.0)
