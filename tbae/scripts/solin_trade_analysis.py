"""Analyse the per-trade log written by Solin_Pilot (InpLogTrades=true).

    python3 scripts/solin_trade_analysis.py path/to/solin_XAUUSD_PERIOD_H1_trades.csv [--split 2023-01-01]

1. Results per engine / entry type.
2. For every context feature: does it separate winners from losers?  Measured
   as AUC (0.5 = coin flip) separately on the TRAIN part (before --split) and
   the TEST part (after) — a feature only counts if it points the same way in both.
3. A single filter per stable feature, its threshold chosen on TRAIN only, then
   applied once to TEST.  Reports trades kept, R per trade and total R.
Nothing here edits the EA; the output is a shortlist of filters worth porting.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

FEATURES = ["hour", "weekday", "stateA", "stateB", "clsO", "clsP", "seg", "risk_atr", "atr_dr",
            "er30", "slope96", "dist96", "dist24", "cloud_w", "piv_dist", "touches", "respect",
            "rv", "rm", "delta", "ret12", "spread"]
CATEGORICAL = {"hour", "weekday", "stateA", "stateB", "clsO", "clsP", "seg"}


def auc(x: pd.Series, win: pd.Series) -> float:
    m = x.notna()
    x, win = x[m], win[m]
    a, b = x[win], x[~win]
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    r = pd.concat([a, b]).rank().to_numpy()
    return float((r[:len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)))


def summary(t: pd.DataFrame) -> str:
    if t.empty:
        return "n=0"
    r = t["r_multiple"]
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else float("inf")
    return (f"n={len(t):4d}  win={(r > 0).mean():5.1%}  R/trade={r.mean():+.3f}  "
            f"total R={r.sum():+7.1f}  PF={pf:4.2f}")


def best_threshold(train: pd.DataFrame, f: str, min_keep: float = 0.4) -> tuple[str, float] | None:
    """Keep trades with f >= q or f <= q (q from train deciles) maximising train R/trade,
    keeping at least ``min_keep`` of the trades (a filter, not a new strategy)."""
    x = train[f]
    best, best_r = None, train["r_multiple"].mean()
    for q in np.nanpercentile(x, np.arange(10, 100, 10)):
        for side in (">=", "<="):
            keep = x >= q if side == ">=" else x <= q
            if keep.mean() < min_keep:
                continue
            r = train.loc[keep, "r_multiple"].mean()
            if r > best_r:
                best, best_r = (side, float(q)), r
    return best


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--split", default=None, help="train/test boundary (default: 60%% of trades)")
    a = p.parse_args()
    t = pd.read_csv(a.csv)
    t["decision_time"] = pd.to_datetime(t["decision_time"], format="%Y.%m.%d %H:%M")
    t = t.sort_values("decision_time").reset_index(drop=True)
    split = pd.Timestamp(a.split) if a.split else t["decision_time"].iloc[int(len(t) * 0.6)]
    train, test = t[t["decision_time"] < split], t[t["decision_time"] >= split]
    print(f"{len(t)} trades, {t['decision_time'].min():%Y-%m-%d} .. {t['decision_time'].max():%Y-%m-%d}; "
          f"TRAIN < {split:%Y-%m-%d} <= TEST")
    print(f"\nALL    {summary(t)}\nTRAIN  {summary(train)}\nTEST   {summary(test)}")
    print("\nper engine / type (TRAIN | TEST)")
    for (e, ty), g in t.groupby(["engine", "type"]):
        print(f"  {e} {ty:8s} {summary(g[g['decision_time'] < split])}  |  {summary(g[g['decision_time'] >= split])}")

    win_tr, win_te = train["r_multiple"] > 0, test["r_multiple"] > 0
    print("\nfeature separation (AUC; 0.5 = none). Stable = same side of 0.5 by >= 0.05 in both parts")
    stable = []
    for f in FEATURES:
        if f in CATEGORICAL:
            continue
        a_tr, a_te = auc(train[f], win_tr), auc(test[f], win_te)
        ok = (not np.isnan(a_tr) and not np.isnan(a_te) and (a_tr - 0.5) * (a_te - 0.5) > 0
              and abs(a_tr - 0.5) >= 0.05 and abs(a_te - 0.5) >= 0.05)
        print(f"  {f:10s} train {a_tr:.2f}  test {a_te:.2f}  {'STABLE' if ok else ''}")
        if ok:
            stable.append(f)

    print("\ncategorical: R/trade by value (TRAIN | TEST), values with >= 15 train trades")
    for f in sorted(CATEGORICAL):
        rows = []
        for v, g in train.groupby(f):
            if len(g) < 15:
                continue
            gt = test[test[f] == v]
            rows.append(f"{v}:{g['r_multiple'].mean():+.2f}|{gt['r_multiple'].mean() if len(gt) else float('nan'):+.2f}")
        print(f"  {f:8s} " + "  ".join(rows))

    print("\nsingle-feature filters: threshold from TRAIN, applied once to TEST")
    print(f"  baseline TEST: {summary(test)}")
    for f in stable:
        th = best_threshold(train, f)
        if th is None:
            continue
        side, q = th
        keep = test[f] >= q if side == ">=" else test[f] <= q
        print(f"  {f} {side} {q:.4g}:  TEST {summary(test[keep])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
