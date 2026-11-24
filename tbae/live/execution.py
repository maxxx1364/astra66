"""ENTRY / EXIT ENGINE — turns ranked opportunities into positions.

Spot, long-only.  Every position is: maker LIMIT buy near the best bid ->
resting LIMIT sell at the target (maker) -> stop watched by this process and
executed as a MARKET sell (taker).

Modes
-----
``paper`` (default)  fills are simulated against the live trade tape: an
                     entry fills only when a trade prints *below* the limit
                     (a print at the limit does not prove our queue position),
                     a target fills when a trade prints above it, a stop exits
                     at the worse of stop/last price minus half the spread.
``live``             real orders.  Requires ``execution.mode = "live"`` **and**
                     ``TBAE_LIVE_TRADING=yes`` in the environment.

Limitation, stated plainly: the stop is enforced by this process, not by the
exchange.  If the runner is down while price falls through the stop, nothing
sells.  Run it under a supervisor (systemd ``Restart=always``) and keep
position sizes small until this has been observed in paper mode.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .config import ExecutionConfig, FeeConfig, live_trading_armed
from .exchange.base import ExchangeError, Market
from .market_data import MarketDataEngine
from .storage import Store


class ExecutionEngine:
    def __init__(self, exchange: Any, store: Store, md: MarketDataEngine,
                 cfg: ExecutionConfig, fees: FeeConfig, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.ex = exchange
        self.store = store
        self.md = md
        self.cfg = cfg
        self.fees = fees
        self.clock = clock
        if cfg.mode == "live" and not live_trading_armed():
            raise RuntimeError("execution.mode is 'live' but TBAE_LIVE_TRADING=yes is not set")
        self.live = cfg.mode == "live"

    # ------------------------------------------------------------- account
    def refresh_fees(self) -> bool:
        """Replace configured fees with the account's real ones, if readable."""
        try:
            acc = self.ex.account()
        except (ExchangeError, AttributeError):
            return False
        if acc.maker_bps is not None:
            self.fees.maker_bps = float(acc.maker_bps)
        if acc.taker_bps is not None:
            self.fees.taker_bps = float(acc.taker_bps)
        if acc.can_withdraw:
            self.store.log("security", "API key has WITHDRAW permission — create a key "
                           "without it", level="warn")
        return True

    def equity(self, quote: str) -> float:
        if not self.live:
            closed = sum(p["pnl_quote"] or 0.0 for p in self.store.positions(["closed"])
                         if p["data"].get("quote") == quote)
            return self.cfg.paper_equity + closed
        acc = self.ex.account()
        free, frozen = acc.balances.get(quote, (0.0, 0.0))
        return free + frozen

    # --------------------------------------------------------------- price
    def _last(self, symbol: str) -> float:
        st = self.md.state.get(symbol)
        if st and st.trades:
            return st.trades[-1].price
        return st.book.mid if st and st.book else 0.0

    def _trades_since(self, symbol: str, ts_ms: int) -> list[Any]:
        st = self.md.state.get(symbol)
        return [t for t in st.trades if t.ts > ts_ms] if st else []

    # --------------------------------------------------------------- entry
    def consider(self, opps: list[dict[str, Any]]) -> list[int]:
        """Open positions for the best qualifying opportunities."""
        active = self.store.positions(["pending", "open"])
        held = {p["symbol"] for p in active}
        slots = self.cfg.max_open_positions - len(active)
        opened = []
        for o in opps:
            if slots <= 0:
                break
            if o.get("side") != 1 or o.get("score", 0) < self.cfg.min_score:
                continue
            if o["symbol"] in held:
                continue
            pid = self.enter(o)
            if pid:
                opened.append(pid)
                slots -= 1
        return opened

    def size(self, m: Market, entry: float, stop: float, equity: float) -> float:
        risk_quote = equity * self.cfg.risk_per_trade_pct / 100.0
        per_unit = entry - stop
        if per_unit <= 0:
            return 0.0
        qty = risk_quote / per_unit
        qty = min(qty, equity * self.cfg.max_position_pct / 100.0 / entry)
        qty = m.round_qty(qty)
        if qty < m.min_qty or qty * entry < m.min_notional:
            return 0.0
        return qty

    def enter(self, o: dict[str, Any]) -> int | None:
        sym = o["symbol"]
        st = self.md.state.get(sym)
        if not st or not st.book or not st.book.bids:
            return None
        m = st.market
        entry = m.round_price(st.book.best_bid * (1 - self.cfg.entry_offset_bps / 1e4))
        stop_bps, move_bps = o["stop_bps"], o["expected_move_bps"]
        stop = m.round_price(entry * (1 - stop_bps / 1e4))
        target = m.round_price(entry * (1 + move_bps / 1e4))
        equity = self.equity(m.quote)
        qty = self.size(m, entry, stop, equity)
        if qty <= 0:
            self.store.log("skip", f"size below exchange minimum (equity {equity:.2f})", sym)
            return None
        coid = f"tbae-{uuid.uuid4().hex[:12]}"
        order_id = None
        if self.live:
            try:
                order = self.ex.place_order(sym, "BUY", "LIMIT", qty, entry, coid)
            except ExchangeError as e:
                self.store.log("order_error", str(e), sym, "error")
                return None
            order_id = str(order.order_id)
        pid = self.store.open_position(
            symbol=sym, mode=self.cfg.mode, status="pending", entry_price=entry, qty=qty,
            stop=stop, target=target, entry_order_id=order_id, opportunity_id=o.get("id"),
            opened_ts=int(self.clock() * 1000),
            data={"quote": m.quote, "client_order_id": coid, "score": o["score"],
                  "risk_quote": qty * (entry - stop)})
        self.store.log("entry_placed", f"BUY {qty} @ {entry} stop {stop} target {target}", sym)
        return pid

    # ---------------------------------------------------------------- tick
    def tick(self) -> None:
        for p in self.store.positions(["pending", "open"]):
            try:
                if p["status"] == "pending":
                    self._tick_pending(p)
                else:
                    self._tick_open(p)
            except ExchangeError as e:
                self.store.log("order_error", str(e), p["symbol"], "error")

    def _expired(self, p: dict[str, Any]) -> bool:
        return self.clock() * 1000 - p["opened_ts"] > self.cfg.order_ttl_s * 1000

    def _tick_pending(self, p: dict[str, Any]) -> None:
        sym, pid = p["symbol"], p["id"]
        if not self.live:
            if any(t.price < p["entry_price"] for t in self._trades_since(sym, p["opened_ts"])):
                fee = p["entry_price"] * p["qty"] * self.fees.maker_bps / 1e4
                self.store.update_position(pid, status="open", fees_quote=fee)
                self.store.log("filled", f"entry @ {p['entry_price']}", sym)
            elif self._expired(p):
                self.store.update_position(pid, status="cancelled",
                                           closed_ts=int(self.clock() * 1000),
                                           exit_reason="entry_ttl")
            return
        order = self.ex.get_order(sym, p["entry_order_id"])
        if order.status == "FILLED" or (order.executed_qty > 0 and self._expired(p)):
            if order.is_open:
                self.ex.cancel_order(sym, p["entry_order_id"])
            qty = self._sellable(sym, order.executed_qty)
            target = self.ex.place_order(sym, "SELL", "LIMIT", qty, p["target"])
            data = {**p["data"], "target_order_id": str(target.order_id)}
            self.store.update_position(pid, status="open", qty=qty, entry_price=order.avg_price,
                                       fees_quote=order.avg_price * order.executed_qty
                                       * self.fees.maker_bps / 1e4, data=data)
            self.store.log("filled", f"entry {qty} @ {order.avg_price}", sym)
        elif order.status in ("CANCELED", "REJECTED") or self._expired(p):
            if order.is_open:
                self.ex.cancel_order(sym, p["entry_order_id"])
            self.store.update_position(pid, status="cancelled", closed_ts=int(self.clock() * 1000),
                                       exit_reason="entry_ttl" if order.is_open else order.status)

    def _sellable(self, symbol: str, executed: float) -> float:
        """Buy commissions may be taken in the base asset; never sell more than
        the account holds."""
        m = self.md.state[symbol].market
        try:
            free = self.ex.account().balances.get(m.base, (executed, 0.0))[0]
        except ExchangeError:
            free = executed
        return m.round_qty(min(executed, free))

    def _close(self, p: dict[str, Any], price: float, reason: str, maker: bool) -> None:
        fee_bps = self.fees.maker_bps if maker else self.fees.taker_bps
        exit_fee = price * p["qty"] * fee_bps / 1e4
        fees = (p["fees_quote"] or 0.0) + exit_fee
        pnl = (price - p["entry_price"]) * p["qty"] - fees
        risk = p["data"].get("risk_quote") or (p["entry_price"] - p["stop"]) * p["qty"]
        self.store.update_position(p["id"], status="closed", closed_ts=int(self.clock() * 1000),
                                   exit_price=price, exit_reason=reason, fees_quote=fees,
                                   pnl_quote=pnl, pnl_r=pnl / risk if risk > 0 else 0.0)
        self.store.log("closed", f"{reason} @ {price:.8g}  pnl {pnl:+.4f}", p["symbol"])

    def _tick_open(self, p: dict[str, Any]) -> None:
        sym = p["symbol"]
        last = self._last(sym)
        st = self.md.state.get(sym)
        if not self.live:
            seen = self._trades_since(sym, p["data"].get("checked_ts", p["opened_ts"]))
            if any(t.price > p["target"] for t in seen):
                self._close(p, p["target"], "target", maker=True)
                return
            if last and last <= p["stop"]:
                half_spread = (st.book.best_ask - st.book.best_bid) / 2 if st and st.book else 0.0
                self._close(p, min(p["stop"], last) - half_spread, "stop", maker=False)
                return
            if seen:
                self.store.update_position(p["id"], data={**p["data"], "checked_ts": seen[-1].ts})
            return
        tid = p["data"].get("target_order_id")
        tgt = self.ex.get_order(sym, tid) if tid else None
        if tgt and tgt.status == "FILLED":
            self._close(p, tgt.avg_price, "target", maker=True)
            return
        if last and last <= p["stop"]:
            if tgt and tgt.is_open:
                self.ex.cancel_order(sym, tid)
            remaining = self._sellable(sym, p["qty"] - (tgt.executed_qty if tgt else 0.0))
            out = self.ex.place_order(sym, "SELL", "MARKET", remaining)
            self._close(p, out.avg_price or last, "stop", maker=False)
