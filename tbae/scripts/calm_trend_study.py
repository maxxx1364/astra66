"""Calm-trend study: the spot trend rule plus filters against excitement and junk.

Protocol (fixed before running):
  * candidates = trend entry rule (live/trend.py) with the BTC > MA50 filter
  * filters ("excitement" / "junk"):
        atr_pct_max       daily ATR % of price            (wild coins)
        rel_btc_max       30-day return minus BTC's        (already ran hot)
        dist_ema50_max    close / EMA50 - 1                (stretched)
        vol_ratio_max     signal-day volume / 20-day median (volume explosion = pump)
        day_move_max      signal-day candle                (chasing a candle)
        liq_min           20-day median quote volume, USDT  (thin, junk coins)
        age_min_days      days since listing                (fresh listings)
  * TRAIN 2023-06-01 .. 2024-12-31: grid search, objective = mean net per trade
    after Tabdeal costs, at least 80 trades.
  * TEST  2025-01-01 .. end: evaluated ONCE for (a) the train-best grid point and
    (b) a "moderate" preset written down before the search.
"""

from __future__ import annotations

import glob
import gzip
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.trend import TrendConfig, eligible, entry_signals, indicators, simulate  # noqa: E402
from live.wakeup import klines_frame  # noqa: E402

COST = 2 * (0.0035 + 0.001)          # Tabdeal taker + slippage, both sides
DAY = 86_400_000
TRAIN = ("2023-06-01", "2024-12-31")
TEST_START = "2025-01-01"

GRID = {
    "atr_pct_max": [0.04, 0.05, 0.06, 0.08, np.inf],
    "rel_btc_max": [0.0, 0.10, 0.20, np.inf],
    "dist_ema50_max": [0.10, 0.15, 0.20, np.inf],
    "vol_ratio_max": [3.0, 5.0, np.inf],
    "day_move_max": [0.08, 0.15, np.inf],
    "liq_min": [1e6, 5e6, 10e6],
    "age_min_days": [0, 180],
}
MODERATE = {"atr_pct_max": 0.06, "rel_btc_max": 0.10, "dist_ema50_max": 0.15,
            "vol_ratio_max": 5.0, "day_move_max": 0.15, "liq_min": 5e6, "age_min_days": 180}


def ms(d: str) -> int:
    return int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)


def candidates() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    cfg = TrendConfig()
    frames = {}
    for p in glob.glob("data/wakeup_cache/*_1d.json.gz"):
        with gzip.open(p, "rt") as fh:
            rows = json.load(fh)
        if len(rows) >= 120:
            frames[os.path.basename(p).split("_")[0]] = klines_frame(rows).reset_index(drop=True)
    btc = frames["BTCUSDT"].set_index("ts")["close"]
    mkt = btc > btc.rolling(cfg.market_ma).mean()
    first_ts_all = min(int(f["ts"].iat[0]) for f in frames.values())
    out = []
    for sym, df in frames.items():
        x = indicators(df)
        ts = df["ts"].to_numpy()
        c = df["close"].to_numpy()
        b = btc.reindex(ts).to_numpy()
        m_ok = mkt.reindex(ts).fillna(False).to_numpy()
        sig = entry_signals(df, x, cfg) & eligible(x, cfg) & m_ok & (ts >= ms(TRAIN[0]))
        listed_before = int(ts[0]) <= first_ts_all + 3 * DAY
        for i in np.flatnonzero(sig):
            if i < 30:
                continue
            r = simulate(df, x, i, cfg)
            if r is None or r["exit"] == "open_at_end":
                continue
            out.append({
                "symbol": sym, "i": i, "ts": int(ts[i]), "days": r["days"], "gross": r["gross"],
                "exit": r["exit"],
                "atr_pct": x["atr"].iat[i] / c[i],
                "rel_btc": (c[i] / c[i - 30]) - (b[i] / b[i - 30]),
                "dist_ema50": c[i] / x["ema_s"].iat[i] - 1,
                "vol_ratio": x["vol_ratio"].iat[i],
                "day_move": x["day_move"].iat[i],
                "liq": x["liq"].iat[i],
                "age": np.inf if listed_before else i,
            })
    return pd.DataFrame(out), frames


def apply(c: pd.DataFrame, p: dict) -> pd.DataFrame:
    m = ((c["atr_pct"] <= p["atr_pct_max"]) & (c["rel_btc"] <= p["rel_btc_max"])
         & (c["dist_ema50"] <= p["dist_ema50_max"]) & (c["vol_ratio"] <= p["vol_ratio_max"])
         & (c["day_move"] <= p["day_move_max"]) & (c["liq"] >= p["liq_min"])
         & (c["age"] >= p["age_min_days"]))
    t = c[m].sort_values(["symbol", "i"])
    keep, busy, last_sym = [], -1, None
    for row in t.itertuples():
        if row.symbol != last_sym:
            busy, last_sym = -1, row.symbol
        if row.i <= busy:
            continue
        keep.append(row.Index)
        busy = row.i + row.days
    return t.loc[keep]


def stats(t: pd.DataFrame) -> dict:
    if len(t) == 0:
        return {"n": 0}
    net = t["gross"] - COST
    wk = t["ts"] // (7 * DAY)
    d = pd.DataFrame({"v": net, "g": wk}).groupby("g")["v"].agg(["sum", "count"])
    s, n = d["sum"].to_numpy(), d["count"].to_numpy()
    idx = np.random.default_rng(7).integers(0, len(s), (2000, len(s)))
    boots = s[idx].sum(1) / n[idx].sum(1)
    w, l = net[net > 0], net[net <= 0]
    return {"n": int(len(t)), "mean": float(net.mean()), "median": float(net.median()),
            "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "win_rate": float((net > 0).mean()),
            "profit_factor": float(w.sum() / -l.sum()) if l.sum() < 0 else float("inf"),
            "avg_win": float(w.mean()) if len(w) else 0.0, "avg_loss": float(l.mean()) if len(l) else 0.0}


def portfolio(t: pd.DataFrame, slots: int = 5) -> dict:
    t = t.assign(entry=t["ts"] + DAY, exit=t["ts"] + (t["days"] + 1) * DAY).sort_values("entry")
    eq, pos, curve = 1.0, [], [(int(t["entry"].min()) if len(t) else 0, 1.0)]
    for r in t.itertuples():
        for p in [p for p in pos if p[0] <= r.entry]:
            eq += p[1] * p[2] - p[1] * COST / 2 * (1 + p[2])
            curve.append((p[0], eq))
        pos = [p for p in pos if p[0] > r.entry]
        if len(pos) < slots:
            alloc = eq / slots
            eq -= alloc * COST / 2                     # entry fee
            pos.append((r.exit, alloc, r.gross))
    for p in sorted(pos):
        eq += p[1] * p[2] - p[1] * COST / 2 * (1 + p[2])
        curve.append((p[0], eq))
    c = pd.Series([v for _, v in curve])
    return {"final_equity_x": float(eq), "max_drawdown": float((c / c.cummax() - 1).min())}


def main() -> int:
    c, frames = candidates()
    train = c[(c["ts"] >= ms(TRAIN[0])) & (c["ts"] <= ms(TRAIN[1]))]
    test = c[c["ts"] >= ms(TEST_START)]
    keys = list(GRID)
    best, best_p, tried = None, None, 0
    for combo in itertools.product(*GRID.values()):
        p = dict(zip(keys, combo))
        s = stats(apply(train, p))
        tried += 1
        if s["n"] >= 80 and (best is None or s["mean"] > best["mean"]):
            best, best_p = s, p
    btc = frames["BTCUSDT"]
    bt = btc[btc["ts"] >= ms(TEST_START)]
    res = {
        "candidates": {"train": len(train), "test": len(test)},
        "grid_points": tried,
        "no_filter": {"train": stats(apply(train, {k: (np.inf if k.endswith("max") else 0) for k in keys})),
                      "test": stats(apply(test, {k: (np.inf if k.endswith("max") else 0) for k in keys}))},
        "train_best": {"params": best_p, "train": best, "test": stats(apply(test, best_p)),
                       "train_portfolio": portfolio(apply(train, best_p)),
                       "test_portfolio": portfolio(apply(test, best_p))},
        "moderate_preset": {"params": MODERATE, "train": stats(apply(train, MODERATE)),
                            "test": stats(apply(test, MODERATE)),
                            "train_portfolio": portfolio(apply(train, MODERATE)),
                            "test_portfolio": portfolio(apply(test, MODERATE))},
        "btc_buy_and_hold_test": float(bt["close"].iloc[-1] / bt["open"].iloc[0] - 1),
        "test_trades_best": apply(test, best_p)[["symbol", "ts", "gross", "exit", "days"]]
        .assign(date=lambda d: pd.to_datetime(d["ts"], unit="ms").dt.date.astype(str))
        .drop(columns="ts").to_dict("records"),
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/calm_trend.json", "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "test_trades_best"}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
