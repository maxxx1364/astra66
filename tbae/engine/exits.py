"""Staged exits, dynamic TP/SL, and the reversal-event ladder.

Three mechanisms, deliberately separated
----------------------------------------
1. **Price-based exits** — stop and target ladder.  Evaluated *per minute* inside
   each bar by the backtester, because the minute path is available.  This is the
   difference between "the bar's low touched my stop" (ambiguous: did it touch
   before or after the high?) and "at 14:07 the price traded through my stop".
2. **Dynamic re-pricing** — the stop and the runner target are recomputed on every
   bar close from the *current* intra-candle sigma (``sigma_atr``, the Wilder-smoothed
   blend of minute realised variance and Garman-Klass).  Volatility is not
   stationary; a stop set at entry is stale by bar three.
3. **Reversal events** — semantic exits that price levels cannot express: churn
   without progress, a wick rejection, the final third of the minute legs flipping
   against you, a VWAP loss.  Each produces a severity in [0,1]; severities combine
   with a noisy-OR and drive a *graduated* response — tighten first, exit later.

Why graduated rather than binary
--------------------------------
A hard "any reversal pattern -> flatten" rule is the most common way a promising
exit system destroys itself: most such patterns are noise, and acting on every one
converts a positive-expectancy runner into a series of scratches.  The noisy-OR
combination means one weak event does almost nothing, two moderate events tighten
the stop, and a cluster exits.  The thresholds are explicit and tested.

Asymmetric re-pricing
---------------------
In profit, the stop may only move *towards* the position (ratchet).  Widening is
permitted only when all of: the trade is young, volatility genuinely expanded, and
the resulting stop is still inside ``max_stop_pct``.  Without that asymmetry a
trailing stop loosens on every quiet bar and gives back the move it was protecting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .indicators import Indicators
from .mathx import EPS, clamp, mean, safe_div
from .models import Bar, Category, Settings
from .path import PathPoint, completion_ratio, expected_formed_pct
from .portfolio import Fill, Position, Tranche
from .systembar import tail_flow


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ExitConfig:
    # ---- initial stop geometry ----
    #: ``sigma`` | ``atr`` | ``structure`` | ``sigma_structure_max`` | ``sigma_structure_min``
    stop_mode: str = "sigma_structure_max"
    stop_sigma_mult: float = 2.20
    stop_atr_mult: float = 1.80
    structure_buffer_sigma: float = 0.30
    #: The last *confirmed* pivot on a 15m chart can sit dozens of bars back, so
    #: an uncapped structural stop lands around 6x ATR — far beyond what the
    #: timeframe can actually deliver, which makes 1R unreachable and the target
    #: ladder decorative (measured: median 1.57% stop vs 0.26% ATR).  The
    #: structural level is therefore clamped into a sigma band: it may refine the
    #: stop, not redefine the timeframe.
    structure_min_sigma_mult: float = 1.20
    structure_max_sigma_mult: float = 3.20
    min_stop_pct: float = 0.12      # never tighter (spread/noise floor)
    max_stop_pct: float = 1.60      # never wider (budget ceiling)

    # ---- staged targets: (R multiple, share of remaining position) ----
    #: ``r_multiple == 0`` marks the runner: no fixed target, managed by the trail.
    tranches: tuple[tuple[float, float], ...] = (
        (1.00, 0.40),
        (2.00, 0.35),
        (0.00, 1.00),
    )
    move_stop_to_be_after_r: float = 1.00
    be_buffer_sigma: float = 0.10
    runner_target_sigma_mult: float = 4.0
    runner_has_hard_target: bool = False

    # ---- trailing ----
    #: ``chandelier`` | ``r_ratchet`` | ``sar`` | ``none``
    trail_mode: str = "chandelier"
    chandelier_period: int = 10
    chandelier_mult: float = 3.00
    ratchet_give_back_r: float = 1.00
    trail_start_r: float = 0.80
    ratchet_never_loosen: bool = True

    # ---- dynamic re-pricing from live intra-candle volatility ----
    reprice_each_bar: bool = True
    allow_stop_widening: bool = True
    widen_max_bars_held: int = 4
    widen_vol_expansion: float = 1.55
    widen_max_pct_of_r: float = 0.45      # a widen may add at most 45% of 1R
    target_widen_on_vol_expansion: bool = True

    # ---- reversal-event ladder ----
    events_enabled: bool = True
    #: Severities were recalibrated against measured firing rates.  At the
    #: original 0.34/0.62 the ladder fired on ~45% of bars (``category_flip``
    #: alone) and closed trades after ~3 bars, before the target ladder could
    #: ever be reached.  A reversal detector that fires on half the bars is not
    #: detecting reversals; it is a cost generator.
    tighten_severity: float = 0.42
    exit_all_severity: float = 0.72
    partial_severity: float = 0.50
    partial_share: float = 0.50
    tighten_factor: float = 0.55          # new stop = mid(price, old stop) blended
    max_tightens_per_trade: int = 3

    # event weights (noisy-OR inputs); 0 disables an event
    w_effort_vs_result: float = 0.55
    w_efficiency_collapse: float = 0.45
    w_wick_rejection: float = 0.50
    w_engulfing: float = 0.50
    w_leg_flow_flip: float = 0.55
    w_structure_break: float = 0.55
    w_vwap_cross: float = 0.40
    w_category_flip: float = 0.40
    w_momentum_stall: float = 0.35
    w_vol_contraction: float = 0.30
    w_profit_giveback: float = 0.65
    w_rsi_reversal: float = 0.30

    # event thresholds
    wick_rejection_share: float = 0.55
    engulfing_min_vol_z: float = 0.30
    #: flow-flip threshold, in units of the bar's OWN realised volatility (not the
    #: smoothed sigma, which underestimates a burst and so over-fires).
    flow_flip_rv_mult: float = 1.35
    #: minimum depth, in sigma, before a lost pivot counts as a structure break
    structure_break_min_sigma: float = 0.75
    #: the ladder is silent for the first N bars of a trade.  A fresh position's
    #: own entry-bar noise must not be read as an immediate reversal.
    min_bars_held_for_events: int = 2
    flow_flip_tail: float = 1.0 / 3.0
    efficiency_floor: float = 0.18
    #: efficiency_collapse additionally requires the trade to have worked first
    #: and the drop to be *relative*, so a quiet bar in a young trade does not
    #: read as an impulse dying.
    efficiency_collapse_min_peak_r: float = 0.50
    efficiency_collapse_ratio: float = 0.55
    completion_floor: float = 0.50
    giveback_peak_r: float = 1.00
    giveback_trough_r: float = -0.60
    rsi_long_extreme: float = 76.0
    rsi_short_extreme: float = 24.0
    vol_contraction_from: float = 1.45
    vol_contraction_to: float = 0.75

    # ---- intra-bar early check ----
    #: Evaluate the flow-flip event partway through the bar (at this fraction of
    #: elapsed minutes) instead of waiting for the close.  Only possible because
    #: the minute path is retained; the fill is that minute's close + slippage.
    intra_bar_event_check: bool = True
    event_check_elapsed: float = 0.66

    # ---- time exits ----
    max_bars_held: int = 64
    time_stop_bars: int = 8
    time_stop_min_r: float = 0.30
    flatten_at_day_end: bool = False

    def validate(self) -> "ExitConfig":
        if self.stop_mode not in ("sigma", "atr", "structure",
                                  "sigma_structure_max", "sigma_structure_min"):
            raise ValueError(f"unknown stop_mode {self.stop_mode!r}")
        if self.trail_mode not in ("chandelier", "r_ratchet", "sar", "none"):
            raise ValueError(f"unknown trail_mode {self.trail_mode!r}")
        if self.min_stop_pct >= self.max_stop_pct:
            raise ValueError("min_stop_pct must be < max_stop_pct")
        total = 0.0
        for r, share in self.tranches:
            if share <= 0:
                raise ValueError("tranche share must be > 0")
            if r < 0:
                raise ValueError("tranche R multiple must be >= 0 (0 = runner)")
            total += share
        if total < 0.999:
            raise ValueError(
                f"tranche shares must sum to >= 1.0 (got {total}); the remainder "
                "would be an unmanaged position"
            )
        runners = [t for t in self.tranches if t[0] == 0.0]
        if len(runners) != 1:
            raise ValueError("exactly one tranche must be the runner (r_multiple=0)")
        if not 0.0 < self.tighten_severity < self.exit_all_severity <= 1.0:
            raise ValueError("need 0 < tighten_severity < exit_all_severity <= 1")
        if self.max_bars_held < 1:
            raise ValueError("max_bars_held must be >= 1")
        if not 0.0 < self.event_check_elapsed < 1.0:
            raise ValueError("event_check_elapsed must be in (0, 1)")
        return self


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ReversalEvent:
    name: str
    severity: float          # 0..1, raw
    weight: float            # 0..1, config
    detail: str = ""

    @property
    def contribution(self) -> float:
        return clamp(self.severity, 0.0, 1.0) * clamp(self.weight, 0.0, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "severity": self.severity, "weight": self.weight,
                "contribution": self.contribution, "detail": self.detail}


@dataclass(slots=True)
class ExitDecision:
    action: str = "hold"        # hold | tighten | close_partial | close_all
    share: float = 0.0          # fraction of the *remaining* position to close
    reason: str = ""
    new_stop: float | None = None
    severity: float = 0.0
    events: list[ReversalEvent] = field(default_factory=list)
    price_hint: float = 0.0     # suggested fill reference (0 = use bar close)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "share": self.share, "reason": self.reason,
                "new_stop": self.new_stop, "severity": self.severity,
                "events": [e.to_dict() for e in self.events], "note": self.note}


#: The small set of families a report should group exits by.  Concrete reasons are
#: open-ended (event names, tranche numbers, ``reversal:<event>``), so anything that
#: counts them has to collapse them first — otherwise every new event silently adds a
#: row nobody reads.
EXIT_FAMILIES: tuple[str, ...] = (
    "entry", "stop", "target", "runner", "time", "reversal", "event", "session",
    "end_of_data", "other",
)

_EVENT_WORDS = ("flow_flip", "effort_vs_result", "efficiency_collapse", "divergence",
                "exhaustion", "absorption", "climax", "leg_", "stall_event")


def exit_reason_family(reason: str) -> str:
    """Map a concrete exit reason onto one of :data:`EXIT_FAMILIES`.

    Order matters: ``reversal_tighten`` must not be read as a time exit, and
    ``tp2`` must not be read as an event.  Unknown reasons collapse to ``other``
    rather than raising, so a new exit type degrades the report instead of the run.
    """
    r = (reason or "").strip().lower()
    if not r or r == "entry":
        return "entry" if r == "entry" else "other"
    if r.startswith("end_of_data"):
        return "end_of_data"
    if r.startswith("stop") or r.startswith("trail_stop") or r in ("breakeven", "be_stop"):
        return "stop"
    if r.startswith("tp") or r.startswith("target") or r.startswith("scale"):
        return "target"
    if r.startswith("runner"):
        return "runner"
    if r.startswith("time"):
        return "time"
    if r.startswith("reversal"):
        return "reversal"
    if r.startswith("day_end") or r.startswith("session") or r.startswith("funding"):
        return "session"
    if any(w in r for w in _EVENT_WORDS) or r.startswith("event"):
        return "event"
    return "other"


def count_exit_families(reasons: Sequence[str]) -> dict[str, int]:
    """Histogram of :func:`exit_reason_family` over a list of concrete reasons."""
    out = {f: 0 for f in EXIT_FAMILIES if f != "entry"}
    for r in reasons:
        fam = exit_reason_family(r)
        if fam == "entry":
            continue                      # an entry is not an exit
        out[fam] = out.get(fam, 0) + 1
    return {k: v for k, v in out.items() if v}


def combine_severity(events: Sequence[ReversalEvent]) -> float:
    """Noisy-OR combination: ``1 - prod(1 - p_i)``.

    Chosen over a weighted sum because severities are not additive evidence: two
    events at 0.5 should be *more* convincing than one at 1.0 but less than two
    certain ones, and a sum saturates at the wrong place.  The noisy-OR also
    keeps the result in [0,1] for any number of events without renormalisation.
    """
    prod = 1.0
    for e in events:
        prod *= (1.0 - clamp(e.contribution, 0.0, 1.0))
    return clamp(1.0 - prod, 0.0, 1.0)


@dataclass(slots=True)
class EntryPlan:
    """Stop/target geometry decided at entry, before any position exists."""

    side: int
    stop: float
    stop_distance: float
    targets: list[float] = field(default_factory=list)
    tranches: list[Tranche] = field(default_factory=list)
    runner_target: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    capped: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side, "stop": self.stop, "stop_distance": self.stop_distance,
            "targets": self.targets, "runner_target": self.runner_target,
            "components": self.components, "capped": self.capped,
            "tranches": [t.to_dict() for t in self.tranches],
        }


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #
class ExitManager:
    """Stateless policy object: it inspects a position and returns decisions.

    Keeping it stateless (all mutable state lives on the :class:`Position`) means
    the backtester and any live runner share exactly one implementation, and unit
    tests can exercise a decision without constructing an account.
    """

    def __init__(self, cfg: ExitConfig | None = None, settings: Settings | None = None) -> None:
        self.cfg = (cfg or ExitConfig()).validate()
        self.settings = settings or Settings()

    # ------------------------------------------------------------------ #
    # entry geometry
    # ------------------------------------------------------------------ #
    def plan(self, bar: Bar, side: int, ind: Indicators, i: int,
             *, price: float | None = None) -> EntryPlan:
        """Compute the initial stop and the staged target ladder."""
        c = self.cfg
        px = price if price is not None else bar.close
        sigma = self._sigma(bar)
        atr = bar.atr if bar.atr > 0 else sigma

        sigma_stop = c.stop_sigma_mult * sigma
        atr_stop = c.stop_atr_mult * atr

        # structural stop: just beyond the last *confirmed* pivot against us.
        # Confirmed, not the raw N-bar extreme — see ``indicators`` docstring.
        struct_stop = 0.0
        if i < ind.n:
            if side > 0:
                pivot = ind.swing_lo[i] if ind.swing_lo[i] > 0 else bar.low
                raw = px - (pivot - c.structure_buffer_sigma * sigma)
            else:
                pivot = ind.swing_hi[i] if ind.swing_hi[i] > 0 else bar.high
                raw = (pivot + c.structure_buffer_sigma * sigma) - px
            # clamp into the sigma band (see structure_*_sigma_mult docstring)
            struct_stop = clamp(raw, c.structure_min_sigma_mult * sigma,
                                c.structure_max_sigma_mult * sigma)
            if raw <= 0:
                struct_stop = c.structure_min_sigma_mult * sigma

        mode = c.stop_mode
        if mode == "sigma":
            dist, used = sigma_stop, "sigma"
        elif mode == "atr":
            dist, used = atr_stop, "atr"
        elif mode == "structure":
            dist, used = (struct_stop if struct_stop > 0 else sigma_stop), "structure"
        elif mode == "sigma_structure_min":
            dist = min(sigma_stop, struct_stop) if struct_stop > 0 else sigma_stop
            used = "sigma_structure_min"
        else:  # sigma_structure_max — the default: never tighter than either view
            dist = max(sigma_stop, struct_stop) if struct_stop > 0 else sigma_stop
            used = "sigma_structure_max"

        # clamp to the % band: the floor keeps the stop out of the spread, the
        # ceiling keeps a single trade's loss inside the risk budget
        lo = px * c.min_stop_pct / 100.0
        hi = px * c.max_stop_pct / 100.0
        capped = ""
        if dist < lo:
            dist, capped = lo, "min_stop_pct"
        elif dist > hi:
            dist, capped = hi, "max_stop_pct"
        if dist <= EPS:
            dist = max(lo, EPS)
            capped = capped or "degenerate"

        stop = px - side * dist
        if stop <= 0:
            stop = px * 0.5
            dist = px - stop

        # ---- staged ladder ----
        tranches: list[Tranche] = []
        targets: list[float] = []
        for r, share in c.tranches:
            t = Tranche(r_multiple=r, share=share)
            tranches.append(t)
            if r > 0:
                targets.append(px + side * r * dist)

        runner_target = 0.0
        if c.runner_has_hard_target:
            runner_target = px + side * c.runner_target_sigma_mult * sigma
            targets.append(runner_target)

        return EntryPlan(
            side=side, stop=stop, stop_distance=dist, targets=sorted(targets),
            tranches=tranches, runner_target=runner_target,
            components={"sigma_stop": sigma_stop, "atr_stop": atr_stop,
                        "structure_stop": struct_stop, "sigma_used": sigma,
                        "atr_used": atr, "mode": used},
            capped=capped,
        )

    def _sigma(self, bar: Bar) -> float:
        """The volatility number every distance in this module is scaled by.

        ``sigma_atr`` (smoothed) by preference: sizing and stop placement must not
        twitch on a single bar's spike.  Falls back to raw sigma, then to ATR,
        then to a fraction of price so a degenerate bar cannot produce a zero stop.
        """
        for v in (bar.sigma_atr, bar.sigma, bar.atr):
            if v > EPS:
                return v
        return max(bar.close * 0.002, EPS)

    # ------------------------------------------------------------------ #
    # price-based exits (evaluated per minute by the backtester)
    # ------------------------------------------------------------------ #
    def stop_hit(self, pos: Position, price: float) -> bool:
        if pos.stop_distance <= 0:
            return False
        return price <= pos.stop if pos.side > 0 else price >= pos.stop

    def tranches_hit(self, pos: Position, price: float) -> list[int]:
        """Indices of unfilled fixed-R tranches whose target ``price`` reached."""
        hit: list[int] = []
        for k, t in enumerate(pos.tranches):
            if t.filled or t.r_multiple <= 0:
                continue
            target = pos.entry_price + pos.side * t.r_multiple * pos.stop_distance
            if (pos.side > 0 and price >= target) or (pos.side < 0 and price <= target):
                hit.append(k)
        return hit

    def runner_target_hit(self, pos: Position, price: float) -> bool:
        if not self.cfg.runner_has_hard_target or pos.runner_target <= 0:
            return False
        return price >= pos.runner_target if pos.side > 0 else price <= pos.runner_target

    # ------------------------------------------------------------------ #
    # per-bar management
    # ------------------------------------------------------------------ #
    def on_bar(self, pos: Position, bars: Sequence[Bar], i: int, ind: Indicators,
               *, curves: dict[str, list[PathPoint]] | None = None) -> ExitDecision:
        """Bar-close management: re-price the stop, then run the event ladder.

        Order matters.  Trailing/re-pricing happens *first* so the event ladder
        tightens from the already-updated stop; doing it the other way round lets
        a trailing step undo an event-driven tighten in the same bar.
        """
        c = self.cfg
        bar = bars[i]
        pos.bars_held += 1
        pos.update_extremes(bar.high, bar.low)

        sigma = self._sigma(bar)
        reprice_note = ""
        if c.reprice_each_bar:
            reprice_note = self._reprice(pos, bar, i, ind, sigma)

        # ---- tranche promotion: breakeven after the first target ----
        be_note = ""
        if (not pos.be_moved and c.move_stop_to_be_after_r > 0
                and pos.peak_r >= c.move_stop_to_be_after_r):
            be = pos.entry_price + pos.side * c.be_buffer_sigma * sigma
            if self._better(pos, be):
                pos.stop = be
                pos.be_moved = True
                be_note = "stop->breakeven"

        # ---- time exits ----
        tdec = self._time_exit(pos, bar, i, bars, curves)
        if tdec is not None:
            tdec.note = " ".join(x for x in (reprice_note, be_note, tdec.note) if x)
            return tdec

        # ---- reversal events ----
        if not c.events_enabled or pos.bars_held < c.min_bars_held_for_events:
            skip = ("" if c.events_enabled
                    else f"events_disabled held={pos.bars_held}<{c.min_bars_held_for_events}")
            return ExitDecision(
                action="hold",
                note=" ".join(x for x in (reprice_note, be_note, skip) if x))

        events = self.detect_events(pos, bars, i, ind, curves)
        sev = combine_severity(events)
        fired = [e for e in events if e.contribution > 0.05]
        dec = self._decide_from_severity(pos, sev, fired, bar, sigma)
        dec.note = " ".join(x for x in (reprice_note, be_note, dec.note) if x)
        return dec

    def _better(self, pos: Position, candidate: float) -> bool:
        """Is ``candidate`` a tighter (more protective) stop than the current one?"""
        if pos.stop_distance <= 0:
            return True
        return candidate > pos.stop if pos.side > 0 else candidate < pos.stop

    def _reprice(self, pos: Position, bar: Bar, i: int, ind: Indicators,
                 sigma: float) -> str:
        """Trail the stop using live intra-candle volatility.  Returns a note."""
        c = self.cfg
        if c.trail_mode == "none":
            return ""
        if pos.peak_r < c.trail_start_r:
            return ""            # do not trail before the trade has worked at all

        cand = pos.stop
        note = ""
        if c.trail_mode == "chandelier":
            k = c.chandelier_mult * sigma
            if pos.side > 0:
                cand = pos.highest_since_entry - k
            else:
                cand = pos.lowest_since_entry + k
            note = "chandelier"
        elif c.trail_mode == "r_ratchet":
            give = c.ratchet_give_back_r * pos.stop_distance
            if pos.side > 0:
                cand = pos.highest_since_entry - give
            else:
                cand = pos.lowest_since_entry + give
            note = "r_ratchet"
        else:  # sar
            step = 0.02 * pos.stop_distance
            extreme = pos.highest_since_entry if pos.side > 0 else pos.lowest_since_entry
            cand = pos.stop + pos.side * max(step, 0.25 * c.chandelier_mult * sigma)
            cand = extreme - pos.side * 0.5 * sigma if pos.side > 0 else extreme + 0.5 * sigma
            cand = pos.stop + pos.side * max(step, abs(cand - pos.stop) * 0.35)
            note = "sar"

        if c.ratchet_never_loosen and not self._better(pos, cand):
            return note + "(no_change)"
        if self._better(pos, cand):
            pos.stop = cand
            pos.stop_tightened_count += 1
            return note
        # candidate is looser: allowed only under strict widening conditions
        if c.allow_stop_widening and pos.bars_held <= c.widen_max_bars_held \
                and bar.vol_regime >= c.widen_vol_expansion:
            room = c.widen_max_pct_of_r * pos.stop_distance
            widened = pos.stop - pos.side * min(abs(cand - pos.stop), room)
            px_pct = abs(widened - pos.entry_price) / pos.entry_price * 100.0
            if px_pct <= c.max_stop_pct and widened > 0:
                pos.stop = widened
                pos.stop_widened_count += 1
                return note + "(widened_vol_expansion)"
        return note + "(held)"

    def _time_exit(self, pos: Position, bar: Bar, i: int, bars: Sequence[Bar],
                   curves: dict[str, list[PathPoint]] | None) -> ExitDecision | None:
        c = self.cfg
        if pos.bars_held >= c.max_bars_held:
            return ExitDecision(action="close_all", reason="time_max",
                                note=f"held={pos.bars_held}")
        if pos.bars_held >= c.time_stop_bars and pos.peak_r < c.time_stop_min_r:
            return ExitDecision(
                action="close_all", reason="time_stall",
                note=f"held={pos.bars_held} peak_r={pos.peak_r:.2f}<{c.time_stop_min_r}")
        if c.flatten_at_day_end and i + 1 < len(bars):
            import datetime as _dt
            d0 = _dt.datetime.fromtimestamp(bar.ts / 1000.0, _dt.timezone.utc).date()
            d1 = _dt.datetime.fromtimestamp(bars[i + 1].ts / 1000.0, _dt.timezone.utc).date()
            if d0 != d1:
                return ExitDecision(action="close_all", reason="day_end",
                                    note="session boundary")
        return None

    def _decide_from_severity(self, pos: Position, sev: float,
                              events: Sequence[ReversalEvent], bar: Bar,
                              sigma: float) -> ExitDecision:
        c = self.cfg
        base = ExitDecision(severity=sev, events=list(events))
        if sev >= c.exit_all_severity:
            names = "+".join(e.name for e in events[:3]) or "threshold"
            base.action = "close_all"
            base.share = 1.0
            base.reason = f"reversal:{names}"
            base.note = f"severity={sev:.2f}>={c.exit_all_severity}"
            return base
        if sev >= c.partial_severity and pos.qty_share_open() > 0.35:
            base.action = "close_partial"
            base.share = c.partial_share
            base.reason = "reversal_partial"
            base.note = f"severity={sev:.2f} share={c.partial_share}"
            return base
        if sev >= c.tighten_severity and pos.stop_tightened_count < c.max_tightens_per_trade:
            # tighten towards price by ``tighten_factor`` of the remaining distance
            cur_r = pos.unrealised_r(bar.close)
            target_stop = bar.close - pos.side * (1.0 - c.tighten_factor) * max(
                pos.stop_distance, EPS) * 0.5
            # never tighten past breakeven-plus unless already in profit
            if cur_r <= 0:
                target_stop = bar.close - pos.side * pos.stop_distance * 0.75
            if self._better(pos, target_stop):
                base.action = "tighten"
                base.new_stop = target_stop
                base.reason = "reversal_tighten"
                base.note = f"severity={sev:.2f} new_stop={target_stop:.6g}"
                return base
            base.note = f"severity={sev:.2f} tighten_blocked"
            return base
        base.note = f"severity={sev:.2f} below tighten threshold"
        return base

    # ------------------------------------------------------------------ #
    # reversal event library
    # ------------------------------------------------------------------ #
    def detect_events(self, pos: Position, bars: Sequence[Bar], i: int,
                      ind: Indicators,
                      curves: dict[str, list[PathPoint]] | None = None) -> list[ReversalEvent]:
        """All reversal events firing on bar ``i`` for ``pos``.

        Each detector returns severity in [0,1]; the configured weight scales it.
        Detectors are deliberately conservative: they must fire on genuinely
        unusual bars, otherwise the ladder is just a cost generator.
        """
        c = self.cfg
        bar = bars[i]
        prev = bars[i - 1] if i > 0 else bar
        side = pos.side
        ev: list[ReversalEvent] = []

        # 1. effort vs result — the README's "pressure" footprint, generalised:
        #    lots of mobility, no displacement, in the direction we are holding.
        if c.w_effort_vs_result > 0:
            s_pct, ch_pct = bar.system_pct, bar.chart_pct
            if s_pct > 0:
                stall = clamp((s_pct - 60.0) / 60.0, 0.0, 1.0) * clamp(
                    (30.0 - ch_pct) / 30.0, 0.0, 1.0)
                if stall > 0.02:
                    ev.append(ReversalEvent(
                        "effort_vs_result", stall, c.w_effort_vs_result,
                        f"system_pct={s_pct:.0f} chart_pct={ch_pct:.0f}"))

        # 2. efficiency collapse — the bar moved a lot less usefully than its
        #    predecessors, i.e. the impulse is dying while we are still in it.
        if (c.w_efficiency_collapse > 0 and i >= 3
                and pos.peak_r >= c.efficiency_collapse_min_peak_r):
            recent = mean([bars[j].efficiency for j in range(i - 3, i)])
            if (bar.efficiency < c.efficiency_floor
                    and bar.efficiency < c.efficiency_collapse_ratio * recent
                    and recent > 0):
                sev = clamp((recent - bar.efficiency) / max(recent, EPS), 0.0, 1.0)
                if sev > 0.15:
                    ev.append(ReversalEvent(
                        "efficiency_collapse", sev, c.w_efficiency_collapse,
                        f"eff={bar.efficiency:.2f} vs prev3={recent:.2f}"))

        # 3. wick rejection against the position
        if c.w_wick_rejection > 0 and bar.rng > EPS:
            adverse_wick = bar.upper_wick if side > 0 else bar.lower_wick
            share = adverse_wick / bar.rng
            if share >= c.wick_rejection_share:
                closed_back = (bar.close < prev.close) if side > 0 else (bar.close > prev.close)
                sev = clamp((share - c.wick_rejection_share)
                            / max(1.0 - c.wick_rejection_share, EPS), 0.0, 1.0)
                if closed_back:
                    sev = clamp(sev + 0.25, 0.0, 1.0)
                if sev > 0.05:
                    ev.append(ReversalEvent(
                        "wick_rejection", sev, c.w_wick_rejection,
                        f"adverse_wick={share * 100:.0f}% closed_back={closed_back}"))

        # 4. engulfing against the position, on volume
        if c.w_engulfing > 0 and prev.rng > EPS:
            opp = -side
            is_opp = prev.direction == opp and bar.direction == opp
            engulfs = (bar.close < prev.open and bar.open > prev.close) if opp > 0 \
                else (bar.close > prev.open and bar.open < prev.close)
            if engulfs or (is_opp and abs(bar.body) > abs(prev.body) * 1.15):
                vz = ind.vol_z[i] if i < ind.n else 0.0
                if vz >= c.engulfing_min_vol_z:
                    sev = clamp(abs(bar.body) / max(prev.rng, EPS), 0.0, 1.0)
                    ev.append(ReversalEvent(
                        "engulfing", sev, c.w_engulfing,
                        f"body={bar.body:+.6g} prev_range={prev.rng:.6g} vol_z={vz:.2f}"))

        # 5. leg-flow flip — intra-candle microstructure.  The bar may still be
        #    green, but its final minutes were sold into.
        if c.w_leg_flow_flip > 0 and bar.minute_path:
            flow, nlegs = tail_flow(bar.minute_path, c.flow_flip_tail)
            # scale by the bar's OWN realised volatility: the tail of a bar that
            # moved 3x its normal path should be judged against that path, not
            # against a 14-bar average that has not caught up yet.
            scale = bar.rv if bar.rv > EPS else self._sigma(bar)
            thresh = c.flow_flip_rv_mult * scale * math.sqrt(max(c.flow_flip_tail, 1e-6))
            against = -flow * side
            if thresh > EPS and against > 0:
                sev = clamp(against / thresh, 0.0, 1.0)
                if sev > 0.25:
                    ev.append(ReversalEvent(
                        "leg_flow_flip", sev, c.w_leg_flow_flip,
                        f"tail_flow={flow:+.6g} vs side={side} thresh={thresh:.6g} legs={nlegs}"))

        # 6. structure break against the position (confirmed pivot lost)
        if c.w_structure_break > 0 and i < ind.n:
            pivot = ind.swing_lo[i] if side > 0 else ind.swing_hi[i]
            if pivot > 0:
                broke = bar.close < pivot if side > 0 else bar.close > pivot
                depth = abs(bar.close - pivot) / max(self._sigma(bar), EPS)
                if broke and depth >= c.structure_break_min_sigma:
                    sev = clamp((depth - c.structure_break_min_sigma) / 1.5, 0.0, 1.0)
                    ev.append(ReversalEvent(
                        "structure_break", sev, c.w_structure_break,
                        f"close={bar.close:.6g} pivot={pivot:.6g} depth={depth:.2f}sigma"))

        # 7. session VWAP crossed against the position
        if c.w_vwap_cross > 0 and bar.vwap > 0:
            now_below = bar.close < bar.vwap
            was_above = prev.close > prev.vwap if prev.vwap > 0 else False
            if side > 0 and now_below and was_above:
                sev = clamp(abs(bar.close - bar.vwap) / max(self._sigma(bar), EPS), 0.0, 1.0)
                ev.append(ReversalEvent("vwap_cross", sev, c.w_vwap_cross,
                                        "long lost session VWAP"))
            elif side < 0 and (not now_below) and (not was_above):
                sev = clamp(abs(bar.close - bar.vwap) / max(self._sigma(bar), EPS), 0.0, 1.0)
                ev.append(ReversalEvent("vwap_cross", sev, c.w_vwap_cross,
                                        "short lost session VWAP"))

        # 8. category flip away from impulse categories
        if c.w_category_flip > 0 and pos.category:
            # NB: ``weak`` is deliberately NOT a reversal.  Weak bars are ~44% of
            # all bars — they are simply quiet.  Treating quiet as reversal made
            # this the single most frequent event (45% of bars) and killed every
            # trend trade at the first lull.  Only ``pressure`` — huge mobility,
            # no displacement — is genuine evidence that the impulse stalled.
            impulse = {"strong", "energetic"}
            if pos.category in impulse and bar.category.value == "pressure":
                ev.append(ReversalEvent(
                    "category_flip", 0.85, c.w_category_flip,
                    f"{pos.category} -> pressure"))
            elif (bar.category.value == "pressure" and pos.strategy == "trend"
                  and pos.category not in impulse):
                ev.append(ReversalEvent(
                    "category_flip", 0.45, c.w_category_flip,
                    "trend position into pressure bar"))

        # 9. momentum stall vs the cohort growth curve
        if c.w_momentum_stall > 0 and curves:
            curve = curves.get(f"{bar.weekday}-{bar.hour}")
            if curve:
                comp = completion_ratio(bar, curve)
                if comp < c.completion_floor and pos.peak_r > 0.5:
                    sev = clamp((c.completion_floor - comp) / max(c.completion_floor, EPS), 0.0, 1.0)
                    ev.append(ReversalEvent(
                        "momentum_stall", sev, c.w_momentum_stall,
                        f"completion={comp:.2f} floor={c.completion_floor}"))

        # 10. volatility contraction after expansion — the impulse ran out of fuel
        if c.w_vol_contraction > 0 and i >= 2:
            prev_vr = mean([bars[j].vol_regime for j in range(i - 2, i)])
            if prev_vr >= c.vol_contraction_from and bar.vol_regime <= c.vol_contraction_to:
                sev = clamp((prev_vr - bar.vol_regime) / max(prev_vr, EPS), 0.0, 1.0)
                ev.append(ReversalEvent(
                    "vol_contraction", sev, c.w_vol_contraction,
                    f"vol_regime {prev_vr:.2f} -> {bar.vol_regime:.2f}"))

        # 11. profit giveback — had a real move, now returning towards entry.
        #     This one is not a pattern; it is the cost of a trailing stop that is
        #     too loose, made explicit so it can be tuned.
        if c.w_profit_giveback > 0:
            cur_r = pos.unrealised_r(bar.close)
            if pos.peak_r >= c.giveback_peak_r and cur_r <= c.giveback_trough_r * pos.peak_r:
                sev = clamp((pos.peak_r - cur_r) / max(pos.peak_r, EPS), 0.0, 1.0)
                ev.append(ReversalEvent(
                    "profit_giveback", sev, c.w_profit_giveback,
                    f"peak_r={pos.peak_r:.2f} now_r={cur_r:.2f}"))

        # 12. RSI turning back out of an extreme against us
        if c.w_rsi_reversal > 0 and i < ind.n and i >= 1:
            r0, r1 = ind.rsi[i - 1], ind.rsi[i]
            if side > 0 and r0 >= c.rsi_long_extreme and r1 < r0:
                sev = clamp((r0 - c.rsi_long_extreme) / 10.0 + 0.3, 0.0, 1.0)
                ev.append(ReversalEvent("rsi_reversal", sev, c.w_rsi_reversal,
                                        f"rsi {r0:.1f} -> {r1:.1f}"))
            elif side < 0 and r0 <= c.rsi_short_extreme and r1 > r0:
                sev = clamp((c.rsi_short_extreme - r0) / 10.0 + 0.3, 0.0, 1.0)
                ev.append(ReversalEvent("rsi_reversal", sev, c.w_rsi_reversal,
                                        f"rsi {r0:.1f} -> {r1:.1f}"))

        return [e for e in ev if e.contribution > 0.0]

    # ------------------------------------------------------------------ #
    # intra-bar early check
    # ------------------------------------------------------------------ #
    def intra_bar_check(self, pos: Position, bar: Bar, minute_index: int,
                        elapsed_minutes: int) -> ExitDecision | None:
        """Optional mid-bar event evaluation, at ``event_check_elapsed`` of the bar.

        Only the flow-flip event is checked here: it is the one whose evidence
        genuinely exists mid-bar (the last minutes' legs).  Everything else needs
        the completed bar's high/low/close and would be a guess at this point —
        pretending otherwise is how intra-bar logic leaks look-ahead.

        The fill is that minute's close plus slippage, applied by the backtester.
        """
        c = self.cfg
        if not c.events_enabled or not c.intra_bar_event_check:
            return None
        if not bar.minute_path:
            return None
        target = int(math.floor(bar.tf * c.event_check_elapsed))
        if elapsed_minutes != target or target < 2:
            return None
        partial = bar.minute_path[:target]
        flow, _ = tail_flow(partial, 0.5)
        from .volatility import rv_log_variance
        # realised vol of the *partial* path, in price units, is the right scale:
        # the full bar's rv is not known yet at this point in time.
        part_rv = math.sqrt(max(rv_log_variance(partial), 0.0)) * partial[-1].close
        scale = part_rv if part_rv > EPS else self._sigma(bar)
        thresh = c.flow_flip_rv_mult * scale * 0.5
        against = -flow * pos.side
        if thresh <= EPS or against <= 0:
            return None
        sev = clamp(against / thresh, 0.0, 1.0)
        if sev < 0.55:
            return None
        ev = ReversalEvent("leg_flow_flip_intrabar", sev, c.w_leg_flow_flip,
                           f"mid-bar tail_flow={flow:+.6g} elapsed={elapsed_minutes}m")
        combined = combine_severity([ev])
        if combined >= c.exit_all_severity:
            return ExitDecision(action="close_all", share=1.0, severity=combined,
                                events=[ev], reason="reversal:leg_flow_flip_intrabar",
                                price_hint=partial[-1].close,
                                note=f"mid-bar exit at minute {elapsed_minutes}")
        if combined >= c.tighten_severity and pos.stop_tightened_count < c.max_tightens_per_trade:
            new_stop = partial[-1].close - pos.side * pos.stop_distance * 0.6
            if self._better(pos, new_stop):
                return ExitDecision(action="tighten", new_stop=new_stop,
                                    severity=combined, events=[ev],
                                    reason="reversal_tighten_intrabar",
                                    price_hint=partial[-1].close,
                                    note=f"mid-bar tighten at minute {elapsed_minutes}")
        return None

    # ------------------------------------------------------------------ #
    # tranche execution helpers
    # ------------------------------------------------------------------ #
    def next_unfilled(self, pos: Position) -> int | None:
        for k, t in enumerate(pos.tranches):
            if not t.filled:
                return k
        return None

    def tranche_qty(self, pos: Position, k: int) -> float:
        """Quantity closed by tranche ``k``.

        Shares are applied to the *remaining* position for the fixed-R tranches,
        and the runner takes whatever is left.  Applying every share to the
        initial size instead would silently leave a residual position nobody
        manages — the classic staged-exit bug.
        """
        t = pos.tranches[k]
        if t.r_multiple == 0.0:
            return pos.qty
        return pos.qty * clamp(t.share, 0.0, 1.0)


def exit_config_presets() -> dict[str, ExitConfig]:
    """Named starting points.  They are *priors*, not recommendations: every one
    of them must be re-validated on the user's own data before it means anything."""
    base = ExitConfig()
    return {
        "default": base,
        "tight": ExitConfig(stop_sigma_mult=1.5, stop_atr_mult=1.2,
                            chandelier_mult=2.0, trail_start_r=0.5,
                            tranches=((0.8, 0.45), (1.6, 0.35), (0.0, 1.0)),
                            max_bars_held=32),
        "wide": ExitConfig(stop_sigma_mult=3.0, stop_atr_mult=2.4,
                           chandelier_mult=4.0, trail_start_r=1.2,
                           tranches=((1.5, 0.30), (3.0, 0.30), (0.0, 1.0)),
                           max_bars_held=128),
        "scalp": ExitConfig(stop_sigma_mult=1.1, stop_atr_mult=0.9,
                            chandelier_mult=1.5, trail_start_r=0.35,
                            tranches=((0.6, 0.5), (1.2, 0.3), (0.0, 1.0)),
                            max_bars_held=12, time_stop_bars=4),
        "no_staging": ExitConfig(tranches=((0.0, 1.0),)),
    }
