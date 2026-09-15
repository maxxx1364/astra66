"""Validation: walk-forward, purged splits, overfitting probability, ablation.

A backtest that only reports an in-sample equity curve reports nothing.  This
module exists to answer the three questions that decide whether a result means
anything:

1. **Does it survive out-of-sample?**  :func:`walk_forward` selects parameters on
   a training window and scores them on the following, unseen window, then chains
   the out-of-sample returns into one honest curve.
2. **Was it found by searching?**  :func:`cscv_pbo` implements the Combinatorially
   Symmetric Cross-Validation of Bailey et al. and returns the *Probability of
   Backtest Overfitting*: the chance that the configuration which looked best
   in-sample lands below median out-of-sample.  Above ~0.5 the search was noise.
3. **Does each filter earn its place?**  :func:`ablation` disables one filter at a
   time and reports what happens.  A filter whose removal changes nothing is
   decoration; one whose removal improves the result is actively harmful.

Purging and embargo
-------------------
Splits are purged: because a trade opened near a split boundary is *closed* using
bars from the other side of it, the last ``purge`` training bars before a test
window are dropped.  An ``embargo`` of a few bars after the test window is dropped
too, to stop serial correlation leaking backwards.  Without purging, walk-forward
results on overlapping-horizon strategies are systematically optimistic — this is
the López de Prado critique and it applies directly here, since positions span
many bars.

Efficiency note
---------------
Every series in the pipeline is causal, so a parameter set's return series can be
computed once over the whole sample and then sliced per fold.  That makes
walk-forward cost ``O(n_configs)`` backtests rather than ``O(n_configs x n_folds)``,
which is the difference between a tool you run and one you avoid.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .mathx import EPS, clamp, mean, median, percentile, safe_div, stdev
from .metrics import deflated_sharpe, drawdown_series, max_drawdown, sharpe_of
from .portfolio import Trade


# --------------------------------------------------------------------------- #
# split construction
# --------------------------------------------------------------------------- #
def purged_kfold(n: int, k: int = 5, purge: int = 0,
                 embargo: int = 0) -> list[tuple[list[int], list[int]]]:
    """Contiguous, purged walk-forward splits over ``n`` observations.

    Returns ``[(train_idx, test_idx), ...]`` with ``k`` folds.  Fold ``j`` trains
    on everything before its test window and tests on the window itself, which is
    the only ordering that respects causality for a time series.
    """
    if n <= 0 or k < 2:
        return []
    size = n // k
    out: list[tuple[list[int], list[int]]] = []
    for j in range(k):
        t0 = j * size
        t1 = n if j == k - 1 else (j + 1) * size
        test = list(range(t0, t1))
        train = list(range(0, max(0, t0 - purge)))
        if j + 1 < k:
            extra = list(range(min(n, t1 + embargo), n))
            train += extra
        out.append((train, test))
    return out


def anchored_splits(n: int, n_splits: int = 5, min_train: int = 0,
                    purge: int = 0) -> list[tuple[list[int], list[int]]]:
    """Expanding-window ("anchored") splits: train grows, test is the next block."""
    if n <= 0 or n_splits < 2:
        return []
    block = n // (n_splits + 1)
    out: list[tuple[list[int], list[int]]] = []
    for j in range(1, n_splits + 1):
        train_end = max(min_train, j * block) - purge
        test_start = max(min_train, j * block)
        test_end = n if j == n_splits else (j + 1) * block
        if train_end <= 0 or test_end <= test_start:
            continue
        out.append((list(range(0, max(0, train_end))),
                    list(range(test_start, min(n, test_end)))))
    return out


# --------------------------------------------------------------------------- #
# walk-forward
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class FoldResult:
    fold: int
    train_idx: tuple[int, int]
    test_idx: tuple[int, int]
    best_config: str
    is_score: float
    oos_score: float
    oos_return_pct: float
    oos_max_dd_pct: float
    oos_n_trades: int
    is_rank_of_oos_best: int = -1
    n_configs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "train": list(self.train_idx), "test": list(self.test_idx),
            "best_config": self.best_config,
            "is_score": self.is_score, "oos_score": self.oos_score,
            "oos_return_pct": self.oos_return_pct,
            "oos_max_dd_pct": self.oos_max_dd_pct,
            "oos_n_trades": self.oos_n_trades,
            "is_rank_of_oos_best": self.is_rank_of_oos_best,
            "n_configs": self.n_configs,
        }


@dataclass(slots=True)
class WalkForwardResult:
    folds: list[FoldResult] = field(default_factory=list)
    oos_returns: list[float] = field(default_factory=list)
    oos_sharpe: float = 0.0
    oos_return_pct: float = 0.0
    oos_max_dd_pct: float = 0.0
    is_sharpe_mean: float = 0.0
    overfit_gap: float = 0.0
    periods_per_year: float = 1.0
    n_configs_tried: int = 0
    deflated: dict[str, Any] = field(default_factory=dict)
    pbo: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "folds": [f.to_dict() for f in self.folds],
            "oos_sharpe": self.oos_sharpe,
            "is_sharpe_mean": self.is_sharpe_mean,
            "overfit_gap": self.overfit_gap,
            "oos_return_pct": self.oos_return_pct,
            "oos_max_dd_pct": self.oos_max_dd_pct,
            "periods_per_year": self.periods_per_year,
            "n_configs_tried": self.n_configs_tried,
            "deflated_sharpe": self.deflated,
            "pbo": self.pbo,
        }


def walk_forward(
    returns_by_config: dict[str, Sequence[float]],
    trades_by_config: dict[str, Sequence[Trade]] | None = None,
    *,
    periods_per_year: float,
    n_splits: int = 5,
    purge: int = 16,
    embargo: int = 4,
    score: str = "sharpe",
    compute_pbo: bool = True,
) -> WalkForwardResult:
    """Select on train, score on the unseen test block, chain the OOS returns.

    ``returns_by_config`` maps a config label to its *per-period return series*
    over the whole sample.  Because every engine series is causal, one backtest
    per config is enough — see the module docstring.
    """
    if not returns_by_config:
        return WalkForwardResult()
    labels = sorted(returns_by_config)
    n = min(len(returns_by_config[l]) for l in labels)
    if n < 40:
        return WalkForwardResult()
    splits = anchored_splits(n, n_splits=n_splits, min_train=max(40, n // 6),
                             purge=purge)
    out = WalkForwardResult(periods_per_year=periods_per_year,
                            n_configs_tried=len(labels))
    scorer = _scorer(score, periods_per_year)

    is_scores: list[float] = []
    oos_returns: list[float] = []
    # matrix for CSCV: config x observation
    for j, (train, test) in enumerate(splits):
        if not test:
            continue
        best_label, best_is, _ = _pick_best(returns_by_config, labels, train, scorer)
        oos = scorer(returns_by_config[best_label], test)
        oos_r = returns_by_config[best_label][test[0]: test[-1] + 1]
        oos_returns.extend(oos_r)
        is_scores.append(best_is)

        # where did the OOS-best config rank in-sample?  A large gap between the
        # IS-best and the OOS-best is the direct signature of overfitting.
        oos_best, oos_best_score, _ = _pick_best(
            returns_by_config, labels, test, scorer)
        is_ranking = sorted(
            labels, key=lambda l: -scorer(returns_by_config[l], train))
        rank_of_oos_best = (is_ranking.index(oos_best)
                            if oos_best in is_ranking else -1)

        eq = [1.0]
        for r in oos_r:
            eq.append(eq[-1] * (1.0 + r))
        out.folds.append(FoldResult(
            fold=j, train_idx=(train[0], train[-1]), test_idx=(test[0], test[-1]),
            best_config=best_label, is_score=best_is, oos_score=oos_best_score,
            oos_return_pct=(eq[-1] - 1.0) * 100.0,
            oos_max_dd_pct=max_drawdown(eq) * 100.0,
            oos_n_trades=len([t for t in (trades_by_config or {}).get(best_label, [])
                              if True]),
            is_rank_of_oos_best=rank_of_oos_best, n_configs=len(labels),
        ))
        _ = oos

    out.oos_returns = oos_returns
    out.oos_sharpe = sharpe_of(oos_returns, periods_per_year) if oos_returns else 0.0
    out.is_sharpe_mean = mean(is_scores) if is_scores else 0.0
    out.overfit_gap = out.is_sharpe_mean - out.oos_sharpe
    eq = [1.0]
    for r in oos_returns:
        eq.append(eq[-1] * (1.0 + r))
    out.oos_return_pct = (eq[-1] - 1.0) * 100.0
    out.oos_max_dd_pct = max_drawdown(eq) * 100.0

    sr_period = safe_div(mean(oos_returns), stdev(oos_returns), 0.0) \
        if len(oos_returns) > 2 else 0.0
    sharpe_var = stdev(is_scores) if len(is_scores) > 2 else 0.35
    out.deflated = deflated_sharpe(
        sr_period, n_obs=len(oos_returns),
        skew=_skew(oos_returns), kurt=_kurt(oos_returns) + 3.0,
        n_trials=max(1, len(labels)), sr_std=max(sharpe_var, 0.05) /
        math.sqrt(max(periods_per_year, 1.0)))

    if compute_pbo and len(labels) >= 4:
        matrix = [[returns_by_config[l][i] for i in range(n)] for l in labels]
        out.pbo = cscv_pbo(matrix, n_splits=min(16, max(4, n // 40)), seed=11)
    return out


def _scorer(score: str, ppy: float) -> Callable[[Sequence[float], Sequence[int]], float]:
    if score == "return":
        def f(xs: Sequence[float], idx: Sequence[int]) -> float:
            v = 1.0
            for i in idx:
                v *= (1.0 + xs[i])
            return v - 1.0
        return f
    if score == "calmar":
        def f(xs: Sequence[float], idx: Sequence[int]) -> float:
            sub = [xs[i] for i in idx]
            eq = [1.0]
            for r in sub:
                eq.append(eq[-1] * (1.0 + r))
            return safe_div(_cagr(eq, ppy, len(sub)), max(max_drawdown(eq), 1e-6), 0.0)
        return f
    def f(xs: Sequence[float], idx: Sequence[int]) -> float:
        return sharpe_of([xs[i] for i in idx], ppy)
    return f


def _cagr(eq: Sequence[float], ppy: float, n: int) -> float:
    if n <= 0 or not eq or eq[0] <= 0 or eq[-1] <= 0:
        return 0.0
    years = n / max(ppy, 1.0)
    if years <= 0:
        return 0.0
    return (eq[-1] / eq[0]) ** (1.0 / years) - 1.0


def _pick_best(returns_by_config: dict[str, Sequence[float]], labels: Sequence[str],
               idx: Sequence[int], scorer: Callable[[Sequence[float], Sequence[int]], float]
               ) -> tuple[str, float, list[tuple[str, float]]]:
    scored = sorted(((l, scorer(returns_by_config[l], idx)) for l in labels),
                    key=lambda kv: -kv[1])
    return (scored[0][0], scored[0][1], scored)


def _skew(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m, s = mean(xs), stdev(xs)
    if s <= EPS:
        return 0.0
    return safe_div(sum(((x - m) / s) ** 3 for x in xs) * n, (n - 1) * (n - 2), 0.0)


def _kurt(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 4:
        return 0.0
    m, s = mean(xs), stdev(xs)
    if s <= EPS:
        return 0.0
    return sum(((x - m) / s) ** 4 for x in xs) / n - 3.0


# --------------------------------------------------------------------------- #
# CSCV / probability of backtest overfitting
# --------------------------------------------------------------------------- #
def cscv_pbo(matrix: Sequence[Sequence[float]], n_splits: int = 16,
             max_combos: int = 64, seed: int = 11,
             score_fn: Callable[[Sequence[float]], float] | None = None) -> dict[str, Any]:
    """Combinatorially Symmetric Cross-Validation (Bailey, Borwein, López de Prado, Zhu).

    ``matrix`` is ``[n_configs][n_observations]`` of per-period returns.  The
    observation axis is cut into ``n_splits`` blocks; for each way of choosing half
    the blocks as in-sample, the config that looks best in-sample is ranked
    out-of-sample.  PBO is the share of splits where that rank falls in the bottom
    half — i.e. the probability that "best in-sample" is a selection artefact.

    Reading it: PBO < 0.2 is reassuring, 0.2-0.5 is worrying, > 0.5 means the
    search was fitting noise and the reported configuration should be discarded.
    """
    n_cfg = len(matrix)
    if n_cfg < 2:
        return {"pbo": 0.0, "reliable": False, "reason": "fewer than 2 configs"}
    n_obs = min(len(r) for r in matrix)
    n_splits = max(4, min(n_splits, n_obs // 10))
    if n_splits % 2 == 1:
        n_splits -= 1
    if n_splits < 4:
        return {"pbo": 0.0, "reliable": False, "reason": "not enough observations"}

    block = n_obs // n_splits
    blocks = [list(range(b * block, (b + 1) * block)) for b in range(n_splits)]
    scorer = score_fn or (lambda xs: sharpe_of(xs, 1.0))

    combos = list(itertools.combinations(range(n_splits), n_splits // 2))
    if len(combos) > max_combos:
        rng = random.Random(seed)
        combos = rng.sample(combos, max_combos)

    logits: list[float] = []
    below_median = 0
    for combo in combos:
        is_idx = [i for b in combo for i in blocks[b]]
        oos_idx = [i for b in range(n_splits) if b not in combo for i in blocks[b]]
        if not is_idx or not oos_idx:
            continue
        is_scores = [scorer([matrix[c][i] for i in is_idx]) for c in range(n_cfg)]
        oos_scores = [scorer([matrix[c][i] for i in oos_idx]) for c in range(n_cfg)]
        best = max(range(n_cfg), key=lambda c: is_scores[c])
        # relative rank of the IS-best in the OOS ordering, in (0, 1)
        rank = sum(1 for v in oos_scores if v < oos_scores[best])
        omega = (rank + 1) / (n_cfg + 1)
        omega = clamp(omega, 1e-6, 1.0 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))
        if omega <= 0.5:
            below_median += 1

    if not logits:
        return {"pbo": 0.0, "reliable": False, "reason": "no valid splits"}
    return {
        "pbo": below_median / len(logits),
        "n_splits": n_splits,
        "n_combos_evaluated": len(logits),
        "n_configs": n_cfg,
        "logit_mean": mean(logits),
        "logit_median": median(logits),
        "logit_stdev": stdev(logits),
        "reliable": True,
        "interpretation": _pbo_reading(below_median / len(logits)),
    }


def _pbo_reading(pbo: float) -> str:
    if pbo < 0.20:
        return "low: in-sample selection mostly carries out-of-sample"
    if pbo < 0.50:
        return "elevated: a meaningful share of the ranking is selection noise"
    return "high: the configuration search was fitting noise — discard the best-in-sample pick"


# --------------------------------------------------------------------------- #
# ablation
# --------------------------------------------------------------------------- #
def ablation(run_one: Callable[[str, bool], dict[str, Any]],
             filters: Sequence[str]) -> dict[str, Any]:
    """Measure each filter's marginal contribution by disabling it.

    ``run_one(filter_name, disabled)`` must return at least ``n_trades``,
    ``expectancy_r``, ``sharpe``, ``max_dd_pct`` and ``return_pct``.

    Two numbers matter per filter:

    * ``delta`` — how much the metric moves when the filter is removed.  Near zero
      means the filter is decoration.
    * ``verdict`` — ``keep`` / ``review`` / ``harmful``.  "Harmful" means removing
      the filter *improved* the result, which is the outcome nobody wants to see
      and therefore the one most often left unreported.
    """
    base = run_one("", False)
    rows: dict[str, Any] = {"baseline": base, "filters": {}}
    for f in filters:
        alt = run_one(f, True)
        d_n = alt.get("n_trades", 0) - base.get("n_trades", 0)
        d_exp = alt.get("expectancy_r", 0.0) - base.get("expectancy_r", 0.0)
        d_sh = alt.get("sharpe", 0.0) - base.get("sharpe", 0.0)
        d_ret = alt.get("return_pct", 0.0) - base.get("return_pct", 0.0)
        d_dd = alt.get("max_dd_pct", 0.0) - base.get("max_dd_pct", 0.0)
        if d_exp > 0.02 and d_sh > 0.05:
            verdict = "harmful"
        elif abs(d_exp) <= 0.02 and abs(d_sh) <= 0.05 and abs(d_n) <= max(2, base.get("n_trades", 0) * 0.05):
            verdict = "decoration"
        elif d_exp < -0.02 or d_sh < -0.05:
            verdict = "keep"
        else:
            verdict = "review"
        rows["filters"][f] = {
            "n_trades": alt.get("n_trades", 0),
            "delta_n_trades": d_n,
            "delta_expectancy_r": d_exp,
            "delta_sharpe": d_sh,
            "delta_return_pct": d_ret,
            "delta_max_dd_pct": d_dd,
            "verdict": verdict,
            "detail": alt,
        }
    return rows


# --------------------------------------------------------------------------- #
# parameter plateau
# --------------------------------------------------------------------------- #
def parameter_plateau(sweep: Sequence[tuple[Any, float]],
                      *, window: int = 1) -> list[dict[str, Any]]:
    """Neighbourhood stability of a 1-D parameter sweep.

    Reports each value's score *and* the mean score of its ``window`` neighbours.
    A parameter whose own score is high but whose neighbours are poor is a spike,
    not a plateau — and spikes do not survive contact with live data.  Prefer the
    widest flat region over the single best point.
    """
    n = len(sweep)
    out: list[dict[str, Any]] = []
    for i, (val, score) in enumerate(sweep):
        lo, hi = max(0, i - window), min(n, i + window + 1)
        neigh = [s for j, (_, s) in enumerate(sweep[lo:hi]) if lo + j != i]
        out.append({
            "value": val, "score": score,
            "neighbour_mean": mean(neigh) if neigh else score,
            "neighbour_min": min(neigh) if neigh else score,
            "stability": safe_div(min(neigh) if neigh else score, score, 0.0)
            if score != 0 else 0.0,
            "is_spike": bool(neigh) and score > 0 and mean(neigh) < 0.5 * score,
            #: an edge point's window is clipped, so its neighbourhood mean is
            #: computed over fewer (and one-sided) neighbours — see best_plateau
            "full_window": lo == i - window and hi == i + window + 1,
        })
    return out


def best_plateau(sweep: Sequence[tuple[Any, float]], *, window: int = 2) -> dict[str, Any]:
    """Pick the value that maximises the *neighbourhood* mean, not the point.

    Two biases have to be removed before that ranking means anything:

    * **edge clipping** — at the ends of the sweep the window is one-sided, so a
      terrible value sitting next to a good region inherits that region's mean and
      can win.  Restricting the ranking to points with a full window removes it
      (and falls back to all points when the sweep is too short to have any).
    * **spikes** — a value that is good while both neighbours are poor is a fit to
      noise, not a plateau.  Spikes are excluded unless nothing else remains, and
      the result says which happened.
    """
    rows = parameter_plateau(sweep, window=window)
    if not rows:
        return {}
    best_point = max(rows, key=lambda r: r["score"])
    interior = [r for r in rows if r["full_window"]]
    pool_source = "interior_non_spike"
    pool = [r for r in interior if not r["is_spike"]]
    if not pool:
        pool = interior
        pool_source = "interior_only" if interior else "none"
    if not pool:
        pool = [r for r in rows if not r["is_spike"]] or rows
        pool_source = "all_non_spike" if any(not r["is_spike"] for r in rows) else "all"
    best = max(pool, key=lambda r: (r["neighbour_mean"], r["score"]))
    return {
        "chosen": best["value"],
        "chosen_score": best["score"],
        "chosen_neighbour_mean": best["neighbour_mean"],
        "chosen_is_spike": best["is_spike"],
        "best_point_value": best_point["value"],
        "best_point_score": best_point["score"],
        "agrees": best["value"] == best_point["value"],
        "candidate_pool": pool_source,
        "n_interior_candidates": len(interior),
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# monte carlo on the trade sequence
# --------------------------------------------------------------------------- #
def monte_carlo_drawdown(trades: Sequence[Trade], n_sims: int = 500,
                         seed: int = 3, block: int = 5) -> dict[str, Any]:
    """Distribution of max drawdown under block-resampled trade ordering.

    The realised drawdown is one draw from a distribution; reporting only the
    realised number understates what the strategy can do to an account.  Blocks
    (not iid) are used because trade outcomes cluster by regime.
    """
    if len(trades) < 10:
        # return the SAME key set as the reliable path.  A partial dict makes every
        # consumer's `out["max_dd_p95_pct"]` a KeyError on exactly the runs (few
        # trades) where a report is most likely to be generated.
        return {
            "reliable": False, "reason": f"only {len(trades)} trades; need >= 10",
            "n_sims": 0, "n_trades": len(trades),
            "max_dd_mean_pct": 0.0, "max_dd_median_pct": 0.0,
            "max_dd_p95_pct": 0.0, "max_dd_p99_pct": 0.0, "max_dd_worst_pct": 0.0,
            "return_mean_pct": 0.0, "return_p05_pct": 0.0, "return_p95_pct": 0.0,
            "prob_return_negative": 0.0, "prob_loss_70pct": 0.0,
        }
    rs = [t.r_multiple for t in trades]
    risk_cash = mean([t.risk_cash for t in trades]) or 1.0
    equity0 = 100_000.0
    rng = random.Random(seed)
    n = len(rs)
    dds: list[float] = []
    rets: list[float] = []
    ruins = 0
    for _ in range(n_sims):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            for k in range(block):
                sample.append(rs[(start + k) % n])
                if len(sample) >= n:
                    break
        eq = [equity0]
        for r in sample:
            eq.append(max(1.0, eq[-1] + r * risk_cash))
        dds.append(max_drawdown(eq))
        rets.append(safe_div(eq[-1] - equity0, equity0, 0.0))
        if eq[-1] <= equity0 * 0.30:
            ruins += 1
    return {
        "reliable": True,
        "n_sims": n_sims,
        "n_trades": n,
        "max_dd_mean_pct": mean(dds) * 100.0,
        "max_dd_median_pct": median(dds) * 100.0,
        "max_dd_p95_pct": percentile(dds, 95) * 100.0,
        "max_dd_p99_pct": percentile(dds, 99) * 100.0,
        "max_dd_worst_pct": max(dds) * 100.0,
        "return_mean_pct": mean(rets) * 100.0,
        "return_p05_pct": percentile(rets, 5) * 100.0,
        "return_p95_pct": percentile(rets, 95) * 100.0,
        "prob_return_negative": safe_div(sum(1 for r in rets if r < 0), len(rets), 0.0),
        "prob_loss_70pct": safe_div(ruins, len(rets), 0.0),
    }


def bootstrap_expectancy(trades: Sequence[Trade], n_boot: int = 2000,
                         seed: int = 5) -> dict[str, Any]:
    """Bootstrap CI on expectancy (mean R per trade).

    iid resampling is defensible *here* — unlike the equity curve, expectancy is a
    mean over trades and the ordering does not enter the statistic.  The question
    it answers is the only one that really matters before risking money: is
    expectancy distinguishable from zero?
    """
    if len(trades) < 8:
        return {"reliable": False, "n": len(trades)}
    rs = [t.r_multiple for t in trades]
    rng = random.Random(seed)
    n = len(rs)
    vals: list[float] = []
    for _ in range(n_boot):
        vals.append(mean([rs[rng.randrange(n)] for _ in range(n)]))
    vals.sort()
    return {
        "reliable": True,
        "n": n,
        "expectancy_r": mean(rs),
        "ci95_lo": percentile(vals, 2.5),
        "ci95_hi": percentile(vals, 97.5),
        "p_expectancy_gt_0": safe_div(sum(1 for v in vals if v > 0), len(vals), 0.0),
        "n_boot": n_boot,
    }


def minimum_detectable_trades(effect_r: float, sd_r: float,
                              power: float = 0.8, alpha: float = 0.05) -> int:
    """How many trades are needed to detect an expectancy of ``effect_r``.

    Reported alongside every result, because "not significant" and "no edge" are
    different statements and the difference is sample size.
    """
    if effect_r <= 0 or sd_r <= 0:
        return 0
    from .metrics import norm_ppf
    za = norm_ppf(1.0 - alpha / 2.0)
    zb = norm_ppf(power)
    return int(math.ceil(((za + zb) * sd_r / effect_r) ** 2))
