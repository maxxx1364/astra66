"""FastAPI application: JSON API + static dashboard.

Run with::

    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

Design rules
------------
* The engine does all the work.  Handlers only parse query parameters, call
  ``pipeline.run`` / ``signals.generate`` / ``backtest.run_backtest`` and
  serialise.  No maths lives here, so the CLI and the API can never disagree.
* Results are cached on ``(source, settings)`` because a full 45-day pipeline run
  costs ~0.6 s and the dashboard re-requests on every slider move.
* The backtest endpoint refuses a look-ahead configuration (``reference_mode=full``)
  with HTTP 422 unless ``allow_lookahead`` is explicitly passed — the same guard
  the engine raises, surfaced as an API error rather than a silent bad number.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from engine import backtest as BT
from engine import classify, feeds, pipeline, rules as rules_mod, signals as S
from engine import timing as timing_mod
from engine.exits import ExitConfig, exit_config_presets
from engine.models import (CATEGORY_RULES, Category, MinuteBar, Settings,
                           category_color_key, category_label)
from engine.path import average_curve, curve_to_dicts
from engine.risk import RiskConfig
from engine.resample import periods_per_year

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT, "static")

app = FastAPI(
    title="TBAE — Trading Backtest & Analytics Engine",
    version="0.2.0",
    description=(
        "Custom computational engine: 1-minute data to any timeframe, system bars "
        "(non-neutralised mobility), dynamic 100% reference, five-way "
        "classification, timing heatmap, confirmation-filter signal stack, risk "
        "management with staged exits, and an event-driven backtester with "
        "minute-level exit resolution."
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
_CACHE: dict[str, Any] = {}
_CACHE_MAX = 6


def _cache_key(**kw: Any) -> str:
    raw = json.dumps(kw, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _put(key: str, value: Any) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[key] = value


def _pipeline(
    tf: int = 15, days: int = 45, seed: int = 20260913, csv_path: str | None = None,
    reference_mode: str = "expanding", timing_mode: str = "expanding",
    reference_window: int = 0,
    reference_percentile: float = 98.0, outlier_share: float = 0.02,
    weak_threshold: float = 20.0, big_threshold: float = 55.0,
    pressure_threshold: float = 80.0, dead_share: float = 0.33,
    hot_share: float = 0.25, reference_min_bars: int = 200,
    limit_minutes: int = 0, cohort: bool = True,
) -> Any:
    """Build (or fetch from cache) a :class:`PipelineResult`."""
    key = _cache_key(tf=tf, days=days, seed=seed, csv_path=csv_path,
                     reference_mode=reference_mode, timing_mode=timing_mode,
                     reference_window=reference_window,
                     reference_percentile=reference_percentile,
                     outlier_share=outlier_share, weak_threshold=weak_threshold,
                     big_threshold=big_threshold,
                     pressure_threshold=pressure_threshold,
                     dead_share=dead_share, hot_share=hot_share,
                     reference_min_bars=reference_min_bars,
                     limit_minutes=limit_minutes, cohort=cohort)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        settings = Settings(
            reference_percentile=reference_percentile,
            reference_max_outlier_share=outlier_share,
            weak_threshold=weak_threshold, big_threshold=big_threshold,
            pressure_system_threshold=pressure_threshold,
            timing_dead_share=dead_share, timing_hot_share=hot_share,
            reference_mode=reference_mode, timing_mode=timing_mode,
            reference_window=reference_window,
            reference_min_bars=reference_min_bars,
        ).validate()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    t0 = time.perf_counter()
    try:
        if csv_path:
            minutes = feeds.CsvFeed(csv_path).load()
        elif limit_minutes:
            minutes = feeds.BinanceRestFeed().load(limit_minutes=limit_minutes)
        else:
            minutes = feeds.SyntheticFeed(
                feeds.SyntheticConfig(days=days, seed=seed)).load()
        res = pipeline.run(minutes, settings=settings, tf=tf,
                           with_cohort_curves=cohort)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:                                   # pragma: no cover
        raise HTTPException(status_code=500, detail=f"pipeline failed: {e}") from e
    res.manifest["cache_key"] = key
    res.manifest["build_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    _put(key, res)
    return res


def _curves(res: Any) -> dict[str, Any]:
    return res.stats.get("cohort_curves", {}) or {}


def _signal_cfg(
    min_score: float = 0.45, cooldown: int = 2,
    entry_timing: str = "pullback_limit",
) -> S.SignalConfig:
    try:
        return S.SignalConfig(min_edge_score=min_score, cooldown_bars=cooldown,
                              entry_timing=entry_timing).validate()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index() -> Any:
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"detail": "dashboard not built; use /docs or /api/*"},
                        status_code=200)


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def api_meta() -> dict[str, Any]:
    payload = rules_mod.load()
    return {
        "engine_version": "0.2.0",
        "timeframes": [1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440],
        "categories": [
            {"id": c.value, "label_fa": category_label(c, "fa"),
             "label_en": category_label(c, "en"), "rule": CATEGORY_RULES[c],
             "colors": {d: category_color_key(c, d) for d in (1, -1)}}
            for c in Category
        ],
        "colors": rules_mod.COLORS,
        "commands": rules_mod.command_registry(),
        "commands_by_group": rules_mod.commands_by_group(),
        "rules": payload["rules"],
        "keymap": payload["keymap"],
        "config_errors": payload["errors"],
        "defaults": Settings().to_dict(),
        "signal_defaults": {f: getattr(S.SignalConfig(), f) for f in S.SignalConfig.__slots__},
        "signal_config_hash": S.SignalConfig().validate().config_hash(),
        "exit_presets": sorted(exit_config_presets()),
        "periods_per_year_by_tf": {tf: periods_per_year(tf)
                                   for tf in (5, 15, 30, 60, 240, 1440)},
    }


@app.get("/api/commands")
def api_commands() -> dict[str, Any]:
    return {"commands": rules_mod.command_registry(),
            "by_group": rules_mod.commands_by_group(),
            "default_keymap": rules_mod.DEFAULT_KEYMAP,
            "reserved_keys": sorted(rules_mod.RESERVED_KEYS)}


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
@app.get("/api/data")
def api_data(
    tf: int = Query(15, ge=1, le=1440),
    days: int = Query(45, ge=1, le=365),
    seed: int = 20260913,
    limit: int = Query(500, ge=1, le=5000),
    weak_threshold: float = Query(20.0, ge=0, le=500),
    big_threshold: float = Query(55.0, ge=0, le=500),
    pressure_system_threshold: float = Query(80.0, ge=0, le=500),
    reference_percentile: float = Query(98.0, gt=0, le=100),
    reference_mode: str = Query("expanding", pattern="^(expanding|rolling|full)$"),
    reference_window: int = Query(0, ge=0, le=100000,
                                  description="bars of history for reference_mode=rolling; "
                                              "0 = all available"),
    timing_mode: str = Query("expanding", pattern="^(expanding|full)$"),
    hot_only: bool = False,
) -> dict[str, Any]:
    res = _pipeline(tf=tf, days=days, seed=seed,
                    reference_mode=reference_mode, timing_mode=timing_mode,
                    reference_window=reference_window,
                    reference_percentile=reference_percentile,
                    weak_threshold=weak_threshold, big_threshold=big_threshold,
                    pressure_threshold=pressure_system_threshold)
    bars = pipeline.filter_bars(res, hot_only=hot_only, limit=limit)
    return {
        "meta": res.manifest,
        "kpi": res.kpi,
        "stats": {k: v for k, v in res.stats.items() if k != "cohort_curves"},
        "completeness": res.completeness,
        "reference": res.reference_summary,
        "timing": {"cells": timing_mod.cells_to_dicts(res.cells.values()),
                   **res.timing_meta},
        "bars": [b.to_dict() for b in bars],
        "warmup_index": res.warmup_index,
    }


@app.get("/api/raw")
def api_raw(minutes: int = Query(1440, ge=1, le=20000), end: int | None = None,
            days: int = 45, seed: int = 20260913) -> dict[str, Any]:
    cfg = feeds.SyntheticConfig(days=days, seed=seed)
    bars = feeds.SyntheticFeed(cfg).load()
    if end is not None:
        bars = [b for b in bars if b.ts <= end]
    bars = bars[-minutes:]
    return {"count": len(bars),
            "minutes": [b.to_dict() for b in bars],
            "manifest": {"seed": seed, "days": days,
                         "end_ts": bars[-1].ts if bars else 0}}


@app.get("/api/table")
def api_table(
    tf: int = 15, days: int = 45, seed: int = 20260913,
    category: str | None = None, from_ts: int | None = None,
    to_ts: int | None = None, limit: int = Query(500, ge=1, le=5000),
    direction: int | None = Query(None, ge=-1, le=1),
    hot_only: bool = False,
) -> dict[str, Any]:
    res = _pipeline(tf=tf, days=days, seed=seed, cohort=False)
    cats = [category] if category else None
    if cats:
        try:
            cats = [Category(c).value for c in cats]
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    bars = pipeline.filter_bars(res, categories=cats, hot_only=hot_only,
                                from_ts=from_ts, to_ts=to_ts, limit=limit,
                                direction=direction)
    return {"count": len(bars), "bars": [b.to_dict() for b in bars],
            "manifest": res.manifest}


@app.get("/api/path")
def api_path(tf: int = 15, ts: int | None = None, weekday: int = 0, hour: int = 13,
             days: int = 45, seed: int = 20260913) -> dict[str, Any]:
    res = _pipeline(tf=tf, days=days, seed=seed)
    target = None
    if ts is not None:
        target = next((b for b in res.bars if b.ts == ts), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"no bar at ts={ts}")
    else:
        target = next((b for b in res.bars
                       if b.weekday == weekday and b.hour == hour), None)
        if target is None:
            raise HTTPException(status_code=404,
                                detail=f"no bar for weekday={weekday} hour={hour}")
    from engine.path import growth_curve
    cohort = average_curve([b for b in res.bars
                            if b.weekday == target.weekday and b.hour == target.hour],
                           target.weekday, target.hour)
    return {
        "bar": target.to_dict(),
        "curve": curve_to_dicts(growth_curve(target)),
        "cohort_curve": curve_to_dicts(cohort),
        "cohort_key": f"{target.weekday}-{target.hour}",
        "cohort_bars": sum(1 for b in res.bars
                           if b.weekday == target.weekday and b.hour == target.hour),
    }


@app.get("/api/explain")
def api_explain(tf: int = 15, ts: int | None = None, index: int | None = None,
                days: int = 45, seed: int = 20260913) -> dict[str, Any]:
    """Why did this bar get this category?  Rule-by-rule trace."""
    res = _pipeline(tf=tf, days=days, seed=seed, cohort=False)
    bar = None
    if ts is not None:
        bar = next((b for b in res.bars if b.ts == ts), None)
    elif index is not None and 0 <= index < len(res.bars):
        bar = res.bars[index]
    else:
        bar = res.bars[-1]
    if bar is None:
        raise HTTPException(status_code=404, detail="bar not found")
    from engine.systembar import describe
    return {"explain": classify.explain(bar, res.settings),
            "system_bar": describe(bar),
            "bar": bar.to_dict()}


# --------------------------------------------------------------------------- #
# strategy layer
# --------------------------------------------------------------------------- #
@app.get("/api/signals")
def api_signals(
    tf: int = 15, days: int = 45, seed: int = 20260913,
    min_score: float = Query(0.45, ge=0, le=1), cooldown: int = Query(2, ge=0),
    entry_timing: str = Query("pullback_limit", pattern="^(immediate|pullback_limit)$"),
    limit: int = Query(200, ge=1, le=2000), include_rejected: bool = False,
    sensitivity: bool = False,
) -> dict[str, Any]:
    res = _pipeline(tf=tf, days=days, seed=seed)
    ss = S.generate(res.bars, res.indicators, res.settings,
                    _signal_cfg(min_score, cooldown, entry_timing),
                    warmup_index=res.warmup_index, cohort_curves=_curves(res))
    diag = S.diagnose(res.bars, ss, res.settings, warmup_index=res.warmup_index)
    if sensitivity:
        diag["threshold_sensitivity"] = S.threshold_sensitivity(
            res.bars, res.settings, warmup_index=res.warmup_index)
    pool = ss.candidates if include_rejected else ss.signals
    return {
        "manifest": res.manifest,
        "diagnostic": diag,
        "count": len(pool),
        "signals": [s.to_dict() for s in pool[-limit:]],
    }


@app.get("/api/backtest")
def api_backtest(
    tf: int = 15, days: int = 45, seed: int = 20260913,
    min_score: float = Query(0.45, ge=0, le=1), cooldown: int = Query(2, ge=0),
    entry_timing: str = Query("pullback_limit", pattern="^(immediate|pullback_limit)$"),
    stop_mode: str = "sigma_structure_max", stop_sigma: float = Query(2.2, gt=0),
    equity: float = Query(100_000.0, gt=0), risk_pct: float = Query(0.75, gt=0, le=10),
    sizing: str = "risk_and_vol", commission_bps: float = Query(4.0, ge=0),
    maker_bps: float = Query(1.0, ge=0), slippage_bps: float = Query(2.0, ge=0),
    entry_mode: str = Query("signal", pattern="^(signal|random|every_bar)$"),
    use_intra_bar_path: bool = True, adverse_first: bool = True,
    allow_lookahead: bool = False, reference_mode: str = "expanding",
    timing_mode: str = "expanding", include_trades: bool = False,
    n_trials: int = Query(1, ge=1),
) -> dict[str, Any]:
    if reference_mode == "full" and not allow_lookahead:
        raise HTTPException(
            status_code=422,
            detail=("reference_mode='full' is look-ahead: the dynamic 100% reference "
                    "would be built from the whole sample. Pass allow_lookahead=true "
                    "to override (recorded in the manifest)."))
    res = _pipeline(tf=tf, days=days, seed=seed, reference_mode=reference_mode,
                    timing_mode=timing_mode)
    rcfg = RiskConfig(initial_equity=equity, risk_per_trade_pct=risk_pct,
                      sizing_mode=sizing)
    rcfg.costs.commission_bps = commission_bps
    rcfg.costs.maker_bps = maker_bps
    rcfg.costs.slippage_bps = slippage_bps
    try:
        xcfg = ExitConfig(stop_mode=stop_mode, stop_sigma_mult=stop_sigma).validate()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    bcfg = BT.BacktestConfig(entry_mode=entry_mode,
                             use_intra_bar_path=use_intra_bar_path,
                             adverse_first=adverse_first,
                             allow_lookahead=allow_lookahead).validate()
    try:
        r = BT.run_backtest(res, signal_cfg=_signal_cfg(min_score, cooldown,
                                                        entry_timing),
                            risk_cfg=rcfg, exit_cfg=xcfg, bt_cfg=bcfg,
                            cohort_curves=_curves(res))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # re-score the metrics with the real number of trials if the caller knows it
    if n_trials > 1:
        from engine import metrics as metrics_mod
        r.metrics = metrics_mod.summarise(
            r, initial_equity=equity,
            periods_per_year=periods_per_year(res.settings.timeframe),
            timeframe=res.settings.timeframe, n_trials=n_trials)
        r.manifest["n_trials_declared"] = n_trials

    payload = r.to_dict(include_trades=include_trades)
    payload["signal_diagnostic"] = r.signal_diagnostic
    return payload


@app.get("/api/compare")
def api_compare(
    tf: int = 15, days: int = 45, seed: int = 20260913,
    min_score: float = 0.45, cooldown: int = 2,
    entry_timing: str = "pullback_limit", stop_sigma: float = 2.2,
    commission_bps: float = 4.0, maker_bps: float = 1.0, slippage_bps: float = 2.0,
) -> dict[str, Any]:
    """Strategy against its random-entry and every-bar controls."""
    from engine import metrics as metrics_mod
    res = _pipeline(tf=tf, days=days, seed=seed)
    scfg = _signal_cfg(min_score, cooldown, entry_timing)
    rcfg = RiskConfig()
    rcfg.costs.commission_bps = commission_bps
    rcfg.costs.maker_bps = maker_bps
    rcfg.costs.slippage_bps = slippage_bps
    xcfg = ExitConfig(stop_sigma_mult=stop_sigma)
    curves = _curves(res)
    kw = dict(signal_cfg=scfg, risk_cfg=rcfg, exit_cfg=xcfg, cohort_curves=curves)
    strat = BT.run_backtest(res, **kw)
    ctrl = BT.run_backtest(res, bt_cfg=BT.BacktestConfig(entry_mode="random",
                                                         random_seed=seed), **kw)
    every = BT.run_backtest(res, bt_cfg=BT.BacktestConfig(entry_mode="every_bar"), **kw)
    return {
        "comparison": metrics_mod.compare(strat, ctrl, every),
        "strategy": strat.to_dict(include_trades=False),
        "random_control": ctrl.to_dict(include_trades=False),
        "every_bar_control": every.to_dict(include_trades=False),
        "manifest": res.manifest,
    }


@app.get("/api/ablation")
def api_ablation(tf: int = 15, days: int = 45, seed: int = 20260913,
                 min_score: float = 0.45, cooldown: int = 2,
                 entry_timing: str = "pullback_limit") -> dict[str, Any]:
    """Per-filter marginal contribution (one backtest per filter, plus baseline)."""
    from engine import validation
    res = _pipeline(tf=tf, days=days, seed=seed)
    curves = _curves(res)
    flags = {"trend": "f_trend", "volatility": "f_volatility", "volume": "f_volume",
             "structure": "f_structure", "momentum": "f_momentum",
             "extension": "f_extension", "timing": "f_timing", "quality": "f_quality"}

    def run_one(name: str, disabled: bool) -> dict[str, Any]:
        kw: dict[str, Any] = {"min_edge_score": min_score, "cooldown_bars": cooldown,
                              "entry_timing": entry_timing}
        if disabled and name in flags:
            kw[flags[name]] = False
        r = BT.run_backtest(res, signal_cfg=S.SignalConfig(**kw), cohort_curves=curves)
        return {"n_trades": len(r.trades),
                "expectancy_r": r.metrics["trades"].get("expectancy_r", 0.0),
                "sharpe": r.metrics["risk_adjusted"]["sharpe"],
                "max_dd_pct": r.metrics["risk"]["max_drawdown_pct"],
                "return_pct": r.metrics["returns"]["total_return_pct"],
                "win_rate": r.metrics["trades"].get("win_rate", 0.0)}

    return {"ablation": validation.ablation(run_one, list(flags)),
            "manifest": res.manifest}


@app.get("/api/monte-carlo")
def api_monte_carlo(tf: int = 15, days: int = 45, seed: int = 20260913,
                    min_score: float = 0.45, cooldown: int = 2,
                    entry_timing: str = "pullback_limit", n_sims: int = 300,
                    n_boot: int = 1000) -> dict[str, Any]:
    from engine import validation
    res = _pipeline(tf=tf, days=days, seed=seed)
    r = BT.run_backtest(res, signal_cfg=_signal_cfg(min_score, cooldown, entry_timing),
                        cohort_curves=_curves(res))
    rs = [t.r_multiple for t in r.trades]
    from engine.mathx import stdev
    return {
        "monte_carlo_drawdown": validation.monte_carlo_drawdown(
            r.trades, n_sims=n_sims, seed=seed),
        "bootstrap_expectancy": validation.bootstrap_expectancy(
            r.trades, n_boot=n_boot, seed=seed),
        "minimum_trades_for_power": validation.minimum_detectable_trades(
            effect_r=0.10, sd_r=stdev(rs) if len(rs) > 2 else 1.0),
        "n_trades": len(r.trades),
        "manifest": r.manifest,
    }


# --------------------------------------------------------------------------- #
# rules / keymap
# --------------------------------------------------------------------------- #
@app.get("/api/rules")
def api_get_rules() -> dict[str, Any]:
    payload = rules_mod.load()
    return {"rules": payload["rules"], "source": payload["source"],
            "errors": payload["errors"], "allowed_fields": sorted(rules_mod.ALLOWED_FIELDS),
            "allowed_colors": sorted(rules_mod.COLORS)}


@app.post("/api/rules")
def api_add_rule(rule: dict[str, Any] = Body(...)) -> dict[str, Any]:
    payload = rules_mod.load()
    # collect the skips: saving below rewrites the user's file from this ruleset, so
    # a rule that failed to compile would otherwise vanish without a word
    dropped: list[str] = []
    rs = rules_mod.ruleset_from_payload(payload, errors=dropped)
    try:
        rs.add(rules_mod.ColorRule(
            id=str(rule.get("id") or f"rule_{int(time.time())}"),
            expr=str(rule.get("expr", "")),
            color_key=str(rule.get("color_key", "")),
            label_fa=str(rule.get("label_fa", "")),
            label_en=str(rule.get("label_en", "")),
            enabled=bool(rule.get("enabled", True)),
            priority=int(rule.get("priority", 100)),
        ))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    payload["rules"] = rs.to_dict()["rules"]
    rules_mod.save(payload)
    out: dict[str, Any] = {"ok": True, "rules": payload["rules"]}
    if dropped:
        out["dropped_rules"] = dropped
        out["warning"] = ("existing rules that failed to compile were removed from "
                          "the saved file: " + "; ".join(dropped))
    return out


@app.delete("/api/rules")
def api_delete_rule(rule_id: str = Query(...)) -> dict[str, Any]:
    payload = rules_mod.load()
    rs = rules_mod.ruleset_from_payload(payload)
    if not rs.remove(rule_id):
        raise HTTPException(status_code=404, detail=f"no rule with id {rule_id!r}")
    payload["rules"] = rs.to_dict()["rules"]
    rules_mod.save(payload)
    return {"ok": True, "rules": payload["rules"]}


@app.get("/api/keymap")
def api_get_keymap() -> dict[str, Any]:
    payload = rules_mod.load()
    return {"keymap": payload["keymap"], "defaults": rules_mod.DEFAULT_KEYMAP,
            "reserved": sorted(rules_mod.RESERVED_KEYS)}


@app.post("/api/keymap")
def api_set_keymap(km: dict[str, str] = Body(...)) -> dict[str, Any]:
    try:
        validated = rules_mod.validate_keymap(km)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    payload = rules_mod.load()
    payload["keymap"] = validated
    rules_mod.save(payload)
    return {"ok": True, "keymap": validated}


@app.delete("/api/keymap")
def api_delete_key(key: str = Query(...)) -> dict[str, Any]:
    payload = rules_mod.load()
    if key not in payload["keymap"]:
        raise HTTPException(status_code=404, detail=f"key {key!r} is not bound")
    payload["keymap"].pop(key)
    rules_mod.save(payload)
    return {"ok": True, "keymap": payload["keymap"]}


@app.post("/api/reset")
def api_reset() -> dict[str, Any]:
    return {"ok": True, **rules_mod.reset()}


@app.post("/api/upload")
async def api_upload(file: UploadFile) -> dict[str, Any]:
    """Upload a personal 1-minute CSV.  Validated before it is stored."""
    body = await file.read()
    if len(body) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large (max 64 MB)")
    name = os.path.basename(file.filename or "upload.csv")
    if not name.lower().endswith(".csv"):
        name += ".csv"
    dest_dir = os.path.join(ROOT, "data", "uploads")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    with open(dest, "wb") as fh:
        fh.write(body)
    try:
        minutes = feeds.CsvFeed(dest).load()
    except ValueError as e:
        os.remove(dest)
        raise HTTPException(status_code=422, detail=f"invalid CSV: {e}") from e
    if len(minutes) < 60:
        os.remove(dest)
        raise HTTPException(status_code=422,
                            detail=f"only {len(minutes)} minute bars parsed; need >= 60")
    return {"ok": True, "path": dest, "minutes": len(minutes),
            "first_ts": minutes[0].ts, "last_ts": minutes[-1].ts,
            "span_hours": (minutes[-1].ts - minutes[0].ts) / 3_600_000.0}


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {"ok": True, "engine_version": "0.2.0",
            "cache_entries": len(_CACHE),
            "static_dashboard": os.path.exists(os.path.join(STATIC_DIR, "index.html"))}


# static assets last, so /api/* is never shadowed
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
