"""Where does friction actually come from, and which lever moves it?

Run from ``tbae/``::

    python3 scripts/friction_sensitivity.py --seeds 12 --days 45 --tf 15

Background
----------
``engine/metrics.py`` flags a strategy ``cost_bound`` when
``friction_r_per_trade >= gross_expectancy_r``.  On the 2026-10-26 real-data run
BTCUSDT and ETHUSDT were both flagged: friction ~0.057R against gross edges of
+0.000R and +0.018R.

The engine's own prescription for that state is "widen stops, cut exit legs or
rest orders as maker".  This script exists because that advice turned out to be
the *weakest* of the available levers, and the two strongest are not in the list.

Findings (synthetic, 12 seeds x 45d x 15m; see docs/FRICTION.md for the write-up)
--------------------------------------------------------------------------------
1. **Market impact dominates friction, and it is not on the list.**
   ``CostConfig.impact_bps()`` is a sqrt law: ``0.10 * sqrt(N / ADV)``.  At the
   default synthetic ADV of 2e8 and a ~52k ticket that is **16.1 bp per fill**
   against an assumed fixed slippage of 2.0 bp — impact is 8x the slippage, and
   ~67% of all friction.  It is also an *assumption*: ``venues.py`` documents
   ``impact_coeff`` as assumed, not measured.  Sweeping it 0.01 -> 0.20 swings
   net E[R] by a factor of 20.  Until it is measured from real fills, every
   ``cost_bound`` verdict is a statement about an assumption.

2. **Widening stops does not help.**  ``stop_sigma_mult`` 2.2 -> 4.0 cuts
   friction/R by 25% but the gross edge falls by 23% right alongside it, so net
   is flat.  friction/R falls because R grows, not because anything got cheaper.

3. **Lowering the first take-profit is the one lever that improves both sides.**
   Mean peak R is only **0.62R** and mean giveback is **0.55R**, while tp1 sits
   at **1.00R** — above the average trade's peak, so **61% of trades fill zero
   tranches**.  Sweeping tp1 from 1.0R down to 0.4R is monotone in both
   friction/R (0.182 -> 0.142) and gross R (+0.068 -> +0.107) at stable n:
   earlier targets are maker fills (1 bp, no spread, no impact) *and* they
   capture excursion that is otherwise given back.

4. **Size is the other real lever.**  Impact is ``~sqrt(N)`` while P&L is
   ``~N``, so impact as a share of P&L falls as ``sqrt(N)``.  Halving the ticket
   does not halve the drag — it cuts it by ~1.41x.  Cutting
   ``risk_per_trade_pct`` 0.75% -> 0.19% cut friction/R 0.182 -> 0.149.

Caveats
-------
Everything here is **synthetic**.  The generator uses the placeholder ADV
(2e8), not a measured one, so its absolute impact (~16 bp) is roughly 2.7x the
real BTCUSDT figure (~6 bp at ADV 1.6e9).  Treat these as measurements of a
*mechanism*, never as predictions.  Any config change must be re-validated on
real data with walk-forward / CSCV / PBO before it means anything — tp1 = 0.4R
in particular is exactly the kind of knob that overfits a generator.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import backtest, feeds, pipeline  # noqa: E402
from engine.exits import ExitConfig  # noqa: E402
from engine.models import Settings  # noqa: E402
from engine.risk import RiskConfig  # noqa: E402


def run_one(seed: int, days: int, tf: int, exit_cfg=None,
            risk_pct=None, impact=None, slippage=None) -> dict:
    minutes = feeds.SyntheticFeed(feeds.SyntheticConfig(days=days, seed=seed)).load()
    res = pipeline.run(minutes, settings=Settings(), tf=tf)
    rc = RiskConfig()
    if risk_pct is not None:
        rc.risk_per_trade_pct = risk_pct
    if impact is not None or slippage is not None:
        rc.costs = copy.copy(rc.costs)
        if impact is not None:
            rc.costs.impact_coeff = impact
        if slippage is not None:
            rc.costs.slippage_bps = slippage
    out = backtest.run_backtest(res, risk_cfg=rc, exit_cfg=exit_cfg)
    t = out.metrics["trades"]
    return {
        "n": t["n"],
        "gross_r": t["gross_expectancy_r"],
        "fric_r": t["friction_r_per_trade"],
        "fric_bp": t["friction_bp_mean"],
        "net_r": t["expectancy_r"],
        "tranches": t["avg_tranches_filled"],
        "bars": t["avg_bars_held"],
        "win_rate": t["win_rate"],
    }


def pool(rows: list[dict]) -> dict | None:
    """Weight by n at the *trade* level.

    Averaging ratios across seeds whose n differs is meaningless — the same
    mistake the first RESEARCH.md analysis made and later corrected.
    """
    n = sum(r["n"] for r in rows)
    if not n:
        return None
    w = lambda k: sum(r[k] * r["n"] for r in rows) / n  # noqa: E731
    return {"n": n, "gross_r": w("gross_r"), "fric_r": w("fric_r"),
            "fric_bp": w("fric_bp"), "net_r": w("net_r"),
            "tranches": w("tranches"), "bars": w("bars"),
            "win_rate": w("win_rate")}


HEAD = (f"{'variant':24} {'n':>5} {'grossR':>8} {'fricR':>8} {'fric_bp':>8} "
        f"{'netR':>8} {'trnch':>6} {'bars':>5} {'win%':>6}")


def sweep(title: str, variants, seeds, days, tf) -> list[dict]:
    print(f"\n{'=' * 92}\n{title}\n{'=' * 92}\n{HEAD}")
    out = []
    for name, kw in variants:
        p = pool([run_one(s, days, tf, **kw) for s in seeds])
        if p is None:
            print(f"{name:24} (no trades)")
            continue
        print(f"{name:24} {p['n']:>5} {p['gross_r']:>+8.3f} {p['fric_r']:>8.3f} "
              f"{p['fric_bp']:>8.2f} {p['net_r']:>+8.3f} {p['tranches']:>6.2f} "
              f"{p['bars']:>5.1f} {p['win_rate'] * 100:>6.1f}")
        out.append({"variant": name, **p})
    return out


def build_variants(which: str) -> list[tuple[str, dict]]:
    tp = lambda r1: ExitConfig(tranches=((r1, 0.40), (2.00, 0.35), (0.0, 1.0)))  # noqa: E731
    if which == "tp1":
        return [(f"tp1={r}R", {"exit_cfg": tp(r)})
                for r in (0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.5)]
    if which == "size":
        return [(f"risk={p}%", {"risk_pct": p})
                for p in (0.05, 0.10, 0.19, 0.375, 0.75, 1.50, 3.00)]
    if which == "impact":
        return [(f"impact_coeff={c}", {"impact": c})
                for c in (0.01, 0.02, 0.05, 0.10, 0.20)]
    if which == "stops":
        return [(f"stop_sigma={m}", {"exit_cfg": ExitConfig(stop_sigma_mult=m)})
                for m in (1.8, 2.2, 2.8, 3.4, 4.0)]
    if which == "slippage":
        return [(f"slippage={b}bp", {"slippage": b})
                for b in (0.25, 0.5, 1.0, 2.0, 3.0)]
    if which == "combo":
        return [
            ("base (tp1=1.0, 0.75%)", {}),
            ("tp1=0.6 only", {"exit_cfg": tp(0.6)}),
            ("size 0.19% only", {"risk_pct": 0.19}),
            ("tp1=0.6 + size 0.19%", {"exit_cfg": tp(0.6), "risk_pct": 0.19}),
            ("tp1=0.6 + size 0.10%", {"exit_cfg": tp(0.6), "risk_pct": 0.10}),
        ]
    raise ValueError(which)


TITLES = {
    "tp1": "LEVER A — first target level (mean peak R is 0.62R, mean giveback 0.55R)",
    "size": "LEVER B — ticket size (impact ~ sqrt(N), P&L ~ N, so drag ~ sqrt(N))",
    "impact": "LEVER C — impact coefficient (ASSUMED, not measured — biggest unknown)",
    "stops": "LEVER D — stop width (the engine's own prescription; net is flat)",
    "slippage": "LEVER E — assumed slippage (2.0 bp vs a 16.1 bp impact — negligible)",
    "combo": "COMBINED — the two levers that are real, not assumptions",
}

DEFAULT_ORDER = ["tp1", "size", "impact", "stops", "slippage", "combo"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--only", default=",".join(DEFAULT_ORDER),
                    help=f"comma-separated subset of {DEFAULT_ORDER}")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    seeds = list(range(1, a.seeds + 1))
    results = {}
    for which in a.only.split(","):
        which = which.strip()
        if not which:
            continue
        results[which] = sweep(TITLES[which], build_variants(which),
                               seeds, a.days, a.tf)

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(results, indent=2))
        print(f"\nwrote {a.json}")

    print("\nReminder: these are synthetic-data measurements of a mechanism. "
          "Re-validate any change on real data with walk-forward / CSCV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
