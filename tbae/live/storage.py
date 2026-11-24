"""SQLite persistence: candles, trade cursors, scans, opportunities, positions.

One file, WAL mode, so the dashboard can read while the runner writes.  All
writes go through one lock; reads are cheap and lock-free under WAL.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Iterable, Sequence

from engine.models import MinuteBar

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, quote_volume REAL, taker_buy_volume REAL, trades INTEGER,
    source TEXT NOT NULL DEFAULT 'live',
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS trade_cursor (
    symbol TEXT PRIMARY KEY, last_trade_id INTEGER, last_ts INTEGER,
    gaps INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scan (
    symbol TEXT PRIMARY KEY, ts INTEGER, passed INTEGER, reasons TEXT,
    candidate INTEGER NOT NULL DEFAULT 0, data TEXT
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, symbol TEXT NOT NULL, score REAL, side INTEGER,
    expected_move_bps REAL, net_edge_bps REAL, rank INTEGER, data TEXT
);
CREATE INDEX IF NOT EXISTS opp_ts ON opportunities (ts);
CREATE INDEX IF NOT EXISTS opp_sym ON opportunities (symbol, ts);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
    opened_ts INTEGER, closed_ts INTEGER,
    entry_price REAL, qty REAL, stop REAL, target REAL,
    exit_price REAL, exit_reason TEXT,
    fees_quote REAL DEFAULT 0, pnl_quote REAL, pnl_r REAL,
    entry_order_id TEXT, exit_order_id TEXT, opportunity_id INTEGER, data TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, level TEXT, kind TEXT,
    symbol TEXT, message TEXT
);
"""

_CANDLE_COLS = ("ts", "open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_volume", "trades")


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def _write(self, sql: str, args: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, args)

    def _write_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, rows)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # -------------------------------------------------------------- candles
    def upsert_candles(self, symbol: str, bars: Iterable[MinuteBar], source: str = "live",
                       *, overwrite_live: bool = True) -> None:
        """Insert or replace candles.  History rows never overwrite live rows:
        the venue we trade on is the ground truth for its own prices."""
        rows = [(symbol, b.ts, b.open, b.high, b.low, b.close, b.volume, b.quote_volume,
                 b.taker_buy_volume, b.trades, source) for b in bars]
        if not rows:
            return
        if source == "live" and overwrite_live:
            sql = ("INSERT OR REPLACE INTO candles (symbol, ts, open, high, low, close, volume,"
                   " quote_volume, taker_buy_volume, trades, source)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?)")
        else:
            sql = ("INSERT OR IGNORE INTO candles (symbol, ts, open, high, low, close, volume,"
                   " quote_volume, taker_buy_volume, trades, source)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?)")
        self._write_many(sql, rows)

    def candles(self, symbol: str, since_ts: int = 0, limit: int | None = None) -> list[MinuteBar]:
        sql = ("SELECT " + ", ".join(_CANDLE_COLS) +
               " FROM candles WHERE symbol = ? AND ts >= ? ORDER BY ts")
        args: list[Any] = [symbol, since_ts]
        if limit:
            sql = ("SELECT * FROM (SELECT " + ", ".join(_CANDLE_COLS) +
                   " FROM candles WHERE symbol = ? AND ts >= ? ORDER BY ts DESC LIMIT ?)"
                   " ORDER BY ts")
            args.append(limit)
        return [MinuteBar(*tuple(r)) for r in self.conn.execute(sql, args)]

    def candle_stats(self, symbol: str) -> dict[str, Any]:
        r = self.conn.execute(
            "SELECT COUNT(*) n, MIN(ts) first, MAX(ts) last,"
            " SUM(source = 'live') live FROM candles WHERE symbol = ?", (symbol,)).fetchone()
        return {"n": r["n"], "first": r["first"], "last": r["last"], "live": r["live"] or 0}

    def prune_candles(self, older_than_ts: int) -> int:
        return self._write("DELETE FROM candles WHERE ts < ?", (older_than_ts,)).rowcount

    # --------------------------------------------------------- trade cursor
    def cursor(self, symbol: str) -> tuple[int, int, int] | None:
        r = self.conn.execute("SELECT last_trade_id, last_ts, gaps FROM trade_cursor"
                              " WHERE symbol = ?", (symbol,)).fetchone()
        return (r[0], r[1], r[2]) if r else None

    def set_cursor(self, symbol: str, last_id: int, last_ts: int, gap: bool = False) -> None:
        self._write("INSERT INTO trade_cursor (symbol, last_trade_id, last_ts, gaps)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET"
                    " last_trade_id = excluded.last_trade_id, last_ts = excluded.last_ts,"
                    " gaps = trade_cursor.gaps + ?", (symbol, last_id, last_ts, int(gap), int(gap)))

    # ----------------------------------------------------------------- scan
    def save_scan(self, rows: Iterable[dict[str, Any]], ts: int | None = None) -> None:
        ts = ts or now_ms()
        self._write_many(
            "INSERT OR REPLACE INTO scan (symbol, ts, passed, reasons, candidate, data)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(r["symbol"], ts, int(bool(r.get("passed"))), ",".join(r.get("reasons", [])),
              int(bool(r.get("candidate"))), json.dumps(r, default=float)) for r in rows])

    def scan(self) -> list[dict[str, Any]]:
        return [json.loads(r["data"]) for r in
                self.conn.execute("SELECT data FROM scan ORDER BY candidate DESC, symbol")]

    # -------------------------------------------------------- opportunities
    def save_opportunities(self, opps: Sequence[dict[str, Any]], ts: int | None = None) -> list[int]:
        ts = ts or now_ms()
        ids = []
        with self._lock:
            for o in opps:
                cur = self.conn.execute(
                    "INSERT INTO opportunities (ts, symbol, score, side, expected_move_bps,"
                    " net_edge_bps, rank, data) VALUES (?,?,?,?,?,?,?,?)",
                    (ts, o["symbol"], o["score"], o.get("side", 0), o.get("expected_move_bps"),
                     o.get("net_edge_bps"), o.get("rank"), json.dumps(o, default=float)))
                ids.append(int(cur.lastrowid))
        return ids

    def latest_opportunities(self) -> list[dict[str, Any]]:
        r = self.conn.execute("SELECT MAX(ts) FROM opportunities").fetchone()
        if not r or r[0] is None:
            return []
        rows = self.conn.execute("SELECT id, data FROM opportunities WHERE ts = ? ORDER BY rank",
                                 (r[0],)).fetchall()
        out = []
        for row in rows:
            d = json.loads(row["data"])
            d["id"] = row["id"]
            out.append(d)
        return out

    def opportunity_history(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT ts, score, side, expected_move_bps, net_edge_bps, rank FROM opportunities"
            " WHERE symbol = ? ORDER BY ts DESC LIMIT ?", (symbol, limit))]

    # ------------------------------------------------------------ positions
    def open_position(self, **kw: Any) -> int:
        kw.setdefault("opened_ts", now_ms())
        kw.setdefault("status", "pending")
        if "data" in kw and not isinstance(kw["data"], str):
            kw["data"] = json.dumps(kw["data"], default=float)
        cols = ", ".join(kw)
        q = ", ".join("?" for _ in kw)
        return int(self._write(f"INSERT INTO positions ({cols}) VALUES ({q})",
                               list(kw.values())).lastrowid)

    def update_position(self, pid: int, **kw: Any) -> None:
        if "data" in kw and not isinstance(kw["data"], str):
            kw["data"] = json.dumps(kw["data"], default=float)
        sets = ", ".join(f"{k} = ?" for k in kw)
        self._write(f"UPDATE positions SET {sets} WHERE id = ?", [*kw.values(), pid])

    def positions(self, status: Sequence[str] | None = None, limit: int = 500) -> list[dict[str, Any]]:
        if status:
            q = ",".join("?" for _ in status)
            rows = self.conn.execute(f"SELECT * FROM positions WHERE status IN ({q})"
                                     " ORDER BY id DESC LIMIT ?", (*status, limit))
        else:
            rows = self.conn.execute("SELECT * FROM positions ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data"]) if d.get("data") else {}
            out.append(d)
        return out

    def performance(self) -> dict[str, Any]:
        rows = self.conn.execute("SELECT pnl_quote, pnl_r, fees_quote FROM positions"
                                 " WHERE status = 'closed'").fetchall()
        n = len(rows)
        if not n:
            return {"trades": 0}
        r = [x["pnl_r"] or 0.0 for x in rows]
        return {"trades": n, "wins": sum(1 for x in r if x > 0),
                "win_rate": sum(1 for x in r if x > 0) / n,
                "avg_r": sum(r) / n, "total_r": sum(r),
                "pnl_quote": sum(x["pnl_quote"] or 0.0 for x in rows),
                "fees_quote": sum(x["fees_quote"] or 0.0 for x in rows)}

    # --------------------------------------------------------------- events
    def log(self, kind: str, message: str, symbol: str = "", level: str = "info") -> None:
        self._write("INSERT INTO events (ts, level, kind, symbol, message) VALUES (?,?,?,?,?)",
                    (now_ms(), level, kind, symbol, message))

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
