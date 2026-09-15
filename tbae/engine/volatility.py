"""Volatility — including the *intra-candle* component the strategy needs.

Why not just ATR?
-----------------
ATR is a range estimator computed on the aggregate timeframe.  For stop placement
it is systematically wrong in one direction: it ignores everything that happened
*inside* the bar.  Two 15-minute bars can have identical OHLC and completely
different risk — one drifted, the other whipped back and forth twenty times.  The
whippy bar will stop you out; ATR cannot tell them apart.

Because this engine keeps the 1-minute path, we can measure that difference.
Three estimators are computed per bar, all as **log-return variance** so they are
dimensionally comparable, then blended:

``rv``   realised variance of the minute path, ``sum(log(c_i/c_{i-1})^2)``.
         Path-based: sees chop, ignores nothing.  Noisy for very short bars.
``gk``   Garman-Klass, ``0.5*ln(H/L)^2 - (2ln2-1)*ln(C/O)^2``.
         Range-based: ~5x more efficient than close-to-close, but assumes no
         overnight gap and is biased by the bar's own open/close placement.
``atr``  Wilder-smoothed true range.  Kept as the familiar, slow, comparable
         number and as the trailing-stop yardstick.

The blend ``sigma = sqrt(w_gk*gk + w_rv*rv) * close`` is what ``risk`` and
``exits`` size against; ``sigma_atr`` is its Wilder-smoothed version, used for
position sizing where a one-bar volatility spike must not silently halve the
position.  ``vol_regime`` expresses the current bar's sigma relative to its own
recent median, so filters can say "normal volatility" without hardcoding a level.
"""

from __future__ import annotations

import math
from typing import Sequence

from .mathx import EPS, clamp, median, safe_div, wilder_series
from .models import Bar, MinuteBar, Settings

_LN2 = math.log(2.0)
_GK_BODY_COEF = 2.0 * _LN2 - 1.0


def log_legs(minutes: Sequence[MinuteBar]) -> list[float]:
    """Log-return legs of the minute path: ln(c1/o1), ln(c2/c1), ..."""
    if not minutes:
        return []
    out: list[float] = []
    o = minutes[0].open
    c = minutes[0].close
    if o > 0 and c > 0:
        out.append(math.log(c / o))
    prev = c
    for m in minutes[1:]:
        if prev > 0 and m.close > 0:
            out.append(math.log(m.close / prev))
        prev = m.close
    return out


def rv_log_variance(minutes: Sequence[MinuteBar]) -> float:
    """Realised variance of the intra-bar minute path (log units)."""
    legs = log_legs(minutes)
    if not legs:
        return 0.0
    return math.fsum(l * l for l in legs)


def rv_price(bar: Bar) -> float:
    """Realised volatility over the bar, in price units."""
    ms = bar.minute_path or ()
    v = rv_log_variance(ms)
    return math.sqrt(max(v, 0.0)) * bar.close


def garman_klass_log_variance(bar: Bar) -> float:
    """Garman-Klass estimator (log units), clamped at zero.

    The raw expression can go negative for bars with a large body and tiny range
    ratio; clamping is the standard fix and is far better than dropping the bar
    (which would bias the sample towards quiet bars).
    """
    if bar.high <= 0 or bar.low <= 0 or bar.open <= 0 or bar.close <= 0:
        return 0.0
    hl = math.log(bar.high / bar.low)
    co = math.log(bar.close / bar.open)
    v = 0.5 * hl * hl - _GK_BODY_COEF * co * co
    return max(v, 0.0)


def parkinson_log_variance(bar: Bar) -> float:
    """Parkinson (1980) high-low estimator (log units)."""
    if bar.high <= 0 or bar.low <= 0:
        return 0.0
    hl = math.log(bar.high / bar.low)
    return (hl * hl) / (4.0 * _LN2)


def true_range(bar: Bar, prev_close: float | None) -> float:
    if prev_close is None or prev_close <= 0:
        return bar.high - bar.low
    return max(
        bar.high - bar.low,
        abs(bar.high - prev_close),
        abs(bar.low - prev_close),
    )


def annotate_volatility(bars: Sequence[Bar], s: Settings | None = None) -> list[Bar]:
    """Fill every volatility field on ``bars`` (in place).  Single pass + two
    Wilder smoothings, so O(n)."""
    s = s or Settings()
    n = len(bars)
    if n == 0:
        return []

    trs: list[float] = []
    sigmas: list[float] = []
    prev_close: float | None = None

    w_gk, w_rv = s.sigma_w_gk, s.sigma_w_rv
    wsum = w_gk + w_rv
    if wsum <= 0:
        w_gk, w_rv, wsum = 0.5, 0.5, 1.0

    for b in bars:
        b.true_range = true_range(b, prev_close)
        trs.append(b.true_range)

        ms = b.minute_path or ()
        rv_var = rv_log_variance(ms)
        gk_var = garman_klass_log_variance(b)
        if not ms:
            # no path available: fall back to a pure range estimator
            blend = gk_var if gk_var > 0 else parkinson_log_variance(b)
        else:
            blend = (w_gk * gk_var + w_rv * rv_var) / wsum
        b.rv = math.sqrt(max(rv_var, 0.0)) * b.close
        b.gk = math.sqrt(max(gk_var, 0.0)) * b.close
        b.sigma = math.sqrt(max(blend, 0.0)) * b.close
        sigmas.append(b.sigma)
        prev_close = b.close

    atr = wilder_series(trs, s.atr_period)
    sig_atr = wilder_series(sigmas, s.atr_period)

    win = max(10, s.vol_regime_period)
    for i, b in enumerate(bars):
        b.atr = atr[i]
        b.sigma_atr = sig_atr[i]
        b.atr_pct = safe_div(b.atr, b.close, 0.0) * 100.0
        lo = max(0, i - win + 1)
        hist = sigmas[lo : i + 1]
        med = median(hist)
        b.vol_regime = clamp(safe_div(b.sigma, med, 1.0), 0.0, 100.0) if med > EPS else 1.0
    return list(bars)


def atr_series(bars: Sequence[Bar], period: int) -> list[float]:
    """Standalone ATR (for consumers that want a different period)."""
    trs: list[float] = []
    prev_close: float | None = None
    for b in bars:
        trs.append(true_range(b, prev_close))
        prev_close = b.close
    return wilder_series(trs, period)


def sigma_pct(bar: Bar) -> float:
    return safe_div(bar.sigma, bar.close, 0.0) * 100.0


def annualised_vol(bars: Sequence[Bar], periods_per_year: float) -> float:
    """Annualised volatility of bar log-returns (fraction, not percent)."""
    if len(bars) < 2:
        return 0.0
    rets: list[float] = []
    for i in range(1, len(bars)):
        p, c = bars[i - 1].close, bars[i].close
        if p > 0 and c > 0:
            rets.append(math.log(c / p))
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = math.fsum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(max(periods_per_year, 1.0))


def vol_summary(bars: Sequence[Bar]) -> dict[str, float]:
    if not bars:
        return {}
    sig = [b.sigma for b in bars]
    atr = [b.atr for b in bars]
    return {
        "sigma_mean": sum(sig) / len(sig),
        "sigma_median": median(sig),
        "sigma_p95": sorted(sig)[max(0, int(len(sig) * 0.95) - 1)],
        "atr_mean": sum(atr) / len(atr),
        "atr_pct_mean": sum(b.atr_pct for b in bars) / len(bars),
        "vol_regime_mean": sum(b.vol_regime for b in bars) / len(bars),
        "rv_over_gk": safe_div(sum(b.rv for b in bars), sum(b.gk for b in bars), 0.0),
    }
