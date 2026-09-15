"""Performance statistics — and the guards that stop them lying to you.

A backtest report is only useful if the reader can tell a real edge from a lucky
sample.  Every headline number here therefore ships with either a confidence
interval or an explicit overfitting adjustment:

* **Stationary bootstrap** (Politis & Romano) confidence intervals on Sharpe and
  max drawdown.  Block resampling, not iid, because trade returns are
  autocorrelated — iid bootstrap understates the interval by a wide margin.
* **Deflated Sharpe Ratio** (Bailey & López de Prado).  Shrinks the observed
  Sharpe by the number of configurations actually tried, and corrects for the
  skew/kurtosis of the return distribution.  A Sharpe of 1.6 found after 200
  trials is not a Sharpe of 1.6.
* **Trade-level autocorrelation and streak analysis**, because a run of winners
  clustered in one regime is a different object from the same wins spread evenly.
* **MFE/MAE capture**, which separates "the entry found the move" from "the exit
  kept it".  These fail independently and the fix is different for each.

Conventions
-----------
Risk-free rate is 0 and this is stated rather than hidden.  Sharpe is annualised
with ``sqrt(periods_per_year)`` derived from the traded timeframe, so numbers from
different timeframes are comparable.  Drawdown is a fraction of the running peak.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .mathx import (EPS, clamp, cvar, kurtosis, mean, median, percentile,
                    safe_div, skewness, stdev, autocorr, var_quantile)
from .portfolio import EquityPoint, Trade

# Euler–Mascheroni constant, used by the Deflated Sharpe Ratio
GAMMA_E = 0.5772156649015329
_SQRT_2 = math.sqrt(2.0)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |err|<1.15e-9)."""
    p = clamp(p, 1e-12, 1.0 - 1e-12)
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# --------------------------------------------------------------------------- #
# drawdown
# --------------------------------------------------------------------------- #
def drawdown_series(equity: Sequence[float]) -> list[float]:
    """Fraction below the running peak, >= 0."""
    out: list[float] = []
    peak = -math.inf
    for v in equity:
        peak = max(peak, v)
        out.append(max(0.0, (peak - v) / peak) if peak > 0 else 0.0)
    return out


def max_drawdown(equity: Sequence[float]) -> float:
    dd = drawdown_series(equity)
    return max(dd) if dd else 0.0


@dataclass(slots=True)
class DrawdownInfo:
    max_dd: float = 0.0
    max_dd_index: int = -1
    peak_index: int = -1
    trough_index: int = -1
    recovery_index: int = -1
    duration_bars: int = 0        # peak -> recovery
    underwater_bars: int = 0      # peak -> trough
    recovery_bars: int = -1       # trough -> recovery (-1 = never recovered)
    recovered: bool = False
    ulcer_index: float = 0.0
    top_drawdowns: list[dict[str, Any]] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_drawdown": self.max_dd,
            "max_drawdown_pct": self.max_dd * 100.0,
            "peak_index": self.peak_index,
            "trough_index": self.trough_index,
            "recovery_index": self.recovery_index,
            "duration_bars": self.duration_bars,
            "underwater_bars": self.underwater_bars,
            "recovery_bars": self.recovery_bars,
            "recovered": self.recovered,
            "ulcer_index": self.ulcer_index,
            "top_drawdowns": self.top_drawdowns or [],
        }


def drawdown_info(equity: Sequence[float]) -> DrawdownInfo:
    """Full drawdown anatomy, plus the largest non-overlapping drawdowns.

    Duration and recovery are reported separately because they mean different
    things operationally: ``underwater_bars`` is how long the strategy hurts,
    ``recovery_bars`` is how long until it is whole again.  A strategy with a
    12% drawdown that recovers in 40 bars is a different animal from one with the
    same 12% that takes 900 bars.
    """
    info = DrawdownInfo(top_drawdowns=[])
    n = len(equity)
    if n == 0:
        return info
    dd = drawdown_series(equity)
    info.max_dd = max(dd)
    # without this the field keeps its -1 default and quietly claims "not found"
    # on every run, even though max_dd right above it was located
    info.max_dd_index = dd.index(info.max_dd)
    info.ulcer_index = math.sqrt(mean([d * d for d in dd]))

    # episodes: peak -> trough -> recovery
    episodes: list[dict[str, Any]] = []
    peak_i = 0
    in_dd = False
    trough_i = 0
    for i in range(n):
        if dd[i] > 0:
            if not in_dd:
                in_dd = True
                peak_i = i - 1 if i > 0 else 0
                trough_i = i
            elif dd[i] > dd[trough_i]:
                trough_i = i
        else:
            if in_dd:
                episodes.append({"peak": peak_i, "trough": trough_i, "recovery": i,
                                 "depth": dd[trough_i],
                                 "underwater": trough_i - peak_i,
                                 "recovery_bars": i - trough_i,
                                 "duration": i - peak_i})
                in_dd = False
    if in_dd:
        episodes.append({"peak": peak_i, "trough": trough_i, "recovery": -1,
                         "depth": dd[trough_i], "underwater": trough_i - peak_i,
                         "recovery_bars": -1, "duration": n - 1 - peak_i})

    if episodes:
        worst = max(episodes, key=lambda e: e["depth"])
        info.peak_index = worst["peak"]
        info.trough_index = worst["trough"]
        info.recovery_index = worst["recovery"]
        info.duration_bars = worst["duration"]
        info.underwater_bars = worst["underwater"]
        info.recovery_bars = worst["recovery_bars"]
        info.recovered = worst["recovery"] >= 0
        # largest non-overlapping episodes by depth
        ordered = sorted(episodes, key=lambda e: -e["depth"])
        kept: list[dict[str, Any]] = []
        for e in ordered:
            if any(not (e["peak"] > k["recovery"] if k["recovery"] >= 0
                        else e["peak"] > k["trough"])
                   and not (k["peak"] > e["recovery"] if e["recovery"] >= 0
                            else k["peak"] > e["trough"]) for k in kept):
                continue
            kept.append(e)
            if len(kept) >= 5:
                break
        info.top_drawdowns = kept
    return info


# --------------------------------------------------------------------------- #
# bootstrap
# --------------------------------------------------------------------------- #
def stationary_bootstrap(xs: Sequence[float], n_boot: int = 500,
                         mean_block: int = 20, seed: int = 7) -> list[list[float]]:
    """Politis–Romano stationary bootstrap.

    Block lengths are geometric (so the resampled series stays stationary) and the
    index wraps around.  Use this rather than an iid bootstrap whenever the
    statistic depends on the *ordering* of returns — Sharpe of a trend strategy,
    drawdown depth, and any streak statistic all do.
    """
    n = len(xs)
    if n == 0:
        return []
    rng = random.Random(seed)
    p = 1.0 / max(1, mean_block)
    out: list[list[float]] = []
    for _ in range(n_boot):
        sample: list[float] = []
        idx = rng.randrange(n)
        while len(sample) < n:
            sample.append(xs[idx])
            idx = (idx + 1) % n
            if rng.random() < p:
                idx = rng.randrange(n)
        out.append(sample)
    return out


def bootstrap_ci(xs: Sequence[float], stat: Callable[[Sequence[float]], float],
                 n_boot: int = 500, mean_block: int = 20, seed: int = 7,
                 alpha: float = 0.05) -> dict[str, float]:
    """Percentile bootstrap CI of ``stat``.  Returns point estimate + interval."""
    point = stat(xs)
    if len(xs) < 20:
        return {"estimate": point, "lo": point, "hi": point, "n_boot": 0,
                "width": 0.0, "reliable": False}
    boots = stationary_bootstrap(xs, n_boot=n_boot, mean_block=mean_block, seed=seed)
    vals = sorted(stat(b) for b in boots)
    lo = percentile(vals, alpha / 2.0 * 100.0)
    hi = percentile(vals, (1.0 - alpha / 2.0) * 100.0)
    return {
        "estimate": point, "lo": lo, "hi": hi, "n_boot": len(vals),
        "width": hi - lo, "reliable": True,
        "p_greater_than_zero": safe_div(sum(1 for v in vals if v > 0), len(vals), 0.0),
    }


def sharpe_of(returns: Sequence[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    mu = mean(returns)
    sd = stdev(returns)
    if sd <= EPS:
        return 0.0
    return (mu / sd) * math.sqrt(max(periods_per_year, 1.0))


def sortino_of(returns: Sequence[float], periods_per_year: float,
               mar: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [min(r - mar, 0.0) for r in returns]
    dsd = math.sqrt(mean([d * d for d in downside]))
    if dsd <= EPS:
        return 0.0
    return ((mean(returns) - mar) / dsd) * math.sqrt(max(periods_per_year, 1.0))


def omega_of(returns: Sequence[float], threshold: float = 0.0) -> float:
    gains = sum(max(r - threshold, 0.0) for r in returns)
    losses = sum(max(threshold - r, 0.0) for r in returns)
    if losses <= EPS:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


# --------------------------------------------------------------------------- #
# deflated Sharpe ratio
# --------------------------------------------------------------------------- #
def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """Expected maximum Sharpe across ``n_trials`` independent attempts.

    This is the benchmark the observed Sharpe must beat.  It grows like
    ``sqrt(2 ln N)`` — which is why trying 100 parameter sets and reporting the
    best is not the same as having one strategy.
    """
    if n_trials <= 1 or sr_std <= EPS:
        return 0.0
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return sr_std * ((1.0 - GAMMA_E) * z1 + GAMMA_E * z2)


def deflated_sharpe(observed_sr_per_period: float, n_obs: int, skew: float,
                    kurt: float, n_trials: int, sr_std: float = 0.0,
                    sr_benchmark: float | None = None) -> dict[str, float]:
    """Bailey & López de Prado's Deflated Sharpe Ratio.

    ``observed_sr_per_period`` must be the *non-annualised* per-period Sharpe,
    because the skew/kurtosis correction is derived in per-period units.
    ``kurt`` is the **non-excess** kurtosis (3.0 for a normal distribution).

    **Every argument is in per-period units**, including ``sr_std``: the
    cross-sectional standard deviation of the Sharpe ratios of the ``n_trials``
    configurations that were tried, measured on the same period as
    ``observed_sr_per_period``.  The 0.35 figure quoted in the original paper is
    an *annualised* dispersion, so a caller working on 15-minute bars must pass
    ``0.35 / sqrt(periods_per_year)`` — passing it raw makes the benchmark
    ``sr0`` ~200x too large and drives every DSR to exactly 0, which looks like a
    verdict but is only a units error.  :func:`summarise` and
    :func:`engine.validation.walk_forward` do that conversion for you.

    ``sr_std=0`` (the default) means "no dispersion information", which disables
    the trial penalty: with ``n_trials > 1`` the result is then flagged
    ``reliable=False`` rather than reported as if it had been deflated.

    Returns the probability that the true Sharpe exceeds the expected maximum
    Sharpe of ``n_trials`` attempts.  Below ~0.95 the result should be treated as
    unproven, regardless of how good the equity curve looks.
    """
    disabled_penalty = (n_trials > 1 and sr_std <= EPS and sr_benchmark is None)
    if n_obs < 3:
        return {"dsr": 0.0, "sr0": 0.0, "sr_std": sr_std, "reliable": False,
                "reason": f"only {n_obs} observations; need >= 3", "n_obs": n_obs}
    sr0 = sr_benchmark if sr_benchmark is not None else expected_max_sharpe(n_trials, sr_std)
    denom = math.sqrt(
        max(1e-12, 1.0 - skew * observed_sr_per_period
            + ((kurt - 1.0) / 4.0) * observed_sr_per_period ** 2)
    )
    z = ((observed_sr_per_period - sr0) * math.sqrt(max(1, n_obs - 1))) / denom
    return {
        "dsr": norm_cdf(z),
        "sr0": sr0,
        "sr_observed": observed_sr_per_period,
        "n_obs": n_obs,
        "n_trials": n_trials,
        "sr_std": sr_std,
        "skew": skew,
        "kurtosis": kurt,
        "reliable": not disabled_penalty,
        "reason": ("n_trials > 1 but sr_std == 0: the multiple-testing penalty is "
                   "disabled, so this is an ordinary significance test, not a "
                   "deflated one. Pass the cross-sectional std of the trial "
                   "Sharpers in PER-PERIOD units." if disabled_penalty else ""),
        "pass_95": norm_cdf(z) >= 0.95 and not disabled_penalty,
    }


# --------------------------------------------------------------------------- #
# trade-level analytics
# --------------------------------------------------------------------------- #
#: A profit factor with no losing trades is mathematically infinite.  Reports are
#: serialised to JSON, where ``Infinity`` is not valid, so the value is capped and
#: the situation is flagged separately.  Returning 0.0 (the ``safe_div`` default)
#: instead would report the best possible book as the worst.
PROFIT_FACTOR_CAP = 999.0


def profit_factor(gross_win: float, gross_loss: float) -> float:
    """Win gross over loss gross, capped when there are no losses at all."""
    if gross_loss <= 0.0:
        return PROFIT_FACTOR_CAP if gross_win > 0.0 else 0.0
    return gross_win / gross_loss


def trade_stats(trades: Sequence[Trade]) -> dict[str, Any]:
    """Everything worth knowing about the trades themselves."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "note": "no trades executed"}
    rs = [t.r_multiple for t in trades]
    nets = [t.net_pnl for t in trades]
    gross = [t.gross_pnl for t in trades]
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    w_rs = [t.r_multiple for t in wins]
    l_rs = [t.r_multiple for t in losses]

    gross_win = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))
    payoff = safe_div(mean(w_rs), abs(mean(l_rs)), 0.0) if w_rs and l_rs else 0.0

    # streaks
    max_win_streak = max_loss_streak = cur_w = cur_l = 0
    for t in trades:
        if t.net_pnl > 0:
            cur_w += 1
            cur_l = 0
            max_win_streak = max(max_win_streak, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_loss_streak = max(max_loss_streak, cur_l)

    # MFE/MAE capture — does the exit keep what the entry found?
    peaks = [t.peak_r for t in trades]
    troughs = [t.trough_r for t in trades]
    # Only trades that actually went somewhere can have a meaningful capture
    # ratio: with peak_r near zero the ratio explodes (r=-0.8 / peak=0.11 = -7)
    # and the mean ends up describing arithmetic, not exits.
    captured = [safe_div(t.r_multiple, t.peak_r, 0.0) for t in trades if t.peak_r >= 0.5]
    captured_all = [safe_div(t.r_multiple, t.peak_r, 0.0) for t in trades if t.peak_r > 0.1]

    friction = [t.costs for t in trades]
    gross_total = sum(gross)
    net_total = sum(nets)

    # ---- scale-free cost decomposition ------------------------------------
    # Every trade carries ``gross_pnl`` (reference prices, before fees) and
    # ``costs``, and ``net_pnl == gross_pnl - costs`` holds exactly, so the
    # expectancy splits with no residual:
    #
    #     mean(net R) == mean(gross R) - mean(friction R)
    #
    # R units (not cash, not bp) are what make this comparable across stop widths
    # and position sizes, and the comparison decides where effort should go next:
    # when friction R >= gross R the strategy is *cost*-bound and no change to the
    # filters can help — only geometry (wider stops make R bigger relative to the
    # same bp cost), fewer fee-paying legs, or resting orders.
    sized = [t for t in trades if t.risk_cash > 0]
    gross_r = [safe_div(t.gross_pnl, t.risk_cash, 0.0) for t in sized]
    fric_r = [safe_div(t.costs, t.risk_cash, 0.0) for t in sized]
    gross_expectancy_r = mean(gross_r) if gross_r else 0.0
    friction_r_per_trade = mean(fric_r) if fric_r else 0.0
    # "cost-bound" means friction ate an edge that was there.  Without the
    # positive-gross condition a strategy losing money BEFORE costs also satisfies
    # friction >= gross, and the flag then contradicts its own verdict string.
    cost_bound = bool(gross_r) and gross_expectancy_r > 0.0 \
        and friction_r_per_trade >= gross_expectancy_r

    if not gross_r:
        cost_verdict = "no sized trades to decompose"
    elif gross_expectancy_r <= 0.0:
        cost_verdict = (f"signal-bound: gross expectancy is {gross_expectancy_r:+.3f}R "
                        f"before costs, so cost engineering cannot rescue it")
    elif cost_bound:
        cost_verdict = (f"cost-bound: friction {friction_r_per_trade:.3f}R/trade >= "
                        f"gross edge {gross_expectancy_r:+.3f}R/trade; widen stops, "
                        f"cut exit legs or rest orders as maker")
    else:
        cost_verdict = (f"net-positive after costs: gross {gross_expectancy_r:+.3f}R "
                        f"- friction {friction_r_per_trade:.3f}R = "
                        f"{gross_expectancy_r - friction_r_per_trade:+.3f}R")

    by_strategy: dict[str, dict[str, Any]] = {}
    for strat in sorted({t.strategy for t in trades}):
        sub = [t for t in trades if t.strategy == strat]
        by_strategy[strat] = {
            "n": len(sub),
            "win_rate": safe_div(sum(1 for t in sub if t.net_pnl > 0), len(sub), 0.0),
            "expectancy_r": mean([t.r_multiple for t in sub]),
            "net_pnl": sum(t.net_pnl for t in sub),
            "profit_factor": profit_factor(
                sum(t.net_pnl for t in sub if t.net_pnl > 0),
                abs(sum(t.net_pnl for t in sub if t.net_pnl <= 0))),
            "no_losing_trades": not any(t.net_pnl <= 0 for t in sub),
        }

    by_side: dict[str, dict[str, Any]] = {}
    for side, label in ((1, "long"), (-1, "short")):
        sub = [t for t in trades if t.side == side]
        if not sub:
            by_side[label] = {"n": 0}
            continue
        by_side[label] = {
            "n": len(sub),
            "win_rate": safe_div(sum(1 for t in sub if t.net_pnl > 0), len(sub), 0.0),
            "expectancy_r": mean([t.r_multiple for t in sub]),
            "net_pnl": sum(t.net_pnl for t in sub),
        }

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": safe_div(len(wins), n, 0.0),
        "payoff_ratio": payoff,
        "profit_factor": profit_factor(gross_win, gross_loss),
        # keyed on the trade list, not on gross_loss: a break-even trade is counted
        # as a loss everywhere else in this module (wins are net_pnl > 0), so a book
        # of one flat trade must not claim to have no losers
        "no_losing_trades": bool(n) and not losses,
        "expectancy_r": mean(rs),
        "expectancy_r_median": median(rs),
        "expectancy_pct_per_trade": safe_div(mean(nets),
                                             mean([t.notional for t in trades]), 0.0) * 100.0,
        "r_distribution": {
            "mean": mean(rs), "median": median(rs), "stdev": stdev(rs),
            "p05": percentile(rs, 5), "p25": percentile(rs, 25),
            "p75": percentile(rs, 75), "p95": percentile(rs, 95),
            "min": min(rs), "max": max(rs),
            "skew": skewness(rs), "kurtosis_excess": kurtosis(rs),
            "var95": var_quantile(rs, 0.05), "cvar95": cvar(rs, 0.05),
        },
        "gross_pnl_total": gross_total,
        "net_pnl_total": net_total,
        "friction_total": sum(friction),
        "friction_share_of_gross": safe_div(sum(friction), abs(gross_total), 0.0),
        "friction_bp_mean": mean([t.friction_bp for t in trades]),
        "gross_expectancy_r": gross_expectancy_r,
        "friction_r_per_trade": friction_r_per_trade,
        "cost_bound": cost_bound,
        "cost_verdict": cost_verdict,
        "r_decomposition_n": len(sized),
        "avg_bars_held": mean([t.bars_held for t in trades]),
        "avg_tranches_filled": mean([t.tranches_filled for t in trades]),
        "avg_stop_tightens": mean([t.stop_tightened for t in trades]),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "mfe": {"mean_peak_r": mean(peaks), "median_peak_r": median(peaks),
                "p90_peak_r": percentile(peaks, 90)},
        "mae": {"mean_trough_r": mean(troughs), "median_trough_r": median(troughs),
                "p10_trough_r": percentile(troughs, 10)},
        "capture_ratio_mean": mean(captured) if captured else 0.0,
        "capture_ratio_median": median(captured) if captured else 0.0,
        "capture_ratio_n": len(captured),
        "capture_ratio_mean_all": mean(captured_all) if captured_all else 0.0,
        "trades_never_reached_0p5R": sum(1 for t in trades if t.peak_r < 0.5),
        "giveback_r_mean": mean([t.peak_r - t.r_multiple for t in trades]),
        "r_autocorr_lag1": autocorr(rs, 1),
        "by_strategy": by_strategy,
        "by_side": by_side,
        "exit_reasons": _exit_reason_stats(trades),
        "exit_families": _exit_family_stats(trades),
        "events": _event_stats(trades),
        "score_bucket": _score_buckets(trades),
    }


def _exit_family_stats(trades: Sequence[Trade]) -> dict[str, Any]:
    """Group the concrete exit reasons into their families.

    Concrete reasons are open-ended (``tp2``, ``reversal:leg_flow_flip``,
    ``time_stall``); a report grouped on them grows a row every time an event is
    added, and the reader cannot see that "the strategy exits on stops 60% of the
    time".  The family view is the one worth reading.
    """
    from .exits import exit_reason_family

    out: dict[str, Any] = {}
    fams = sorted({exit_reason_family(t.exit_reason) for t in trades})
    for fam in fams:
        sub = [t for t in trades if exit_reason_family(t.exit_reason) == fam]
        out[fam] = {
            "n": len(sub),
            "share": safe_div(len(sub), len(trades), 0.0),
            "expectancy_r": mean([t.r_multiple for t in sub]),
            "net_pnl": sum(t.net_pnl for t in sub),
            "win_rate": safe_div(sum(1 for t in sub if t.net_pnl > 0), len(sub), 0.0),
            "avg_bars_held": mean([t.bars_held for t in sub]),
            "reasons": sorted({t.exit_reason for t in sub}),
        }
    return out


def _exit_reason_stats(trades: Sequence[Trade]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for reason in sorted({t.exit_reason for t in trades}):
        sub = [t for t in trades if t.exit_reason == reason]
        out[reason] = {
            "n": len(sub),
            "share": safe_div(len(sub), len(trades), 0.0),
            "expectancy_r": mean([t.r_multiple for t in sub]),
            "net_pnl": sum(t.net_pnl for t in sub),
            "win_rate": safe_div(sum(1 for t in sub if t.net_pnl > 0), len(sub), 0.0),
            "avg_bars_held": mean([t.bars_held for t in sub]),
        }
    return out


def _event_stats(trades: Sequence[Trade]) -> dict[str, Any]:
    """Which reversal events fired, and what trades they were on."""
    out: dict[str, Any] = {}
    names: set[str] = set()
    for t in trades:
        names.update(t.events_seen)
    for name in sorted(names):
        sub = [t for t in trades if name in t.events_seen]
        rest = [t for t in trades if name not in t.events_seen]
        out[name] = {
            "n": len(sub),
            "share": safe_div(len(sub), len(trades), 0.0),
            "expectancy_r_with": mean([t.r_multiple for t in sub]),
            "expectancy_r_without": mean([t.r_multiple for t in rest]) if rest else 0.0,
            "net_pnl": sum(t.net_pnl for t in sub),
        }
        out[name]["expectancy_delta"] = (out[name]["expectancy_r_with"]
                                         - out[name]["expectancy_r_without"])
    return out


def _score_buckets(trades: Sequence[Trade]) -> dict[str, Any]:
    """Does a higher edge score actually predict a better trade?

    If it does not, the score is decoration and ``min_edge_score`` is filtering on
    noise — which is worth knowing before spending effort tuning it.
    """
    buckets = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    out: dict[str, Any] = {}
    for lo, hi in buckets:
        sub = [t for t in trades if lo <= t.signal_score < hi]
        out[f"{lo:.1f}-{hi:.1f}"] = {
            "n": len(sub),
            "expectancy_r": mean([t.r_multiple for t in sub]) if sub else 0.0,
            "win_rate": safe_div(sum(1 for t in sub if t.net_pnl > 0), len(sub), 0.0)
            if sub else 0.0,
            "net_pnl": sum(t.net_pnl for t in sub) if sub else 0.0,
        }
    return out


# --------------------------------------------------------------------------- #
# top-level summary
# --------------------------------------------------------------------------- #
def summarise(result: Any, *, initial_equity: float, periods_per_year: float,
              timeframe: int, n_trials: int = 1, sr_std: float = 0.35,
              n_boot: int = 400, seed: int = 7) -> dict[str, Any]:
    """Build the full metrics block for a :class:`BacktestResult`.

    ``n_trials`` is how many configurations were tried before reporting this one.
    Defaulting to 1 is honest only for a single hand-specified run; the CLI and
    walk-forward driver pass the real number so the Deflated Sharpe means
    something.

    ``sr_std`` is the ANNUALISED cross-sectional dispersion of the trial Sharpe
    ratios; it is converted to per-period units before deflation (see
    :func:`deflated_sharpe`).
    """
    eq_pts: Sequence[EquityPoint] = result.equity_curve
    trades: Sequence[Trade] = result.trades
    equity = [p.equity for p in eq_pts]
    if not equity:
        return {"error": "empty equity curve"}

    rets: list[float] = []
    for k in range(1, len(equity)):
        prev = equity[k - 1]
        rets.append(safe_div(equity[k] - prev, prev, 0.0) if prev > 0 else 0.0)

    ppy = max(periods_per_year, 1.0)
    total_return = safe_div(equity[-1] - initial_equity, initial_equity, 0.0)
    n_periods = len(rets)
    years = n_periods / ppy if ppy > 0 else 0.0
    cagr = ((equity[-1] / initial_equity) ** (1.0 / years) - 1.0) \
        if years > 0 and equity[-1] > 0 and initial_equity > 0 else 0.0

    dd = drawdown_info(equity)
    ann_vol = stdev(rets) * math.sqrt(ppy) if len(rets) > 1 else 0.0
    sr_period = safe_div(mean(rets), stdev(rets), 0.0) if len(rets) > 1 else 0.0
    sharpe = sr_period * math.sqrt(ppy)
    sortino = sortino_of(rets, ppy)

    exposure = safe_div(
        sum(1 for p in eq_pts if p.open_positions > 0), len(eq_pts), 0.0)
    avg_leverage = mean([safe_div(p.open_risk, p.equity, 0.0) for p in eq_pts]) \
        if eq_pts else 0.0

    ts = trade_stats(trades)
    # sr_std arrives as an ANNUALISED dispersion (0.35 is the conventional figure)
    # but deflated_sharpe works in per-period units; without this conversion the
    # expected-maximum benchmark is sqrt(ppy) times too big and the DSR collapses
    # to 0 for every run — exactly when n_trials > 1 and the guard matters.
    dsr = deflated_sharpe(
        sr_period, n_obs=len(rets), skew=skewness(rets),
        kurt=kurtosis(rets) + 3.0, n_trials=max(1, n_trials),
        sr_std=sr_std / math.sqrt(ppy))
    sharpe_ci = bootstrap_ci(rets, lambda r: sharpe_of(r, ppy),
                             n_boot=n_boot, mean_block=max(4, len(rets) // 40),
                             seed=seed)
    dd_ci = bootstrap_ci(rets, lambda r: max_drawdown(
        _equity_from_returns(r, initial_equity)),
        n_boot=n_boot, mean_block=max(4, len(rets) // 40), seed=seed + 1)

    monthly = _monthly_returns(eq_pts)

    out: dict[str, Any] = {
        "period": {
            "bars": len(equity), "return_periods": n_periods,
            "years": years, "timeframe_minutes": timeframe,
            "periods_per_year": ppy,
            "start_ts": eq_pts[0].ts if eq_pts else 0,
            "end_ts": eq_pts[-1].ts if eq_pts else 0,
        },
        "returns": {
            "initial_equity": initial_equity,
            "final_equity": equity[-1],
            "pnl": equity[-1] - initial_equity,
            "total_return_pct": total_return * 100.0,
            "cagr_pct": cagr * 100.0,
            "best_period_pct": (max(rets) * 100.0) if rets else 0.0,
            "worst_period_pct": (min(rets) * 100.0) if rets else 0.0,
            "positive_periods_share": safe_div(sum(1 for r in rets if r > 0), n_periods, 0.0),
        },
        "risk": {
            "annualised_vol_pct": ann_vol * 100.0,
            "max_drawdown_pct": dd.max_dd * 100.0,
            "drawdown": dd.to_dict(),
            "var95_period_pct": var_quantile(rets, 0.05) * 100.0,
            "cvar95_period_pct": cvar(rets, 0.05) * 100.0,
            "skew": skewness(rets),
            "kurtosis_excess": kurtosis(rets),
            "return_autocorr_lag1": autocorr(rets, 1),
        },
        "risk_adjusted": {
            "sharpe": sharpe,
            "sharpe_per_period": sr_period,
            "sortino": sortino,
            "calmar": safe_div(cagr, dd.max_dd, 0.0),
            "omega": omega_of(rets),
            "sharpe_ci95": sharpe_ci,
            "max_drawdown_ci95": dd_ci,
            "deflated_sharpe": dsr,
            "vol_to_drawdown": safe_div(ann_vol, dd.max_dd, 0.0),
        },
        "exposure": {
            "time_in_market": exposure,
            "avg_open_risk_share": avg_leverage,
            "avg_open_positions": mean([float(p.open_positions) for p in eq_pts])
            if eq_pts else 0.0,
        },
        "trades": ts,
        "monthly_returns_pct": monthly,
        "consistency": _consistency(monthly, rets, ppy),
    }
    return out


def _equity_from_returns(rets: Sequence[float], initial: float) -> list[float]:
    eq = [initial]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _monthly_returns(eq_pts: Sequence[EquityPoint]) -> dict[str, float]:
    import datetime as _dt
    by_month: dict[str, list[float]] = {}
    for p in eq_pts:
        key = _dt.datetime.fromtimestamp(p.ts / 1000.0, _dt.timezone.utc).strftime("%Y-%m")
        by_month.setdefault(key, []).append(p.equity)
    keys = sorted(by_month)
    out: dict[str, float] = {}
    prev_end: float | None = None
    for k in keys:
        series = by_month[k]
        base = prev_end if prev_end is not None else series[0]
        out[k] = safe_div(series[-1] - base, base, 0.0) * 100.0 if base > 0 else 0.0
        prev_end = series[-1]
    return out


def _consistency(monthly: dict[str, float], rets: Sequence[float],
                 ppy: float) -> dict[str, Any]:
    """Is the edge spread across time, or is it one good month?"""
    vals = list(monthly.values())
    if not vals:
        return {}
    pos = sum(1 for v in vals if v > 0)
    best = max(vals)
    total = sum(vals)
    # return with the single best month removed
    rest = [v for v in vals]
    rest.remove(best)
    return {
        "months": len(vals),
        "positive_months": pos,
        "positive_month_share": safe_div(pos, len(vals), 0.0),
        "best_month_pct": best,
        "worst_month_pct": min(vals),
        "total_monthly_pct": total,
        "best_month_share_of_total": safe_div(best, total, 0.0) if total > 0 else 0.0,
        "total_ex_best_month_pct": sum(rest),
        "monthly_mean_pct": mean(vals),
        "monthly_stdev_pct": stdev(vals),
        "monthly_sharpe": safe_div(mean(vals), stdev(vals), 0.0) * math.sqrt(12.0),
    }


# --------------------------------------------------------------------------- #
# comparison helper
# --------------------------------------------------------------------------- #
def compare(strat: Any, control: Any | None = None,
            every_bar: Any | None = None) -> dict[str, Any]:
    """Strategy vs its random-entry and every-bar controls.

    This is the single most informative table in a report.  Three outcomes:

    * beats random control → the *entry* selection carries information;
    * ties random control but beats every-bar → the *exit* logic carries it and
      the signal is decoration;
    * loses to both → the system is a cost generator on this data.
    """
    def row(r: Any, label: str) -> dict[str, Any]:
        m = r.metrics
        return {
            "label": label,
            "n_trades": len(r.trades),
            "return_pct": m.get("returns", {}).get("total_return_pct", 0.0),
            "sharpe": m.get("risk_adjusted", {}).get("sharpe", 0.0),
            "max_dd_pct": m.get("risk", {}).get("max_drawdown_pct", 0.0),
            "win_rate": m.get("trades", {}).get("win_rate", 0.0),
            "expectancy_r": m.get("trades", {}).get("expectancy_r", 0.0),
            "profit_factor": m.get("trades", {}).get("profit_factor", 0.0),
        }

    rows = [row(strat, "strategy")]
    if control is not None:
        rows.append(row(control, "random_entry_control"))
    if every_bar is not None:
        rows.append(row(every_bar, "every_bar_control"))

    verdict = "insufficient_data"
    if control is not None:
        s_sh = rows[0]["sharpe"]
        c_sh = rows[1]["sharpe"]
        s_ex = rows[0]["expectancy_r"]
        c_ex = rows[1]["expectancy_r"]
        if s_ex > c_ex + 0.05 and s_sh > c_sh:
            verdict = "entry_selection_has_edge"
        elif abs(s_ex - c_ex) <= 0.05:
            verdict = "exit_logic_dominates_entry_is_decoration"
        else:
            verdict = "entry_selection_is_negative"
    return {"rows": rows, "verdict": verdict}
