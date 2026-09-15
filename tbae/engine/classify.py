"""Classification decision tree + colouring.

First match wins, coverage is complete (rule 5 is the catch-all).  The order is
the specification and is asserted by ``tests/test_engine.py``:

    1 weak       chart_pct <  weak  AND  system_pct <  weak        grey
    2 pressure   system_pct >= press AND  chart_pct <  weak        purple
    3 energetic  chart_pct >= big   AND  system_pct >= big         navy
    4 strong     chart_pct >= big   AND  system_pct <  big         blue
    5 medium     otherwise                                         green/orange

Technical note carried over from the README: because ``S >= chart_abs`` always
holds, rule 4 ("strong") is *large useful displacement with only moderate total
mobility* — a move that travelled cleanly.  Rule 2 ("pressure") is its opposite:
enormous mobility, no displacement — a fight with no territory, which is the
classic accumulation/distribution footprint and the raw material for the
reversal side of the strategy layer.

``explain`` exists so that a "why did this bar get this colour?" question has a
machine-readable answer instead of a shrug.  The signal-diagnostics module reuses
it to explain *why so few bars qualify*.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from .models import Bar, Category, Settings, category_color, category_color_key
from .reference import is_reference_ready


def classify(bar: Bar, s: Settings | None = None) -> Category:
    """Return the category for one bar.  Pure function of its percentages."""
    s = s or Settings()
    cp, sp = bar.chart_pct, bar.system_pct
    weak, big, press = s.weak_threshold, s.big_threshold, s.pressure_system_threshold

    if cp < weak and sp < weak:
        return Category.WEAK
    if sp >= press and cp < weak:
        return Category.PRESSURE
    if cp >= big and sp >= big:
        return Category.ENERGETIC
    if cp >= big and sp < big:
        return Category.STRONG
    return Category.MEDIUM


def explain(bar: Bar, s: Settings | None = None) -> dict[str, Any]:
    """Rule-by-rule trace: which predicate fired and with which numbers."""
    s = s or Settings()
    cp, sp = bar.chart_pct, bar.system_pct
    weak, big, press = s.weak_threshold, s.big_threshold, s.pressure_system_threshold
    checks = [
        {
            "rule": 1,
            "category": Category.WEAK.value,
            "expr": f"chart_pct({cp:.1f}) < {weak} AND system_pct({sp:.1f}) < {weak}",
            "passed": cp < weak and sp < weak,
        },
        {
            "rule": 2,
            "category": Category.PRESSURE.value,
            "expr": f"system_pct({sp:.1f}) >= {press} AND chart_pct({cp:.1f}) < {weak}",
            "passed": sp >= press and cp < weak,
        },
        {
            "rule": 3,
            "category": Category.ENERGETIC.value,
            "expr": f"chart_pct({cp:.1f}) >= {big} AND system_pct({sp:.1f}) >= {big}",
            "passed": cp >= big and sp >= big,
        },
        {
            "rule": 4,
            "category": Category.STRONG.value,
            "expr": f"chart_pct({cp:.1f}) >= {big} AND system_pct({sp:.1f}) < {big}",
            "passed": cp >= big and sp < big,
        },
        {
            "rule": 5,
            "category": Category.MEDIUM.value,
            "expr": "otherwise",
            "passed": True,
        },
    ]
    winner = next(c for c in checks if c["passed"])
    return {
        "ts": bar.ts,
        "chart_pct": cp,
        "system_pct": sp,
        "efficiency": bar.efficiency,
        "reference_ready": is_reference_ready(bar),
        "category": classify(bar, s).value,
        "winning_rule": winner["rule"],
        "checks": checks,
    }


def paint(bar: Bar, cat: Category) -> Bar:
    bar.category = cat
    bar.color_key = category_color_key(cat, bar.direction)
    bar.color = category_color(cat, bar.direction)
    return bar


def annotate(bars: Sequence[Bar], s: Settings | None = None) -> list[Bar]:
    """Classify + colour every bar in place.

    Bars still in reference warm-up are left grey/WEAK and flagged by
    ``is_reference_ready() == False``; the strategy layer refuses to trade them.
    """
    s = s or Settings()
    for b in bars:
        paint(b, classify(b, s))
    return list(bars)


def category_counts(bars: Sequence[Bar]) -> dict[str, int]:
    c = Counter(b.category.value for b in bars)
    return {k.value: c.get(k.value, 0) for k in Category}


def category_shares(bars: Sequence[Bar]) -> dict[str, float]:
    n = len(bars)
    if n == 0:
        return {k.value: 0.0 for k in Category}
    counts = category_counts(bars)
    return {k: v / n for k, v in counts.items()}


def directional_split(bars: Sequence[Bar]) -> dict[str, dict[str, int]]:
    """Per category, how many bars closed up vs down.

    Useful sanity check: if ``strong`` is 50/50 up/down, the category carries no
    directional information and trading it as a trend signal is noise.
    """
    out: dict[str, dict[str, int]] = {
        k.value: {"up": 0, "down": 0, "flat": 0} for k in Category
    }
    for b in bars:
        d = b.direction
        slot = "up" if d > 0 else ("down" if d < 0 else "flat")
        out[b.category.value][slot] += 1
    return out


def transition_matrix(bars: Sequence[Bar]) -> dict[str, dict[str, int]]:
    """P(next category | current category) as raw counts.

    The exit engine reads this to know whether a ``strong -> pressure`` flip is
    genuinely unusual (a real reversal event) or just the common next state
    (in which case acting on it costs money).
    """
    cats = [k.value for k in Category]
    m: dict[str, dict[str, int]] = {a: {b: 0 for b in cats} for a in cats}
    for i in range(1, len(bars)):
        m[bars[i - 1].category.value][bars[i].category.value] += 1
    return m


def transition_probabilities(bars: Sequence[Bar]) -> dict[str, dict[str, float]]:
    m = transition_matrix(bars)
    out: dict[str, dict[str, float]] = {}
    for a, row in m.items():
        tot = sum(row.values())
        out[a] = {b: (v / tot if tot else 0.0) for b, v in row.items()}
    return out


def base_rate_of(bars: Sequence[Bar], cat: Category | str) -> float:
    """Fraction of bars in ``cat`` — the ceiling on how many signals can exist.

    This single number is the honest answer to "why does the strategy trade so
    rarely": a rule that requires the top few percent of bars *cannot* fire
    often, no matter how the rest of the stack is tuned.
    """
    if not bars:
        return 0.0
    cat = Category(cat)
    return sum(1 for b in bars if b.category is cat) / len(bars)
