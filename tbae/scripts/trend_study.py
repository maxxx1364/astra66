"""Study: spot trend-following (enter after confirmation, trail the exit).

    python3 scripts/trend_study.py --cache data/wakeup_cache --out reports/trend

Uses the daily klines cached by ``wakeup_study.py`` (all Binance USDT coin
pairs, delisted included).  Reports per-trade results against a random-entry
baseline that uses the *same* exits, plus a small-account portfolio simulation
(at most 5 positions, 20 % of equity each, compounding, fees on every fill).
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.trend import TrendConfig, eligible, entry_signals, indicators, simulate  # noqa: E402
from live.wakeup import klines_frame  # noqa: E402

COSTS = {"tabdeal": 2 * (0.0035 + 0.001), "nobitex": 2 * (0.0013 + 0.001), "gross": 0.0}


def load(cache: str) -> dict[str, pd.DataFrame]:
    out = {}
    for p in glob.glob(os.path.join(cache, "*_1d.json.gz")):
        with gzip.open(p, "rt") as fh:
            rows = json.load(fh)
        if len(rows) >= 120:
            out[os.path.basename(p).split("_")[0]] = klines_frame(rows).reset_index(drop=True)
    return out


def cluster_ci(v: np.ndarray, g: np.ndarray, n_boot: int = 2000) -> list[float]:
    if len(v) < 5:
        return [float("nan"), float("nan")]
    d = pd.DataFrame({"v": v, "g": g}).groupby("g")["v"].agg(["sum", "count"])
    s, c = d["sum"].to_numpy(), d["count"].to_numpy()
    idx = np.random.default_rng(7).integers(0, len(s), (n_boot, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summary(t: pd.DataFrame) -> dict[str, Any]:
    if t.empty:
        return {"n": 0}
    out: dict[str, Any] = {"n": len(t), "median_days": float(t["days"].median()),
                           "stop_rate": float((t["exit"] == "stop").mean()),
                           "best_trade": float(t["gross"].max())}
    for k, cost in COSTS.items():
        net = t["gross"] - cost
        wins, losses = net[net > 0], net[net <= 0]
        out[k] = {"mean": float(net.mean()), "median": float(net.median()),
                  "ci95": cluster_ci(net.to_numpy(), t["week"].to_numpy()),
                  "win_rate": float((net > 0).mean()),
                  "avg_win": float(wins.mean()) if len(wins) else 0.0,
                  "avg_loss": float(losses.mean()) if len(losses) else 0.0,
                  "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")}
    # how much of the total comes from the top 5 % of trades
    g = t["gross"].sort_values(ascending=False)
    k = max(1, int(len(g) * 0.05))
    out["top5pct_share_of_total"] = float(g.iloc[:k].sum() / g.sum()) if g.sum() != 0 else float("nan")
    return out


def portfolio(trades: pd.DataFrame, cost: float, slots: int = 5) -> dict[str, Any]:
    """Take signals in date order (best volume ratio first), at most ``slots``
    open positions, each sized at 1/slots of equity at entry, fees on both fills."""
    t = trades.sort_values(["entry_ts", "vol_ratio"], ascending=[True, False])
    eq, open_pos, curve = 1.0, [], []
    for row in t.itertuples():
        # close positions that exited before this entry
        still = []
        for p in open_pos:
            if p["exit_ts"] <= row.entry_ts:
                eq += p["alloc"] * (1 + p["gross"]) * (1 - cost / 2) - p["alloc"]
                curve.append((p["exit_ts"], eq))
            else:
                still.append(p)
        open_pos = still
        if len(open_pos) >= slots:
            continue
        free = eq - sum(p["alloc"] for p in open_pos)
        alloc = min(eq / slots, free)
        if alloc <= 0:
            continue
        open_pos.append({"exit_ts": row.exit_ts, "gross": row.gross,
                         "alloc": alloc * (1 - cost / 2)})
        eq -= alloc * cost / 2
    for p in sorted(open_pos, key=lambda p: p["exit_ts"]):
        eq += p["alloc"] * (1 + p["gross"]) * (1 - cost / 2) - p["alloc"]
        curve.append((p["exit_ts"], eq))
    if not curve:
        return {"final": 1.0}
    c = pd.Series([v for _, v in curve], index=[k for k, _ in curve]).sort_index()
    dd = (c / c.cummax() - 1).min()
    years = (c.index[-1] - t["entry_ts"].min()) / (365 * 86_400_000)
    return {"final_equity_x": float(c.iloc[-1]), "max_drawdown": float(dd),
            "cagr": float(c.iloc[-1] ** (1 / years) - 1) if years > 0 and c.iloc[-1] > 0 else float("nan"),
            "years": float(years)}


def run(cache: str, start: str) -> dict[str, Any]:
    cfg = TrendConfig()
    frames = load(cache)
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    btc = frames["BTCUSDT"].set_index("ts")["close"]
    mkt = (btc > btc.rolling(cfg.market_ma).mean())
    rng = np.random.default_rng(11)
    sig_rows: dict[str, list] = {"filtered": [], "unfiltered": []}
    base_rows = []
    for sym, df in frames.items():
        x = indicators(df)
        ts = df["ts"].to_numpy()
        m_ok = mkt.reindex(ts).fillna(False).to_numpy()
        elig = eligible(x, cfg) & (ts >= start_ms)
        raw = entry_signals(df, x, cfg) & elig
        for name, sig in (("unfiltered", raw), ("filtered", raw & m_ok)):
            busy_until = -1
            for i in np.flatnonzero(sig):
                if i <= busy_until:
                    continue          # already holding this coin
                r = simulate(df, x, i, cfg)
                if r is None:
                    continue
                busy_until = i + r["days"]
                sig_rows[name].append({"symbol": sym, "ts": int(ts[i]), "bull": bool(m_ok[i]),
                                       "entry_ts": int(ts[i]) + 86_400_000,
                                       "exit_ts": int(ts[i]) + (r["days"] + 1) * 86_400_000,
                                       "vol_ratio": float(x["vol_ratio"].iat[i]), **r})
        # random baseline: ~3 % of eligible days, same exits, same market filter split
        for i in np.flatnonzero(elig & (rng.random(len(df)) < 0.03)):
            r = simulate(df, x, i, cfg)
            if r is not None:
                base_rows.append({"symbol": sym, "ts": int(ts[i]), "bull": bool(m_ok[i]), **r})
    res: dict[str, Any] = {"symbols": len(frames), "start": start}
    for name in ("filtered", "unfiltered"):
        t = pd.DataFrame(sig_rows[name])
        t["week"] = t["ts"] // (7 * 86_400_000)
        t["year"] = pd.to_datetime(t["ts"], unit="ms").dt.year
        res[name] = summary(t)
        res[name]["by_year"] = {str(y): summary(g) for y, g in t.groupby("year")}
        res[name]["portfolio"] = {k: portfolio(t, c) for k, c in COSTS.items()}
    b = pd.DataFrame(base_rows)
    b["week"] = b["ts"] // (7 * 86_400_000)
    res["baseline_random_entry"] = summary(b)
    res["baseline_random_entry_bull_only"] = summary(b[b["bull"]])
    btc_bh = frames["BTCUSDT"]
    bb = btc_bh[btc_bh["ts"] >= start_ms]
    res["btc_buy_and_hold"] = float(bb["close"].iloc[-1] / bb["open"].iloc[0] - 1)
    return res


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="data/wakeup_cache")
    p.add_argument("--start", default="2023-06-01")
    p.add_argument("--out", default="reports/trend")
    a = p.parse_args()
    res = run(a.cache, a.start)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out + ".json", "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    print(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
