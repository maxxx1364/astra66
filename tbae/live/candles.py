"""LIVE CANDLE ENGINE — trades -> 1-minute candles.

Tabdeal publishes no candles, so this module *is* the candle history.  Rules:

* trades are de-duplicated by id against a persisted cursor, so overlapping
  polls (the normal case) never double-count;
* if the oldest trade in a poll is newer than the cursor + 1, trades were lost
  between polls; the gap is counted, and the poll interval should be shortened;
* only **closed** minutes are written as final.  The current minute is kept in
  memory and re-emitted as it updates;
* minutes with no trades are filled flat at the previous close with zero
  volume, so a 15-minute bar is never silently built from 3 minutes;
* ``taker_buy_volume`` comes from ``isBuyerMaker = False`` — the tbae engine's
  flow-imbalance indicator reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from engine.models import MinuteBar

from .exchange.base import Trade

MINUTE_MS = 60_000


def trades_to_minutes(trades: Sequence[Trade]) -> pd.DataFrame:
    """Aggregate trades into per-minute OHLCV (only minutes that had trades)."""
    if not trades:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume",
                                     "quote_volume", "taker_buy_volume", "trades"])
    df = pd.DataFrame({
        "id": [t.id for t in trades], "ts": [t.ts for t in trades],
        "price": [t.price for t in trades], "qty": [t.qty for t in trades],
        "taker_buy": [t.taker_buy for t in trades],
    }).sort_values("id")
    df["minute"] = (df["ts"] // MINUTE_MS) * MINUTE_MS
    df["quote"] = df["price"] * df["qty"]
    df["buy_qty"] = np.where(df["taker_buy"], df["qty"], 0.0)
    g = df.groupby("minute", sort=True)
    out = pd.DataFrame({
        "open": g["price"].first(), "high": g["price"].max(), "low": g["price"].min(),
        "close": g["price"].last(), "volume": g["qty"].sum(),
        "quote_volume": g["quote"].sum(), "taker_buy_volume": g["buy_qty"].sum(),
        "trades": g["price"].size(),
    }).reset_index().rename(columns={"minute": "ts"})
    return out


def fill_gaps(df: pd.DataFrame, prev_close: float | None = None,
              start_ts: int | None = None, end_ts: int | None = None) -> pd.DataFrame:
    """Reindex to a continuous minute grid; empty minutes are flat, zero volume."""
    if df.empty and (start_ts is None or end_ts is None or prev_close is None):
        return df
    lo = start_ts if start_ts is not None else int(df["ts"].min())
    hi = end_ts if end_ts is not None else int(df["ts"].max())
    if hi < lo:
        return df.iloc[0:0]
    grid = pd.Index(np.arange(lo, hi + 1, MINUTE_MS, dtype=np.int64), name="ts")
    out = df.set_index("ts").reindex(grid)
    close = out["close"].ffill()
    if prev_close is not None:
        close = close.fillna(prev_close)
    empty = out["open"].isna()
    for c in ("open", "high", "low"):
        out[c] = out[c].where(~empty, close)
    out["close"] = close
    for c in ("volume", "quote_volume", "taker_buy_volume"):
        out[c] = out[c].fillna(0.0)
    out["trades"] = out["trades"].fillna(0).astype(int)
    out = out.dropna(subset=["close"])
    return out.reset_index()


def frame_to_bars(df: pd.DataFrame) -> list[MinuteBar]:
    return [MinuteBar(int(r.ts), float(r.open), float(r.high), float(r.low), float(r.close),
                      float(r.volume), float(r.quote_volume), float(r.taker_buy_volume),
                      int(r.trades)) for r in df.itertuples(index=False)]


def bars_to_frame(bars: Iterable[MinuteBar]) -> pd.DataFrame:
    rows = [(b.ts, b.open, b.high, b.low, b.close, b.volume, b.quote_volume,
             b.taker_buy_volume, b.trades) for b in bars]
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume",
                                       "quote_volume", "taker_buy_volume", "trades"])


@dataclass(slots=True)
class IngestResult:
    new_trades: int = 0
    closed: list[MinuteBar] = field(default_factory=list)
    forming: MinuteBar | None = None
    gap: bool = False


@dataclass
class SymbolCandles:
    """Per-symbol incremental builder.  State survives restarts through the
    store's trade cursor and the last stored candle."""

    symbol: str
    last_trade_id: int = -1
    last_closed_ts: int = -1          # ts of the last *final* minute written
    last_close: float | None = None
    pending: list[Trade] = field(default_factory=list)   # trades of open minute(s)

    def ingest(self, trades: Sequence[Trade], now_ms: int, limit: int = 1000) -> IngestResult:
        """``limit`` is the window size requested.  A *full* window in which every
        trade is new means the window did not reach back to the cursor, so trades
        between polls were lost.  (Trade ids are not assumed contiguous.)"""
        res = IngestResult()
        fresh = [t for t in trades if t.id > self.last_trade_id]
        if (self.last_trade_id >= 0 and trades and len(fresh) == len(trades)
                and len(trades) >= limit):
            res.gap = True
        res.new_trades = len(fresh)
        if fresh:
            self.last_trade_id = max(t.id for t in fresh)
        if self.last_closed_ts < 0 and fresh and len(trades) >= limit:
            # first poll with a full window: its earliest minute is truncated
            # (older trades of that minute are beyond the window) — drop it.
            first_min = min((t.ts // MINUTE_MS) * MINUTE_MS for t in fresh)
            fresh = [t for t in fresh if (t.ts // MINUTE_MS) * MINUTE_MS > first_min]
        # trades for minutes already finalised are late; drop them (rare).
        fresh = [t for t in fresh if (t.ts // MINUTE_MS) * MINUTE_MS > self.last_closed_ts]
        self.pending.extend(fresh)

        current_minute = (now_ms // MINUTE_MS) * MINUTE_MS
        closed_trades = [t for t in self.pending if t.ts < current_minute]
        self.pending = [t for t in self.pending if t.ts >= current_minute]

        last_closed_minute = current_minute - MINUTE_MS
        if closed_trades or (self.last_close is not None and self.last_closed_ts >= 0):
            df = trades_to_minutes(closed_trades)
            start = (self.last_closed_ts + MINUTE_MS) if self.last_closed_ts >= 0 else None
            if start is None and not df.empty:
                start = int(df["ts"].min())
            if start is not None and start <= last_closed_minute:
                df = fill_gaps(df, self.last_close, start, last_closed_minute)
                if not df.empty:
                    res.closed = frame_to_bars(df)
                    self.last_closed_ts = res.closed[-1].ts
                    self.last_close = res.closed[-1].close

        if self.pending:
            fm = trades_to_minutes(self.pending)
            res.forming = frame_to_bars(fm)[-1]
        return res
