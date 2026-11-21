"""Price-structure setups: order blocks and the third touch of a trendline.

Both detectors are **causal**: a setup is emitted at the close of the bar on
which everything it needs is known, and nothing later is read.  A swing point
of strength ``k`` at bar ``c`` is only known at bar ``c + k`` (the bars that
confirm it), and is never used before then.

Order block
-----------
A bullish order block is the last down candle before an impulsive up move
that breaks structure:

* **break of structure (BOS)** at bar ``i``: ``close[i]`` is the first close
  above the most recent *confirmed* swing high;
* **order-block candle** ``j``: the last bearish candle (close < open) in the
  ``ob_lookback`` bars before ``i``;
* **displacement**: ``close[i] - low[j] >= disp_atr * ATR`` — the move away
  from the block was impulsive, not a drift;
* **zone** ``[low[j], high[j]]``: proximal edge ``high[j]`` (the limit entry),
  distal edge ``low[j]`` (the stop sits ``stop_buffer_atr`` beyond it).

The setup is a resting limit at the proximal edge, valid from ``i + 1`` for
``ob_ttl`` bars, cancelled if a bar closes beyond the distal edge first, and
used **once** (the first retest).  Bearish blocks mirror it.

Trendline third touch
---------------------
An ascending support line is drawn through two confirmed swing lows ``a < b``
with ``low[b] > low[a]`` and at least ``min_gap`` bars apart.  The line is
only valid if no bar between them closed below it and no low pierced it by
more than ``touch_atr`` ATR.  It is then watched from ``b``'s confirmation:

* it **breaks** (and is dropped) on any close below the line;
* price must first move **away** — a close at least ``away_atr`` ATR above it;
* the **third touch** is the first bar after that whose low comes within
  ``touch_atr`` ATR of the line and which still **closes above** it.

The setup is a market entry at the next bar's open, stop ``stop_buffer_atr``
ATR below the touch bar's low or the line, whichever is lower.  A line is
used for one third touch and lines expire after ``max_line_age`` bars.
Descending resistance through two lower swing highs mirrors it for shorts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class SetupConfig:
    atr_period: int = 14
    swing_k: int = 3
    # order block
    ob_lookback: int = 10
    disp_atr: float = 1.5
    ob_ttl: int = 48
    ob_stop_buffer_atr: float = 0.10
    # trendline third touch
    min_gap: int = 5
    touch_atr: float = 0.25
    away_atr: float = 1.0
    max_line_age: int = 200
    pivots_per_line: int = 4            # how many earlier swings a new swing is paired with
    tl_stop_buffer_atr: float = 0.30
    # shared
    min_risk_atr: float = 0.20
    max_risk_atr: float = 4.0

    def validate(self) -> "SetupConfig":
        if self.swing_k < 1 or self.atr_period < 2:
            raise ValueError("swing_k >= 1 and atr_period >= 2 required")
        if self.ob_lookback < 1 or self.ob_ttl < 1 or self.disp_atr <= 0:
            raise ValueError("bad order-block parameters")
        if self.min_gap < 1 or self.touch_atr <= 0 or self.away_atr <= 0 or self.max_line_age < self.min_gap:
            raise ValueError("bad trendline parameters")
        if not 0 < self.min_risk_atr < self.max_risk_atr:
            raise ValueError("need 0 < min_risk_atr < max_risk_atr")
        return self


@dataclass
class Setup:
    kind: str                 # "order_block" | "trendline3"
    side: int                 # +1 long, -1 short
    signal_index: int         # bar at whose close the setup is known
    entry: str                # "limit" (rest at entry_price) | "market" (next bar's open)
    entry_price: float | None
    stop: float
    cancel_level: float | None = None   # limit is cancelled if a bar closes beyond this
    expires_index: int | None = None    # last bar on which a limit may fill
    atr: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


def atr_series(o: Sequence[float], h: Sequence[float], low: Sequence[float], c: Sequence[float],
               period: int = 14) -> list[float | None]:
    """Simple mean true range of the ``period`` bars ending at ``i`` (inclusive)."""
    n = len(c)
    tr = [0.0] * n
    for i in range(n):
        pc = c[i - 1] if i > 0 else o[i]
        tr[i] = max(h[i], pc) - min(low[i], pc)
    out: list[float | None] = [None] * n
    s = 0.0
    for i in range(n):
        s += tr[i]
        if i >= period:
            s -= tr[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def swing_points(h: Sequence[float], low: Sequence[float], k: int) -> tuple[list[int], list[int]]:
    """Indices of swing highs and lows of strength ``k`` (strict on the right,
    non-strict on the left).  Swing ``c`` is known only at bar ``c + k``."""
    n = len(h)
    highs, lows = [], []
    for c in range(k, n - k):
        if all(h[c + j] < h[c] for j in range(1, k + 1)) and all(h[c - j] <= h[c] for j in range(1, k + 1)):
            highs.append(c)
        if all(low[c + j] > low[c] for j in range(1, k + 1)) and all(low[c - j] >= low[c] for j in range(1, k + 1)):
            lows.append(c)
    return highs, lows


def _ohlc(bars: Sequence[Any]) -> tuple[list[float], list[float], list[float], list[float]]:
    return ([float(b.open) for b in bars], [float(b.high) for b in bars],
            [float(b.low) for b in bars], [float(b.close) for b in bars])


# --------------------------------------------------------------------------- #
# order blocks
# --------------------------------------------------------------------------- #
def order_blocks(bars: Sequence[Any], cfg: SetupConfig | None = None) -> list[Setup]:
    cfg = (cfg or SetupConfig()).validate()
    o, h, low, c = _ohlc(bars)
    n = len(c)
    atr = atr_series(o, h, low, c, cfg.atr_period)
    sh, sl = swing_points(h, low, cfg.swing_k)
    k = cfg.swing_k
    out: list[Setup] = []
    used: set[tuple[int, int]] = set()
    ih = il = 0
    last_high = last_low = None      # most recent swing known at bar i
    for i in range(1, n):
        while ih < len(sh) and sh[ih] + k <= i:
            last_high = sh[ih]
            ih += 1
        while il < len(sl) and sl[il] + k <= i:
            last_low = sl[il]
            il += 1
        a = atr[i]
        if a is None or a <= 0:
            continue
        lo_j = max(0, i - cfg.ob_lookback)
        # bullish: first close above the last confirmed swing high
        if last_high is not None and c[i] > h[last_high] >= c[i - 1]:
            j = next((x for x in range(i - 1, lo_j - 1, -1) if c[x] < o[x]), None)
            if j is not None and (1, j) not in used and c[i] - low[j] >= cfg.disp_atr * a:
                stop = low[j] - cfg.ob_stop_buffer_atr * a
                risk = h[j] - stop
                if cfg.min_risk_atr * a <= risk <= cfg.max_risk_atr * a:
                    used.add((1, j))
                    out.append(Setup("order_block", 1, i, "limit", h[j], stop, cancel_level=low[j],
                                     expires_index=min(n - 1, i + cfg.ob_ttl), atr=a,
                                     meta={"ob_index": j, "bos_level": h[last_high],
                                           "displacement_atr": (c[i] - low[j]) / a}))
        # bearish: first close below the last confirmed swing low
        if last_low is not None and c[i] < low[last_low] <= c[i - 1]:
            j = next((x for x in range(i - 1, lo_j - 1, -1) if c[x] > o[x]), None)
            if j is not None and (-1, j) not in used and h[j] - c[i] >= cfg.disp_atr * a:
                stop = h[j] + cfg.ob_stop_buffer_atr * a
                risk = stop - low[j]
                if cfg.min_risk_atr * a <= risk <= cfg.max_risk_atr * a:
                    used.add((-1, j))
                    out.append(Setup("order_block", -1, i, "limit", low[j], stop, cancel_level=h[j],
                                     expires_index=min(n - 1, i + cfg.ob_ttl), atr=a,
                                     meta={"ob_index": j, "bos_level": low[last_low],
                                           "displacement_atr": (h[j] - c[i]) / a}))
    return out


# --------------------------------------------------------------------------- #
# trendline third touch
# --------------------------------------------------------------------------- #
@dataclass
class _Line:
    side: int
    a: int
    b: int
    pa: float
    slope: float
    created: int
    away: bool = False

    def at(self, t: int) -> float:
        return self.pa + self.slope * (t - self.a)


def trendline_third_touches(bars: Sequence[Any], cfg: SetupConfig | None = None) -> list[Setup]:
    cfg = (cfg or SetupConfig()).validate()
    o, h, low, c = _ohlc(bars)
    n = len(c)
    atr = atr_series(o, h, low, c, cfg.atr_period)
    sh, sl = swing_points(h, low, cfg.swing_k)
    k = cfg.swing_k
    confirm: dict[int, list[tuple[int, int]]] = {}
    for idx in sl:
        confirm.setdefault(idx + k, []).append((1, idx))
    for idx in sh:
        confirm.setdefault(idx + k, []).append((-1, idx))
    known_lows: list[int] = []
    known_highs: list[int] = []
    lines: list[_Line] = []
    out: list[Setup] = []
    for i in range(n):
        a_i = atr[i]
        # 1) new lines from swings confirmed at this bar
        for side, b in confirm.get(i, []):
            pool = known_lows if side > 0 else known_highs
            if a_i is not None and a_i > 0:
                for a in pool[-cfg.pivots_per_line:]:
                    if b - a < cfg.min_gap:
                        continue
                    pa = low[a] if side > 0 else h[a]
                    pb = low[b] if side > 0 else h[b]
                    if side > 0 and pb <= pa:
                        continue                      # support must rise
                    if side < 0 and pb >= pa:
                        continue                      # resistance must fall
                    ln = _Line(side, a, b, pa, (pb - pa) / (b - a), created=i)
                    tol = cfg.touch_atr * a_i
                    ok = True
                    for t in range(a + 1, i + 1):
                        y = ln.at(t)
                        if side > 0 and (c[t] < y or (t < b and low[t] < y - tol)):
                            ok = False
                            break
                        if side < 0 and (c[t] > y or (t < b and h[t] > y + tol)):
                            ok = False
                            break
                    if ok:
                        lines.append(ln)
            pool.append(b)
        if a_i is None or a_i <= 0:
            continue
        # 2) update live lines on this bar
        keep: list[_Line] = []
        for ln in lines:
            if ln.created >= i:
                keep.append(ln)               # watched from the next bar
                continue
            if i - ln.b > cfg.max_line_age:
                continue
            y = ln.at(i)
            tol = cfg.touch_atr * a_i
            if ln.side > 0:
                if c[i] < y:
                    continue                  # broken
                if not ln.away:
                    if c[i] >= y + cfg.away_atr * a_i:
                        ln.away = True
                    keep.append(ln)
                    continue
                if low[i] <= y + tol:         # third touch, closed above: rejection
                    stop = min(low[i], y) - cfg.tl_stop_buffer_atr * a_i
                    risk_ref = c[i] - stop
                    if cfg.min_risk_atr * a_i <= risk_ref <= cfg.max_risk_atr * a_i and i + 1 < n:
                        out.append(Setup("trendline3", 1, i, "market", None, stop, atr=a_i,
                                         meta={"a": ln.a, "b": ln.b, "line": y,
                                               "slope_atr_per_bar": ln.slope / a_i}))
                    continue                  # one third touch per line
                keep.append(ln)
            else:
                if c[i] > y:
                    continue
                if not ln.away:
                    if c[i] <= y - cfg.away_atr * a_i:
                        ln.away = True
                    keep.append(ln)
                    continue
                if h[i] >= y - tol:
                    stop = max(h[i], y) + cfg.tl_stop_buffer_atr * a_i
                    risk_ref = stop - c[i]
                    if cfg.min_risk_atr * a_i <= risk_ref <= cfg.max_risk_atr * a_i and i + 1 < n:
                        out.append(Setup("trendline3", -1, i, "market", None, stop, atr=a_i,
                                         meta={"a": ln.a, "b": ln.b, "line": y,
                                               "slope_atr_per_bar": ln.slope / a_i}))
                    continue
                keep.append(ln)
        lines = keep
    # several lines can be touched on the same bar: keep one setup per bar and side
    seen: set[tuple[int, int]] = set()
    uniq: list[Setup] = []
    for s in out:
        key = (s.signal_index, s.side)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


__all__ = ["SetupConfig", "Setup", "atr_series", "swing_points", "order_blocks",
           "trendline_third_touches"]
