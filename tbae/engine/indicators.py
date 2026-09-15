"""Trend / momentum / volume / structure indicators.

Contract: **every series here is causal.**  Element ``i`` uses bars ``<= i``
only, and anything that describes a *prior* level (Donchian channel, swing
points, volume baseline) is explicitly shifted so bar ``i`` is compared against
information that existed before bar ``i`` opened.

That shift is the detail most home-grown backtests get wrong.  "Close breaks the
20-bar high" implemented as ``close[i] > max(high[i-19..i])`` is self-fulfilling:
the bar being tested is part of its own threshold, so it always breaks on an
uptrend and the strategy looks brilliant.  Here the channel is
``max(high[i-20..i-1])``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from .mathx import EPS, clamp, ema_series, mean, percentile, safe_div, sma_series, stdev, wilder_series
from .models import Bar, Settings
from .systembar import flow_imbalance
from .volatility import atr_series


@dataclass(slots=True)
class IndicatorConfig:
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    rsi_period: int = 14
    dmi_period: int = 14
    donchian_period: int = 20
    swing_left: int = 3          # bars on each side of a fractal pivot
    roc_period: int = 5
    vol_z_min_samples: int = 12  # cohort samples before volume z is trusted
    vol_z_window: int = 400      # fallback rolling window
    rank_window: int = 200       # window for rolling percentile ranks
    squeeze_rank: float = 0.20   # BB-width percentile below which = squeeze
    bb_period: int = 20
    bb_mult: float = 2.0
    trend_adx_floor: float = 20.0
    trend_ribbon_eps: float = 1e-4


@dataclass(slots=True)
class Indicators:
    """Parallel arrays, all index-aligned with the bar list.

    A dataclass of lists (rather than fields on ``Bar``) keeps ``Bar`` small and
    makes it impossible to accidentally read an indicator that was computed on a
    different slice of data — the whole frame is rebuilt or not at all.
    """

    n: int = 0
    ema_fast: list[float] = field(default_factory=list)
    ema_mid: list[float] = field(default_factory=list)
    ema_slow: list[float] = field(default_factory=list)
    ribbon_tilt: list[float] = field(default_factory=list)   # (fast-slow)/close
    trend_state: list[int] = field(default_factory=list)     # +1 / -1 / 0
    adx: list[float] = field(default_factory=list)
    plus_di: list[float] = field(default_factory=list)
    minus_di: list[float] = field(default_factory=list)
    rsi: list[float] = field(default_factory=list)
    roc: list[float] = field(default_factory=list)
    vwap: list[float] = field(default_factory=list)
    session_open: list[float] = field(default_factory=list)
    dist_vwap_sigma: list[float] = field(default_factory=list)
    dist_ema_sigma: list[float] = field(default_factory=list)
    donchian_hi: list[float] = field(default_factory=list)   # prior N bars
    donchian_lo: list[float] = field(default_factory=list)   # prior N bars
    swing_hi: list[float] = field(default_factory=list)      # last confirmed pivot
    swing_lo: list[float] = field(default_factory=list)
    struct_break_up: list[bool] = field(default_factory=list)
    struct_break_dn: list[bool] = field(default_factory=list)
    vol_z: list[float] = field(default_factory=list)
    flow_imb: list[float] = field(default_factory=list)
    atr_pct_rank: list[float] = field(default_factory=list)
    sigma_rank: list[float] = field(default_factory=list)
    bb_width: list[float] = field(default_factory=list)
    bb_width_rank: list[float] = field(default_factory=list)
    squeeze: list[bool] = field(default_factory=list)
    bars_since_new_high: list[int] = field(default_factory=list)
    bars_since_new_low: list[int] = field(default_factory=list)

    def at(self, i: int) -> dict[str, object]:
        """Snapshot of all indicators at index ``i`` (for logs/diagnostics)."""
        out: dict[str, object] = {}
        for name in (
            "ema_fast", "ema_mid", "ema_slow", "ribbon_tilt", "trend_state", "adx",
            "plus_di", "minus_di", "rsi", "roc", "vwap", "session_open",
            "dist_vwap_sigma", "dist_ema_sigma", "donchian_hi", "donchian_lo",
            "swing_hi", "swing_lo", "struct_break_up", "struct_break_dn", "vol_z",
            "flow_imb", "atr_pct_rank", "sigma_rank", "bb_width", "bb_width_rank",
            "squeeze", "bars_since_new_high", "bars_since_new_low",
        ):
            seq = getattr(self, name)
            out[name] = seq[i] if i < len(seq) else None
        return out


def _shifted_rolling_max(xs: Sequence[float], period: int) -> list[float]:
    """``max(xs[i-period .. i-1])`` — the window *excludes* bar ``i``."""
    n = len(xs)
    out: list[float] = [0.0] * n
    for i in range(n):
        lo = max(0, i - period)
        win = xs[lo:i]
        out[i] = max(win) if win else 0.0
    return out


def _shifted_rolling_min(xs: Sequence[float], period: int) -> list[float]:
    n = len(xs)
    out: list[float] = [0.0] * n
    for i in range(n):
        lo = max(0, i - period)
        win = xs[lo:i]
        out[i] = min(win) if win else 0.0
    return out


def _rolling_rank(xs: Sequence[float], window: int) -> list[float]:
    """Percentile rank of ``xs[i]`` inside ``xs[i-window+1 .. i]``, 0..1."""
    n = len(xs)
    out: list[float] = [0.5] * n
    for i in range(n):
        lo = max(0, i - window + 1)
        win = xs[lo : i + 1]
        if len(win) < 5:
            out[i] = 0.5
            continue
        below = sum(1 for v in win if v < xs[i])
        equal = sum(1 for v in win if v == xs[i])
        out[i] = (below + 0.5 * equal) / len(win)
    return out


def _dmi(bars: Sequence[Bar], period: int) -> tuple[list[float], list[float], list[float]]:
    """Wilder's DMI/ADX.  Returns (+DI, -DI, ADX) in 0..100."""
    n = len(bars)
    if n == 0:
        return ([], [], [])
    up: list[float] = [0.0]
    dn: list[float] = [0.0]
    tr: list[float] = [max(bars[0].high - bars[0].low, 0.0)]
    for i in range(1, n):
        h, l = bars[i].high, bars[i].low
        ph, pl = bars[i - 1].high, bars[i - 1].low
        pc = bars[i - 1].close
        up_move = h - ph
        dn_move = pl - l
        up.append(up_move if (up_move > dn_move and up_move > 0) else 0.0)
        dn.append(dn_move if (dn_move > up_move and dn_move > 0) else 0.0)
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    tr_s = wilder_series(tr, period)
    up_s = wilder_series(up, period)
    dn_s = wilder_series(dn, period)
    pdi = [100.0 * safe_div(up_s[i], tr_s[i], 0.0) for i in range(n)]
    mdi = [100.0 * safe_div(dn_s[i], tr_s[i], 0.0) for i in range(n)]
    dx = [
        100.0 * safe_div(abs(pdi[i] - mdi[i]), pdi[i] + mdi[i], 0.0) for i in range(n)
    ]
    adx = wilder_series(dx, period)
    return (pdi, mdi, adx)


def _rsi(closes: Sequence[float], period: int) -> list[float]:
    n = len(closes)
    if n == 0:
        return []
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    g = wilder_series(gains, period)
    l = wilder_series(losses, period)
    out: list[float] = [50.0] * n
    for i in range(n):
        denom = g[i] + l[i]
        out[i] = 50.0 if denom <= EPS else 100.0 * g[i] / denom
    return out


def _session_anchors(bars: Sequence[Bar], s: Settings) -> tuple[list[float], list[float]]:
    """Session-anchored VWAP and the session's opening price.

    The anchor resets at ``session_start_hour`` UTC each day.  Anchoring matters:
    an all-history VWAP drifts so slowly that it stops being a meaningful
    mean-reversion reference intraday.
    """
    n = len(bars)
    vwap: list[float] = [0.0] * n
    sopen: list[float] = [0.0] * n
    import datetime as _dt

    pv = 0.0
    vv = 0.0
    cur_day: int | None = None
    cur_open = 0.0
    for i, b in enumerate(bars):
        dt = _dt.datetime.fromtimestamp(b.ts / 1000.0, _dt.timezone.utc)
        day = dt.toordinal()
        if dt.hour < s.session_start_hour:
            day -= 1
        if day != cur_day:
            cur_day = day
            pv = 0.0
            vv = 0.0
            cur_open = b.open
        # typical price weighted by volume; fall back to volume=1 when the feed
        # has no volume (synthetic-without-volume, some FX feeds)
        tp = (b.high + b.low + b.close) / 3.0
        w = b.volume if b.volume > 0 else 1.0
        pv += tp * w
        vv += w
        vwap[i] = safe_div(pv, vv, tp)
        sopen[i] = cur_open
    return (vwap, sopen)


def _volume_z(bars: Sequence[Bar], cfg: IndicatorConfig) -> list[float]:
    """Volume z-score against a *causal* hour-of-day baseline.

    Raw volume z-scores are near-useless in crypto/FX because volume is wildly
    seasonal: 13:30 UTC is always busier than 03:00 UTC, so a global z-score
    just rediscovering the clock.  We therefore keep per-(weekday, hour)
    accumulators of volume seen *strictly before* the current bar.
    """
    n = len(bars)
    out: list[float] = [0.0] * n
    acc: dict[tuple[int, int], tuple[int, float, float]] = {}
    glob_n = 0
    glob_sum = 0.0
    glob_sq = 0.0
    for i, b in enumerate(bars):
        key = (b.weekday, b.hour)
        cnt, ssum, ssq = acc.get(key, (0, 0.0, 0.0))
        if cnt >= cfg.vol_z_min_samples:
            mu = ssum / cnt
            var = max(ssq / cnt - mu * mu, 0.0)
            sd = math.sqrt(var)
            out[i] = safe_div(b.volume - mu, sd, 0.0) if sd > EPS else 0.0
        elif glob_n >= cfg.vol_z_min_samples:
            mu = glob_sum / glob_n
            var = max(glob_sq / glob_n - mu * mu, 0.0)
            sd = math.sqrt(var)
            out[i] = safe_div(b.volume - mu, sd, 0.0) if sd > EPS else 0.0
        else:
            out[i] = 0.0
        acc[key] = (cnt + 1, ssum + b.volume, ssq + b.volume * b.volume)
        glob_n += 1
        glob_sum += b.volume
        glob_sq += b.volume * b.volume
    return out


def compute(bars: Sequence[Bar], s: Settings | None = None, cfg: IndicatorConfig | None = None) -> Indicators:
    """Build the whole indicator frame for ``bars``."""
    s = s or Settings()
    cfg = cfg or IndicatorConfig()
    ind = Indicators(n=len(bars))
    if not bars:
        return ind

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    atr_pct = [b.atr_pct for b in bars]
    sigmas = [b.sigma if b.sigma > 0 else b.atr for b in bars]

    ind.ema_fast = ema_series(closes, cfg.ema_fast)
    ind.ema_mid = ema_series(closes, cfg.ema_mid)
    ind.ema_slow = ema_series(closes, cfg.ema_slow)
    ind.ribbon_tilt = [
        clamp(safe_div(ind.ema_fast[i] - ind.ema_slow[i], closes[i], 0.0), -1.0, 1.0)
        for i in range(len(bars))
    ]
    plus_di, minus_di, adx = _dmi(bars, cfg.dmi_period)
    ind.plus_di, ind.minus_di, ind.adx = plus_di, minus_di, adx

    # trend state: ribbon order + ADX confirmation.  Requiring both avoids
    # labelling a flat, ribbon-tangled market as "trending" — which is what
    # makes trend filters bleed in ranges.
    ts: list[int] = []
    for i in range(len(bars)):
        up_order = ind.ema_fast[i] > ind.ema_mid[i] > ind.ema_slow[i]
        dn_order = ind.ema_fast[i] < ind.ema_mid[i] < ind.ema_slow[i]
        strong = adx[i] >= cfg.trend_adx_floor
        tilt = abs(ind.ribbon_tilt[i]) >= cfg.trend_ribbon_eps
        if up_order and strong and tilt:
            ts.append(1)
        elif dn_order and strong and tilt:
            ts.append(-1)
        else:
            ts.append(0)
    ind.trend_state = ts

    ind.rsi = _rsi(closes, cfg.rsi_period)
    ind.roc = [
        clamp(safe_div(closes[i] - closes[max(0, i - cfg.roc_period)],
                       abs(closes[max(0, i - cfg.roc_period)]), 0.0), -10.0, 10.0)
        for i in range(len(bars))
    ]

    vwap, sopen = _session_anchors(bars, s)
    ind.vwap, ind.session_open = vwap, sopen
    for i, b in enumerate(bars):
        b.vwap = vwap[i]
        b.session_open = sopen[i]

    sig_safe = [x if x > EPS else EPS for x in sigmas]
    ind.dist_vwap_sigma = [
        clamp(safe_div(closes[i] - vwap[i], sig_safe[i], 0.0), -50.0, 50.0)
        for i in range(len(bars))
    ]
    ind.dist_ema_sigma = [
        clamp(safe_div(closes[i] - ind.ema_mid[i], sig_safe[i], 0.0), -50.0, 50.0)
        for i in range(len(bars))
    ]

    ind.donchian_hi = _shifted_rolling_max(highs, cfg.donchian_period)
    ind.donchian_lo = _shifted_rolling_min(lows, cfg.donchian_period)

    # confirmed fractal pivots: a pivot at j needs ``swing_left`` bars after it,
    # so it only becomes visible at j + swing_left.  Publishing it earlier is
    # look-ahead; publishing the raw extreme of the last N bars is not a pivot.
    k = cfg.swing_left
    last_hi, last_lo = 0.0, 0.0
    shi: list[float] = [0.0] * len(bars)
    slo: list[float] = [0.0] * len(bars)
    for i in range(len(bars)):
        j = i - k
        if j >= k:
            window = highs[j - k : j + k + 1]
            if highs[j] == max(window) and window.count(highs[j]) == 1:
                last_hi = highs[j]
            window_l = lows[j - k : j + k + 1]
            if lows[j] == min(window_l) and window_l.count(lows[j]) == 1:
                last_lo = lows[j]
        shi[i] = last_hi
        slo[i] = last_lo
    ind.swing_hi, ind.swing_lo = shi, slo

    ind.struct_break_up = [
        bool(ind.donchian_hi[i] > 0 and closes[i] > ind.donchian_hi[i])
        for i in range(len(bars))
    ]
    ind.struct_break_dn = [
        bool(ind.donchian_lo[i] > 0 and closes[i] < ind.donchian_lo[i])
        for i in range(len(bars))
    ]

    ind.vol_z = _volume_z(bars, cfg)
    ind.flow_imb = [flow_imbalance(b.minute_path or ()) for b in bars]

    ind.atr_pct_rank = _rolling_rank(atr_pct, cfg.rank_window)
    ind.sigma_rank = _rolling_rank(sigmas, cfg.rank_window)

    # Bollinger width + its rolling rank -> squeeze detection
    mid = sma_series(closes, cfg.bb_period)
    sd = [0.0] * len(bars)
    for i in range(len(bars)):
        lo = max(0, i - cfg.bb_period + 1)
        win = closes[lo : i + 1]
        sd[i] = stdev(win) if len(win) >= 3 else 0.0
    ind.bb_width = [
        clamp(safe_div(2.0 * cfg.bb_mult * sd[i], mid[i], 0.0), 0.0, 10.0)
        for i in range(len(bars))
    ]
    ind.bb_width_rank = _rolling_rank(ind.bb_width, cfg.rank_window)
    ind.squeeze = [ind.bb_width_rank[i] <= cfg.squeeze_rank for i in range(len(bars))]

    # bars since the last N-bar high/low (staleness of the breakout)
    bs_hi: list[int] = [0] * len(bars)
    bs_lo: list[int] = [0] * len(bars)
    ch, cl = 0, 0
    run_hi = -math.inf
    run_lo = math.inf
    for i in range(len(bars)):
        if highs[i] > run_hi:
            run_hi = highs[i]
            ch = 0
        else:
            ch += 1
        if lows[i] < run_lo:
            run_lo = lows[i]
            cl = 0
        else:
            cl += 1
        # decay the running extremes over the donchian window so "new high"
        # means new relative to recent price action, not to all history
        if ch >= cfg.donchian_period:
            lo = max(0, i - cfg.donchian_period + 1)
            run_hi = max(highs[lo : i + 1])
            ch = 0
        if cl >= cfg.donchian_period:
            lo = max(0, i - cfg.donchian_period + 1)
            run_lo = min(lows[lo : i + 1])
            cl = 0
        bs_hi[i], bs_lo[i] = ch, cl
    ind.bars_since_new_high, ind.bars_since_new_low = bs_hi, bs_lo
    return ind


def warmup_bars(cfg: IndicatorConfig | None = None) -> int:
    """Bars that must be discarded before indicators are trustworthy."""
    cfg = cfg or IndicatorConfig()
    return max(
        cfg.ema_slow,
        cfg.donchian_period + cfg.swing_left * 2,
        cfg.rsi_period * 3,
        cfg.dmi_period * 3,
        cfg.bb_period * 2,
        60,
    )


def trend_agreement(ind: Indicators, i: int, side: int) -> tuple[bool, str]:
    """Does the higher-context trend agree with ``side``?  Returns (ok, reason)."""
    if i >= ind.n:
        return (False, "out_of_range")
    st = ind.trend_state[i]
    if st == side:
        return (True, "ribbon_aligned")
    if st == 0:
        # range: allow the trade only if momentum and DMI both point our way
        if side > 0 and ind.plus_di[i] > ind.minus_di[i] and ind.roc[i] > 0:
            return (True, "range_with_momentum")
        if side < 0 and ind.minus_di[i] > ind.plus_di[i] and ind.roc[i] < 0:
            return (True, "range_with_momentum")
        return (False, "range_no_momentum")
    return (False, "counter_trend")


def extension_risk(ind: Indicators, i: int, side: int, max_sigma: float) -> tuple[bool, float]:
    """True when price is already too far from its anchors to enter safely.

    Entering an extended move means the mean-reversion component of the return
    distribution is working against you from bar one.  Measured in sigma units
    against both the session VWAP and the mid EMA, taking the *worst* of the two.
    """
    if i >= ind.n:
        return (False, 0.0)
    d_vwap = ind.dist_vwap_sigma[i] * side
    d_ema = ind.dist_ema_sigma[i] * side
    ext = max(d_vwap, d_ema)
    return (ext > max_sigma, ext)
