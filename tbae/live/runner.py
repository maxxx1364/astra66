"""Orchestrator: one ``step()`` walks the whole chain top to bottom.

    refresh universe (every ``universe_poll_s``)
    sweep a batch of symbols round-robin        -> MARKET DATA ENGINE + candles
    poll candidates that are due                -> LIVE CANDLE ENGINE
    scan + filter + select (every ``scan_interval_s``)
    DNA + ranking for candidates                -> SQLite ``opportunities``
    execution tick / new entries                -> SQLite ``positions``
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from . import dna as dna_mod
from . import filters, ranking, scanner
from .config import LiveConfig
from .exchange import build_exchange
from .execution import ExecutionEngine
from .market_data import MarketDataEngine
from .selector import CandidateSelector
from .storage import Store

log = logging.getLogger("tbae.live")


class Runner:
    def __init__(self, cfg: LiveConfig, *, exchange: Any | None = None,
                 history: Any | None = None, store: Store | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.cfg = cfg.validate()
        self.clock = clock
        self.ex = exchange or build_exchange(cfg.exchange, min_spacing_s=cfg.request_spacing_s)
        self.store = store or Store(cfg.db_path)
        self.md = MarketDataEngine(self.ex, self.store, cfg, clock=clock)
        self.selector = CandidateSelector(cfg.selector, cfg.fees)
        self.exec = ExecutionEngine(self.ex, self.store, self.md, cfg.execution, cfg.fees,
                                    clock=clock)
        self.history = history
        if self.history is None and cfg.history_exchange:
            self.history = build_exchange(cfg.history_exchange)
        self.candidates: list[str] = []
        self.last_universe = 0.0
        self.last_scan = 0.0
        self.funnel: dict[str, int] = {}
        self.backfilled: set[str] = set()
        self._stop = threading.Event()
        self._depth = None
        self._depth_set: set[str] = set()

    # ------------------------------------------------------------------ steps
    def refresh_universe(self) -> None:
        self.md.refresh_markets()
        self.last_universe = self.clock()
        if self.exec.refresh_fees():
            self.store.log("fees", f"account fees: maker {self.cfg.fees.maker_bps}bp "
                           f"taker {self.cfg.fees.taker_bps}bp")

    def scan(self) -> list[dict[str, Any]]:
        rows = scanner.scan_all(self.md, self.cfg.filters.depth_band_bps)
        filters.apply(rows, self.cfg.filters, self.cfg.fees)
        self.candidates = self.selector.select(rows, self.clock())
        self.funnel = filters.funnel(rows)
        self.store.save_scan(rows, int(self.clock() * 1000))
        self.last_scan = self.clock()
        return rows

    def _maybe_backfill(self, symbol: str) -> None:
        if self.history is None or symbol in self.backfilled:
            return
        self.backfilled.add(symbol)
        st = self.md.state[symbol]
        if st.market.quote != "USDT":       # IRT prices exist only on Iranian venues
            return
        if self.store.candle_stats(symbol)["n"] >= self.cfg.dna.engine_min_bars * self.cfg.dna.timeframe:
            return
        try:
            n = self.md.backfill(symbol, self.history, self.cfg.dna.lookback_minutes)
            self.store.log("backfill", f"{n} minutes from {self.history.name}", symbol)
        except Exception as e:  # noqa: BLE001 - history is best-effort
            self.store.log("backfill", f"failed: {e}", symbol, "warn")

    def analyze(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_sym = {r["symbol"]: r for r in rows}
        since = int(self.clock() * 1000) - self.cfg.dna.lookback_minutes * 60_000
        scored = []
        for sym in self.candidates:
            self._maybe_backfill(sym)
            minutes = self.store.candles(sym, since_ts=since)
            stats = self.store.candle_stats(sym)
            d = dna_mod.analyze(minutes, self.cfg.dna, live_minutes=stats["live"])
            o = ranking.score(sym, d, by_sym.get(sym, {}), self.cfg.fees, self.cfg.execution)
            o["dna"] = {k: v for k, v in d.items() if k != "features"}
            o["features"] = d.get("features", {})
            o["quote"] = by_sym.get(sym, {}).get("quote")
            scored.append(o)
        ranked = ranking.rank(scored)
        ids = self.store.save_opportunities(ranked, int(self.clock() * 1000))
        for o, i in zip(ranked, ids):
            o["id"] = i
        return ranked

    def step(self, *, sweep_budget: int = 20) -> dict[str, Any]:
        now = self.clock()
        if not self.md.state or now - self.last_universe >= self.cfg.universe_poll_s:
            self.refresh_universe()
        self.md.poll_due(self.candidates, self.cfg.trades_poll_s)
        self.md.sweep(sweep_budget, skip=set(self.candidates))
        ranked: list[dict[str, Any]] = []
        if now - self.last_scan >= self.cfg.scan_interval_s:
            rows = self.scan()
            ranked = self.analyze(rows)
            if self._depth is not None and set(self.candidates) != self._depth_set:
                self._depth_set = set(self.candidates)
                self._restart_depth()
        self.exec.tick()
        if ranked:
            self.exec.consider(ranked)
        return {"candidates": list(self.candidates), "funnel": self.funnel,
                "opportunities": len(ranked)}

    # ------------------------------------------------------------- run loop
    def _restart_depth(self) -> None:
        from .exchange.tabdeal import TabdealDepthStream
        if hasattr(self._depth, "stop"):
            self._depth.stop()
        self._depth = TabdealDepthStream(self.candidates, self.md.on_book)
        self._depth.start()

    def run_forever(self, *, tick_s: float = 5.0, websocket: bool = True) -> None:
        if websocket and self.cfg.exchange == "tabdeal":
            try:
                import websockets  # noqa: F401
                self._depth = object()          # marker: (re)start after first scan
            except ImportError:
                log.warning("websockets not installed; order books via REST only")
        self.store.log("start", f"runner started, mode={self.cfg.execution.mode}")
        while not self._stop.is_set():
            t0 = self.clock()
            try:
                info = self.step()
                if info["opportunities"]:
                    log.info("candidates=%d funnel=%s", len(info["candidates"]), info["funnel"])
            except Exception as e:  # noqa: BLE001 - keep the loop alive, log it
                log.exception("step failed")
                self.store.log("error", repr(e), level="error")
            self._stop.wait(max(0.0, tick_s - (self.clock() - t0)))

    def stop(self) -> None:
        self._stop.set()
        if self._depth is not None and hasattr(self._depth, "stop"):
            self._depth.stop()
