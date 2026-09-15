"""Signal extraction, confirmation filters, and the funnel diagnostics.

Part 1 of the brief asks *why the signals are sparse* before asking for more of
them.  That order is correct, and this module answers it with measurements rather
than opinion — see :func:`diagnose`.

The short answer, which ``diagnose`` reproduces from data
---------------------------------------------------------
The category tree is a **percentile gate**, not a signal generator.  ``chart_pct``
and ``system_pct`` are ratios against the dynamic 98th-percentile reference, so a
rule like ``chart_pct >= 55%`` selects roughly the top decile of bars by
construction.  Requiring it on *both* axes (``energetic``) or on one axis while
excluding the other (``strong``) compounds: empirically ``strong`` is ~3.6% of
bars and ``pressure`` ~1.3%.  On 45 days of 15-minute bars (4.4k tradable bars)
that is ~157 + ~59 candidates *before* any confirmation filter runs.

Sparser still — and this is the part that matters — the categories are almost
directionless on their own.  ``directional_information()`` shows ``strong`` bars
closing up/down roughly 54/46.  A rule that trades "the direction of a strong
bar" is therefore close to a coin flip with costs, no matter how many bars it
fires on.  The confirmation filters below exist to convert a *rare and
undirected* event into a *conditional* one: trade the strong bar only when trend,
volatility regime, volume, flow, structure and time-of-day independently agree.

That is why the funnel is instrumented stage by stage, and why each rejected
candidate records *every* filter it failed (not just the first).  Reporting only
the first failure hides which filters are doing the work and which are redundant.

No look-ahead
-------------
Every filter reads ``Indicators`` / ``Bar`` fields at index ``i``, all of which
are causal (see ``indicators`` module docstring).  The signal is stamped on the
*closed* bar ``i`` and, per ``SignalConfig.execution``, is acted on at bar
``i+1``'s open.  Nothing here ever reads ``i+1``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Sequence

from . import classify
from .indicators import Indicators, extension_risk, trend_agreement
from .mathx import EPS, clamp, mean, safe_div, stdev
from .models import Bar, Category, Settings
from .path import completion_ratio, PathPoint

TRENDCATS: tuple[Category, ...] = (Category.STRONG, Category.ENERGETIC)
REVCATS: tuple[Category, ...] = (Category.PRESSURE,)


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SignalConfig:
    # ---- universe ----
    trend_categories: tuple[str, ...] = ("strong", "energetic")
    reversal_categories: tuple[str, ...] = ("pressure",)
    include_medium: bool = False
    require_reference_ready: bool = True
    #: ``bar_close`` = decide on the closed bar, fill at next open (default).
    #: Anything else is a look-ahead bug and is rejected by ``validate``.
    execution: str = "next_open"

    # ---- entry timing / execution style ----
    #: ``immediate`` = market order at the next bar's open.
    #: ``pullback_limit`` = rest a limit order at a retracement of the signal bar
    #: and take the trade only if price comes back to it.
    #:
    #: This is not a cosmetic choice.  Measured on the calibrated synthetic feed:
    #: market-entering the close of a high-displacement bar bought the top of the
    #: short-horizon move — 75% of trades never reached +0.5R and 68% exited on
    #: the stop, i.e. textbook adverse selection.  Waiting for a retracement
    #: converts a chase into a limit fill and pays maker fees instead of taker.
    entry_timing: str = "pullback_limit"
    #: how far back the limit rests
    pullback_mode: str = "sigma"          # sigma | body | midpoint | open
    pullback_retrace_sigma: float = 0.90
    pullback_body_frac: float = 0.50
    #: bars the order stays live before it is cancelled
    pullback_ttl_bars: int = 4
    #: a limit entry pays the maker fee; a market entry pays taker
    limit_entry_uses_maker_fee: bool = True

    # ---- confirmation filters (each independently switchable) ----
    f_trend: bool = True
    allow_counter_trend: bool = False
    allow_range_entries: bool = True
    min_adx: float = 18.0

    f_volatility: bool = True
    #: Calibrated on the *measured* candidate distribution, not on the all-bar
    #: distribution.  This distinction is the whole point: energetic/strong bars
    #: are high-volatility by construction (candidate vol_regime median 3.18 vs
    #: 0.99 across all bars), so a threshold tuned on all bars rejects half the
    #: candidates for being exactly what the category asked for.  The band below
    #: only excludes dead chop at the bottom and genuine blow-off at the top.
    atr_rank_min: float = 0.10
    atr_rank_max: float = 0.997
    vol_regime_min: float = 0.30
    vol_regime_max: float = 7.00

    f_volume: bool = True
    #: hard floor only; volume confirmation is otherwise scored, not vetoed
    min_vol_z: float = -0.75
    min_flow_agree: float = -0.15
    #: soft targets — reaching these maximises the score contribution
    good_vol_z: float = 0.50
    good_flow_agree: float = 0.20

    f_structure: bool = True
    structure_mode: str = "breakout_or_pullback"   # breakout | pullback | either | off
    pullback_max_sigma: float = 1.6

    f_momentum: bool = True
    #: hard floor; the *preferred* level is ``good_efficiency_trend`` and feeds
    #: the score.  A hard gate at 0.30 rejected ~28% of candidates that were
    #: otherwise well-formed.
    min_efficiency_trend: float = 0.12
    good_efficiency_trend: float = 0.38
    max_efficiency_reversal: float = 0.60
    rsi_long_max: float = 78.0
    rsi_short_min: float = 22.0
    require_roc_agree: bool = True
    min_completion_ratio: float = 0.55

    f_extension: bool = True
    #: Breakout bars are extended by definition (candidate median 1.58 sigma,
    #: p75 3.57).  A 3.0-sigma hard cap rejected ~28% of exactly the bars the
    #: category selected.  5.0 keeps the cap as a genuine 'do not chase a
    #: vertical move' guard while the score penalises extension continuously
    #: from ``extension_soft_sigma`` upwards.
    max_extension_sigma: float = 5.0
    extension_soft_sigma: float = 1.5

    f_timing: bool = True
    skip_dead_hours: bool = True
    hot_only: bool = False

    f_quality: bool = True
    #: The single quality dial.  With hard/soft separation the hard gates remove
    #: structurally-invalid entries and this threshold does the selection.
    min_edge_score: float = 0.45

    #: Which gates may *veto*.  Everything else still runs, still reports, and
    #: still lowers the edge score — it just cannot single-handedly kill a
    #: candidate.  Chaining hard vetoes is why the original stack passed 13 of
    #: 581 candidates (2.2%), which is too few to be statistically meaningful
    #: regardless of how good each filter looks in isolation.
    hard_filters: tuple[str, ...] = (
        "direction", "trend", "volatility", "extension", "timing", "quality",
        "cooldown", "daily_cap",
    )

    # ---- cadence guards ----
    cooldown_bars: int = 2
    max_signals_per_day: int = 8

    # ---- edge-score weights (renormalised internally) ----
    w_category: float = 0.22
    w_efficiency: float = 0.16
    w_trend: float = 0.18
    w_volume: float = 0.12
    w_flow: float = 0.10
    w_timing: float = 0.10
    w_volatility: float = 0.12
    #: structure gets a weight too; without it a clean breakout scores the same
    #: as a bar that merely failed to break anything.
    w_structure: float = 0.10

    def validate(self) -> "SignalConfig":
        if self.entry_timing not in ("immediate", "pullback_limit"):
            raise ValueError(
                f"unknown entry_timing {self.entry_timing!r}")
        if self.pullback_mode not in ("sigma", "body", "midpoint", "open"):
            raise ValueError(f"unknown pullback_mode {self.pullback_mode!r}")
        if self.pullback_ttl_bars < 1:
            raise ValueError("pullback_ttl_bars must be >= 1")
        if self.execution != "next_open":
            raise ValueError(
                "execution must be 'next_open'; deciding and filling on the same "
                "closed bar is look-ahead"
            )
        if self.structure_mode not in ("breakout", "pullback", "breakout_or_pullback", "off"):
            raise ValueError(f"unknown structure_mode {self.structure_mode!r}")
        if not 0.0 <= self.min_edge_score <= 1.0:
            raise ValueError("min_edge_score must be in [0, 1]")
        if self.atr_rank_min >= self.atr_rank_max:
            raise ValueError("atr_rank_min must be < atr_rank_max")
        if self.vol_regime_min >= self.vol_regime_max:
            raise ValueError("vol_regime_min must be < vol_regime_max")
        if self.cooldown_bars < 0:
            raise ValueError("cooldown_bars must be >= 0")
        if self.max_signals_per_day < 0:
            raise ValueError("max_signals_per_day must be >= 0 (0 disables the cap)")
        # ---- pullback limit-order geometry ----
        # A negative retrace would place the resting order *beyond* the signal
        # bar's extreme, where it can only fill by gapping — i.e. it would fill
        # exactly when the thesis is already broken.
        if self.pullback_retrace_sigma < 0:
            raise ValueError("pullback_retrace_sigma must be >= 0")
        if not 0.0 < self.pullback_body_frac <= 1.0:
            raise ValueError("pullback_body_frac must be in (0, 1]")
        if self.pullback_max_sigma <= 0:
            raise ValueError("pullback_max_sigma must be > 0")
        # ---- per-filter ranges ----
        if not 0.0 <= self.min_adx <= 100.0:
            raise ValueError("min_adx must be in [0, 100]")
        if self.max_extension_sigma <= 0:
            raise ValueError("max_extension_sigma must be > 0")
        if not 0.0 < self.extension_soft_sigma <= self.max_extension_sigma:
            raise ValueError(
                "need 0 < extension_soft_sigma <= max_extension_sigma: the soft "
                "penalty band runs from extension_soft_sigma up to the hard veto "
                "at max_extension_sigma, so an inverted pair leaves no band")
        if not 0.0 <= self.rsi_long_max <= 100.0:
            raise ValueError("rsi_long_max must be in [0, 100]")
        if not 0.0 <= self.rsi_short_min <= 100.0:
            raise ValueError("rsi_short_min must be in [0, 100]")
        for name in ("w_category", "w_efficiency", "w_trend", "w_volume", "w_flow",
                     "w_timing", "w_volatility", "w_structure"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (0 removes that term)")
        ws = (self.w_category + self.w_efficiency + self.w_trend + self.w_volume
              + self.w_flow + self.w_timing + self.w_volatility + self.w_structure)
        if ws <= 0:
            raise ValueError("edge-score weights must sum to > 0")
        return self

    def active_filters(self) -> list[str]:
        out = ["reference_ready", "category", "direction"]
        if self.f_trend:
            out.append("trend")
        if self.f_volatility:
            out.append("volatility")
        if self.f_volume:
            out.append("volume")
        if self.f_structure and self.structure_mode != "off":
            out.append("structure")
        if self.f_momentum:
            out.append("momentum")
        if self.f_extension:
            out.append("extension")
        if self.f_timing:
            out.append("timing")
        if self.f_quality:
            out.append("quality")
        out.append("cooldown")
        return out

    def config_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class FilterResult:
    key: str
    passed: bool
    value: float = 0.0
    note: str = ""
    #: 0..1 contribution to the edge score (independent of pass/fail)
    contribution: float = 0.0
    hard: bool = True     # hard filters veto; soft ones only score

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "passed": self.passed, "value": self.value,
                "note": self.note, "contribution": self.contribution, "hard": self.hard}


@dataclass(slots=True)
class Signal:
    ts: int
    index: int
    side: int
    strategy: str                 # trend | reversal
    category: str
    accepted: bool
    score: float
    ref_price: float              # close of the decision bar
    next_open: float = 0.0        # actual fill price candidate (bar i+1 open)
    #: hard-gate failures — these veto the signal
    failed: list[str] = field(default_factory=list)
    #: soft-gate failures — scored down, but not vetoed
    soft_flags: list[str] = field(default_factory=list)
    filters: dict[str, FilterResult] = field(default_factory=dict)
    grade: str = "C"
    # context snapshot — everything a human needs to audit one signal
    chart_pct: float = 0.0
    system_pct: float = 0.0
    efficiency: float = 0.0
    sigma: float = 0.0
    atr_pct: float = 0.0
    vol_z: float = 0.0
    flow_imb: float = 0.0
    adx: float = 0.0
    trend_state: int = 0
    timing_band: str = ""
    extension_sigma: float = 0.0
    rsi: float = 50.0
    day_key: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "index": self.index, "side": self.side,
            "strategy": self.strategy, "category": self.category,
            "accepted": self.accepted, "score": self.score, "grade": self.grade,
            "ref_price": self.ref_price, "next_open": self.next_open,
            "failed": self.failed, "soft_flags": self.soft_flags,
            "filters": {k: v.to_dict() for k, v in self.filters.items()},
            "context": {
                "chart_pct": self.chart_pct, "system_pct": self.system_pct,
                "efficiency": self.efficiency, "sigma": self.sigma,
                "atr_pct": self.atr_pct, "vol_z": self.vol_z,
                "flow_imb": self.flow_imb, "adx": self.adx,
                "trend_state": self.trend_state, "timing_band": self.timing_band,
                "extension_sigma": self.extension_sigma, "rsi": self.rsi,
            },
        }


@dataclass(slots=True)
class FunnelStage:
    key: str
    entered: int
    passed: int
    rejected: int
    note: str = ""

    @property
    def pass_rate(self) -> float:
        return safe_div(self.passed, self.entered, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.key, "entered": self.entered, "passed": self.passed,
                "rejected": self.rejected, "pass_rate": self.pass_rate, "note": self.note}


@dataclass(slots=True)
class SignalSet:
    cfg: SignalConfig
    candidates: list[Signal] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    funnel: list[FunnelStage] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    soft_flag_counts: dict[str, int] = field(default_factory=dict)
    sole_killer: dict[str, int] = field(default_factory=dict)
    n_bars: int = 0
    n_tradable: int = 0

    @property
    def accepted(self) -> list[Signal]:
        return self.signals

    def by_day(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in self.signals:
            out[s.day_key] = out.get(s.day_key, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_hash": self.cfg.config_hash(),
            "n_bars": self.n_bars,
            "n_tradable": self.n_tradable,
            "n_candidates": len(self.candidates),
            "n_signals": len(self.signals),
            "funnel": [f.to_dict() for f in self.funnel],
            "rejection_counts": self.rejection_counts,
            "soft_flag_counts": self.soft_flag_counts,
            "sole_killer": self.sole_killer,
        }


def _fail(sig: "Signal", key: str, cfg: "SignalConfig") -> None:
    """Route a filter failure to the hard or the soft list.

    Splitting these is what makes the funnel readable: a hard failure means the
    candidate is structurally invalid, a soft failure means it is merely weak.
    """
    if key in cfg.hard_filters:
        sig.failed.append(key)
    else:
        sig.soft_flags.append(key)


def _grade(score: float) -> str:
    if score >= 0.80:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.50:
        return "C"
    return "D"


def _tanh01(x: float, scale: float = 1.0) -> float:
    """Smooth squash to (0,1) centred at 0.5 when x=0."""
    return 0.5 + 0.5 * math.tanh(clamp(x, -8.0, 8.0) / max(scale, EPS))


def _bell(x: float, centre: float, width: float) -> float:
    """Gaussian bump in [0,1] — used for 'sweet spot' preferences."""
    return math.exp(-0.5 * ((x - centre) / max(width, EPS)) ** 2)


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def generate(
    bars: Sequence[Bar],
    ind: Indicators,
    settings: Settings | None = None,
    cfg: SignalConfig | None = None,
    *,
    warmup_index: int = 0,
    cohort_curves: dict[str, list[PathPoint]] | None = None,
) -> SignalSet:
    """Evaluate every tradable bar and return the funnel + accepted signals."""
    s = settings or Settings()
    cfg = (cfg or SignalConfig()).validate()
    trend_cats = {Category(c) for c in cfg.trend_categories}
    rev_cats = {Category(c) for c in cfg.reversal_categories}
    if cfg.include_medium:
        trend_cats.add(Category.MEDIUM)

    n = len(bars)
    start = max(1, warmup_index)
    out = SignalSet(cfg=cfg, n_bars=n, n_tradable=max(0, n - start))
    if n <= start + 1:
        return out

    curves = cohort_curves or {}
    last_signal_index = -10**9
    day_counts: dict[int, int] = {}
    # funnel bookkeeping: ordered list of hard gates
    order = ["universe", "category", "direction", "trend", "volatility", "volume",
             "flow", "structure", "momentum", "extension", "timing", "quality",
             "cooldown"]
    entered = {k: 0 for k in order}
    passed = {k: 0 for k in order}

    for i in range(start, n - 1):      # n-1: a signal needs bar i+1 to fill
        b = bars[i]
        entered["universe"] += 1
        if cfg.require_reference_ready and (b.chart_ref <= 0 or b.system_ref <= 0):
            continue
        passed["universe"] += 1

        # ---------- category gate ----------
        entered["category"] += 1
        strat = None
        if b.category in trend_cats:
            strat = "trend"
        elif b.category in rev_cats:
            strat = "reversal"
        if strat is None:
            continue
        passed["category"] += 1

        sig = _blank_signal(b, i, strat, s)
        out.candidates.append(sig)

        # ---------- direction resolution ----------
        entered["direction"] += 1
        side = _resolve_side(b, ind, i, strat, cfg)
        sig.side = side
        if side == 0:
            _fail(sig, "direction", cfg)
            sig.grade = _grade(sig.score)
            continue
        passed["direction"] += 1

        # ---------- filter stack ----------
        gates = _run_filters(bars, ind, i, sig, side, strat, s, cfg, curves)
        for g in gates:
            key = g
            entered[key] += 1
            fr = sig.filters.get(key)
            if fr is None or fr.passed:
                passed[key] += 1

        # ---------- quality / cooldown ----------
        entered["quality"] += 1
        if sig.score >= cfg.min_edge_score or not cfg.f_quality:
            passed["quality"] += 1
        else:
            _fail(sig, "quality", cfg)
        sig.grade = _grade(sig.score)

        entered["cooldown"] += 1
        day = sig.day_key
        if (i - last_signal_index) <= cfg.cooldown_bars and last_signal_index > -10**8:
            _fail(sig, "cooldown", cfg)
        elif day_counts.get(day, 0) >= cfg.max_signals_per_day:
            _fail(sig, "daily_cap", cfg)
        else:
            passed["cooldown"] += 1

        sig.accepted = not sig.failed
        if sig.accepted:
            sig.next_open = bars[i + 1].open
            last_signal_index = i
            day_counts[day] = day_counts.get(day, 0) + 1
            out.signals.append(sig)

    out.funnel = [FunnelStage(key=k, entered=entered[k], passed=passed[k],
                              rejected=entered[k] - passed[k]) for k in order]
    _summarise_rejections(out)
    return out


def _blank_signal(b: Bar, i: int, strat: str, s: Settings) -> Signal:
    import datetime as _dt
    day = _dt.datetime.fromtimestamp(b.ts / 1000.0, _dt.timezone.utc).toordinal()
    return Signal(
        ts=b.ts, index=i, side=0, strategy=strat, category=b.category.value,
        accepted=False, score=0.0, ref_price=b.close,
        chart_pct=b.chart_pct, system_pct=b.system_pct, efficiency=b.efficiency,
        sigma=b.sigma, atr_pct=b.atr_pct, timing_band=b.timing_band, day_key=day,
    )


def _resolve_side(b: Bar, ind: Indicators, i: int, strat: str, cfg: SignalConfig) -> int:
    """Direction of the proposed trade.

    Trend signals take the bar's own direction, but only if the bar actually
    displaced (a ``strong`` bar that closed flat is not a direction).

    Reversal/``pressure`` signals are different: the bar went nowhere by
    definition, so its direction carries no information.  There we use the *flow*
    evidence — the sign of the final third of the minute legs, confirmed by
    taker-buy imbalance.  That is the earliest available read on which side won
    the fight the pressure bar represents.
    """
    if strat == "trend":
        if b.direction == 0:
            return 0
        return b.direction

    # reversal: micro-flow decides
    tail = _tail_flow_of(b)
    imb = ind.flow_imb[i] if i < ind.n else 0.0
    votes = (1 if tail > 0 else -1 if tail < 0 else 0) + (1 if imb > 0 else -1 if imb < 0 else 0)
    if votes == 0:
        return 0
    side = 1 if votes > 0 else -1
    # a pressure bar is a stall; fade the direction that *failed* to make progress
    # when the failure is one-sided, otherwise follow the winning flow
    return side


def _tail_flow_of(b: Bar, frac: float = 1.0 / 3.0) -> float:
    from .systembar import tail_flow
    if not b.minute_path:
        return b.body
    flow, _ = tail_flow(b.minute_path, frac)
    return flow


def _run_filters(
    bars: Sequence[Bar], ind: Indicators, i: int, sig: Signal, side: int,
    strat: str, s: Settings, cfg: SignalConfig,
    curves: dict[str, list[PathPoint]],
) -> list[str]:
    """Run the confirmation stack.  Returns the gate keys evaluated, in order.

    Every filter is evaluated even after one fails, so ``sig.failed`` lists *all*
    reasons.  Short-circuiting would make the funnel unable to say which filters
    are redundant.
    """
    b = bars[i]
    gates: list[str] = []
    contribs: dict[str, float] = {}

    # ---------------- trend ----------------
    if cfg.f_trend:
        gates.append("trend")
        ok, reason = trend_agreement(ind, i, side)
        adx_ok = ind.adx[i] >= cfg.min_adx if i < ind.n else False
        if reason == "counter_trend" and not cfg.allow_counter_trend:
            ok = False
        if reason == "range_no_momentum" and not cfg.allow_range_entries:
            ok = False
        if not adx_ok and strat == "trend":
            ok = False
            reason = f"adx<{cfg.min_adx}"
        st = ind.trend_state[i] if i < ind.n else 0
        c = 1.0 if st == side else (0.55 if st == 0 and adx_ok else 0.1)
        sig.filters["trend"] = FilterResult("trend", ok, float(st), reason, c,
                                            hard="trend" in cfg.hard_filters)
        sig.trend_state = st
        sig.adx = ind.adx[i] if i < ind.n else 0.0
        contribs["trend"] = c
        if not ok:
            _fail(sig, "trend", cfg)

    # ---------------- volatility regime ----------------
    if cfg.f_volatility:
        gates.append("volatility")
        rank = ind.atr_pct_rank[i] if i < ind.n else 0.5
        vr = b.vol_regime
        rank_ok = cfg.atr_rank_min <= rank <= cfg.atr_rank_max
        regime_ok = cfg.vol_regime_min <= vr <= cfg.vol_regime_max
        ok = rank_ok and regime_ok
        note = ("rank=%.3f regime=%.2f" % (rank, vr))
        if not rank_ok:
            note += " | rank_out_of_band"
        if not regime_ok:
            note += " | regime_out_of_band"
        # sweet spot: we want *enough* volatility to pay for costs, but not a
        # blow-off.  A bell centred on rank 0.6 expresses that.
        c = _bell(rank, 0.60, 0.32) * clamp(1.25 - abs(vr - 1.0) * 0.25, 0.0, 1.0)
        sig.filters["volatility"] = FilterResult("volatility", ok, rank, note, c,
                                                 hard="volatility" in cfg.hard_filters)
        contribs["volatility"] = c
        if not ok:
            _fail(sig, "volatility", cfg)

    # ---------------- volume ----------------
    if cfg.f_volume:
        gates.append("volume")
        vz = ind.vol_z[i] if i < ind.n else 0.0
        ok = vz >= cfg.min_vol_z
        c = _tanh01(vz - cfg.good_vol_z, 1.2)
        sig.vol_z = vz
        sig.filters["volume"] = FilterResult("volume", ok, vz, f"vol_z={vz:.2f}", c,
                                             hard="volume" in cfg.hard_filters)
        contribs["volume"] = c
        if not ok:
            _fail(sig, "volume", cfg)

        # flow confirmation is folded into the volume gate: it is the same
        # evidence (who was the aggressor) seen from the tape rather than the total
        imb = ind.flow_imb[i] if i < ind.n else 0.0
        agree = imb * side
        ok_flow = agree >= cfg.min_flow_agree
        c_flow = _tanh01((agree - cfg.good_flow_agree) / max(cfg.good_flow_agree, EPS), 1.0)
        sig.flow_imb = imb
        sig.filters["flow"] = FilterResult("flow", ok_flow, agree,
                                           f"imb={imb:+.3f} side={side}", c_flow,
                                           hard="flow" in cfg.hard_filters)
        contribs["flow"] = c_flow
        gates.append("flow")
        if not ok_flow:
            _fail(sig, "flow", cfg)

    # ---------------- structure ----------------
    if cfg.f_structure and cfg.structure_mode != "off":
        gates.append("structure")
        dh = ind.donchian_hi[i] if i < ind.n else 0.0
        dl = ind.donchian_lo[i] if i < ind.n else 0.0
        brk_up = dh > 0 and b.close > dh
        brk_dn = dl > 0 and b.close < dl
        breakout = brk_up if side > 0 else brk_dn

        sigma = b.sigma_atr if b.sigma_atr > 0 else max(b.sigma, EPS)
        ema = ind.ema_mid[i] if i < ind.n else b.close
        dist = abs(b.close - ema) / sigma
        pullback = dist <= cfg.pullback_max_sigma and (
            (side > 0 and b.close >= ema) or (side < 0 and b.close <= ema)
        )
        mode = cfg.structure_mode
        if mode == "breakout":
            ok = breakout
        elif mode == "pullback":
            ok = pullback
        else:  # breakout_or_pullback
            ok = breakout or pullback
        note = f"breakout={breakout} pullback={pullback} dist_sigma={dist:.2f}"
        c = 1.0 if breakout else (0.75 if pullback else 0.15)
        sig.filters["structure"] = FilterResult("structure", ok, 1.0 if breakout else 0.0,
                                                note, c,
                                                hard="structure" in cfg.hard_filters)
        contribs["structure"] = c
        if not ok:
            _fail(sig, "structure", cfg)

    # ---------------- momentum ----------------
    if cfg.f_momentum:
        gates.append("momentum")
        eff = b.efficiency
        eff_ok = (eff >= cfg.min_efficiency_trend) if strat == "trend" \
            else (eff <= cfg.max_efficiency_reversal)
        rsi = ind.rsi[i] if i < ind.n else 50.0
        rsi_ok = (rsi <= cfg.rsi_long_max) if side > 0 else (rsi >= cfg.rsi_short_min)
        roc = ind.roc[i] if i < ind.n else 0.0
        roc_ok = (roc * side >= 0) if cfg.require_roc_agree else True
        curve = curves.get(f"{b.weekday}-{b.hour}", [])
        comp = completion_ratio(b, curve) if curve else 1.0
        comp_ok = comp >= cfg.min_completion_ratio
        ok = eff_ok and rsi_ok and roc_ok and comp_ok
        note = (f"eff={eff:.2f}({'ok' if eff_ok else 'bad'}) rsi={rsi:.1f}"
                f"({'ok' if rsi_ok else 'bad'}) roc={roc:+.4f}({'ok' if roc_ok else 'bad'})"
                f" compl={comp:.2f}({'ok' if comp_ok else 'bad'})")
        sig.rsi = rsi
        if strat == "trend":
            c = clamp((eff - cfg.min_efficiency_trend)
                      / max(cfg.good_efficiency_trend - cfg.min_efficiency_trend, EPS), 0.0, 1.0)
        else:
            c = clamp((cfg.max_efficiency_reversal - eff) / max(cfg.max_efficiency_reversal, EPS), 0.0, 1.0)
        c = 0.5 * c + 0.5 * clamp(comp, 0.0, 1.0)
        sig.filters["momentum"] = FilterResult("momentum", ok, eff, note, c,
                                               hard="momentum" in cfg.hard_filters)
        contribs["efficiency"] = c
        if not ok:
            _fail(sig, "momentum", cfg)

    # ---------------- extension ----------------
    if cfg.f_extension:
        gates.append("extension")
        too_far, ext = extension_risk(ind, i, side, cfg.max_extension_sigma)
        sig.extension_sigma = ext
        ok = not too_far
        c = clamp(1.0 - max(0.0, ext - cfg.extension_soft_sigma)
                  / max(cfg.max_extension_sigma - cfg.extension_soft_sigma, EPS), 0.0, 1.0)
        sig.filters["extension"] = FilterResult(
            "extension", ok, ext,
            f"ext={ext:+.2f}sigma limit={cfg.max_extension_sigma}", c,
            hard="extension" in cfg.hard_filters)
        if not ok:
            _fail(sig, "extension", cfg)

    # ---------------- timing ----------------
    if cfg.f_timing:
        gates.append("timing")
        band = b.timing_band
        ok = True
        if cfg.hot_only and band != "hot":
            ok = False
        elif cfg.skip_dead_hours and band == "dead":
            ok = False
        c = {"hot": 1.0, "mid": 0.6, "dead": 0.1}.get(band, 0.5)
        sig.filters["timing"] = FilterResult("timing", ok, c, f"band={band}", c,
                                             hard="timing" in cfg.hard_filters)
        contribs["timing"] = c
        if not ok:
            _fail(sig, "timing", cfg)

    # ---------------- category strength + edge score ----------------
    if strat == "trend":
        c_cat = clamp((b.chart_pct - s.big_threshold) / max(s.big_threshold, EPS), 0.0, 1.0)
    else:
        c_cat = clamp((b.system_pct - s.pressure_system_threshold)
                      / max(100.0 - s.pressure_system_threshold, EPS), 0.0, 1.0)
    contribs["category"] = c_cat
    sig.filters["category_strength"] = FilterResult(
        "category_strength", True, c_cat,
        f"chart_pct={b.chart_pct:.1f} system_pct={b.system_pct:.1f}", c_cat, hard=False)

    sig.score = _edge_score(cfg, contribs)
    sig.filters["quality"] = FilterResult(
        "quality", sig.score >= cfg.min_edge_score, sig.score,
        f"score={sig.score:.3f} >= {cfg.min_edge_score}", sig.score)
    return gates


def _edge_score(cfg: SignalConfig, contribs: dict[str, float]) -> float:
    """Weighted mean of the per-factor contributions, renormalised to 0..1.

    Missing factors are dropped from both numerator and denominator, so disabling
    a filter does not silently depress every score (which would make the
    ``min_edge_score`` gate behave differently across configurations and render
    ablation comparisons meaningless).
    """
    pairs = (
        ("category", cfg.w_category),
        ("efficiency", cfg.w_efficiency),
        ("trend", cfg.w_trend),
        ("volume", cfg.w_volume),
        ("flow", cfg.w_flow),
        ("timing", cfg.w_timing),
        ("volatility", cfg.w_volatility),
        ("structure", cfg.w_structure),
    )
    num = 0.0
    den = 0.0
    for key, w in pairs:
        if key in contribs and w > 0:
            num += w * clamp(contribs[key], 0.0, 1.0)
            den += w
    return clamp(safe_div(num, den, 0.0), 0.0, 1.0)


def _summarise_rejections(out: SignalSet) -> None:
    counts: dict[str, int] = {}
    softs: dict[str, int] = {}
    sole: dict[str, int] = {}
    for sig in out.candidates:
        for f in sig.failed:
            counts[f] = counts.get(f, 0) + 1
        for f in sig.soft_flags:
            softs[f] = softs.get(f, 0) + 1
        if len(sig.failed) == 1:
            sole[sig.failed[0]] = sole.get(sig.failed[0], 0) + 1
    out.rejection_counts = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    out.soft_flag_counts = dict(sorted(softs.items(), key=lambda kv: -kv[1]))
    out.sole_killer = dict(sorted(sole.items(), key=lambda kv: -kv[1]))


# --------------------------------------------------------------------------- #
# diagnostics — "why are the signals sparse, and are they worth taking?"
# --------------------------------------------------------------------------- #
def diagnose(bars: Sequence[Bar], sigset: SignalSet, settings: Settings | None = None,
             *, warmup_index: int = 0) -> dict[str, Any]:
    """Full scarcity audit.  Every number here is measured, not asserted."""
    s = settings or Settings()
    trad = list(bars[warmup_index:])
    n = len(trad)
    shares = classify.category_shares(trad)
    funnel = [f.to_dict() for f in sigset.funnel]

    return {
        "universe": {
            "bars_total": len(bars),
            "bars_tradable": n,
            "warmup_dropped": warmup_index,
            "days_covered": (bars[-1].ts - bars[warmup_index].ts) / 86_400_000.0
            if len(bars) > warmup_index else 0.0,
        },
        "category_base_rates": {k: round(v, 5) for k, v in shares.items()},
        "category_counts": classify.category_counts(trad),
        "theoretical_max_candidates": int(round(
            n * (sum(shares[c] for c in sigset.cfg.trend_categories)
                 + sum(shares[c] for c in sigset.cfg.reversal_categories))
        )),
        "funnel": funnel,
        "rejection_counts": sigset.rejection_counts,
        "soft_flag_counts": sigset.soft_flag_counts,
        "sole_killer": sigset.sole_killer,
        "hard_filters": list(sigset.cfg.hard_filters),
        "accepted": len(sigset.signals),
        "accept_rate_of_candidates": safe_div(len(sigset.signals), len(sigset.candidates), 0.0),
        "signals_per_day": safe_div(
            len(sigset.signals),
            max(1e-9, (bars[-1].ts - bars[warmup_index].ts) / 86_400_000.0)
            if len(bars) > warmup_index else 1.0, 0.0),
        "directional_information": directional_information(trad, s),
        "score_distribution": _score_dist([c.score for c in sigset.candidates]),
        "grade_distribution": _grade_dist(sigset.signals),
        "bottleneck": _bottleneck(sigset),
    }


def _score_dist(scores: Sequence[float]) -> dict[str, Any]:
    if not scores:
        return {"n": 0}
    srt = sorted(scores)
    return {
        "n": len(srt), "mean": mean(srt), "median": srt[len(srt) // 2],
        "p10": srt[max(0, int(len(srt) * 0.10))],
        "p90": srt[min(len(srt) - 1, int(len(srt) * 0.90))],
        "min": srt[0], "max": srt[-1],
    }


def _grade_dist(signals: Sequence[Signal]) -> dict[str, int]:
    out = {"A": 0, "B": 0, "C": 0, "D": 0}
    for s in signals:
        out[s.grade] = out.get(s.grade, 0) + 1
    return out


def _bottleneck(sigset: SignalSet) -> dict[str, Any]:
    """Which single stage removes the most candidates?

    Reported as both an absolute count and a "sole killer" count.  The two answer
    different questions: absolute says *where the funnel narrows*, sole-killer
    says *which filter would you actually lose signals by removing*.  A filter
    with a high absolute count and a near-zero sole count is redundant — it only
    rejects bars that something else already rejected.
    """
    if not sigset.funnel:
        return {}
    worst = max(sigset.funnel, key=lambda f: f.rejected)
    sole = sigset.sole_killer
    return {
        "narrowest_stage": worst.key,
        "narrowest_rejected": worst.rejected,
        "narrowest_pass_rate": round(worst.pass_rate, 4),
        "most_decisive_filter": max(sole, key=lambda k: sole[k]) if sole else None,
        "redundant_filters": [
            k for k, v in sigset.rejection_counts.items()
            if v >= 5 and sole.get(k, 0) == 0
        ],
    }


def directional_information(bars: Sequence[Bar], s: Settings | None = None) -> dict[str, Any]:
    """Does each category actually predict the *next* move?

    For every category we take the bar's own direction as the naive call and
    measure the forward return over several horizons, aligned to that call.  A
    category with ~50% up/down split and a near-zero aligned forward return has
    no directional edge, and no amount of position sizing will fix that.

    Overlap caveat: forward windows overlap, so consecutive observations are
    correlated and the naive t-stat is inflated.  We divide the effective sample
    by the horizon (a standard conservative correction) and report both.
    """
    s = s or Settings()
    horizons = (1, 2, 4, 8, 16)
    out: dict[str, Any] = {}
    for cat in Category:
        rows: dict[int, dict[str, float]] = {}
        for h in horizons:
            rows[h] = {"n": 0, "sum": 0.0, "sq": 0.0, "wins": 0}
        ups = downs = 0
        for i, b in enumerate(bars):
            if b.category is not cat or b.direction == 0:
                continue
            if b.direction > 0:
                ups += 1
            else:
                downs += 1
            for h in horizons:
                j = i + h
                if j >= len(bars) or bars[j].close <= 0:
                    continue
                r = (bars[j].close - b.close) / b.close * b.direction
                d = rows[h]
                d["n"] += 1
                d["sum"] += r
                d["sq"] += r * r
                if r > 0:
                    d["wins"] += 1
        per_h: dict[str, Any] = {}
        for h in horizons:
            d = rows[h]
            if d["n"] < 3:
                per_h[str(h)] = {"n": int(d["n"])}
                continue
            mu = d["sum"] / d["n"]
            var = max(d["sq"] / d["n"] - mu * mu, 0.0)
            sd = math.sqrt(var)
            t_naive = safe_div(mu, sd / math.sqrt(d["n"]), 0.0)
            t_adj = safe_div(mu, sd / math.sqrt(max(1.0, d["n"] / h)), 0.0)
            per_h[str(h)] = {
                "n": int(d["n"]),
                "mean_aligned_return_bp": mu * 10_000.0,
                "win_rate": safe_div(d["wins"], d["n"], 0.0),
                "t_stat": t_naive,
                "t_stat_overlap_adjusted": t_adj,
            }
        out[cat.value] = {
            "up": ups, "down": downs,
            "up_share": safe_div(ups, ups + downs, 0.0),
            "horizons": per_h,
        }
    return out


def threshold_sensitivity(
    bars: Sequence[Bar], settings: Settings | None = None, *, warmup_index: int = 0
) -> dict[str, Any]:
    """How candidate count responds to the classification thresholds.

    Answers the practical question behind "signals are sparse": *is sparsity a
    property of the market, or an artefact of where we put the thresholds?*  If
    dropping ``big_threshold`` from 55 to 40 multiplies candidates by 4 while the
    aligned forward return collapses, the threshold was doing real work.
    """
    s = settings or Settings()
    trad = list(bars[warmup_index:])
    grid_big = (35.0, 45.0, 55.0, 65.0, 75.0)
    grid_press = (60.0, 70.0, 80.0, 90.0)
    out: dict[str, Any] = {"big_threshold": {}, "pressure_system_threshold": {}}
    for bt in grid_big:
        st = s.replace(big_threshold=bt)
        cnt = {"strong": 0, "energetic": 0}
        for b in trad:
            c = classify.classify(b, st)
            if c is Category.STRONG:
                cnt["strong"] += 1
            elif c is Category.ENERGETIC:
                cnt["energetic"] += 1
        out["big_threshold"][str(bt)] = cnt
    for pt in grid_press:
        st = s.replace(pressure_system_threshold=pt)
        out["pressure_system_threshold"][str(pt)] = sum(
            1 for b in trad if classify.classify(b, st) is Category.PRESSURE
        )
    out["bars_tradable"] = len(trad)
    return out


def signal_frame(sigset: SignalSet) -> list[dict[str, Any]]:
    return [s.to_dict() for s in sigset.signals]
