"""Tabdeal spot adapter (native — CCXT has no Tabdeal exchange).

Endpoints and signing follow https://docs.tabdeal.org and the official SDK
(Tabdeal-Exchange/tabdeal-python):

* reads go to ``/r/api/v1/<path>``, writes (POST/DELETE/PUT) to ``/api/v1/<path>``;
* signed (TRADE) calls send header ``X-MBX-APIKEY`` and append ``timestamp`` then
  ``signature = HMAC_SHA256(secret, urlencode(params))``; POST params go in a
  form body, GET/DELETE params in the query string.

Limits that shape the design above this module:

* there is **no kline endpoint** — candles are built from trades
  (:mod:`live.candles`);
* ``trades`` returns at most the last 1000 trades with no cursor, so active
  symbols must be polled often enough that no trade falls out of the window;
* the spot order-book WebSocket pushes every 2000 ms (``<sym>@depth@2000ms``).

Only the standard library is used for REST; ``websockets`` is imported lazily.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Sequence

from .base import Account, ExchangeError, Market, Order, OrderBook, Trade, fmt_decimal

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/stream/"
USER_AGENT = "tbae-live/0.1"


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def sign(secret: str, params: dict[str, Any]) -> str:
    query = urllib.parse.urlencode(params)
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_market(row: dict[str, Any]) -> Market:
    m = Market(
        symbol=str(row.get("symbol", "")).upper(),
        base=str(row.get("baseAsset", "")).upper(),
        quote=str(row.get("quoteAsset", "")).upper(),
        status=str(row.get("status", "")),
        exchange_symbol=str(row.get("tabdealSymbol", "")),
    )
    for flt in row.get("filters", []) or []:
        t = flt.get("filterType")
        if t == "PRICE_FILTER":
            m.tick_size = _f(flt.get("tickSize"))
        elif t == "LOT_SIZE":
            m.step_size = _f(flt.get("stepSize"))
            m.min_qty = _f(flt.get("minQty"))
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            m.min_notional = _f(flt.get("minNotional"))
    return m


def parse_trades(rows: Sequence[dict[str, Any]]) -> list[Trade]:
    out = [Trade(id=int(r["id"]), ts=int(r["time"]), price=_f(r["price"]),
                 qty=_f(r["qty"]), is_buyer_maker=bool(r.get("isBuyerMaker", False)))
           for r in rows]
    out.sort(key=lambda t: t.id)
    return out


def parse_book(symbol: str, payload: dict[str, Any], ts: int | None = None) -> OrderBook:
    """Accepts both the REST ``depth`` shape (``bids``/``asks``) and the
    WebSocket ``depthUpdate`` shape (``b``/``a``)."""
    bids = payload.get("bids", payload.get("b", [])) or []
    asks = payload.get("asks", payload.get("a", [])) or []
    book = OrderBook(
        symbol=symbol.upper(),
        ts=int(ts if ts is not None else payload.get("E") or time.time() * 1000),
        bids=sorted(((_f(p), _f(q)) for p, q, *_ in bids), key=lambda x: -x[0]),
        asks=sorted(((_f(p), _f(q)) for p, q, *_ in asks), key=lambda x: x[0]),
    )
    return book


def parse_order(row: dict[str, Any]) -> Order:
    return Order(
        order_id=row.get("orderId", ""),
        symbol=str(row.get("symbol", "")).upper(),
        side=str(row.get("side", "")),
        type=str(row.get("type", "")),
        status=str(row.get("status", "")),
        price=_f(row.get("price")),
        qty=_f(row.get("origQty")),
        executed_qty=_f(row.get("executedQty")),
        quote_qty=_f(row.get("cumulativeQuoteQty", row.get("cummulativeQuoteQty"))),
        client_order_id=row.get("clientOrderId"),
        ts=int(row.get("updateTime") or row.get("transactTime") or 0),
        raw=dict(row),
    )


def parse_account(row: dict[str, Any]) -> Account:
    # Binance-style integer commission: 10 = 0.10 % = 10 bp, so 40 -> 40 bp.
    def bps(k: str) -> float | None:
        return _f(row[k]) if k in row and row[k] is not None else None
    bal = {str(b["asset"]).upper(): (_f(b.get("free")), _f(b.get("freeze", b.get("locked"))))
           for b in row.get("balances", []) or []}
    return Account(maker_bps=bps("makerCommission"), taker_bps=bps("takerCommission"),
                   can_trade=bool(row.get("canTrade", False)),
                   can_withdraw=bool(row.get("canWithdraw", False)), balances=bal)


class Transport:
    """Thin urllib wrapper; swapped for a fake in the tests."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def __call__(self, method: str, url: str, headers: dict[str, str],
                 body: bytes | None) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class TabdealAdapter:
    name = "tabdeal"

    def __init__(self, api_key: str = "", api_secret: str = "", *,
                 base_url: str = BASE_URL, transport: Callable[..., tuple[int, bytes]] | None = None,
                 min_spacing_s: float = 0.25, max_retries: int = 3,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.transport = transport or Transport()
        self.min_spacing_s = min_spacing_s
        self.max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._markets: dict[str, Market] = {}

    # ------------------------------------------------------------------ http
    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self.min_spacing_s - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_call = self._clock()

    def request(self, method: str, path: str, params: dict[str, Any] | None = None, *,
                signed: bool = False, api_key_only: bool = False) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if signed or api_key_only:
            if not self.api_key or (signed and not self.api_secret):
                raise ExchangeError("API key/secret not configured "
                                    "(set TABDEAL_API_KEY / TABDEAL_API_SECRET)")
            headers["X-MBX-APIKEY"] = self.api_key
        prefix = "/r/api/v1/" if method == "GET" else "/api/v1/"
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            p = dict(params)
            if signed:
                p["timestamp"] = int(self._clock() * 1000)
                p["signature"] = sign(self.api_secret, p)
            query = urllib.parse.urlencode(p)
            url = self.base_url + prefix + path.lstrip("/")
            body = None
            if method in ("POST", "PUT"):
                body = query.encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif query:
                url += "?" + query
            self._throttle()
            try:
                status, raw = self.transport(method, url, headers, body)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt >= self.max_retries:
                    raise ExchangeError(f"network error: {e}") from e
                self._sleep(delay)
                delay *= 2
                continue
            data: Any
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {"msg": raw[:200].decode("utf-8", "replace")}
            err_code = data.get("code") if isinstance(data, dict) else None
            is_err = status >= 400 or (isinstance(err_code, int) and err_code >= 1000
                                       and "msg" in data)
            if not is_err:
                return data
            exc = ExchangeError(f"{method} {path}: HTTP {status} "
                                f"{data.get('msg', '') if isinstance(data, dict) else ''}",
                                status=status, code=err_code)
            if (exc.rate_limited or status >= 500) and attempt < self.max_retries:
                self._sleep(delay)
                delay *= 2
                continue
            raise exc
        raise ExchangeError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------- symbols
    def _sym_param(self, symbol: str) -> dict[str, str]:
        return {"tabdealSymbol": symbol} if "_" in symbol else {"symbol": symbol.upper()}

    # --------------------------------------------------------- market data
    def ping(self) -> bool:
        try:
            self.request("GET", "ping")
            return True
        except ExchangeError:
            return False

    def server_time(self) -> int:
        return int(self.request("GET", "time")["serverTime"])

    def markets(self) -> list[Market]:
        rows = self.request("GET", "exchangeInfo")
        if isinstance(rows, dict):          # tolerate a Binance-style wrapper
            rows = rows.get("symbols", [])
        mk = [parse_market(r) for r in rows]
        self._markets = {m.symbol: m for m in mk}
        return mk

    def market(self, symbol: str) -> Market | None:
        if not self._markets:
            self.markets()
        return self._markets.get(symbol.upper())

    def recent_trades(self, symbol: str, limit: int = 1000) -> list[Trade]:
        return parse_trades(self.request("GET", "trades",
                                         {**self._sym_param(symbol), "limit": min(limit, 1000)}))

    def order_book(self, symbol: str, limit: int = 50) -> OrderBook:
        data = self.request("GET", "depth", {**self._sym_param(symbol), "limit": limit})
        return parse_book(symbol, data, ts=int(self._clock() * 1000))

    def history_ohlcv(self, symbol: str, since_ms: int, limit: int = 1000) -> None:
        return None          # Tabdeal publishes no candle history

    # -------------------------------------------------------------- trading
    def account(self) -> Account:
        return parse_account(self.request("GET", "account", signed=True))

    def place_order(self, symbol: str, side: str, type: str, qty: float,
                    price: float | None = None, client_order_id: str | None = None) -> Order:
        type = type.upper()
        if type == "LIMIT" and not price:
            raise ValueError("LIMIT order needs a price")
        params: dict[str, Any] = {
            **self._sym_param(symbol), "side": side.upper(), "type": type,
            "quantity": fmt_decimal(qty),
            "price": fmt_decimal(price) if price else 0,
            "stopPrice": 0,
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return parse_order(self.request("POST", "order", params, signed=True))

    def get_order(self, symbol: str, order_id: int | str) -> Order:
        return parse_order(self.request("GET", "order",
                                        {**self._sym_param(symbol), "orderId": order_id},
                                        signed=True))

    def cancel_order(self, symbol: str, order_id: int | str) -> Order:
        return parse_order(self.request("DELETE", "order",
                                        {**self._sym_param(symbol), "orderId": order_id},
                                        signed=True))

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        params = self._sym_param(symbol) if symbol else {}
        return [parse_order(r) for r in self.request("GET", "openOrders", params, signed=True)]


class TabdealDepthStream:
    """Order-book WebSocket (``<symbol>@depth@2000ms``), run in a thread.

    Subscriptions are split across connections of at most ``per_conn`` topics:
    the docs warn that one socket carrying more than 50 markets may be dropped.
    """

    def __init__(self, symbols: Sequence[str], on_book: Callable[[OrderBook], None], *,
                 url: str = WS_URL, per_conn: int = 40) -> None:
        self.symbols = [s.lower() for s in symbols]
        self.on_book = on_book
        self.url = url
        self.per_conn = per_conn
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @staticmethod
    def handle_message(raw: str | bytes, on_book: Callable[[OrderBook], None]) -> bool:
        msg = json.loads(raw)
        data = msg.get("data") if isinstance(msg, dict) else None
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict) or data.get("e") != "depthUpdate":
            return False
        on_book(parse_book(str(data.get("s", "")), data))
        return True

    def start(self) -> None:
        chunks = [self.symbols[i:i + self.per_conn]
                  for i in range(0, len(self.symbols), self.per_conn)]
        for n, chunk in enumerate(chunks):
            t = threading.Thread(target=self._run, args=(chunk, n + 1), daemon=True,
                                 name=f"tabdeal-depth-{n}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def _run(self, chunk: list[str], sub_id: int) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError("pip install websockets  (needed for live order books)") from e
        backoff = 1.0
        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=15, close_timeout=5) as ws:
                    ws.send(json.dumps({"method": "SUBSCRIBE", "id": sub_id,
                                        "params": [f"{s}@depth@2000ms" for s in chunk]}))
                    backoff = 1.0
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=30)
                        except TimeoutError:
                            continue
                        try:
                            self.handle_message(raw, self.on_book)
                        except (ValueError, KeyError, TypeError):
                            continue
            except Exception:  # noqa: BLE001 - reconnect on any socket failure
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)
