"""Pure-stdlib numeric helpers.

The engine deliberately avoids numpy so that it runs on any stock interpreter
and produces bit-identical results everywhere (no BLAS threading variance, which
is a real reproducibility hazard for backtests).  These helpers are the single
place where floating-point aggregation happens, so edge cases — empty input,
zero variance, NaN — are handled once and tested once.

All functions are O(n) single-pass unless stated otherwise.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

EPS = 1e-12


def is_nan(x: float) -> bool:
    return x != x


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """``a / b`` without ever raising or returning NaN/inf.

    Returns ``default`` only when the quotient is genuinely undefined: ``b`` is
    exactly zero, or either operand is NaN, or the quotient overflows.

    An *absolute* epsilon cut-off (``abs(b) < EPS -> default``) is deliberately
    NOT used: it silently turns a legitimate ratio into 0 whenever the data is
    scaled small, and 0 is a meaningful value in this engine (calm volatility,
    no flow imbalance), so swallowing a real quotient corrupts downstream
    filters.  Callers that need a noise floor apply it explicitly at the call
    site (``safe_div(x, max(den, EPS))``), where the right floor is known.
    """
    if b == 0.0:
        return default
    if is_nan(a) or is_nan(b):
        return default
    q = a / b
    if math.isinf(q):
        return default
    return q


def clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def mean(xs: Sequence[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    # math.fsum: exact rounding, so aggregates are order-stable and reproducible
    return math.fsum(xs) / n


def sum_(xs: Iterable[float]) -> float:
    return math.fsum(xs)


def variance(xs: Sequence[float], sample: bool = True) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    ss = math.fsum((x - m) ** 2 for x in xs)
    denom = (n - 1) if sample else n
    return ss / denom if denom > 0 else 0.0


def stdev(xs: Sequence[float], sample: bool = True) -> float:
    return math.sqrt(variance(xs, sample))


def median(xs: Sequence[float]) -> float:
    return percentile(xs, 50.0)


def percentile(xs: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (same convention as numpy's default).

    ``p`` is in 0..100.  Empty input -> 0.0.
    """
    n = len(xs)
    if n == 0:
        return 0.0
    if n == 1:
        return float(xs[0])
    p = clamp(float(p), 0.0, 100.0)
    s = sorted(xs)
    k = (n - 1) * (p / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(s[lo])
    frac = k - lo
    return float(s[lo]) * (1.0 - frac) + float(s[hi]) * frac


def quantile_rank(xs: Sequence[float], value: float) -> float:
    """Fraction of ``xs`` that is <= value, in 0..1 (mid-rank for ties)."""
    n = len(xs)
    if n == 0:
        return 0.0
    below = 0
    equal = 0
    for x in xs:
        if x < value:
            below += 1
        elif x == value:
            equal += 1
    return (below + 0.5 * equal) / n


def mad(xs: Sequence[float]) -> float:
    """Median absolute deviation — robust dispersion, used for outlier gates."""
    if not xs:
        return 0.0
    m = median(xs)
    return median([abs(x - m) for x in xs])


def zscore(x: float, mu: float, sigma: float) -> float:
    return safe_div(x - mu, sigma, 0.0)


def ema_series(xs: Sequence[float], period: int, seed: str = "sma") -> list[float]:
    """Exponential moving average as a full series (same length as ``xs``).

    Values before enough samples exist are seeded with the SMA of the first
    ``period`` points (``seed="sma"``) so the output has no artificial warm-up
    discontinuity, or with the first value (``seed="first"``).
    """
    n = len(xs)
    if n == 0:
        return []
    if period <= 1:
        return [float(x) for x in xs]
    alpha = 2.0 / (period + 1.0)
    out: list[float] = [0.0] * n
    if seed == "sma" and n >= period:
        head = math.fsum(xs[:period]) / period
        for i in range(period - 1):
            out[i] = head
        out[period - 1] = head
        prev = head
        for i in range(period, n):
            prev = alpha * xs[i] + (1.0 - alpha) * prev
            out[i] = prev
    else:
        prev = float(xs[0])
        out[0] = prev
        for i in range(1, n):
            prev = alpha * float(xs[i]) + (1.0 - alpha) * prev
            out[i] = prev
    return out


def wilder_series(xs: Sequence[float], period: int) -> list[float]:
    """Wilder's smoothing (R=1/period), the convention behind classic ATR/RSI."""
    n = len(xs)
    if n == 0:
        return []
    if period <= 1:
        return [float(x) for x in xs]
    out: list[float] = [0.0] * n
    if n < period:
        # not enough history: fall back to a running mean so the series is usable
        acc = 0.0
        for i, v in enumerate(xs):
            acc += v
            out[i] = acc / (i + 1)
        return out
    head = math.fsum(xs[:period]) / period
    for i in range(period):
        out[i] = head
    prev = head
    for i in range(period, n):
        prev = (prev * (period - 1) + float(xs[i])) / period
        out[i] = prev
    return out


def sma_series(xs: Sequence[float], period: int) -> list[float]:
    """Simple moving average; entries before the window is full use the
    expanding mean (documented, deliberate: avoids a NaN warm-up that silently
    shortens a backtest)."""
    n = len(xs)
    if n == 0:
        return []
    period = max(1, int(period))
    out: list[float] = [0.0] * n
    if period == 1:
        return [float(x) for x in xs]
    # prefix sums for O(n)
    acc = 0.0
    window: list[float] = []
    for i in range(n):
        v = float(xs[i])
        window.append(v)
        acc += v
        if len(window) > period:
            acc -= window.pop(0)
        out[i] = acc / len(window)
    return out


def rolling_apply(
    xs: Sequence[float], period: int, fn: Callable[[Sequence[float]], float]
) -> list[float]:
    """Generic rolling window; partial windows at the head are passed as-is."""
    n = len(xs)
    if n == 0:
        return []
    period = max(1, int(period))
    out: list[float] = [0.0] * n
    for i in range(n):
        lo = max(0, i - period + 1)
        out[i] = fn(xs[lo : i + 1])
    return out


def rolling_max(xs: Sequence[float], period: int) -> list[float]:
    return rolling_apply(xs, period, max)


def rolling_min(xs: Sequence[float], period: int) -> list[float]:
    return rolling_apply(xs, period, min)


def rolling_sum(xs: Sequence[float], period: int) -> list[float]:
    return rolling_apply(xs, period, sum_)


def cumsum(xs: Sequence[float]) -> list[float]:
    out: list[float] = []
    acc = 0.0
    for x in xs:
        acc += x
        out.append(acc)
    return out


def pct_change(xs: Sequence[float]) -> list[float]:
    out: list[float] = [0.0] * len(xs)
    for i in range(1, len(xs)):
        out[i] = safe_div(xs[i] - xs[i - 1], abs(xs[i - 1]), 0.0)
    return out


def linreg_slope(xs: Sequence[float]) -> float:
    """OLS slope over index 0..n-1 (per-sample units).  Used for trend tilt."""
    n = len(xs)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2.0
    ym = mean(xs)
    num = math.fsum((i - xm) * (xs[i] - ym) for i in range(n))
    den = math.fsum((i - xm) ** 2 for i in range(n))
    return safe_div(num, den, 0.0)


def linreg_r2(xs: Sequence[float]) -> float:
    """Goodness of fit of a straight line through ``xs`` — trend *quality*."""
    n = len(xs)
    if n < 3:
        return 0.0
    ym = mean(xs)
    syy = math.fsum((y - ym) ** 2 for y in xs)
    if syy <= EPS:
        # A constant series has sse = syy = 0, so R^2 is 0/0 and undefined.
        # Returning 1.0 ("a flat line fits perfectly") is the textbook answer but
        # the wrong one here: this function measures trend *quality*, and a series
        # with no variation has no trend at all.  Scoring it maximal would rank a
        # dead market above a real one — and dead bars are ~44% of a crypto 15m
        # sample, so the error would not be rare.
        return 0.0
    xm = (n - 1) / 2.0
    sxx = math.fsum((i - xm) ** 2 for i in range(n))
    sxy = math.fsum((i - xm) * (xs[i] - ym) for i in range(n))
    if sxx <= EPS:
        return 0.0
    slope = sxy / sxx
    intercept = ym - slope * xm
    sse = math.fsum((xs[i] - (slope * i + intercept)) ** 2 for i in range(n))
    return clamp(1.0 - safe_div(sse, syy, 0.0), 0.0, 1.0)


def autocorr(xs: Sequence[float], lag: int = 1) -> float:
    n = len(xs)
    if n <= lag + 2:
        return 0.0
    a = xs[: n - lag]
    b = xs[lag:]
    ma, mb = mean(a), mean(b)
    num = math.fsum((a[i] - ma) * (b[i] - mb) for i in range(len(a)))
    den = math.sqrt(
        math.fsum((x - ma) ** 2 for x in a) * math.fsum((x - mb) ** 2 for x in b)
    )
    return clamp(safe_div(num, den, 0.0), -1.0, 1.0)


def skewness(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = mean(xs)
    s = stdev(xs)
    if s <= EPS:
        return 0.0
    return safe_div(math.fsum(((x - m) / s) ** 3 for x in xs) * n, (n - 1) * (n - 2), 0.0)


def kurtosis(xs: Sequence[float]) -> float:
    """Excess kurtosis (0 = normal).  Fat tails matter for stop placement."""
    n = len(xs)
    if n < 4:
        return 0.0
    m = mean(xs)
    s = stdev(xs)
    if s <= EPS:
        return 0.0
    k4 = math.fsum(((x - m) / s) ** 4 for x in xs) / n
    return k4 - 3.0


def cvar(xs: Sequence[float], alpha: float = 0.05) -> float:
    """Expected shortfall of the worst ``alpha`` tail (returned negative-ish)."""
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(1, int(math.ceil(len(s) * alpha)))
    return mean(s[:k])


def var_quantile(xs: Sequence[float], alpha: float = 0.05) -> float:
    if not xs:
        return 0.0
    return percentile(xs, alpha * 100.0)


def manhattan(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(abs(x - y) for x, y in zip(a, b))


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(math.fsum((x - y) ** 2 for x, y in zip(a, b)))


def argmax(xs: Sequence[float]) -> int:
    best, bi = -math.inf, 0
    for i, x in enumerate(xs):
        if x > best:
            best, bi = x, i
    return bi


def argmin(xs: Sequence[float]) -> int:
    best, bi = math.inf, 0
    for i, x in enumerate(xs):
        if x < best:
            best, bi = x, i
    return bi


def round_lot(qty: float, step: float) -> float:
    """Round a quantity down to the exchange's lot step (never up — rounding up
    silently increases risk beyond the sizing decision)."""
    if step <= 0:
        return float(qty)
    return math.floor(qty / step + 1e-9) * step


def annualisation_factor(periods_per_year: float) -> float:
    return math.sqrt(max(periods_per_year, 1.0))
