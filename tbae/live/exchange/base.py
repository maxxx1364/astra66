"""Exchange-neutral data types and the adapter interface.

Every layer above ``live.exchange`` speaks only these types, so adding an
exchange means writing one adapter — nothing else changes.  Symbols are always
the compact upper-case form without a separator (``BTCUSDT``, ``USDTIRT``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol, Sequence, runtime_checkable


class ExchangeError(RuntimeError):
    """An error reported by the exchange (HTTP 4xx/5xx or an error payload)."""

    def __init__(self, message: str, *, status: int = 0, code: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def rate_limited(self) -> bool:
        # Tabdeal: code 1216 = too many requests; HTTP 429 is the generic form.
        return self.status == 429 or self.code == 1216


@dataclass(slots=True)
class Market:
    symbol: str                 # BTCUSDT
    base: str                   # BTC
    quote: str                  # USDT
    status: str = "TRADING"
    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    exchange_symbol: str = ""   # the venue's own spelling, e.g. BTC_USDT

    @property
    def trading(self) -> bool:
        return self.status.upper() == "TRADING"

    def round_price(self, price: float) -> float:
        return _floor_to_step(price, self.tick_size)

    def round_qty(self, qty: float) -> float:
        return _floor_to_step(qty, self.step_size)


@dataclass(slots=True)
class Trade:
    id: int
    ts: int                     # epoch milliseconds
    price: float
    qty: float
    #: True when the buyer was the resting (maker) side, i.e. the aggressor sold.
    is_buyer_maker: bool

    @property
    def taker_buy(self) -> bool:
        return not self.is_buyer_maker


@dataclass(slots=True)
class OrderBook:
    symbol: str
    ts: int
    bids: list[tuple[float, float]] = field(default_factory=list)   # best first
    asks: list[tuple[float, float]] = field(default_factory=list)   # best first

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def mid(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        return (self.best_ask - self.best_bid) / m * 1e4 if m > 0 else float("inf")

    def depth_quote(self, band_bps: float) -> tuple[float, float]:
        """Quote-currency liquidity resting within ``band_bps`` of mid (bid, ask)."""
        m = self.mid
        if m <= 0:
            return 0.0, 0.0
        lo, hi = m * (1 - band_bps / 1e4), m * (1 + band_bps / 1e4)
        bid = sum(p * q for p, q in self.bids if p >= lo)
        ask = sum(p * q for p, q in self.asks if p <= hi)
        return bid, ask

    def imbalance(self, band_bps: float = 100.0) -> float:
        """(bid - ask) / (bid + ask) of near-mid liquidity, in [-1, 1]."""
        b, a = self.depth_quote(band_bps)
        return (b - a) / (b + a) if b + a > 0 else 0.0


@dataclass(slots=True)
class Order:
    order_id: int | str
    symbol: str
    side: str                   # BUY | SELL
    type: str                   # LIMIT | MARKET | STOP_LOSS_LIMIT
    status: str                 # NEW | PARTIALLY_FILLED | FILLED | CANCELED | REJECTED
    price: float = 0.0
    qty: float = 0.0
    executed_qty: float = 0.0
    quote_qty: float = 0.0      # cumulative quote spent/received
    client_order_id: str | None = None
    ts: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in ("NEW", "PARTIALLY_FILLED")

    @property
    def avg_price(self) -> float:
        return self.quote_qty / self.executed_qty if self.executed_qty > 0 else self.price


@dataclass(slots=True)
class Account:
    maker_bps: float | None
    taker_bps: float | None
    can_trade: bool
    can_withdraw: bool
    balances: dict[str, tuple[float, float]]     # asset -> (free, frozen)


@runtime_checkable
class ExchangeAdapter(Protocol):
    name: str

    def markets(self) -> list[Market]: ...
    def recent_trades(self, symbol: str, limit: int = 1000) -> list[Trade]: ...
    def order_book(self, symbol: str, limit: int = 50) -> OrderBook: ...
    def history_ohlcv(self, symbol: str, since_ms: int, limit: int = 1000
                      ) -> list[Sequence[float]] | None: ...


@runtime_checkable
class TradingAdapter(ExchangeAdapter, Protocol):
    def account(self) -> Account: ...
    def place_order(self, symbol: str, side: str, type: str, qty: float,
                    price: float | None = None, client_order_id: str | None = None) -> Order: ...
    def get_order(self, symbol: str, order_id: int | str) -> Order: ...
    def cancel_order(self, symbol: str, order_id: int | str) -> Order: ...
    def open_orders(self, symbol: str | None = None) -> list[Order]: ...


def _floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    d = Decimal(str(step))
    return float((Decimal(str(x)) / d).to_integral_value(rounding=ROUND_DOWN) * d)


def fmt_decimal(x: float) -> str:
    """Plain decimal string (no exponent) for order parameters."""
    s = format(Decimal(str(x)).normalize(), "f")
    return s
