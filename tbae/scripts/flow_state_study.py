#!/usr/bin/env python3
"""Where do the flow states sit on the chart, and what follows each one?

Run::

    python3 scripts/flow_state_study.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
        --data-dir data/binance --tfs 60,5 --out ../reports/flow_state

For every symbol and chart timeframe the 1-minute store is aggregated into
chart bars and 4-bar blocks (1h -> 4h, 5m -> 20m), each block gets its flow
state (:mod:`engine.flow_state`), and five questions are measured on completed
blocks:

1. **Shares** — how often each state occurs.
2. **Location** — where in its trailing 20-block range each state closes
   (0 = at the low, 1 = at the high).
3. **Swing highs / lows** — which states sit on a pivot block, as a lift over
   their base rate.  Pivots are confirmed with 2 blocks on each side, so this
   is a *description* of the chart, not something tradable at that block.
4. **Range vs trend** — state composition when the 6-block efficiency ratio
   says the market is ranging (< 0.25) or trending (> 0.50).
5. **Level breaks** — first close beyond the prior 20-block high/low, grouped
   by the state of the breaking block and of the block before it.  A break
   *holds* when the next 3 closes all stay beyond the level.
6. **Next block** — given a state, how often the next block moves in the
   direction of the delta, and (for explosive) against the block's own move.

Rates carry 95% Wilson intervals; pooled rows sum counts across symbols.
Everything up to the outcome is causal; only the outcome windows look forward,
which is what an outcome is.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import flow_state as fs                                # noqa: E402
from engine.feeds import CsvFeed                                   # noqa: E402

LOOKBACK = 20          # blocks defining a level and the location range
ATR_N = 30             # blocks in the trailing mean range
PIVOT_K = 2            # blocks on each side confirming a swing
ER_N = 6               # blocks in the efficiency ratio
HOLD_N = 3             # closes that must stay beyond a broken level
FOLLOW_N = 6           # blocks over which break follow-through is measured
EFFORT_KEYS = ["vol>>price", "vol>price", "equal", "price>vol", "price>>vol",
               "cross|volume_crosses_up", "cross|price_crosses_up", "cross|none",
               "both_high", "both_low"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def sgn(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


class Counter2:
    """k-of-n tallies per key, plus running sums for means."""

    def __init__(self) -> None:
        self.k: dict[str, int] = {}
        self.n: dict[str, int] = {}
        self.s: dict[str, float] = {}

    def add(self, key: str, hit: bool, value: float | None = None) -> None:
        self.n[key] = self.n.get(key, 0) + 1
        self.k[key] = self.k.get(key, 0) + (1 if hit else 0)
        if value is not None:
            self.s[key] = self.s.get(key, 0.0) + value

    def merge(self, other: "Counter2") -> None:
        for d_self, d_other in ((self.k, other.k), (self.n, other.n), (self.s, other.s)):
            for key, v in d_other.items():
                d_self[key] = d_self.get(key, 0) + v

    def rows(self, keys: Sequence[str]) -> list[dict[str, Any]]:
        out = []
        for key in keys:
            n = self.n.get(key, 0)
            k = self.k.get(key, 0)
            lo, hi = wilson(k, n)
            out.append({"key": key, "n": n, "k": k, "rate": (k / n) if n else None,
                        "ci_lo": lo if n else None, "ci_hi": hi if n else None,
                        "mean": (self.s[key] / n) if n and key in self.s else None})
        return out


def study_blocks(blocks: Sequence[fs.FlowBlock], cfg: fs.FlowConfig) -> dict[str, Any]:
    B = [b for b in blocks if b.n_bars == cfg.block]
    n = len(B)
    ready = [b.state != "unready" for b in B]
    atr: list[float | None] = [None] * n
    for i in range(n):
        if i >= ATR_N:
            atr[i] = sum(B[j].high - B[j].low for j in range(i - ATR_N, i)) / ATR_N
    res: dict[str, Any] = {}

    # 1 shares --------------------------------------------------------------
    shares = Counter2()
    for i in range(n):
        if ready[i]:
            for s in fs.STATES:
                shares.add(s, B[i].state == s)
    res["shares"] = shares

    # 2 location in trailing range ------------------------------------------
    loc = Counter2()
    for i in range(LOOKBACK, n):
        if not ready[i]:
            continue
        hi = max(B[j].high for j in range(i - LOOKBACK + 1, i + 1))
        lo = min(B[j].low for j in range(i - LOOKBACK + 1, i + 1))
        if hi <= lo:
            continue
        p = (B[i].close - lo) / (hi - lo)
        loc.add(B[i].state, p >= 2 / 3, p)        # rate = share closing in the top third
        loc.add(B[i].state + "|bottom", p <= 1 / 3)
    res["location"] = loc

    # 3 swing pivots (descriptive) -------------------------------------------
    piv = Counter2()
    for i in range(PIVOT_K, n - PIVOT_K):
        if not ready[i]:
            continue
        win = range(i - PIVOT_K, i + PIVOT_K + 1)
        is_hi = all(B[i].high > B[j].high for j in win if j != i)
        is_lo = all(B[i].low < B[j].low for j in win if j != i)
        st = B[i].state
        piv.add(st + "|high", is_hi)
        piv.add(st + "|low", is_lo)
        prev = B[i - 1].state if ready[i - 1] else None
        if prev:
            piv.add(prev + "|before_high", is_hi)
            piv.add(prev + "|before_low", is_lo)
    res["pivots"] = piv

    # 4 range vs trend regime ------------------------------------------------
    reg = Counter2()
    for i in range(ER_N, n):
        if not ready[i]:
            continue
        path = sum(abs(B[j].close - B[j - 1].close) for j in range(i - ER_N + 1, i + 1))
        er = abs(B[i].close - B[i - ER_N].close) / path if path > 0 else 0.0
        regime = "range" if er < 0.25 else "trend" if er > 0.50 else "mixed"
        for s in fs.STATES:
            reg.add(regime + "|" + s, B[i].state == s)
    res["regime"] = reg

    # 5 level breaks ---------------------------------------------------------
    brk = Counter2()
    for i in range(LOOKBACK + 1, n - FOLLOW_N):
        if not ready[i] or atr[i] is None or atr[i] <= 0:
            continue
        up = max(B[j].high for j in range(i - LOOKBACK, i))
        dn = min(B[j].low for j in range(i - LOOKBACK, i))
        for side, level, crossed in ((1, up, B[i].close > up and B[i - 1].close <= up),
                                     (-1, dn, B[i].close < dn and B[i - 1].close >= dn)):
            if not crossed:
                continue
            holds = all((B[j].close - level) * side > 0 for j in range(i + 1, i + 1 + HOLD_N))
            ext = (max(B[j].high for j in range(i + 1, i + 1 + FOLLOW_N)) - B[i].close) if side > 0 \
                else (B[i].close - min(B[j].low for j in range(i + 1, i + 1 + FOLLOW_N)))
            follow = ext / atr[i]
            st = B[i].state
            brk.add("all", holds, follow)
            brk.add("state|" + st, holds, follow)
            if ready[i - 1]:
                brk.add("prev|" + B[i - 1].state, holds, follow)
            agree = sgn(B[i].delta) == side
            brk.add("effort|" + ("vol_above_price" if B[i].vol_pct >= B[i].move_pct else "price_above_vol"),
                    holds, follow)
            brk.add("delta_agrees" if agree else "delta_disagrees", holds, follow)
    res["breaks"] = brk

    # 6 next block -----------------------------------------------------------
    nxt = Counter2()
    for i in range(ATR_N, n - 1):
        if not ready[i] or atr[i] is None or atr[i] <= 0:
            continue
        st = B[i].state
        d = sgn(B[i].delta)
        nm = B[i + 1].close - B[i + 1].open
        if d:
            nxt.add("flow|" + st, sgn(nm) == d, d * nm / atr[i])
        m = sgn(B[i].move)
        if m:
            nxt.add("revert|" + st, sgn(nm) == -m, -m * nm / atr[i])
        nxt.add("absmove|" + st, abs(nm) > atr[i], abs(nm) / atr[i])
    res["next"] = nxt

    # 7 effort (volume%) vs result (move%) ---------------------------------
    # spread = vol% - move%: > 0 effort without result, < 0 result without effort.
    # A cross is a block whose spread sign differs from the previous ready block's.
    er = Counter2()
    prev_sp = None
    for i in range(ATR_N, n - PIVOT_K):
        if not ready[i] or atr[i] is None or atr[i] <= 0:
            prev_sp = None
            continue
        sp = B[i].vol_pct - B[i].move_pct
        bucket = ("vol>>price" if sp >= 40 else "vol>price" if sp >= 10 else
                  "equal" if sp > -10 else "price>vol" if sp > -40 else "price>>vol")
        if prev_sp is None:
            cross = "none"
        elif prev_sp < 0 <= sp:
            cross = "volume_crosses_up"
        elif prev_sp >= 0 > sp:
            cross = "price_crosses_up"
        else:
            cross = "none"
        prev_sp = sp
        win = [j for j in range(i - PIVOT_K, i + PIVOT_K + 1) if j != i]
        pivot = all(B[i].high > B[j].high for j in win) or all(B[i].low < B[j].low for j in win)
        nm = B[i + 1].close - B[i + 1].open
        m = sgn(B[i].move)
        both = "both_high" if B[i].vol_pct >= 55 and B[i].move_pct >= 55 else \
               "both_low" if B[i].vol_pct < 20 and B[i].move_pct < 20 else None
        for key in [bucket, "cross|" + cross] + ([both] if both else []):
            er.add("pivot|" + key, pivot)
            er.add("bigmove|" + key, abs(nm) > atr[i], abs(nm) / atr[i])
            if m:
                er.add("revert|" + key, sgn(nm) == -m, -m * nm / atr[i])
    res["effort"] = er
    return res


def tables(res: dict[str, Counter2]) -> dict[str, Any]:
    S = list(fs.STATES)
    sh = res["shares"].rows(S)
    loc = res["location"].rows(S)
    locb = {r["key"].split("|")[0]: r for r in res["location"].rows([s + "|bottom" for s in S])}
    piv_hi = res["pivots"].rows([s + "|high" for s in S])
    piv_lo = res["pivots"].rows([s + "|low" for s in S])
    pre_hi = res["pivots"].rows([s + "|before_high" for s in S])
    pre_lo = res["pivots"].rows([s + "|before_low" for s in S])

    def overall(rows: list[dict[str, Any]]) -> float:
        k = sum(r["k"] for r in rows)
        n = sum(r["n"] for r in rows)
        return k / n if n else float("nan")

    out = {
        "shares": [{"state": r["key"], "n": r["n"], "share": r["rate"]} for r in sh],
        "location": [{"state": s, "mean_position": loc[i]["mean"], "top_third": loc[i]["rate"],
                      "bottom_third": locb[s]["rate"], "n": loc[i]["n"]} for i, s in enumerate(S)],
        "pivots": {
            "base_high": overall(piv_hi), "base_low": overall(piv_lo),
            "rows": [{"state": s, "n": piv_hi[i]["n"],
                      "high_rate": piv_hi[i]["rate"], "low_rate": piv_lo[i]["rate"],
                      "high_ci": [piv_hi[i]["ci_lo"], piv_hi[i]["ci_hi"]],
                      "low_ci": [piv_lo[i]["ci_lo"], piv_lo[i]["ci_hi"]],
                      "before_high_rate": pre_hi[i]["rate"], "before_low_rate": pre_lo[i]["rate"]}
                     for i, s in enumerate(S)],
        },
        "regime": {rg: [{"state": s, **{k: v for k, v in r.items() if k in ("n", "rate")}}
                        for s, r in zip(S, res["regime"].rows([rg + "|" + s for s in S]))]
                   for rg in ("range", "mixed", "trend")},
        "breaks": {
            "all": res["breaks"].rows(["all"])[0],
            "by_state": [dict(state=s, **r) for s, r in zip(S, res["breaks"].rows(["state|" + s for s in S]))],
            "by_prev_state": [dict(state=s, **r) for s, r in zip(S, res["breaks"].rows(["prev|" + s for s in S]))],
            "by_delta": res["breaks"].rows(["delta_agrees", "delta_disagrees"]),
            "by_effort": res["breaks"].rows(["effort|vol_above_price", "effort|price_above_vol"]),
        },
        "next": {
            "flow": [dict(state=s, **r) for s, r in zip(S, res["next"].rows(["flow|" + s for s in S]))],
            "revert": [dict(state=s, **r) for s, r in zip(S, res["next"].rows(["revert|" + s for s in S]))],
            "absmove": [dict(state=s, **r) for s, r in zip(S, res["next"].rows(["absmove|" + s for s in S]))],
        },
        "effort": {
            kind: res["effort"].rows([kind + "|" + k for k in EFFORT_KEYS])
            for kind in ("pivot", "bigmove", "revert")
        },
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--data-dir", default="data/binance")
    ap.add_argument("--tfs", default="60,5", help="chart timeframes in minutes")
    ap.add_argument("--block", type=int, default=4)
    ap.add_argument("--out", default="../reports/flow_state")
    a = ap.parse_args()

    cfg = fs.FlowConfig(block=a.block).validate()
    os.makedirs(a.out, exist_ok=True)
    tfs = [int(x) for x in a.tfs.split(",") if x.strip()]
    report: dict[str, Any] = {"config": cfg.__dict__, "tfs": tfs, "per_symbol": {}, "pooled": {}}
    pooled: dict[int, dict[str, Counter2]] = {}
    samples: dict[str, Any] = {}

    for sym in [s.strip().upper() for s in a.symbols.split(",") if s.strip()]:
        path = os.path.join(a.data_dir, f"{sym}_1m.csv.gz")
        if not os.path.exists(path):
            print(f"skip {sym}: no {path}")
            continue
        mins = CsvFeed(path).load()
        print(f"[{sym}] {len(mins):,} minutes")
        report["per_symbol"][sym] = {}
        for tf in tfs:
            bars = fs.flow_bars(mins, tf)
            blocks = fs.annotate(fs.flow_blocks(bars, tf, cfg.block), tf, cfg)
            res = study_blocks(blocks, cfg)
            report["per_symbol"][sym][str(tf)] = tables(res)
            acc = pooled.setdefault(tf, {k: Counter2() for k in res})
            for k, c in res.items():
                acc[k].merge(c)
            # keep a recent window for the charts
            line = fs.bar_line(bars, blocks, tf, cfg)
            keep = 24 * 45 if tf == 60 else 12 * 48
            samples[f"{sym}_{tf}"] = {
                "bars": [{"ts": b.ts, "o": b.open, "h": b.high, "l": b.low, "c": b.close} for b in bars[-keep:]],
                "line": line[-keep:],
                "blocks": [b.to_dict() for b in blocks if b.ts >= bars[-keep].ts],
            }
            sh = {r["state"]: round((r["share"] or 0) * 100, 1) for r in report["per_symbol"][sym][str(tf)]["shares"]}
            print(f"  tf={tf}m blocks={len(blocks)} shares%={sh}")
        del mins

    for tf, res in pooled.items():
        report["pooled"][str(tf)] = tables(res)
    with open(os.path.join(a.out, "flow_state_study.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=float)
    with open(os.path.join(a.out, "flow_state_samples.json"), "w") as fh:
        json.dump(samples, fh)
    print(f"wrote {a.out}/flow_state_study.json and flow_state_samples.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
