#!/usr/bin/env python3
"""Download Binance klines into the CSV format ``engine.feeds.CsvFeed`` reads.

Why this script exists
----------------------
Every research number produced so far came from the deterministic synthetic
generator, because the sandbox the engine was built in has no route to the
exchange.  That is a property of the sandbox, not of the code: ``BinanceRestFeed``
was written and unit-tested offline, and the CLI already accepts
``--feed binance:BTCUSDT:days=45``.  What was missing is a way to pull *bulk*
history in one shot, verify it, and write it to disk as CSV — which is what this
does.  Run it anywhere with internet access (your machine, a CI runner), then
point any command at the file:

    python3 scripts/fetch_binance.py --symbols BTCUSDT --days 45
    python3 -m app.cli compare --feed csv:data/binance/BTCUSDT_1m.csv --tf 15

Two sources
-----------
``vision``  data.binance.vision public archives (monthly or daily zip files).
            One request per month, SHA256 published next to every archive,
            covers the whole listing history.  Use this for anything longer than
            ~2 weeks — it is roughly 40x fewer requests than REST paging.
``rest``    ``/api/v3/klines``, 1000 candles per request, paginated by
            ``startTime``.  Use it for the most recent days, or for an interval
            the archive does not carry.

``--source auto`` (the default) picks vision for spans longer than 21 days and
REST otherwise.

No API key is required: klines are public market data.  If ``BINANCE_API_KEY``
is set it is sent anyway, which raises the rate limit.

Geo-blocking
------------
``api.binance.com`` returns HTTP 451 from some jurisdictions.  ``--mirror``
switches the REST host to ``https://data-api.binance.vision``, a public
market-data mirror that serves the same endpoints.

Integrity
---------
Vision archives are verified against their published ``.CHECKSUM`` file unless
``--no-verify`` is passed, and the merged series is checked for duplicate and
missing minutes before it is written — a silent one-hour hole in the data would
otherwise show up as a mysterious gap in the backtest, not as an error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Iterable, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine import feeds as feeds_mod                      # noqa: E402
from engine.feeds import BinanceRestFeed, CsvFeed, MinuteBar  # noqa: E402
from engine.models import MINUTE_MS                        # noqa: E402
from engine.resample import validate_minutes               # noqa: E402

VISION_BASE = "https://data.binance.vision"
REST_BASE = "https://api.binance.com"
REST_MIRROR = "https://data-api.binance.vision"
USER_AGENT = "tbae/0.2 (+research)"

#: spans longer than this use the vision archive instead of REST paging
AUTO_VISION_DAYS = 21


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
def http_get(url: str, *, timeout: float = 30.0, retries: int = 5,
             accept_404: bool = False, pause: float = 0.12) -> bytes | None:
    """GET with exponential backoff on 418/429/5xx.  Returns ``None`` on 404.

    Binance answers rate-limit breaches with 429 and, if you keep going, a
    temporary IP ban (418) — both are signalled with a ``Retry-After`` header
    that is worth honouring instead of hammering.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            key = os.environ.get("BINANCE_API_KEY")
            if key:
                req.add_header("X-MBX-APIKEY", key)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if pause:
                time.sleep(pause)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404 and accept_404:
                return None
            if e.code in (418, 429) or e.code >= 500:
                last = e
                wait = e.headers.get("Retry-After") if e.headers else None
                try:
                    delay = float(wait) if wait else min(2 ** attempt, 20)
                except ValueError:
                    delay = min(2 ** attempt, 20)
                if e.code == 418:
                    delay += 2.0
                time.sleep(delay)
                continue
            raise RuntimeError(f"HTTP {e.code} for {url}: {e.read()[:200]!r}") from e
        except Exception as e:                       # DNS / TLS / timeout
            last = e
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"request failed after {retries} tries: {url} ({last})")


# --------------------------------------------------------------------------- #
# vision archive
# --------------------------------------------------------------------------- #
def _months(start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cur = dt.datetime.fromtimestamp(start_ms / 1000.0, dt.timezone.utc)
    end = dt.datetime.fromtimestamp(end_ms / 1000.0, dt.timezone.utc)
    cur = cur.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= end:
        out.append((cur.year, cur.month))
        cur = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return out


def _days(start_ms: int, end_ms: int) -> list[dt.date]:
    out: list[dt.date] = []
    cur = dt.datetime.fromtimestamp(start_ms / 1000.0, dt.timezone.utc).date()
    end = dt.datetime.fromtimestamp(end_ms / 1000.0, dt.timezone.utc).date()
    while cur <= end:
        out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def vision_url(symbol: str, interval: str, period: str, base: str = VISION_BASE,
               market: str = "spot") -> str:
    """``period`` is ``"2024-03"`` (monthly) or ``"2024-03-17"`` (daily)."""
    name = f"{symbol}-{interval}-{period}"
    gran = "monthly" if len(period) == 7 else "daily"
    return f"{base.rstrip('/')}/data/{market}/{gran}/klines/{symbol}/{interval}/{name}.zip"


def parse_kline_zip(blob: bytes, *, name: str = "<zip>") -> list[MinuteBar]:
    """Parse a Binance-vision kline archive.

    The CSV inside has **no header** and uses the raw kline column order, which
    ``CsvFeed`` already recognises — so this is a straight hand-off rather than a
    second parser that could drift from the first.
    """
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise ValueError(f"{name}: archive contains no csv member ({zf.namelist()[:5]})")
        with zf.open(members[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            return CsvFeed().load_fileobj(text)


def verify_checksum(blob: bytes, url: str, *, timeout: float = 30.0) -> str:
    """Check ``blob`` against the published ``.CHECKSUM``.  Returns the digest."""
    got = hashlib.sha256(blob).hexdigest()
    raw = http_get(url + ".CHECKSUM", timeout=timeout, accept_404=True)
    if raw is None:
        return f"{got} (no published checksum)"
    line = raw.decode("utf-8", "replace").strip().splitlines()[0]
    want = line.split()[0].strip().lower()
    if want != got:
        raise RuntimeError(f"sha256 mismatch for {url}: archive={got} published={want}")
    return got


def fetch_vision(symbol: str, interval: str, start_ms: int, end_ms: int, *,
                 granularity: str = "monthly", tail: str = "daily",
                 base: str = VISION_BASE, verify: bool = True,
                 log: Any = print) -> list[MinuteBar]:
    """Download and merge vision archives covering ``[start_ms, end_ms]``.

    Monthly archives are published only **after** a month closes, so a span that
    ends today always has an unpublished tail.  Downloading monthly archives
    alone therefore yields a series that silently stops up to a month ago — the
    backtest would still run, on stale data, and nothing would complain.  The
    tail is filled with daily archives (published the next day), and if the whole
    span falls inside the current month the daily archives are used for all of it.
    """
    if interval != "1m":
        log(f"  note: vision archives exist for {interval}, but the engine wants 1m "
            f"and derives every higher timeframe locally")

    def _grab(periods: Sequence[str], what: str) -> tuple[list[MinuteBar], list[str]]:
        got: list[MinuteBar] = []
        absent: list[str] = []
        for p in periods:
            url = vision_url(symbol, interval, p, base=base)
            blob = http_get(url, accept_404=True)
            if blob is None:
                # 404 on the oldest period is normal (symbol not listed yet);
                # on the newest it means "not published yet"
                absent.append(p)
                log(f"  {what} {p}: not published (404)")
                continue
            digest = verify_checksum(blob, url) if verify else "<skipped>"
            bars = parse_kline_zip(blob, name=p)
            got.extend(bars)
            log(f"  {what} {p}: {len(bars):>7,d} bars  {len(blob)/1e6:5.2f} MB  "
                f"sha256={digest[:12]}")
        return got, absent

    out: list[MinuteBar] = []
    if granularity.startswith("d"):
        out, _ = _grab([d.isoformat() for d in _days(start_ms, end_ms)], "daily")
    else:
        out, _ = _grab([f"{y:04d}-{m:02d}" for y, m in _months(start_ms, end_ms)],
                       "monthly")
        if not out:
            log("  no monthly archive covered this span (it is inside the current "
                "month) — falling back to daily archives")
            out, _ = _grab([d.isoformat() for d in _days(start_ms, end_ms)], "daily")
        elif tail.startswith("d"):
            last = max(b.ts for b in out)
            day_after = ((last // 86_400_000) + 1) * 86_400_000
            if day_after <= end_ms:
                n_days = len(_days(day_after, end_ms))
                log(f"  filling the unpublished tail with {n_days} daily archive(s) "
                    f"from {_iso(day_after)}")
                tail_bars, _ = _grab([d.isoformat() for d in _days(day_after, end_ms)],
                                     "daily")
                out.extend(tail_bars)
    return out


# --------------------------------------------------------------------------- #
# rest
# --------------------------------------------------------------------------- #
def fetch_rest(symbol: str, interval: str, start_ms: int, end_ms: int, *,
               base: str = REST_BASE, log: Any = print) -> list[MinuteBar]:
    pages = max(1, (end_ms - start_ms) // (1000 * MINUTE_MS) + 1)
    log(f"  rest: ~{pages} request(s) of 1000 candles from {base}")
    feed = BinanceRestFeed(symbol=symbol, interval=interval, base_url=base)
    return feed.load(start_ms=start_ms, end_ms=end_ms)


# --------------------------------------------------------------------------- #
# merge / QC
# --------------------------------------------------------------------------- #
def merge(bars: Iterable[MinuteBar], start_ms: int | None = None,
          end_ms: int | None = None) -> list[MinuteBar]:
    seen: dict[int, MinuteBar] = {}
    for b in bars:
        seen[b.ts] = b                     # last write wins; identical rows anyway
    out = [seen[k] for k in sorted(seen)]
    if start_ms is not None:
        out = [b for b in out if b.ts >= start_ms]
    if end_ms is not None:
        out = [b for b in out if b.ts <= end_ms]
    return out


def qc(bars: Sequence[MinuteBar]) -> dict[str, Any]:
    """Duplicates, missing minutes, OHLC sanity — reported, never silently fixed."""
    if not bars:
        return {"bars": 0, "missing_minutes": 0, "invalid": "empty series"}
    ts = [b.ts for b in bars]
    span = (ts[-1] - ts[0]) // MINUTE_MS + 1
    dupes = len(ts) - len(set(ts))
    invalid = validate_minutes(list(bars))
    holes: list[str] = []
    prev = ts[0]
    for t in ts[1:]:
        if t - prev > MINUTE_MS:
            gap = (t - prev) // MINUTE_MS - 1
            if len(holes) < 8:
                holes.append(f"{_iso(prev + MINUTE_MS)} (+{gap}m)")
        prev = t
    return {
        "bars": len(bars),
        "span_minutes": int(span),
        "missing_minutes": int(span - len(set(ts))),
        "missing_pct": round(100.0 * (span - len(set(ts))) / span, 4) if span else 0.0,
        "duplicates": dupes,
        "first": _iso(ts[0]),
        "last": _iso(ts[-1]),
        "largest_holes": holes,
        "invalid": invalid or None,
    }


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date(s: str) -> int:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {s!r} (want YYYY-MM-DD)")


def default_out_path(out_dir: str, symbol: str, interval: str, start_ms: int,
                     end_ms: int) -> str:
    stamp_a = dt.datetime.fromtimestamp(start_ms / 1000.0, dt.timezone.utc).strftime("%Y%m%d")
    stamp_b = dt.datetime.fromtimestamp(end_ms / 1000.0, dt.timezone.utc).strftime("%Y%m%d")
    return os.path.join(out_dir, f"{symbol}_{interval}_{stamp_a}_{stamp_b}.csv")


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="BTCUSDT", help="comma-separated, e.g. BTCUSDT,ETHUSDT")
    ap.add_argument("--interval", default="1m", help="Binance kline interval (engine wants 1m)")
    ap.add_argument("--days", type=int, default=0, help="lookback from now (UTC)")
    ap.add_argument("--start", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--source", choices=("auto", "vision", "rest"), default="auto")
    ap.add_argument("--granularity", choices=("monthly", "daily"), default="monthly",
                    help="vision archive size; daily is ~30x more requests but "
                         "works for spans inside the current month")
    ap.add_argument("--tail", choices=("daily", "none"), default="daily",
                    help="with monthly archives, fill the unpublished current-month "
                         "tail from daily archives (default) or leave the series "
                         "ending at the last month boundary")
    ap.add_argument("--out-dir", default=os.path.join("data", "binance"))
    ap.add_argument("--out", help="explicit output path (single symbol only)")
    ap.add_argument("--mirror", action="store_true",
                    help=f"use {REST_MIRROR} instead of {REST_BASE} (geo-blocked regions)")
    ap.add_argument("--no-verify", action="store_true", help="skip sha256 verification")
    ap.add_argument("--force", action="store_true", help="re-download even if the file exists")
    ap.add_argument("--json", help="write a machine-readable download report here")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    log: Any = (lambda *_x, **_k: None) if a.quiet else print
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    if a.out and len(symbols) != 1:
        ap.error("--out requires exactly one symbol")

    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    now = (now // MINUTE_MS) * MINUTE_MS
    if a.start or a.end:
        if not (a.start and a.end):
            ap.error("--start and --end must be given together")
        start_ms, end_ms = _parse_date(a.start), _parse_date(a.end) + 86_399_000
    elif a.days:
        end_ms = now
        start_ms = now - a.days * 1440 * MINUTE_MS
    else:
        ap.error("give --days N or both --start and --end")
    if end_ms <= start_ms:
        ap.error("end must be after start")

    span_days = (end_ms - start_ms) / (1440 * MINUTE_MS)
    rest_base = REST_MIRROR if a.mirror else REST_BASE
    report: dict[str, Any] = {
        "generated_utc": _iso(now),
        "start": _iso(start_ms), "end": _iso(end_ms), "span_days": round(span_days, 2),
        "interval": a.interval, "rest_base": rest_base, "symbols": {},
    }

    for sym in symbols:
        source = a.source
        if source == "auto":
            source = "vision" if span_days > AUTO_VISION_DAYS else "rest"
        out = a.out or default_out_path(a.out_dir, sym, a.interval, start_ms, end_ms)
        if os.path.exists(out) and not a.force:
            log(f"[{sym}] {out} exists — using it (pass --force to re-download)")
            bars = CsvFeed(out).load()
            source = "cache"
        else:
            log(f"[{sym}] {source} {_iso(start_ms)} .. {_iso(end_ms)}")
            t0 = time.perf_counter()
            if source == "vision":
                raw = fetch_vision(sym, a.interval, start_ms, end_ms,
                                   granularity=a.granularity, tail=a.tail,
                                   verify=not a.no_verify, log=log)
            else:
                raw = fetch_rest(sym, a.interval, start_ms, end_ms, base=rest_base, log=log)
            bars = merge(raw, start_ms, end_ms)
            log(f"[{sym}] merged {len(bars):,} bars in {time.perf_counter()-t0:.1f}s")

        checks = qc(bars)
        if not bars:
            log(f"[{sym}] FAILED: no bars returned")
            report["symbols"][sym] = {"source": source, "error": "no bars", **checks}
            continue
        if checks["missing_pct"] > 2.0:
            log(f"[{sym}] WARNING: {checks['missing_pct']}% of minutes are absent — "
                f"holes at {checks['largest_holes'][:3]}")
        if checks["invalid"]:
            log(f"[{sym}] WARNING: {checks['invalid']}")

        feeds_mod.write_minutes_csv(bars, out)
        size = os.path.getsize(out)
        log(f"[{sym}] wrote {out} ({size/1e6:.2f} MB) — {checks['first']} .. {checks['last']}")
        report["symbols"][sym] = {
            "source": source, "path": out, "bytes": size, **checks,
        }

    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)) or ".", exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
        log(f"report -> {a.json}")

    ok = all(s.get("bars", 0) > 0 for s in report["symbols"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
