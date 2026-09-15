"""Timing heatmap — 7x24 weekday/hour activity map.

Score per cell (README section 3):

    score = 0.50 * mean(system_pct)
          + 0.35 * mean(chart_pct)
          + 0.15 * mean(efficiency)

Bands are *percentile cuts of the cell distribution*, not absolute thresholds:

    bottom ``timing_dead_share`` (33%) -> dead  (yellow)
    top    ``timing_hot_share``  (25%) -> hot   (red)
    everything else                   -> mid   (brown)

Causality
---------
In ``timing_mode="expanding"`` each bar is tagged with the band its cell had
using only bars *before* it, recomputed every ``recalc_every`` bars.  Without
this, the "skip dead hours" filter would be using a seasonality map built from
the whole backtest — i.e. knowing in advance which hours turned out to be quiet.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any, Iterable, Sequence

from .mathx import mean, percentile, quantile_rank
from .models import COLORS, Bar, Settings, TimingCell

WEEKDAYS_FA = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
WEEKDAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday_of(ts_ms: int) -> int:
    return _dt.datetime.fromtimestamp(ts_ms / 1000.0, _dt.timezone.utc).weekday()


def hour_of(ts_ms: int) -> int:
    return _dt.datetime.fromtimestamp(ts_ms / 1000.0, _dt.timezone.utc).hour


def tag_bars(bars: Sequence[Bar]) -> None:
    """Stamp ``weekday`` / ``hour`` onto each bar (cheap, done once)."""
    for b in bars:
        b.weekday = weekday_of(b.ts)
        b.hour = hour_of(b.ts)


class _CellAcc:
    __slots__ = ("n", "sys_sum", "chart_sum", "eff_sum")

    def __init__(self) -> None:
        self.n = 0
        self.sys_sum = 0.0
        self.chart_sum = 0.0
        self.eff_sum = 0.0

    def add(self, b: Bar) -> None:
        self.n += 1
        self.sys_sum += b.system_pct
        self.chart_sum += b.chart_pct
        self.eff_sum += b.efficiency

    @property
    def mean_sys(self) -> float:
        return self.sys_sum / self.n if self.n else 0.0

    @property
    def mean_chart(self) -> float:
        return self.chart_sum / self.n if self.n else 0.0

    @property
    def mean_eff(self) -> float:
        return self.eff_sum / self.n if self.n else 0.0

    def raw_score(self, s: Settings) -> float:
        """Weighted sum of the *raw* component means.

        Kept for diagnostics only — it is not a usable cell score, because the
        components have incompatible units (see :func:`score_cells`).
        """
        if self.n == 0:
            return 0.0
        return (s.timing_weight_system * self.mean_sys
                + s.timing_weight_chart * self.mean_chart
                + s.timing_weight_efficiency * self.mean_eff)


def score_cells(acc: dict[tuple[int, int], "_CellAcc"],
                s: Settings) -> dict[tuple[int, int], float]:
    """Score every cell on a common [0, 1] scale so the documented weights hold.

    ``mean_system_pct`` and ``mean_chart_pct`` are percentages of the dynamic
    reference (typically 5..80) while ``mean_efficiency`` is a ratio in [-1, 1].
    Weighting those directly makes the 0.15 efficiency term numerically
    irrelevant — it can move the score by at most 0.15, while a 20-point
    difference in mean_system_pct moves it by 10.  Measured on a 45-day 15m
    sample the raw scores spanned 6.3..76.2, i.e. the "50/35/15" weighting was
    fiction: it was really "system_pct, plus rounding error".

    Each component is therefore converted to its quantile rank *across cells*
    first.  Ranks are scale-free and, unlike a z-score, immune to the one wild
    cell that a mean-based normalisation would let dominate.  The weighted sum of
    three ranks lands in [0, 1] and the weights mean what the spec says.
    """
    keys = list(acc)
    if not keys:
        return {}
    sys_vals = [acc[k].mean_sys for k in keys]
    chart_vals = [acc[k].mean_chart for k in keys]
    eff_vals = [acc[k].mean_eff for k in keys]
    r_sys = [quantile_rank(sys_vals, v) for v in sys_vals]
    r_chart = [quantile_rank(chart_vals, v) for v in chart_vals]
    r_eff = [quantile_rank(eff_vals, v) for v in eff_vals]
    return {
        k: (s.timing_weight_system * r_sys[j]
            + s.timing_weight_chart * r_chart[j]
            + s.timing_weight_efficiency * r_eff[j])
        for j, k in enumerate(keys)
    }


def _band_cutoffs(scores: Sequence[float], s: Settings) -> tuple[float, float]:
    """(dead_below, hot_above) from the distribution of cell scores."""
    if not scores:
        return (0.0, 0.0)
    dead_p = s.timing_dead_share * 100.0
    hot_p = (1.0 - s.timing_hot_share) * 100.0
    return (percentile(scores, dead_p), percentile(scores, hot_p))


def _band_of(score: float, dead_cut: float, hot_cut: float) -> str:
    if score <= dead_cut:
        return "dead"
    if score >= hot_cut:
        return "hot"
    return "mid"


def build_cells(bars: Sequence[Bar], s: Settings | None = None) -> dict[str, TimingCell]:
    """Whole-sample heatmap (the dashboard view)."""
    s = s or Settings()
    tag_bars(bars)
    acc: dict[tuple[int, int], _CellAcc] = defaultdict(_CellAcc)
    for b in bars:
        acc[(b.weekday, b.hour)].add(b)

    scored = score_cells(acc, s)
    cells: dict[str, TimingCell] = {}
    for (wd, hr), a in acc.items():
        c = TimingCell(
            weekday=wd,
            hour=hr,
            bars=a.n,
            mean_system_pct=a.mean_sys,
            mean_chart_pct=a.mean_chart,
            mean_efficiency=a.mean_eff,
        )
        c.score = scored[(wd, hr)]
        c.raw_score = a.raw_score(s)
        cells[c.key] = c

    scores = [c.score for c in cells.values()]
    dead_cut, hot_cut = _band_cutoffs(scores, s)
    for c in cells.values():
        c.band = _band_of(c.score, dead_cut, hot_cut)
        c.color = COLORS[f"timing_{ 'mid' if c.band == 'mid' else c.band }"]
    return cells


def annotate(
    bars: Sequence[Bar],
    s: Settings | None = None,
    *,
    recalc_every: int = 96,
) -> dict[str, Any]:
    """Tag every bar with its cell score and band.  Returns the final heatmap.

    In ``expanding`` mode the map is rebuilt from history every ``recalc_every``
    bars; between rebuilds a bar inherits the last computed band for its cell.
    ``recalc_every`` trades a little precision for O(n) behaviour — 96 bars on a
    15m timeframe is one day, which is far slower than any real seasonality
    drift.
    """
    s = s or Settings()
    tag_bars(bars)
    n = len(bars)
    if n == 0:
        return {"cells": {}, "mode": s.timing_mode, "dead_cut": 0.0, "hot_cut": 0.0}

    if s.timing_mode == "full":
        cells = build_cells(bars, s)
        for b in bars:
            c = cells.get(f"{b.weekday}-{b.hour}")
            b.timing_score = c.score if c else 0.0
            b.timing_band = c.band if c else "mid"
        scores = [c.score for c in cells.values()]
        dc, hc = _band_cutoffs(scores, s)
        return {"cells": cells, "mode": "full", "dead_cut": dc, "hot_cut": hc}

    # ---- expanding / causal ----
    acc: dict[tuple[int, int], _CellAcc] = defaultdict(_CellAcc)
    band_by_cell: dict[tuple[int, int], str] = {}
    score_by_cell: dict[tuple[int, int], float] = {}
    dead_cut = hot_cut = 0.0

    for i, b in enumerate(bars):
        key = (b.weekday, b.hour)
        ready = i >= s.timing_min_bars and band_by_cell
        b.timing_score = score_by_cell.get(key, 0.0)
        b.timing_band = band_by_cell.get(key, "mid") if ready else "mid"

        # update history *after* tagging the bar, so bar i never sees itself
        acc[key].add(b)
        if (i + 1) % recalc_every == 0 or i == n - 1:
            # Re-scored across all accumulated cells, so the quantile ranks (and
            # therefore the score scale) stay comparable as history grows.
            score_by_cell = score_cells(acc, s)
            scores = list(score_by_cell.values())
            dead_cut, hot_cut = _band_cutoffs(scores, s)
            band_by_cell = {
                k: _band_of(v, dead_cut, hot_cut) for k, v in score_by_cell.items()
            }

    cells = {
        f"{k[0]}-{k[1]}": TimingCell(
            weekday=k[0],
            hour=k[1],
            bars=acc[k].n,
            score=score_by_cell.get(k, 0.0),
            mean_system_pct=acc[k].mean_sys,
            mean_chart_pct=acc[k].mean_chart,
            mean_efficiency=acc[k].mean_eff,
            raw_score=acc[k].raw_score(s),
            band=band_by_cell.get(k, "mid"),
            color=COLORS[f"timing_{band_by_cell.get(k, 'mid')}"],
        )
        for k in acc
    }
    return {"cells": cells, "mode": "expanding", "dead_cut": dead_cut, "hot_cut": hot_cut}


def hour_scores(cells: Iterable[TimingCell]) -> list[tuple[int, float]]:
    """Mean cell score per hour-of-day, collapsed across weekdays."""
    by_hour: dict[int, list[float]] = defaultdict(list)
    for c in cells:
        by_hour[c.hour].append(c.score)
    return sorted((h, mean(v)) for h, v in by_hour.items())


def dead_cells(cells: Iterable[TimingCell]) -> list[str]:
    return sorted(c.key for c in cells if c.band == "dead")


def hot_cells(cells: Iterable[TimingCell]) -> list[str]:
    return sorted(c.key for c in cells if c.band == "hot")


def band_share(bars: Sequence[Bar]) -> dict[str, float]:
    n = len(bars)
    if n == 0:
        return {"dead": 0.0, "mid": 0.0, "hot": 0.0}
    out = {"dead": 0, "mid": 0, "hot": 0}
    for b in bars:
        out[b.timing_band] = out.get(b.timing_band, 0) + 1
    return {k: v / n for k, v in out.items()}


def cells_to_dicts(cells: Iterable[TimingCell]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in sorted(cells, key=lambda c: (c.weekday, c.hour))]
