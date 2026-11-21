#!/usr/bin/env python3
"""Charts for the flow-state study (needs matplotlib, which the engine does not).

    python3 scripts/flow_state_charts.py --in ../reports/flow_state --out ../reports/flow_state

Reads ``flow_state_samples.json`` and ``flow_state_study.json`` written by
``flow_state_study.py`` and draws:

* ``chart_<SYMBOL>_<tf>.png`` — candles with each block shaded by its state,
  confirmed swing highs/lows, and the indicator line underneath coloured block
  by block, on a dark ground like a trading terminal so the white and yellow
  range states stay visible;
* ``summary.png`` — pivot lift, break hold rate and range/trend composition
  per state, pooled over all symbols.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                       # noqa: E402
from matplotlib.collections import LineCollection                    # noqa: E402
from matplotlib.patches import Patch                                 # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.flow_state import STATE_COLORS, STATES                   # noqa: E402

BG, PANEL, FG, GRID = "#121417", "#181B1F", "#D7DADF", "#2A2E35"
NAMES = {"quiet": "quiet: low vol, balanced (yellow)", "balanced": "balanced: vol, no side (white)",
         "trend": "trend (green)", "strong": "strong", "pressure": "pressure",
         "absorption": "absorption", "explosive": "explosive", "max": "max", "unready": "no reference"}
ORDER = ["quiet", "balanced", "trend", "strong", "pressure", "absorption", "explosive", "max"]
VOL_C, PRICE_C = "#3FC1E0", "#FF9F43"


def style(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=FG, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6)
    ax.yaxis.label.set_color(FG)


def chart(sample: dict, title: str, path: str, tf: int, block: int) -> None:
    bars, line, blocks = sample["bars"], sample["line"], sample["blocks"]
    t = [dt.datetime.fromtimestamp(b["ts"] / 1000, dt.timezone.utc) for b in bars]
    x = list(range(len(bars)))
    idx = {b["ts"]: i for i, b in enumerate(bars)}
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(15, 10.5), sharex=True,
                                     gridspec_kw={"height_ratios": [2.3, 1, 1]}, facecolor=BG)
    style(a1); style(a2); style(a3)
    # block shading
    for blk in blocks:
        i0 = idx.get(blk["ts"])
        if i0 is None:
            continue
        a1.axvspan(i0 - 0.5, i0 + block - 0.5, color=STATE_COLORS[blk["state"]], alpha=0.13, lw=0)
    # candles
    for i, b in enumerate(bars):
        up = b["c"] >= b["o"]
        col = "#8FD19E" if up else "#E8888C"
        a1.vlines(i, b["l"], b["h"], color=col, linewidth=0.6)
        a1.add_patch(plt.Rectangle((i - 0.3, min(b["o"], b["c"])), 0.6,
                                   max(abs(b["c"] - b["o"]), 1e-9), color=col, lw=0))
    # confirmed swing highs/lows at block level (2 blocks each side)
    K = 2
    for j in range(K, len(blocks) - K):
        win = [blocks[k] for k in range(j - K, j + K + 1) if k != j]
        i0 = idx.get(blocks[j]["ts"])
        if i0 is None:
            continue
        if all(blocks[j]["high"] > w["high"] for w in win):
            a1.scatter(i0 + block / 2 - 0.5, blocks[j]["high"] * 1.0015, marker="v", s=28,
                       color=STATE_COLORS[blocks[j]["state"]], edgecolors=FG, linewidths=0.5, zorder=5)
        if all(blocks[j]["low"] < w["low"] for w in win):
            a1.scatter(i0 + block / 2 - 0.5, blocks[j]["low"] * 0.9985, marker="^", s=28,
                       color=STATE_COLORS[blocks[j]["state"]], edgecolors=FG, linewidths=0.5, zorder=5)
    a1.set_title(title, color=FG, fontsize=11, loc="left")
    a1.set_ylabel("price")
    # indicator line coloured by block state
    pts = [(i, l["line"]) for i, l in enumerate(line) if l["line"] is not None]
    segs, cols = [], []
    for (i0, y0), (i1, y1) in zip(pts, pts[1:]):
        if i1 - i0 > 1:
            continue
        segs.append([(i0, y0), (i1, y1)])
        cols.append(STATE_COLORS[line[i1]["state"]])
    a2.add_collection(LineCollection(segs, colors=cols, linewidths=1.8))
    ys = [p[1] for p in pts] or [0]
    a2.set_ylim(min(ys + [-60]) * 1.1, max(ys + [60]) * 1.1)
    for lvl, ls in ((0, "-"), (20, ":"), (-20, ":"), (55, "--"), (-55, "--")):
        a2.axhline(lvl, color="#6B7280", linewidth=0.7, linestyle=ls)
    a2.set_ylabel(f"weighted delta %\n(last {block} bars)")
    # effort vs result: two parallel lines on one percentage scale
    vx = [i for i, l in enumerate(line) if l.get("vol_line") is not None]
    vv = [min(line[i]["vol_line"], 160) for i in vx]
    pv = [min(line[i]["price_line"], 160) for i in vx]
    a3.plot(vx, vv, color=VOL_C, linewidth=1.5, label="volume % (effort)")
    a3.plot(vx, pv, color=PRICE_C, linewidth=1.5, label="price move % (result)")
    a3.fill_between(vx, vv, pv, where=[a > b for a, b in zip(vv, pv)], color=VOL_C, alpha=0.12, lw=0)
    a3.fill_between(vx, vv, pv, where=[a <= b for a, b in zip(vv, pv)], color=PRICE_C, alpha=0.12, lw=0)
    for lvl in (20, 55, 100):
        a3.axhline(lvl, color="#6B7280", linewidth=0.7, linestyle=":")
    a3.set_ylim(0, 165)
    a3.set_ylabel("effort vs result\n(%, clipped at 160)")
    leg3 = a3.legend(loc="upper left", fontsize=7.5, frameon=False, ncol=2)
    for txt in leg3.get_texts():
        txt.set_color(FG)
    step = max(1, len(x) // 10)
    a3.set_xticks(x[::step])
    a3.set_xticklabels([t[i].strftime("%m-%d %H:%M") for i in x[::step]], rotation=0)
    a3.set_xlim(-1, len(x))
    handles = [Patch(color=STATE_COLORS[s], label=NAMES[s]) for s in ORDER]
    leg = a1.legend(handles=handles, loc="upper left", ncol=4, fontsize=7.5, frameon=False)
    for txt in leg.get_texts():
        txt.set_color(FG)
    fig.text(0.01, 0.005, f"{tf}m candles · state per {block}-bar block ({tf * block}m) · "
             "triangles = confirmed block swing highs/lows, coloured by that block's state",
             color="#9AA0A6", fontsize=8)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=130, facecolor=BG)
    plt.close(fig)


def summary(study: dict, path: str) -> None:
    S = list(STATES)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2), facecolor=BG)
    for ax in axes:
        style(ax)
    w = 0.38
    for k, (tf, off) in enumerate((("60", -w / 2), ("5", w / 2))):
        P = study["pooled"][tf]
        pv = P["pivots"]
        lift = [((r["high_rate"] or 0) / pv["base_high"] + (r["low_rate"] or 0) / pv["base_low"]) / 2
                for r in pv["rows"]]
        axes[0].bar([i + off for i in range(len(S))], lift, width=w,
                    color=[STATE_COLORS[s] for s in S], edgecolor=FG if k else "#555",
                    hatch="" if k == 0 else "//", linewidth=0.6,
                    label="1h chart (4h blocks)" if k == 0 else "5m chart (20m blocks)")
        br = {r["state"]: r for r in P["breaks"]["by_state"]}
        rates = [br[s]["rate"] or 0 for s in S]
        err = [[(br[s]["rate"] or 0) - (br[s]["ci_lo"] or 0) for s in S],
               [(br[s]["ci_hi"] or 0) - (br[s]["rate"] or 0) for s in S]]
        axes[1].bar([i + off for i in range(len(S))], rates, width=w, yerr=err, ecolor=FG,
                    color=[STATE_COLORS[s] for s in S], edgecolor=FG if k else "#555",
                    hatch="" if k == 0 else "//", linewidth=0.6, capsize=2)
        axes[1].axhline(P["breaks"]["all"]["rate"], color=FG if k else "#9AA0A6",
                        linestyle="--" if k else ":", linewidth=0.8)
    axes[0].axhline(1.0, color="#9AA0A6", linewidth=0.8)
    axes[0].set_title("Swing high/low lift (1 = base rate)", color=FG, fontsize=10)
    axes[1].set_title("Level break holds 3 closes (dashed = all breaks)", color=FG, fontsize=10)
    for ax in axes[:2]:
        ax.set_xticks(range(len(S)))
        ax.set_xticklabels(S, rotation=30, fontsize=8)
    leg = axes[0].legend(fontsize=8, frameon=False)
    for txt in leg.get_texts():
        txt.set_color(FG)
    # regime composition, 1h
    P = study["pooled"]["60"]["regime"]
    regs = ["range", "mixed", "trend"]
    bottom = [0.0] * 3
    for s in ORDER:
        vals = [next(r["rate"] for r in P[rg] if r["state"] == s) * 100 for rg in regs]
        axes[2].bar(regs, vals, bottom=bottom, color=STATE_COLORS[s], edgecolor=BG, linewidth=0.5, label=s)
        bottom = [b + v for b, v in zip(bottom, vals)]
    axes[2].set_title("State mix by market regime, 1h (efficiency ratio)", color=FG, fontsize=10)
    axes[2].set_ylabel("% of blocks")
    leg = axes[2].legend(fontsize=7.5, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    for txt in leg.get_texts():
        txt.set_color(FG)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=BG)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", default="../reports/flow_state")
    ap.add_argument("--out", default="../reports/flow_state")
    ap.add_argument("--symbols", default="BTCUSDT,SOLUSDT")
    a = ap.parse_args()
    with open(os.path.join(a.inp, "flow_state_samples.json")) as fh:
        samples = json.load(fh)
    with open(os.path.join(a.inp, "flow_state_study.json")) as fh:
        study = json.load(fh)
    block = int(study["config"]["block"])
    os.makedirs(a.out, exist_ok=True)
    for sym in a.symbols.split(","):
        for tf in study["tfs"]:
            key = f"{sym}_{tf}"
            if key not in samples:
                continue
            s = samples[key]
            if tf == 5:      # two days are enough to read a 5m chart
                s = {**s, "bars": s["bars"][-288 * 2:], "line": s["line"][-288 * 2:]}
                first = s["bars"][0]["ts"]
                s["blocks"] = [b for b in s["blocks"] if b["ts"] >= first]
            else:
                s = {**s, "bars": s["bars"][-24 * 21:], "line": s["line"][-24 * 21:]}
                first = s["bars"][0]["ts"]
                s["blocks"] = [b for b in s["blocks"] if b["ts"] >= first]
            out = os.path.join(a.out, f"chart_{sym}_{tf}.png")
            chart(s, f"{sym} · {tf}m · flow state per {tf * block}m block", out, tf, block)
            print("wrote", out)
    out = os.path.join(a.out, "summary.png")
    summary(study, out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
