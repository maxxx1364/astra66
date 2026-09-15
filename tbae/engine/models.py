"""Data containers, Settings, palette and bilingual labels.

Everything in this module is a plain dataclass with ``slots``: the engine moves
tens of thousands of bars around, so per-object overhead matters.

Timestamp convention
--------------------
All timestamps are **unix epoch milliseconds** marking the *start* of a period.
A 1-minute bar with ``ts = T`` covers ``[T, T + 60_000)``.

Design note — why bars keep their minute path
---------------------------------------------
:class:`Bar.minutes` retains the source 1-minute bars that formed the aggregate.
This is the single most important structural decision in the engine: it is what
lets ``backtest`` resolve *in which order* the high and the low occurred inside a
bar, instead of guessing.  Guessing that order is the classic source of
over-optimistic backtests (a bar whose high precedes its low turns a losing
long into a winning one).  See ``backtest._resolve_intrabar_path``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from enum import Enum
from typing import Any, Iterable, Sequence

MINUTE_MS = 60_000
SUPPORTED_TIMEFRAMES: tuple[int, ...] = (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440)


# --------------------------------------------------------------------------- #
# palette + bilingual labels (kept next to the categories on purpose)
# --------------------------------------------------------------------------- #
class Lang(str, Enum):
    FA = "fa"
    EN = "en"


#: canonical colour keys -> hex.  The UI consumes keys, never raw hex, so a
#: custom user rule can re-point a key without touching engine logic.
COLORS: dict[str, str] = {
    "weak": "#8a94a6",       # grey
    "pressure": "#a855f7",   # purple
    "energetic": "#1e3a8a",  # navy
    "strong": "#3b82f6",     # blue
    "medium_up": "#22c55e",  # green
    "medium_down": "#f97316",  # orange
    "timing_dead": "#eab308",   # yellow
    "timing_mid": "#8b5a2b",    # brown
    "timing_hot": "#dc2626",    # red
    "long": "#22c55e",
    "short": "#ef4444",
    "flat": "#8a94a6",
}


class Category(str, Enum):
    """The five-way decision tree of the source specification.

    Ordering is load-bearing: ``classify.classify`` returns the **first**
    matching rule, so WEAK must be tested before PRESSURE and ENERGETIC before
    STRONG.  Do not re-order members.
    """

    WEAK = "weak"
    PRESSURE = "pressure"
    ENERGETIC = "energetic"
    STRONG = "strong"
    MEDIUM = "medium"


#: ``Category`` -> (fa, en, colour key).  MEDIUM resolves to two colour keys
#: depending on direction, so its entry holds a callable-free pair and
#: ``category_color_key`` disambiguates.
CATEGORY_LABELS: dict[Category, tuple[str, str, str]] = {
    Category.WEAK: ("ضعیف", "Weak", "weak"),
    Category.PRESSURE: ("پرفشار", "Pressure", "pressure"),
    Category.ENERGETIC: ("پرانرژی", "Energetic", "energetic"),
    Category.STRONG: ("قوی", "Strong", "strong"),
    Category.MEDIUM: ("متوسط", "Medium", "medium_up"),
}

#: rule index -> one-line predicate, exported so docs/API and tests stay honest
#: about what the tree actually does (mirrors README section 3).
CATEGORY_RULES: dict[Category, str] = {
    Category.WEAK: "chart_pct < weak AND system_pct < weak",
    Category.PRESSURE: "system_pct >= pressure AND chart_pct < weak",
    Category.ENERGETIC: "chart_pct >= big AND system_pct >= big",
    Category.STRONG: "chart_pct >= big AND system_pct < big",
    Category.MEDIUM: "otherwise",
}


def category_label(cat: Category, lang: Lang | str = Lang.FA) -> str:
    fa, en, _ = CATEGORY_LABELS[Category(cat)]
    return fa if str(lang) in ("fa", "Lang.FA") else en


def category_color_key(cat: Category, direction: int = 0) -> str:
    """Colour key for a category, disambiguating MEDIUM by direction."""
    cat = Category(cat)
    if cat is Category.MEDIUM:
        return "medium_down" if direction < 0 else "medium_up"
    return CATEGORY_LABELS[cat][2]


def category_color(cat: Category, direction: int = 0) -> str:
    return COLORS[category_color_key(cat, direction)]


# --------------------------------------------------------------------------- #
# raw input
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class MinuteBar:
    """One source 1-minute candle.  The atomic unit of the whole engine."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    quote_volume: float = 0.0
    #: taker (aggressor) buy volume — lets us build a flow-imbalance proxy.
    taker_buy_volume: float = 0.0
    trades: int = 0

    @property
    def body(self) -> float:
        return self.close - self.open

    @property
    def rng(self) -> float:
        return self.high - self.low

    @property
    def direction(self) -> int:
        return 1 if self.close > self.open else (-1 if self.close < self.open else 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MinuteBar":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# --------------------------------------------------------------------------- #
# aggregated, annotated bar
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Bar:
    """An aggregated timeframe bar carrying every derived quantity.

    Fields are grouped: identity/OHLCV, then system-bar decomposition, then
    volatility, then dynamic-reference annotation, then classification.  Keeping
    them on one object (rather than parallel arrays) makes the pipeline trivially
    serialisable and avoids index-alignment bugs — a class of bug that is very
    expensive in a backtester.
    """

    # identity + OHLCV
    ts: int
    tf: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    quote_volume: float = 0.0
    taker_buy_volume: float = 0.0
    trades: int = 0
    n_minutes: int = 0

    # --- system bar (non-neutralised mobility) ---
    s_total: float = 0.0      # S  = sum |close-to-close legs|
    s_up: float = 0.0         # sum of positive legs
    s_down: float = 0.0       # sum of |negative legs|
    s_intra: float = 0.0      # sum of minute (high - low) — intra-minute wicks
    s_first_leg: float = 0.0  # |close_1 - open_1|, exposed for diagnostics
    chart_abs: float = 0.0    # |close_n - open_1|
    chart_range: float = 0.0  # high - low
    efficiency: float = 0.0   # chart_abs / S, clipped to [0, 1]
    leg_skew: float = 0.0     # (S_up - S_down) / S in [-1, 1]

    # --- volatility (engine.volatility) ---
    true_range: float = 0.0
    atr: float = 0.0          # Wilder-smoothed ATR, in price units
    atr_pct: float = 0.0      # atr / close * 100
    rv: float = 0.0           # minute realised vol over the bar (price units)
    gk: float = 0.0           # Garman-Klass range estimator (price units)
    sigma: float = 0.0        # blended per-bar sigma used by risk/exits
    sigma_atr: float = 0.0    # smoothed sigma (ATR-like) for stable sizing
    vol_regime: float = 0.0   # sigma / rolling median sigma  (~1.0 = normal)

    # --- dynamic 100% reference (engine.reference) ---
    chart_ref: float = 0.0
    system_ref: float = 0.0
    chart_pct: float = 0.0    # 0..100+ (can exceed 100 for Max Bars)
    system_pct: float = 0.0
    is_max_bar: bool = False  # trimmed as an outlier when building the reference

    # --- classification ---
    category: Category = Category.MEDIUM
    color_key: str = "medium_up"
    color: str = COLORS["medium_up"]

    # --- context filled by pipeline (anchors / indicators) ---
    vwap: float = 0.0         # session-anchored VWAP at bar close
    session_open: float = 0.0

    # --- timing map (engine.timing) ---
    weekday: int = -1         # 0 = Monday
    hour: int = -1            # 0..23 UTC
    timing_score: float = 0.0
    timing_band: str = "mid"  # dead | mid | hot

    minute_path: tuple[MinuteBar, ...] | None = None

    # ---- derived helpers ----
    @property
    def body(self) -> float:
        return self.close - self.open

    @property
    def direction(self) -> int:
        return 1 if self.close > self.open else (-1 if self.close < self.open else 0)

    @property
    def rng(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def wick_ratio(self) -> float:
        """Share of the range that is *not* body — a rejection/exhaustion proxy."""
        r = self.rng
        return (r - abs(self.body)) / r if r > 0 else 0.0

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    def to_dict(self, include_path: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ts": self.ts,
            "tf": self.tf,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "quote_volume": self.quote_volume,
            "trades": self.trades,
            "n_minutes": self.n_minutes,
            "direction": self.direction,
            "body": self.body,
            "range": self.rng,
            "upper_wick": self.upper_wick,
            "lower_wick": self.lower_wick,
            "wick_ratio": self.wick_ratio,
            "s_total": self.s_total,
            "s_up": self.s_up,
            "s_down": self.s_down,
            "s_intra": self.s_intra,
            "chart_abs": self.chart_abs,
            "chart_range": self.chart_range,
            "efficiency": self.efficiency,
            "leg_skew": self.leg_skew,
            "true_range": self.true_range,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "rv": self.rv,
            "gk": self.gk,
            "sigma": self.sigma,
            "sigma_atr": self.sigma_atr,
            "vol_regime": self.vol_regime,
            "chart_ref": self.chart_ref,
            "system_ref": self.system_ref,
            "chart_pct": self.chart_pct,
            "system_pct": self.system_pct,
            "is_max_bar": self.is_max_bar,
            "category": self.category.value,
            "color_key": self.color_key,
            "color": self.color,
            "vwap": self.vwap,
            "session_open": self.session_open,
            "weekday": self.weekday,
            "hour": self.hour,
            "timing_score": self.timing_score,
            "timing_band": self.timing_band,
        }
        if include_path and self.minute_path is not None:
            d["minutes"] = [m.to_dict() for m in self.minute_path]
        return d


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Settings:
    """Every tunable of the *research* engine (classification/reference/timing).

    Strategy tunables live in :class:`engine.signals.SignalConfig`,
    :class:`engine.risk.RiskConfig` and :class:`engine.exits.ExitConfig` so that
    a research run and a strategy run can be versioned independently.
    """

    timeframe: int = 15

    # dynamic 100% reference
    reference_percentile: float = 98.0
    reference_max_outlier_share: float = 0.02
    #: ``"expanding"`` (causal — only history up to bar i), ``"rolling"``
    #: (causal, fixed window) or ``"full"`` (**look-ahead**, research only).
    #:
    #: This matters more than it looks.  ``chart_pct`` / ``system_pct`` drive the
    #: category tree, which drives every signal.  If the 100% reference is taken
    #: from the *whole* sample then bar #10 is scored against volatility that
    #: only happened at bar #4000 — the backtest quietly knows the future and
    #: reports an edge that cannot be traded.  ``pipeline`` therefore defaults to
    #: causal, and ``backtest`` refuses ``"full"`` unless explicitly overridden.
    reference_mode: str = "expanding"
    #: window length for ``reference_mode="rolling"``; 0 = all available history.
    reference_window: int = 0
    #: bars required before the reference (and thus categories) are emitted.
    reference_min_bars: int = 200

    # classification thresholds, in percent of the reference
    weak_threshold: float = 20.0
    big_threshold: float = 55.0
    pressure_system_threshold: float = 80.0

    # timing heatmap
    timing_dead_share: float = 0.33
    timing_hot_share: float = 0.25
    timing_weight_system: float = 0.50
    timing_weight_chart: float = 0.35
    timing_weight_efficiency: float = 0.15
    #: ``"expanding"`` = each bar is scored against the day-of-week/hour
    #: statistics of the bars *before* it (causal).  ``"full"`` uses the whole
    #: sample (look-ahead, research/dashboard only).
    timing_mode: str = "expanding"
    timing_min_bars: int = 500

    # session anchor for VWAP / session-open (0 = UTC midnight)
    session_start_hour: int = 0

    # volatility
    atr_period: int = 14
    vol_regime_period: int = 100
    sigma_w_gk: float = 0.5      # blend weight: Garman-Klass range estimator
    sigma_w_rv: float = 0.5      # blend weight: minute realised volatility

    # engine behaviour
    keep_minute_path: bool = True
    min_minutes_per_bar: int = 1  # drop aggregates built from fewer minutes

    def validate(self) -> "Settings":
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"timeframe {self.timeframe} not in {SUPPORTED_TIMEFRAMES}"
            )
        if not 0.0 <= self.reference_max_outlier_share < 0.5:
            raise ValueError("reference_max_outlier_share must be in [0, 0.5)")
        if not 0.0 < self.reference_percentile <= 100.0:
            raise ValueError("reference_percentile must be in (0, 100]")
        for name in ("weak_threshold", "big_threshold", "pressure_system_threshold"):
            v = getattr(self, name)
            if not 0.0 <= v <= 500.0:
                raise ValueError(f"{name} must be in [0, 500], got {v}")
        w = (
            self.timing_weight_system
            + self.timing_weight_chart
            + self.timing_weight_efficiency
        )
        if abs(w - 1.0) > 1e-6:
            raise ValueError(f"timing weights must sum to 1.0, got {w}")
        if self.atr_period < 1:
            raise ValueError("atr_period must be >= 1")
        if self.sigma_w_gk < 0 or self.sigma_w_rv < 0:
            raise ValueError("sigma blend weights must be non-negative")
        if self.sigma_w_gk + self.sigma_w_rv <= 0:
            raise ValueError("sigma blend weights must not both be zero")
        if self.reference_mode not in ("expanding", "rolling", "full"):
            raise ValueError(
                f"reference_mode must be expanding|rolling|full, got {self.reference_mode!r}"
            )
        if self.timing_mode not in ("expanding", "full"):
            raise ValueError(
                f"timing_mode must be expanding|full, got {self.timing_mode!r}"
            )
        if self.reference_min_bars < 2:
            raise ValueError("reference_min_bars must be >= 2")
        if self.reference_window < 0:
            raise ValueError("reference_window must be >= 0")
        if self.reference_mode == "rolling" and self.reference_window == 0:
            raise ValueError('reference_mode="rolling" requires reference_window > 0')
        return self

    def replace(self, **kw: Any) -> "Settings":
        base = asdict(self)
        base.update(kw)
        return Settings(**base).validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# small shared value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Side:
    """Trade direction constants (a class, not an Enum, so it stays an int)."""

    LONG: int = 1
    SHORT: int = -1
    FLAT: int = 0

    @staticmethod
    def name(side: int) -> str:
        return {1: "long", -1: "short", 0: "flat"}[int(side)]

    @staticmethod
    def color(side: int) -> str:
        return COLORS[Side.name(side)]


@dataclass(slots=True)
class TimingCell:
    """One (weekday, hour) cell of the 7x24 heatmap."""

    weekday: int
    hour: int
    bars: int = 0
    #: Cell score in **[0, 1]**: a weighted sum of the quantile ranks (across
    #: cells) of mean_system_pct / mean_chart_pct / mean_efficiency, with weights
    #: ``timing_weight_system`` / ``_chart`` / ``_efficiency``.  Rank-normalising
    #: each component first is what makes those weights meaningful — the raw
    #: components have incompatible units (percent vs ratio), so weighting them
    #: directly would let the two percentage terms drown out efficiency entirely.
    score: float = 0.0
    mean_system_pct: float = 0.0
    mean_chart_pct: float = 0.0
    mean_efficiency: float = 0.0
    #: Un-normalised weighted sum of the raw component means.  Diagnostic only —
    #: not comparable across runs and not used for banding.
    raw_score: float = 0.0
    band: str = "mid"  # dead | mid | hot
    color: str = COLORS["timing_mid"]

    @property
    def key(self) -> str:
        return f"{self.weekday}-{self.hour}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekday": self.weekday,
            "hour": self.hour,
            "bars": self.bars,
            "score": self.score,
            "raw_score": self.raw_score,
            "mean_system_pct": self.mean_system_pct,
            "mean_chart_pct": self.mean_chart_pct,
            "mean_efficiency": self.mean_efficiency,
            "band": self.band,
            "color": self.color,
        }


@dataclass(slots=True)
class PathPoint:
    """One sample of the intra-bar growth curve (``engine.path``)."""

    minute_index: int
    ts: int
    formed_abs: float
    formed_pct: float   # 0..1 of the fully-formed bar
    elapsed_pct: float  # 0..1 of the bar's duration


def bars_to_dicts(bars: Iterable[Bar], include_path: bool = False) -> list[dict[str, Any]]:
    return [b.to_dict(include_path) for b in bars]


def timeframe_ms(tf: int) -> int:
    return int(tf) * MINUTE_MS


def align_ts(ts: int, tf: int) -> int:
    """Floor a millisecond timestamp to the start of its ``tf``-minute bucket."""
    step = timeframe_ms(tf)
    return (ts // step) * step


def ts_range(bars: Sequence[Bar]) -> tuple[int, int]:
    if not bars:
        return (0, 0)
    return (bars[0].ts, bars[-1].ts)
