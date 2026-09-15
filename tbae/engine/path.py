"""Intra-bar growth curve — "x% of the formed bar".

Question this answers: *at 40% of the way through a 15-minute bar, how much of
the final body has typically already happened?*  Two uses:

1. **Live/early exit.**  If a bar has consumed 60% of its duration but only 10%
   of its cohort's typical displacement, the move is stalling — the exit engine
   reads that as a time-stop signal.
2. **Realistic intra-bar replay.**  The cohort curve tells the backtester what a
   "normal" path shape looks like, which is the prior used when the minute path
   is missing and stop/target ordering has to be inferred.

The curve is computed per ``(weekday, hour)`` cohort because bar shape is
strongly seasonal: the first bar of the US session does not grow like a bar at
03:00 UTC.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Sequence

from . import timing as timing_mod
from .mathx import EPS, clamp, mean, safe_div
from .models import Bar, PathPoint


def growth_curve(bar: Bar) -> list[PathPoint]:
    """Displacement-from-open sampled at each minute close, normalised 0..1.

    ``formed_pct`` is ``|close_k - open_1| / |close_n - open_1|``.  When the final
    body is zero (doji) the normalisation is undefined; we then fall back to
    normalising by the bar's *range* so the curve still carries shape.
    """
    ms = bar.minute_path or ()
    n = len(ms)
    if n == 0:
        return []
    o = ms[0].open
    final_body = abs(bar.close - o)
    denom = final_body if final_body > EPS else (bar.high - bar.low)
    out: list[PathPoint] = []
    for i, m in enumerate(ms, start=1):
        formed = abs(m.close - o)
        out.append(
            PathPoint(
                minute_index=i,
                ts=m.ts,
                formed_abs=formed,
                formed_pct=clamp(safe_div(formed, denom, 0.0), 0.0, 5.0),
                elapsed_pct=i / n,
            )
        )
    return out


def cohort_key(bar: Bar) -> tuple[int, int]:
    """``(weekday, hour)`` bucket for cohort averaging.

    Falls back to deriving the tag from the timestamp rather than substituting 0:
    an untagged bar (``weekday == -1`` because :func:`timing.tag_bars` has not run
    yet) would otherwise be pooled into the Monday-00:00 cohort and silently
    corrupt its average curve.  The timestamp is always present, so the fallback
    is exact and removes an ordering dependency between pipeline stages.
    """
    wd, hr = bar.weekday, bar.hour
    if wd < 0:
        wd = timing_mod.weekday_of(bar.ts)
    if hr < 0:
        hr = timing_mod.hour_of(bar.ts)
    return (wd, hr)


def average_curve(
    bars: Sequence[Bar],
    weekday: int | None = None,
    hour: int | None = None,
    *,
    min_bars: int = 5,
) -> list[PathPoint]:
    """Mean growth curve across a cohort of bars.

    Bars with a different minute count are re-sampled onto a common 20-point
    grid by linear interpolation, so a 14-minute bar and a 15-minute bar can be
    averaged without biasing the tail.
    """
    GRID = 20
    picks: list[list[float]] = []
    for b in bars:
        if weekday is not None and b.weekday != weekday:
            continue
        if hour is not None and b.hour != hour:
            continue
        curve = growth_curve(b)
        if len(curve) < 2:
            continue
        picks.append(_resample_curve([p.formed_pct for p in curve], GRID))
    if len(picks) < min_bars:
        return []
    out: list[PathPoint] = []
    for g in range(GRID):
        frac = (g + 1) / GRID
        vals = [p[g] for p in picks]
        out.append(
            PathPoint(
                minute_index=g + 1,
                ts=0,
                formed_abs=0.0,
                formed_pct=mean(vals),
                elapsed_pct=frac,
            )
        )
    return out


def _resample_curve(values: Sequence[float], grid: int) -> list[float]:
    """Linear-interpolate ``values`` (uniformly spaced) onto ``grid`` points."""
    n = len(values)
    if n == 0:
        return [0.0] * grid
    if n == 1:
        return [values[0]] * grid
    out: list[float] = []
    for g in range(grid):
        x = (g + 1) / grid * (n - 1)
        lo = int(math.floor(x))
        hi = min(lo + 1, n - 1)
        frac = x - lo
        out.append(values[lo] * (1.0 - frac) + values[hi] * frac)
    return out


def expected_formed_pct(
    curve: Sequence[PathPoint], elapsed_frac: float
) -> float:
    """Read the cohort curve at a given elapsed fraction (interpolated)."""
    if not curve:
        return elapsed_frac  # no prior: assume linear growth
    xs = [p.elapsed_pct for p in curve]
    ys = [p.formed_pct for p in curve]
    x = clamp(elapsed_frac, 0.0, 1.0)
    for i in range(len(xs)):
        if xs[i] >= x:
            if i == 0:
                return ys[0]
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            if x1 - x0 < EPS:
                return y1
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ys[-1]


def completion_ratio(bar: Bar, curve: Sequence[PathPoint]) -> float:
    """Actual displacement vs cohort expectation at this point in the bar.

    ``< 1`` = behind schedule (stalling), ``> 1`` = ahead (extending).  Used by
    the time-stop and by the ``efficiency_collapse`` exit event.
    """
    ms = bar.minute_path or ()
    if not ms:
        return 1.0
    elapsed = len(ms) / max(1, bar.tf)
    expected = expected_formed_pct(curve, elapsed)
    o = ms[0].open
    actual = abs(ms[-1].close - o)
    denom = abs(bar.close - o) if abs(bar.close - o) > EPS else (bar.high - bar.low)
    actual_frac = clamp(safe_div(actual, denom, 0.0), 0.0, 5.0)
    return safe_div(actual_frac, expected, 1.0) if expected > EPS else 1.0


def curve_to_dicts(curve: Sequence[PathPoint]) -> list[dict[str, Any]]:
    return [
        {
            "minute_index": p.minute_index,
            "ts": p.ts,
            "formed_abs": p.formed_abs,
            "formed_pct": p.formed_pct,
            "elapsed_pct": p.elapsed_pct,
        }
        for p in curve
    ]


def build_cohort_curves(bars: Sequence[Bar], *, min_bars: int = 5) -> dict[str, list[PathPoint]]:
    """All ``(weekday, hour)`` cohort curves, for the dashboard's path overlay."""
    buckets: dict[tuple[int, int], list[Bar]] = defaultdict(list)
    for b in bars:
        buckets[cohort_key(b)].append(b)
    out: dict[str, list[PathPoint]] = {}
    for (wd, hr), group in buckets.items():
        c = average_curve(group, wd, hr, min_bars=min_bars)
        if c:
            out[f"{wd}-{hr}"] = c
    return out
