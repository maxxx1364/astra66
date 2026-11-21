"""Volume-flow state: tick volume and size-weighted delta as percentages.

What this module measures
-------------------------
The bar classifier in :mod:`classify` reads *price* displacement.  This module
reads the *order flow* behind it, on two axes:

* **volume** — how much traded in the bar;
* **weighted delta** — aggressive buying minus aggressive selling, where every
  trade counts by its *size*.  ``delta = taker_buy_volume - taker_sell_volume``
  ``= 2 * taker_buy_volume - volume``.  A plain tick delta (count of up-ticks
  minus down-ticks) treats a one-lot print and a thousand-lot print as equal, so
  a burst of small noise can outvote one decisive order.  Weighting by size is
  what makes the delta read the side that actually moved money.

Both are converted to percentages of a **dynamic 100% reference** built exactly
like the price reference (:func:`reference.build_reference`): sort the trailing
window, drop the top ``max_outlier_share`` as *Max* values, and take the
``reference_percentile`` of the rest as 100%.  Trimming first matters: a
liquidation spike can carry many times the market's normal capacity, and
letting it define 100% would squeeze every normal state into the bottom decile.
Values at or above 100% are the ones that trimming set aside — they are
labelled ``max`` instead of distorting the scale.

States
------
States are assigned per **block** of ``block`` consecutive chart bars (4 by
default: a 1h chart is read in 4h blocks, a 5m chart in 20m blocks), aligned to
clock boundaries.  Three levels are read on every axis: weak (< ``weak``),
medium, strong (>= ``big``).  Delta is *balanced* when ``|delta%| < weak``.
A balanced block can never be a trend.  First match wins:

    1 max         vol% >= max_level                          beyond the trimmed reference
    2 explosive   volume < trailing mean AND move% >= big    thin, fast move
    -- balanced delta (buyers ~ sellers) ------------------------------------
    3 pressure    vol% >= big                                heavy two-sided fight
    4 balanced    vol% >= weak                               white: real volume, no side wins
    5 quiet       otherwise                                  yellow: little volume, little move
    -- one-sided delta -------------------------------------------------------
    6 strong      price followed the delta (move% >= weak) AND vol% >= big
    7 trend       price followed the delta, volume weak or medium   green
    8 absorption  price did not follow the delta             the aggressive side was absorbed

Colours: quiet yellow, balanced white, trend green, strong blue, pressure
purple, absorption pink, explosive orange, max red.

Effort vs result
----------------
:func:`effort_result_lines` gives two parallel lines on one percentage scale:
**volume%** (effort) and **move%** (result) over the last ``block`` bars.  Both
high = strong; both low = quiet; volume above price = effort without result
(pressure/absorption); price above volume = result without effort (explosive).
Where they cross is where the market changes between those regimes.

Causality
---------
Every reference is built from blocks strictly *before* the one being scored,
so a block's state uses no future data.  A block's state is final only when
the block closes; on a live chart the forming block repaints until then.  The
reference is rebuilt every ``refresh_blocks`` blocks rather than every block —
a sort per block over a 30-day window is the only expensive step, and a daily
refresh changes the percentages by a fraction of a point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .reference import build_reference

STATES = ("max", "explosive", "pressure", "balanced", "quiet", "strong", "trend", "absorption")

#: The user's colour scheme: balanced-delta ranges white/yellow, gentle trend green.
STATE_COLORS = {
    "quiet": "#F5C518",
    "balanced": "#F2F2F2",
    "trend": "#2E9E44",
    "strong": "#1F5FD1",
    "pressure": "#7B3FB8",
    "absorption": "#E26FA8",
    "explosive": "#F07C1A",
    "max": "#D3242B",
    "unready": "#9AA0A6",
}

STATE_LABELS_FA = {
    "quiet": "زرد: حجم و حرکت ضعیف، دلتای برابر",
    "balanced": "سفید: حجم بالا، حرکت ضعیف، دلتای برابر",
    "trend": "سبز: روند نرمال",
    "strong": "آبی: قوی",
    "pressure": "بنفش: پرفشار",
    "absorption": "صورتی: جذب",
    "explosive": "نارنجی: انفجاری",
    "max": "قرمز: مکس",
    "unready": "بدون مرجع",
}


@dataclass
class FlowConfig:
    block: int = 4
    reference_window_days: float = 30.0
    reference_percentile: float = 98.0
    max_outlier_share: float = 0.02
    #: blocks of history before a reference exists; earlier blocks are 'unready'
    min_reference_blocks: int = 60
    #: rebuild the reference every N blocks (None = once per day)
    refresh_blocks: int | None = None
    weak: float = 20.0
    big: float = 55.0
    max_level: float = 100.0

    def validate(self) -> "FlowConfig":
        if self.block < 1:
            raise ValueError("block must be >= 1")
        if not 0.0 < self.weak < self.big < self.max_level:
            raise ValueError("need 0 < weak < big < max_level")
        if self.min_reference_blocks < 2:
            raise ValueError("min_reference_blocks must be >= 2")
        return self


@dataclass
class FlowBar:
    """One chart bar (tf minutes) with its flow totals."""
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float
    trades: int = 0


@dataclass
class FlowBlock:
    """``block`` chart bars read together, with their percentages and state."""
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float
    n_bars: int
    bar_deltas: list[float] = field(default_factory=list)
    vol_pct: float | None = None
    delta_pct: float | None = None       # signed
    move_pct: float | None = None
    mean_volume: float | None = None
    consistency: int = 0
    ref_volume: float | None = None
    ref_delta: float | None = None
    ref_move: float | None = None
    state: str = "unready"

    @property
    def imbalance(self) -> float:
        return abs(self.delta) / self.volume if self.volume > 0 else 0.0

    @property
    def move(self) -> float:
        return self.close - self.open

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "open": self.open, "high": self.high, "low": self.low,
            "close": self.close, "volume": self.volume, "delta": self.delta,
            "vol_pct": self.vol_pct, "delta_pct": self.delta_pct,
            "move_pct": self.move_pct, "imbalance": self.imbalance,
            "consistency": self.consistency, "state": self.state,
        }


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def _weighted_delta(m: Any) -> float:
    vol = float(getattr(m, "volume", 0.0) or 0.0)
    buy = float(getattr(m, "taker_buy_volume", 0.0) or 0.0)
    return 2.0 * buy - vol


def flow_bars(minutes: Sequence[Any], tf: int) -> list[FlowBar]:
    """Aggregate 1-minute candles into ``tf``-minute flow bars on clock boundaries."""
    if tf < 1:
        raise ValueError("tf must be >= 1")
    ms = tf * 60_000
    out: list[FlowBar] = []
    cur: FlowBar | None = None
    for m in minutes:
        key = (m.ts // ms) * ms
        if cur is None or key != cur.ts:
            cur = FlowBar(ts=key, open=float(m.open), high=float(m.high), low=float(m.low),
                          close=float(m.close), volume=0.0, delta=0.0)
            out.append(cur)
        cur.high = max(cur.high, float(m.high))
        cur.low = min(cur.low, float(m.low))
        cur.close = float(m.close)
        cur.volume += float(m.volume or 0.0)
        cur.delta += _weighted_delta(m)
        cur.trades += int(getattr(m, "trades", 0) or 0)
    return out


def flow_blocks(bars: Sequence[FlowBar], tf: int, block: int) -> list[FlowBlock]:
    """Group chart bars into blocks of ``block`` bars aligned to clock boundaries.

    A block missing bars (data gaps, the forming block at the end) is kept with
    its real ``n_bars`` so callers can drop it; it is never padded.
    """
    ms = tf * 60_000 * block
    out: list[FlowBlock] = []
    cur: FlowBlock | None = None
    for b in bars:
        key = (b.ts // ms) * ms
        if cur is None or key != cur.ts:
            cur = FlowBlock(ts=key, open=b.open, high=b.high, low=b.low, close=b.close,
                            volume=0.0, delta=0.0, n_bars=0)
            out.append(cur)
        cur.high = max(cur.high, b.high)
        cur.low = min(cur.low, b.low)
        cur.close = b.close
        cur.volume += b.volume
        cur.delta += b.delta
        cur.n_bars += 1
        cur.bar_deltas.append(b.delta)
    return out


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def classify_block(blk: FlowBlock, cfg: FlowConfig) -> str:
    """State of one block whose percentages are already filled in."""
    if blk.vol_pct is None or blk.delta_pct is None or blk.move_pct is None:
        return "unready"
    vp, dp, mp = blk.vol_pct, blk.delta_pct, blk.move_pct
    if vp >= cfg.max_level:
        return "max"
    if blk.mean_volume is not None and blk.volume < blk.mean_volume and mp >= cfg.big:
        return "explosive"
    if abs(dp) < cfg.weak:                       # balanced: never a trend
        if vp >= cfg.big:
            return "pressure"
        if vp >= cfg.weak:
            return "balanced"
        return "quiet"
    followed = mp >= cfg.weak and ((blk.move > 0 and dp > 0) or (blk.move < 0 and dp < 0))
    if followed:
        return "strong" if vp >= cfg.big else "trend"
    return "absorption"


def _trimmed_mean(values: Sequence[float], share: float) -> float:
    s = sorted(values)
    n_trim = int(len(s) * share)
    kept = s[: len(s) - n_trim] if 0 < n_trim < len(s) else s
    return sum(kept) / len(kept) if kept else 0.0


def annotate(blocks: Sequence[FlowBlock], tf: int, cfg: FlowConfig | None = None) -> list[FlowBlock]:
    """Fill percentages and state on every block, causally.

    The reference for block ``i`` comes only from complete blocks before ``i``
    inside the trailing ``reference_window_days``.
    """
    cfg = (cfg or FlowConfig()).validate()
    blocks = list(blocks)
    block_minutes = tf * cfg.block
    per_day = max(1, int(round(1440 / block_minutes)))
    window = max(cfg.min_reference_blocks, int(round(cfg.reference_window_days * per_day)))
    refresh = cfg.refresh_blocks or per_day
    complete = [b.n_bars == cfg.block for b in blocks]

    ref_vol = ref_delta = ref_move = mean_vol = None
    last_built = -10**9
    for i, blk in enumerate(blocks):
        if i - last_built >= refresh or ref_vol is None:
            hist = [blocks[j] for j in range(max(0, i - window), i) if complete[j]]
            if len(hist) >= cfg.min_reference_blocks:
                ref_vol, _ = build_reference([h.volume for h in hist], cfg.reference_percentile,
                                             cfg.max_outlier_share)
                ref_delta, _ = build_reference([abs(h.delta) for h in hist], cfg.reference_percentile,
                                               cfg.max_outlier_share)
                ref_move, _ = build_reference([abs(h.move) for h in hist], cfg.reference_percentile,
                                              cfg.max_outlier_share)
                mean_vol = _trimmed_mean([h.volume for h in hist], cfg.max_outlier_share)
                last_built = i
        if not ref_vol or not ref_delta or not ref_move:
            blk.state = "unready"
            continue
        blk.vol_pct = 100.0 * blk.volume / ref_vol
        blk.delta_pct = 100.0 * blk.delta / ref_delta
        blk.move_pct = 100.0 * abs(blk.move) / ref_move
        blk.mean_volume = mean_vol
        blk.ref_volume, blk.ref_delta, blk.ref_move = ref_vol, ref_delta, ref_move
        sign = 1 if blk.delta > 0 else -1 if blk.delta < 0 else 0
        blk.consistency = sum(1 for d in blk.bar_deltas if sign and (d > 0) == (sign > 0) and d != 0)
        blk.state = classify_block(blk, cfg)
    return blocks


def bar_line(bars: Sequence[FlowBar], blocks: Sequence[FlowBlock], tf: int,
             cfg: FlowConfig | None = None) -> list[dict[str, Any]]:
    """Per chart bar: the delta%, volume% and move% of the last ``block`` bars
    (a rolling block, so the value equals the block's own at each block close),
    each scaled by the reference of the block the bar belongs to, plus that
    block's state for colouring.

    ``line`` is the signed delta line; ``vol_line`` and ``price_line`` are the
    two effort-vs-result lines.
    """
    cfg = cfg or FlowConfig()
    ms = tf * 60_000 * cfg.block
    by_ts = {b.ts: b for b in blocks}
    out: list[dict[str, Any]] = []
    for i, b in enumerate(bars):
        blk = by_ts.get((b.ts // ms) * ms)
        lo = max(0, i - cfg.block + 1)
        win = bars[lo:i + 1]
        ok = blk is not None and blk.ref_volume and blk.ref_delta and blk.ref_move and len(win) == cfg.block
        out.append({
            "ts": b.ts, "close": b.close,
            "line": 100.0 * sum(w.delta for w in win) / blk.ref_delta if ok else None,
            "vol_line": 100.0 * sum(w.volume for w in win) / blk.ref_volume if ok else None,
            "price_line": 100.0 * abs(b.close - win[0].open) / blk.ref_move if ok else None,
            "state": blk.state if blk is not None else "unready",
        })
    return out


def effort_result_lines(bars: Sequence[FlowBar], blocks: Sequence[FlowBlock], tf: int,
                        cfg: FlowConfig | None = None) -> list[dict[str, Any]]:
    """The two-line indicator: volume% (effort) and move% (result) per bar."""
    return [{"ts": p["ts"], "volume": p["vol_line"], "price": p["price_line"], "state": p["state"]}
            for p in bar_line(bars, blocks, tf, cfg)]


def states_for_bars(bars: Sequence[Any], cfg: FlowConfig | None = None) -> list[str]:
    """For each chart bar, the state of the last block that had **closed** by
    that bar's close — what a strategy deciding on that bar could know.

    ``bars`` are engine :class:`~engine.models.Bar` objects (or anything with
    ts/tf/open/high/low/close/volume/taker_buy_volume).  A bar that ends its
    block sees that block; any other bar sees the block before.
    """
    cfg = (cfg or FlowConfig()).validate()
    if not bars:
        return []
    tf = int(getattr(bars[0], "tf", 0) or 0)
    if tf <= 0:
        raise ValueError("bars must carry their timeframe in .tf")
    fbars = [FlowBar(ts=b.ts, open=float(b.open), high=float(b.high), low=float(b.low),
                     close=float(b.close), volume=float(b.volume or 0.0),
                     delta=2.0 * float(getattr(b, "taker_buy_volume", 0.0) or 0.0) - float(b.volume or 0.0))
             for b in bars]
    blocks = annotate(flow_blocks(fbars, tf, cfg.block), tf, cfg)
    span = tf * 60_000 * cfg.block
    by_ts = {blk.ts: blk for blk in blocks}
    out: list[str] = []
    for b in fbars:
        key = (b.ts // span) * span
        blk = by_ts.get(key)
        if blk is not None and b.ts + tf * 60_000 == key + span and blk.n_bars == cfg.block:
            out.append(blk.state)                   # this bar closes its block
        else:
            prev = by_ts.get(key - span)
            out.append(prev.state if prev is not None and prev.n_bars == cfg.block else "unready")
    return out


def state_shares(blocks: Sequence[FlowBlock]) -> dict[str, float]:
    ready = [b for b in blocks if b.state != "unready"]
    n = len(ready)
    return {s: (sum(1 for b in ready if b.state == s) / n if n else 0.0) for s in STATES}


__all__ = [
    "STATES", "STATE_COLORS", "STATE_LABELS_FA", "FlowConfig", "FlowBar", "FlowBlock",
    "flow_bars", "flow_blocks", "classify_block", "annotate", "bar_line",
    "effort_result_lines", "states_for_bars", "state_shares",
]
