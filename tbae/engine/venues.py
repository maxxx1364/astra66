"""Per-symbol venue constants, measured from the data instead of assumed.

Why this module exists
----------------------
``CostConfig`` ships with a single set of numbers — ``commission_bps=4``,
``slippage_bps=2``, ``adv_notional=2e8`` — applied identically to every symbol.
That made every cross-symbol comparison in the project quietly unfair, in a
specific and important direction:

* ``adv_notional`` drives the square-root impact term.  A constant value means a
  thin symbol is charged the same market impact as the deepest pair on the
  venue, so it looks artificially *cheap*.
* ``slippage_bps`` is a floor on crossing the spread, but the spread can never
  be narrower than one tick.  BTCUSDT trades in 0.01 increments around ~100,000
  (a relative tick of ~1e-5 bp — effectively free), while XRPUSDT trades in
  0.0001 increments around ~2.5 (~0.4 bp).  Charging both the same 2 bp is not
  neutral: it flatters the coarse-tick symbol.

Both of those are measurable from the candles themselves, and measuring them is
better than tabulating exchange metadata that goes stale the moment a tick size
is revised.  So this module estimates them from the series and returns a
:class:`CostConfig` with the estimates substituted for the placeholders.

What is estimated, and what is not
---------------------------------
Estimated: tick size and average daily traded notional (ADV).
**Not** estimated: the fee schedule.  Commission depends on the account's VIP
tier and on whether BNB fee discount is on — neither is knowable from market
data.  Those stay a declared input (CLI ``--commission-bps``), and the estimate
is recorded alongside them so a reader can see which numbers were measured and
which were assumed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from .mathx import median
from .models import MinuteBar
from .risk import CostConfig

#: How many prices to sample when looking for the smallest tick.  Every observed
#: price is an exact multiple of the tick, so the minimum positive difference
#: between two distinct prices is the tick itself — provided the sample is large
#: enough to contain two adjacent ticks.  150k is comfortably enough for liquid
#: pairs and keeps the sort well under a second in pure Python.
_TICK_SAMPLE = 150_000

#: A price difference this small is floating-point residue, not a tick.
_TICK_EPS = 1e-12


# --------------------------------------------------------------------------- #
# estimators
# --------------------------------------------------------------------------- #
def estimate_tick_size(bars: Sequence[MinuteBar], *,
                       sample: int = _TICK_SAMPLE) -> float | None:
    """Smallest observable price increment, inferred from the candles.

    All traded prices are integer multiples of the venue's tick, so every
    difference between two distinct prices is also a multiple of it and the
    smallest positive difference *is* the tick.  The estimate can therefore only
    come out equal to or larger than the true tick (if the sample happens to miss
    adjacent ticks), never smaller — and erring large raises the slippage floor,
    which is the conservative direction.
    """
    if not bars:
        return None
    step = max(1, len(bars) // sample)
    seen = {round(float(b.close), 10) for b in bars[::step]}
    if len(seen) < 2:
        return None
    ordered = sorted(seen)
    best: float | None = None
    for a, b in zip(ordered, ordered[1:]):
        # Subtracting two large floats loses the low digits — 100000.03 −
        # 100000.02 is 0.00999999999476131, not 0.01.  Rounding the *difference*
        # to 8 significant digits recovers the exact tick without assuming
        # anything about the price scale.
        d = _round_sig(b - a, 8)
        if d > _TICK_EPS and (best is None or d < best):
            best = d
    return best


def estimate_adv_notional(bars: Sequence[MinuteBar]) -> float | None:
    """Median daily traded notional, in quote currency.

    The median across days rather than the mean: a listing's first weeks are
    an order of magnitude thinner than its steady state, and a mean would let
    that tail decide the impact term for the whole series.

    Days that hold far fewer bars than a typical day are dropped first.  A
    series almost always starts and ends mid-day, and those two stubs can pull
    the median down badly on a short window (measured: a 3-day sample read
    77M instead of 144M).  The threshold is relative to the observed median day
    length so the rule still works for any bar interval.
    """
    if not bars:
        return None
    totals: dict[int, float] = {}
    counts: dict[int, int] = {}
    for b in bars:
        day = b.ts // 86_400_000
        totals[day] = totals.get(day, 0.0) + float(getattr(b, "quote_volume", 0.0) or 0.0)
        counts[day] = counts.get(day, 0) + 1

    typical = median(sorted(counts.values())) if counts else 0.0
    floor_count = 0.6 * typical
    usable = [v for d, v in totals.items()
              if v > 0.0 and counts[d] >= floor_count]
    if not usable:                                  # every day is a stub
        usable = [v for v in totals.values() if v > 0.0]
    if not usable:
        return None
    return median(sorted(usable))


def _round_sig(x: float, digits: int = 8) -> float:
    """Round to ``digits`` significant figures, scale-independently."""
    if x <= 0.0 or x != x:
        return 0.0
    from math import floor, log10
    return round(x, -int(floor(log10(x))) + (digits - 1))


# --------------------------------------------------------------------------- #
# calibration
# --------------------------------------------------------------------------- #
def calibrate_costs(bars: Sequence[MinuteBar], costs: CostConfig | None = None, *,
                    apply_tick_floor: bool = True) -> tuple[CostConfig, dict[str, Any]]:
    """Return a cost config with the measurable placeholders filled in.

    The second return value is a provenance record — what was measured and
    whether each measurement actually moved a parameter.  It belongs in the run
    manifest: a backtest that assumes XRP is as liquid as BTC should say so on
    its face, and one that measured it should be able to prove it.
    """
    base = costs if costs is not None else CostConfig()
    out = replace(base)
    info: dict[str, Any] = {
        "measured": [],
        "assumed": ["commission_bps", "maker_bps", "impact_coeff"],
    }

    adv = estimate_adv_notional(bars)
    if adv and adv > 0:
        out.adv_notional = adv
        info["adv_notional"] = adv
        info["measured"].append("adv_notional")
    else:
        info["adv_notional"] = None

    tick = estimate_tick_size(bars)
    closes = [float(b.close) for b in bars[::max(1, len(bars) // 20_000)]]
    mid = median(sorted(closes)) if closes else None
    info["tick_size"] = tick
    info["median_price"] = mid

    if apply_tick_floor and tick and mid and mid > 0:
        # Crossing the spread costs at least half of it, and the spread is at
        # least one tick.  This is a floor, not a replacement: a venue can be
        # wider than its tick, and the declared slippage still covers that.
        half_spread_bps = 0.5 * tick / mid * 10_000.0
        info["tick_half_spread_bps"] = round(half_spread_bps, 6)
        if half_spread_bps > out.slippage_bps:
            out.slippage_bps = round(half_spread_bps, 6)
            info["slippage_raised_by_tick"] = True
            info["measured"].append("slippage_bps")
        else:
            info["slippage_raised_by_tick"] = False
            info["assumed"].append("slippage_bps")
    else:
        info["slippage_raised_by_tick"] = False
        info["assumed"].append("slippage_bps")

    info["slippage_bps"] = out.slippage_bps
    info["impact_bps_at_1pct_adv"] = round(
        out.impact_bps(0.01 * out.adv_notional), 6)
    out.validate()
    return out, info


def friction_per_r(costs: CostConfig, stop_distance_pct: float) -> float | None:
    """Round-trip friction expressed in R, the unit the edge is measured in.

    This is the number that decides whether a strategy is *cost-bound*: the same
    6 bp round trip is 0.03R against a 2% stop and 0.12R against a 0.5% stop.
    Quote it whenever two symbols are being compared, because comparing raw
    basis points across symbols with different volatility is what makes a
    high-volatility pair look free.
    """
    if stop_distance_pct is None or stop_distance_pct <= 0:
        return None
    round_trip_bps = costs.commission_bps + costs.maker_bps + 2.0 * costs.slippage_bps
    return round_trip_bps / (stop_distance_pct * 100.0)


def symbol_from_path(path: str) -> str | None:
    """Best-effort symbol label from a store filename (``XRPUSDT_1m_...csv.gz``)."""
    import os

    stem = os.path.basename(str(path)).split("_")[0].upper()
    return stem or None


__all__ = [
    "estimate_tick_size", "estimate_adv_notional", "calibrate_costs",
    "friction_per_r", "symbol_from_path",
]
