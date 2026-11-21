#!/usr/bin/env python3
"""Backtest order blocks and trendline third touches on real data.

    python3 scripts/setup_backtest.py --tfs 60,240 --out ../reports/setups

For every symbol and chart timeframe the setups from
:mod:`engine.structure_setups` are traded one by one:

* **entries** — order blocks rest a limit at the proximal edge (maker fee),
  cancelled when a bar closes beyond the distal edge or the block expires;
  third touches enter at the next bar's open (taker fee + slippage);
* **exits** — stop, fixed target (``--target`` R, default 2), or a time stop
  after ``--max-hold`` bars at that bar's close;
* **fills and exits are resolved on the 1-minute path**: a chart bar is only
  opened up when it could have filled the order or touched the stop or the
  target; inside a minute that touches both, the stop is taken;
* **costs** — maker 1 bp for resting orders (entry limit, target), taker 2 bp
  plus 2 bp slippage for market orders (market entry, stop, time exit),
  charged in R: ``bps x price / risk``.

Every setup is tagged with the half of the sample it falls in (split at
``--split``), with the TBAE flow state of the last block closed by its signal
bar, and is paired with ``--controls`` random entries: same side, same stop
distance in ATR, same exits, on a random bar of the same half.  An edge is the
difference to that control, not the raw E[R].

Trades are simulated independently (several may overlap); the non-overlapping
subset — one open position per symbol and setup type — is reported too.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import random
import sys
from types import SimpleNamespace
from typing import Any, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import flow_state as fs                                # noqa: E402
from engine import structure_setups as ss                          # noqa: E402
from engine.feeds import CsvFeed                                   # noqa: E402

MAKER_BPS, TAKER_BPS, SLIP_BPS = 1.0, 2.0, 2.0


class Path:
    """Chart bars plus the 1-minute candles inside each of them."""

    def __init__(self, mins: Sequence[Any], tf: int) -> None:
        self.m = mins
        self.bars = fs.flow_bars(mins, tf)
        mts = [x.ts for x in mins]
        ms = tf * 60_000
        self.span: list[tuple[int, int]] = []
        for b in self.bars:
            lo = bisect.bisect_left(mts, b.ts)
            hi = bisect.bisect_left(mts, b.ts + ms)
            self.span.append((lo, hi))


def simulate(p: Path, st: ss.Setup, target_r: float, max_hold: int,
             market_from: int | None = None, stop_override: float | None = None) -> dict | None:
    """One trade; ``market_from``/``stop_override`` turn it into a control entry."""
    bars, m = p.bars, p.m
    side = st.side
    n = len(bars)
    stop = st.stop if stop_override is None else stop_override
    sig = st.signal_index if market_from is None else market_from
    entry_kind = "market" if market_from is not None else st.entry
    fill = fill_bar = fill_min = None

    if entry_kind == "market":
        fb = sig + 1
        if fb >= n:
            return None
        lo, hi = p.span[fb]
        if lo >= hi:
            return None
        fill, fill_bar, fill_min = m[lo].open, fb, lo
        entry_bps = TAKER_BPS + SLIP_BPS
    else:
        px = st.entry_price
        last = min(n - 1, st.expires_index if st.expires_index is not None else n - 1)
        for b in range(sig + 1, last + 1):
            bb = bars[b]
            touched = bb.low <= px if side > 0 else bb.high >= px
            if touched:
                lo, hi = p.span[b]
                for k in range(lo, hi):
                    mm = m[k]
                    if (side > 0 and mm.low <= px) or (side < 0 and mm.high >= px):
                        fill = min(mm.open, px) if side > 0 else max(mm.open, px)
                        fill_bar, fill_min = b, k
                        break
                if fill is not None:
                    break
            if st.cancel_level is not None and (
                    (side > 0 and bb.close < st.cancel_level) or (side < 0 and bb.close > st.cancel_level)):
                return {"status": "cancelled"}
        if fill is None:
            return {"status": "expired"}
        entry_bps = MAKER_BPS

    risk = (fill - stop) * side
    if risk <= 0:
        return {"status": "gapped"}
    target = fill + side * target_r * risk
    end_bar = min(n - 1, fill_bar + max_hold)
    exit_px = reason = exit_min = None

    def check_minute(k: int, first: bool) -> tuple[float, str] | None:
        mm = m[k]
        if not first:
            if (side > 0 and mm.open <= stop) or (side < 0 and mm.open >= stop):
                return mm.open, "stop"
            if (side > 0 and mm.open >= target) or (side < 0 and mm.open <= target):
                return mm.open, "target"
        if (side > 0 and mm.low <= stop) or (side < 0 and mm.high >= stop):
            return stop, "stop"
        if not first and ((side > 0 and mm.high >= target) or (side < 0 and mm.low <= target)):
            return target, "target"
        return None

    for b in range(fill_bar, end_bar + 1):
        bb = bars[b]
        lo, hi = p.span[b]
        start = fill_min if b == fill_bar else lo
        could = (b == fill_bar or (side > 0 and (bb.low <= stop or bb.high >= target))
                 or (side < 0 and (bb.high >= stop or bb.low <= target)))
        if could:
            for k in range(start, hi):
                r = check_minute(k, first=(k == fill_min))
                if r is not None:
                    exit_px, reason = r
                    exit_min = k
                    break
        if exit_px is not None:
            break
    if exit_px is None:
        exit_px, reason = bars[end_bar].close, "time"
        exit_min = p.span[end_bar][1] - 1

    gross = side * (exit_px - fill) / risk
    exit_bps = MAKER_BPS if reason == "target" else TAKER_BPS + SLIP_BPS
    cost = (entry_bps * fill + exit_bps * exit_px) / 1e4 / risk
    return {"status": "filled", "fill": fill, "fill_ts": m[fill_min].ts, "exit": exit_px,
            "exit_ts": m[exit_min].ts, "reason": reason, "risk": risk,
            "risk_atr": risk / st.atr if st.atr else None,
            "r_gross": gross, "r_cost": cost, "r": gross - cost,
            "bars_held": (exit_min - fill_min) // max(1, (p.span[fill_bar][1] - p.span[fill_bar][0]))}


def summarize(rs: list[float]) -> dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {"n": 0}
    mean = sum(rs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    pos = sum(x for x in rs if x > 0)
    neg = -sum(x for x in rs if x < 0)
    se = sd / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean_r": mean, "se": se, "t": (mean / se) if se else None,
            "win": sum(1 for x in rs if x > 0) / n, "pf": (pos / neg) if neg > 0 else None,
            "sum_r": sum(rs)}


def non_overlapping(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, busy_until = [], {}
    for t in sorted(trades, key=lambda x: x["fill_ts"]):
        key = (t["symbol"], t["tf"], t["kind"])
        if t["fill_ts"] >= busy_until.get(key, -1):
            out.append(t)
            busy_until[key] = t["exit_ts"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--data-dir", default="data/binance")
    ap.add_argument("--tfs", default="60,240")
    ap.add_argument("--target", type=float, default=2.0)
    ap.add_argument("--sensitivity", default="1,3", help="extra targets in R, reported as sensitivity")
    ap.add_argument("--max-hold", type=int, default=48)
    ap.add_argument("--controls", type=int, default=3)
    ap.add_argument("--split", default="2025-05-22")
    ap.add_argument("--flow-veto", default="balanced,explosive")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="../reports/setups")
    a = ap.parse_args()

    cfg = ss.SetupConfig().validate()
    cut = int(dt.datetime.fromisoformat(a.split).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    veto = {x.strip() for x in a.flow_veto.split(",") if x.strip()}
    rng = random.Random(a.seed)
    targets = [a.target] + [float(x) for x in a.sensitivity.split(",") if x.strip()]
    trades: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    os.makedirs(a.out, exist_ok=True)

    for sym in [s.strip().upper() for s in a.symbols.split(",") if s.strip()]:
        mins = CsvFeed(os.path.join(a.data_dir, f"{sym}_1m.csv.gz")).load()
        print(f"[{sym}] {len(mins):,} minutes")
        for tf in [int(x) for x in a.tfs.split(",") if x.strip()]:
            p = Path(mins, tf)
            ns = [SimpleNamespace(ts=b.ts, tf=tf, open=b.open, high=b.high, low=b.low, close=b.close,
                                  volume=b.volume, taker_buy_volume=(b.volume + b.delta) / 2)
                  for b in p.bars]
            flow = fs.states_for_bars(ns)
            atr = ss.atr_series([b.open for b in p.bars], [b.high for b in p.bars],
                                [b.low for b in p.bars], [b.close for b in p.bars], cfg.atr_period)
            halves = {"IS": [i for i, b in enumerate(p.bars) if b.ts < cut and atr[i]],
                      "OOS": [i for i, b in enumerate(p.bars) if b.ts >= cut and atr[i]]}
            setups = ss.order_blocks(p.bars, cfg) + ss.trendline_third_touches(p.bars, cfg)
            status: dict[str, int] = {}
            for st in setups:
                half = "IS" if p.bars[st.signal_index].ts < cut else "OOS"
                base = {"symbol": sym, "tf": tf, "kind": st.kind, "side": st.side, "half": half,
                        "signal_ts": p.bars[st.signal_index].ts, "flow": flow[st.signal_index]}
                for tr in targets:
                    res = simulate(p, st, tr, a.max_hold)
                    if res is None:
                        continue
                    if tr == a.target:
                        status[f"{st.kind}:{res['status']}"] = status.get(f"{st.kind}:{res['status']}", 0) + 1
                    if res["status"] != "filled":
                        continue
                    trades.append({**base, **res, "target_r": tr})
                    if tr != a.target:
                        continue
                    for _ in range(a.controls):
                        pool = halves[half]
                        r_i = pool[rng.randrange(len(pool) - 1)]
                        if r_i + 1 >= len(p.bars):
                            continue
                        dist = res["risk_atr"] * atr[r_i]
                        ref = p.bars[r_i].close
                        c = simulate(p, st, tr, a.max_hold, market_from=r_i,
                                     stop_override=ref - st.side * dist)
                        if c and c["status"] == "filled":
                            controls.append({**base, **c, "target_r": tr, "flow": flow[r_i]})
            counts[f"{sym}_{tf}"] = status
            print(f"  tf={tf}m setups={len(setups)} {status}")
        del mins

    # ---------------------------------------------------------------- report
    rep: dict[str, Any] = {"config": cfg.__dict__, "args": vars(a), "counts": counts, "tables": {}}
    prim = [t for t in trades if t["target_r"] == a.target]

    def table(rows: list[dict], ctrl: list[dict], keys: Sequence[str]) -> list[dict]:
        groups: dict[tuple, list[float]] = {}
        cgroups: dict[tuple, list[float]] = {}
        for t in rows:
            groups.setdefault(tuple(t[k] for k in keys), []).append(t["r"])
        for t in ctrl:
            cgroups.setdefault(tuple(t[k] for k in keys), []).append(t["r"])
        out = []
        for g in sorted(groups):
            s = summarize(groups[g])
            cs = summarize(cgroups.get(g, []))
            out.append({**dict(zip(keys, g)), **s, "control_mean_r": cs.get("mean_r"),
                        "edge_vs_control": (s["mean_r"] - cs["mean_r"]) if cs.get("n") else None})
        return out

    rep["tables"]["by_kind_tf_half"] = table(prim, controls, ["kind", "tf", "half"])
    rep["tables"]["by_kind_tf"] = table(prim, controls, ["kind", "tf"])
    rep["tables"]["by_kind_tf_symbol"] = table(prim, controls, ["kind", "tf", "symbol"])
    rep["tables"]["by_kind_tf_side"] = table(prim, controls, ["kind", "tf", "side"])
    rep["tables"]["by_kind_flow"] = table(prim, [], ["kind", "flow"])
    vet = [t for t in prim if t["flow"] not in veto]
    vctl = [t for t in controls if t["flow"] not in veto]
    rep["tables"]["veto_by_kind_tf_half"] = table(vet, vctl, ["kind", "tf", "half"])
    rep["tables"]["sensitivity"] = table(trades, [], ["kind", "tf", "target_r"])
    rep["tables"]["non_overlap_by_kind_tf"] = table(non_overlapping(prim), [], ["kind", "tf"])
    rep["tables"]["exit_reasons"] = table(prim, [], ["kind", "tf", "reason"])
    with open(os.path.join(a.out, "setup_backtest.json"), "w") as fh:
        json.dump(rep, fh, indent=1, default=float)
    with open(os.path.join(a.out, "setup_trades.json"), "w") as fh:
        json.dump({"trades": prim, "controls": controls}, fh, default=float)

    def fmt(r: dict) -> str:
        if not r.get("n"):
            return "n=0"
        e = r.get("edge_vs_control")
        return (f"n={r['n']:5d} E[R]={r['mean_r']:+.3f}±{(r['se'] or 0):.3f} win={r['win']*100:4.1f}% "
                f"PF={(r['pf'] or 0):.2f}" + (f" ctrl={r['control_mean_r']:+.3f} edge={e:+.3f}" if e is not None else ""))
    for name in ("by_kind_tf_half", "by_kind_tf", "veto_by_kind_tf_half", "non_overlap_by_kind_tf",
                 "by_kind_tf_side", "sensitivity", "by_kind_tf_symbol", "by_kind_flow", "exit_reasons"):
        print(f"\n== {name}")
        for r in rep["tables"][name]:
            label = " ".join(f"{k}={r[k]}" for k in r if k in ("kind", "tf", "half", "symbol", "side",
                                                                 "flow", "target_r", "reason"))
            print(f"  {label:48s} {fmt(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
