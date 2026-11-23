"""ALL SYMBOLS SCANNER — one cheap snapshot row per symbol.

Everything here is computed from what the market data engine already holds
(the in-memory trade window and the latest order book); no extra API calls.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .market_data import MarketDataEngine, SymbolState


def snapshot(st: SymbolState, now_ms: int, band_bps: float = 100.0) -> dict[str, Any]:
    m = st.market
    row: dict[str, Any] = {"symbol": m.symbol, "base": m.base, "quote": m.quote,
                           "status": m.status, "error": st.last_error, "gaps": st.gaps}
    trades = list(st.trades)
    if trades:
        px = np.fromiter((t.price for t in trades), float, len(trades))
        qty = np.fromiter((t.qty for t in trades), float, len(trades))
        buy = np.fromiter((t.taker_buy for t in trades), bool, len(trades))
        notional = px * qty
        span_min = max((trades[-1].ts - trades[0].ts) / 60_000.0, 1.0)
        hi, lo = float(px.max()), float(px.min())
        mid_px = (hi + lo) / 2
        row.update(
            last=float(px[-1]), trades=len(trades), window_minutes=round(span_min, 1),
            notional=float(notional.sum()),
            notional_per_min=float(notional.sum() / span_min),
            change_bps=float((px[-1] / px[0] - 1) * 1e4) if px[0] > 0 else 0.0,
            range_bps=float((hi - lo) / mid_px * 1e4) if mid_px > 0 else 0.0,
            buy_share=float(notional[buy].sum() / notional.sum()) if notional.sum() > 0 else 0.5,
            last_trade_age_s=(now_ms - trades[-1].ts) / 1000.0,
        )
        # realised volatility of 1-minute log returns inside the window
        minute = np.array([t.ts // 60_000 for t in trades])
        _, last_idx = np.unique(minute[::-1], return_index=True)
        closes = px[::-1][last_idx]
        if len(closes) >= 5:
            r = np.diff(np.log(closes))
            row["rv_bps_per_min"] = float(np.std(r) * 1e4)
    else:
        row.update(last=0.0, trades=0, notional=0.0, notional_per_min=0.0, change_bps=0.0,
                   range_bps=0.0, buy_share=0.5, last_trade_age_s=math.inf)
    b = st.book
    if b and b.bids and b.asks:
        bid_d, ask_d = b.depth_quote(band_bps)
        row.update(bid=b.best_bid, ask=b.best_ask, mid=b.mid, spread_bps=b.spread_bps,
                   depth_bid=bid_d, depth_ask=ask_d, book_imbalance=b.imbalance(band_bps),
                   book_age_s=(now_ms - b.ts) / 1000.0)
    else:
        row.update(spread_bps=math.inf, depth_bid=0.0, depth_ask=0.0, book_imbalance=0.0)
    return row


def scan_all(md: MarketDataEngine, band_bps: float = 100.0) -> list[dict[str, Any]]:
    now_ms = int(md.clock() * 1000)
    return [snapshot(md.state[s], now_ms, band_bps) for s in md.symbols]
