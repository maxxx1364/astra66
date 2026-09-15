"""Backtest correctness: the accounting identity, causality, and fill semantics.

A backtest is only worth reading if three things hold, and each is asserted here
against real runs rather than mocks:

* the money adds up — ``net == gross - costs`` on every trade, the equity curve
  integrates to the same final number, and one full stop-out costs exactly the
  budgeted cash;
* nothing sees the future — decisions on bar ``i-1`` fill on bar ``i``, warmup is
  respected, re-running on truncated history reproduces the overlapping trades,
  and a look-ahead configuration has to be *explicitly* allowed (and is then
  recorded in the manifest);
* fills mean what they say — resting limit entries are maker-priced with zero
  slippage and are cancelled when price runs away, adverse moves resolve before
  favourable ones inside a bar, and exits are attributed to a minute of the bar
  in which they happened.
"""
from __future__ import annotations

import json
import math

import pytest

from engine import backtest as BT
from engine import pipeline
from engine.backtest import BacktestConfig
from engine.exits import exit_config_presets
from engine.risk import CostConfig, RiskConfig
from engine.signals import SignalConfig

pytestmark = pytest.mark.slow

DAYS = 20          # short enough to keep the suite fast, long enough for ~30 trades
PRESETS = exit_config_presets()


@pytest.fixture(scope="module")
def res():
    return pipeline.run(days=DAYS, seed=7, tf=15)


@pytest.fixture(scope="module")
def result(res):
    return BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))


def bars_by_index(res_or_result):
    return {i: b for i, b in enumerate(res_or_result.bars)}


def decision_index_for(position, signals):
    """Match a position back to the signal that produced it (by score, then order)."""
    for s in signals.signals:
        if abs(s.score - position.signal_score) < 1e-12 and s.index < position.entry_index:
            return s.index
    raise AssertionError(f"no signal precedes position entered at {position.entry_index}")


# --------------------------------------------------------------------- #
# 1. the accounting identity
# --------------------------------------------------------------------- #
class TestAccounting:
    def test_costs_are_the_sum_of_their_parts(self, result):
        assert result.trades, "fixture should produce trades"
        for t in result.trades:
            parts = t.commission_cost + t.funding_cost + t.slippage_cost
            assert t.costs == pytest.approx(parts, rel=1e-9, abs=1e-12)
            assert t.costs >= 0.0

    def test_net_equals_gross_minus_costs_on_every_trade(self, result):
        for t in result.trades:
            assert t.net_pnl == pytest.approx(t.gross_pnl - t.costs, rel=1e-9, abs=1e-9), (
                f"net {t.net_pnl} != gross {t.gross_pnl} - costs {t.costs}")

    def test_r_multiple_is_net_pnl_over_the_cash_actually_risked(self, result):
        for t in result.trades:
            assert t.risk_cash > 0.0
            assert t.r_multiple == pytest.approx(t.net_pnl / t.risk_cash, rel=1e-9)
            assert math.isfinite(t.r_multiple)

    def test_one_full_stop_out_costs_exactly_the_risk_budget(self, result):
        """The sizing contract: ``initial_qty * stop_distance == risk_cash``, so a
        stop-out loses the budgeted cash and 1R means what the report says."""
        for p in result.positions:
            assert p.initial_qty > 0.0 and p.stop_distance > 0.0
            assert p.initial_qty * p.stop_distance == pytest.approx(p.risk_cash, rel=1e-6)

    def test_commission_is_the_sum_of_the_fill_commissions(self, result):
        for pos, t in zip(result.positions, result.trades):
            assert pos.entry_ts == t.entry_ts, "positions and trades are 1:1 and in order"
            assert t.commission_cost == pytest.approx(
                sum(f.commission for f in pos.fills), rel=1e-9, abs=1e-9)
            assert t.slippage_cost == pytest.approx(
                sum(f.slippage for f in pos.fills), rel=1e-9, abs=1e-9)

    def test_entry_friction_is_charged_exactly_once(self, result):
        for pos in result.positions:
            entries = [f for f in pos.fills if f.reason == "entry"]
            assert len(entries) == 1
            assert entries[0].commission > 0.0
            assert entries[0].r_multiple == 0.0, "the entry leg achieves no R by definition"

    def test_fill_r_sits_between_the_reference_gross_and_the_net(self, result):
        """The R-decomposition, per trade: gross is measured at frictionless
        reference prices, the fills carry real prices (so slip but no fees), and
        net carries both.  Any ordering violation means one of the three ledgers
        is wrong."""
        for pos, t in zip(result.positions, result.trades):
            weighted = sum(f.r_multiple * (abs(f.qty) / pos.initial_qty) for f in pos.fills)
            gross_r = t.gross_pnl / t.risk_cash
            assert t.r_multiple - 1e-9 <= weighted <= gross_r + 1e-9, (
                f"net {t.r_multiple:.4f} <= fills {weighted:.4f} <= gross {gross_r:.4f} "
                "is violated")

    def test_avg_exit_price_is_the_quantity_weighted_exit_fill_price(self, result):
        for pos, t in zip(result.positions, result.trades):
            exits = [f for f in pos.fills if f.reason != "entry"]
            assert exits
            qty = sum(abs(f.qty) for f in exits)
            avg = sum(abs(f.qty) * f.price for f in exits) / qty
            assert t.avg_exit_price == pytest.approx(avg, rel=1e-9)

    def test_positions_are_fully_closed(self, result):
        for pos, t in zip(result.positions, result.trades):
            exited = sum(abs(f.qty) for f in pos.fills if f.reason != "entry")
            assert exited == pytest.approx(pos.initial_qty, rel=1e-9)
            assert pos.qty == pytest.approx(0.0, abs=1e-12)
            assert t.exit_ts >= t.entry_ts

    def test_equity_curve_integrates_to_the_final_equity(self, result):
        curve = result.equity_curve
        expected = result.manifest["initial_equity"] + sum(t.net_pnl for t in result.trades)
        assert curve[-1].equity == pytest.approx(expected, rel=1e-9)
        assert result.manifest["final_equity"] == pytest.approx(expected, rel=1e-9)
        assert curve[-1].cash == pytest.approx(expected, rel=1e-9), (
            "with everything closed, cash is equity")

    def test_equity_curve_covers_the_tradable_window(self, result, res):
        curve = result.equity_curve
        assert curve[0].index == res.warmup_index
        assert curve[-1].index == len(result.bars) - 1
        assert len(curve) == len(result.bars) - res.warmup_index

    def test_equity_only_moves_when_something_happens(self, result):
        """A jump on a bar with no fill and no open position would be value invented
        out of nothing."""
        active = {f.bar_index for p in result.positions for f in p.fills}
        prev = None
        for pt in result.equity_curve:
            if prev is not None and pt.index not in active and pt.open_positions == 0:
                assert pt.equity == pytest.approx(prev.equity, rel=1e-12)
            prev = pt

    def test_costs_are_bounded_by_a_sane_fraction_of_notional(self, result):
        for t in result.trades:
            assert t.commission_cost <= 0.01 * t.notional
            assert t.slippage_cost <= 0.01 * t.notional

    def test_no_accounting_errors_are_reported(self, result):
        assert result.accounting_errors == []


# --------------------------------------------------------------------- #
# 2. causality
# --------------------------------------------------------------------- #
class TestCausality:
    def test_every_entry_fills_after_its_decision_bar(self, result):
        for pos in result.positions:
            d = decision_index_for(pos, result.signals)
            assert pos.entry_index > d, (
                f"position filled on decision bar {d} — that is look-ahead")
            for f in pos.fills:
                assert f.bar_index >= pos.entry_index

    def test_market_entries_fill_on_the_bar_after_the_decision(self, res):
        r = BT.run_backtest(res, signal_cfg=SignalConfig(entry_timing="immediate",
                                                         execution="next_open"),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.trades
        bars = bars_by_index(r)
        for pos in r.positions:
            d = decision_index_for(pos, r.signals)
            assert pos.entry_index == d + 1, "next_open must act on the very next bar"
            fill_bar = bars[pos.entry_index]
            assert fill_bar.low * 0.999 <= pos.entry_price <= fill_bar.high * 1.001

    def test_no_position_opens_before_warmup(self, result, res):
        assert res.warmup_index > 0
        for pos in result.positions:
            assert pos.entry_index >= res.warmup_index

    def test_exits_never_precede_their_entry(self, result):
        for pos in result.positions:
            assert pos.exit_ts >= pos.entry_ts
            assert pos.bars_held >= 0
            for f in pos.fills:
                assert f.ts >= pos.entry_ts

    def test_a_look_ahead_reference_is_refused_by_default(self, res):
        res.settings.reference_mode = "full"
        try:
            with pytest.raises(ValueError, match="look-ahead"):
                BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        finally:
            res.settings.reference_mode = "expanding"

    def test_the_look_ahead_override_is_recorded_in_the_manifest(self, res):
        res.settings.reference_mode = "full"
        try:
            r = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal",
                                                           allow_lookahead=True))
            assert r.manifest["allow_lookahead"] is True
            assert r.manifest["lookahead_flags"] == ["reference_mode='full'"]
            assert any("LOOK-AHEAD ALLOWED" in w for w in r.warnings)
        finally:
            res.settings.reference_mode = "expanding"

    def test_causal_runs_record_no_look_ahead_flags(self, result):
        assert result.manifest["allow_lookahead"] is False
        assert result.manifest["lookahead_flags"] == []
        assert result.manifest["reference_mode"] == "expanding"

    def test_truncated_history_reproduces_the_overlapping_trades(self, res):
        """The strongest causality test available: rebuild the whole stack on a
        shorter window and the trades inside the overlap must be identical."""
        half = len(res.minutes) // 2
        short = pipeline.run(minutes=res.minutes[:half], tf=15, seed=7)
        r_full = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        r_short = BT.run_backtest(short, bt_cfg=BacktestConfig(entry_mode="signal"))
        cutoff = len(short.bars) - 3
        a = [t for t in r_full.trades if t.entry_index < cutoff]
        b = [t for t in r_short.trades if t.entry_index < cutoff]
        assert a and b, "both runs need trades inside the overlap"
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x.entry_index == y.entry_index
            assert x.side == y.side
            assert x.entry_price == pytest.approx(y.entry_price, rel=1e-9)
            assert x.r_multiple == pytest.approx(y.r_multiple, rel=1e-9)

    def test_same_inputs_are_reproducible(self, res):
        a = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        b = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        assert a.manifest["config_hash"] == b.manifest["config_hash"]
        assert [t.entry_index for t in a.trades] == [t.entry_index for t in b.trades]
        assert [t.r_multiple for t in a.trades] == [t.r_multiple for t in b.trades]
        assert a.metrics["returns"]["total_return_pct"] == b.metrics["returns"]["total_return_pct"]

    def test_manifest_describes_the_run_it_produced(self, result, res):
        m = result.manifest
        assert m["n_trades"] == len(result.trades)
        assert m["bars"] == len(result.bars)
        assert m["timeframe"] == res.settings.timeframe
        assert m["first_ts"] == result.bars[0].ts
        assert m["last_ts"] == result.bars[-1].ts
        assert m["initial_equity"] == RiskConfig().initial_equity
        assert m["engine_version"]


# --------------------------------------------------------------------- #
# 3. entry execution semantics
# --------------------------------------------------------------------- #
class TestEntryExecution:
    def test_pullback_limits_never_fill_worse_than_the_signal_close(self, result):
        """The point of a resting limit: the retracement level sits *inside* the
        signal bar, so a long cannot fill above that bar's close.  A market order
        can, and that is the adverse selection this avoids."""
        assert result.pending_stats["entry_timing"] == "pullback_limit"
        bars = bars_by_index(result)
        assert result.positions
        for pos in result.positions:
            entry = pos.fills[0]
            fill_bar = bars[entry.bar_index]
            assert fill_bar.low - 1e-9 <= entry.price <= fill_bar.high + 1e-9
            decision = bars[decision_index_for(pos, result.signals)]
            if pos.side == 1:
                assert entry.price <= decision.close + 1e-9
            else:
                assert entry.price >= decision.close - 1e-9

    def test_maker_entries_pay_no_slippage_and_the_maker_rate(self, res):
        cfg = CostConfig(commission_bps=20.0, maker_bps=1.0, slippage_bps=8.0)
        r = BT.run_backtest(res, risk_cfg=RiskConfig(costs=cfg),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.positions
        for pos in r.positions:
            f = pos.fills[0]
            assert f.slippage == 0.0, "a resting limit order cannot slip"
            implied = f.commission / (abs(f.qty) * f.price) * 10_000.0
            assert implied == pytest.approx(cfg.maker_bps, rel=1e-6), (
                f"maker entry charged {implied:.2f}bp, expected {cfg.maker_bps}bp")

    def test_market_entries_are_takers_and_do_slip(self, res):
        cfg = CostConfig(commission_bps=20.0, maker_bps=1.0, slippage_bps=8.0)
        r = BT.run_backtest(res, signal_cfg=SignalConfig(entry_timing="immediate"),
                            risk_cfg=RiskConfig(costs=cfg),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.positions
        for pos in r.positions:
            f = pos.fills[0]
            assert f.slippage > 0.0, "crossing the spread must cost something"
            implied = f.commission / (abs(f.qty) * f.price) * 10_000.0
            assert implied == pytest.approx(cfg.commission_bps, rel=1e-6)

    def test_stop_exits_cross_the_spread(self, res):
        cfg = CostConfig(commission_bps=20.0, maker_bps=1.0, slippage_bps=8.0)
        r = BT.run_backtest(res, risk_cfg=RiskConfig(costs=cfg),
                            exit_cfg=PRESETS["tight"],
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        stops = [f for p in r.positions for f in p.fills if f.reason == "stop"]
        assert stops, "a tight stop should be hit within 20 days"
        for f in stops:
            implied = f.commission / (abs(f.qty) * f.price) * 10_000.0
            assert implied == pytest.approx(cfg.commission_bps, rel=1e-6)
            assert f.slippage > 0.0

    def test_pending_order_book_reconciles(self, result):
        ps = result.pending_stats
        assert ps["orders_emitted"] == (ps["orders_filled"] + ps["orders_invalidated"]
                                        + ps["orders_expired"] + ps["still_resting_at_end"])
        assert 0.0 <= ps["fill_rate"] <= 1.0
        assert result.entry_blocks.get("pullback_invalidated", 0) == ps["orders_invalidated"]

    def test_immediate_mode_rests_no_orders(self, res):
        r = BT.run_backtest(res, signal_cfg=SignalConfig(entry_timing="immediate"),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.pending_stats["orders_emitted"] == 0
        assert r.pending_stats["entry_timing"] == "immediate"

    def test_entry_funnel_reconciles_end_to_end(self, result):
        ef = result.entry_funnel
        assert ef["orders_placed"] == (ef["orders_filled"] + ef["orders_invalidated"]
                                       + ef["orders_expired"] + ef["orders_resting_at_end"])
        assert ef["entry_attempts"] == ef["positions_opened"] + ef["gate_blocked"]
        assert ef["positions_opened"] <= ef["orders_filled"] <= ef["signals_emitted"]
        assert ef["end_to_end_rate"] == pytest.approx(
            ef["positions_opened"] / ef["signals_emitted"], rel=1e-9)
        assert ef["positions_opened"] == len(result.positions)

    def test_the_risk_gate_is_why_a_fill_does_not_become_a_position(self, res):
        r = BT.run_backtest(res, risk_cfg=RiskConfig(max_open_positions=1),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert any(k.startswith("risk_gate:") for k in r.entry_blocks), (
            f"with one slot open some fills must be vetoed, got {r.entry_blocks}")
        assert r.entry_funnel["gate_blocked"] > 0

    def test_pullback_level_modes_all_produce_fills(self, res):
        for mode in ("sigma", "body", "midpoint"):
            r = BT.run_backtest(res, signal_cfg=SignalConfig(pullback_mode=mode),
                                bt_cfg=BacktestConfig(entry_mode="signal"))
            assert r.positions, f"pullback_mode={mode} produced no trades"
            assert r.pending_stats["orders_emitted"] > 0


# --------------------------------------------------------------------- #
# 4. exit resolution
# --------------------------------------------------------------------- #
class TestExitResolution:
    def test_stop_fills_are_at_or_worse_than_the_stop_they_triggered(self, result):
        for pos in result.positions:
            stops = [f for f in pos.fills if f.reason == "stop"]
            for f in stops:
                # slippage can only make a stop worse, never better
                if pos.side == 1:
                    assert f.price <= pos.stop + 1e-9
                else:
                    assert f.price >= pos.stop - 1e-9

    def test_take_profit_fills_are_on_the_profitable_side(self, result):
        for pos in result.positions:
            for f in pos.fills:
                if not f.reason.startswith("tp"):
                    continue
                if pos.side == 1:
                    assert f.price >= pos.entry_price
                else:
                    assert f.price <= pos.entry_price
                assert f.r_multiple > 0.0

    def test_exits_are_attributed_to_a_minute_of_their_bar(self, res):
        r = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal",
                                                       use_intra_bar_path=True))
        assert r.manifest["intra_bar_path"] is True
        tf = r.manifest["timeframe"]
        bars = bars_by_index(r)
        seen_minute = 0
        for pos in r.positions:
            for f in pos.fills:
                if f.minute_index < 0:
                    continue                      # -1 is the "not minute-resolved" sentinel
                assert 0 <= f.minute_index < tf, (
                    f"minute_index {f.minute_index} is not a valid index into a "
                    f"{tf}-minute bar's path")
                # and it must name the minute the fill actually happened in
                assert bars[f.bar_index].minute_path[f.minute_index].ts == f.ts
                seen_minute += 1
        assert seen_minute, "with the minute path enabled, exits should name a minute"

    def test_exit_prices_stay_inside_the_exit_bar(self, result):
        bars = bars_by_index(result)
        for pos in result.positions:
            for f in pos.fills:
                bar = bars[f.bar_index]
                tol = bar.high * 0.002 + 1e-9        # slippage may push slightly out
                assert bar.low - tol <= f.price <= bar.high + tol

    def test_disabling_the_minute_path_changes_exit_prices(self, res):
        """If the intra-bar path were decoration, turning it off would change
        nothing — and then the accuracy claim would be empty."""
        a = BT.run_backtest(res, bt_cfg=BacktestConfig(use_intra_bar_path=True))
        b = BT.run_backtest(res, bt_cfg=BacktestConfig(use_intra_bar_path=False))
        assert a.trades and b.trades
        pa = [t.avg_exit_price for t in a.trades]
        pb = [t.avg_exit_price for t in b.trades]
        assert pa != pb or len(a.trades) != len(b.trades), (
            "bar-only resolution should not reproduce minute-path exits exactly")
        assert any("intra-bar path resolution disabled" in w for w in b.warnings)

    def test_adverse_first_is_the_pessimistic_choice(self, res):
        a = BT.run_backtest(res, bt_cfg=BacktestConfig(adverse_first=True))
        b = BT.run_backtest(res, bt_cfg=BacktestConfig(adverse_first=False))
        ea = sum(t.net_pnl for t in a.trades)
        eb = sum(t.net_pnl for t in b.trades)
        assert ea <= eb + 1e-9, (
            f"resolving ambiguity favourably must not lose more: adverse {ea:.1f} "
            f"vs optimistic {eb:.1f}")
        assert any("optimism" in w for w in b.warnings)

    def test_wide_stops_survive_at_least_as_long_as_tight_ones(self, res):
        tight = BT.run_backtest(res, exit_cfg=PRESETS["tight"],
                                bt_cfg=BacktestConfig(entry_mode="signal"))
        wide = BT.run_backtest(res, exit_cfg=PRESETS["wide"],
                               bt_cfg=BacktestConfig(entry_mode="signal"))
        assert tight.trades and wide.trades
        h_t = sum(1 for t in tight.trades if t.exit_reason == "stop") / len(tight.trades)
        h_w = sum(1 for t in wide.trades if t.exit_reason == "stop") / len(wide.trades)
        assert h_w <= h_t + 1e-9, f"wide {h_w:.2f} stopped out more than tight {h_t:.2f}"
        assert (sum(t.bars_held for t in wide.trades) / len(wide.trades)
                >= sum(t.bars_held for t in tight.trades) / len(tight.trades) - 1e-9)

    def test_staging_produces_partial_exits(self, res):
        staged = BT.run_backtest(res, exit_cfg=PRESETS["default"],
                                 bt_cfg=BacktestConfig(entry_mode="signal"))
        flat = BT.run_backtest(res, exit_cfg=PRESETS["no_staging"],
                               bt_cfg=BacktestConfig(entry_mode="signal"))
        assert any(t.tranches_filled > 1 for t in staged.trades), (
            "staged exits should scale out more than once on some trades")
        assert all(t.tranches_filled <= 1 for t in flat.trades)

    def test_open_positions_at_the_end_are_closed_not_dropped(self, res):
        r = BT.run_backtest(res, bt_cfg=BacktestConfig(close_open_at_end=True))
        assert all(p.qty == pytest.approx(0.0, abs=1e-12) for p in r.positions)
        assert len(r.positions) == len(r.trades)
        kept = BT.run_backtest(res, bt_cfg=BacktestConfig(close_open_at_end=False))
        assert len(kept.trades) <= len(r.trades)

    def test_exit_reasons_collapse_into_known_families(self, result):
        from engine.exits import EXIT_FAMILIES, exit_reason_family
        for t in result.trades:
            fam = exit_reason_family(t.exit_reason)
            assert fam in EXIT_FAMILIES
            assert fam != "other", f"'{t.exit_reason}' did not map to a family"
            assert fam != "entry", "an exit reason must not be the entry leg"
        assert sum(result.exit_reason_counts.values()) == len(result.trades)

    def test_exit_family_stats_reconcile_with_the_trades(self, result):
        fams = result.metrics["trades"]["exit_families"]
        assert fams
        assert sum(v["n"] for v in fams.values()) == len(result.trades)
        assert sum(v["share"] for v in fams.values()) == pytest.approx(1.0, rel=1e-9)
        assert sum(v["net_pnl"] for v in fams.values()) == pytest.approx(
            sum(t.net_pnl for t in result.trades), rel=1e-9)


# --------------------------------------------------------------------- #
# 5. controls and configuration plumbing
# --------------------------------------------------------------------- #
class TestControlsAndConfig:
    def test_control_runs_produce_trades_and_say_they_are_controls(self, res):
        rnd = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="random", random_seed=11))
        evb = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="every_bar"))
        assert rnd.manifest["entry_mode"] == "random"
        assert evb.manifest["entry_mode"] == "every_bar"
        assert rnd.trades and evb.trades
        assert len(evb.trades) > len(rnd.trades)
        assert any("control run" in w for w in rnd.warnings)
        assert any("control run" in w for w in evb.warnings)

    def test_random_control_matches_the_real_signal_count(self, res):
        r = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="random", random_seed=5))
        real = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        assert any(str(len(real.signals.signals)) in w for w in r.warnings), (
            "the control should state how many real signals it matched")

    def test_random_control_is_seed_dependent_but_deterministic(self, res):
        a = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="random", random_seed=3))
        b = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="random", random_seed=3))
        c = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="random", random_seed=4))
        ia = [t.entry_index for t in a.trades]
        assert ia == [t.entry_index for t in b.trades]
        assert ia != [t.entry_index for t in c.trades]

    def test_entry_mode_defaults_to_signal(self):
        assert BacktestConfig().entry_mode == "signal"

    def test_unknown_entry_mode_is_rejected(self, res):
        with pytest.raises(ValueError, match="entry_mode"):
            BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="telepathy"))

    def test_config_hash_tracks_the_cost_model(self, res):
        a = BT.run_backtest(res, bt_cfg=BacktestConfig(entry_mode="signal"))
        b = BT.run_backtest(res, risk_cfg=RiskConfig(costs=CostConfig(commission_bps=9.0)),
                            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert a.manifest["config_hash"] != b.manifest["config_hash"]

    def test_higher_friction_lowers_net_but_barely_moves_gross(self, res):
        cheap = BT.run_backtest(res, risk_cfg=RiskConfig(costs=CostConfig(
            commission_bps=1.0, maker_bps=0.0, slippage_bps=1.0)),
            bt_cfg=BacktestConfig(entry_mode="signal"))
        pricey = BT.run_backtest(res, risk_cfg=RiskConfig(costs=CostConfig(
            commission_bps=20.0, maker_bps=20.0, slippage_bps=20.0)),
            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert cheap.trades and pricey.trades
        assert sum(t.net_pnl for t in cheap.trades) > sum(t.net_pnl for t in pricey.trades)
        # gross is measured at reference prices, so it is close to cost-independent
        g_c = sum(t.gross_pnl for t in cheap.trades)
        g_p = sum(t.gross_pnl for t in pricey.trades)
        assert g_c == pytest.approx(g_p, rel=0.05)

    def test_zero_cost_run_has_net_equal_to_gross(self, res):
        r = BT.run_backtest(res, risk_cfg=RiskConfig(costs=CostConfig(
            commission_bps=0.0, maker_bps=0.0, slippage_bps=0.0, impact_coeff=0.0,
            funding_bps_per_day=0.0, min_ticket_fee=0.0)),
            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.trades
        for t in r.trades:
            assert t.costs == pytest.approx(0.0, abs=1e-12)
            assert t.net_pnl == pytest.approx(t.gross_pnl, rel=1e-9)
            assert t.r_multiple == pytest.approx(t.gross_pnl / t.risk_cash, rel=1e-9)

    def test_cost_bound_run_says_so(self, res):
        r = BT.run_backtest(res, risk_cfg=RiskConfig(costs=CostConfig(
            commission_bps=60.0, maker_bps=60.0, slippage_bps=60.0)),
            bt_cfg=BacktestConfig(entry_mode="signal"))
        assert r.metrics["trades"]["cost_bound"] is True
        assert any("cost-bound" in w for w in r.warnings)

    def test_benchmark_is_reported(self, result):
        bm = result.benchmark
        assert bm["entry_mode"] == "signal"
        bh = bm["buy_and_hold"]
        assert isinstance(bh, dict) and bh["entry_price"] > 0.0
        assert math.isfinite(bh["return_pct"])
        assert bm["strategy_final_equity"] == pytest.approx(result.manifest["final_equity"])
        assert math.isfinite(bm["strategy_return_pct"])

    def test_risk_report_and_snapshot_are_attached(self, result):
        assert isinstance(result.risk_report, dict)
        assert result.risk_snapshot
        assert result.risk_report["trades"] == len(result.trades)
        assert result.risk_report["risk_cash_mean"] > 0.0

    def test_result_serialises_to_json(self, result):
        d = result.to_dict()
        assert isinstance(d, dict)
        s = json.dumps(d, default=str)
        for key in ("entry_funnel", "pending_stats", "manifest", "metrics"):
            assert key in s

    def test_elapsed_time_is_measured(self, result):
        assert result.elapsed_ms > 0.0
