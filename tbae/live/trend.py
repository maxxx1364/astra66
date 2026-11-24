"""Spot trend-following on daily bars: enter only after the direction is
settled, then let the winner run.

Rules fixed before any result was seen (``TrendConfig`` defaults):

entry, evaluated at the daily close of day t, filled at the open of t+1
    breakout     close is the highest close of the prior 50 days
    trend        close > EMA50 and EMA20 > EMA50 (the trend already exists)
    volume       quote volume >= 1.5 x the 20-day median before today
    liquidity    20-day median quote volume >= 1M USDT
    not_a_spike  the signal day itself rose less than 25 % (no chasing a candle)
    market       BTC closes above its 50-day average (spot does not buy alts
                 into a falling market) — reported with and without

exit
    initial stop   entry - 2.5 x ATR(20), never wider than 25 %; checked against
                   each day's low, filled at the stop or the gap-down open
    trailing exit  a daily close below the lowest close of the prior 20 days
                   -> sell at the next open
    no profit target and no time limit (capped at 365 days for bookkeeping)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class TrendConfig:
    breakout_days: int = 50
    ema_fast: int = 20
    ema_slow: int = 50
    min_vol_ratio: float = 1.5
    min_quote_volume: float = 1_000_000.0
    max_signal_day_move: float = 0.25
    atr_days: int = 20
    stop_atr: float = 2.5
    max_stop: float = 0.25
    trail_days: int = 20
    max_hold: int = 365
    market_ma: int = 50


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o, qv = df["close"], df["high"], df["low"], df["open"], df["quote_volume"]
    cfg = TrendConfig()
    x = pd.DataFrame(index=df.index)
    x["ema_f"] = c.ewm(span=cfg.ema_fast, adjust=False).mean()
    x["ema_s"] = c.ewm(span=cfg.ema_slow, adjust=False).mean()
    x["hh"] = c.shift(1).rolling(cfg.breakout_days).max()
    x["ll_trail"] = c.shift(1).rolling(cfg.trail_days).min()
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(cfg.atr_days).mean()
    x["vol_ratio"] = qv / qv.shift(1).rolling(20, min_periods=15).median()
    x["liq"] = qv.rolling(20, min_periods=15).median()
    x["day_move"] = c / o - 1
    return x


def entry_signals(df: pd.DataFrame, x: pd.DataFrame, cfg: TrendConfig,
                  market_ok: np.ndarray | None = None) -> np.ndarray:
    c = df["close"]
    sig = ((c > x["hh"]) & (c > x["ema_s"]) & (x["ema_f"] > x["ema_s"])
           & (x["vol_ratio"] >= cfg.min_vol_ratio) & (x["liq"] >= cfg.min_quote_volume)
           & (x["day_move"] < cfg.max_signal_day_move)).fillna(False).to_numpy()
    if market_ok is not None:
        sig &= market_ok
    return sig


def eligible(x: pd.DataFrame, cfg: TrendConfig) -> np.ndarray:
    return (x["liq"] >= cfg.min_quote_volume).fillna(False).to_numpy() & x["atr"].notna().to_numpy()


def simulate(df: pd.DataFrame, x: pd.DataFrame, i: int, cfg: TrendConfig) -> dict[str, Any] | None:
    """Signal at the close of ``i``; enter at the open of ``i+1``."""
    n = len(df)
    e = i + 1
    if e >= n:
        return None
    o = df["open"].to_numpy()
    lo = df["low"].to_numpy()
    c = df["close"].to_numpy()
    ll = x["ll_trail"].to_numpy()
    entry = o[e]
    atr = x["atr"].iat[i]
    if not (entry > 0 and atr > 0):
        return None
    stop = max(entry - cfg.stop_atr * atr, entry * (1 - cfg.max_stop))
    risk = (entry - stop) / entry
    peak = entry
    for j in range(e, min(n, e + cfg.max_hold)):
        if lo[j] <= stop:
            px = min(o[j], stop) if j > e else min(entry, stop) if o[j] <= stop else stop
            return _res(entry, px, "stop", j - e + 1, risk, peak)
        peak = max(peak, c[j])
        if c[j] < ll[j]:
            if j + 1 >= n:
                return _res(entry, c[j], "open_at_end", j - e + 1, risk, peak)
            return _res(entry, o[j + 1], "trail", j - e + 2, risk, peak)
    last = min(n, e + cfg.max_hold) - 1
    return _res(entry, c[last], "open_at_end" if last == n - 1 else "max_hold",
                last - e + 1, risk, peak)


def _res(entry: float, px: float, why: str, days: int, risk: float, peak: float) -> dict[str, Any]:
    g = px / entry - 1
    return {"gross": g, "exit": why, "days": days, "risk": risk, "r": g / risk if risk > 0 else 0.0,
            "peak": peak / entry - 1}
