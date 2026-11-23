"""Exchange adapters.  ``build_exchange("tabdeal")`` or any CCXT exchange id."""

from __future__ import annotations

from typing import Any

from ..config import credentials
from .base import (Account, ExchangeAdapter, ExchangeError, Market, Order, OrderBook,
                   Trade, TradingAdapter)

__all__ = ["Account", "ExchangeAdapter", "ExchangeError", "Market", "Order", "OrderBook",
           "Trade", "TradingAdapter", "build_exchange"]


def build_exchange(name: str, **kw: Any) -> Any:
    name = name.lower()
    if name == "tabdeal":
        from .tabdeal import TabdealAdapter
        key, secret = credentials("TABDEAL")
        return TabdealAdapter(key, secret, **kw)
    from .ccxt_adapter import CcxtAdapter
    key, secret = credentials(name.upper())
    return CcxtAdapter(name, key, secret, **kw)
