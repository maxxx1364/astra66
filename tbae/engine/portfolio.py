"""Portfolio objects shared by risk, exits and the backtester.

Kept in their own module so that ``risk`` and ``exits`` can type against
:class:`Position` without importing the backtester (which imports both) — that
cycle is how strategy codebases end up with one 3000-line file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .mathx import safe_div


@dataclass(slots=True)
class Fill:
    """One executed order leg."""

    ts: int
    price: float
    qty: float                 # signed: +ve buys, -ve sells
    side: int                  # trade side this fill belongs to (1 long / -1 short)
    reason: str                # entry | tp1 | tp2 | stop | trail | event | time | flatten
    commission: float = 0.0
    slippage: float = 0.0
    bar_index: int = -1
    minute_index: int = -1     # -1 = filled at a bar boundary (open/close)
    r_multiple: float = 0.0    # realised R at the moment of the fill
    note: str = ""

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.price

    @property
    def cost(self) -> float:
        """Commission (deducted from cash) + slippage (embedded in ``price``).

        Both are real costs of the fill; they are accounted once at the trade
        level, never both here and there.
        """
        return self.commission + self.slippage

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "price": self.price, "qty": self.qty, "side": self.side,
            "reason": self.reason, "commission": self.commission, "slippage": self.slippage,
            "bar_index": self.bar_index, "minute_index": self.minute_index,
            "r_multiple": self.r_multiple, "notional": self.notional, "cost": self.cost,
            "note": self.note,
        }


@dataclass(slots=True)
class Tranche:
    """One staged-exit leg: a target R-multiple and the share it closes."""

    r_multiple: float          # 0.0 => runner (no fixed target)
    share: float               # fraction of the *remaining* position
    filled: bool = False
    fill_price: float = 0.0
    fill_ts: int = 0
    realised_r: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "r_multiple": self.r_multiple, "share": self.share, "filled": self.filled,
            "fill_price": self.fill_price, "fill_ts": self.fill_ts,
            "realised_r": self.realised_r,
        }


@dataclass(slots=True)
class Position:
    """An open (or just-closed) position, with everything needed to manage it."""

    side: int
    entry_ts: int
    entry_price: float               # actual fill (reference + slippage)
    qty: float                       # absolute quantity still open
    initial_qty: float
    entry_index: int
    #: the level the decision was made at (bar open), before slippage.
    #: ``gross_pnl`` is measured against reference prices so commission and
    #: slippage can be itemised instead of being buried in one number.
    entry_ref_price: float = 0.0
    gross_ref_pnl: float = 0.0       # P&L at reference prices
    commission_paid: float = 0.0
    #: exit slippage only; entry slippage is charged once, up front
    slippage_paid: float = 0.0
    entry_slippage: float = 0.0
    funding_paid: float = 0.0
    strategy: str = "trend"
    signal_score: float = 0.0
    category: str = ""

    # risk geometry, all in price units
    initial_stop: float = 0.0
    stop: float = 0.0                # current (possibly trailed) stop
    stop_distance: float = 0.0       # |entry - initial_stop| = 1R
    targets: list[float] = field(default_factory=list)
    tranches: list[Tranche] = field(default_factory=list)

    # state
    open: bool = True
    entry_commission: float = 0.0
    exit_ts: int = 0
    exit_reason: str = ""
    fills: list[Fill] = field(default_factory=list)
    realised_pnl: float = 0.0        # cash, costs included
    bars_held: int = 0
    peak_r: float = 0.0              # max favourable excursion, in R
    trough_r: float = 0.0            # max adverse excursion, in R (negative)
    highest_since_entry: float = 0.0
    lowest_since_entry: float = 0.0
    stop_tightened_count: int = 0
    stop_widened_count: int = 0
    events_seen: list[str] = field(default_factory=list)
    be_moved: bool = False
    runner_target: float = 0.0
    #: cash at risk if the initial stop is hit (the denominator of every
    #: R-multiple in the system).  Set by ``risk.RiskManager`` at entry.
    risk_cash: float = 0.0

    # ---- R maths ----
    def r_of(self, price: float) -> float:
        """Signed profit of ``price`` in units of the initial risk (1R)."""
        if self.stop_distance <= 0:
            return 0.0
        return self.side * (price - self.entry_price) / self.stop_distance

    def unrealised_r(self, price: float) -> float:
        return self.r_of(price)

    def qty_share_open(self) -> float:
        return safe_div(self.qty, self.initial_qty, 0.0)

    def update_extremes(self, high: float, low: float) -> None:
        self.highest_since_entry = max(self.highest_since_entry, high)
        self.lowest_since_entry = min(self.lowest_since_entry, low) if self.lowest_since_entry else low
        self.peak_r = max(self.peak_r, self.r_of(self.highest_since_entry))
        self.trough_r = min(self.trough_r, self.r_of(self.lowest_since_entry))

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side, "strategy": self.strategy, "category": self.category,
            "signal_score": self.signal_score,
            "entry_ts": self.entry_ts, "entry_price": self.entry_price,
            "exit_ts": self.exit_ts, "exit_reason": self.exit_reason,
            "initial_qty": self.initial_qty, "qty": self.qty,
            "entry_ref_price": self.entry_ref_price,
            "gross_ref_pnl": self.gross_ref_pnl,
            "commission_paid": self.commission_paid,
            "slippage_paid": self.slippage_paid,
            "funding_paid": self.funding_paid,
            "initial_stop": self.initial_stop, "final_stop": self.stop,
            "stop_distance": self.stop_distance, "targets": self.targets,
            "runner_target": self.runner_target,
            "realised_pnl": self.realised_pnl,
            "risk_cash": self.risk_cash,
            "r_multiple": safe_div(self.realised_pnl, self.risk_cash, 0.0),
            "bars_held": self.bars_held, "peak_r": self.peak_r, "trough_r": self.trough_r,
            "stop_tightened_count": self.stop_tightened_count,
            "stop_widened_count": self.stop_widened_count,
            "be_moved": self.be_moved, "events_seen": self.events_seen,
            "fills": [f.to_dict() for f in self.fills],
            "tranches": [t.to_dict() for t in self.tranches],
            "entry_index": self.entry_index,
            "open": self.open,
        }


@dataclass(slots=True)
class Trade:
    """A closed round trip — the unit every statistic in ``metrics`` is built on."""

    side: int
    strategy: str
    category: str
    signal_score: float
    entry_ts: int
    exit_ts: int
    entry_price: float
    avg_exit_price: float
    qty: float
    notional: float
    #: P&L at *reference* prices (entry at the bar open, exits at the stop /
    #: target / close level), before any friction.
    gross_pnl: float
    #: commissions actually deducted
    commission_cost: float
    #: funding actually deducted
    funding_cost: float
    #: price impact vs the reference levels.  ``gross_pnl`` is measured at
    #: *reference* prices, so this IS deducted — exactly once.  (The identity
    #: ``net == gross - costs`` is asserted in ``tests/test_backtest.py``.)
    slippage_cost: float
    #: total friction actually deducted: commission + funding + slippage
    costs: float
    net_pnl: float
    r_multiple: float              # net PnL / initial cash risk
    risk_cash: float
    peak_r: float
    trough_r: float
    bars_held: int
    exit_reason: str
    tranches_filled: int
    events_seen: list[str]
    stop_tightened: int
    entry_index: int
    exit_index: int
    equity_after: float = 0.0
    drawdown_after: float = 0.0

    @property
    def win(self) -> bool:
        return self.net_pnl > 0

    @property
    def total_friction(self) -> float:
        """Everything the trade paid.  Equals ``costs`` by construction."""
        return self.costs

    @property
    def friction_bp(self) -> float:
        """Total friction in basis points of entry notional."""
        return safe_div(self.total_friction, self.notional, 0.0) * 10_000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side, "strategy": self.strategy, "category": self.category,
            "signal_score": self.signal_score, "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts, "entry_price": self.entry_price,
            "avg_exit_price": self.avg_exit_price, "qty": self.qty,
            "notional": self.notional, "gross_pnl": self.gross_pnl,
            "commission_cost": self.commission_cost,
            "funding_cost": self.funding_cost,
            "slippage_cost": self.slippage_cost,
            "costs": self.costs,
            "total_friction": self.total_friction,
            "net_pnl": self.net_pnl,
            "r_multiple": self.r_multiple, "risk_cash": self.risk_cash,
            "peak_r": self.peak_r, "trough_r": self.trough_r,
            "bars_held": self.bars_held, "exit_reason": self.exit_reason,
            "tranches_filled": self.tranches_filled, "events_seen": self.events_seen,
            "stop_tightened": self.stop_tightened, "win": self.win,
            "entry_index": self.entry_index, "exit_index": self.exit_index,
            "equity_after": self.equity_after, "drawdown_after": self.drawdown_after,
        }


@dataclass(slots=True)
class EquityPoint:
    """One sample of the equity curve, marked to market."""

    ts: int
    index: int
    equity: float
    cash: float
    drawdown: float          # fraction below the running peak (>= 0)
    open_positions: int
    open_risk: float         # sum of cash-at-risk of open positions
    mark_price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "index": self.index, "equity": self.equity,
            "cash": self.cash, "drawdown": self.drawdown,
            "open_positions": self.open_positions, "open_risk": self.open_risk,
        }
