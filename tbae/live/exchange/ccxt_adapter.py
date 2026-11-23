"""Any CCXT-supported exchange behind the same interface.

CCXT has no Iranian exchanges, so Tabdeal uses its native adapter; this one is
for (a) future venues and (b) candle *history* — e.g. ``binance`` 1-minute
OHLCV for USDT pairs that also trade on Tabdeal, which lets the DNA analyzer
run on day one instead of waiting for the live candle engine to accumulate.

``ccxt`` is an optional dependency, imported only when this adapter is built.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from .base import Account, ExchangeError, Market, Order, OrderBook, Trade


def _compact(sym: str) -> str:
    return sym.split(":")[0].replace("/", "").upper()


class CcxtAdapter:
    def __init__(self, exchange_id: str, api_key: str = "", api_secret: str = "",
                 client: Any | None = None, **options: Any) -> None:
        if client is None:
            try:
                import ccxt  # type: ignore
            except ImportError as e:  # pragma: no cover - optional dependency
                raise RuntimeError("pip install ccxt  (needed for CCXT exchanges)") from e
            if not hasattr(ccxt, exchange_id):
                raise ValueError(f"ccxt has no exchange '{exchange_id}'")
            cfg = {"enableRateLimit": True, **options}
            if api_key:
                cfg.update(apiKey=api_key, secret=api_secret)
            client = getattr(ccxt, exchange_id)(cfg)
        self.client = client
        self.name = exchange_id
        self._by_compact: dict[str, str] = {}

    def _wrap(self, fn: Any, *a: Any, **kw: Any) -> Any:
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 - ccxt raises many types
            raise ExchangeError(f"{self.name}: {e}") from e

    def _ccxt_symbol(self, symbol: str) -> str:
        if not self._by_compact:
            self.markets()
        s = self._by_compact.get(symbol.upper())
        if s is None:
            raise ExchangeError(f"{self.name}: unknown symbol {symbol}")
        return s

    def markets(self) -> list[Market]:
        raw = self._wrap(self.client.load_markets)
        out = []
        for sym, m in raw.items():
            if m.get("type", "spot") != "spot":
                continue
            compact = _compact(sym)
            self._by_compact[compact] = sym
            lim = m.get("limits") or {}
            prec = m.get("precision") or {}
            out.append(Market(
                symbol=compact, base=str(m.get("base", "")).upper(),
                quote=str(m.get("quote", "")).upper(),
                status="TRADING" if m.get("active", True) else "BREAK",
                tick_size=float(prec.get("price") or 0) if isinstance(prec.get("price"), float) else 0.0,
                step_size=float(prec.get("amount") or 0) if isinstance(prec.get("amount"), float) else 0.0,
                min_qty=float((lim.get("amount") or {}).get("min") or 0),
                min_notional=float((lim.get("cost") or {}).get("min") or 0),
                exchange_symbol=sym))
        return out

    def recent_trades(self, symbol: str, limit: int = 1000) -> list[Trade]:
        rows = self._wrap(self.client.fetch_trades, self._ccxt_symbol(symbol), limit=limit)
        out = []
        for r in rows:
            try:
                tid = int(r.get("id"))
            except (TypeError, ValueError):
                tid = int(r["timestamp"]) * 1000 + len(out)
            out.append(Trade(id=tid, ts=int(r["timestamp"]), price=float(r["price"]),
                             qty=float(r["amount"]), is_buyer_maker=r.get("side") == "sell"))
        out.sort(key=lambda t: t.id)
        return out

    def order_book(self, symbol: str, limit: int = 50) -> OrderBook:
        ob = self._wrap(self.client.fetch_order_book, self._ccxt_symbol(symbol), limit)
        return OrderBook(symbol=symbol.upper(), ts=int(ob.get("timestamp") or time.time() * 1000),
                         bids=[(float(p), float(q)) for p, q, *_ in ob["bids"]],
                         asks=[(float(p), float(q)) for p, q, *_ in ob["asks"]])

    def history_ohlcv(self, symbol: str, since_ms: int, limit: int = 1000
                      ) -> list[Sequence[float]] | None:
        """1-minute ``[ts, open, high, low, close, volume]`` rows, or None if the
        venue does not list the symbol."""
        try:
            sym = self._ccxt_symbol(symbol)
        except ExchangeError:
            return None
        return self._wrap(self.client.fetch_ohlcv, sym, "1m", since_ms, limit)

    # trading is intentionally limited to what the execution engine needs
    def account(self) -> Account:
        bal = self._wrap(self.client.fetch_balance)
        free, used = bal.get("free", {}), bal.get("used", {})
        return Account(maker_bps=None, taker_bps=None, can_trade=True, can_withdraw=False,
                       balances={k.upper(): (float(free.get(k) or 0), float(used.get(k) or 0))
                                 for k in free})

    def place_order(self, symbol: str, side: str, type: str, qty: float,
                    price: float | None = None, client_order_id: str | None = None) -> Order:
        params = {"clientOrderId": client_order_id} if client_order_id else {}
        r = self._wrap(self.client.create_order, self._ccxt_symbol(symbol), type.lower(),
                       side.lower(), qty, price, params)
        return _order(r, symbol)

    def get_order(self, symbol: str, order_id: int | str) -> Order:
        return _order(self._wrap(self.client.fetch_order, str(order_id),
                                 self._ccxt_symbol(symbol)), symbol)

    def cancel_order(self, symbol: str, order_id: int | str) -> Order:
        return _order(self._wrap(self.client.cancel_order, str(order_id),
                                 self._ccxt_symbol(symbol)), symbol)

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        rows = self._wrap(self.client.fetch_open_orders,
                          self._ccxt_symbol(symbol) if symbol else None)
        return [_order(r, _compact(r.get("symbol", ""))) for r in rows]


_STATUS = {"open": "NEW", "closed": "FILLED", "canceled": "CANCELED",
           "cancelled": "CANCELED", "rejected": "REJECTED", "expired": "CANCELED"}


def _order(r: dict[str, Any], symbol: str) -> Order:
    st = _STATUS.get(str(r.get("status")), "NEW")
    filled = float(r.get("filled") or 0)
    if st == "NEW" and filled > 0:
        st = "PARTIALLY_FILLED"
    return Order(order_id=r.get("id", ""), symbol=symbol.upper(),
                 side=str(r.get("side", "")).upper(), type=str(r.get("type", "")).upper(),
                 status=st, price=float(r.get("price") or 0), qty=float(r.get("amount") or 0),
                 executed_qty=filled, quote_qty=float(r.get("cost") or 0),
                 client_order_id=r.get("clientOrderId"), ts=int(r.get("timestamp") or 0), raw=r)
