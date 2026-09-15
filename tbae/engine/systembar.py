"""System bar — non-neutralised mobility.

The chart bar (``close_n - open_1``) hides everything that happened in between:
a bar that ran up 3%, collapsed, and closed flat looks identical to a bar that
never moved.  The system bar measures the *path*, not the displacement.

Definitions (mirrors README section 3)
--------------------------------------
Given the source minutes ``i = 1..n`` of one aggregate bar:

    leg_1     = close_1 - open_1
    leg_i     = close_i - close_{i-1}          for i = 2..n

    S         = sum |leg_i|                    (total non-neutralised mobility)
    S_up      = sum max(leg_i, 0)
    S_down    = sum |min(leg_i, 0)|
    S_intra   = sum (high_i - low_i)           (intra-minute wick mobility)

    chart_abs   = |close_n - open_1|
    chart_range = high - low
    efficiency  = clamp(chart_abs / S, 0, 1)
    leg_skew    = (S_up - S_down) / S          in [-1, 1]

Invariant
---------
By the triangle inequality ``S >= chart_abs`` always holds, so ``efficiency`` is
naturally bounded by 1.  This is why the specification's "strong" rule is
``chart_pct >= 55% AND system_pct < 55%``: a large *useful* move achieved with
only moderate total mobility — i.e. price travelled in a straight line.  The
opposite corner (huge ``S``, tiny ``chart_abs``) is the "pressure" bar: lots of
fight, no territory.

``S`` and ``S_intra`` are kept separate rather than summed: ``high_i - low_i``
already contains minute ``i``'s own body, so ``S + S_intra`` would double count
it.  Consumers that want a single "total churn" figure should use
:func:`total_churn`, which is explicit about doing so.
"""

from __future__ import annotations

import math
from typing import Sequence

from .mathx import EPS, clamp, safe_div
from .models import Bar, MinuteBar


# --------------------------------------------------------------------------- #
# leg extraction
# --------------------------------------------------------------------------- #
def leg_series(minutes: Sequence[MinuteBar]) -> list[float]:
    """Close-to-close legs, including the first minute's open->close leg."""
    if not minutes:
        return []
    legs = [minutes[0].close - minutes[0].open]
    prev = minutes[0].close
    for m in minutes[1:]:
        legs.append(m.close - prev)
        prev = m.close
    return legs


def cumulative_path(minutes: Sequence[MinuteBar]) -> list[float]:
    """Running displacement from the bar's open, sampled at each minute close.

    Length == len(minutes).  ``cumulative_path[-1] == close_n - open_1``.
    """
    if not minutes:
        return []
    o = minutes[0].open
    return [m.close - o for m in minutes]


def path_extremes(minutes: Sequence[MinuteBar]) -> tuple[float, float]:
    """(max, min) displacement from open reached *within* the bar.

    Uses minute closes only (the sampled path), so it is strictly inside
    ``[low - open, high - open]``; that gap is intentional and is what makes the
    value an honest measure of where the *traded path* went.
    """
    cp = cumulative_path(minutes)
    if not cp:
        return (0.0, 0.0)
    return (max(cp), min(cp))


def tail_flow(minutes: Sequence[MinuteBar], frac: float = 1.0 / 3.0) -> tuple[float, int]:
    """Sum of legs over the last ``frac`` of the bar, plus how many legs.

    This is the earliest available microstructure evidence of a reversal: the
    bar can still close green while its final minutes are being sold into.  The
    exit engine consumes it as the ``leg_flow_flip`` event.
    """
    legs = leg_series(minutes)
    if not legs:
        return (0.0, 0)
    k = max(1, int(math.ceil(len(legs) * clamp(frac, 0.0, 1.0))))
    tail = legs[-k:]
    return (math.fsum(tail), len(tail))


def head_flow(minutes: Sequence[MinuteBar], frac: float = 1.0 / 3.0) -> tuple[float, int]:
    legs = leg_series(minutes)
    if not legs:
        return (0.0, 0)
    k = max(1, int(math.ceil(len(legs) * clamp(frac, 0.0, 1.0))))
    head = legs[:k]
    return (math.fsum(head), len(head))


def flow_imbalance(minutes: Sequence[MinuteBar]) -> float:
    """Aggressor-flow imbalance in [-1, 1].

    Uses taker buy volume when the feed supplies it, else falls back to a
    minute-direction proxy (volume of up-minutes minus volume of down-minutes).
    Positive = buyers were the aggressors.
    """
    total = math.fsum(m.volume for m in minutes)
    if total <= EPS:
        return 0.0
    taker = math.fsum(m.taker_buy_volume for m in minutes)
    if taker > EPS:
        return clamp((2.0 * taker - total) / total, -1.0, 1.0)
    buy = math.fsum(m.volume for m in minutes if m.close > m.open)
    sell = math.fsum(m.volume for m in minutes if m.close < m.open)
    return clamp(safe_div(buy - sell, buy + sell, 0.0), -1.0, 1.0)


def intra_bar_rv(minutes: Sequence[MinuteBar]) -> float:
    """Realised volatility of the minute path over the bar, in price units.

    ``sqrt(sum(leg_i^2))`` — the quadratic variation of the sampled path.  Unlike
    the close-to-close range this *sees* chop, which is exactly what a stop-loss
    needs to be sized against.
    """
    legs = leg_series(minutes)
    if not legs:
        return 0.0
    return math.sqrt(math.fsum(l * l for l in legs))


def total_churn(bar: Bar) -> float:
    """``S + S_intra`` — an explicit 'everything moved' figure.

    Double counts minute bodies on purpose; useful as a relative activity gauge,
    **not** as a displacement measure.
    """
    return bar.s_total + bar.s_intra


# --------------------------------------------------------------------------- #
# annotation
# --------------------------------------------------------------------------- #
def compute_system_bar(bar: Bar, minutes: Sequence[MinuteBar] | None = None) -> Bar:
    """Fill the system-bar fields of ``bar`` in place and return it."""
    ms = minutes if minutes is not None else (bar.minute_path or ())
    if not ms:
        # No minute path: degrade gracefully to range-based estimates so a
        # caller feeding pre-aggregated OHLCV still gets usable numbers.
        bar.chart_abs = abs(bar.close - bar.open)
        bar.chart_range = bar.high - bar.low
        bar.s_total = bar.chart_range
        bar.s_up = max(bar.body, 0.0)
        bar.s_down = max(-bar.body, 0.0)
        bar.s_intra = bar.chart_range
        bar.s_first_leg = abs(bar.body)
        bar.efficiency = clamp(safe_div(bar.chart_abs, bar.s_total, 0.0), 0.0, 1.0)
        bar.leg_skew = clamp(safe_div(bar.s_up - bar.s_down, bar.s_total, 0.0), -1.0, 1.0)
        return bar

    legs = leg_series(ms)
    s_up = math.fsum(l for l in legs if l > 0)
    s_down = math.fsum(-l for l in legs if l < 0)
    s_total = math.fsum(abs(l) for l in legs)
    s_intra = math.fsum(m.high - m.low for m in ms)

    bar.s_up = s_up
    bar.s_down = s_down
    bar.s_total = s_total
    bar.s_intra = s_intra
    bar.s_first_leg = abs(legs[0]) if legs else 0.0
    bar.chart_abs = abs(bar.close - bar.open)
    bar.chart_range = bar.high - bar.low
    bar.efficiency = clamp(safe_div(bar.chart_abs, s_total, 0.0), 0.0, 1.0)
    bar.leg_skew = clamp(safe_div(s_up - s_down, s_total, 0.0), -1.0, 1.0)
    return bar


def annotate(bars: Sequence[Bar]) -> list[Bar]:
    """Bulk system-bar annotation over an already-resampled series."""
    for b in bars:
        compute_system_bar(b)
    return list(bars)


def describe(bar: Bar) -> dict[str, float]:
    """Human/API friendly decomposition of one bar's mobility."""
    s = bar.s_total
    return {
        "S": s,
        "S_up": bar.s_up,
        "S_down": bar.s_down,
        "S_intra": bar.s_intra,
        "chart_abs": bar.chart_abs,
        "chart_range": bar.chart_range,
        "efficiency": bar.efficiency,
        "leg_skew": bar.leg_skew,
        "up_share": safe_div(bar.s_up, s, 0.0),
        "down_share": safe_div(bar.s_down, s, 0.0),
        "path_to_range": safe_div(s, bar.chart_range, 0.0),
        "total_churn": total_churn(bar),
    }


def reconstitute_close(bar: Bar) -> float:
    """Sanity check: open + signed legs must equal the close.

    Exposed for tests — if this ever fails, the resampler and the leg extractor
    disagree, and every downstream percentage is wrong.
    """
    ms = bar.minute_path or ()
    if not ms:
        return bar.close
    return ms[0].open + math.fsum(leg_series(ms))
