"""The full chain: raw 1-minute data -> annotated bars -> statistics.

``run`` is the single entry point the README promises: one function produces
everything, and every consumer (CLI, FastAPI, backtester, tests) calls the same
one.  Nothing here knows about HTTP or the DOM.

Stage order is fixed and each stage is idempotent on its own inputs:

    1 resample       1m -> tf buckets (keeps the minute path)
    2 systembar      S / S_up / S_down / S_intra / efficiency
    3 volatility     TR / ATR / RV / Garman-Klass / blended sigma / vol regime
    4 reference      dynamic 100% (causal by default)
    5 classify       decision tree -> category + colour
    6 timing         7x24 heatmap bands (causal by default)
    7 indicators     trend / momentum / volume / structure frame

Stages 3 and 7 need the *previous* bar, so they must run after resampling but
before any consumer slices the series.  If you slice first and annotate second,
the first bar of the slice silently gets an ATR seeded from nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import classify, indicators as ind_mod, reference, resample, systembar, timing, volatility
from .feeds import SyntheticConfig, SyntheticFeed, load_feed
from .mathx import mean, median, percentile, safe_div, stdev
from .models import Bar, Category, MinuteBar, Settings
from .path import build_cohort_curves


@dataclass(slots=True)
class PipelineResult:
    settings: Settings
    minutes: list[MinuteBar] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    indicators: ind_mod.Indicators = field(default_factory=ind_mod.Indicators)
    cells: dict[str, Any] = field(default_factory=dict)
    timing_meta: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    kpi: dict[str, Any] = field(default_factory=dict)
    completeness: dict[str, Any] = field(default_factory=dict)
    reference_summary: dict[str, Any] = field(default_factory=dict)
    warmup_index: int = 0
    elapsed_ms: float = 0.0
    manifest: dict[str, Any] = field(default_factory=dict)

    # ---- convenience ----
    @property
    def tradable(self) -> list[Bar]:
        """Bars past warm-up with a valid reference — the only ones a strategy
        may act on.  Trading a warm-up bar is trading on a category the engine
        had no data to assign yet."""
        return self.bars[self.warmup_index:]

    def tradable_indices(self) -> range:
        return range(self.warmup_index, len(self.bars))

    def bars_dicts(self, limit: int | None = None, include_path: bool = False) -> list[dict[str, Any]]:
        src = self.bars if limit is None else self.bars[-limit:]
        return [b.to_dict(include_path) for b in src]

    def to_payload(self, limit: int = 500) -> dict[str, Any]:
        """JSON payload for the API/dashboard."""
        return {
            "meta": self.manifest,
            "kpi": self.kpi,
            "stats": self.stats,
            "completeness": self.completeness,
            "reference": self.reference_summary,
            "timing": {
                "cells": timing.cells_to_dicts(self.cells.values()),
                **{k: v for k, v in self.timing_meta.items() if k != "cells"},
            },
            "bars": self.bars_dicts(limit),
            "warmup_index": self.warmup_index,
        }


def run(
    minutes: Sequence[MinuteBar] | None = None,
    *,
    feed: str | None = None,
    settings: Settings | None = None,
    indicator_config: ind_mod.IndicatorConfig | None = None,
    tf: int | None = None,
    days: int | None = None,
    seed: int | None = None,
    drop_incomplete: bool = True,
    with_cohort_curves: bool = False,
) -> PipelineResult:
    """Execute the whole chain and return a :class:`PipelineResult`."""
    t0 = time.perf_counter()
    s = (settings or Settings()).validate()
    if tf is not None:
        s = s.replace(timeframe=int(tf))
    icfg = indicator_config or ind_mod.IndicatorConfig()

    # ---- 0. source data ----
    if minutes is None:
        if feed:
            minutes = load_feed(feed)
        else:
            scfg = SyntheticConfig()
            if days is not None:
                scfg.days = int(days)
            if seed is not None:
                scfg.seed = int(seed)
            minutes = SyntheticFeed(scfg).load()
    minutes = list(minutes)
    if not minutes:
        raise ValueError("no input data: feed returned zero minute bars")

    # ---- 1. resample ----
    bars = resample.resample(minutes, s.timeframe, drop_incomplete=drop_incomplete, settings=s)
    if len(bars) < 5:
        raise ValueError(
            f"only {len(bars)} bars produced from {len(minutes)} minutes at tf={s.timeframe}"
        )

    # ---- 2..7 ----
    systembar.annotate(bars)
    volatility.annotate_volatility(bars, s)
    reference.annotate_reference(bars, s)
    classify.annotate(bars, s)
    tmeta = timing.annotate(bars, s)
    cells = tmeta.pop("cells", {})
    ind = ind_mod.compute(bars, s, icfg)

    warmup = max(ind_mod.warmup_bars(icfg), s.reference_min_bars)
    warmup = min(warmup, max(0, len(bars) - 2))
    # also skip bars whose reference is not ready yet
    while warmup < len(bars) and not reference.is_reference_ready(bars[warmup]):
        warmup += 1

    cohort_curves = build_cohort_curves(bars) if with_cohort_curves else {}

    res = PipelineResult(
        settings=s,
        minutes=minutes,
        bars=bars,
        indicators=ind,
        cells=cells,
        timing_meta=tmeta,
        completeness=resample.completeness_report(bars, s.timeframe),
        reference_summary=reference.reference_summary(bars),
        warmup_index=warmup,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )
    res.stats = compute_stats(res)
    res.kpi = compute_kpi(res)
    res.manifest = {
        "engine_version": "0.2.0",
        "timeframe": s.timeframe,
        "bars": len(bars),
        "minutes": len(minutes),
        "first_ts": bars[0].ts,
        "last_ts": bars[-1].ts,
        "warmup_index": warmup,
        "reference_mode": s.reference_mode,
        "timing_mode": s.timing_mode,
        "settings": s.to_dict(),
        "cohort_curves": len(cohort_curves),
        "elapsed_ms": round(res.elapsed_ms, 2),
    }
    if cohort_curves:
        res.manifest["cohort_curve_keys"] = sorted(cohort_curves)
        res.stats["cohort_curves"] = cohort_curves
    return res


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def compute_stats(res: PipelineResult) -> dict[str, Any]:
    bars = res.bars
    trad = bars[res.warmup_index:]
    counts = classify.category_counts(trad)
    shares = classify.category_shares(trad)
    effs = [b.efficiency for b in trad]
    charts = [b.chart_pct for b in trad]
    systems = [b.system_pct for b in trad]
    sigmas = [b.sigma for b in trad]
    return {
        "bars_total": len(bars),
        "bars_tradable": len(trad),
        "category_counts": counts,
        "category_shares": {k: round(v, 6) for k, v in shares.items()},
        "directional_split": classify.directional_split(trad),
        "transition_probabilities": classify.transition_probabilities(trad),
        "max_bars": sum(1 for b in trad if b.is_max_bar),
        "efficiency": {
            "mean": mean(effs), "median": median(effs),
            "p10": percentile(effs, 10), "p90": percentile(effs, 90),
            "stdev": stdev(effs),
        },
        "chart_pct": {
            "mean": mean(charts), "median": median(charts),
            "p50": percentile(charts, 50), "p90": percentile(charts, 90),
            "p98": percentile(charts, 98), "p99": percentile(charts, 99),
            "max": max(charts) if charts else 0.0,
        },
        "system_pct": {
            "mean": mean(systems), "median": median(systems),
            "p90": percentile(systems, 90), "p98": percentile(systems, 98),
            "max": max(systems) if systems else 0.0,
        },
        "volatility": volatility.vol_summary(trad),
        "sigma_dist": {
            "p10": percentile(sigmas, 10), "p50": percentile(sigmas, 50),
            "p90": percentile(sigmas, 90), "p99": percentile(sigmas, 99),
        },
        "timing_band_share": timing.band_share(trad),
        "hot_cells": timing.hot_cells(res.cells.values()),
        "dead_cells": timing.dead_cells(res.cells.values()),
        "hour_scores": timing.hour_scores(res.cells.values()),
        "trend_state_share": _trend_share(res),
    }


def _trend_share(res: PipelineResult) -> dict[str, float]:
    ts = res.indicators.trend_state[res.warmup_index:]
    n = len(ts)
    if n == 0:
        return {"up": 0.0, "down": 0.0, "range": 0.0}
    return {
        "up": ts.count(1) / n,
        "down": ts.count(-1) / n,
        "range": ts.count(0) / n,
    }


def compute_kpi(res: PipelineResult) -> dict[str, Any]:
    """The handful of numbers the dashboard shows above the fold."""
    trad = res.tradable
    if not trad:
        return {}
    n = len(trad)
    counts = classify.category_counts(trad)
    strong_share = safe_div(counts["strong"], n, 0.0)
    pressure_share = safe_div(counts["pressure"], n, 0.0)
    up = sum(1 for b in trad if b.direction > 0)
    dn = sum(1 for b in trad if b.direction < 0)
    rets = [
        safe_div(trad[i].close - trad[i - 1].close, trad[i - 1].close, 0.0)
        for i in range(1, n)
    ]
    ann = resample.periods_per_year(res.settings.timeframe)
    mu, sd = mean(rets), stdev(rets)
    return {
        "bars": n,
        "timeframe": res.settings.timeframe,
        "last_close": trad[-1].close,
        "net_change_pct": safe_div(trad[-1].close - trad[0].open, trad[0].open, 0.0) * 100.0,
        "up_bars": up,
        "down_bars": dn,
        "up_share": safe_div(up, n, 0.0),
        "strong_share": strong_share,
        "pressure_share": pressure_share,
        "energetic_share": safe_div(counts["energetic"], n, 0.0),
        "weak_share": safe_div(counts["weak"], n, 0.0),
        "mean_efficiency": mean([b.efficiency for b in trad]),
        "max_bar_count": sum(1 for b in trad if b.is_max_bar),
        "atr_pct_mean": mean([b.atr_pct for b in trad]),
        "annualised_vol_pct": volatility.annualised_vol(trad, ann) * 100.0,
        "sharpe_bar": safe_div(mu, sd, 0.0) * (ann ** 0.5),
        "reference_mode": res.settings.reference_mode,
        "timing_mode": res.settings.timing_mode,
        "warmup_bars": res.warmup_index,
        "coverage": res.completeness.get("coverage", 1.0),
    }


def filter_bars(
    res: PipelineResult,
    *,
    categories: Sequence[Category | str] | None = None,
    hot_only: bool = False,
    from_ts: int | None = None,
    to_ts: int | None = None,
    limit: int | None = None,
    direction: int | None = None,
) -> list[Bar]:
    """The `/api/table` filter, kept in the engine so CLI and HTTP agree."""
    cats = {Category(c) for c in categories} if categories else None
    out: list[Bar] = []
    for i in res.tradable_indices():
        b = res.bars[i]
        if cats is not None and b.category not in cats:
            continue
        if hot_only and b.timing_band != "hot":
            continue
        if from_ts is not None and b.ts < from_ts:
            continue
        if to_ts is not None and b.ts > to_ts:
            continue
        if direction is not None and b.direction != direction:
            continue
        out.append(b)
    if limit is not None:
        out = out[-limit:] if limit > 0 else out
    return out
