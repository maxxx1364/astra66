#!/usr/bin/env python3
"""Which flow states did the strategy's trades enter in, and how did they do?

    python3 -m app.cli backtest --feed csv:data/binance/BTCUSDT_1m.csv.gz --tf 60 \
        --commission-bps 2 --stop-mode sigma --stop-sigma 4.4 --trades-csv trades/BTCUSDT.csv
    python3 scripts/flow_trade_attribution.py --trades-dir ../reports/flow_state/trades

Each trade is tagged with the flow state of the **last block that had closed
before its entry** — information the strategy could have had — and with the
effort/result spread (volume% − move%) of that block and whether the block's
delta pointed the trade's way.  Net R is then grouped by tag.

The sample is split in time at ``--split`` (default: the midpoint of the
trades).  A veto rule is only worth adding if it is chosen on the first half
and still helps on the second; the report prints both halves side by side so
that a rule picked in-sample can be judged out-of-sample.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import flow_state as fs                                # noqa: E402
from engine.feeds import CsvFeed                                   # noqa: E402


def stats(rs: list[float]) -> dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean_r": None, "se": None, "sum_r": 0.0}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean_r": m, "se": sd / math.sqrt(n) if n > 1 else None, "sum_r": sum(rs)}


def tag_trades(trades: list[dict[str, Any]], blocks: list[fs.FlowBlock], tf: int, block: int) -> None:
    span = tf * 60_000 * block
    closed = [b for b in blocks if b.n_bars == block]
    ends = [b.ts + span for b in closed]
    import bisect
    for t in trades:
        k = bisect.bisect_right(ends, t["entry_ts"]) - 1
        if k < 0 or closed[k].vol_pct is None:
            t["flow"] = "unready"
            continue
        b = closed[k]
        t["flow"] = b.state
        sp = b.vol_pct - b.move_pct
        t["effort"] = ("vol>>price" if sp >= 40 else "vol>price" if sp >= 10 else
                       "equal" if sp > -10 else "price>vol" if sp > -40 else "price>>vol")
        side = 1 if str(t["side"]).lower() in ("1", "long", "buy") else -1
        t["delta_agrees"] = (b.delta > 0) == (side > 0) and b.delta != 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trades-dir", default="../reports/flow_state/trades")
    ap.add_argument("--data-dir", default="data/binance")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--tf", type=int, default=60)
    ap.add_argument("--block", type=int, default=4)
    ap.add_argument("--split", default="", help="ISO date splitting in- and out-of-sample")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    cfg = fs.FlowConfig(block=a.block)
    allt: list[dict[str, Any]] = []
    for sym in [s.strip().upper() for s in a.symbols.split(",") if s.strip()]:
        tp = os.path.join(a.trades_dir, f"{sym}.csv")
        if not os.path.exists(tp):
            continue
        with open(tp) as fh:
            trades = [dict(r) for r in csv.DictReader(fh)]
        for t in trades:
            t["entry_ts"] = int(float(t["entry_ts"]))
            t["r"] = float(t["r_multiple"])
            t["symbol"] = sym
        mins = CsvFeed(os.path.join(a.data_dir, f"{sym}_1m.csv.gz")).load()
        bars = fs.flow_bars(mins, a.tf)
        blocks = fs.annotate(fs.flow_blocks(bars, a.tf, a.block), a.tf, cfg)
        del mins
        tag_trades(trades, blocks, a.tf, a.block)
        allt.extend(trades)
        print(f"[{sym}] {len(trades)} trades tagged")

    allt.sort(key=lambda t: t["entry_ts"])
    if a.split:
        import datetime as dt
        cut = int(dt.datetime.fromisoformat(a.split).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    else:
        cut = allt[len(allt) // 2]["entry_ts"]
    halves = {"in_sample": [t for t in allt if t["entry_ts"] < cut],
              "out_of_sample": [t for t in allt if t["entry_ts"] >= cut]}

    out: dict[str, Any] = {"split_ts": cut, "n_trades": len(allt), "groups": {}}
    for key in ("flow", "effort", "delta_agrees"):
        vals = sorted({str(t.get(key)) for t in allt})
        out["groups"][key] = {
            v: {h: stats([t["r"] for t in ts if str(t.get(key)) == v]) for h, ts in
                (("all", allt), *halves.items())}
            for v in vals
        }
    out["baseline"] = {h: stats([t["r"] for t in ts]) for h, ts in (("all", allt), *halves.items())}

    def fmt(s: dict[str, Any]) -> str:
        if not s["n"]:
            return f"{'—':>22s}"
        se = f"±{s['se']:.3f}" if s["se"] is not None else ""
        return f"n={s['n']:4d} {s['mean_r']:+.3f}{se:>7s}"

    print(f"\nsplit at {cut} · baseline  all {fmt(out['baseline']['all'])} | "
          f"IS {fmt(out['baseline']['in_sample'])} | OOS {fmt(out['baseline']['out_of_sample'])}")
    for key, groups in out["groups"].items():
        print(f"\n by {key}")
        for v, g in groups.items():
            print(f"  {v:12s} all {fmt(g['all'])} | IS {fmt(g['in_sample'])} | OOS {fmt(g['out_of_sample'])}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
