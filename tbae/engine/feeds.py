"""Data sources: synthetic / csv / Binance REST / Binance websocket.

All feeds return ``list[MinuteBar]`` sorted ascending with no duplicates — that
is the contract ``resample.validate_minutes`` enforces downstream.

The synthetic feed
------------------
It is not ``random.gauss`` in a loop.  A backtest run on white noise will happily
report a Sharpe of 2 for a trend-following rule, because there is nothing in the
data to punish it.  This generator reproduces the properties that actually decide
whether a strategy survives:

* **regime switching** (Markov) between trend-up / trend-down / range / shock, so
  a trend filter has periods where it must stand aside;
* **GARCH(1,1) volatility clustering**, so volatility persists and ATR-based
  stops are sometimes sized against a stale regime;
* **intra-minute sub-paths** (5 ticks per minute) — without these, ``high``/``low``
  are decoration and the Garman-Klass / realised-vol estimators measure nothing;
* **hour-of-day and weekday seasonality** in both volatility and volume, so the
  timing heatmap has real structure to find and the volume z-score has a
  seasonality it must remove;
* **jumps / liquidation spikes**, which is what makes the reference's Max-Bar
  trimming necessary rather than cosmetic;
* **volume coupled to |return|**, and taker-buy volume coupled to the sign of the
  return, so the flow-imbalance indicator has signal instead of noise.

Everything is seeded: the same ``(seed, days)`` always yields bit-identical data,
which is what makes a backtest report reproducible.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import math
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .mathx import clamp
from .models import MINUTE_MS, MinuteBar

# --------------------------------------------------------------------------- #
# synthetic
# --------------------------------------------------------------------------- #
#: regime -> (drift per minute in sigma units, vol multiplier, jump prob, persistence)
#:
#: Calibrated against BTC/USDT 1-minute statistics (see ``scripts/calibrate_feed.py``):
#: with ``base_sigma=0.00042`` the generator produces ~7.3 bp per-minute stdev
#: (~53% annualised), a 99.9th-percentile minute of ~44 bp, a ~28% high/low range
#: over 20 days, and ``|r|`` autocorrelation of ~0.42 (volatility clustering).
_REGIMES: dict[str, tuple[float, float, float, float]] = {
    "trend_up": (0.045, 1.05, 0.0006, 0.985),
    "trend_down": (-0.045, 1.10, 0.0008, 0.985),
    "range": (0.000, 0.80, 0.0002, 0.975),
    "shock": (0.000, 2.00, 0.0025, 0.900),
}
_REGIME_NAMES = tuple(_REGIMES)

#: Fixed end timestamp for the synthetic feed: 2026-01-01T00:00:00Z.
#:
#: This used to default to ``datetime.now()`` floored to the minute, which made
#: the generator **not reproducible**: crossing a minute boundary between two
#: runs shifted the entire series by one minute, changing bar alignment and
#: therefore every downstream number (observed: 139 signals in one run, 137 in
#: the next, same seed, ~60 s apart).  A research engine whose "seeded" data
#: depends on the wall clock cannot be compared across runs, so the default is
#: now a constant.  Pass ``follow_clock=True`` to anchor to the present.
DEFAULT_END_TS = 1_767_225_600_000

#: relative volatility by UTC hour (crypto-ish: Asia + US overlap peaks)
_HOUR_VOL = (
    0.72, 0.70, 0.74, 0.80, 0.86, 0.90, 0.94, 1.00, 1.06, 1.08, 1.06, 1.02,
    1.00, 1.06, 1.18, 1.26, 1.28, 1.20, 1.10, 1.02, 0.96, 0.90, 0.84, 0.78,
)
#: relative volume by UTC hour
_HOUR_VOLU = (
    0.68, 0.64, 0.66, 0.72, 0.80, 0.88, 0.96, 1.04, 1.10, 1.10, 1.06, 1.00,
    0.98, 1.06, 1.22, 1.34, 1.38, 1.26, 1.12, 1.02, 0.94, 0.86, 0.78, 0.72,
)
#: relative volume by weekday (Mon..Sun); weekends thinner
_DAY_VOLU = (1.06, 1.04, 1.02, 1.02, 1.00, 0.86, 0.84)


@dataclass(slots=True)
class SyntheticConfig:
    days: int = 45
    seed: int = 20260913
    start_price: float = 60_000.0
    #: per-minute base vol (log return).  4.2e-4 -> ~7.3 bp realised, ~53% annualised.
    #: Note the GARCH unconditional variance equals ``base_sigma**2`` only when
    #: ``garch_omega == 1 - garch_alpha - garch_beta``; with the defaults below
    #: that identity holds (0.02 == 1 - 0.08 - 0.90).
    base_sigma: float = 0.00042
    garch_omega: float = 0.02
    garch_alpha: float = 0.08
    garch_beta: float = 0.90
    ticks_per_minute: int = 5
    jump_scale: float = 3.5          # jump size in sigma units
    volume_base: float = 12.0        # base units per minute
    #: last minute's ts.  ``None`` -> :data:`DEFAULT_END_TS` (a constant), so a
    #: given ``(seed, days)`` always yields bit-identical data.
    end_ts: int | None = None
    #: anchor the series to the current wall clock instead.  Useful for demos,
    #: **not** for reproducible research.
    follow_clock: bool = False
    warmup_days: int = 3             # extra leading days for indicator warm-up
    taker_coupling: float = 0.42
    #: hard bounds on the conditional-vol multiplier.  Without these the GARCH
    #: recursion can run away: one large innovation multiplies ``h``, which
    #: multiplies the next innovation, and the price series explodes.  Clamping
    #: the *multiplier* (not the recursion) keeps clustering while bounding it.
    vol_mult_floor: float = 0.35
    vol_mult_cap: float = 3.0
    #: per-minute log-return cap, in sigma units — models a circuit breaker and
    #: stops a single bar from moving the price by orders of magnitude.
    max_minute_move_sigma: float = 8.0


class SyntheticFeed:
    """Seeded, regime-aware 1-minute generator.  See module docstring."""

    def __init__(self, cfg: SyntheticConfig | None = None, **kw: Any) -> None:
        import dataclasses as _dc

        base = cfg or SyntheticConfig()
        if kw:
            # NB: ``slots=True`` dataclasses have no ``__dict__`` — build the
            # replacement from the declared fields.
            current = {f.name: getattr(base, f.name) for f in _dc.fields(base)}
            allowed = {f.name for f in _dc.fields(base)}
            current.update({k: v for k, v in kw.items() if k in allowed})
            base = SyntheticConfig(**current)
        self.cfg = base

    # -- public API --
    def load(self) -> list[MinuteBar]:
        c = self.cfg
        rng = random.Random(c.seed)
        total_days = c.days + c.warmup_days
        n_minutes = total_days * 1440
        if c.end_ts is not None:
            end = c.end_ts
        elif c.follow_clock:
            now = _dt.datetime.now(_dt.timezone.utc).replace(second=0, microsecond=0)
            end = int(now.timestamp() * 1000)
        else:
            end = DEFAULT_END_TS
        end = (end // MINUTE_MS) * MINUTE_MS
        start = end - (n_minutes - 1) * MINUTE_MS

        price = c.start_price
        h = c.base_sigma ** 2                  # GARCH conditional variance
        regime = "range"
        bars: list[MinuteBar] = []
        gauss = rng.gauss
        unif = rng.random

        for k in range(n_minutes):
            ts = start + k * MINUTE_MS
            dt = _dt.datetime.fromtimestamp(ts / 1000.0, _dt.timezone.utc)
            hour, wd = dt.hour, dt.weekday()

            # ---- regime switch (persist with prob p, else redraw) ----
            drift_mu, vol_mult, jump_p, persist = _REGIMES[regime]
            if unif() > persist:
                regime = _draw_regime(rng, regime)
                drift_mu, vol_mult, jump_p, persist = _REGIMES[regime]

            # ---- seasonality ----
            seas = _HOUR_VOL[hour] * (0.92 if wd >= 5 else 1.0)
            vsea = _HOUR_VOLU[hour] * _DAY_VOLU[wd]

            # ---- GARCH(1,1) on the minute return ----
            # ``sigma_m`` is the *conditional* vol: base vol scaled by the GARCH
            # state (clamped), the regime, and the hour-of-day seasonality.
            garch_mult = clamp(
                math.sqrt(max(h, 1e-18)) / c.base_sigma, c.vol_mult_floor, c.vol_mult_cap
            )
            sigma_m = c.base_sigma * garch_mult * vol_mult * seas
            sigma_m = max(sigma_m, 1e-9)
            mu_m = drift_mu * sigma_m

            o = price
            hi = lo = c_ = o
            sub = max(1, c.ticks_per_minute)
            s_sub = sigma_m / math.sqrt(sub)
            m_sub = mu_m / sub
            diffusion_ret = 0.0   # continuous component -> feeds GARCH
            jump_ret = 0.0        # discontinuous component -> excluded from GARCH
            for _ in range(sub):
                d = m_sub + s_sub * gauss(0.0, 1.0)
                diffusion_ret += d
                j = 0.0
                if unif() < jump_p:
                    j = c.jump_scale * sigma_m * gauss(0.0, 1.0)
                    j *= 1.0 if unif() < 0.5 else -1.0
                    jump_ret += j
                r = d + j
                c_ = c_ * math.exp(r)
                if c_ > hi:
                    hi = c_
                if c_ < lo:
                    lo = c_
            # keep prices strictly positive and bounded away from denormals
            c_ = max(c_, 1e-6)
            hi = max(hi, o, c_)
            lo = max(min(lo, o, c_), 1e-9)

            minute_ret = diffusion_ret + jump_ret
            # circuit breaker: cap the realised minute move, and reflect the cap
            # in OHLC so the bar stays internally consistent
            cap = c.max_minute_move_sigma * sigma_m
            if abs(minute_ret) > cap and minute_ret != 0.0:
                scale = cap / abs(minute_ret)
                c_ = o * math.exp(minute_ret * scale)
                hi = max(o, c_) * math.exp(abs(jump_ret) * scale * 0.5)
                lo = min(o, c_) * math.exp(-abs(jump_ret) * scale * 0.5)
                c_ = max(c_, 1e-6)
                hi = max(hi, o, c_)
                lo = max(min(lo, o, c_), 1e-9)
                minute_ret *= scale

            eps = minute_ret / sigma_m
            # Variance update uses the **diffusion** component only.  Feeding jumps
            # into it makes alpha*jump^2 dominate (a 6-sigma jump squares to 36x)
            # and the recursion runs away — that is what made an earlier version of
            # this generator produce prices of 9e16.
            h = (
                c.garch_omega * (c.base_sigma ** 2)
                + c.garch_alpha * (diffusion_ret ** 2)
                + c.garch_beta * h
            )

            # ---- volume: seasonal x activity x lognormal noise ----
            activity = 1.0 + 1.6 * min(abs(eps), 6.0)
            vol = max(0.0, c.volume_base * vsea * activity * math.exp(0.55 * gauss(0.0, 1.0)))
            quote = vol * ((hi + lo + c_) / 3.0)
            # taker-buy share rises with the minute's signed move
            imb = clamp(0.5 + c.taker_coupling * math.tanh(1.6 * eps), 0.0, 1.0)
            tbuy = vol * imb
            trades = max(1, int(vol * (2.5 + 3.0 * vsea)))

            bars.append(
                MinuteBar(
                    ts=ts,
                    open=o,
                    high=hi,
                    low=lo,
                    close=c_,
                    volume=vol,
                    quote_volume=quote,
                    taker_buy_volume=tbuy,
                    trades=trades,
                )
            )
            price = c_

        return bars

    def split_warmup(self, bars: Sequence[MinuteBar]) -> tuple[list[MinuteBar], list[MinuteBar]]:
        """Split off the leading warm-up days (used to seed indicators)."""
        cut = self.cfg.warmup_days * 1440
        return (list(bars[:cut]), list(bars[cut:]))


def _draw_regime(rng: random.Random, current: str) -> str:
    """Redraw a regime, biased towards leaving 'shock' quickly and rarely
    entering it from a quiet state (shocks are rare by construction)."""
    u = rng.random()
    if current == "shock":
        return "range" if u < 0.55 else ("trend_up" if u < 0.78 else "trend_down")
    if current == "range":
        if u < 0.02:
            return "shock"
        return "trend_up" if u < 0.51 else "trend_down"
    # trending -> keep, flip, or decay to range
    if u < 0.03:
        return "shock"
    if u < 0.42:
        return "range"
    if u < 0.71:
        return current
    return "trend_down" if current == "trend_up" else "trend_up"


# --------------------------------------------------------------------------- #
# csv
# --------------------------------------------------------------------------- #
_TS_KEYS = ("ts", "timestamp", "time", "datetime", "date", "open_time", "openTime")
_COL_ALIASES: dict[str, tuple[str, ...]] = {
    "open": ("open", "o", "open_price"),
    "high": ("high", "h", "high_price"),
    "low": ("low", "l", "low_price"),
    "close": ("close", "c", "close_price"),
    "volume": ("volume", "vol", "v", "base_volume"),
    "quote_volume": ("quote_volume", "quoteVolume", "turnover", "quote"),
    "taker_buy_volume": ("taker_buy_volume", "takerBuyBaseAssetVolume", "taker_buy"),
    "trades": ("trades", "n_trades", "count"),
}


def _pick(header: Sequence[str], names: Iterable[str]) -> int:
    lower = [h.strip().lower() for h in header]
    for n in names:
        nl = n.lower()
        if nl in lower:
            return lower.index(nl)
    return -1


def _parse_ts(raw: str) -> int:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty timestamp")
    # epoch ms / s
    try:
        v = float(raw)
        if v > 1e14:
            raise ValueError("timestamp out of range")
        if v > 1e11:          # milliseconds
            return int(v)
        if v > 1e9:           # seconds
            return int(v * 1000)
        raise ValueError(f"unrecognised epoch timestamp: {raw}")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = _dt.datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp format: {raw!r}")


def _to_float(raw: str, default: float = 0.0) -> float:
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class CsvFeed:
    """Load 1-minute bars from a CSV file or an open file-like object.

    Header names are matched case-insensitively against a set of aliases covering
    the common exchange exports (Binance vision dumps, TradingView, CryptoCompare).
    Timestamps may be epoch seconds, epoch milliseconds or ISO-8601.
    """

    def __init__(self, path: str | None = None, *, delimiter: str = ",",
                 drop_duplicates: bool = True, sort: bool = True,
                 compression: str = "auto") -> None:
        self.path = path
        self.delimiter = delimiter
        self.drop_duplicates = drop_duplicates
        self.sort = sort
        if compression not in ("auto", "gzip", "none"):
            raise ValueError(
                f"compression must be 'auto', 'gzip' or 'none'; got {compression!r}")
        self.compression = compression
        #: rows dropped for a non-finite or non-positive price (set by ``load``)
        self.skipped_rows = 0

    # -- gzip ------------------------------------------------------------- #
    # A year of 1-minute bars is ~18.6 MB of CSV and ~6.3 MB gzipped (~34%).
    # That ratio decides whether a multi-symbol, multi-year history can live in
    # a cache or a repository at all, so the reader/writer round-trip is part of
    # the data contract rather than an optimisation.  Parquet is deliberately
    # NOT supported: it needs a third-party dependency and would break the
    # "every number is reproducible from the stdlib alone" guarantee.
    @staticmethod
    def _is_gzip(path: str) -> bool:
        return str(path).lower().endswith((".gz", ".gzip"))

    def _open_for_read(self):
        if self.path is None:
            raise ValueError("CsvFeed needs a path")
        if self._is_gzip(self.path):
            import gzip
            return gzip.open(self.path, "rt", newline="", encoding="utf-8-sig")
        return open(self.path, "r", newline="", encoding="utf-8-sig")

    def load(self) -> list[MinuteBar]:
        if self.path is None:
            raise ValueError("CsvFeed needs a path")
        with self._open_for_read() as fh:
            return self.load_fileobj(fh)

    def load_fileobj(self, fh: Any) -> list[MinuteBar]:
        reader = csv.reader(fh, delimiter=self.delimiter)
        rows = [r for r in reader if r and any(c.strip() for c in r)]
        if not rows:
            raise ValueError(
                f"csv is empty: {self.path or '<stream>'} contains no rows at all")
        header = rows[0]
        # headerless numeric file: assume binance-vision kline column order
        if not any(c.isalpha() for c in header[0]):
            header = ["ts", "open", "high", "low", "close", "volume",
                      "close_time", "quote_volume", "trades",
                      "taker_buy_volume", "taker_buy_quote", "ignore"]
            body = rows
        else:
            body = rows[1:]

        i_ts = _pick(header, _TS_KEYS)
        idx = {k: _pick(header, v) for k, v in _COL_ALIASES.items()}
        if i_ts < 0 or idx["close"] < 0:
            raise ValueError(
                f"csv header must contain a timestamp and a close column; got {header}"
            )

        def col(row: Sequence[str], i: int, default: str = "") -> str:
            return row[i] if 0 <= i < len(row) else default

        out: list[MinuteBar] = []
        skipped = 0
        for r in body:
            ts = _parse_ts(col(r, i_ts))
            o = _to_float(col(r, idx["open"]))
            h = _to_float(col(r, idx["high"]))
            l = _to_float(col(r, idx["low"]))
            c = _to_float(col(r, idx["close"]))
            # ``float("nan")`` parses happily and ``nan <= 0`` is False, so without
            # this a single NaN price walks straight into every indicator, the
            # reference percentile and the backtest — and nothing downstream can
            # tell where it came from.
            if not all(math.isfinite(v) for v in (float(ts), o, h, l, c)):
                skipped += 1
                continue
            if c <= 0:
                skipped += 1
                continue
            if o <= 0:
                o = c
            if h <= 0:
                h = max(o, c)
            if l <= 0:
                l = min(o, c)
            h = max(h, o, c)
            l = min(l, o, c)
            out.append(
                MinuteBar(
                    ts=ts,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=_to_float(col(r, idx["volume"])),
                    quote_volume=_to_float(col(r, idx["quote_volume"])),
                    taker_buy_volume=_to_float(col(r, idx["taker_buy_volume"])),
                    trades=int(_to_float(col(r, idx["trades"]))),
                )
            )
        if self.sort:
            out.sort(key=lambda m: m.ts)
        self.skipped_rows = skipped
        if not out:
            raise ValueError(
                f"no valid minute bars parsed from {self.path or '<stream>'}: "
                f"{len(body)} data row(s), {skipped} skipped for a non-finite or "
                "non-positive price")
        if self.drop_duplicates:
            seen: set[int] = set()
            deduped: list[MinuteBar] = []
            for m in out:
                if m.ts in seen:
                    continue
                seen.add(m.ts)
                deduped.append(m)
            out = deduped
        return out


def write_minutes_csv(bars: Sequence[MinuteBar], path: str) -> None:
    """Write bars in the exact shape :class:`CsvFeed` reads back.

    The extension decides the container: ``.csv.gz``/``.csv.gzip`` are written
    gzipped, anything else plain.  Gzip is offered at all because a multi-symbol
    multi-year 1-minute store is only portable at ~34% of its raw size; it is
    opt-in so existing plain-CSV consumers are unaffected.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if CsvFeed._is_gzip(path):
        import gzip
        fh_ctx = gzip.open(path, "wt", newline="", encoding="utf-8")
    else:
        fh_ctx = open(path, "w", newline="", encoding="utf-8")
    with fh_ctx as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "datetime", "open", "high", "low", "close", "volume",
                    "quote_volume", "taker_buy_volume", "trades"])
        for b in bars:
            w.writerow([
                b.ts,
                _dt.datetime.fromtimestamp(b.ts / 1000.0, _dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S"),
                f"{b.open:.8g}", f"{b.high:.8g}", f"{b.low:.8g}", f"{b.close:.8g}",
                f"{b.volume:.8g}", f"{b.quote_volume:.8g}",
                f"{b.taker_buy_volume:.8g}", b.trades,
            ])


# --------------------------------------------------------------------------- #
# binance (REST + websocket)
# --------------------------------------------------------------------------- #
_BINANCE_REST = "https://api.binance.com"


class BinanceRestFeed:
    """Kline fetcher over REST using only ``urllib`` (no third-party HTTP stack).

    Paginates 1000 candles at a time and retries with exponential backoff on
    429/5xx.  ``interval`` must be a Binance kline interval; the engine wants
    ``"1m"`` because everything above it is derived locally.
    """

    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1m",
                 base_url: str = _BINANCE_REST, timeout: float = 15.0,
                 max_retries: int = 4, api_key: str | None = None) -> None:
        self.symbol = symbol.upper()
        self.interval = interval
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = api_key or os.environ.get("BINANCE_API_KEY")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "tbae/0.2"})
        if self.api_key:
            req.add_header("X-MBX-APIKEY", self.api_key)
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:      # noqa: PERF203
                if e.code in (418, 429) or e.code >= 500:
                    last = e
                    import time
                    time.sleep(min(2 ** attempt, 16) + (2.0 if e.code == 418 else 0.0))
                    continue
                raise
            except Exception as e:                   # network/DNS/timeout
                last = e
                import time
                time.sleep(min(2 ** attempt, 16))
        raise RuntimeError(f"binance request failed after {self.max_retries} tries: {last}")

    def load(self, *, start_ms: int | None = None, end_ms: int | None = None,
             limit_minutes: int | None = None) -> list[MinuteBar]:
        """Fetch ``[start_ms, end_ms]`` (inclusive of end bucket)."""
        out: list[MinuteBar] = []
        cursor = start_ms
        if cursor is None and limit_minutes:
            cursor = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000) \
                - limit_minutes * MINUTE_MS
        if cursor is None:
            raise ValueError("BinanceRestFeed.load needs start_ms or limit_minutes")
        cursor = (cursor // MINUTE_MS) * MINUTE_MS
        while True:
            params: dict[str, Any] = {
                "symbol": self.symbol, "interval": self.interval,
                "startTime": cursor, "limit": 1000,
            }
            if end_ms is not None:
                params["endTime"] = end_ms
            chunk = self._get("/api/v3/klines", params)
            if not chunk:
                break
            out.extend(self._parse(chunk))
            last_open = int(chunk[-1][0])
            nxt = last_open + MINUTE_MS
            if end_ms is not None and nxt > end_ms:
                break
            if len(chunk) < 1000:
                break
            if nxt <= cursor:      # defensive: never loop forever
                break
            cursor = nxt
            if limit_minutes and len(out) >= limit_minutes:
                break
        if end_ms is not None:
            # a page is requested in whole 1000-candle blocks, so the last one can
            # overshoot the window; the venue normally respects endTime, but keeping
            # rows past it would silently widen every backtest that asked for a range
            out = [b for b in out if b.ts <= end_ms]
        if limit_minutes:
            out = out[-limit_minutes:]
        return out

    @staticmethod
    def _parse(chunk: Iterable[Sequence[Any]]) -> list[MinuteBar]:
        bars: list[MinuteBar] = []
        for k in chunk:
            bars.append(
                MinuteBar(
                    ts=int(k[0]),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    quote_volume=float(k[7]) if len(k) > 7 else 0.0,
                    taker_buy_volume=float(k[9]) if len(k) > 9 else 0.0,
                    trades=int(k[8]) if len(k) > 8 else 0,
                )
            )
        return bars

    def ping(self) -> bool:
        try:
            self._get("/api/v3/ping", {})
            return True
        except Exception:
            return False


class BinanceWsFeed:
    """Live kline stream with a ring buffer and auto-reconnect.

    The websocket dependency is optional and imported lazily so the rest of the
    engine keeps working on a bare interpreter::

        pip install websockets

    ``snapshot()`` returns the closed minutes in ascending order, i.e. exactly the
    ``list[MinuteBar]`` contract every other feed honours — so the pipeline can be
    pointed at live data without changing a line of maths.
    """

    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1m",
                 capacity: int = 5000, base_url: str = "wss://stream.binance.com:9443") -> None:
        self.symbol = symbol.upper()
        self.interval = interval
        self.capacity = capacity
        self.base_url = base_url.rstrip("/")
        self._buf: dict[int, MinuteBar] = {}
        self._running = False

    @property
    def url(self) -> str:
        return f"{self.base_url}/ws/{self.symbol.lower()}@kline_{self.interval}"

    def _ingest(self, msg: dict[str, Any]) -> None:
        k = msg.get("k") or {}
        ts = int(k.get("t", 0))
        if not ts:
            return
        bar = MinuteBar(
            ts=ts,
            open=float(k.get("o", 0)), high=float(k.get("h", 0)),
            low=float(k.get("l", 0)), close=float(k.get("c", 0)),
            volume=float(k.get("v", 0)), quote_volume=float(k.get("q", 0)),
            taker_buy_volume=float(k.get("V", 0)), trades=int(k.get("n", 0)),
        )
        # an in-progress candle is overwritten until it closes; only closed
        # candles are ever handed to the strategy (no partial-bar look-ahead)
        self._buf[ts] = bar
        if len(self._buf) > self.capacity:
            for old in sorted(self._buf)[: len(self._buf) - self.capacity]:
                self._buf.pop(old, None)

    def snapshot(self, closed_only: bool = True) -> list[MinuteBar]:
        items = sorted(self._buf.values(), key=lambda m: m.ts)
        if closed_only and items:
            now = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)
            items = [m for m in items if m.ts + MINUTE_MS <= now]
        return items

    def run(self, on_bar: Callable[[MinuteBar], None] | None = None,
            max_reconnects: int = 10) -> None:
        try:
            import websockets.sync.client as wsc   # type: ignore
        except ImportError as e:                   # pragma: no cover
            raise RuntimeError(
                "BinanceWsFeed needs the 'websockets' package: pip install websockets"
            ) from e
        self._running = True
        attempt = 0
        while self._running and attempt <= max_reconnects:
            try:
                with wsc.connect(self.url, open_timeout=15) as ws:
                    attempt = 0
                    for raw in ws:
                        if not self._running:
                            break
                        msg = json.loads(raw)
                        self._ingest(msg)
                        k = msg.get("k") or {}
                        if k.get("x") and on_bar:       # candle closed
                            on_bar(self._buf[int(k["t"])])
            except Exception:                            # pragma: no cover
                attempt += 1
                import time
                time.sleep(min(2 ** attempt, 30))

    def stop(self) -> None:
        self._running = False


# --------------------------------------------------------------------------- #
# factory
# --------------------------------------------------------------------------- #
def load_feed(spec: str, **kw: Any) -> list[MinuteBar]:
    """Resolve a feed spec string to minute bars.

    ``"synthetic"``, ``"synthetic:days=45,seed=7"``, ``"csv:/path/to.csv"``,
    ``"binance:BTCUSDT:days=45"``.
    """
    parts = spec.split(":", 1)
    kind = parts[0].lower().strip()
    rest = parts[1] if len(parts) > 1 else ""

    if kind in ("synthetic", "synth", "demo"):
        opts = _parse_kv(rest)
        opts.update({k: v for k, v in kw.items() if k in SyntheticConfig.__slots__})
        cfg = SyntheticConfig(**_coerce(opts, SyntheticConfig))
        return SyntheticFeed(cfg).load()

    if kind == "csv":
        return CsvFeed(rest or kw.get("path")).load()

    if kind in ("binance", "bnb"):
        sym, _, tail = rest.partition(":")
        opts = _parse_kv(tail)
        opts.update(kw)
        days = int(float(opts.pop("days", 0) or 0))
        feed = BinanceRestFeed(symbol=sym or "BTCUSDT",
                               interval=opts.pop("interval", "1m"))
        end = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)
        start = end - days * 1440 * MINUTE_MS if days else None
        limit = int(float(opts.pop("minutes", 0) or 0)) or None
        return feed.load(start_ms=start, end_ms=end if days else None,
                         limit_minutes=limit if not days else None)

    raise ValueError(f"unknown feed spec: {spec!r}")


def _parse_kv(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in (s or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = v.strip()
        elif ":" in chunk:
            k, v = chunk.split(":", 1)
            out[k.strip()] = v.strip()
        else:
            out["path"] = chunk
    return out


def _coerce(opts: dict[str, Any], cls: type) -> dict[str, Any]:
    """String -> annotated type for dataclass construction."""
    import typing
    hints = typing.get_type_hints(cls)
    out: dict[str, Any] = {}
    for k, v in opts.items():
        if k not in hints:
            continue
        t = hints[k]
        origin = getattr(t, "__origin__", None)
        if origin is not None:                     # e.g. int | None
            args = [a for a in t.__args__ if a is not type(None)]
            t = args[0] if args else str
        if v is None or v == "":
            continue
        try:
            out[k] = t(v) if t is not str else str(v)
        except (TypeError, ValueError):
            continue
    return out
