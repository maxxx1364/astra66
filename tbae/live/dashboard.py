"""SPOT DASHBOARD — FastAPI JSON API + one self-contained HTML page.

It only reads the SQLite store, so it can run in the runner's process
(``python -m live run --dashboard``) or on its own (``python -m live dashboard``)
against the same database file.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .candles import bars_to_frame
from .dna import resample
from .storage import Store

_HTML = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")


def create_app(store: Store, runner: Any | None = None) -> FastAPI:
    app = FastAPI(title="TBAE live spot dashboard", version="0.1.0")
    app.mount("/static", StaticFiles(directory=os.path.dirname(_HTML)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        with open(_HTML, encoding="utf-8") as fh:
            return fh.read()

    @app.get("/api/live/status")
    def status() -> dict[str, Any]:
        out: dict[str, Any] = {"performance": store.performance(),
                               "open_positions": len(store.positions(["pending", "open"]))}
        if runner is not None:
            out.update(mode=runner.cfg.execution.mode, exchange=runner.cfg.exchange,
                       candidates=runner.candidates, funnel=runner.funnel,
                       fees={"maker_bps": runner.cfg.fees.maker_bps,
                             "taker_bps": runner.cfg.fees.taker_bps},
                       symbols=len(runner.md.state))
        return out

    @app.get("/api/live/opportunities")
    def opportunities() -> list[dict[str, Any]]:
        return store.latest_opportunities()

    @app.get("/api/live/scan")
    def scan(passed_only: bool = False) -> list[dict[str, Any]]:
        rows = store.scan()
        return [r for r in rows if r.get("passed")] if passed_only else rows

    @app.get("/api/live/positions")
    def positions(status: str | None = None) -> list[dict[str, Any]]:
        return store.positions(status.split(",") if status else None)

    @app.get("/api/live/events")
    def events(limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
        return store.events(limit)

    @app.get("/api/live/candles/{symbol}")
    def candles(symbol: str, tf: int = Query(15, ge=1, le=1440),
                limit: int = Query(300, ge=10, le=5000)) -> dict[str, Any]:
        bars = store.candles(symbol.upper(), limit=limit * tf)
        if not bars:
            raise HTTPException(404, f"no candles for {symbol}")
        df = resample(bars_to_frame(bars), tf).tail(limit)
        return {"symbol": symbol.upper(), "tf": tf,
                "candles": [{"time": int(r.ts // 1000), "open": r.open, "high": r.high,
                             "low": r.low, "close": r.close, "volume": r.quote_volume}
                            for r in df.itertuples(index=False)],
                "stats": store.candle_stats(symbol.upper()),
                "history": store.opportunity_history(symbol.upper(), 100)}

    return app
