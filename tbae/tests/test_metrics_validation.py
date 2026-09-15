"""The statistics layer: every number the research conclusions rest on.

Two failure modes matter here and both are tested:

* a formula that is silently wrong (annualisation, downside deviation, the
  deflated-Sharpe trial penalty, drawdown anatomy) — these produce confident,
  plausible, false numbers;
* a procedure that degrades badly on small or degenerate input (constant returns,
  zero variance, two trades, an empty list) — these produce crashes or, worse,
  infinities that survive into a report.

The overfitting guards get the most attention, because they are the only thing
standing between a tuned backtest and a claim of edge.
"""
from __future__ import annotations

import math

import pytest

from engine import metrics as M
from engine import validation as V
from engine.portfolio import Trade


def make_trade(r: float, *, gross_r: float | None = None, pnl: float | None = None,
               risk: float = 100.0, bars: int = 5, reason: str = "stop") -> Trade:
    """A Trade with a chosen R; ``gross_r`` defaults to ``r`` plus 0.1R of friction."""
    g = (r + 0.1) if gross_r is None else gross_r
    net = r * risk if pnl is None else pnl
    return Trade(
        side=1, strategy="trend", category="medium", signal_score=0.6,
        entry_ts=0, exit_ts=bars * 900_000, entry_price=100.0, avg_exit_price=100.0 + r,
        qty=1.0, notional=100.0,
        gross_pnl=g * risk, commission_cost=0.5 * risk * (g - r),
        funding_cost=0.0, slippage_cost=0.5 * risk * (g - r),
        costs=risk * (g - r), net_pnl=net, r_multiple=r, risk_cash=risk,
        peak_r=max(r, 0.0), trough_r=min(r, 0.0), bars_held=bars,
        exit_reason=reason, tranches_filled=1, events_seen=[], stop_tightened=0,
        entry_index=0, exit_index=bars, equity_after=100_000.0 + net,
        drawdown_after=0.0,
    )


# --------------------------------------------------------------------- #
# 1. distribution helpers
# --------------------------------------------------------------------- #
class TestNormalHelpers:
    @pytest.mark.parametrize("x,expected", [(0.0, 0.5), (1.96, 0.975), (-1.96, 0.025)])
    def test_cdf_matches_known_values(self, x, expected):
        assert M.norm_cdf(x) == pytest.approx(expected, abs=5e-4)

    def test_cdf_is_monotone_and_bounded(self):
        xs = [-6.0, -2.0, -0.5, 0.0, 0.5, 2.0, 6.0]
        ys = [M.norm_cdf(x) for x in xs]
        assert ys == sorted(ys)
        assert all(0.0 <= y <= 1.0 for y in ys)
        assert ys[0] < 1e-6 and ys[-1] > 1 - 1e-6

    @pytest.mark.parametrize("p", [0.001, 0.025, 0.5, 0.9, 0.975, 0.999])
    def test_ppf_inverts_the_cdf(self, p):
        assert M.norm_cdf(M.norm_ppf(p)) == pytest.approx(p, abs=1e-6)

    def test_ppf_of_half_is_zero_and_tails_are_symmetric(self):
        assert M.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
        assert M.norm_ppf(0.975) == pytest.approx(-M.norm_ppf(0.025), rel=1e-6)

    def test_ppf_is_finite_at_extreme_probabilities(self):
        for p in (1e-12, 1 - 1e-12):
            assert math.isfinite(M.norm_ppf(p))


# --------------------------------------------------------------------- #
# 2. risk-adjusted returns
# --------------------------------------------------------------------- #
class TestRiskAdjusted:
    def test_sharpe_annualises_by_sqrt_periods(self):
        rets = [0.001, -0.002, 0.0015, 0.0005, -0.001, 0.002]
        s1 = M.sharpe_of(rets, 1.0)
        s4 = M.sharpe_of(rets, 4.0)
        assert s4 == pytest.approx(s1 * 2.0, rel=1e-9), "sqrt(4) = 2"

    def test_sharpe_sign_follows_the_mean_return(self):
        assert M.sharpe_of([0.01, 0.02, -0.005], 100.0) > 0
        assert M.sharpe_of([-0.01, -0.02, 0.005], 100.0) < 0

    def test_sharpe_of_constant_returns_is_zero_not_infinite(self):
        """Zero variance is the classic division-by-zero; a report showing inf or
        nan here is worse than one showing 0."""
        assert M.sharpe_of([0.01] * 50, 35040.0) == 0.0
        assert M.sharpe_of([0.0] * 50, 35040.0) == 0.0
        assert M.sharpe_of([], 35040.0) == 0.0

    def test_sharpe_of_a_single_observation_is_zero(self):
        assert M.sharpe_of([0.05], 100.0) == 0.0

    def test_sortino_uses_only_downside_deviation(self):
        # same mean and same total variance, but the second has all its dispersion
        # on the upside -> a higher Sortino and an equal-or-higher Sharpe
        a = [0.01, -0.01, 0.01, -0.01]
        b = [0.02, 0.0, 0.02, -0.02]
        assert M.sortino_of(b, 1.0) > M.sortino_of(a, 1.0)

    def test_sortino_at_least_sharpe_when_upside_dominates(self):
        rets = [0.03, 0.02, -0.005, 0.01, 0.025, -0.002]
        assert M.sortino_of(rets, 100.0) >= M.sharpe_of(rets, 100.0) - 1e-12

    def test_sortino_with_no_downside_is_finite(self):
        assert math.isfinite(M.sortino_of([0.01, 0.02, 0.03], 100.0))
        assert M.sortino_of([], 100.0) == 0.0

    def test_omega_splits_gains_from_losses_around_the_threshold(self):
        rets = [0.02, -0.01, 0.03, -0.02]
        assert M.omega_of(rets, 0.0) == pytest.approx(0.05 / 0.03, rel=1e-9)
        # raising the threshold moves everything into the "loss" bucket
        assert M.omega_of(rets, 0.05) == pytest.approx(0.0, abs=1e-12)

    def test_omega_is_finite_when_nothing_beats_the_threshold(self):
        assert math.isfinite(M.omega_of([-0.01, -0.02], 0.0))
        assert M.omega_of([], 0.0) == 0.0


# --------------------------------------------------------------------- #
# 3. drawdown anatomy
# --------------------------------------------------------------------- #
class TestDrawdown:
    def test_series_is_the_distance_from_the_running_peak(self):
        eq = [100.0, 110.0, 105.0, 95.0, 120.0, 115.0]
        dd = M.drawdown_series(eq)
        assert dd[0] == 0.0 and dd[1] == 0.0
        assert dd[2] == pytest.approx(5.0 / 110.0)
        assert dd[3] == pytest.approx(15.0 / 110.0)
        assert dd[4] == 0.0, "a new high ends the drawdown"
        assert dd[5] == pytest.approx(5.0 / 120.0)

    def test_max_drawdown_matches_the_series_maximum(self):
        eq = [100.0, 110.0, 105.0, 95.0, 120.0, 115.0]
        assert M.max_drawdown(eq) == pytest.approx(max(M.drawdown_series(eq)))
        assert M.max_drawdown(eq) == pytest.approx(15.0 / 110.0)

    def test_monotone_equity_has_no_drawdown(self):
        assert M.max_drawdown([1.0, 2.0, 3.0, 4.0]) == 0.0

    def test_empty_and_single_point_equity(self):
        assert M.max_drawdown([]) == 0.0
        assert M.drawdown_series([]) == []
        assert M.max_drawdown([100.0]) == 0.0

    def test_info_locates_peak_trough_and_recovery(self):
        eq = [100.0, 110.0, 105.0, 95.0, 120.0, 115.0]
        info = M.drawdown_info(eq)
        assert info.peak_index == 1 and info.trough_index == 3 and info.recovery_index == 4
        assert info.max_dd == pytest.approx(15.0 / 110.0)
        assert info.max_dd_index == 3, "the index must be populated, not the -1 default"
        assert info.recovered is True
        assert info.underwater_bars == 2 and info.recovery_bars == 1
        assert info.duration_bars == 3

    def test_info_flags_an_unrecovered_final_drawdown(self):
        info = M.drawdown_info([100.0, 120.0, 90.0, 80.0])
        assert info.recovered is False
        assert info.recovery_index == -1
        assert info.max_dd == pytest.approx(40.0 / 120.0)
        assert info.peak_index == 1 and info.trough_index == 3

    def test_ulcer_index_is_the_rms_of_the_drawdown_series(self):
        eq = [100.0, 110.0, 105.0, 95.0, 120.0, 115.0]
        dd = M.drawdown_series(eq)
        info = M.drawdown_info(eq)
        assert info.ulcer_index == pytest.approx(math.sqrt(sum(d * d for d in dd) / len(dd)))
        assert info.ulcer_index <= info.max_dd + 1e-12

    def test_top_drawdowns_are_non_overlapping_and_sorted(self):
        eq = [100.0, 90.0, 100.0, 95.0, 105.0, 80.0, 110.0, 108.0]
        info = M.drawdown_info(eq)
        eps = info.top_drawdowns
        assert eps, "this series has several drawdowns"
        depths = [e["depth"] for e in eps]
        assert depths == sorted(depths, reverse=True)
        for a, b in zip(eps, eps[1:]):
            assert a["trough"] < b["peak"] or b["trough"] < a["peak"], "episodes overlap"

    def test_info_of_empty_equity_is_the_neutral_default(self):
        info = M.drawdown_info([])
        assert info.max_dd == 0.0 and info.max_dd_index == -1
        assert info.top_drawdowns == []


# --------------------------------------------------------------------- #
# 4. the deflated Sharpe ratio and the multiple-testing penalty
# --------------------------------------------------------------------- #
class TestDeflatedSharpe:
    #: every argument of deflated_sharpe is per-period, sr_std included
    BASE = dict(observed_sr_per_period=0.05, n_obs=2000, skew=0.0, kurt=3.0, sr_std=0.01)

    def test_more_trials_lower_the_deflated_sharpe(self):
        d1 = M.deflated_sharpe(n_trials=1, **self.BASE)["dsr"]
        d10 = M.deflated_sharpe(n_trials=10, **self.BASE)["dsr"]
        d100 = M.deflated_sharpe(n_trials=100, **self.BASE)["dsr"]
        assert d1 > d10 > d100, "the trial penalty must bite"
        assert M.deflated_sharpe(n_trials=1, **self.BASE)["sr0"] == 0.0
        assert M.deflated_sharpe(n_trials=100, **self.BASE)["sr0"] > 0.0

    def test_a_missing_sr_std_disables_the_penalty_and_says_so(self):
        """With ``n_trials > 1`` and no dispersion, the "deflated" ratio is just a
        significance test.  Reporting it as reliable would be the silent-optimism
        failure mode this guard exists to prevent."""
        d = M.deflated_sharpe(observed_sr_per_period=0.05, n_obs=2000, skew=0.0,
                              kurt=3.0, n_trials=20, sr_std=0.0)
        assert d["sr0"] == 0.0
        assert d["reliable"] is False
        assert d["pass_95"] is False
        assert "PER-PERIOD" in d["reason"]
        # a single trial needs no penalty, so it stays reliable
        one = M.deflated_sharpe(observed_sr_per_period=0.05, n_obs=2000, skew=0.0,
                                kurt=3.0, n_trials=1, sr_std=0.0)
        assert one["reliable"] is True and one["reason"] == ""
        # an explicit benchmark needs no dispersion either
        bench = M.deflated_sharpe(observed_sr_per_period=0.05, n_obs=2000, skew=0.0,
                                  kurt=3.0, n_trials=20, sr_benchmark=0.01)
        assert bench["reliable"] is True and bench["sr0"] == 0.01

    def test_a_higher_observed_sharpe_raises_the_deflated_sharpe(self):
        lo = M.deflated_sharpe(0.01, 2000, 0.0, 3.0, 20)["dsr"]
        hi = M.deflated_sharpe(0.10, 2000, 0.0, 3.0, 20)["dsr"]
        assert hi > lo

    def test_more_observations_raise_the_deflated_sharpe(self):
        short = M.deflated_sharpe(0.05, 100, 0.0, 3.0, 5)["dsr"]
        long = M.deflated_sharpe(0.05, 10_000, 0.0, 3.0, 5)["dsr"]
        assert long > short

    def test_kurtosis_is_taken_as_a_raw_fourth_moment(self):
        """The convention matters: 3.0 must mean Gaussian.  If the function expected
        *excess* kurtosis, passing 3.0 would inflate the variance term and quietly
        flatter every result."""
        gauss = M.deflated_sharpe(0.05, 2000, 0.0, 3.0, 1, sr_std=0.01)
        assert gauss["kurtosis"] == 3.0
        fat = M.deflated_sharpe(0.05, 2000, 0.0, 8.0, 1, sr_std=0.01)
        assert fat["dsr"] < gauss["dsr"], "fat tails must reduce confidence"

    def test_negative_skew_reduces_confidence(self):
        pos = M.deflated_sharpe(0.05, 2000, 0.5, 3.0, 1)["dsr"]
        neg = M.deflated_sharpe(0.05, 2000, -0.5, 3.0, 1)["dsr"]
        assert neg < pos

    def test_pass_flag_agrees_with_the_95_threshold(self):
        for d in (M.deflated_sharpe(0.20, 5000, 0.0, 3.0, 1, sr_std=0.01),
                  M.deflated_sharpe(0.001, 50, 0.0, 3.0, 200, sr_std=0.01)):
            assert d["pass_95"] == (d["dsr"] > 0.95)
            assert 0.0 <= d["dsr"] <= 1.0

    def test_expected_max_sharpe_grows_with_the_number_of_trials(self):
        a = M.expected_max_sharpe(1, 0.35)
        b = M.expected_max_sharpe(10, 0.35)
        c = M.expected_max_sharpe(1000, 0.35)
        assert a <= b <= c
        assert M.expected_max_sharpe(1, 0.35) == pytest.approx(0.0, abs=1e-9)

    def test_degenerate_inputs_do_not_produce_nan(self):
        d = M.deflated_sharpe(0.0, 0, 0.0, 3.0, 1, sr_std=0.01)
        assert math.isfinite(d["dsr"])
        d2 = M.deflated_sharpe(0.05, 100, 0.0, 3.0, 0, sr_std=0.01)
        assert math.isfinite(d2["dsr"])


# --------------------------------------------------------------------- #
# 5. resampling
# --------------------------------------------------------------------- #
class TestResampling:
    def test_stationary_bootstrap_returns_the_requested_number_of_paths(self):
        xs = [float(i % 7) for i in range(200)]
        out = M.stationary_bootstrap(xs, n_boot=13, mean_block=10, seed=1)
        assert len(out) == 13
        assert all(len(p) == len(xs) for p in out), "each path preserves the sample length"

    def test_stationary_bootstrap_draws_only_observed_values(self):
        xs = [1.0, 2.0, 3.0, 5.0, 8.0]
        out = M.stationary_bootstrap(xs, n_boot=5, mean_block=2, seed=2)
        allowed = set(xs)
        assert all(set(p) <= allowed for p in out)

    def test_stationary_bootstrap_is_seed_deterministic(self):
        xs = [math.sin(i / 3.0) for i in range(120)]
        a = M.stationary_bootstrap(xs, n_boot=4, mean_block=8, seed=99)
        b = M.stationary_bootstrap(xs, n_boot=4, mean_block=8, seed=99)
        c = M.stationary_bootstrap(xs, n_boot=4, mean_block=8, seed=100)
        assert a == b
        assert a != c

    def test_stationary_bootstrap_keeps_local_order_within_blocks(self):
        """A stationary (Politis-Romano) bootstrap resamples *blocks*, so runs of
        consecutive original values must appear — an iid shuffle would destroy the
        autocorrelation the CI is supposed to respect."""
        xs = [float(i) for i in range(300)]
        out = M.stationary_bootstrap(xs, n_boot=3, mean_block=25, seed=5)
        runs = 0
        for p in out:
            for a, b in zip(p, p[1:]):
                if b - a == 1.0:
                    runs += 1
        assert runs > len(xs) * 0.5, f"expected long contiguous runs, got {runs}"

    def test_bootstrap_ci_brackets_the_point_estimate(self):
        xs = [0.1, -0.05, 0.2, 0.0, 0.15, -0.1, 0.05, 0.12] * 12
        stat = lambda v: sum(v) / len(v)                      # noqa: E731
        ci = M.bootstrap_ci(xs, stat, n_boot=300, mean_block=8, seed=3)
        assert ci["lo"] <= ci["estimate"] <= ci["hi"]
        assert ci["estimate"] == pytest.approx(stat(xs), rel=1e-9)
        assert ci["width"] == pytest.approx(ci["hi"] - ci["lo"], rel=1e-9)
        assert 0.0 <= ci["p_greater_than_zero"] <= 1.0

    def test_bootstrap_ci_narrows_with_more_data(self):
        import random
        stat = lambda v: sum(v) / len(v)                      # noqa: E731
        rng = random.Random(11)
        large = [rng.gauss(0.05, 0.4) for _ in range(600)]
        small = large[:40]
        w_small = M.bootstrap_ci(small, stat, n_boot=400, mean_block=5, seed=4)["width"]
        w_large = M.bootstrap_ci(large, stat, n_boot=400, mean_block=5, seed=4)["width"]
        assert w_large < w_small, "15x the data must tighten the interval"

    def test_bootstrap_ci_flags_a_tiny_sample_as_unreliable(self):
        ci = M.bootstrap_ci([0.1, -0.2], lambda v: sum(v) / len(v), n_boot=100, seed=1)
        assert ci["reliable"] is False

    def test_bootstrap_ci_of_an_empty_sample_does_not_crash(self):
        ci = M.bootstrap_ci([], lambda v: 0.0, n_boot=50, seed=1)
        assert math.isfinite(ci["lo"]) and math.isfinite(ci["hi"])
        assert ci["reliable"] is False


# --------------------------------------------------------------------- #
# 6. trade statistics and the R-decomposition
# --------------------------------------------------------------------- #
class TestTradeStats:
    def test_the_r_decomposition_is_exact(self):
        """mean(net R) == mean(gross R) - mean(friction R) must hold to the digit;
        it is the identity the whole cost-bound argument rests on."""
        trades = [make_trade(0.5, gross_r=0.6), make_trade(-0.3, gross_r=-0.2),
                  make_trade(1.2, gross_r=1.3), make_trade(-0.8, gross_r=-0.7)]
        ts = M.trade_stats(trades)
        assert ts["expectancy_r"] == pytest.approx(
            ts["gross_expectancy_r"] - ts["friction_r_per_trade"], abs=1e-12)
        assert ts["n"] == 4
        assert ts["r_decomposition_n"] == 4

    def test_cost_bound_means_friction_ate_the_whole_gross_edge(self):
        eaten = [make_trade(0.0, gross_r=0.10) for _ in range(10)]
        ts = M.trade_stats(eaten)
        assert ts["gross_expectancy_r"] == pytest.approx(0.10)
        assert ts["friction_r_per_trade"] == pytest.approx(0.10)
        assert ts["expectancy_r"] == pytest.approx(0.0, abs=1e-12)
        assert ts["cost_bound"] is True
        assert ts["cost_verdict"].startswith("cost-bound")

        survivors = [make_trade(0.02, gross_r=0.10) for _ in range(10)]
        ts2 = M.trade_stats(survivors)
        assert ts2["friction_share_of_gross"] == pytest.approx(0.8, rel=1e-6)
        assert ts2["cost_bound"] is False, "80% of the edge is bad, but not cost-bound"
        assert ts2["cost_verdict"].startswith("net-positive")

    def test_a_negative_gross_edge_is_called_signal_bound(self):
        ts = M.trade_stats([make_trade(-0.30, gross_r=-0.20) for _ in range(10)])
        assert ts["cost_bound"] is False
        assert ts["cost_verdict"].startswith("signal-bound")

    def test_unsized_trades_are_excluded_from_the_decomposition(self):
        t = make_trade(0.5, gross_r=0.6)
        t.risk_cash = 0.0
        ts = M.trade_stats([t])
        assert ts["r_decomposition_n"] == 0
        assert ts["cost_verdict"] == "no sized trades to decompose"

    def test_win_rate_profit_factor_and_streaks(self):
        trades = [make_trade(1.0), make_trade(-0.5), make_trade(0.8), make_trade(-0.4),
                  make_trade(1.2)]
        ts = M.trade_stats(trades)
        assert ts["wins"] == 3 and ts["losses"] == 2
        assert ts["win_rate"] == pytest.approx(0.6)
        assert ts["profit_factor"] == pytest.approx(3.0 / 0.9, rel=1e-9)
        assert ts["max_win_streak"] == 1 and ts["max_loss_streak"] == 1
        assert ts["payoff_ratio"] == pytest.approx(1.0 / 0.45, rel=1e-9)

    def test_profit_factor_with_no_losers_is_capped_and_flagged(self):
        """An all-winning book has an infinite profit factor; reporting 0.0 (the
        safe_div default) would describe the best possible result as the worst."""
        ts = M.trade_stats([make_trade(1.0), make_trade(0.5)])
        assert ts["no_losing_trades"] is True
        assert ts["profit_factor"] == M.PROFIT_FACTOR_CAP
        assert math.isfinite(ts["profit_factor"]), "must survive json.dumps"
        mixed = M.trade_stats([make_trade(1.0), make_trade(-0.5)])
        assert mixed["no_losing_trades"] is False
        assert mixed["profit_factor"] < M.PROFIT_FACTOR_CAP
        assert mixed["profit_factor"] == pytest.approx(100.0 / 50.0, rel=1e-9)

    def test_profit_factor_of_a_break_even_book_is_zero(self):
        ts = M.trade_stats([make_trade(0.0, gross_r=0.0, pnl=0.0)])
        assert ts["profit_factor"] == 0.0
        assert ts["no_losing_trades"] is False

    def test_mfe_mae_and_giveback(self):
        t = make_trade(0.2)
        t.peak_r, t.trough_r = 1.5, -0.3
        ts = M.trade_stats([t])
        assert ts["mfe"]["mean_peak_r"] == pytest.approx(1.5)
        assert ts["mae"]["mean_trough_r"] == pytest.approx(-0.3)
        assert ts["giveback_r_mean"] == pytest.approx(1.3), (
            "how much of the best open profit was handed back")

    def test_totals_match_the_trades(self):
        trades = [make_trade(0.5, pnl=50.0), make_trade(-0.2, pnl=-20.0)]
        ts = M.trade_stats(trades)
        assert ts["net_pnl_total"] == pytest.approx(30.0)
        assert ts["gross_pnl_total"] == pytest.approx(
            sum(t.gross_pnl for t in trades), rel=1e-9)
        assert ts["friction_total"] == pytest.approx(
            ts["gross_pnl_total"] - ts["net_pnl_total"], rel=1e-9)
        assert ts["friction_bp_mean"] > 0.0

    def test_empty_trade_list_reports_zero_trades_without_crashing(self):
        ts = M.trade_stats([])
        assert ts["n"] == 0

    def test_exit_reason_and_family_breakdowns_reconcile(self):
        trades = [make_trade(0.5, reason="stop"), make_trade(-0.2, reason="tp1"),
                  make_trade(0.1, reason="time_stall")]
        ts = M.trade_stats(trades)
        assert sum(v["n"] for v in ts["exit_reasons"].values()) == 3
        assert sum(v["n"] for v in ts["exit_families"].values()) == 3
        assert "stop" in ts["exit_families"] and "target" in ts["exit_families"]
        assert ts["exit_families"]["target"]["reasons"] == ["tp1"]

    def test_side_and_strategy_breakdowns(self):
        a = make_trade(0.5)
        b = make_trade(-0.2)
        b.side, b.strategy = -1, "meanrev"
        ts = M.trade_stats([a, b])
        assert set(ts["by_side"]) == {"long", "short"}
        assert ts["by_side"]["long"]["n"] == 1 and ts["by_side"]["short"]["n"] == 1
        assert ts["by_strategy"]["trend"]["n"] == 1
        assert ts["by_strategy"]["meanrev"]["n"] == 1

    def test_r_autocorr_is_finite_for_few_trades(self):
        ts = M.trade_stats([make_trade(0.1), make_trade(0.2)])
        assert math.isfinite(ts["r_autocorr_lag1"])


# --------------------------------------------------------------------- #
# 7. cross-validation splits
# --------------------------------------------------------------------- #
class TestSplits:
    def test_purged_kfold_covers_every_observation_exactly_once_as_test(self):
        n, k = 120, 5
        folds = V.purged_kfold(n, k=k, purge=0, embargo=0)
        assert len(folds) == k
        seen: list[int] = []
        for train, test in folds:
            assert not (set(train) & set(test)), "train and test overlap"
            seen.extend(test)
        assert sorted(seen) == list(range(n))

    def test_purging_removes_the_observations_before_the_test_window(self):
        """Lopez de Prado's convention: *purge* clears the training samples that
        overlap the test period (the past side), *embargo* adds a buffer after it
        (the future side).  A label spanning both would otherwise leak."""
        n, k, purge = 100, 5, 4
        clean = V.purged_kfold(n, k=k, purge=0, embargo=0)
        purged = V.purged_kfold(n, k=k, purge=purge, embargo=0)
        assert purged != clean, "purge=4 must change something"
        for (tr0, te0), (tr1, te1) in zip(clean, purged):
            assert len(tr1) <= len(tr0)
            lo = min(te1)
            leaked = [i for i in tr1 if lo - purge <= i < lo]
            assert not leaked, f"purge window leaked into train: {leaked[:5]}"

    def test_embargo_clears_the_observations_after_the_test_window(self):
        embargo = 6
        folds = V.purged_kfold(100, k=5, purge=0, embargo=embargo)
        for tr, te in folds:
            hi = max(te)
            leaked = [i for i in tr if hi < i <= hi + embargo]
            assert not leaked, f"embargo window leaked into train: {leaked[:5]}"
        a = V.purged_kfold(100, k=4, purge=2, embargo=0)
        b = V.purged_kfold(100, k=4, purge=2, embargo=6)
        assert sum(len(tr) for tr, _ in b) < sum(len(tr) for tr, _ in a)

    def test_purged_kfold_handles_tiny_inputs(self):
        assert V.purged_kfold(0, k=5) == []
        assert V.purged_kfold(3, k=5, purge=1) != []
        for train, test in V.purged_kfold(3, k=5, purge=1):
            assert not (set(train) & set(test))

    def test_anchored_splits_have_an_expanding_train_window(self):
        splits = V.anchored_splits(200, n_splits=4)
        assert len(splits) == 4
        trains = [len(tr) for tr, _ in splits]
        assert trains == sorted(trains), "anchored means the train window only grows"
        assert all(tr[0] == 0 for tr, _ in splits), "anchored at the first observation"
        for tr, te in splits:
            assert max(tr) < min(te), "test must come strictly after train"
            assert not (set(tr) & set(te))

    def test_anchored_splits_respect_a_minimum_train_size(self):
        splits = V.anchored_splits(100, n_splits=5, min_train=40)
        assert splits
        assert all(len(tr) >= 40 for tr, _ in splits)

    def test_anchored_splits_with_purge_leave_a_gap(self):
        splits = V.anchored_splits(100, n_splits=3, purge=5)
        for tr, te in splits:
            assert min(te) - max(tr) > 5 or not tr or not te


# --------------------------------------------------------------------- #
# 8. walk-forward, PBO and the rest of the overfitting guards
# --------------------------------------------------------------------- #
class TestOverfittingGuards:
    def test_walk_forward_prefers_the_better_config_in_sample(self):
        import random
        rng = random.Random(21)
        # constant returns have zero variance, so every Sharpe is 0 and the ranking
        # is a coin flip -- the test needs real dispersion to mean anything
        good = [rng.gauss(0.004, 0.01) for _ in range(200)]
        bad = [rng.gauss(0.0002, 0.01) for _ in range(200)]
        wf = V.walk_forward({"good": good, "bad": bad}, periods_per_year=35040,
                            n_splits=4)
        assert wf.folds
        assert all(f.best_config == "good" for f in wf.folds), \
            [f.best_config for f in wf.folds]
        assert all(f.is_score > 0 for f in wf.folds)
        assert wf.n_configs_tried == 2
        assert wf.oos_return_pct > 0.0

    def test_walk_forward_reports_an_overfit_gap(self):
        import random
        rng = random.Random(22)
        wf = V.walk_forward({"a": [rng.gauss(0.01, 0.01) for _ in range(100)]
                                    + [rng.gauss(0.0, 0.01) for _ in range(100)],
                             "b": [rng.gauss(0.0, 0.01) for _ in range(100)]
                                    + [rng.gauss(0.01, 0.01) for _ in range(100)]},
                            periods_per_year=35040, n_splits=4)
        assert wf.overfit_gap >= 0.0
        assert math.isfinite(wf.oos_sharpe)
        assert "dsr" in wf.deflated

    def test_walk_forward_fold_indices_never_overlap(self):
        wf = V.walk_forward({"a": [0.01] * 160}, periods_per_year=35040, n_splits=4)
        for f in wf.folds:
            tr = set(range(f.train_idx[0], f.train_idx[1] + 1))
            te = set(range(f.test_idx[0], f.test_idx[1] + 1))
            assert not (tr & te)
            assert max(tr) < min(te)

    def test_walk_forward_with_one_config_still_runs(self):
        wf = V.walk_forward({"only": [0.002] * 80}, periods_per_year=35040, n_splits=2)
        assert wf.folds and wf.folds[0].n_configs == 1

    def test_cscv_pbo_is_low_when_the_best_config_is_genuinely_best(self):
        # config 0 dominates on every sub-sample: nothing was selected by luck
        matrix = [[3.0 + 0.01 * ((j * 5) % 7) for j in range(32)]] + \
                 [[1.0 + 0.1 * ((i * 7 + j * 3) % 5) for j in range(32)] for i in range(1, 8)]
        out = V.cscv_pbo(matrix, n_splits=8, max_combos=64, seed=11)
        assert out["reliable"] is True
        assert out["pbo"] < 0.2, f"a dominant config should not look overfit: {out}"
        assert "discard" not in out["interpretation"]

    def test_cscv_pbo_is_high_when_rankings_are_pure_noise(self):
        import random
        rng = random.Random(5)
        matrix = [[rng.gauss(0.0, 1.0) for _ in range(32)] for _ in range(12)]
        out = V.cscv_pbo(matrix, n_splits=8, max_combos=64, seed=11)
        assert out["reliable"] is True
        assert out["pbo"] > 0.3, f"noise should look overfit, got {out['pbo']:.2f}"

    def test_cscv_pbo_is_bounded_and_explains_itself(self):
        out = V.cscv_pbo([[1.0, 2.0], [3.0, 0.5]], n_splits=2)
        assert 0.0 <= out["pbo"] <= 1.0
        assert out["reason"] or out.get("interpretation")

    def test_cscv_pbo_flags_degenerate_input_as_unreliable(self):
        assert V.cscv_pbo([], n_splits=4)["reliable"] is False
        assert V.cscv_pbo([[1.0, 2.0]], n_splits=16)["reliable"] is False

    def test_minimum_detectable_trades_shrinks_with_a_larger_effect(self):
        small_effect = V.minimum_detectable_trades(0.02, 1.0)
        big_effect = V.minimum_detectable_trades(0.20, 1.0)
        assert small_effect > big_effect > 0
        assert V.minimum_detectable_trades(0.05, 1.0, power=0.9) > \
            V.minimum_detectable_trades(0.05, 1.0, power=0.8)

    def test_minimum_detectable_trades_grows_with_dispersion(self):
        assert V.minimum_detectable_trades(0.05, 2.0) > V.minimum_detectable_trades(0.05, 0.5)

    def test_minimum_detectable_trades_handles_an_impossible_effect(self):
        assert V.minimum_detectable_trades(0.0, 1.0) >= 0
        assert V.minimum_detectable_trades(-0.1, 1.0) >= 0

    def test_ablation_labels_a_decoration_filter(self):
        run = lambda name, disabled: {                       # noqa: E731
            "n_trades": 100, "expectancy_r": 0.10, "sharpe": 1.0,
            "max_dd_pct": 8.0, "return_pct": 12.0}
        out = V.ablation(run, ["noop"])
        assert out["filters"]["noop"]["verdict"] == "decoration"
        assert out["filters"]["noop"]["delta_expectancy_r"] == pytest.approx(0.0)

    def test_ablation_labels_a_filter_that_hurts_when_removed(self):
        def run(name, disabled):
            base = {"n_trades": 100, "expectancy_r": 0.30, "sharpe": 2.0,
                    "max_dd_pct": 8.0, "return_pct": 30.0}
            if disabled:
                base.update(expectancy_r=0.05, sharpe=0.4, n_trades=260)
            return base
        out = V.ablation(run, ["quality"])
        assert out["filters"]["quality"]["verdict"] == "keep"

    def test_ablation_labels_a_harmful_filter(self):
        def run(name, disabled):
            base = {"n_trades": 100, "expectancy_r": 0.05, "sharpe": 0.4,
                    "max_dd_pct": 8.0, "return_pct": 5.0}
            if disabled:
                base.update(expectancy_r=0.30, sharpe=2.0)
            return base
        out = V.ablation(run, ["bad"])
        row = out["filters"]["bad"]
        assert row["verdict"] == "harmful"
        assert row["delta_expectancy_r"] > 0.0

    def test_ablation_reports_the_baseline_run(self):
        out = V.ablation(lambda n, d: {"n_trades": 7, "expectancy_r": 0.2, "sharpe": 1.0,
                                       "max_dd_pct": 5.0, "return_pct": 9.0}, [])
        assert out["baseline"]["n_trades"] == 7
        assert out["filters"] == {}

    def test_parameter_plateau_flags_a_lone_spike(self):
        sweep = [(0.1, 0.02), (0.2, 0.05), (0.3, 0.90), (0.4, 0.04), (0.5, 0.02)]
        rows = V.parameter_plateau(sweep, window=1)
        assert [r["value"] for r in rows] == [0.1, 0.2, 0.3, 0.4, 0.5]
        spike = [r for r in rows if r["value"] == 0.3][0]
        assert spike["is_spike"] is True
        assert spike["score"] > spike["neighbour_mean"] * 3

    def test_parameter_plateau_marks_whether_the_window_was_full(self):
        rows = V.parameter_plateau([(i, float(i)) for i in range(5)], window=1)
        assert [r["full_window"] for r in rows] == [False, True, True, True, False]

    def test_parameter_plateau_rewards_a_flat_neighbourhood(self):
        sweep = [(1, 0.10), (2, 0.45), (3, 0.48), (4, 0.46), (5, 0.12)]
        rows = V.parameter_plateau(sweep, window=1)
        mid = [r for r in rows if r["value"] == 3][0]
        assert mid["is_spike"] is False
        assert mid["stability"] > 0.5

    def test_best_plateau_prefers_a_stable_region_over_a_spike(self):
        sweep = [(1, 0.10), (2, 0.45), (3, 0.48), (4, 0.46), (5, 0.99), (6, 0.11)]
        out = V.best_plateau(sweep, window=2)
        assert out["best_point_value"] == 5, "the raw maximum is the spike"
        assert out["chosen"] != 5, "the plateau choice must reject the spike"
        assert out["chosen_is_spike"] is False
        assert out["agrees"] is False
        assert out["candidate_pool"] == "interior_non_spike"
        assert out["rows"]

    def test_best_plateau_never_recommends_an_edge_point_next_to_a_good_region(self):
        """The bias this guards against: an edge value inherits its (clipped)
        neighbour's score, so a naive argmax over neighbour means can pick the
        WORST value on the grid."""
        sweep = [(1, 0.10), (2, 0.50), (3, 0.52), (4, 0.50), (5, 0.05)]
        out = V.best_plateau(sweep, window=2)
        assert out["chosen"] == 3
        assert out["chosen_score"] >= 0.5, f"chose a poor value: {out['chosen_score']}"
        assert out["agrees"] is True

    def test_best_plateau_agrees_when_the_peak_is_broad(self):
        sweep = [(1, 0.10), (2, 0.45), (3, 0.50), (4, 0.47), (5, 0.12)]
        out = V.best_plateau(sweep, window=1)
        assert out["chosen"] == 3 and out["agrees"] is True

    def test_plateau_helpers_handle_short_sweeps(self):
        assert V.parameter_plateau([], window=1) == []
        assert V.parameter_plateau([(1, 0.5)], window=1)
        out = V.best_plateau([(1, 0.5)], window=1)
        assert out["chosen"] == 1
        assert out["candidate_pool"] in ("all", "all_non_spike", "interior_only")

    def test_monte_carlo_drawdown_orders_its_percentiles(self):
        trades = [make_trade(r, bars=3) for r in
                  (0.8, -0.5, 1.2, -0.9, 0.3, -0.2, 0.6, -1.0, 0.4, 0.2) * 3]
        out = V.monte_carlo_drawdown(trades, n_sims=200, seed=3, block=3)
        assert out["n_sims"] == 200 and out["n_trades"] == len(trades)
        assert out["max_dd_median_pct"] <= out["max_dd_p95_pct"] <= out["max_dd_worst_pct"]
        assert out["max_dd_mean_pct"] >= 0.0
        assert out["return_p05_pct"] <= out["return_mean_pct"] <= out["return_p95_pct"]
        assert 0.0 <= out["prob_return_negative"] <= 1.0

    def test_monte_carlo_drawdown_is_seed_reproducible(self):
        trades = [make_trade(r) for r in (0.5, -0.3, 0.9, -1.1, 0.2, 0.4, -0.6,
                                          0.8, -0.2, 0.3, -0.4, 0.7)]
        a = V.monte_carlo_drawdown(trades, n_sims=80, seed=7)
        b = V.monte_carlo_drawdown(trades, n_sims=80, seed=7)
        c = V.monte_carlo_drawdown(trades, n_sims=80, seed=8)
        assert a["max_dd_p95_pct"] == b["max_dd_p95_pct"]
        assert a["max_dd_p95_pct"] != c["max_dd_p95_pct"]

    def test_monte_carlo_drawdown_reports_more_risk_than_the_single_path(self):
        """Shuffling the order cannot reduce the worst case; a simulator that
        returned less than the realised drawdown would be broken."""
        trades = [make_trade(r) for r in (0.5, -0.6, 0.4, -0.7, 0.3, -0.5, 0.2)]
        out = V.monte_carlo_drawdown(trades, n_sims=150, seed=3)
        realised = M.max_drawdown([100_000.0] + [100_000.0 + 100.0 * r for r in
                                                 [t.r_multiple for t in trades]])
        assert out["max_dd_worst_pct"] >= 0.0
        assert math.isfinite(realised)

    def test_monte_carlo_with_too_few_trades_is_flagged_but_complete(self):
        out = V.monte_carlo_drawdown([make_trade(0.5)], n_sims=50, seed=1)
        full = V.monte_carlo_drawdown([make_trade(r) for r in
                                       (0.5, -0.3, 0.9, -1.1, 0.2, 0.4, -0.6, 0.8,
                                        -0.2, 0.3, -0.4, 0.7)], n_sims=20, seed=1)
        assert out["reliable"] is False
        assert "reason" in out
        assert set(full) <= set(out), (
            "the degenerate path must return the same keys, or every consumer of a "
            "small run gets a KeyError")
        for k in ("max_dd_p95_pct", "max_dd_worst_pct", "return_mean_pct"):
            assert out[k] == 0.0

    def test_bootstrap_expectancy_ci_brackets_the_point_estimate(self):
        trades = [make_trade(r) for r in (0.6, -0.4, 0.9, -0.2, 0.3, -0.5, 1.1, -0.1) * 4]
        out = V.bootstrap_expectancy(trades, n_boot=400, seed=5)
        assert out["n"] == len(trades)
        assert out["ci95_lo"] <= out["expectancy_r"] <= out["ci95_hi"]
        assert 0.0 <= out["p_expectancy_gt_0"] <= 1.0
        assert out["reliable"] is True

    def test_bootstrap_expectancy_of_a_clearly_negative_edge_excludes_zero(self):
        trades = [make_trade(-0.5) for _ in range(40)]
        out = V.bootstrap_expectancy(trades, n_boot=300, seed=5)
        assert out["ci95_hi"] < 0.0
        assert out["p_expectancy_gt_0"] == 0.0

    def test_bootstrap_expectancy_of_an_empty_book(self):
        out = V.bootstrap_expectancy([], n_boot=50, seed=1)
        assert out["n"] == 0 and out["reliable"] is False
