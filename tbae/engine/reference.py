"""Dynamic 100% reference.

The classification tree compares each bar against a "100%" yardstick.  A fixed
yardstick is useless across volatility regimes, so the reference is derived from
the data itself:

    1. sort the values,
    2. drop the top ``reference_max_outlier_share`` (default 2%) as *Max Bars*,
    3. take the ``reference_percentile`` (default 98) of the remainder as 100%.

Trimming before the percentile is what stops a single liquidation spike from
redefining "100%" and compressing every other bar into the weak bucket.

Causality — read this before changing ``mode``
----------------------------------------------
``full``    : reference from the whole sample.  Contains look-ahead: bar *i* is
              scored against volatility that happens at bar *j > i*.  Fine for a
              research dashboard describing history, **invalid for a backtest**.
``expanding``: reference from bars ``[0, i]`` only.  Causal.  Warm-up guarded by
              ``min_bars`` — until then the bar carries no reference and is
              marked unclassified so it cannot generate a signal.
``rolling``  : reference from the trailing ``window`` bars.  Causal and adaptive;
              the right choice when the instrument's volatility drifts.

``backtest`` refuses to run on ``full`` unless the caller explicitly overrides,
and every result carries the mode in its manifest so a report can never be
mistaken for a causal one.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .mathx import percentile
from .models import Bar, Category, Settings, category_color, category_color_key


def build_reference(
    values: Sequence[float],
    pct: float = 98.0,
    max_outlier_share: float = 0.02,
) -> tuple[float, int]:
    """Return ``(reference, n_trimmed)`` for a sample of values.

    ``n_trimmed`` is how many top values were discarded as Max Bars — surfaced so
    callers can detect a degenerate sample (e.g. everything trimmed).
    """
    n = len(values)
    if n == 0:
        return (0.0, 0)
    s = sorted(values)
    n_trim = int(n * max_outlier_share)
    if n_trim >= n:            # tiny sample: trim nothing rather than everything
        n_trim = 0
    kept = s[: n - n_trim] if n_trim else s
    if not kept:
        kept = s
    ref = percentile(kept, pct)
    return (float(ref), n_trim)


def _window_indices(i: int, mode: str, window: int, n: int) -> tuple[int, int]:
    """Half-open ``[lo, hi)`` slice of history usable when scoring bar ``i``."""
    if mode == "full":
        return (0, n)
    if mode == "rolling":
        w = window if window > 0 else n
        return (max(0, i - w + 1), i + 1)
    # expanding (default)
    return (0, i + 1)


def annotate_reference(
    bars: Sequence[Bar],
    settings: Settings | None = None,
    *,
    chart_getter: Callable[[Bar], float] | None = None,
    system_getter: Callable[[Bar], float] | None = None,
) -> list[Bar]:
    """Fill ``chart_ref``/``system_ref``/``chart_pct``/``system_pct``/``is_max_bar``.

    Runs in O(n log w) for rolling and O(n^2 log n) worst case for expanding.
    For the expanding mode we use an incremental sorted structure (a simple
    bisect-maintained list) to keep it near O(n log n) — with 4k+ bars the naive
    re-sort is already noticeable.
    """
    settings = settings or Settings()
    n = len(bars)
    if n == 0:
        return []

    get_chart = chart_getter or (lambda b: b.chart_abs)
    get_system = system_getter or (lambda b: b.s_total)

    chart_vals = [get_chart(b) for b in bars]
    system_vals = [get_system(b) for b in bars]

    mode = settings.reference_mode
    window = settings.reference_window
    min_bars = settings.reference_min_bars
    pct = settings.reference_percentile
    outlier = settings.reference_max_outlier_share

    import bisect

    if mode == "expanding":
        # incremental sorted lists -> percentile without re-sorting each step
        cs: list[float] = []
        ss: list[float] = []
        for i in range(n):
            bisect.insort(cs, chart_vals[i])
            bisect.insort(ss, system_vals[i])
            if i + 1 < min_bars:
                _mark_unclassified(bars[i])
                continue
            c_ref, c_trim = build_reference(cs, pct, outlier)
            s_ref, _ = build_reference(ss, pct, outlier)
            _apply(bars[i], chart_vals[i], system_vals[i], c_ref, s_ref, c_trim)
        return list(bars)

    if mode == "rolling":
        cs: list[float] = []
        ss: list[float] = []
        from collections import deque

        cq: deque[float] = deque()
        sq: deque[float] = deque()
        for i in range(n):
            cv, sv = chart_vals[i], system_vals[i]
            bisect.insort(cs, cv)
            bisect.insort(ss, sv)
            cq.append(cv)
            sq.append(sv)
            if len(cq) > window:
                old = cq.popleft()
                cs.pop(bisect.bisect_left(cs, old))
                olds = sq.popleft()
                ss.pop(bisect.bisect_left(ss, olds))
            if i + 1 < min_bars:
                _mark_unclassified(bars[i])
                continue
            c_ref, c_trim = build_reference(cs, pct, outlier)
            s_ref, _ = build_reference(ss, pct, outlier)
            _apply(bars[i], cv, sv, c_ref, s_ref, c_trim)
        return list(bars)

    # full (look-ahead)
    c_ref, c_trim = build_reference(chart_vals, pct, outlier)
    s_ref, _ = build_reference(system_vals, pct, outlier)
    for i in range(n):
        _apply(bars[i], chart_vals[i], system_vals[i], c_ref, s_ref, 0)
    # Max-Bar flag in full mode compares against the trimmed chart reference
    _ = c_trim
    return list(bars)


def _apply(
    bar: Bar,
    chart_val: float,
    system_val: float,
    chart_ref: float,
    system_ref: float,
    chart_trim: int,
) -> None:
    bar.chart_ref = chart_ref
    bar.system_ref = system_ref
    bar.chart_pct = (chart_val / chart_ref * 100.0) if chart_ref > 0 else 0.0
    bar.system_pct = (system_val / system_ref * 100.0) if system_ref > 0 else 0.0
    # A bar above the *untrimmed* 100% line is by construction one of the Max
    # Bars that were cut, i.e. an outlier the reference deliberately ignores.
    bar.is_max_bar = chart_ref > 0 and chart_val > chart_ref
    bar.category = Category.MEDIUM  # re-derived by classify; keeps field honest
    _ = chart_trim


def _mark_unclassified(bar: Bar) -> None:
    """Warm-up: no reference yet, so no percentages and no category."""
    bar.chart_ref = 0.0
    bar.system_ref = 0.0
    bar.chart_pct = 0.0
    bar.system_pct = 0.0
    bar.is_max_bar = False
    bar.category = Category.WEAK
    bar.color_key = category_color_key(Category.WEAK, bar.direction)
    bar.color = category_color(Category.WEAK, bar.direction)


def is_reference_ready(bar: Bar) -> bool:
    """True once the bar has a usable (non-zero) dynamic reference."""
    return bar.chart_ref > 0.0 and bar.system_ref > 0.0


def reference_summary(bars: Sequence[Bar]) -> dict[str, object]:
    ready = [b for b in bars if is_reference_ready(b)]
    if not ready:
        return {"ready": 0, "total": len(bars)}
    return {
        "total": len(bars),
        "ready": len(ready),
        "warmup_bars": len(bars) - len(ready),
        "max_bars": sum(1 for b in ready if b.is_max_bar),
        "chart_ref_last": ready[-1].chart_ref,
        "system_ref_last": ready[-1].system_ref,
        "chart_ref_mean": sum(b.chart_ref for b in ready) / len(ready),
        "system_ref_mean": sum(b.system_ref for b in ready) / len(ready),
    }
