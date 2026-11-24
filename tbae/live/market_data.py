"""MARKET DATA ENGINE — keeps trades, books and candles current for all symbols.

Polling plan (REST, because Tabdeal's spot WebSocket only carries order books):

* the whole universe is swept round-robin, one symbol per call slot, so a
  sweep of N symbols costs N trade calls (+ N book calls when no WebSocket
  book is fresh);
* candidates are polled more often (``LiveConfig.trades_poll_s``) because a busy
  market can push more than 1000 trades out of the window between sweeps;
* every poll feeds the LIVE CANDLE ENGINE, so *every* symbol accumulates
  history — that is the only way to get Tabdeal candle history at all.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .candles import MINUTE_MS, SymbolCandles
from .config import LiveConfig
from .exchange.base import ExchangeAdapter, ExchangeError, Market, OrderBook, Trade
from .storage import Store


@dataclass
class SymbolState:
    market: Market
    trades: deque = field(default_factory=lambda: deque(maxlen=20_000))
    book: OrderBook | None = None
    candles: SymbolCandles | None = None
    forming: Any = None
    last_poll: float = 0.0
    last_error: str = ""
    gaps: int = 0
    max_trade_id: int = -1


class MarketDataEngine:
    def __init__(self, exchange: ExchangeAdapter, store: Store, cfg: LiveConfig, *,
                 clock: Callable[[], float] = time.time,
                 window_minutes: int = 60) -> None:
        self.ex = exchange
        self.store = store
        self.cfg = cfg
        self.clock = clock
        self.window_ms = window_minutes * MINUTE_MS
        self.state: dict[str, SymbolState] = {}
        self._lock = threading.RLock()
        self._rr: deque[str] = deque()
        self.book_max_age_s = 10.0

    # ----------------------------------------------------------- universe
    def refresh_markets(self) -> list[Market]:
        mk = self.ex.markets()
        quotes = set(self.cfg.filters.quote_assets)
        with self._lock:
            for m in mk:
                if quotes and m.quote not in quotes:
                    continue
                st = self.state.get(m.symbol)
                if st is None:
                    self.state[m.symbol] = SymbolState(market=m, candles=self._restore(m.symbol))
                else:
                    st.market = m
            self._rr = deque(sorted(self.state))
        return mk

    def _restore(self, symbol: str) -> SymbolCandles:
        sc = SymbolCandles(symbol)
        cur = self.store.cursor(symbol)
        if cur:
            sc.last_trade_id = cur[0]
        last = self.store.candles(symbol, limit=1)
        if last and (cur is None or last[-1].ts >= 0):
            sc.last_closed_ts = last[-1].ts
            sc.last_close = last[-1].close
            # after a long downtime, do not fill hours of flat candles
            if self.clock() * 1000 - last[-1].ts > 6 * 3600 * 1000:
                sc.last_closed_ts, sc.last_close = -1, None
        return sc

    @property
    def symbols(self) -> list[str]:
        return sorted(self.state)

    # ------------------------------------------------------------- books
    def on_book(self, book: OrderBook) -> None:
        with self._lock:
            st = self.state.get(book.symbol.upper())
            if st is not None:
                st.book = book

    def _book_fresh(self, st: SymbolState) -> bool:
        return bool(st.book) and (self.clock() * 1000 - st.book.ts) < self.book_max_age_s * 1000

    # ------------------------------------------------------------ polling
    def poll(self, symbol: str, *, with_book: bool = True) -> int:
        """Fetch trades (and a book if none is fresh) for one symbol."""
        st = self.state[symbol]
        now = self.clock()
        try:
            trades = self.ex.recent_trades(symbol, limit=1000)
            if with_book and not self._book_fresh(st):
                st.book = self.ex.order_book(symbol, limit=50)
        except ExchangeError as e:
            st.last_error = str(e)
            st.last_poll = now
            return 0
        st.last_error = ""
        st.last_poll = now
        return self._ingest(st, trades, int(now * 1000))

    def _ingest(self, st: SymbolState, trades: list[Trade], now_ms: int) -> int:
        assert st.candles is not None
        res = st.candles.ingest(trades, now_ms)
        # dedupe by the highest id ever added, not by what is still in the
        # deque: trades aged out of the window must not be re-added.
        for t in trades:
            if t.id > st.max_trade_id:
                st.trades.append(t)
                st.max_trade_id = t.id
        cutoff = now_ms - self.window_ms
        while st.trades and st.trades[0].ts < cutoff:
            st.trades.popleft()
        if res.closed:
            self.store.upsert_candles(st.market.symbol, res.closed, "live")
        if res.new_trades or res.gap:
            self.store.set_cursor(st.market.symbol, st.candles.last_trade_id,
                                  trades[-1].ts if trades else 0, gap=res.gap)
        if res.gap:
            st.gaps += 1
            self.store.log("gap", "trade window overflowed between polls; "
                           "poll this symbol more often", st.market.symbol, "warn")
        st.forming = res.forming
        return res.new_trades

    def sweep(self, budget: int, skip: set[str] | None = None) -> list[str]:
        """Poll up to ``budget`` symbols round-robin; returns those polled."""
        done = []
        for _ in range(min(budget, len(self._rr))):
            sym = self._rr[0]
            self._rr.rotate(-1)
            if skip and sym in skip:
                continue
            self.poll(sym)
            done.append(sym)
        return done

    def poll_due(self, symbols: list[str], interval_s: float) -> list[str]:
        now = self.clock()
        due = [s for s in symbols if s in self.state
               and now - self.state[s].last_poll >= interval_s]
        for s in due:
            self.poll(s)
        return due

    # ------------------------------------------------------------ history
    def backfill(self, symbol: str, history: Any, minutes: int) -> int:
        """Seed candle history from another venue (CCXT ``fetch_ohlcv``).

        Rows are stored with ``source='history'`` and never overwrite live rows.
        Use only for pairs whose price is the same instrument (USDT pairs), not
        for IRT pairs."""
        from engine.models import MinuteBar
        since = int(self.clock() * 1000) - minutes * MINUTE_MS
        total = 0
        while True:
            rows = history.history_ohlcv(symbol, since, 1000)
            if not rows:
                break
            bars = [MinuteBar(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                              float(r[5]), float(r[4]) * float(r[5])) for r in rows]
            self.store.upsert_candles(symbol, bars, "history", overwrite_live=False)
            total += len(bars)
            nxt = bars[-1].ts + MINUTE_MS
            if nxt <= since or len(rows) < 2:
                break
            since = nxt
            if since >= self.clock() * 1000 - MINUTE_MS:
                break
        return total
