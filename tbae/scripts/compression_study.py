"""Base-rate study: does compression actually precede explosive moves?

Run from ``tbae/``::

    # smoke test on the deterministic generator (GARCH: alpha .08 + beta .90,
    # so it really does cluster — quiet stretches followed by volatile ones)
    python3 scripts/compression_study.py --seeds 8 --days 120 --tf 15

    # one real symbol
    python3 scripts/compression_study.py --feed csv:data/binance/SOLUSDT_1m.csv.gz \
        --tf 60 --json ../reports/compression_SOL.json

    # the whole universe the CI downloaded
    python3 scripts/compression_study.py --feeds-dir data/binance --tf 60

Why this exists
---------------
The fee arithmetic from ``docs/FRICTION.md``: on Wallex the round trip costs
about **0.46R**, so with the *current* payoff profile (payoff ratio ~1.1R, win
rate ~44-52%) the system is dead — it would need a ~71% win rate to break
even.  The escape is not lower fees; it is a **much bigger average win**:

    E[R] = p*W - (1-p)*L - c     with L = 1R, c = 0.46R

    W (avg win)   break-even win rate
       1.1R            71%      <- where the system is now (delivers 44-52%)
       2.0R            49%
       3.0R            37%
       5.0R            25%
       8.0R            17%

So the pivot to "coins coiled in a range that then break out" reduces to one
measurable question: **among compressed coins, how often does a >=5R move
follow, and how much more often than unconditionally?**

This script answers it, and — with ``--profile`` — measures *which* feature
carries the signal, so the screening rules are read off the data rather than
invented.

Outcome
-------
Forward maximum favourable excursion over the next ``horizon`` bars, in **ATR
units** — a compression breakout is naturally stopped below the range, so 1 ATR
of risk makes an X-ATR move an X-R win.  No look-ahead: the event uses bars
``<= i``, the outcome bars ``> i``.

Caveats that survive every rewrite
----------------------------------
* **MFE is not realised return.**  It is "if you had sold at the peak" — an
  optimistic ceiling.  A trailing stop captures some fraction of it.
* **Synthetic results are a harness check only.**  GARCH clusters volatility by
  construction, so "low vol now -> higher vol later" is partly true *by
  definition* in the generator.  A lift here means the plumbing works; it is
  not evidence about any real market.
* The control matters as much as the signal: if 36% of *all* bars reach 5R,
  then a 5R move is not rare, and the filter is buying a tilt on a common
  event — which is a much weaker claim than finding a rare one.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import feeds, indicators, pipeline  # noqa: E402
from engine.classify import Category  # noqa: E402
from engine.models import Settings  # noqa: E402
from engine.volatility import atr_series  # noqa: E402

THRESHOLDS = (2.0, 3.0, 5.0, 8.0, 13.0)
HEADLINE = 5.0  # the R multiple the fee arithmetic says we need


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _pct_rank_series(xs: list[float], window: int) -> list[float]:
    """Rolling percentile rank of x within the trailing window, in [0, 1]."""
    out = [float("nan")] * len(xs)
    for i in range(len(xs)):
        lo = max(0, i - window + 1)
        win = xs[lo: i + 1]
        if len(win) < 20:
            continue
        xi = xs[i]
        if xi != xi:  # NaN
            continue
        out[i] = sum(1 for v in win if v <= xi) / len(win)
    return out


def _sustained(flags: list[bool], k: int) -> list[bool]:
    out = [False] * len(flags)
    run = 0
    for i, f in enumerate(flags):
        run = run + 1 if f else 0
        out[i] = run >= k
    return out


def _rates(mask: list[bool], mfe: list[float]) -> dict | None:
    n = sum(1 for m in mask if m)
    if n < 30:
        return None
    sel = [mfe[i] for i in range(len(mask)) if mask[i]]
    return {
        "n": n,
        "mfe_median": statistics.median(sel),
        **{f"p_ge_{t:g}R": sum(1 for v in sel if v >= t) / n for t in THRESHOLDS},
    }


def _merge(rows: list[dict | None]) -> dict | None:
    rows = [r for r in rows if r]
    if not rows:
        return None
    tot = sum(r["n"] for r in rows)
    out = {"n": tot, "mfe_median": statistics.median(
        [r["mfe_median"] for r in rows])}
    for t in THRESHOLDS:
        out[f"p_ge_{t:g}R"] = sum(r[f"p_ge_{t:g}R"] * r["n"] for r in rows) / tot
    return out


# --------------------------------------------------------------------------- #
# per-symbol work
# --------------------------------------------------------------------------- #
def prepare(bars: list, a) -> dict | None:
    """Compute the forward outcome and every candidate feature once."""
    if len(bars) < a.horizon + a.rank_window + 60:
        return None
    ind = indicators.compute(bars, Settings())
    atr = atr_series(bars, 14)
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    n = len(bars)

    # forward max favourable excursion, in ATR — precomputed once, reused by
    # every filter below (the O(n*horizon) pass is the expensive part)
    mfe = [float("nan")] * n
    for i in range(n):
        if i + a.horizon >= n:
            break
        a_i = atr[i]
        if not (a_i == a_i) or a_i <= 0:
            continue
        mfe[i] = (max(highs[i + 1: i + 1 + a.horizon]) - closes[i]) / a_i

    don_w, don_hi, don_lo = [], ind.donchian_hi, ind.donchian_lo
    for i in range(n):
        if don_hi[i] > 0 and don_lo[i] > 0 and closes[i] > 0:
            don_w.append((don_hi[i] - don_lo[i]) / closes[i])
        else:
            don_w.append(float("nan"))
    don_rank = _pct_rank_series(don_w, a.rank_window)

    # where inside the Donchian channel the price sits (0 = at the floor)
    pos = [float("nan")] * n
    for i in range(n):
        if don_hi[i] > 0 and don_lo[i] > 0 and don_hi[i] > don_lo[i]:
            pos[i] = (closes[i] - don_lo[i]) / (don_hi[i] - don_lo[i])

    valid = [i for i in range(n) if mfe[i] == mfe[i]]
    return {
        "n_bars": n, "mfe": mfe, "valid": valid,
        "squeeze": list(ind.squeeze),
        "bb_rank": list(ind.bb_width_rank),
        "don_rank": don_rank,
        "pos": pos,
        "vol_z": list(ind.vol_z),
        "dead": [b.category == Category.WEAK for b in bars],
        "atr_rank": list(ind.atr_pct_rank),
    }


def definitions(p: dict, a) -> dict[str, list[bool]]:
    n = p["n_bars"]
    in_range = [(p["don_rank"][i] == p["don_rank"][i]
                 and p["don_rank"][i] <= a.range_rank) for i in range(n)]
    sq = p["squeeze"]
    return {
        "all bars (control)": [True] * n,
        "squeeze": sq,
        f"range >= {a.min_bars}b": _sustained(in_range, a.min_bars),
        f"dead >= {a.min_bars}b": _sustained(p["dead"], a.min_bars),
        "squeeze AND range": [x and y for x, y in
                              zip(sq, _sustained(in_range, a.min_bars))],
    }


def profile(p: dict, a) -> dict[str, list[tuple[str, list[bool]]]]:
    """Sweep each feature so the screening rules come from the data."""
    n = p["n_bars"]
    out: dict[str, list[tuple[str, list[bool]]]] = {}

    in_range_r = {}
    for r in (0.10, 0.20, 0.30, 0.50):
        in_range_r[r] = _sustained(
            [(p["don_rank"][i] == p["don_rank"][i] and p["don_rank"][i] <= r)
             for i in range(n)], a.min_bars)

    out["range width percentile"] = [
        (f"<= {r:.2f}", in_range_r[r]) for r in (0.10, 0.20, 0.30, 0.50)]
    out["bars stuck in range"] = [
        (f">= {k}b", _sustained(in_range_r[a.range_rank], k))
        for k in (3, 6, 10, 16, 24)]
    out["bollinger squeeze rank"] = [
        (f"<= {r:.2f}", [p["bb_rank"][i] == p["bb_rank"][i]
                         and p["bb_rank"][i] <= r for i in range(n)])
        for r in (0.05, 0.10, 0.20, 0.30)]
    out["ATR percentile (how quiet)"] = [
        (f"<= {r:.2f}", [p["atr_rank"][i] == p["atr_rank"][i]
                         and p["atr_rank"][i] <= r for i in range(n)])
        for r in (0.10, 0.20, 0.35, 0.50)]
    out["position inside channel"] = [
        (f"{lo:.1f}-{hi:.1f}",
         [p["pos"][i] == p["pos"][i] and lo <= p["pos"][i] < hi
          for i in range(n)])
        for lo, hi in ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01))]

    vz = p["vol_z"]
    known = [v for v in vz if v == v]
    if known:
        lo_t, hi_t = statistics.quantiles(known, n=3)[0], \
            statistics.quantiles(known, n=3)[1]
        out["volume z during coil"] = [
            (f"bottom third (<{lo_t:+.2f})",
             [v == v and v <= lo_t for v in vz]),
            (f"top third (>{hi_t:+.2f})", [v == v and v >= hi_t for v in vz]),
        ]
    return out


# --------------------------------------------------------------------------- #
# drivers
# --------------------------------------------------------------------------- #
def load_bars(a) -> list[tuple[str, list]]:
    if a.feeds_dir:
        paths = sorted(glob.glob(os.path.join(a.feeds_dir, "*.csv"))
                       + glob.glob(os.path.join(a.feeds_dir, "*.csv.gz")))
        out = []
        for p in paths:
            # load_feed() wants a spec ("csv:path"), not a bare path
            b = bars_for(f"csv:{p}", a)
            if b:
                out.append((Path(p).stem.replace("_1m", ""), b))
        return out
    if a.feed and not a.feed.startswith("synthetic"):
        spec = a.feed if ":" in a.feed else f"csv:{a.feed}"
        return [(Path(spec).stem, bars_for(spec, a))]
    out = []
    for seed in range(1, a.seeds + 1):
        minutes = feeds.SyntheticFeed(
            feeds.SyntheticConfig(days=a.days, seed=seed)).load()
        out.append((f"seed{seed}",
                    pipeline.run(minutes, settings=Settings(), tf=a.tf).bars))
    return out


def bars_for(spec: str, a):
    try:
        minutes = feeds.load_feed(spec)
        return pipeline.run(minutes, settings=Settings(), tf=a.tf).bars
    except Exception as exc:  # a bad CSV must not kill the whole universe
        print(f"  ! skipping {spec}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed", default="synthetic")
    ap.add_argument("--feeds-dir", default=None,
                    help="directory of *.csv / *.csv.gz, one per symbol")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--tf", type=int, default=15)
    ap.add_argument("--horizon", type=int, default=40)
    ap.add_argument("--min-bars", type=int, default=6)
    ap.add_argument("--range-rank", type=float, default=0.20)
    ap.add_argument("--rank-window", type=int, default=200)
    ap.add_argument("--profile", action="store_true",
                    help="also sweep each feature to build the screen")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    runs = [(nm, b) for nm, b in load_bars(a) if b]
    if not runs:
        print("no data loaded", file=sys.stderr)
        return 1

    print(f"\nsymbols={len(runs)}  tf={a.tf}m  horizon={a.horizon}b  "
          f"min_bars={a.min_bars}  range_rank={a.range_rank}")

    prepped = [(nm, prepare(b, a)) for nm, b in runs]
    prepped = [(nm, p) for nm, p in prepped if p]
    if not prepped:
        print("no usable symbols (too few bars?)", file=sys.stderr)
        return 1

    # ---------------- headline table ----------------
    def_names = list(definitions(prepped[0][1], a).keys())
    print(f"\n{'definition':26} {'n':>8} {'med MFE':>8} "
          + " ".join(f">{t:g}R".rjust(7) for t in THRESHOLDS))
    print("-" * (26 + 9 + 9 + 8 * len(THRESHOLDS)))
    pooled, base = {}, None
    for name in def_names:
        rows = [_rates(list(definitions(p, a)[name]), p["mfe"])
                for _, p in prepped]
        m = _merge(rows)
        if not m:
            print(f"{name:26} (too few events)")
            continue
        pooled[name] = m
        if name == "all bars (control)":
            base = m
        print(f"{name:26} {m['n']:>8} {m['mfe_median']:>8.2f} "
              + " ".join(f"{m[f'p_ge_{t:g}R'] * 100:>6.1f}%" for t in THRESHOLDS))

    if base:
        print(f"\nlift vs unconditional control at >={HEADLINE:g}R "
              f"(base {base[f'p_ge_{HEADLINE:g}R'] * 100:.1f}%, "
              f"1.00x = no predictive value):")
        for name, m in pooled.items():
            if name == "all bars (control)":
                continue
            print(f"  {name:26} "
                  + "  ".join(f"{t:g}R:{m[f'p_ge_{t:g}R'] / base[f'p_ge_{t:g}R']:>5.2f}x"
                              for t in THRESHOLDS if base[f"p_ge_{t:g}R"]))

    # ---------------- feature profile ----------------
    prof = None
    if a.profile and base:
        prof = {}
        print(f"\n{'=' * 78}\nFEATURE PROFILE — lift at >={HEADLINE:g}R, "
              f"pooled across {len(prepped)} symbols\n{'=' * 78}")
        b5 = base[f"p_ge_{HEADLINE:g}R"]
        for feat, variants in profile(prepped[0][1], a).items():
            print(f"\n{feat}   (base rate {b5 * 100:.1f}%)")
            for label, mask in variants:
                m = _merge([_rates(list(mask), p["mfe"]) for _, p in prepped])
                if not m:
                    print(f"    {label:26} (too few events)")
                    continue
                lift = m[f"p_ge_{HEADLINE:g}R"] / b5 if b5 else float("nan")
                bar = "#" * int(round(max(0.0, lift - 1.0) * 60))
                print(f"    {label:26} n={m['n']:>7}  "
                      f"{m[f'p_ge_{HEADLINE:g}R'] * 100:>5.1f}%  "
                      f"{lift:>5.2f}x  {bar}")
                prof.setdefault(feat, []).append(
                    {"bucket": label, **{k: v for k, v in m.items()},
                     "lift": lift})

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"symbols": [nm for nm, _ in prepped],
             "definitions": pooled, "profile": prof}, indent=2))
        print(f"\nwrote {a.json}")

    print("\nReminder: MFE is a ceiling, not a captured return.  On synthetic")
    print("data a lift is a harness check, not evidence — GARCH clusters")
    print("volatility by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
