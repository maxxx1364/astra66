"""Daily "wake-up" scanner: coins whose volume and structure change *before*
price makes its big move.

Runs on daily candles only, ~90 days per symbol, so a full-market scan is a
few hundred small requests.  Every feature at day *t* uses data up to and
including the close of *t*; a signal on *t* is acted on at the open of *t+1*.
That causality is what makes the study in ``scripts/wakeup_study.py`` honest.

Rule set (fixed before looking at results — see ``WakeupConfig``):

mandatory
    liquidity   20-day median quote volume >= ``min_quote_volume``
    rvol        today's quote volume >= ``min_rvol`` x the 20-day median
                *before* today
    not_jumped  today's move and the 5-day move are still small — the point
                is to be early, not to chase

confirming (need ``min_confirm`` of them)
    squeeze     10-day ATR / 60-day ATR below ``squeeze_ratio`` (as of yesterday)
    taker_buy   today's taker-buy share of volume >= ``min_taker_buy``
    rel_strength 20-day return beats BTC's 20-day return
    breakout    close above the highest high of the prior 20 days
    obv_trend   on-balance volume at a 20-day high while price is not
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

BINANCE_DATA = "https://data-api.binance.vision"
KLINE_COLS = ["ts", "open", "high", "low", "close", "volume", "close_ts", "quote_volume",
              "trades", "taker_buy_base", "taker_buy_quote", "_ignore"]

# never "coins": stablecoins, fiat, wrapped/pegged, leveraged tokens
EXCLUDE_BASES = {
    "USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "EUR", "GBP", "AUD", "TRY", "BRL",
    "UST", "USTC", "PAX", "SUSD", "USDD", "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "PAXG",
    "WBTC", "WBETH", "BETH", "RLUSD", "USDE",
}
CONFIRMING = ("squeeze", "taker_buy", "rel_strength", "breakout", "obv_trend")


@dataclass(slots=True)
class WakeupConfig:
    min_quote_volume: float = 1_000_000.0   # USDT per day (20-day median)
    min_rvol: float = 3.0
    max_day_move: float = 0.08              # |close/open - 1| on the signal day
    max_5d_move: float = 0.15               # close / close 5 days ago - 1
    squeeze_ratio: float = 0.75
    min_taker_buy: float = 0.55
    min_confirm: int = 2
    lookback_days: int = 90                 # what the daily scanner downloads


_LEVERAGED = re.compile(r"^(BTC|ETH|BNB|XRP|ADA|LINK|DOT|EOS|TRX|LTC|XLM|YFI|SUSHI|UNI|AAVE|FIL|"
                        r"SXP|XTZ|BCH|1INCH)(UP|DOWN|BULL|BEAR)$")


def is_coin_pair(symbol: str, base: str, quote: str) -> bool:
    return quote == "USDT" and base not in EXCLUDE_BASES and not _LEVERAGED.match(base)


def klines_frame(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=KLINE_COLS).drop(columns=["_ignore", "close_ts"])
    for c in df.columns:
        df[c] = pd.to_numeric(df[c])
    df["ts"] = df["ts"].astype("int64")
    return df


# --------------------------------------------------------------------------- #
# features and signals (pure functions — the study and the scanner share them)
# --------------------------------------------------------------------------- #
def features(df: pd.DataFrame, btc_close: pd.Series | None = None) -> pd.DataFrame:
    """Per-day features for one symbol.  ``df`` is daily OHLCV sorted by ts;
    ``btc_close`` is BTC's close indexed by ts (for relative strength)."""
    f = pd.DataFrame(index=df.index)
    f["ts"] = df["ts"]
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    qv = df["quote_volume"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

    base_vol = qv.shift(1).rolling(20, min_periods=15).median()
    f["liq"] = qv.rolling(20, min_periods=15).median()
    f["rvol"] = qv / base_vol
    f["day_move"] = c / o - 1
    f["move_5d"] = c / c.shift(5) - 1
    f["atr_ratio"] = (tr.rolling(10).mean() / tr.rolling(60, min_periods=40).mean()).shift(1)
    f["taker_buy"] = (df["taker_buy_quote"] / qv).where(qv > 0)
    ret20 = c / c.shift(20) - 1
    if btc_close is not None:
        b = btc_close.reindex(df["ts"].to_numpy()).to_numpy()
        btc20 = pd.Series(b, index=df.index)
        f["rel_20d"] = ret20 - (btc20 / btc20.shift(20) - 1)
    else:
        f["rel_20d"] = ret20
    f["breakout"] = c > h.shift(1).rolling(20).max()
    direction = np.sign(c.diff()).fillna(0)
    obv = (direction * qv).cumsum()
    f["obv_high"] = obv >= obv.rolling(20).max()
    f["price_not_high"] = c < c.rolling(20).max() * 0.97
    f["close"] = c
    return f


def signals(f: pd.DataFrame, cfg: WakeupConfig) -> pd.DataFrame:
    s = pd.DataFrame(index=f.index)
    s["liquidity"] = f["liq"] >= cfg.min_quote_volume
    s["rvol"] = f["rvol"] >= cfg.min_rvol
    s["not_jumped"] = (f["day_move"].abs() <= cfg.max_day_move) & (f["move_5d"] <= cfg.max_5d_move)
    s["squeeze"] = f["atr_ratio"] < cfg.squeeze_ratio
    s["taker_buy"] = f["taker_buy"] >= cfg.min_taker_buy
    s["rel_strength"] = f["rel_20d"] > 0
    s["breakout"] = f["breakout"].astype(bool)
    s["obv_trend"] = f["obv_high"].astype(bool) & f["price_not_high"].astype(bool)
    s = s.fillna(False).astype(bool)
    s["confirm"] = s[list(CONFIRMING)].sum(axis=1)
    s["eligible"] = s["liquidity"]
    s["signal"] = s["liquidity"] & s["rvol"] & s["not_jumped"] & (s["confirm"] >= cfg.min_confirm)
    # ranking score for the daily list: strength of the volume event + confirmations
    s["score"] = np.where(s["signal"],
                          s["confirm"] + np.log2(f["rvol"].clip(lower=1).fillna(1)), 0.0)
    return s


# --------------------------------------------------------------------------- #
# trade simulation on daily bars
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class TradeRule:
    target: float = 0.15          # +15 %
    stop: float = 0.08            # -8 %
    max_days: int = 14
    fee_per_side: float = 0.0035  # Tabdeal base taker
    slippage_per_side: float = 0.001

    @property
    def cost(self) -> float:
        return 2 * (self.fee_per_side + self.slippage_per_side)


def simulate(df: pd.DataFrame, entry_idx: int, rule: TradeRule) -> dict[str, Any] | None:
    """Enter at the open of ``entry_idx``; exit on stop / target / timeout.
    If stop and target fall in the same daily bar, the stop is assumed first
    (daily bars cannot tell the order, so the conservative choice)."""
    if entry_idx >= len(df):
        return None
    entry = float(df["open"].iat[entry_idx])
    if not entry > 0:
        return None
    stop_px, tgt_px = entry * (1 - rule.stop), entry * (1 + rule.target)
    last = min(entry_idx + rule.max_days, len(df)) - 1
    max_up = 0.0
    for j in range(entry_idx, last + 1):
        hi, lo = float(df["high"].iat[j]), float(df["low"].iat[j])
        max_up = max(max_up, hi / entry - 1)
        if lo <= stop_px:
            gross = -rule.stop if float(df["open"].iat[j]) > stop_px else float(df["open"].iat[j]) / entry - 1
            return {"gross": gross, "net": gross - rule.cost, "exit": "stop",
                    "days": j - entry_idx + 1, "max_up": max_up}
        if hi >= tgt_px:
            return {"gross": rule.target, "net": rule.target - rule.cost, "exit": "target",
                    "days": j - entry_idx + 1, "max_up": max_up}
    if last < entry_idx + rule.max_days - 1:
        return None                     # not enough future data: trade still open
    gross = float(df["close"].iat[last]) / entry - 1
    return {"gross": gross, "net": gross - rule.cost, "exit": "timeout",
            "days": last - entry_idx + 1, "max_up": max_up}


# --------------------------------------------------------------------------- #
# data access (public market data; no API key)
# --------------------------------------------------------------------------- #
class BinanceDaily:
    def __init__(self, base_url: str = BINANCE_DATA, spacing_s: float = 0.12,
                 timeout: float = 30.0,
                 opener: Callable[[str], bytes] | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.spacing = spacing_s
        self.timeout = timeout
        self._last = 0.0
        self._open = opener or self._http

    def _http(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "tbae-wakeup/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read()

    def get(self, path: str, **params: Any) -> Any:
        wait = self._last + self.spacing - time.time()
        if wait > 0:
            time.sleep(wait)
        url = f"{self.base}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(4):
            try:
                self._last = time.time()
                return json.loads(self._open(url))
            except Exception:  # noqa: BLE001 - network: retry with backoff
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")  # pragma: no cover

    def symbols(self, include_delisted: bool = False) -> list[str]:
        info = self.get("/api/v3/exchangeInfo")
        out = []
        for s in info["symbols"]:
            if not is_coin_pair(s["symbol"], s["baseAsset"], s["quoteAsset"]):
                continue
            if s["status"] == "TRADING" or include_delisted:
                out.append(s["symbol"])
        return sorted(out)

    def daily(self, symbol: str, start_ms: int | None = None, limit: int = 1000) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol, "interval": "1d", "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        return klines_frame(self.get("/api/v3/klines", **params))

    def tickers(self) -> list[dict[str, Any]]:
        return self.get("/api/v3/ticker/24hr")


def scan_today(data: BinanceDaily, cfg: WakeupConfig | None = None,
               symbols: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """The daily scan: one ticker call pre-filters by 24h volume, then ~90 daily
    candles per surviving symbol.  Returns the signal list for the last *closed*
    day, best first."""
    cfg = cfg or WakeupConfig()
    syms = list(symbols) if symbols is not None else data.symbols()
    vol = {t["symbol"]: float(t.get("quoteVolume", 0)) for t in data.tickers()}
    syms = [s for s in syms if vol.get(s, 0) >= cfg.min_quote_volume * 0.5]
    btc = data.daily("BTCUSDT", limit=cfg.lookback_days)
    now_ms = int(time.time() * 1000)
    btc = btc[btc["ts"] + 86_400_000 <= now_ms]          # closed days only
    btc_close = btc.set_index("ts")["close"]
    out = []
    for sym in syms:
        try:
            df = data.daily(sym, limit=cfg.lookback_days)
        except Exception:  # noqa: BLE001 - skip one bad symbol, keep scanning
            continue
        df = df[df["ts"] + 86_400_000 <= now_ms].reset_index(drop=True)
        if len(df) < 70:
            continue
        f = features(df, btc_close)
        s = signals(f, cfg)
        i = len(df) - 1
        if not s["signal"].iat[i]:
            continue
        out.append({"symbol": sym, "date": pd.to_datetime(df["ts"].iat[i], unit="ms").date().isoformat(),
                    "score": round(float(s["score"].iat[i]), 3),
                    "close": float(df["close"].iat[i]),
                    "rvol": round(float(f["rvol"].iat[i]), 2),
                    "day_move": round(float(f["day_move"].iat[i]), 4),
                    "taker_buy": round(float(f["taker_buy"].iat[i]), 3),
                    "rel_20d": round(float(f["rel_20d"].iat[i]), 4),
                    "confirm": [k for k in CONFIRMING if s[k].iat[i]]})
    return sorted(out, key=lambda r: -r["score"])


def config_dict(cfg: WakeupConfig) -> dict[str, Any]:
    return asdict(cfg)
