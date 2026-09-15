#!/usr/bin/env python3
"""Cost attribution: is the strategy signal-bound or cost-bound?

Run::

    python3 scripts/cost_attribution.py --seeds 20 --days 45 --tf 15

Why this script exists
----------------------
A backtest that reports one net number cannot tell you *why* it lost.  Every
trade in this engine carries ``gross_pnl`` (P&L at reference prices, before any
fee) and ``costs`` (commission + funding + slippage, itemised), and
``net_pnl == gross_pnl - costs`` exactly, so the net result decomposes without
residual:

    mean(net R) = mean(gross R) - mean(friction R)

That single identity answers the only question that matters before touching the
model again: if ``friction R`` exceeds ``gross R``, no amount of extra filtering
can help — the fix has to be geometric (wider stops, fewer exit legs, resting
orders).  If ``gross R`` is <= 0, cost engineering is irrelevant and the signal
is the problem.

Pooling rules (easy to get wrong, so they are stated here)
----------------------------------------------------------
* Trades are pooled **across seeds** and every statistic is computed once on the
  pooled sample.  Averaging per-seed *ratios* (profit factor, Sharpe, return %)
  weights each seed equally regardless of how many trades it produced and is
  statistically meaningless when seed sample sizes differ by 10x — which they do
  at high confirmation thresholds.
* Pooled profit factor = sum(net wins) / |sum(net losses)| over the pooled set.
* Pooled return = sum of per-seed equity change / (n_seeds * initial equity).
* Standard errors use the pooled per-trade dispersion; confidence intervals come
  from the Politis-Romano stationary bootstrap, which respects serial dependence
  inside a seed's trade sequence.
* ``minimum_detectable_trades`` is reported next to ``n`` so a small-sample
  result can never be mistaken for a validated one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import backtest as BT                                # noqa: E402
from engine import metrics as metrics_mod                        # noqa: E402
from engine import pipeline, signals as S, validation            # noqa: E402
from engine.exits import ExitConfig                              # noqa: E402
from engine.mathx import mean, stdev                             # noqa: E402

#: exit geometries worth comparing.  ``wide`` widens the stop, which shrinks
#: friction *per R* mechanically because R is defined by the stop distance;
#: ``single`` collapses the three tranche legs into one runner, which removes two
#: fee-paying fills per trade.
GEOMETRIES: dict[str, ExitConfig] = {
    "baseline_3tranche_2.2s": ExitConfig(),
    "wide_3tranche_4.4s": ExitConfig(stop_mode="sigma", stop_sigma_mult=4.40),
    "single_runner_2.2s": ExitConfig(tranches=((0.00, 1.00),)),
    "wide_single_runner_4.4s": ExitConfig(stop_mode="sigma", stop_sigma_mult=4.40,
                                          tranches=((0.00, 1.00),)),
}


def _ci(xs: Sequence[float], n_boot: int, seed: int) -> tuple[float, float]:
    """95% stationary-bootstrap CI for the mean of ``xs``."""
    if len(xs) < 8:
        return (float("nan"), float("nan"))
    samples = metrics_mod.stationary_bootstrap(list(xs), n_boot=n_boot, seed=seed)
    means = sorted(sum(s) / len(s) for s in samples if s)
    if not means:
        return (float("nan"), float("nan"))
    lo = means[max(0, int(0.025 * len(means)))]
    hi = means[min(len(means) - 1, int(0.975 * len(means)))]
    return (lo, hi)


def collect(seed: int, days: int, tf: int, min_score: float, geom: str,
            maker_targets: bool, cache: dict[int, Any]) -> dict[str, Any]:
    if seed not in cache:
        cache[seed] = pipeline.run(days=days, seed=seed, tf=tf)
    res = cache[seed]
    r = BT.run_backtest(
        res, signal_cfg=S.SignalConfig(min_edge_score=min_score),
        exit_cfg=GEOMETRIES[geom], cohort_curves=res.stats.get("cohort_curves", {}),
        bt_cfg=BT.BacktestConfig(target_exits_are_maker=maker_targets))
    eq = r.equity_curve
    start = eq[0].equity if eq else 0.0
    end = eq[-1].equity if eq else start
    return {
        "seed": seed,
        "gross_r": [t.gross_pnl / t.risk_cash for t in r.trades if t.risk_cash > 0],
        "fric_r": [t.costs / t.risk_cash for t in r.trades if t.risk_cash > 0],
        "net_r": [t.r_multiple for t in r.trades if t.risk_cash > 0],
        "bp": [(t.costs / t.notional * 1e4) for t in r.trades if t.notional > 0],
        "wins": sum(t.net_pnl for t in r.trades if t.net_pnl > 0),
        "losses": abs(sum(t.net_pnl for t in r.trades if t.net_pnl <= 0)),
        "net_cash": sum(t.net_pnl for t in r.trades),
        "start": start, "end": end,
        "max_dd_pct": r.metrics["risk"]["max_drawdown_pct"],
        "n": len(r.trades),
    }


def pooled(runs: Sequence[dict[str, Any]], n_boot: int, seed: int) -> dict[str, Any]:
    def flat(key: str) -> list[float]:
        return [v for r in runs for v in r[key]]

    g, f, n_ = flat("gross_r"), flat("fric_r"), flat("net_r")
    if not n_:
        return {"n": 0}
    wins = sum(r["wins"] for r in runs)
    losses = sum(r["losses"] for r in runs)
    net_cash = sum(r["net_cash"] for r in runs)
    start = sum(r["start"] for r in runs)
    lo, hi = _ci(n_, n_boot, seed)
    glo, ghi = _ci(g, n_boot, seed)
    sd = stdev(n_)
    return {
        "n": len(n_),
        "gross_r": mean(g), "fric_r": mean(f), "net_r": mean(n_),
        "gross_r_ci": [glo, ghi], "net_r_ci": [lo, hi],
        "net_r_se": sd / len(n_) ** 0.5 if len(n_) > 1 else float("nan"),
        "net_r_t": (mean(n_) / (sd / len(n_) ** 0.5))
        if len(n_) > 2 and sd > 0 else float("nan"),
        "gross_r_t": (mean(g) / (stdev(g) / len(g) ** 0.5))
        if len(g) > 2 and stdev(g) > 0 else float("nan"),
        "bp_per_trade": mean(flat("bp")) if flat("bp") else 0.0,
        "profit_factor": (wins / losses) if losses > 0 else float("inf"),
        "pooled_return_pct": (net_cash / start * 100.0) if start > 0 else 0.0,
        "seeds_positive": sum(1 for r in runs if r["net_cash"] > 0),
        "n_seeds": len(runs),
        "mean_max_dd_pct": mean([r["max_dd_pct"] for r in runs]),
        "fric_to_gross": (mean(f) / abs(mean(g))) if abs(mean(g)) > 1e-12 else float("inf"),
        "mde_trades": validation.minimum_detectable_trades(
            effect_r=0.10, sd_r=sd if sd > 0 else 1.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=20, help="how many independent windows")
    ap.add_argument("--seed0", type=int, default=7, help="first seed")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--thresholds", default="0.45,0.75,0.80",
                    help="comma-separated min_edge_score values")
    ap.add_argument("--geometries", default=",".join(GEOMETRIES),
                    help="comma-separated exit geometries")
    ap.add_argument("--taker-targets", action="store_true",
                    help="charge target legs as taker (conservative fill model)")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--json", default="", help="write the raw pooled stats here")
    a = ap.parse_args()

    seeds = [a.seed0 + 2 * i for i in range(a.seeds)]      # spread the seeds out
    thrs = [float(x) for x in a.thresholds.split(",") if x.strip()]
    geoms = [g.strip() for g in a.geometries.split(",") if g.strip()]
    maker = not a.taker_targets

    print(f"cost attribution — {len(seeds)} independent {a.days}-day windows "
          f"@{a.tf}m, targets={'maker' if maker else 'taker'}")
    print(f"pooled over {len(seeds) * len(thrs) * len(geoms)} runs; "
          f"bootstrap n={a.n_boot}\n")
    hdr = (f"{'thr':>5s} {'exit geometry':24s} | {'n':>5s} | {'grossR':>7s} "
           f"{'t':>6s} | {'fricR':>6s} | {'netR':>7s} {'95% CI':>18s} | "
           f"{'PF':>5s} | {'ret%':>7s} | {'bp':>5s} | {'+seeds':>7s}")
    print(hdr)
    print("-" * len(hdr))

    out: list[dict[str, Any]] = []
    cache: dict[int, Any] = {}
    for thr in thrs:
        for geom in geoms:
            runs = [collect(sd, a.days, a.tf, thr, geom, maker, cache) for sd in seeds]
            p = pooled(runs, a.n_boot, seed=1)
            p.update({"threshold": thr, "geometry": geom, "targets": "maker" if maker
                      else "taker"})
            out.append(p)
            if not p.get("n"):
                print(f"{thr:5.2f} {geom:24s} |     0 | (no trades)")
                continue
            ci = f"[{p['net_r_ci'][0]:+.3f},{p['net_r_ci'][1]:+.3f}]"
            mde = p["mde_trades"]
            mde_n = mde.get("n_trades") if isinstance(mde, dict) else mde
            enough = "ok" if p["n"] >= float(mde_n or 1e9) else "LOW POWER"
            print(f"{thr:5.2f} {geom:24s} | {p['n']:5d} | {p['gross_r']:+7.4f} "
                  f"{p['gross_r_t']:+6.2f} | {p['fric_r']:6.4f} | {p['net_r']:+7.4f} "
                  f"{ci:>18s} | {p['profit_factor']:5.2f} | "
                  f"{p['pooled_return_pct']:+7.2f} | {p['bp_per_trade']:5.1f} | "
                  f"{p['seeds_positive']:3d}/{p['n_seeds']:<3d}")
            if enough == "LOW POWER":
                print(f"{'':5s} {'':24s}   -> n={p['n']} < {mde_n} trades needed for "
                      f"80% power at 0.10R: treat as unvalidated")

    # the decision rule, stated explicitly
    best = max((p for p in out if p.get("n")), key=lambda p: p["net_r"], default=None)
    if best:
        print()
        print("verdict")
        if best["gross_r"] <= 0:
            print("  gross expectancy is not positive: the SIGNAL is the binding "
                  "constraint.  Cost engineering will not help.")
        elif best["fric_r"] > best["gross_r"]:
            print(f"  cost-bound: friction {best['fric_r']:.3f}R exceeds the gross edge "
                  f"{best['gross_r']:+.3f}R ({best['fric_to_gross'] * 100:.0f}% of it).")
            print("  Levers that move friction per R: wider stops (R grows), fewer "
                  "exit legs,")
            print("  resting (maker) target orders, lower-commission venue. Adding "
                  "filters does not.")
        else:
            print(f"  gross edge {best['gross_r']:+.3f}R exceeds friction "
                  f"{best['fric_r']:.3f}R: net {best['net_r']:+.3f}R.")
        print(f"  best configuration here: thr={best['threshold']} "
              f"geom={best['geometry']} targets={best['targets']} "
              f"(n={best['n']}, PF {best['profit_factor']:.2f})")

    if a.json:
        parent = os.path.dirname(os.path.abspath(a.json))
        os.makedirs(parent, exist_ok=True)
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=2, default=str)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
