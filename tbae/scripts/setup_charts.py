#!/usr/bin/env python3
"""Charts for the order-block / trendline-third-touch backtest (needs matplotlib).

    python3 scripts/setup_charts.py --in ../reports/setups --out ../reports/setups

* ``setups_<SYMBOL>_<tf>.png`` — recent candles with every order-block zone
  (from its break of structure until it filled or expired) and every
  trendline that produced a third touch, with the touch marked;
* ``setups_summary.png`` — E[R] per setup and timeframe next to its random
  control, both halves, and E[R] by flow state.
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
from matplotlib.patches import Rectangle                             # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import flow_state as fs                                  # noqa: E402
from engine import structure_setups as ss                            # noqa: E402
from engine.feeds import CsvFeed                                     # noqa: E402

BG, PANEL, FG, GRID = "#121417", "#181B1F", "#D7DADF", "#2A2E35"
UP, DN = "#8FD19E", "#E8888C"
OB_BULL, OB_BEAR, TL_C = "#3FC1E0", "#FF9F43", "#C9A0FF"


def style(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=FG, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6)


def chart(sym: str, tf: int, data_dir: str, out: str, n_show: int) -> None:
    mins = CsvFeed(os.path.join(data_dir, f"{sym}_1m.csv.gz")).load()
    bars = fs.flow_bars(mins, tf)
    del mins
    cfg = ss.SetupConfig()
    obs = ss.order_blocks(bars, cfg)
    tls = ss.trendline_third_touches(bars, cfg)
    s0 = len(bars) - n_show
    view = bars[s0:]
    fig, ax = plt.subplots(figsize=(15, 7.5), facecolor=BG)
    style(ax)
    for i, b in enumerate(view):
        col = UP if b.close >= b.open else DN
        ax.vlines(i, b.low, b.high, color=col, linewidth=0.6)
        ax.add_patch(Rectangle((i - 0.3, min(b.open, b.close)), 0.6, max(abs(b.close - b.open), 1e-9),
                               color=col, lw=0))
    for s in obs:
        if s.signal_index < s0 or s.expires_index is None:
            continue
        x0 = s.signal_index - s0
        end = s.expires_index
        for t in range(s.signal_index + 1, s.expires_index + 1):
            b = bars[t]
            if (s.side > 0 and b.low <= s.entry_price) or (s.side < 0 and b.high >= s.entry_price):
                end = t
                break
        lo, hi = sorted((s.entry_price, s.cancel_level))
        col = OB_BULL if s.side > 0 else OB_BEAR
        ax.add_patch(Rectangle((x0, lo), max(1, end - s.signal_index), hi - lo, color=col, alpha=0.18, lw=0))
        ax.plot([x0, x0 + max(1, end - s.signal_index)], [s.entry_price] * 2, color=col, lw=0.8)
    for s in tls:
        if s.meta["a"] < s0:
            continue
        a, i = s.meta["a"], s.signal_index
        slope = s.meta["slope_atr_per_bar"] * s.atr
        ya = s.meta["line"] - slope * (i - a)
        ax.plot([a - s0, i - s0 + 2], [ya, s.meta["line"] + 2 * slope], color=TL_C, lw=1.0, alpha=0.9)
        ax.scatter([i - s0], [bars[i].low if s.side > 0 else bars[i].high], marker="^" if s.side > 0 else "v",
                   s=40, color=TL_C, edgecolors=FG, linewidths=0.5, zorder=5)
    step = max(1, n_show // 10)
    ax.set_xticks(range(0, n_show, step))
    ax.set_xticklabels([dt.datetime.fromtimestamp(view[k].ts / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
                        for k in range(0, n_show, step)])
    ax.set_xlim(-1, n_show + 1)
    ax.set_title(f"{sym} · {tf}m · order blocks (cyan bull / orange bear, until filled or expired) "
                 f"· trendlines with their third touch (violet)", color=FG, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=BG)
    plt.close(fig)


def summary(rep: dict, out: str) -> None:
    rows = rep["tables"]["by_kind_tf_half"]
    flow = rep["tables"]["by_kind_flow"]
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.4), facecolor=BG)
    for ax in axes:
        style(ax)
    labels, setup_v, ctrl_v, err = [], [], [], []
    for r in rows:
        labels.append(f"{'OB' if r['kind'] == 'order_block' else 'TL3'} {r['tf'] // 60}h {r['half']}")
        setup_v.append(r["mean_r"])
        ctrl_v.append(r["control_mean_r"] or 0)
        err.append(1.96 * (r["se"] or 0))
    x = range(len(labels))
    axes[0].bar([i - 0.2 for i in x], setup_v, width=0.4, yerr=err, ecolor=FG, capsize=2,
                color=["#3FC1E0" if "OB" in lb else "#C9A0FF" for lb in labels], label="setup")
    axes[0].bar([i + 0.2 for i in x], ctrl_v, width=0.4, color="#6B7280", label="random control")
    axes[0].axhline(0, color=FG, lw=0.8)
    axes[0].set_xticks(list(x))
    axes[0].set_xticklabels(labels, rotation=30, fontsize=8, color=FG)
    axes[0].set_title("Net E[R] per trade (2R target, costs in) vs random control, 95% CI", color=FG, fontsize=10)
    leg = axes[0].legend(fontsize=8, frameon=False)
    for t in leg.get_texts():
        t.set_color(FG)
    order = ["max", "trend", "strong", "absorption", "pressure", "quiet", "balanced", "explosive"]
    w = 0.38
    for k, (kind, col) in enumerate((("order_block", "#3FC1E0"), ("trendline3", "#C9A0FF"))):
        vals = {r["flow"]: r for r in flow if r["kind"] == kind}
        ys = [vals[s]["mean_r"] if s in vals else 0 for s in order]
        es = [1.96 * (vals[s]["se"] or 0) if s in vals else 0 for s in order]
        axes[1].bar([i + (k - 0.5) * w for i in range(len(order))], ys, width=w, yerr=es, ecolor=FG,
                    capsize=2, color=[fs.STATE_COLORS[s] for s in order], edgecolor=col, linewidth=1.4,
                    hatch="" if k == 0 else "//", label="order block" if k == 0 else "trendline 3rd touch")
    axes[1].axhline(0, color=FG, lw=0.8)
    axes[1].set_xticks(range(len(order)))
    axes[1].set_xticklabels(order, rotation=30, fontsize=8, color=FG)
    axes[1].set_title("Net E[R] by flow state at the signal (bars = state colour)", color=FG, fontsize=10)
    leg = axes[1].legend(fontsize=8, frameon=False)
    for t in leg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=BG)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", default="../reports/setups")
    ap.add_argument("--out", default="../reports/setups")
    ap.add_argument("--data-dir", default="data/binance")
    ap.add_argument("--charts", default="BTCUSDT:60:400,SOLUSDT:240:250")
    a = ap.parse_args()
    with open(os.path.join(a.inp, "setup_backtest.json")) as fh:
        rep = json.load(fh)
    os.makedirs(a.out, exist_ok=True)
    for spec in a.charts.split(","):
        sym, tf, n = spec.split(":")
        p = os.path.join(a.out, f"setups_{sym}_{tf}.png")
        chart(sym, int(tf), a.data_dir, p, int(n))
        print("wrote", p)
    p = os.path.join(a.out, "setups_summary.png")
    summary(rep, p)
    print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
