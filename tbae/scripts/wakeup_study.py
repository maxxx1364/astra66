"""Event study: does the daily wake-up signal beat picking liquid coins at random?

    python3 scripts/wakeup_study.py --start 2023-06-01 --out reports/wakeup

1. Downloads daily klines for every USDT coin pair on Binance — *including
   delisted ones* (status BREAK), which reduces survivorship bias: the coins
   that died are in the sample too.  Cached under ``--cache``.
2. Computes features/signals with ``live.wakeup`` (causal: signal on day t,
   entry at the open of t+1).
3. Simulates one trade rule (+15 % target / -8 % stop / 14 days) on
   (a) every signal, (b) every liquid symbol-day (the random baseline),
   (c) the top 3 signals per day (what a small account could actually take).
4. Reports net results under three fee levels, by year and by market regime,
   with bootstrap confidence intervals clustered by signal day (signals bunch
   on the same days, so per-trade CIs would be too narrow).

Nothing is tuned here: the rule set and trade rule are the defaults in
``live/wakeup.py``.  The per-condition table is descriptive only — picking the
best row from it after the fact would be curve fitting.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.wakeup import (CONFIRMING, BinanceDaily, TradeRule, WakeupConfig,  # noqa: E402
                         features, klines_frame, signals, simulate)

FEES = {  # per side: (fee, slippage)
    "tabdeal_base": (0.0035, 0.001),
    "nobitex_usdt": (0.0013, 0.001),
    "gross_no_cost": (0.0, 0.0),
}


def load_all(data: BinanceDaily, start_ms: int, cache: str) -> dict[str, pd.DataFrame]:
    os.makedirs(cache, exist_ok=True)
    syms = data.symbols(include_delisted=True)
    out: dict[str, pd.DataFrame] = {}
    for n, sym in enumerate(syms, 1):
        path = os.path.join(cache, f"{sym}_1d.json.gz")
        rows = None
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 20 * 3600:
            with gzip.open(path, "rt") as fh:
                rows = json.load(fh)
        if rows is None:
            try:
                rows = data.get("/api/v3/klines", symbol=sym, interval="1d",
                                startTime=start_ms, limit=1000)
            except Exception as e:  # noqa: BLE001
                print(f"  {sym}: {e}", file=sys.stderr)
                continue
            with gzip.open(path, "wt") as fh:
                json.dump(rows, fh)
        if len(rows) >= 80:
            out[sym] = klines_frame(rows)
        if n % 50 == 0:
            print(f"  {n}/{len(syms)} symbols", file=sys.stderr)
    return out


def cluster_ci(values: np.ndarray, groups: np.ndarray, n_boot: int = 2000,
               seed: int = 7) -> tuple[float, float]:
    """95 % CI of the mean, resampling whole signal days."""
    if len(values) < 5:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"v": values, "g": groups})
    sums = df.groupby("g")["v"].agg(["sum", "count"])
    s, c = sums["sum"].to_numpy(), sums["count"].to_numpy()
    k = len(s)
    idx = rng.integers(0, k, size=(n_boot, k))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def summarise(trades: pd.DataFrame, rule: TradeRule) -> dict[str, Any]:
    if trades.empty:
        return {"n": 0}
    out: dict[str, Any] = {"n": int(len(trades)), "days": int(trades["ts"].nunique()),
                           "target_rate": float((trades["exit"] == "target").mean()),
                           "stop_rate": float((trades["exit"] == "stop").mean()),
                           "up15_within_14d": float((trades["max_up"] >= rule.target).mean()),
                           "mean_gross": float(trades["gross"].mean())}
    for name, (fee, slip) in FEES.items():
        net = trades["gross"] - 2 * (fee + slip)
        lo, hi = cluster_ci(net.to_numpy(), trades["ts"].to_numpy())
        out[name] = {"mean_net": float(net.mean()), "ci95": [lo, hi],
                     "win_rate": float((net > 0).mean())}
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = WakeupConfig()
    rule = TradeRule()
    start_ms = int(pd.Timestamp(args.start, tz="UTC").timestamp() * 1000)
    data = BinanceDaily(spacing_s=args.spacing)
    print("downloading daily klines ...", file=sys.stderr)
    frames = load_all(data, start_ms - 90 * 86_400_000, args.cache)
    if "BTCUSDT" not in frames:
        raise SystemExit("BTCUSDT missing")
    btc = frames["BTCUSDT"]
    btc_close = btc.set_index("ts")["close"]
    btc_ma50 = btc_close.rolling(50).mean()
    bull = (btc_close > btc_ma50)

    sig_rows, base_rows, cond_rows = [], [], []
    for sym, df in frames.items():
        df = df.reset_index(drop=True)
        f = features(df, btc_close)
        s = signals(f, cfg)
        last_sig = -10_000
        for i in range(len(df) - 1):
            ts = int(df["ts"].iat[i])
            if ts < start_ms or not s["eligible"].iat[i]:
                continue
            tr = simulate(df, i + 1, rule)
            if tr is None:
                continue
            row = {"symbol": sym, "ts": ts, **tr, "bull": bool(bull.get(ts, False)),
                   "score": float(s["score"].iat[i]), "confirm": int(s["confirm"].iat[i])}
            base_rows.append(row)
            cond_rows.append({**{k: bool(s[k].iat[i]) for k in
                                 ("rvol", "not_jumped", *CONFIRMING)},
                              "gross": tr["gross"], "ts": ts})
            # one live trade per symbol at a time: skip signals inside a holding period
            if s["signal"].iat[i] and i - last_sig >= rule.max_days:
                sig_rows.append(row)
                last_sig = i

    base = pd.DataFrame(base_rows)
    sig = pd.DataFrame(sig_rows)
    top3 = (sig.sort_values(["ts", "score"], ascending=[True, False]).groupby("ts").head(3)
            if not sig.empty else sig)
    res: dict[str, Any] = {
        "generated": pd.Timestamp.utcnow().isoformat(),
        "window": [args.start, pd.to_datetime(base["ts"].max(), unit="ms").date().isoformat()],
        "symbols": len(frames), "rule": {"target": rule.target, "stop": rule.stop,
                                          "max_days": rule.max_days},
        "config": vars(cfg) if hasattr(cfg, "__dict__") else {k: getattr(cfg, k) for k in cfg.__slots__},
        "signals": summarise(sig, rule),
        "signals_top3_per_day": summarise(top3, rule),
        "baseline_all_liquid_days": summarise(base, rule),
        "by_year": {}, "by_regime": {}, "by_confirm": {}, "conditions": {},
    }
    if not sig.empty:
        sig["year"] = pd.to_datetime(sig["ts"], unit="ms").dt.year
        base["year"] = pd.to_datetime(base["ts"], unit="ms").dt.year
        for y in sorted(sig["year"].unique()):
            res["by_year"][str(y)] = {"signals": summarise(sig[sig["year"] == y], rule),
                                      "baseline": summarise(base[base["year"] == y], rule)}
        for name, flag in (("btc_above_ma50", True), ("btc_below_ma50", False)):
            res["by_regime"][name] = {"signals": summarise(sig[sig["bull"] == flag], rule),
                                      "baseline": summarise(base[base["bull"] == flag], rule)}
        for k in sorted(sig["confirm"].unique()):
            res["by_confirm"][str(int(k))] = summarise(sig[sig["confirm"] == k], rule)
    cond = pd.DataFrame(cond_rows)
    for k in ("rvol", "not_jumped", *CONFIRMING):
        on = cond[cond[k]]
        res["conditions"][k] = {"n": int(len(on)), "mean_gross": float(on["gross"].mean()),
                                "baseline_mean_gross": float(cond["gross"].mean())}
    return res


def pct(x: float) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.2f}%"


def markdown(res: dict[str, Any]) -> str:
    L = [f"# Wake-up scanner study — {res['window'][0]} to {res['window'][1]}", "",
         f"{res['symbols']} Binance USDT coin pairs (delisted included). Rule: "
         f"+{res['rule']['target']:.0%} target / -{res['rule']['stop']:.0%} stop / "
         f"{res['rule']['max_days']} days, entry next open, stop first if both in one bar.", "",
         "| set | n | signal days | target hit | stop hit | +15% within 14d | net (Tabdeal) | 95% CI | net (Nobitex) | gross |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for key, label in (("signals", "all signals"), ("signals_top3_per_day", "top 3 per day"),
                       ("baseline_all_liquid_days", "random liquid coin-day")):
        r = res[key]
        if not r.get("n"):
            L.append(f"| {label} | 0 | | | | | | | | |")
            continue
        t, nb = r["tabdeal_base"], r["nobitex_usdt"]
        L.append(f"| {label} | {r['n']} | {r['days']} | {r['target_rate']:.1%} | {r['stop_rate']:.1%} | "
                 f"{r['up15_within_14d']:.1%} | {pct(t['mean_net'])} | "
                 f"[{pct(t['ci95'][0])}, {pct(t['ci95'][1])}] | {pct(nb['mean_net'])} | "
                 f"{pct(r['mean_gross'])} |")
    for title, block in (("By year", "by_year"), ("By market regime (BTC vs its 50-day MA)", "by_regime")):
        L += ["", f"## {title}", "", "| | signals n | signals net (Tabdeal) | baseline net (Tabdeal) |",
              "|---|---|---|---|"]
        for k, v in res[block].items():
            s, b = v["signals"], v["baseline"]
            L.append(f"| {k} | {s.get('n', 0)} | "
                     f"{pct(s['tabdeal_base']['mean_net']) if s.get('n') else '—'} | "
                     f"{pct(b['tabdeal_base']['mean_net']) if b.get('n') else '—'} |")
    L += ["", "## Per condition (descriptive only — do not pick the best row)", "",
          "| condition | days true | mean gross when true | all liquid days |", "|---|---|---|---|"]
    for k, v in res["conditions"].items():
        L.append(f"| {k} | {v['n']} | {pct(v['mean_gross'])} | {pct(v['baseline_mean_gross'])} |")
    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2023-06-01")
    p.add_argument("--cache", default="data/wakeup_cache")
    p.add_argument("--out", default="reports/wakeup")
    p.add_argument("--spacing", type=float, default=0.12)
    a = p.parse_args()
    res = run(a)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out + ".json", "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    md = markdown(res)
    with open(a.out + ".md", "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
