"""Event-driven backtester with exact intra-bar path resolution.

What makes this accurate rather than merely plausible
----------------------------------------------------
1. **No look-ahead, structurally.**  Signals are stamped on closed bar ``i``
   (``signals.generate`` stops at ``n-1`` for exactly this reason) and filled at
   bar ``i+1``'s open.  Stop/target geometry is decided from bar ``i``'s sigma and
   applied to the realised fill.  Every indicator series is causal.
2. **Minute-level exit resolution.**  Because each bar retains its minute path,
   stops and targets are tested against each minute in order.  A bar whose low
   precedes its high no longer turns a losing long into a winner — the single most
   common source of fictitious backtest edge.
3. **Gaps are honoured, not smoothed.**  If a minute *opens* beyond the stop, the
   fill is the open (worse than the stop).  If it opens beyond a target, the fill
   is the open (better).  Both are what a real order would have done.
4. **Ambiguity resolved against us.**  When one minute's range spans both the stop
   and a target the order is genuinely unknown; ``adverse_first`` assumes the stop.
5. **Friction on every leg.**  Commission + slippage + sqrt-impact per fill, so a
   three-tranche exit pays three exit costs.  Funding accrues per bar held.
6. **Open trades at the end are closed and counted.**  Dropping them is
   trade-level survivorship bias and always flatters the result.
7. **Controls.**  ``random_entry_control`` re-runs identical exit logic on
   randomly-timed entries; ``every_bar`` runs it on all bars.  If the strategy
   cannot beat its own random control, the edge lives in the exit logic (or
   nowhere) — not in the signal.

Accounting identity
-------------------
``gross_pnl`` is measured at **reference prices** (entry at the bar open, exits at
the stop/target/close level).  Friction is itemised as commission, funding and
slippage, and ``net_pnl == gross_pnl - costs`` exactly.  Cash is moved using the
*actual* (slipped) fills, which is arithmetically identical but cannot drift.
``tests/test_backtest.py`` asserts both, per trade.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import signals as sig_mod
from .exits import ExitConfig, ExitManager
from .indicators import Indicators
from .mathx import EPS, clamp, mean, safe_div
from .models import Bar, MinuteBar
from .path import PathPoint
from .pipeline import PipelineResult
from .portfolio import EquityPoint, Fill, Position, Trade, Tranche
from .resample import periods_per_year
from .risk import RiskConfig, RiskManager, risk_report


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class BacktestConfig:
    #: Resolve exits minute-by-minute using the retained path.  Turning this off
    #: degrades to bar-level resolution and *will* inflate results.
    use_intra_bar_path: bool = True
    #: When one minute's range spans both stop and target, assume the adverse one
    #: happened first.  Pessimistic by design.
    adverse_first: bool = True
    #: Honour gaps: fill at the minute open when it is beyond the level.
    honour_gaps: bool = True
    #: ``signal`` | ``random`` | ``every_bar`` (the last two are controls)
    entry_mode: str = "signal"
    random_seed: int = 20260913
    random_entry_count: int = 0          # 0 = match the number of real signals
    equity_curve_every: int = 1
    mark_open_positions: bool = True
    close_open_at_end: bool = True
    #: Refuse to run when the pipeline used a look-ahead reference/timing map.
    allow_lookahead: bool = False
    #: A take-profit tranche is a limit order that was resting in the book from
    #: the moment the position opened, so it fills at its price (no spread
    #: crossing) and earns the maker rate.  Stops, trails, event exits and time
    #: exits *initiate* — they cross the spread and pay taker.  Set False to
    #: charge every exit leg as a taker (a conservative, exchange-agnostic view).
    target_exits_are_maker: bool = True

    def validate(self) -> "BacktestConfig":
        if self.entry_mode not in ("signal", "random", "every_bar"):
            raise ValueError(f"unknown entry_mode {self.entry_mode!r}")
        if self.equity_curve_every < 1:
            raise ValueError("equity_curve_every must be >= 1")
        return self


@dataclass(slots=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    signals: sig_mod.SignalSet | None = None
    signal_diagnostic: dict[str, Any] = field(default_factory=dict)
    risk_snapshot: dict[str, Any] = field(default_factory=dict)
    risk_report: dict[str, Any] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    benchmark: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: per-trade violations of ``net == gross - costs``; must stay empty
    accounting_errors: list[str] = field(default_factory=list)
    #: signal -> position attribution: how many entries were vetoed, and by what
    entry_blocks: dict[str, int] = field(default_factory=dict)
    entry_funnel: dict[str, Any] = field(default_factory=dict)
    #: limit-entry bookkeeping: emitted / filled / expired / invalidated
    pending_stats: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    bars: list[Bar] = field(default_factory=list)

    def r_multiples(self) -> list[float]:
        return [t.r_multiple for t in self.trades]

    def net_pnls(self) -> list[float]:
        return [t.net_pnl for t in self.trades]

    def equity_series(self) -> list[float]:
        return [e.equity for e in self.equity_curve]

    def to_dict(self, include_trades: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "manifest": self.manifest,
            "metrics": self.metrics,
            "benchmark": self.benchmark,
            "risk_snapshot": self.risk_snapshot,
            "risk_report": self.risk_report,
            "exit_reason_counts": self.exit_reason_counts,
            "warnings": self.warnings,
            "accounting_errors": self.accounting_errors,
            "entry_funnel": self.entry_funnel,
            "pending_stats": self.pending_stats,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "n_trades": len(self.trades),
        }
        if include_trades:
            d["trades"] = [t.to_dict() for t in self.trades]
            d["equity_curve"] = [e.to_dict() for e in self.equity_curve]
        return d


@dataclass(slots=True)
class PendingOrder:
    """A resting limit entry.

    Created on the bar *after* the signal (the signal is stamped on a closed bar,
    so the earliest an order can exist is the following bar's open) and cancelled
    after ``ttl`` bars.  Expiry is reported, not hidden: unfilled pullback orders
    are the opportunity cost of not chasing, and if that number is large the
    retracement level is simply set too deep.
    """

    signal: Any
    side: int
    level: float
    created_index: int
    ttl: int
    maker: bool = True
    stop_distance: float = 0.0

    def expired(self, index: int) -> bool:
        return index - self.created_index >= self.ttl


@dataclass(slots=True)
class _ControlSignal:
    """Duck-typed stand-in for :class:`Signal` used by the control modes."""

    index: int
    bar: Bar
    side: int = 0
    strategy: str = "control"
    score: float = 0.0

    def __post_init__(self) -> None:
        if self.side == 0:
            self.side = self.bar.direction or 1


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
class Backtester:
    def __init__(self, res: PipelineResult, *,
                 signal_cfg: sig_mod.SignalConfig | None = None,
                 risk_cfg: RiskConfig | None = None,
                 exit_cfg: ExitConfig | None = None,
                 bt_cfg: BacktestConfig | None = None,
                 cohort_curves: dict[str, list[PathPoint]] | None = None) -> None:
        self.res = res
        self.bars = res.bars
        self.ind: Indicators = res.indicators
        self.settings = res.settings
        self.scfg = (signal_cfg or sig_mod.SignalConfig()).validate()
        self.rcfg = (risk_cfg or RiskConfig()).validate()
        self.xcfg = (exit_cfg or ExitConfig()).validate()
        self.bcfg = (bt_cfg or BacktestConfig()).validate()
        self.curves = cohort_curves or {}
        self.xmgr = ExitManager(self.xcfg, self.settings)
        # annualisation must match the timeframe being traded, or vol targeting
        # silently sizes for a different market
        self.rcfg.periods_per_year = periods_per_year(self.settings.timeframe)
        self.rmgr = RiskManager(self.rcfg)
        self._trades: list[Trade] = []
        self._control_signal_count: int = 0
        self._accounting_errors: list[str] = []
        #: why each signal did NOT become a position.  Without this, a run where
        #: 139 signals produce 8 trades looks like a bug rather than what it is:
        #: the risk layer vetoing entries.  Attribution is the only way to tell
        #: the two apart.
        self._entry_blocks: dict[str, int] = {}
        #: set by :meth:`_guard_lookahead`; recorded in the manifest
        self._lookahead_flags: list[str] = []
        #: accepted signals that reached the entry stage
        self._signals_emitted: int = 0
        #: fills that reached the risk gate (an order that never fills never gets
        #: here, so this is NOT the number of signals)
        self._entry_attempts: int = 0
        self._orders_emitted: int = 0
        self._orders_filled: int = 0
        self._orders_expired: int = 0
        self._orders_invalidated: int = 0
        self._pending: list[PendingOrder] = []
        self._signals: sig_mod.SignalSet | None = None

    # ------------------------------------------------------------------ #
    def run(self) -> BacktestResult:
        t0 = time.perf_counter()
        out = BacktestResult()
        warnings: list[str] = []
        self._guard_lookahead(warnings)

        entries = self._build_entries(warnings)

        open_positions: list[Position] = []
        all_positions: list[Position] = []
        equity_curve: list[EquityPoint] = []

        start = max(1, self.res.warmup_index)
        n = len(self.bars)

        for i in range(start, n):
            bar = self.bars[i]
            self.rmgr.roll_day(bar.ts, i)

            # (1) entry.  A signal decided on bar i-1 may act from bar i onward.
            s = entries.get(i - 1)
            if s is not None:
                opened = self._act_on_signal(s, i, open_positions, all_positions)
                _ = opened

            # (1b) service resting limit orders against this bar
            self._service_pending(i, bar, open_positions, all_positions)

            # (2) walk this bar for every open position (including the new one)
            for pos in list(open_positions):
                self._process_bar(pos, bar, i)
                if not pos.open:
                    open_positions.remove(pos)

            # (3) mark to market
            unreal = 0.0
            open_risk = 0.0
            if self.bcfg.mark_open_positions:
                for pos in open_positions:
                    unreal += pos.side * (bar.close - pos.entry_price) * pos.qty
                    open_risk += pos.qty * pos.stop_distance
            self.rmgr.st.open_risk = open_risk
            self.rmgr.st.open_positions = len(open_positions)
            self.rmgr.mark(self.rmgr.st.cash + unreal)

            if (i - start) % self.bcfg.equity_curve_every == 0 or i == n - 1:
                equity_curve.append(EquityPoint(
                    ts=bar.ts, index=i, equity=self.rmgr.st.equity,
                    cash=self.rmgr.st.cash, drawdown=self.rmgr.st.drawdown,
                    open_positions=len(open_positions), open_risk=open_risk,
                    mark_price=bar.close,
                ))

        # (4) close anything still open — and say so loudly
        if open_positions:
            last = self.bars[-1]
            if self.bcfg.close_open_at_end:
                for pos in open_positions:
                    warnings.append(
                        f"position from index {pos.entry_index} was still open at end "
                        "of data; closed at the last close (counted, not dropped)"
                    )
                    self._close(pos, last.close, last.close, last.ts, n - 1,
                                "end_of_data", 1.0)
            else:
                warnings.append(
                    "open positions at end of data were DROPPED — this biases results"
                )
            open_positions.clear()

        out.trades = self._trades
        out.positions = all_positions
        out.equity_curve = equity_curve
        out.risk_snapshot = self.rmgr.snapshot()
        out.risk_report = risk_report(self._trades, self.rcfg)
        out.exit_reason_counts = self._exit_counts(self._trades)
        out.bars = self.bars
        if self._accounting_errors:
            warnings.append(
                f"ACCOUNTING IDENTITY VIOLATED on {len(self._accounting_errors)} "
                f"trade(s); first: {self._accounting_errors[0]}")
        out.accounting_errors = list(self._accounting_errors)
        out.entry_blocks = dict(sorted(self._entry_blocks.items(),
                                       key=lambda kv: -kv[1]))
        out.pending_stats = {
            "orders_emitted": self._orders_emitted,
            "orders_filled": self._orders_filled,
            "orders_expired": self._orders_expired,
            "orders_invalidated": self._orders_invalidated,
            "fill_rate": safe_div(self._orders_filled, self._orders_emitted, 0.0),
            "still_resting_at_end": len(self._pending),
            "entry_timing": self.scfg.entry_timing,
        }
        if self._orders_emitted:
            warnings.append(
                f"limit entries: {self._orders_filled}/{self._orders_emitted} filled "
                f"({out.pending_stats['fill_rate'] * 100:.0f}%), "
                f"{self._orders_expired} expired, "
                f"{self._orders_invalidated} invalidated by price running away")
        # The funnel has to RECONCILE, or it lies.  Two distinct attrition points
        # are easy to conflate: an order that never fills (price ran away) and a
        # fill that the risk layer then vetoes.  Reporting only the second makes a
        # 52-signal run look like a 30-signal run and hides the real bottleneck.
        ps = out.pending_stats
        opened = len(all_positions)
        gate_blocked = self._entry_attempts - opened
        out.entry_funnel = {
            "signals_emitted": self._signals_emitted,
            "orders_placed": self._orders_emitted,
            "orders_filled": self._orders_filled,
            "orders_invalidated": self._orders_invalidated,
            "orders_expired": self._orders_expired,
            "orders_resting_at_end": ps.get("still_resting_at_end", 0),
            "entry_attempts": self._entry_attempts,
            "gate_blocked": gate_blocked,
            "positions_opened": opened,
            "fill_rate": safe_div(self._orders_filled, self._orders_emitted, 0.0),
            "gate_pass_rate": safe_div(opened, self._entry_attempts, 0.0),
            "end_to_end_rate": safe_div(opened, self._signals_emitted, 0.0),
            "blocks_by_reason": out.entry_blocks,
        }
        ef = out.entry_funnel
        if (ef["orders_placed"] != ef["orders_filled"] + ef["orders_invalidated"]
                + ef["orders_expired"] + ef["orders_resting_at_end"]):
            self._accounting_errors.append(
                "entry_funnel: orders_placed != filled + invalidated + expired + resting")
        if ef["entry_attempts"] != opened + gate_blocked:
            self._accounting_errors.append(
                "entry_funnel: entry_attempts != positions_opened + gate_blocked")
        if self._entry_blocks and opened < self._signals_emitted:
            top = max(self._entry_blocks.items(), key=lambda kv: kv[1])
            warnings.append(
                f"entry attrition: {self._signals_emitted} signals -> "
                f"{self._orders_filled} fills -> {opened} positions "
                f"({ef['end_to_end_rate'] * 100:.0f}% end to end); largest blocker "
                f"'{top[0]}' ({top[1]}x). See entry_funnel for the full breakdown.")
        out.warnings = warnings
        out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if out.signals is not None:
            out.signal_diagnostic = sig_mod.diagnose(
                self.bars, out.signals, self.settings, warmup_index=self.res.warmup_index)

        final_equity = self.rmgr.st.equity
        out.manifest = self._manifest(final_equity, warnings)
        out.benchmark = self._benchmark(final_equity)

        from . import metrics as metrics_mod
        out.metrics = metrics_mod.summarise(
            out, initial_equity=self.rcfg.initial_equity,
            periods_per_year=self.rcfg.periods_per_year,
            timeframe=self.settings.timeframe,
        )
        # Surface the gross/net split as a warning, because it changes what the
        # next step should be: a cost-bound result is fixed with geometry (wider
        # stops, fewer legs, resting orders) while a signal-bound result is fixed
        # with filters.  Without this the two look identical — both are just
        # "negative expectancy".
        tstats = out.metrics.get("trades", {})
        if tstats.get("cost_bound"):
            out.warnings.append(f"{tstats.get('cost_verdict', 'cost-bound')}")
        elif tstats.get("gross_expectancy_r", 0.0) <= 0.0 and tstats.get("n", 0):
            out.warnings.append(
                f"gross expectancy is non-positive ({tstats.get('cost_verdict', '')}): "
                "the edge is in the signal, not the cost model")
        return out

    # ------------------------------------------------------------------ #
    def _guard_lookahead(self, warnings: list[str]) -> None:
        la: list[str] = []
        self._lookahead_flags = la
        if self.settings.reference_mode == "full":
            la.append("reference_mode='full'")
        if self.settings.timing_mode == "full":
            la.append("timing_mode='full'")
        if la and not self.bcfg.allow_lookahead:
            raise ValueError(
                f"look-ahead detected ({', '.join(la)}): the dynamic reference / "
                "timing map would be built from the whole sample, so early bars are "
                "scored against future information. Use 'expanding' or 'rolling', or "
                "pass allow_lookahead=True to override — the override is recorded in "
                "the run manifest."
            )
        if la:
            warnings.append("LOOK-AHEAD ALLOWED EXPLICITLY: " + ", ".join(la))
        if not self.bcfg.use_intra_bar_path:
            warnings.append("accuracy: intra-bar path resolution disabled")
        if not self.bcfg.adverse_first:
            warnings.append("optimism: ambiguous intra-bar ordering resolved favourably")
        if not self.bcfg.honour_gaps:
            warnings.append("optimism: gap-through fills ignored")

    def _build_entries(self, warnings: list[str]) -> dict[int, Any]:
        """Map ``decision bar index -> signal``."""
        start = max(1, self.res.warmup_index)
        n = len(self.bars)
        if self.bcfg.entry_mode == "signal":
            sset = sig_mod.generate(self.bars, self.ind, self.settings, self.scfg,
                                    warmup_index=self.res.warmup_index,
                                    cohort_curves=self.curves)
            self._signals = sset
            self._signals_emitted = len(sset.signals)
            return {s.index: s for s in sset.signals}

        idxs = list(range(start, n - 1))
        out: dict[int, Any] = {}
        if self.bcfg.entry_mode == "every_bar":
            for i in idxs:
                out[i] = _ControlSignal(i, self.bars[i])
            warnings.append(
                f"control run: entry on every bar ({len(out)} decisions) — this "
                "isolates the exit logic from the signal"
            )
            return out

        target = self.bcfg.random_entry_count
        if target <= 0:
            sset = sig_mod.generate(self.bars, self.ind, self.settings, self.scfg,
                                    warmup_index=self.res.warmup_index,
                                    cohort_curves=self.curves)
            target = max(1, len(sset.signals))
            self._control_signal_count = len(sset.signals)
            warnings.append(
                f"control run: {target} random entries matched to the {target} real "
                "signals, identical exit logic — if the strategy does not beat this, "
                "the signal has no edge"
            )
        rng = random.Random(self.bcfg.random_seed)
        picks = sorted(rng.sample(idxs, min(target, len(idxs)))) if idxs else []
        spaced: list[int] = []
        for p in picks:
            if spaced and p - spaced[-1] <= max(1, self.scfg.cooldown_bars):
                continue
            spaced.append(p)
        for i in spaced:
            out[i] = _ControlSignal(i, self.bars[i])
        return out

    # ------------------------------------------------------------------ #
    # entry
    # ------------------------------------------------------------------ #
    def _act_on_signal(self, s: Any, i: int, open_positions: list[Position],
                       all_positions: list[Position]) -> bool:
        """Market or limit entry, according to ``SignalConfig.entry_timing``."""
        bar = self.bars[i]
        decision_bar = self.bars[s.index]
        side = int(getattr(s, "side", 0)) or (decision_bar.direction or 1)
        if side == 0:
            self._block("no_direction")
            return False
        if self.scfg.entry_timing == "immediate" or isinstance(s, _ControlSignal):
            pos = self._open_position(s, i, bar.open, False)
            if pos is not None:
                open_positions.append(pos)
                all_positions.append(pos)
                return True
            return False

        # ---- rest a limit order at a retracement of the signal bar ----
        level = self._pullback_level(decision_bar, side)
        if level <= 0:
            self._block("invalid_pullback_level")
            return False
        plan = self.xmgr.plan(decision_bar, side, self.ind, s.index)
        self._pending.append(PendingOrder(
            signal=s, side=side, level=level, created_index=i,
            ttl=self.scfg.pullback_ttl_bars,
            maker=self.scfg.limit_entry_uses_maker_fee,
            stop_distance=plan.stop_distance))
        self._orders_emitted += 1
        # an order can fill on the very bar it is created
        self._service_pending(i, bar, open_positions, all_positions)
        return False

    def _pullback_level(self, decision_bar: Bar, side: int) -> float:
        """Where the limit order rests, measured on the *decision* bar only."""
        mode = self.scfg.pullback_mode
        if mode == "sigma":
            sigma = self.xmgr._sigma(decision_bar)
            return decision_bar.close - side * self.scfg.pullback_retrace_sigma * sigma
        if mode == "body":
            return decision_bar.close - side * self.scfg.pullback_body_frac * abs(
                decision_bar.body)
        if mode == "midpoint":
            return (decision_bar.high + decision_bar.low) / 2.0
        return decision_bar.open

    def _service_pending(self, i: int, bar: Bar, open_positions: list[Position],
                         all_positions: list[Position]) -> None:
        """Fill or expire resting orders against bar ``i``.

        A limit fills only if the bar actually traded through the level.  When the
        bar *opens* beyond it the fill is the open, which for a limit order is a
        price improvement — the one place where a gap helps rather than hurts.
        """
        if not self._pending:
            return
        still: list[PendingOrder] = []
        for od in self._pending:
            filled_price: float | None = None
            if od.side > 0:
                if bar.low <= od.level:
                    filled_price = min(bar.open, od.level)
            else:
                if bar.high >= od.level:
                    filled_price = max(bar.open, od.level)
            if filled_price is not None and filled_price > 0:
                self._orders_filled += 1
                pos = self._open_position(od.signal, i, filled_price, True,
                                          preset_stop_distance=od.stop_distance,
                                          maker=od.maker)
                if pos is not None:
                    open_positions.append(pos)
                    all_positions.append(pos)
                continue
            if od.expired(i):
                self._orders_expired += 1
                self._block("pullback_expired")
                continue
            # the thesis is invalidated if price runs away through the signal
            # bar's extreme: the retracement we were waiting for will not come
            sig_bar = self.bars[od.signal.index]
            ran_away = (bar.close > sig_bar.high) if od.side > 0 \
                else (bar.close < sig_bar.low)
            if ran_away:
                self._orders_invalidated += 1
                self._block("pullback_invalidated")
                continue
            still.append(od)
        self._pending = still

    def _open_position(self, s: Any, i: int, ref_price: float, is_limit: bool,
                       *, preset_stop_distance: float = 0.0,
                       maker: bool = False) -> Position | None:
        bar = self.bars[i]
        decision_bar = self.bars[s.index]
        self._entry_attempts += 1
        side = int(getattr(s, "side", 0)) or (decision_bar.direction or 1)
        if side == 0:
            self._block("no_direction")
            return None

        # geometry from the DECISION bar (causal), applied at the realised fill
        plan = self.xmgr.plan(decision_bar, side, self.ind, s.index)
        if plan.stop_distance <= EPS:
            self._block("degenerate_stop")
            return None

        ok, reason = self.rmgr.can_open(side, bar.ts, i, plan.stop_distance * 0)
        if not ok:
            self._block("risk_gate:" + reason)
            return None

        equity = self.rmgr.st.equity
        probe_notional = max(equity * self.rcfg.risk_per_trade_pct / 100.0, 1.0)
        if is_limit:
            # a resting limit is not a marketable order: no spread crossing.
            # Slippage is still modelled, but at a fraction, because queue
            # position means the fill can be missed rather than moved.
            fill_price = ref_price
        else:
            fill_price = self.rcfg.costs.slip_price(ref_price, side, probe_notional)
        if fill_price <= 0:
            self._block("invalid_fill_price")
            return None

        # stop distance was computed around the decision bar's close; re-anchor it
        # to the actual fill so 1R is the real cash risk, not the intended one
        stop_distance = preset_stop_distance or plan.stop_distance
        size = self.rmgr.size(fill_price, stop_distance, decision_bar, side=side)
        if size.rejected or size.qty <= 0:
            self._block("sizing:" + size.reason)
            return None

        qty = size.qty
        notional = qty * fill_price
        bps = (self.rcfg.costs.maker_bps if (maker and is_limit)
               else self.rcfg.costs.commission_bps)
        commission = abs(notional) * bps / 10_000.0
        slip_cash = qty * abs(fill_price - ref_price)

        tranches = [Tranche(r_multiple=t.r_multiple, share=t.share) for t in plan.tranches]
        pos = Position(
            side=side, entry_ts=bar.ts, entry_price=fill_price, qty=qty,
            initial_qty=qty, entry_index=i,
            entry_ref_price=ref_price,
            strategy=getattr(s, "strategy", "trend"),
            signal_score=getattr(s, "score", 0.0),
            category=decision_bar.category.value,
            initial_stop=fill_price - side * stop_distance,
            stop=fill_price - side * stop_distance,
            stop_distance=stop_distance,
            tranches=tranches,
            runner_target=(fill_price + side * self.xcfg.runner_target_sigma_mult
                           * self.xmgr._sigma(decision_bar))
            if self.xcfg.runner_has_hard_target else 0.0,
            entry_commission=commission,
            highest_since_entry=fill_price,
            lowest_since_entry=fill_price,
            risk_cash=size.risk_cash,
            targets=list(plan.targets),
        )
        # reference-price gross starts with the entry leg
        pos.gross_ref_pnl = -side * ref_price * qty
        pos.commission_paid = commission
        pos.entry_slippage = slip_cash
        pos.realised_pnl = -(commission + slip_cash)
        pos.fills.append(Fill(
            ts=bar.ts, price=fill_price, qty=side * qty, side=side, reason="entry",
            commission=commission, slippage=slip_cash, bar_index=i, minute_index=-1,
            note=f"score={pos.signal_score:.2f} sizing={size.binding_constraint} "
                 f"stop_mode={plan.components.get('mode')} capped={plan.capped or '-'}",
        ))
        # entry friction is charged once, here: gross_pnl is measured at the
        # reference price, so the slip between reference and fill is a real cost
        self.rmgr.credit(-(commission + slip_cash))
        self.rmgr.reserve(size.risk_cash)
        self.rmgr.st.trades_today += 1
        return pos

    # ------------------------------------------------------------------ #
    # bar processing
    # ------------------------------------------------------------------ #
    def _process_bar(self, pos: Position, bar: Bar, i: int) -> None:
        path = bar.minute_path if self.bcfg.use_intra_bar_path else None
        event_minute = (int(bar.tf * self.xcfg.event_check_elapsed)
                        if (path and self.xcfg.intra_bar_event_check) else -1)

        if path:
            # k is the 0-based minute INDEX (what a Fill records, and what a
            # consumer uses to look the minute up in bar.minute_path); the exit
            # manager wants the COUNT of minutes elapsed, which is k + 1.  Passing
            # the count as the index made the last minute of a 15-minute bar report
            # minute_index=15 — out of range, and off by one everywhere else.
            for k, m in enumerate(path):
                if not pos.open:
                    return
                self._minute_step(pos, m, i, k)
                if not pos.open:
                    return
                if k + 1 == event_minute and k + 1 >= 2:
                    if self._intra_bar_event(pos, bar, m, i, k, k + 1):
                        return
        else:
            self._bar_level_step(pos, bar, i)
            if not pos.open:
                return

        if not pos.open:
            return

        # ---- bar close: trailing, semantics, events, time ----
        dec = self.xmgr.on_bar(pos, self.bars, i, self.ind, curves=self.curves)
        if dec.action == "close_all":
            self._close(pos, bar.close, bar.close, bar.ts, i, dec.reason, 1.0,
                        note=dec.note)
            return
        if dec.action == "close_partial":
            self._reduce(pos, dec.share, bar.close, bar.close, bar.ts, i,
                         dec.reason, note=dec.note)
        elif dec.action == "tighten" and dec.new_stop is not None:
            pos.stop = dec.new_stop
            pos.stop_tightened_count += 1
            pos.events_seen.append(dec.reason)
        for e in dec.events:
            if e.name not in pos.events_seen:
                pos.events_seen.append(e.name)

    def _intra_bar_event(self, pos: Position, bar: Bar, m: MinuteBar, i: int,
                         k: int, elapsed: int) -> bool:
        """Mid-bar reversal check at ``event_check_elapsed`` of the bar.

        Returns True when the position closed.  The fill reference is that
        minute's close — the price actually observable at that moment.  ``k`` is
        the minute index recorded on the fill, ``elapsed`` the count of minutes
        elapsed, which is what the exit manager's partial-path window needs.
        """
        dec = self.xmgr.intra_bar_check(pos, bar, k, elapsed)
        if dec is None:
            return False
        ref = m.close
        if dec.action == "tighten" and dec.new_stop is not None:
            pos.stop = dec.new_stop
            pos.stop_tightened_count += 1
            pos.events_seen.append(dec.reason)
            return False
        if dec.action == "close_all":
            self._close(pos, ref, ref, m.ts, i, dec.reason, 1.0,
                        minute_index=k, note=dec.note)
            return True
        return False

    def _minute_step(self, pos: Position, m: MinuteBar, i: int, k: int) -> None:
        """Resolve one minute of the path against the position's levels."""
        side = pos.side
        stop = pos.stop
        probe = m.high if side > 0 else m.low
        adverse = m.low if side > 0 else m.high

        stop_in_range = (adverse <= stop) if side > 0 else (adverse >= stop)
        tgt_idx = self.xmgr.tranches_hit(pos, probe)

        # Both a stop and a target inside one minute: the order is unknowable.
        # ``adverse_first`` takes the pessimistic branch; the optimistic one is
        # available for sensitivity analysis and is flagged in the manifest.
        if stop_in_range and tgt_idx and self.bcfg.adverse_first:
            self._close(pos, self._stop_ref(pos, m), self._stop_fill(pos, m),
                        m.ts, i, "stop", 1.0, minute_index=k,
                        note="adverse_first: stop assumed before target in same minute")
            return

        if stop_in_range:
            self._close(pos, self._stop_ref(pos, m), self._stop_fill(pos, m),
                        m.ts, i, "stop", 1.0, minute_index=k)
            return

        for tidx in tgt_idx:
            if not pos.open:
                return
            t = pos.tranches[tidx]
            target = pos.entry_price + side * t.r_multiple * pos.stop_distance
            ref = target if not self._gap_target(pos, m.open, target) else m.open
            fill, maker = self._target_fill(pos, side, ref)
            share = safe_div(self.xmgr.tranche_qty(pos, tidx), pos.qty, 1.0)
            self._reduce(pos, clamp(share, 0.0, 1.0), ref, fill, m.ts, i,
                         f"tp{tidx + 1}", minute_index=k, maker=maker)
            t.filled = True
            t.fill_price = fill
            t.fill_ts = m.ts
            t.realised_r = t.r_multiple

        if pos.open and self.xmgr.runner_target_hit(pos, probe):
            rfill, rmaker = self._target_fill(pos, side, pos.runner_target)
            self._close(pos, pos.runner_target, rfill, m.ts, i, "runner_target",
                        1.0, minute_index=k, maker=rmaker)
            return

        pos.update_extremes(m.high, m.low)

    def _bar_level_step(self, pos: Position, bar: Bar, i: int) -> None:
        """Fallback when the minute path is unavailable (bar OHLC only)."""
        side = pos.side
        probe = bar.high if side > 0 else bar.low
        adverse = bar.low if side > 0 else bar.high
        stop_in = (adverse <= pos.stop) if side > 0 else (adverse >= pos.stop)
        tgt_idx = self.xmgr.tranches_hit(pos, probe)

        if stop_in:
            ref = bar.open if self._gap_stop(pos, bar.open) else pos.stop
            fill = self.rcfg.costs.slip_price(ref, -side, pos.qty * ref)
            note = ("adverse_first: stop assumed before target in same bar"
                    if (tgt_idx and self.bcfg.adverse_first) else "")
            self._close(pos, ref, fill, bar.ts, i, "stop", 1.0, note=note)
            return

        for tidx in tgt_idx:
            if not pos.open:
                return
            t = pos.tranches[tidx]
            target = pos.entry_price + side * t.r_multiple * pos.stop_distance
            ref = bar.open if self._gap_target(pos, bar.open, target) else target
            fill, maker = self._target_fill(pos, side, ref)
            share = safe_div(self.xmgr.tranche_qty(pos, tidx), pos.qty, 1.0)
            self._reduce(pos, clamp(share, 0.0, 1.0), ref, fill, bar.ts, i,
                         f"tp{tidx + 1}", maker=maker)
            t.filled = True
            t.fill_price = fill
            t.fill_ts = bar.ts
            t.realised_r = t.r_multiple

        pos.update_extremes(bar.high, bar.low)

    # ---- fill-price helpers ----
    def _gap_stop(self, pos: Position, open_price: float) -> bool:
        if not self.bcfg.honour_gaps:
            return False
        return open_price <= pos.stop if pos.side > 0 else open_price >= pos.stop

    def _gap_target(self, pos: Position, open_price: float, target: float) -> bool:
        if not self.bcfg.honour_gaps:
            return False
        return open_price >= target if pos.side > 0 else open_price <= target

    def _stop_ref(self, pos: Position, m: MinuteBar) -> float:
        """Reference price for a stop exit: the minute open if it gapped through."""
        return m.open if self._gap_stop(pos, m.open) else pos.stop

    def _stop_fill(self, pos: Position, m: MinuteBar) -> float:
        """A stop is a market order once triggered: it crosses the spread."""
        ref = self._stop_ref(pos, m)
        return self.rcfg.costs.slip_price(ref, -pos.side, pos.qty * ref)

    def _target_fill(self, pos: Position, side: int, ref: float) -> tuple[float, bool]:
        """Fill price and maker flag for a *target* leg.

        A take-profit level is a limit order that has been resting since entry,
        so when price touches it the fill is at the limit price (or better, at
        the open if the bar gapped through) and the leg earns the maker rate
        instead of crossing the spread.  Returning ``maker=False`` reproduces the
        conservative all-taker model when ``target_exits_are_maker`` is off.
        """
        if not self.bcfg.target_exits_are_maker:
            return self.rcfg.costs.slip_price(ref, -side, pos.qty * ref), False
        return ref, True

    # ------------------------------------------------------------------ #
    # position mutation
    # ------------------------------------------------------------------ #
    def _reduce(self, pos: Position, share: float, ref_price: float, fill_price: float,
                ts: int, i: int, reason: str, *, minute_index: int = -1,
                r_multiple: float | None = None, note: str = "",
                maker: bool = False) -> None:
        qty = pos.qty * clamp(share, 0.0, 1.0)
        if qty <= EPS or not pos.open:
            return
        notional = qty * fill_price
        commission = self.rcfg.costs.commission(notional, maker=maker)
        slip_cash = qty * abs(fill_price - ref_price)

        # Entry friction was already charged at open, so a reduction only carries
        # its own commission and slippage.  Allocating entry costs pro-rata here
        # as well would charge them twice.  A resting target leg passes
        # ``maker=True`` with ``fill_price == ref_price``, so it pays the maker
        # fee and no spread cost; an initiating leg pays taker + slippage.
        gross_ref = pos.side * (ref_price - pos.entry_ref_price) * qty
        net = gross_ref - commission - slip_cash

        pos.gross_ref_pnl += pos.side * ref_price * qty
        pos.realised_pnl += net
        pos.commission_paid += commission
        pos.slippage_paid += slip_cash
        pos.qty -= qty
        pos.fills.append(Fill(
            ts=ts, price=fill_price, qty=-pos.side * qty, side=pos.side,
            reason=reason, commission=commission, slippage=slip_cash,
            bar_index=i, minute_index=minute_index,
            r_multiple=r_multiple if r_multiple is not None else pos.r_of(fill_price),
            note=note,
        ))
        self.rmgr.credit(net)
        self.rmgr.release(pos.stop_distance * qty)
        if pos.qty <= EPS:
            self._finalise(pos, ts, i, reason)

    def _close(self, pos: Position, ref_price: float, fill_price: float, ts: int,
               i: int, reason: str, share: float, *, minute_index: int = -1,
               note: str = "", maker: bool = False) -> None:
        if not pos.open:
            return
        self._reduce(pos, share, ref_price, fill_price, ts, i, reason,
                     minute_index=minute_index, note=note, maker=maker)
        if pos.open and pos.qty <= EPS:
            self._finalise(pos, ts, i, reason)

    def _finalise(self, pos: Position, ts: int, i: int, reason: str) -> None:
        pos.open = False
        pos.exit_ts = ts
        pos.exit_reason = reason

        funding = self.rmgr.funding_for(
            pos.initial_qty * pos.entry_price, pos.bars_held, self.settings.timeframe)
        if funding:
            pos.funding_paid = funding
            pos.realised_pnl -= funding
            self.rmgr.credit(-funding)

        gross = pos.gross_ref_pnl            # entry leg was added at open
        slippage = pos.entry_slippage + pos.slippage_paid
        commission = pos.commission_paid
        costs = commission + funding + slippage
        net = pos.realised_pnl
        # the identity is checked, not assumed: a silent drift here means the
        # equity curve and the trade list disagree, which invalidates everything
        # downstream.  Recorded as a warning rather than raised so one bad trade
        # cannot destroy a long run.
        residual = abs((gross - costs) - net)
        if residual > 1e-6 * max(1.0, abs(gross)):
            self._accounting_errors.append(
                f"index {pos.entry_index}: gross-costs={gross - costs:.6f} "
                f"!= net={net:.6f} (residual {residual:.2e})")

        exit_qty = sum(abs(f.qty) for f in pos.fills if f.reason != "entry")
        exit_notional = sum(abs(f.qty) * f.price for f in pos.fills if f.reason != "entry")
        avg_exit = safe_div(exit_notional, exit_qty, pos.entry_price)

        tr = Trade(
            side=pos.side, strategy=pos.strategy, category=pos.category,
            signal_score=pos.signal_score, entry_ts=pos.entry_ts, exit_ts=ts,
            entry_price=pos.entry_price, avg_exit_price=avg_exit,
            qty=pos.initial_qty, notional=pos.initial_qty * pos.entry_price,
            gross_pnl=gross, commission_cost=commission, funding_cost=funding,
            slippage_cost=slippage, costs=costs, net_pnl=net,
            r_multiple=safe_div(net, pos.risk_cash, 0.0),
            risk_cash=pos.risk_cash, peak_r=pos.peak_r, trough_r=pos.trough_r,
            bars_held=pos.bars_held, exit_reason=reason,
            tranches_filled=sum(1 for t in pos.tranches if t.filled),
            events_seen=list(pos.events_seen),
            stop_tightened=pos.stop_tightened_count,
            entry_index=pos.entry_index, exit_index=i,
            equity_after=self.rmgr.st.equity,
            drawdown_after=self.rmgr.st.drawdown,
        )
        self._trades.append(tr)
        # behavioural gates only — money was already moved by ``credit``
        self.rmgr.record_trade(net, i, ts)

    def _block(self, reason: str) -> None:
        self._entry_blocks[reason] = self._entry_blocks.get(reason, 0) + 1

    # ------------------------------------------------------------------ #
    def _exit_counts(self, trades: Sequence[Trade]) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in trades:
            out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def _benchmark(self, final_equity: float) -> dict[str, Any]:
        bars = self.bars[self.res.warmup_index:]
        if not bars:
            return {}
        p0, p1 = bars[0].open, bars[-1].close
        eq0 = self.rcfg.initial_equity
        bh_qty = eq0 / p0 if p0 > 0 else 0.0
        bh_pnl = bh_qty * (p1 - p0)
        rets = [safe_div(bars[k].close - bars[k - 1].close, bars[k - 1].close, 0.0)
                for k in range(1, len(bars))]
        mu = mean(rets)
        var = safe_div(sum((r - mu) ** 2 for r in rets), max(1, len(rets) - 1), 0.0)
        return {
            "buy_and_hold": {
                "entry_price": p0, "exit_price": p1,
                "return_pct": safe_div(p1 - p0, p0, 0.0) * 100.0,
                "final_equity": eq0 + bh_pnl,
                "pnl": bh_pnl,
                "bar_return_mean": mu,
                "bar_return_stdev": var ** 0.5,
                "max_drawdown": _max_drawdown([eq0 + bh_qty * (b.close - p0) for b in bars]),
            },
            "strategy_return_pct": safe_div(final_equity - eq0, eq0, 0.0) * 100.0,
            "strategy_final_equity": final_equity,
            "entry_mode": self.bcfg.entry_mode,
        }

    def _manifest(self, final_equity: float, warnings: Sequence[str]) -> dict[str, Any]:
        from dataclasses import asdict, fields

        def shallow(o: Any) -> dict[str, Any]:
            try:
                return {f.name: getattr(o, f.name) for f in fields(o)}
            except TypeError:                                  # pragma: no cover
                return {"repr": repr(o)}

        blob = json.dumps({
            "signal": self.scfg.config_hash(),
            "risk": shallow(self.rcfg),
            "exit": shallow(self.xcfg),
            "backtest": shallow(self.bcfg),
            "settings": self.settings.to_dict(),
        }, sort_keys=True, default=str)
        bars = self.bars
        return {
            "config_hash": hashlib.sha256(blob.encode()).hexdigest()[:16],
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "engine_version": "0.2.0",
            "timeframe": self.settings.timeframe,
            "bars": len(bars),
            "bars_traded": max(0, len(bars) - self.res.warmup_index),
            "first_ts": bars[0].ts,
            "last_ts": bars[-1].ts,
            "days": (bars[-1].ts - bars[0].ts) / 86_400_000.0,
            "initial_equity": self.rcfg.initial_equity,
            "final_equity": final_equity,
            "n_trades": len(self._trades),
            "entry_mode": self.bcfg.entry_mode,
            "intra_bar_path": self.bcfg.use_intra_bar_path,
            "adverse_first": self.bcfg.adverse_first,
            "honour_gaps": self.bcfg.honour_gaps,
            "reference_mode": self.settings.reference_mode,
            "timing_mode": self.settings.timing_mode,
            # the guard's own error message promises this is recorded, and a result
            # that cannot say whether it peeked cannot be trusted or reproduced
            "allow_lookahead": self.bcfg.allow_lookahead,
            "lookahead_flags": self._lookahead_flags,
            "target_exits_are_maker": self.bcfg.target_exits_are_maker,
            "close_open_at_end": self.bcfg.close_open_at_end,
            "periods_per_year": self.rcfg.periods_per_year,
            "warnings": list(warnings),
        }


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = -1e18
    dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd


# --------------------------------------------------------------------------- #
# convenience entry points
# --------------------------------------------------------------------------- #
def run_backtest(res: PipelineResult, *,
                 signal_cfg: sig_mod.SignalConfig | None = None,
                 risk_cfg: RiskConfig | None = None,
                 exit_cfg: ExitConfig | None = None,
                 bt_cfg: BacktestConfig | None = None,
                 cohort_curves: dict[str, list[PathPoint]] | None = None) -> BacktestResult:
    bt = Backtester(res, signal_cfg=signal_cfg, risk_cfg=risk_cfg,
                    exit_cfg=exit_cfg, bt_cfg=bt_cfg, cohort_curves=cohort_curves)
    out = bt.run()
    out.signals = getattr(bt, "_signals", out.signals)
    return out


def random_control(res: PipelineResult, *, n: int = 0, seed: int = 20260913,
                   risk_cfg: RiskConfig | None = None,
                   exit_cfg: ExitConfig | None = None,
                   signal_cfg: sig_mod.SignalConfig | None = None) -> BacktestResult:
    """Same exits, random entries.  The honest test of whether the *signal* works."""
    return run_backtest(res, signal_cfg=signal_cfg, risk_cfg=risk_cfg,
                        exit_cfg=exit_cfg,
                        bt_cfg=BacktestConfig(entry_mode="random", random_seed=seed,
                                              random_entry_count=n))


def every_bar_control(res: PipelineResult, *,
                      risk_cfg: RiskConfig | None = None,
                      exit_cfg: ExitConfig | None = None,
                      signal_cfg: sig_mod.SignalConfig | None = None) -> BacktestResult:
    """Same exits, entry on every tradable bar.  The 'no selection at all' floor."""
    return run_backtest(res, signal_cfg=signal_cfg, risk_cfg=risk_cfg,
                        exit_cfg=exit_cfg,
                        bt_cfg=BacktestConfig(entry_mode="every_bar"))
