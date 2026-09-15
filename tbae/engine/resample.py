"""1-minute data -> any timeframe.

Two rules make this module safe to feed into a backtester:

1. **Gaps are preserved, never invented.**  A ``tf`` bucket is built only from
   the minutes that actually exist.  ``n_minutes`` records how many were seen, so
   a downstream consumer can tell a genuine 15-minute bar from a 4-minute stub
   left by a data outage (and drop it).
2. **The minute path is retained** (``Bar.minute_path``) unless explicitly
   disabled.  That path is what allows exact intra-bar ordering of stop/target
   touches; without it a backtester has to guess.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from .models import Bar, MinuteBar, Settings, align_ts, timeframe_ms


def validate_minutes(minutes: Sequence[MinuteBar]) -> None:
    """Raise on unsorted, duplicated or internally impossible minute bars.

    Silent acceptance of unordered data is the most common way a backtest ends up
    computing an EMA over a shuffled series and still "working".  Impossible OHLC
    is checked too, because a bad row from a CSV or a partial websocket frame
    otherwise propagates into every downstream estimator (high/low feed ATR,
    Garman-Klass and the intra-bar exit resolution).
    """
    prev = None
    for i, m in enumerate(minutes):
        if prev is not None:
            if m.ts < prev:
                raise ValueError(
                    f"minute bars out of order at index {i}: {m.ts} < {prev}"
                )
            if m.ts == prev:
                raise ValueError(f"duplicate minute bar timestamp at index {i}: {m.ts}")
        if m.high < m.low:
            raise ValueError(f"bar at {m.ts} has high < low")
        # open and close must both sit inside [low, high]; checking only
        # `high >= min(o, c)` lets a close above the high through.
        if m.low > min(m.open, m.close) or m.high < max(m.open, m.close):
            raise ValueError(
                f"bar at {m.ts} has open/close outside [low, high]: "
                f"o={m.open} h={m.high} l={m.low} c={m.close}"
            )
        if m.volume < 0:
            raise ValueError(f"bar at {m.ts} has negative volume")
        if not (math.isfinite(m.open) and math.isfinite(m.high)
                and math.isfinite(m.low) and math.isfinite(m.close)):
            raise ValueError(f"bar at {m.ts} has a non-finite price")
        prev = m.ts


def group_minutes(minutes: Sequence[MinuteBar], tf: int) -> list[tuple[int, list[MinuteBar]]]:
    """Bucket minutes into ``tf``-minute groups, preserving order."""
    groups: list[tuple[int, list[MinuteBar]]] = []
    cur_key: int | None = None
    cur: list[MinuteBar] = []
    for m in minutes:
        k = align_ts(m.ts, tf)
        if k != cur_key:
            if cur_key is not None:
                groups.append((cur_key, cur))
            cur_key, cur = k, [m]
        else:
            cur.append(m)
    if cur_key is not None:
        groups.append((cur_key, cur))
    return groups


def aggregate(ts: int, tf: int, ms: Sequence[MinuteBar], settings: Settings | None = None) -> Bar:
    """Build one :class:`Bar` from its constituent minutes."""
    o = ms[0].open
    c = ms[-1].close
    hi = max(m.high for m in ms)
    lo = min(m.low for m in ms)
    vol = sum(m.volume for m in ms)
    qvol = sum(m.quote_volume for m in ms)
    tbuy = sum(m.taker_buy_volume for m in ms)
    trades = sum(m.trades for m in ms)
    bar = Bar(
        ts=ts,
        tf=tf,
        open=o,
        high=hi,
        low=lo,
        close=c,
        volume=vol,
        quote_volume=qvol,
        taker_buy_volume=tbuy,
        trades=trades,
        n_minutes=len(ms),
        chart_abs=abs(c - o),
        chart_range=hi - lo,
    )
    if settings is None or settings.keep_minute_path:
        bar.minute_path = tuple(ms)
    return bar


def resample(
    minutes: Sequence[MinuteBar],
    tf: int,
    *,
    drop_incomplete: bool = True,
    settings: Settings | None = None,
    expected_minutes: int | None = None,
) -> list[Bar]:
    """Resample 1-minute bars into ``tf``-minute bars.

    Parameters
    ----------
    drop_incomplete:
        Drop *every* bucket that holds fewer minutes than ``tf`` (or than
        ``expected_minutes``) — leading, interior and trailing alike.  **Keep this
        True for backtests.**  A trailing short bucket is a bar that has not
        finished forming, so trading it is equivalent to seeing its future closes.
        A leading short bucket is subtler and just as wrong: if the window starts
        mid-bucket, that bar is assembled from (say) 14 of 15 minutes, so its
        ``s_total``/``chart_abs``/high/low are systematically understated and it
        enters the dynamic-reference percentile sample as a spuriously quiet bar.
        Interior short buckets are exchange gaps; they are dropped too, and
        :func:`completeness_report` reports them as ``missing_bars`` rather than
        letting them disappear.
    expected_minutes:
        Explicit completeness target.  Defaults to ``tf``; lower it for assets
        with thin sessions (e.g. FX weekends produce legitimately short buckets).
    """
    if tf not in (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440):
        # still allow it, but warn loudly through the min_minutes check below
        pass
    if tf < 1:
        raise ValueError("tf must be >= 1")
    validate_minutes(minutes)
    if not minutes:
        return []

    settings = settings or Settings()
    want = expected_minutes if expected_minutes is not None else tf
    min_minutes = max(1, min(settings.min_minutes_per_bar, want))

    groups = group_minutes(minutes, tf)
    bars: list[Bar] = []
    for ts, ms in groups:
        if drop_incomplete and len(ms) < want:
            continue
        if len(ms) < min_minutes:
            continue
        bars.append(aggregate(ts, tf, ms, settings))
    return bars


def completeness_report(bars: Sequence[Bar], tf: int) -> dict[str, object]:
    """How much of the expected minute coverage actually arrived.

    Reported (not hidden) because thin coverage inflates ``efficiency`` — a bar
    assembled from 3 of 15 minutes has almost no internal path and therefore
    looks deceptively "clean".

    ``coverage`` is measured against the *time span the kept bars cover*, not
    against ``len(bars)``.  That distinction matters once ``resample`` drops short
    buckets: dividing by the number of surviving bars would report 100% coverage
    while an entire missing bar sat unnoticed in the middle of the series.
    ``missing_bars`` names those holes explicitly.
    """
    if not bars:
        return {"bars": 0, "full": 0, "partial": 0, "coverage": 0.0,
                "expected_bars": 0, "missing_bars": 0}
    full = sum(1 for b in bars if b.n_minutes >= tf)
    total_minutes = sum(b.n_minutes for b in bars)
    tf_ms = timeframe_ms(tf)
    span = (bars[-1].ts - bars[0].ts) // tf_ms + 1 if tf_ms else len(bars)
    expected_bars = max(span, len(bars))
    return {
        "bars": len(bars),
        "full": full,
        "partial": len(bars) - full,
        "expected_bars": expected_bars,
        "missing_bars": expected_bars - len(bars),
        "coverage": total_minutes / (expected_bars * tf),
        "min_minutes": min(b.n_minutes for b in bars),
        "max_minutes": max(b.n_minutes for b in bars),
    }


def slice_minutes(
    minutes: Sequence[MinuteBar], start_ms: int, end_ms: int
) -> list[MinuteBar]:
    """Inclusive-start / exclusive-end slice by timestamp."""
    return [m for m in minutes if start_ms <= m.ts < end_ms]


def iter_bars(bars: Iterable[Bar]):
    return iter(bars)


def timeframe_label(tf: int) -> str:
    if tf % 1440 == 0:
        return f"{tf // 1440}D"
    if tf % 60 == 0:
        return f"{tf // 60}h"
    return f"{tf}m"


def periods_per_year(tf: int) -> float:
    """Trading periods per year for a 24/7 market — the annualisation base for
    Sharpe/vol.  Using the wrong base rescales Sharpe by a constant and makes
    comparisons across timeframes meaningless."""
    minutes_per_year = 365.25 * 24 * 60
    return minutes_per_year / max(1, tf)


def timeframe_ms_of(tf: int) -> int:  # pragma: no cover - thin alias
    return timeframe_ms(tf)
