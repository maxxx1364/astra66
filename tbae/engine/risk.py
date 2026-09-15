"""Risk management: sizing, budget, limits, kill-switch, and the cost model.

The organising principle
------------------------
Position size is the **minimum of four independent constraints**, never a single
formula:

1. *loss budget* — ``equity × risk_per_trade_pct / stop_distance``.  This is the
   one that guarantees a stop-out costs what you decided it should cost.
2. *volatility target* — scale exposure so the position contributes a target
   share of annualised volatility.  Keeps risk comparable across regimes.
3. *leverage / notional cap* — ``max_leverage``, ``max_position_pct_equity``.
4. *portfolio budget* — total cash-at-risk across open positions, trades today,
   daily loss limit, drawdown kill-switch.

Taking the minimum matters: a vol-target formula alone will happily lever up in a
quiet market right before a gap, and a fixed-fractional formula alone will take
the same size into a 4-sigma regime as into a 0.4-sigma one.

Sizing uses ``sigma_atr`` (the *smoothed* intra-candle sigma), not the raw
per-bar sigma.  Raw sigma contains the current bar's own spike, so sizing on it
means a volatility burst shrinks the position one bar too late and then the next
bar — now calm — sizes up into whatever caused the burst.

The cost model is not decoration
--------------------------------
``commission + slippage + sqrt-impact`` is applied to *every* fill, including
each tranche of a staged exit.  A staged exit pays the entry commission once and
the exit commission on every leg, so splitting into three tranches costs roughly
2x the commission of a single exit.  If the backtester ignored that, staged exits
would look strictly better than they are — which is exactly the kind of
self-deception this module exists to prevent.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .mathx import EPS, clamp, mean, round_lot, safe_div
from .models import Bar
from .portfolio import Trade


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CostConfig:
    """Trading costs, in basis points unless stated otherwise."""

    commission_bps: float = 4.0        # taker fee, per side
    maker_bps: float = 1.0             # resting legs: pullback entries and TP limits
    slippage_bps: float = 2.0          # fixed half-spread + queue displacement
    impact_coeff: float = 0.10         # sqrt-impact: bps = coeff * sqrt(notional / adv)
    adv_notional: float = 2.0e8        # average daily traded notional of the venue
    funding_bps_per_day: float = 0.0   # perp funding, charged on notional per day held
    min_ticket_fee: float = 0.0

    def validate(self) -> "CostConfig":
        for name in ("commission_bps", "maker_bps", "slippage_bps", "impact_coeff"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.adv_notional <= 0:
            raise ValueError("adv_notional must be > 0")
        return self

    def impact_bps(self, notional: float) -> float:
        """Square-root market impact.  The sqrt law (not linear) is the empirical
        standard: doubling size does not double impact."""
        if notional <= 0:
            return 0.0
        return self.impact_coeff * math.sqrt(notional / self.adv_notional) * 10_000.0

    def exit_bps(self, notional: float, maker: bool = False) -> float:
        """All-in cost of one exit leg, in bp of notional.

        A maker exit (a resting take-profit limit) pays the maker fee and no
        spread/impact, so it is roughly a quarter of the taker cost.  Modelling
        that distinction matters: with three taker exit legs per trade, friction
        alone was measured at 0.22R — larger than the strategy's entire gross
        edge — while the same trades cost 0.13R when the target legs rest.
        """
        if maker:
            return self.maker_bps
        return self.commission_bps + self.slippage_bps + self.impact_bps(notional)

    def entry_bps(self, notional: float, maker: bool = False) -> float:
        return self.exit_bps(notional, maker=maker)

    def slip_price(self, price: float, aggressor_side: int, notional: float) -> float:
        """Worst-case fill price: a buy fills higher, a sell fills lower."""
        bps = self.slippage_bps + self.impact_bps(notional)
        return price * (1.0 + aggressor_side * bps / 10_000.0)

    def commission(self, notional: float, maker: bool = False) -> float:
        """Fee for one fill.

        ``maker=True`` is for a *resting* order (a pullback entry limit, or a
        take-profit limit already sitting in the book): it earns the maker rebate
        rate and, because it does not cross the spread, it takes no slippage
        either.  Everything that initiates — stops, market exits, event exits —
        is a taker fill.
        """
        bps = self.maker_bps if maker else self.commission_bps
        c = abs(notional) * bps / 10_000.0
        return max(c, self.min_ticket_fee)


@dataclass(slots=True)
class RiskConfig:
    initial_equity: float = 100_000.0
    risk_per_trade_pct: float = 0.75      # % of equity lost if the initial stop hits

    #: ``fixed_fractional`` | ``vol_target`` | ``kelly_capped``
    sizing_mode: str = "risk_and_vol"     # min(loss budget, vol target) — default
    vol_target_annual_pct: float = 30.0
    periods_per_year: float = 35_040.0    # 15m bars in a 365.25-day year
    kelly_fraction: float = 0.25
    kelly_min_trades: int = 30

    max_leverage: float = 3.0
    max_position_pct_equity: float = 60.0
    lot_step: float = 0.0                 # 0 = no rounding
    qty_precision: int = 8
    min_notional: float = 10.0

    # ---- portfolio-level budget ----
    #: Portfolio-level budget.  For the *percentage* limits below, **0 disables
    #: that gate** — it never means "trigger at zero", which for a drawdown or
    #: loss limit would halt on the very first entry.  The *count* caps
    #: (``max_open_positions``, ``max_trades_per_day``) must be >= 1, because a
    #: zero there is ambiguous between "no trading" and "unlimited".
    max_open_positions: int = 1
    max_total_risk_pct: float = 2.5       # sum(open cash risk) / equity
    max_trades_per_day: int = 12
    daily_loss_limit_pct: float = 3.0
    max_drawdown_kill_pct: float = 18.0
    max_consecutive_losses: int = 6
    halt_cooldown_bars: int = 24          # bars to sit out after a soft halt

    # ---- risk ramp: start small, earn full size ----
    ramp_enabled: bool = True
    ramp_start_fraction: float = 0.5
    ramp_full_after_trades: int = 20

    allow_short: bool = True
    costs: CostConfig = field(default_factory=CostConfig)

    def validate(self) -> "RiskConfig":
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be > 0")
        if not 0.0 < self.risk_per_trade_pct <= 10.0:
            raise ValueError("risk_per_trade_pct must be in (0, 10]")
        if self.sizing_mode not in ("fixed_fractional", "vol_target", "risk_and_vol", "kelly_capped"):
            raise ValueError(f"unknown sizing_mode {self.sizing_mode!r}")
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be > 0")
        if not 0.0 < self.max_position_pct_equity <= 1000.0:
            raise ValueError("max_position_pct_equity must be in (0, 1000]")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ValueError("kelly_fraction must be in (0, 1]")
        if not 0.0 < self.ramp_start_fraction <= 1.0:
            raise ValueError("ramp_start_fraction must be in (0, 1]")
        # 0 disables the gate; a negative value is a typo, not a policy
        for name in ("max_total_risk_pct", "daily_loss_limit_pct",
                     "max_drawdown_kill_pct"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (0 disables the gate)")
        for name in ("max_consecutive_losses", "halt_cooldown_bars",
                     "ramp_full_after_trades"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (0 disables the gate)")
        if self.max_trades_per_day < 1:
            # Unlike the percentage limits, a *count* cap has no sensible zero:
            # 0 would read both as "no trading" and as "unlimited".  Require >= 1
            # and let a caller who wants no practical cap pass a large number.
            raise ValueError("max_trades_per_day must be >= 1")
        self.costs.validate()
        return self


@dataclass(slots=True)
class SizeDecision:
    qty: float = 0.0
    notional: float = 0.0
    risk_cash: float = 0.0
    stop_distance: float = 0.0
    leverage: float = 0.0
    position_pct_equity: float = 0.0
    binding_constraint: str = ""
    rejected: bool = False
    reason: str = ""
    ramp_fraction: float = 1.0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qty": self.qty, "notional": self.notional, "risk_cash": self.risk_cash,
            "stop_distance": self.stop_distance, "leverage": self.leverage,
            "position_pct_equity": self.position_pct_equity,
            "binding_constraint": self.binding_constraint, "rejected": self.rejected,
            "reason": self.reason, "ramp_fraction": self.ramp_fraction,
            "detail": self.detail,
        }


@dataclass(slots=True)
class RiskState:
    equity: float = 0.0
    cash: float = 0.0
    peak_equity: float = 0.0
    day_key: int = -1
    day_start_equity: float = 0.0
    day_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    total_trades: int = 0
    wins: int = 0
    realised_pnl: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    halt_until_index: int = -1
    open_risk: float = 0.0
    open_positions: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #
class RiskManager:
    """Stateful gatekeeper.  The backtester asks it two questions per bar:
    *may I open?*, and *how big?*  It never decides direction."""

    def __init__(self, cfg: RiskConfig | None = None) -> None:
        self.cfg = (cfg or RiskConfig()).validate()
        self.st = RiskState(
            equity=self.cfg.initial_equity,
            cash=self.cfg.initial_equity,
            peak_equity=self.cfg.initial_equity,
            day_start_equity=self.cfg.initial_equity,
        )
        self._kelly: float | None = None

    # ---- calendar / day rollover ----
    def roll_day(self, ts_ms: int, index: int) -> None:
        day = _dt.datetime.fromtimestamp(ts_ms / 1000.0, _dt.timezone.utc).toordinal()
        if day != self.st.day_key:
            self.st.day_key = day
            self.st.day_start_equity = self.st.equity
            self.st.day_pnl = 0.0
            self.st.trades_today = 0
            # a daily-loss halt expires with the day; a drawdown halt does not
            if self.st.halted and self.st.halt_reason == "daily_loss_limit":
                self.st.halted = False
                self.st.halt_reason = ""

    # ---- entry gate ----
    def can_open(self, side: int, ts_ms: int, index: int,
                 extra_risk_cash: float = 0.0) -> tuple[bool, str]:
        c, st = self.cfg, self.st
        self.roll_day(ts_ms, index)

        if st.halted and st.halt_until_index > index:
            return (False, f"halted:{st.halt_reason}")
        if st.halted and st.halt_reason in ("max_drawdown",):
            # the drawdown kill-switch is permanent: only a human resets it
            return (False, f"halted:{st.halt_reason}")
        if st.halted:
            st.halted = False
            st.halt_reason = ""
            # The cooldown has been served, so the streak counter must clear with
            # it.  Leaving it at the threshold made the halt self-retriggering:
            # every subsequent entry was vetoed until a win occurred, which turned
            # "sit out 24 bars" into "stop trading for the rest of the backtest".
            st.consecutive_losses = 0

        if side == -1 and not c.allow_short:
            return (False, "shorting_disabled")
        if st.open_positions >= c.max_open_positions:
            return (False, "max_open_positions")
        if st.trades_today >= c.max_trades_per_day:
            return (False, "max_trades_per_day")
        # A non-positive limit means "this gate is disabled", never "trigger at
        # zero": with max_drawdown_kill_pct=0 the comparison `dd >= 0` is true for
        # a flat account, so the kill switch would fire on the first entry and the
        # strategy would silently never trade.
        if (c.daily_loss_limit_pct > 0
                and st.day_pnl <= -(c.daily_loss_limit_pct / 100.0) * st.day_start_equity):
            self._halt("daily_loss_limit", index, until=index + 10**9)
            return (False, "daily_loss_limit")
        if (c.max_drawdown_kill_pct > 0
                and st.drawdown * 100.0 >= c.max_drawdown_kill_pct):
            self._halt("max_drawdown", index, until=10**12)
            return (False, f"max_drawdown:{st.drawdown * 100:.1f}%")
        if (c.max_consecutive_losses > 0
                and st.consecutive_losses >= c.max_consecutive_losses):
            self._halt("consecutive_losses", index,
                       until=index + c.halt_cooldown_bars)
            return (False, f"consecutive_losses:{st.consecutive_losses}")
        if c.max_total_risk_pct > 0:
            budget = (c.max_total_risk_pct / 100.0) * st.equity
            if st.open_risk + extra_risk_cash > budget + EPS:
                return (False, "risk_budget_exhausted")
        return (True, "ok")

    def _halt(self, reason: str, index: int, until: int) -> None:
        if not self.st.halted:
            self.st.events.append(
                {"index": index, "type": "halt", "reason": reason, "equity": self.st.equity}
            )
        self.st.halted = True
        self.st.halt_reason = reason
        self.st.halt_until_index = until

    # ---- ramp ----
    def ramp_fraction(self) -> float:
        c = self.cfg
        if not c.ramp_enabled:
            return 1.0
        n = self.st.total_trades
        if n >= c.ramp_full_after_trades:
            return 1.0
        frac = c.ramp_start_fraction + (1.0 - c.ramp_start_fraction) * (
            n / max(1, c.ramp_full_after_trades)
        )
        return clamp(frac, c.ramp_start_fraction, 1.0)

    # ---- sizing ----
    def size(self, price: float, stop_distance: float, bar: Bar | None = None,
             *, side: int = 1, sigma_override: float | None = None) -> SizeDecision:
        """Return the position size, or a rejected decision with the reason."""
        c, st = self.cfg, self.st
        d = SizeDecision(stop_distance=stop_distance)

        if price <= 0:
            d.rejected, d.reason = True, "invalid_price"
            return d
        if stop_distance <= EPS:
            d.rejected, d.reason = True, "zero_stop_distance"
            return d

        ramp = self.ramp_fraction()
        d.ramp_fraction = ramp
        risk_pct = c.risk_per_trade_pct * ramp
        loss_budget_qty = (st.equity * risk_pct / 100.0) / stop_distance

        # volatility-target quantity
        sigma = sigma_override
        if sigma is None and bar is not None:
            sigma = bar.sigma_atr if bar.sigma_atr > 0 else bar.sigma
        vol_qty = math.inf
        if sigma and sigma > 0 and c.sizing_mode in ("vol_target", "risk_and_vol"):
            per_bar = sigma / price
            ann = per_bar * math.sqrt(max(c.periods_per_year, 1.0))
            if ann > EPS:
                target_weight = (c.vol_target_annual_pct / 100.0) / ann
                vol_qty = (target_weight * st.equity) / price

        # hard caps
        lev_qty = (c.max_leverage * st.equity) / price
        pos_qty = (c.max_position_pct_equity / 100.0 * st.equity) / price

        if c.sizing_mode == "fixed_fractional":
            candidates = {"loss_budget": loss_budget_qty, "leverage": lev_qty,
                          "position_cap": pos_qty}
        elif c.sizing_mode == "vol_target":
            candidates = {"vol_target": vol_qty, "leverage": lev_qty,
                          "position_cap": pos_qty}
        elif c.sizing_mode == "kelly_capped":
            k = self.kelly_risk_pct()
            loss_budget_qty = (st.equity * (k * ramp) / 100.0) / stop_distance
            risk_pct = k * ramp
            candidates = {"kelly": loss_budget_qty, "leverage": lev_qty,
                          "position_cap": pos_qty}
        else:  # risk_and_vol (default)
            candidates = {"loss_budget": loss_budget_qty, "vol_target": vol_qty,
                          "leverage": lev_qty, "position_cap": pos_qty}

        binding = min(candidates, key=lambda k: candidates[k])
        qty = candidates[binding]
        if not math.isfinite(qty) or qty <= 0:
            d.rejected, d.reason = True, "non_positive_size"
            return d

        # risk-budget ceiling: never let this trade push total open risk over budget
        budget_left = (c.max_total_risk_pct / 100.0) * st.equity - st.open_risk
        max_by_budget = budget_left / stop_distance if stop_distance > 0 else 0.0
        if max_by_budget <= EPS:
            d.rejected, d.reason = True, "risk_budget_exhausted"
            return d
        if qty > max_by_budget:
            qty, binding = max_by_budget, "portfolio_risk_budget"

        if c.lot_step > 0:
            qty = round_lot(qty, c.lot_step)
        qty = round(qty, c.qty_precision)
        notional = qty * price
        if notional < c.min_notional:
            d.rejected, d.reason = True, "below_min_notional"
            d.detail = {"notional": notional, "min_notional": c.min_notional}
            return d

        d.qty = qty
        d.notional = notional
        d.risk_cash = qty * stop_distance
        d.leverage = safe_div(notional, st.equity, 0.0)
        d.position_pct_equity = d.leverage * 100.0
        d.binding_constraint = binding
        d.reason = "ok"
        d.detail = {
            "risk_pct_used": risk_pct,
            "candidates": {k: (None if not math.isfinite(v) else v) for k, v in candidates.items()},
            "sigma_used": sigma or 0.0,
            "equity": st.equity,
        }
        return d

    # ---- Kelly ----
    def kelly_risk_pct(self, trades: Sequence[Trade] | None = None) -> float:
        """Fractional-Kelly risk percentage estimated from realised R-multiples.

        ``f* = p - (1-p)/b`` with ``p`` the win rate and ``b`` the payoff ratio.
        We use a fraction (default 0.25) because the inputs are estimated from a
        small sample: full Kelly on noisy ``p``/``b`` is a reliable way to
        over-bet, and over-betting is punished super-linearly.
        """
        c = self.cfg
        base = c.risk_per_trade_pct
        if trades is None:
            trades = getattr(self, "_trades", [])
        if len(trades) < c.kelly_min_trades:
            self._kelly = base
            return base
        rs = [t.r_multiple for t in trades]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        if not wins or not losses:
            self._kelly = base
            return base
        p = len(wins) / len(rs)
        b = safe_div(mean(wins), abs(mean(losses)), 0.0)
        if b <= EPS:
            self._kelly = 0.0
            return 0.0
        f = p - (1.0 - p) / b
        f = max(0.0, f) * c.kelly_fraction
        # never let Kelly exceed 3x the configured risk, nor go to zero
        self._kelly = clamp(f * 100.0, 0.05, base * 3.0)
        return self._kelly

    # ---- state updates ----
    def reserve(self, risk_cash: float) -> None:
        self.st.open_risk += risk_cash
        self.st.open_positions += 1

    def release(self, risk_cash: float) -> None:
        self.st.open_risk = max(0.0, self.st.open_risk - risk_cash)
        self.st.open_positions = max(0, self.st.open_positions - 1)

    def credit(self, amount: float) -> None:
        """Add realised cash.  Called per *fill* (so partial exits land immediately).

        ``equity`` is deliberately NOT touched here: the backtester recomputes
        ``equity = cash + unrealised`` once per bar via :meth:`mark`.  Mutating
        both in two places is how accounting drifts by a few basis points per
        trade and nobody notices until the equity curve disagrees with the sum of
        the trade list.
        """
        self.st.cash += amount
        self.st.realised_pnl += amount

    def record_trade(self, net_pnl: float, index: int, ts_ms: int) -> None:
        """Update *statistical* state after a round trip closes.

        Separate from :meth:`credit` on purpose: this one drives the behavioural
        gates (consecutive losses, daily loss) and must never move money, or a
        partially-exited position would trip the daily limit several times for one
        trade.

        ``trades_today`` is deliberately *not* incremented here: the daily trade
        cap should count positions **taken**, and a trade only reaches this method
        once it has closed — by which time the cap has already failed to stop the
        entry.  The backtester increments it when a position opens.
        """
        st = self.st
        self.roll_day(ts_ms, index)
        st.day_pnl += net_pnl
        st.total_trades += 1
        if net_pnl > 0:
            st.wins += 1
            st.consecutive_losses = 0
        else:
            st.consecutive_losses += 1
        # same "0 disables the gate" convention as can_open: without it a config
        # that turns the streak limit off would halt after the first losing trade
        if (self.cfg.max_consecutive_losses > 0
                and st.consecutive_losses >= self.cfg.max_consecutive_losses):
            self._halt("consecutive_losses", index,
                       until=index + self.cfg.halt_cooldown_bars)

    def mark(self, equity: float) -> None:
        """Mark-to-market update (unrealised PnL included)."""
        self.st.equity = equity
        self.st.peak_equity = max(self.st.peak_equity, equity)

    def funding_for(self, notional: float, bars_held: int, tf_minutes: int) -> float:
        days = bars_held * tf_minutes / 1440.0
        return abs(notional) * (self.cfg.costs.funding_bps_per_day / 10_000.0) * days

    # ---- reporting ----
    def snapshot(self) -> dict[str, Any]:
        st = self.st
        return {
            "equity": st.equity,
            "cash": st.cash,
            "peak_equity": st.peak_equity,
            "drawdown": st.drawdown,
            "drawdown_pct": st.drawdown * 100.0,
            "realised_pnl": st.realised_pnl,
            "total_trades": st.total_trades,
            "wins": st.wins,
            "win_rate": safe_div(st.wins, st.total_trades, 0.0),
            "consecutive_losses": st.consecutive_losses,
            "trades_today": st.trades_today,
            "day_pnl": st.day_pnl,
            "open_risk": st.open_risk,
            "open_positions": st.open_positions,
            "halted": st.halted,
            "halt_reason": st.halt_reason,
            "ramp_fraction": self.ramp_fraction(),
            "kelly_risk_pct": self._kelly,
            "halt_events": st.events,
        }


def risk_report(trades: Sequence[Trade], cfg: RiskConfig) -> dict[str, Any]:
    """How the risk layer actually behaved — as opposed to how it was configured."""
    if not trades:
        return {"trades": 0}
    risks = [t.risk_cash for t in trades]
    lev = [safe_div(t.notional, t.risk_cash, 0.0) for t in trades if t.risk_cash > 0]
    return {
        "trades": len(trades),
        "risk_cash_mean": mean(risks),
        "risk_cash_median": sorted(risks)[len(risks) // 2],
        "risk_cash_max": max(risks),
        "risk_cash_pct_of_initial": mean(risks) / cfg.initial_equity * 100.0,
        "implied_leverage_mean": mean(lev) if lev else 0.0,
        "implied_leverage_max": max(lev) if lev else 0.0,
        "notional_mean": mean([t.notional for t in trades]),
        "loss_exceeding_1R": sum(1 for t in trades if t.r_multiple < -1.05),
        "loss_exceeding_1R_share": safe_div(
            sum(1 for t in trades if t.r_multiple < -1.05), len(trades), 0.0
        ),
        "worst_r": min(t.r_multiple for t in trades),
        "gap_slippage_bp_mean": mean(
            [abs(safe_div(t.costs, t.notional, 0.0)) * 10_000.0 for t in trades]
        ),
    }
