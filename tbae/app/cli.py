"""Command-line interface.

The default action reproduces the invocation documented in the README::

    python3 -m app.cli --tf 15 --days 45 --out bars.csv

Sub-commands cover the strategy layer::

    python3 -m app.cli signals  --tf 15 --days 45          # funnel + scarcity audit
    python3 -m app.cli backtest --tf 15 --days 45 --json report.json
    python3 -m app.cli compare  --tf 15 --days 45          # strategy vs its controls
    python3 -m app.cli sweep    --tf 15 --days 45          # parameter plateau + PBO

Every command prints a run manifest (config hash, data window, look-ahead modes)
so a number in a report can always be traced to the exact configuration that
produced it.  That is not ceremony: without it, two people quoting different
Sharpe ratios from "the same" strategy cannot tell why they differ.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import sys
from typing import Any, Sequence

# allow running as ``python3 -m app.cli`` from inside tbae/, and as a script
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine import backtest as BT                      # type: ignore
    from engine import feeds, metrics, pipeline, signals as S, validation  # type: ignore
    from engine.exits import ExitConfig                    # type: ignore
    from engine.risk import RiskConfig                     # type: ignore
    from engine.models import Settings                     # type: ignore
else:
    from engine import backtest as BT
    from engine import feeds, metrics, pipeline, signals as S, validation
    from engine.exits import ExitConfig
    from engine.risk import RiskConfig
    from engine.models import Settings


BAR_COLUMNS = (
    "ts", "datetime", "tf", "open", "high", "low", "close", "volume", "direction",
    "n_minutes", "s_total", "s_up", "s_down", "s_intra", "chart_abs", "chart_range",
    "efficiency", "leg_skew", "true_range", "atr", "atr_pct", "rv", "gk", "sigma",
    "sigma_atr", "vol_regime", "chart_ref", "system_ref", "chart_pct", "system_pct",
    "is_max_bar", "category", "color_key", "color", "vwap", "session_open",
    "weekday", "hour", "timing_score", "timing_band",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _build(args: argparse.Namespace, *, cohort: bool = False) -> Any:
    settings = Settings(
        reference_percentile=args.reference_percentile,
        reference_max_outlier_share=args.outlier_share,
        weak_threshold=args.weak_threshold,
        big_threshold=args.big_threshold,
        pressure_system_threshold=args.pressure_threshold,
        timing_dead_share=args.dead_share,
        timing_hot_share=args.hot_share,
        reference_mode=args.reference_mode,
        timing_mode=args.timing_mode,
        reference_min_bars=args.reference_min_bars,
        keep_minute_path=True,
    ).validate()

    minutes = None
    if args.csv:
        minutes = feeds.CsvFeed(args.csv).load()
        src = f"csv:{args.csv}"
    elif args.feed and not args.feed.startswith("synthetic"):
        minutes = feeds.load_feed(args.feed)
        src = args.feed
    else:
        opts: dict[str, Any] = {}
        if args.feed and args.feed.startswith("synthetic:"):
            opts = feeds._parse_kv(args.feed.split(":", 1)[1])
        cfg = feeds.SyntheticConfig(
            days=args.days, seed=args.seed,
            **{k: feeds._coerce({k: v}, feeds.SyntheticConfig)[k]
               for k, v in opts.items()},
        )
        minutes = feeds.SyntheticFeed(cfg).load()
        src = f"synthetic(days={args.days}, seed={args.seed})"

    res = pipeline.run(minutes, settings=settings, tf=args.tf,
                       with_cohort_curves=cohort)
    res.manifest["source"] = src
    return res


def _print_manifest(res: Any) -> None:
    m = res.manifest
    print("─" * 74)
    print(f"run manifest   engine {m['engine_version']}   tf={m['timeframe']}m"
          f"   bars={m['bars']}   minutes={m['minutes']}")
    print(f"  window       {_ts(m['first_ts'])} -> {_ts(m['last_ts'])}"
          f"   ({m['bars'] / (1440 / m['timeframe']):.1f} days)")
    print(f"  source       {m.get('source', '-')}")
    print(f"  causality    reference_mode={m['reference_mode']}"
          f"   timing_mode={m['timing_mode']}   warmup_bars={m['warmup_index']}")
    print(f"  coverage     {m.get('coverage', 1.0) * 100:.2f}% of expected minutes"
          f"   pipeline {m['elapsed_ms']:.0f} ms")
    print("─" * 74)


def _ts(ms: int) -> str:
    return _dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M")


def _pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}%" if abs(x) < 100 else f"{x:.{digits}f}"


def _bar_row(b: Any) -> dict[str, Any]:
    d = b.to_dict()
    d["datetime"] = _ts(b.ts)
    return {k: d.get(k, "") for k in BAR_COLUMNS}


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_bars(args: argparse.Namespace) -> int:
    res = _build(args)
    _print_manifest(res)
    rows = [_bar_row(b) for b in res.bars]
    if args.limit:
        rows = rows[-args.limit:]
    out = args.out
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=BAR_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} bars -> {out}")
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=BAR_COLUMNS)
        w.writeheader()
        w.writerows(rows[-args.limit:] if args.limit else rows)

    print("\ncategory distribution (tradable bars)")
    for k, v in res.stats["category_counts"].items():
        share = res.stats["category_shares"][k]
        print(f"  {k:11s} {v:6d}  {share * 100:6.2f}%  {'#' * int(share * 60)}")
    print("\nKPI")
    for k in ("bars", "net_change_pct", "annualised_vol_pct", "atr_pct_mean",
              "mean_efficiency", "strong_share", "pressure_share", "up_share"):
        v = res.kpi.get(k)
        if isinstance(v, float):
            print(f"  {k:22s} {v:+.4f}")
        else:
            print(f"  {k:22s} {v}")
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    res = _build(args, cohort=True)
    _print_manifest(res)
    curves = res.stats.get("cohort_curves", {})
    cfg = S.SignalConfig(min_edge_score=args.min_score, cooldown_bars=args.cooldown)
    ss = S.generate(res.bars, res.indicators, res.settings, cfg,
                    warmup_index=res.warmup_index, cohort_curves=curves)
    diag = S.diagnose(res.bars, ss, res.settings, warmup_index=res.warmup_index)

    u = diag["universe"]
    print(f"universe       {u['bars_total']} bars, {u['bars_tradable']} tradable "
          f"({u['warmup_dropped']} dropped as warm-up), {u['days_covered']:.1f} days")
    print(f"category base rates: "
          + "  ".join(f"{k}={_pct(v)}" for k, v in diag["category_base_rates"].items()))
    print(f"theoretical max candidates before any filter: "
          f"{diag['theoretical_max_candidates']}")

    print("\nsignal funnel")
    print(f"  {'stage':14s} {'entered':>8s} {'passed':>8s} {'rejected':>9s} {'rate':>7s}")
    for f in diag["funnel"]:
        print(f"  {f['stage']:14s} {f['entered']:8d} {f['passed']:8d} "
              f"{f['rejected']:9d} {f['pass_rate']:7.3f}")
    print(f"\n  accepted signals : {diag['accepted']}"
          f"   ({diag['signals_per_day']:.2f}/day,"
          f" {_pct(diag['accept_rate_of_candidates'])} of candidates)")
    print(f"  hard rejections  : {diag['rejection_counts']}")
    print(f"  soft flags       : {diag['soft_flag_counts']}")
    print(f"  sole killer      : {diag['sole_killer']}")
    b = diag["bottleneck"]
    print(f"\nbottleneck     narrowest stage = {b.get('narrowest_stage')} "
          f"({b.get('narrowest_rejected')} rejected, "
          f"pass rate {b.get('narrowest_pass_rate')})")
    print(f"               most decisive filter = {b.get('most_decisive_filter')}")
    print(f"               redundant filters (reject >=5, never sole) = "
          f"{b.get('redundant_filters')}")
    print(f"score dist     {diag['score_distribution']}")
    print(f"grades         {diag['grade_distribution']}")

    print("\ndirectional information — does each category predict the NEXT move?")
    print("  (aligned forward return in bp; t-stat overlap-adjusted for window h)")
    for cat, info in diag["directional_information"].items():
        if info["up"] + info["down"] == 0:
            continue
        h = info["horizons"].get("4", {})
        h16 = info["horizons"].get("16", {})
        print(f"  {cat:11s} up/down={info['up']:4d}/{info['down']:4d} "
              f"({_pct(info['up_share'])} up)   "
              f"h=4: {h.get('mean_aligned_return_bp', 0):+7.1f}bp "
              f"t={h.get('t_stat_overlap_adjusted', 0):+5.2f} "
              f"win={_pct(h.get('win_rate', 0), 0)}   "
              f"h=16: {h16.get('mean_aligned_return_bp', 0):+7.1f}bp "
              f"t={h16.get('t_stat_overlap_adjusted', 0):+5.2f}")

    if args.sensitivity:
        print("\nthreshold sensitivity (candidate counts, tradable bars = "
              f"{S.threshold_sensitivity(res.bars, res.settings, warmup_index=res.warmup_index)['bars_tradable']})")
        sens = S.threshold_sensitivity(res.bars, res.settings,
                                       warmup_index=res.warmup_index)
        for k, row in sens.items():
            if k == "bars_tradable":
                continue
            print(f"  {k}:")
            for thr, cnt in row.items():
                print(f"    {thr:>6s} -> {cnt}")

    if args.json:
        _write_json(args.json, {
            "manifest": res.manifest,
            "diagnostic": diag,
            "signals": S.signal_frame(ss),
        })
        print(f"\nwrote {args.json}")
    return 0


def _risk_config(args: argparse.Namespace) -> RiskConfig:
    """Build the risk config from CLI flags.

    Costs live on ``RiskConfig.costs`` (a :class:`CostConfig`), not on
    ``RiskConfig`` itself — keeping that knowledge in one helper is what stops a
    caller from inventing a ``commission_bps=`` keyword that does not exist.
    """
    rcfg = RiskConfig(initial_equity=args.equity,
                      risk_per_trade_pct=args.risk_pct,
                      sizing_mode=args.sizing,
                      max_leverage=args.leverage)
    rcfg.costs.commission_bps = args.commission_bps
    rcfg.costs.slippage_bps = args.slippage_bps
    rcfg.costs.maker_bps = args.maker_bps
    return rcfg


def cmd_backtest(args: argparse.Namespace) -> int:
    res = _build(args, cohort=True)
    _print_manifest(res)
    curves = res.stats.get("cohort_curves", {})
    scfg = S.SignalConfig(min_edge_score=args.min_score, cooldown_bars=args.cooldown,
                          entry_timing=args.entry_timing)
    rcfg = _risk_config(args)
    xcfg = ExitConfig(stop_mode=args.stop_mode,
                      stop_sigma_mult=args.stop_sigma)
    bcfg = BT.BacktestConfig(use_intra_bar_path=not args.no_intrabar,
                             adverse_first=not args.optimistic,
                             entry_mode=args.entry_mode)

    r = BT.run_backtest(res, signal_cfg=scfg, risk_cfg=rcfg, exit_cfg=xcfg,
                        bt_cfg=bcfg, cohort_curves=curves)
    _print_backtest(r, res, label=args.entry_mode)

    if args.json:
        _write_json(args.json, r.to_dict())
        print(f"\nwrote {args.json}")
    if args.trades_csv:
        _write_trades_csv(args.trades_csv, r)
        print(f"wrote {len(r.trades)} trades -> {args.trades_csv}")
    return 0


def _print_backtest(r: Any, res: Any, label: str = "strategy") -> None:
    m = r.metrics
    tr = m.get("trades", {})
    ra = m.get("risk_adjusted", {})
    rt = m.get("returns", {})
    rk = m.get("risk", {})
    print(f"\n{'═' * 74}\nBACKTEST — {label}\n{'═' * 74}")
    print(f"  config hash    {r.manifest['config_hash']}   "
          f"entry={r.manifest['entry_mode']}  intra_bar={r.manifest['intra_bar_path']}  "
          f"adverse_first={r.manifest['adverse_first']}")
    print(f"  entry funnel   {r.entry_funnel.get('signals_emitted', 0)} signals -> "
          f"{r.entry_funnel.get('positions_opened', 0)} positions "
          f"(fill rate {_pct(r.entry_funnel.get('fill_rate', 0))})")
    if r.entry_blocks:
        print(f"  blocked by     {r.entry_blocks}")
    if r.pending_stats.get("orders_emitted"):
        ps = r.pending_stats
        print(f"  limit orders   {ps['orders_filled']}/{ps['orders_emitted']} filled, "
              f"{ps['orders_expired']} expired, {ps['orders_invalidated']} invalidated")
    print(f"\n  trades         {tr.get('n', 0)}   "
          f"win rate {_pct(tr.get('win_rate', 0), 1)}   "
          f"payoff {tr.get('payoff_ratio', 0):.2f}   "
          f"profit factor {tr.get('profit_factor', 0):.2f}")
    print(f"  expectancy     {tr.get('expectancy_r', 0):+.4f} R/trade   "
          f"median {tr.get('expectancy_r_median', 0):+.4f} R")
    print(f"  return         {rt.get('total_return_pct', 0):+.2f}%   "
          f"CAGR {rt.get('cagr_pct', 0):+.2f}%   "
          f"final equity {rt.get('final_equity', 0):,.0f}")
    print(f"  risk           ann.vol {rk.get('annualised_vol_pct', 0):.2f}%   "
          f"max DD {rk.get('max_drawdown_pct', 0):.2f}%   "
          f"Calmar {ra.get('calmar', 0):.2f}")
    ci = ra.get("sharpe_ci95", {})
    print(f"  Sharpe         {ra.get('sharpe', 0):+.2f}   "
          f"95% CI [{ci.get('lo', 0):+.2f}, {ci.get('hi', 0):+.2f}]   "
          f"P(Sharpe>0)={_pct(ci.get('p_greater_than_zero', 0), 0)}")
    dsr = ra.get("deflated_sharpe", {})
    print(f"  Sortino        {ra.get('sortino', 0):+.2f}   "
          f"deflated Sharpe {dsr.get('dsr', 0):.3f} "
          f"({'PASS' if dsr.get('pass_95') else 'FAIL'} at 95%)")
    print(f"  exposure       time in market {_pct(m.get('exposure', {}).get('time_in_market', 0), 1)}")
    print(f"\n  trade life     avg {tr.get('avg_bars_held', 0):.1f} bars held, "
          f"{tr.get('avg_tranches_filled', 0):.2f} tranches filled")
    print(f"  excursions     MFE {tr.get('mfe', {}).get('mean_peak_r', 0):+.2f}R   "
          f"MAE {tr.get('mae', {}).get('mean_trough_r', 0):+.2f}R   "
          f"capture {tr.get('capture_ratio_mean', 0):.2f}")
    print(f"  never reached +0.5R: {tr.get('trades_never_reached_0p5R', 0)} "
          f"of {tr.get('n', 0)}")
    print(f"  friction       {tr.get('friction_bp_mean', 0):.1f} bp/trade   "
          f"total {tr.get('friction_total', 0):,.0f} "
          f"({_pct(tr.get('friction_share_of_gross', 0), 0)} of gross P&L)")
    print(f"  cost split     gross {tr.get('gross_expectancy_r', 0):+.4f} R/trade "
          f"- friction {tr.get('friction_r_per_trade', 0):.4f} R/trade "
          f"= net {tr.get('expectancy_r', 0):+.4f} R/trade")
    verdict = tr.get('cost_verdict', '')
    if verdict:
        print(f"  verdict        {verdict}")
    print(f"  streaks        max win {tr.get('max_win_streak', 0)}, "
          f"max loss {tr.get('max_loss_streak', 0)}")

    print("\n  exits")
    for k, v in sorted(tr.get("exit_reasons", {}).items(),
                       key=lambda kv: -kv[1]["n"])[:8]:
        print(f"    {k[:44]:44s} n={v['n']:4d} "
              f"({_pct(v['share'], 0)})  E[R]={v['expectancy_r']:+.3f}  "
              f"win={_pct(v['win_rate'], 0)}")
    print("  by side")
    for k, v in tr.get("by_side", {}).items():
        if v.get("n"):
            print(f"    {k:6s} n={v['n']:4d} win={_pct(v['win_rate'], 0)} "
                  f"E[R]={v['expectancy_r']:+.3f} pnl={v['net_pnl']:+,.0f}")
    if tr.get("score_bucket"):
        print("  does a higher edge score predict a better trade?")
        for k, v in tr["score_bucket"].items():
            if v["n"]:
                print(f"    score {k:9s} n={v['n']:4d} "
                      f"E[R]={v['expectancy_r']:+.3f} win={_pct(v['win_rate'], 0)}")

    bh = r.benchmark.get("buy_and_hold", {})
    print(f"\n  benchmark      buy&hold {bh.get('return_pct', 0):+.2f}% "
          f"(max DD {_pct(bh.get('max_drawdown', 0))}) vs strategy "
          f"{rt.get('total_return_pct', 0):+.2f}%")
    if r.accounting_errors:
        print(f"\n  !! ACCOUNTING ERRORS: {len(r.accounting_errors)}")
        for e in r.accounting_errors[:3]:
            print(f"     {e}")
    if r.warnings:
        print("\n  warnings")
        for w in r.warnings[:6]:
            print(f"    - {w}")


def cmd_compare(args: argparse.Namespace) -> int:
    res = _build(args, cohort=True)
    _print_manifest(res)
    curves = res.stats.get("cohort_curves", {})
    scfg = S.SignalConfig(min_edge_score=args.min_score, cooldown_bars=args.cooldown,
                          entry_timing=args.entry_timing)
    rcfg = _risk_config(args)
    xcfg = ExitConfig(stop_mode=args.stop_mode, stop_sigma_mult=args.stop_sigma)

    strat = BT.run_backtest(res, signal_cfg=scfg, risk_cfg=rcfg, exit_cfg=xcfg,
                            cohort_curves=curves)
    ctrl = BT.run_backtest(res, signal_cfg=scfg, risk_cfg=rcfg, exit_cfg=xcfg,
                           cohort_curves=curves,
                           bt_cfg=BT.BacktestConfig(entry_mode="random",
                                                    random_seed=args.seed))
    every = BT.run_backtest(res, signal_cfg=scfg, risk_cfg=rcfg, exit_cfg=xcfg,
                            cohort_curves=curves,
                            bt_cfg=BT.BacktestConfig(entry_mode="every_bar"))

    _print_backtest(strat, res, "strategy")
    cmp_ = metrics.compare(strat, ctrl, every)
    print(f"\n{'═' * 74}\nCONTROLS — is the edge in the entry, or in the exit?\n{'═' * 74}")
    print(f"  {'configuration':24s} {'trades':>7s} {'return%':>9s} {'Sharpe':>8s} "
          f"{'maxDD%':>8s} {'win%':>7s} {'E[R]':>8s} {'PF':>6s}")
    for row in cmp_["rows"]:
        print(f"  {row['label']:24s} {row['n_trades']:7d} {row['return_pct']:+9.2f} "
              f"{row['sharpe']:+8.2f} {row['max_dd_pct']:8.2f} "
              f"{row['win_rate'] * 100:7.1f} {row['expectancy_r']:+8.3f} "
              f"{row['profit_factor']:6.2f}")
    print(f"\n  verdict: {cmp_['verdict']}")
    print("  reading: beats random control -> the entry selection carries information;")
    print("           ties random but beats every-bar -> the exit logic carries it and")
    print("           the signal is decoration; loses to both -> cost generator.")
    if args.json:
        _write_json(args.json, {"strategy": strat.to_dict(include_trades=False),
                                "random_control": ctrl.to_dict(include_trades=False),
                                "every_bar_control": every.to_dict(include_trades=False),
                                "comparison": cmp_})
        print(f"\nwrote {args.json}")
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    """Parameter sweep with plateau analysis, walk-forward and PBO."""
    res = _build(args, cohort=True)
    _print_manifest(res)
    curves = res.stats.get("cohort_curves", {})
    ppy = res.manifest["settings"]["timeframe"] and None
    from engine.resample import periods_per_year
    ppy = periods_per_year(res.settings.timeframe)

    param = args.param
    grid = [float(x) for x in args.grid.split(",")]
    returns_by_cfg: dict[str, Sequence[float]] = {}
    sweep: list[tuple[float, float]] = []
    rows: list[dict[str, Any]] = []

    for value in grid:
        scfg = S.SignalConfig(min_edge_score=args.min_score, cooldown_bars=args.cooldown,
                              entry_timing=args.entry_timing)
        xcfg = ExitConfig(stop_mode=args.stop_mode, stop_sigma_mult=args.stop_sigma)
        if param == "min_edge_score":
            scfg.min_edge_score = value
        elif param == "stop_sigma_mult":
            xcfg.stop_sigma_mult = value
        elif param == "pullback_retrace_sigma":
            scfg.pullback_retrace_sigma = value
        elif param == "cooldown_bars":
            scfg.cooldown_bars = int(value)
        else:
            raise SystemExit(f"unsupported sweep parameter: {param}")
        label = f"{param}={value:g}"
        r = BT.run_backtest(res, signal_cfg=scfg, exit_cfg=xcfg, cohort_curves=curves)
        eq = [p.equity for p in r.equity_curve]
        rets = [(eq[k] - eq[k - 1]) / eq[k - 1] if eq[k - 1] else 0.0
                for k in range(1, len(eq))]
        returns_by_cfg[label] = rets
        sh = r.metrics["risk_adjusted"]["sharpe"]
        sweep.append((value, sh))
        rows.append({"label": label, "value": value, "trades": len(r.trades),
                     "return_pct": r.metrics["returns"]["total_return_pct"],
                     "sharpe": sh,
                     "max_dd_pct": r.metrics["risk"]["max_drawdown_pct"],
                     "expectancy_r": r.metrics["trades"].get("expectancy_r", 0.0)})

    print(f"\nsweep over {param} ({len(grid)} values, {len(grid)} backtests)")
    print(f"  {'value':>10s} {'trades':>7s} {'return%':>9s} {'Sharpe':>8s} "
          f"{'maxDD%':>8s} {'E[R]':>8s}")
    for row in rows:
        print(f"  {row['value']:10.3g} {row['trades']:7d} {row['return_pct']:+9.2f} "
              f"{row['sharpe']:+8.2f} {row['max_dd_pct']:8.2f} "
              f"{row['expectancy_r']:+8.3f}")

    plateau = validation.best_plateau(sweep, window=args.window)
    print(f"\nparameter plateau (neighbourhood window={args.window})")
    print(f"  best point value      : {plateau.get('best_point_value')} "
          f"(Sharpe {plateau.get('best_point_score', 0):+.2f})")
    print(f"  widest-plateau value  : {plateau.get('chosen')} "
          f"(neighbour mean {plateau.get('chosen_neighbour_mean', 0):+.2f})")
    print(f"  point == plateau?     : {plateau.get('agrees')}")
    print("  NB: prefer the plateau centre over the single best point.  A spike is a")
    print("      parameter that only works at exactly that value, which is the")
    print("      signature of a fit to this sample.")
    for row in plateau.get("rows", []):
        flag = "  <-- SPIKE" if row["is_spike"] else ""
        print(f"    {row['value']:10.3g} score={row['score']:+7.2f} "
              f"neighbour_mean={row['neighbour_mean']:+7.2f}{flag}")

    wf = validation.walk_forward(returns_by_cfg, periods_per_year=ppy,
                                 n_splits=args.folds, purge=args.purge,
                                 embargo=args.embargo)
    print(f"\nwalk-forward ({len(wf.folds)} folds, purge={args.purge}, "
          f"embargo={args.embargo})")
    for f in wf.folds:
        print(f"  fold {f.fold}: train[{f.train_idx[0]}..{f.train_idx[1]}] "
              f"test[{f.test_idx[0]}..{f.test_idx[1]}] "
              f"best={f.best_config} IS={f.is_score:+.2f} OOS={f.oos_score:+.2f} "
              f"OOS_ret={f.oos_return_pct:+.2f}% "
              f"(IS rank of the OOS-best: {f.is_rank_of_oos_best + 1}/{f.n_configs})")
    print(f"  in-sample Sharpe mean : {wf.is_sharpe_mean:+.2f}")
    print(f"  out-of-sample Sharpe  : {wf.oos_sharpe:+.2f}")
    print(f"  overfitting gap       : {wf.overfit_gap:+.2f}  "
          f"(IS minus OOS; a large gap is the cost of searching)")
    print(f"  OOS return / max DD   : {wf.oos_return_pct:+.2f}% / {wf.oos_max_dd_pct:.2f}%")
    if wf.pbo:
        print(f"\n  PBO (CSCV)            : {wf.pbo.get('pbo', 0):.3f}  "
              f"[{wf.pbo.get('interpretation', '-')}]")
        print(f"     splits={wf.pbo.get('n_combos_evaluated')} "
              f"configs={wf.pbo.get('n_configs')}")
    print(f"  deflated Sharpe       : {wf.deflated.get('dsr', 0):.3f} "
          f"({'PASS' if wf.deflated.get('pass_95') else 'FAIL'} at 95%, "
          f"trials={len(grid)})")

    if args.json:
        _write_json(args.json, {"param": param, "grid": grid, "rows": rows,
                                "plateau": plateau, "walk_forward": wf.to_dict()})
        print(f"\nwrote {args.json}")
    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    res = _build(args, cohort=True)
    _print_manifest(res)
    curves = res.stats.get("cohort_curves", {})

    def run_one(name: str, disabled: bool) -> dict[str, Any]:
        kw: dict[str, Any] = {"min_edge_score": args.min_score,
                              "cooldown_bars": args.cooldown,
                              "entry_timing": args.entry_timing}
        if disabled and name:
            flag = {"trend": "f_trend", "volatility": "f_volatility",
                    "volume": "f_volume", "structure": "f_structure",
                    "momentum": "f_momentum", "extension": "f_extension",
                    "timing": "f_timing", "quality": "f_quality"}.get(name)
            if flag:
                kw[flag] = False
        scfg = S.SignalConfig(**kw)
        r = BT.run_backtest(res, signal_cfg=scfg, cohort_curves=curves)
        return {"n_trades": len(r.trades),
                "expectancy_r": r.metrics["trades"].get("expectancy_r", 0.0),
                "sharpe": r.metrics["risk_adjusted"]["sharpe"],
                "max_dd_pct": r.metrics["risk"]["max_drawdown_pct"],
                "return_pct": r.metrics["returns"]["total_return_pct"],
                "win_rate": r.metrics["trades"].get("win_rate", 0.0)}

    filters = ["trend", "volatility", "volume", "structure", "momentum",
               "extension", "timing", "quality"]
    rep = validation.ablation(run_one, filters)
    base = rep["baseline"]
    print(f"\n{'═' * 74}\nFILTER ABLATION — does each confirmation filter earn its place?\n{'═' * 74}")
    print(f"  baseline (all filters on): trades={base['n_trades']} "
          f"E[R]={base['expectancy_r']:+.3f} Sharpe={base['sharpe']:+.2f} "
          f"return={base['return_pct']:+.2f}% maxDD={base['max_dd_pct']:.2f}%")
    print(f"\n  {'filter':12s} {'trades':>7s} {'dN':>6s} {'dE[R]':>8s} {'dSharpe':>9s} "
          f"{'dRet%':>8s} {'dDD%':>7s}  verdict")
    for name, row in rep["filters"].items():
        print(f"  {name:12s} {row['n_trades']:7d} {row['delta_n_trades']:+6d} "
              f"{row['delta_expectancy_r']:+8.3f} {row['delta_sharpe']:+9.2f} "
              f"{row['delta_return_pct']:+8.2f} {row['delta_max_dd_pct']:+7.2f}  "
              f"{row['verdict']}")
    print("\n  verdicts: keep    = removing it hurts (it is doing real work)")
    print("            decoration = removing it changes ~nothing (consider dropping)")
    print("            harmful = removing it IMPROVES the result (it is costing money)")
    print("            review  = mixed signal, needs a judgement call")
    if args.json:
        _write_json(args.json, rep)
        print(f"\nwrote {args.json}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    res = _build(args, cohort=True)
    curves = res.stats.get("cohort_curves", {})
    key = f"{args.weekday}-{args.hour}"
    curve = curves.get(key)
    if not curve:
        print(f"no cohort curve for {key} (need >= 5 bars in that weekday/hour cell)")
        return 1
    from engine.path import curve_to_dicts
    print(f"intra-bar growth curve for weekday={args.weekday} hour={args.hour} UTC")
    print(f"  {'elapsed%':>9s} {'formed%':>9s}")
    for d in curve_to_dicts(curve):
        print(f"  {d['elapsed_pct'] * 100:9.1f} {d['formed_pct'] * 100:9.1f}")
    return 0


# --------------------------------------------------------------------------- #
# io
# --------------------------------------------------------------------------- #
def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(o: Any) -> Any:
    for attr in ("to_dict", "_asdict"):
        if hasattr(o, attr):
            return getattr(o, attr)()
    if hasattr(o, "value"):
        return o.value
    return str(o)


def _write_trades_csv(path: str, r: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cols = ("entry_ts", "entry_dt", "exit_ts", "exit_dt", "side", "strategy",
            "category", "signal_score", "entry_price", "avg_exit_price", "qty",
            "notional", "risk_cash", "gross_pnl", "commission_cost",
            "slippage_cost", "funding_cost", "costs", "net_pnl", "r_multiple",
            "peak_r", "trough_r", "bars_held", "exit_reason", "tranches_filled",
            "stop_tightened", "events", "equity_after", "drawdown_after")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for t in r.trades:
            w.writerow([
                t.entry_ts, _ts(t.entry_ts), t.exit_ts, _ts(t.exit_ts),
                "long" if t.side > 0 else "short", t.strategy, t.category,
                f"{t.signal_score:.4f}", f"{t.entry_price:.8g}",
                f"{t.avg_exit_price:.8g}", f"{t.qty:.8g}", f"{t.notional:.4f}",
                f"{t.risk_cash:.4f}", f"{t.gross_pnl:.4f}",
                f"{t.commission_cost:.4f}", f"{t.slippage_cost:.4f}",
                f"{t.funding_cost:.4f}", f"{t.costs:.4f}", f"{t.net_pnl:.4f}",
                f"{t.r_multiple:.4f}", f"{t.peak_r:.4f}", f"{t.trough_r:.4f}",
                t.bars_held, t.exit_reason, t.tranches_filled, t.stop_tightened,
                "|".join(t.events_seen), f"{t.equity_after:.2f}",
                f"{t.drawdown_after:.6f}",
            ])


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="app.cli",
        description="TBAE — trading backtest & analytics engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="With no sub-command the CLI exports annotated bars (README §1).")
    p.add_argument("command", nargs="?", default="bars",
                   choices=("bars", "signals", "backtest", "compare", "sweep",
                            "ablation", "path"),
                   help="what to do (default: bars)")

    g = p.add_argument_group("data")
    g.add_argument("--tf", type=int, default=15, help="timeframe in minutes")
    g.add_argument("--days", type=int, default=45, help="synthetic history length")
    g.add_argument("--seed", type=int, default=20260913, help="RNG seed")
    g.add_argument("--csv", help="load 1-minute bars from this CSV instead")
    g.add_argument("--feed", help="feed spec: synthetic / csv:path / binance:SYM:days=N")

    g = p.add_argument_group("research settings")
    g.add_argument("--reference-percentile", type=float, default=98.0)
    g.add_argument("--outlier-share", type=float, default=0.02)
    g.add_argument("--weak-threshold", type=float, default=20.0)
    g.add_argument("--big-threshold", type=float, default=55.0)
    g.add_argument("--pressure-threshold", type=float, default=80.0)
    g.add_argument("--dead-share", type=float, default=0.33)
    g.add_argument("--hot-share", type=float, default=0.25)
    g.add_argument("--reference-min-bars", type=int, default=200)
    g.add_argument("--reference-mode", default="expanding",
                   choices=("expanding", "rolling", "full"),
                   help="'full' is look-ahead and the backtester refuses it")
    g.add_argument("--timing-mode", default="expanding",
                   choices=("expanding", "full"))

    g = p.add_argument_group("strategy")
    g.add_argument("--min-score", type=float, default=0.45,
                   help="minimum edge score to accept a signal")
    g.add_argument("--cooldown", type=int, default=2, help="bars between entries")
    g.add_argument("--entry-timing", default="pullback_limit",
                   choices=("immediate", "pullback_limit"))
    g.add_argument("--stop-mode", default="sigma_structure_max",
                   choices=("sigma", "atr", "structure", "sigma_structure_max",
                            "sigma_structure_min"))
    g.add_argument("--stop-sigma", type=float, default=2.2)
    g.add_argument("--entry-mode", default="signal",
                   choices=("signal", "random", "every_bar"))

    g = p.add_argument_group("risk / costs")
    g.add_argument("--equity", type=float, default=100_000.0)
    g.add_argument("--risk-pct", type=float, default=0.75,
                   help="percent of equity risked per trade")
    g.add_argument("--sizing", default="risk_and_vol",
                   choices=("fixed_fractional", "vol_target", "risk_and_vol",
                            "kelly_capped"))
    g.add_argument("--leverage", type=float, default=3.0)
    g.add_argument("--commission-bps", type=float, default=4.0)
    g.add_argument("--maker-bps", type=float, default=1.0)
    g.add_argument("--slippage-bps", type=float, default=2.0)

    g = p.add_argument_group("accuracy switches")
    g.add_argument("--no-intrabar", action="store_true",
                   help="disable minute-level exit resolution (inflates results)")
    g.add_argument("--optimistic", action="store_true",
                   help="resolve ambiguous intra-bar ordering in our favour")

    g = p.add_argument_group("sweep / walk-forward")
    g.add_argument("--param", default="min_edge_score",
                   choices=("min_edge_score", "stop_sigma_mult",
                            "pullback_retrace_sigma", "cooldown_bars"))
    g.add_argument("--grid", default="0.30,0.40,0.45,0.50,0.55,0.60,0.70")
    g.add_argument("--window", type=int, default=1, help="plateau neighbour window")
    g.add_argument("--folds", type=int, default=5)
    g.add_argument("--purge", type=int, default=16)
    g.add_argument("--embargo", type=int, default=4)

    g = p.add_argument_group("output")
    g.add_argument("--out", help="bars CSV destination")
    g.add_argument("--limit", type=int, default=0, help="limit rows printed/written")
    g.add_argument("--json", help="write the full report as JSON")
    g.add_argument("--trades-csv", help="write the trade blotter as CSV")
    g.add_argument("--sensitivity", action="store_true",
                   help="also print the threshold sensitivity table")
    g.add_argument("--weekday", type=int, default=0)
    g.add_argument("--hour", type=int, default=13)
    return p


HANDLERS = {
    "bars": cmd_bars,
    "signals": cmd_signals,
    "backtest": cmd_backtest,
    "compare": cmd_compare,
    "sweep": cmd_sweep,
    "ablation": cmd_ablation,
    "path": cmd_path,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
