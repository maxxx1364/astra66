#!/usr/bin/env python3
"""Screen the best-documented systematic edges on the same data and cost model.

    python3 scripts/edge_screen.py --out ../reports/edge_screen

Every rule below was fixed before looking at this data; nothing is tuned.

* **TSMOM-7 / TSMOM-30** — time-series momentum (Moskowitz, Ooi & Pedersen
  2012; for crypto Liu & Tsyvinski 2021): hold the sign of the trailing 7 or
  30-day return, rebalanced daily.
* **Donchian 20/10** — the Turtle breakout: long on a close above the prior
  20-day high, out on a close below the prior 10-day low; short mirrored.
* **Reversal-1** — short-term reversal: hold minus the sign of yesterday.
* **Long-only** — buy and hold, the drift every timing rule must beat.

Positions are vol-targeted (``--vol-target`` annualised, trailing 30-day
realised vol, leverage capped at 2) and decided at the daily close for the
next day.  Costs are taker 2 bp + slippage 2 bp on every unit of turnover.
Results are per symbol and for the equal-weight 4-symbol portfolio, for each
half of the sample (split at ``--split``).

Two combination checks use trades the project already produced:
* the TBAE strategy's trades with the flow veto
  (``--tbae-trades`` = the ``*_trades.csv`` of the latest backtest);
* the order-block trades of ``scripts/setup_backtest.py`` (``--setup-trades``);
each tagged by whether the trade's side agrees with the 30-day trend at entry.

A last table reports the hour-of-day mean return in each half, and how well
the first half's hourly pattern predicts the second's.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import glob
import json
import math
import os
import sys
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import flow_state as fs                                # noqa: E402
from engine.feeds import CsvFeed                                   # noqa: E402

COST = 4.0 / 1e4     # taker 2 bp + slippage 2 bp per unit of turnover
DAY_MS = 86_400_000


def perf(r: np.ndarray, periods: float = 365.0) -> dict[str, Any]:
    r = r[np.isfinite(r)]
    if len(r) < 20:
        return {"n": int(len(r))}
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(eq)
    mu, sd = r.mean(), r.std(ddof=1)
    return {"n": int(len(r)), "ann_ret": float((eq[-1]) ** (periods / len(r)) - 1),
            "ann_vol": float(sd * math.sqrt(periods)),
            "sharpe": float(mu / sd * math.sqrt(periods)) if sd > 0 else None,
            "t": float(mu / sd * math.sqrt(len(r))) if sd > 0 else None,
            "max_dd": float(dd.max())}


def signals(c: np.ndarray, h: np.ndarray, lo: np.ndarray) -> dict[str, np.ndarray]:
    n = len(c)
    out: dict[str, np.ndarray] = {}
    for L in (7, 30):
        s = np.zeros(n)
        s[L:] = np.sign(c[L:] / c[:-L] - 1)
        out[f"TSMOM-{L}"] = s
    d = np.zeros(n)
    pos = 0.0
    for t in range(20, n):
        if pos <= 0 and c[t] > h[t - 20:t].max():
            pos = 1.0
        elif pos >= 0 and c[t] < lo[t - 20:t].min():
            pos = -1.0
        elif pos > 0 and c[t] < lo[t - 10:t].min():
            pos = 0.0
        elif pos < 0 and c[t] > h[t - 10:t].max():
            pos = 0.0
        d[t] = pos
    out["Donchian-20/10"] = d
    rv = np.zeros(n)
    rv[1:] = -np.sign(c[1:] / c[:-1] - 1)
    out["Reversal-1"] = rv
    out["Long-only"] = np.ones(n)
    return out


def run_rule(sig: np.ndarray, c: np.ndarray, vol_target: float) -> np.ndarray:
    """Daily net returns: weight decided at close t, earns the return t -> t+1."""
    n = len(c)
    ret = np.zeros(n)
    ret[1:] = c[1:] / c[:-1] - 1
    rvol = np.full(n, np.nan)
    for t in range(30, n):
        rvol[t] = ret[t - 29:t + 1].std(ddof=1) * math.sqrt(365)
    w = np.where(np.isfinite(rvol) & (rvol > 0), np.clip(vol_target / rvol, 0, 2.0), 0.0) * sig
    out = np.full(n, np.nan)
    prev = 0.0
    for t in range(30, n - 1):
        out[t + 1] = w[t] * ret[t + 1] - abs(w[t] - prev) * COST
        prev = w[t]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--data-dir", default="data/binance")
    ap.add_argument("--split", default="2025-05-22")
    ap.add_argument("--vol-target", type=float, default=0.30)
    ap.add_argument("--tbae-trades", default="../reports/latest/veto")
    ap.add_argument("--setup-trades", default="../reports/setups/setup_trades.json")
    ap.add_argument("--out", default="../reports/edge_screen")
    a = ap.parse_args()
    cut = int(dt.datetime.fromisoformat(a.split).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    os.makedirs(a.out, exist_ok=True)

    daily: dict[str, Any] = {}
    hourly: dict[str, Any] = {}
    rule_rets: dict[str, dict[str, np.ndarray]] = {}
    for sym in [s.strip().upper() for s in a.symbols.split(",") if s.strip()]:
        mins = CsvFeed(os.path.join(a.data_dir, f"{sym}_1m.csv.gz")).load()
        d = [b for b in fs.flow_bars(mins, 1440)]
        hb = fs.flow_bars(mins, 60)
        del mins
        d = d[1:-1]                                    # drop partial first/last day
        ts = np.array([b.ts for b in d])
        c = np.array([b.close for b in d])
        h = np.array([b.high for b in d])
        lo = np.array([b.low for b in d])
        daily[sym] = {"ts": ts, "c": c}
        hourly[sym] = hb
        rule_rets[sym] = {name: run_rule(sig, c, a.vol_target) for name, sig in signals(c, h, lo).items()}
        print(f"[{sym}] {len(d)} days")

    # ---- rules: per symbol and equal-weight portfolio, by half
    report: dict[str, Any] = {"args": vars(a), "rules": {}, "combos": {}, "hourly": {}}
    syms = list(rule_rets)
    names = list(next(iter(rule_rets.values())).keys())
    ts_ref = daily[syms[0]]["ts"]
    for name in names:
        rows = {}
        for half, mask_fn in (("IS", lambda t: t < cut), ("OOS", lambda t: t >= cut), ("ALL", lambda t: t > 0)):
            per = {}
            port = []
            for s in syms:
                m = np.array([mask_fn(t) for t in daily[s]["ts"]])
                per[s] = perf(rule_rets[s][name][m])
            mlen = min(len(daily[s]["ts"]) for s in syms)
            stack = np.vstack([rule_rets[s][name][:mlen] for s in syms])
            m = np.array([mask_fn(t) for t in ts_ref[:mlen]])
            port = np.nanmean(stack, axis=0)[m]
            rows[half] = {"portfolio": perf(port), "symbols": per}
        report["rules"][name] = rows

    # ---- trend alignment of existing trades
    def trend_sign(sym: str, ts_ms: int, L: int = 30) -> int:
        dts = daily[sym]["ts"]
        k = bisect.bisect_right(dts, ts_ms - DAY_MS) - 1       # last daily close before entry day
        if k < L:
            return 0
        cc = daily[sym]["c"]
        return int(np.sign(cc[k] / cc[k - L] - 1))

    def tag(rows: list[tuple[str, int, int, float, int]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for label in ("aligned", "against"):
            for half in ("IS", "OOS"):
                r = [x[3] for x in rows if (x[4] == x[2]) == (label == "aligned") and x[4] != 0
                     and ((x[1] < cut) == (half == "IS"))]
                if r:
                    arr = np.array(r)
                    out[f"{label}|{half}"] = {"n": len(r), "mean_r": float(arr.mean()),
                                              "se": float(arr.std(ddof=1) / math.sqrt(len(r))) if len(r) > 1 else None}
        return out

    tb = []
    for p in glob.glob(os.path.join(a.tbae_trades, "*_trades.csv")):
        sym = os.path.basename(p).split("_")[0]
        if sym not in daily:
            continue
        for r in csv.DictReader(open(p)):
            ts_ms = int(float(r["entry_ts"]))
            side = 1 if r["side"].lower() in ("long", "1", "buy") else -1
            tb.append((sym, ts_ms, side, float(r["r_multiple"]), trend_sign(sym, ts_ms)))
    report["combos"]["tbae_veto_trades_vs_30d_trend"] = tag(tb)
    if os.path.exists(a.setup_trades):
        st = json.load(open(a.setup_trades))["trades"]
        for kind in ("order_block", "trendline3"):
            rows = [(t["symbol"], t["signal_ts"], t["side"], t["r"], trend_sign(t["symbol"], t["signal_ts"]))
                    for t in st if t["kind"] == kind and t["symbol"] in daily]
            report["combos"][f"{kind}_vs_30d_trend"] = tag(rows)

    # ---- hour-of-day seasonality: does the first half's pattern predict the second's?
    for s in syms:
        hb = hourly[s]
        by: dict[str, list[list[float]]] = {"IS": [[] for _ in range(24)], "OOS": [[] for _ in range(24)]}
        for b in hb:
            hr = (b.ts // 3_600_000) % 24
            by["IS" if b.ts < cut else "OOS"][hr].append(b.close / b.open - 1)
        mi = np.array([np.mean(x) if x else 0 for x in by["IS"]])
        mo = np.array([np.mean(x) if x else 0 for x in by["OOS"]])
        report["hourly"][s] = {"is_bp": (mi * 1e4).round(2).tolist(), "oos_bp": (mo * 1e4).round(2).tolist(),
                               "corr_is_oos": float(np.corrcoef(mi, mo)[0, 1])}

    with open(os.path.join(a.out, "edge_screen.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=float)

    f = lambda x, d=2: "—" if x is None else f"{x:+.{d}f}"      # noqa: E731
    print("\nRULES (vol-targeted 30%, costs in) — equal-weight portfolio of 4")
    for name, rows in report["rules"].items():
        line = "  ".join(f"{h}: SR {f(rows[h]['portfolio'].get('sharpe'))} ret {f(100 * rows[h]['portfolio'].get('ann_ret', 0), 1)}% "
                         f"DD {100 * rows[h]['portfolio'].get('max_dd', 0):.0f}%" for h in ("IS", "OOS", "ALL"))
        print(f"  {name:15s} {line}")
        sy = "  ".join(f"{s[:3]} {f(rows['ALL']['symbols'][s].get('sharpe'))}" for s in syms)
        print(f"  {'':15s} per-symbol Sharpe (all): {sy}")
    print("\nCOMBOS — trades whose side agrees / disagrees with the 30-day trend")
    for k, v in report["combos"].items():
        print(f"  {k}")
        for kk, vv in v.items():
            print(f"     {kk:12s} n={vv['n']:5d} E[R]={vv['mean_r']:+.3f}±{(vv['se'] or 0):.3f}")
    print("\nHOUR-OF-DAY — correlation of first-half and second-half hourly mean returns")
    print("  " + "  ".join(f"{s}: {v['corr_is_oos']:+.2f}" for s, v in report["hourly"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
