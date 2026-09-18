"""Offline tests for ``scripts/fetch_binance.py``.

This sandbox has no route to the exchange (every Binance host fails at the TLS
handshake), so nothing here may touch the network: every test either exercises
pure functions or monkeypatches ``http_get``.  That constraint is a feature — the
suite runs in CI where the *runner* can reach the venue, and it must pass in
both places, so the downloader's logic has to be provable without a socket.

What matters most in here is the incremental path (``plan_append``): a long
history is built once and then extended by contiguous blocks, and a bug in that
arithmetic produces a series with a silent hole in the middle — which a backtest
would happily run on.
"""

from __future__ import annotations

import io
import os
import sys
import json
import zipfile

import pytest

_TBAE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TBAE not in sys.path:
    sys.path.insert(0, _TBAE)
_SCRIPTS = os.path.join(_TBAE, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import fetch_binance as fb                                     # noqa: E402
from engine.feeds import CsvFeed, write_minutes_csv            # noqa: E402
from engine.models import MINUTE_MS, MinuteBar                 # noqa: E402

T0 = 1_700_000_000_000 - (1_700_000_000_000 % MINUTE_MS)       # aligned epoch ms


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def bars(start_ms: int = T0, n: int = 10, price: float = 100.0) -> list[MinuteBar]:
    """A clean, gap-free series of ``n`` one-minute bars."""
    out = []
    for i in range(n):
        o = price + i * 0.01
        out.append(MinuteBar(ts=start_ms + i * MINUTE_MS, open=o, high=o + 0.5,
                             low=o - 0.5, close=o + 0.1, volume=10.0,
                             quote_volume=1000.0, taker_buy_volume=5.0, trades=7))
    return out


def kline_zip(rows: list[list], name: str = "BTCUSDT-1m-2024-03.csv") -> bytes:
    """A vision archive: one headerless CSV member in raw kline column order."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        body = "".join(",".join(str(c) for c in r) + "\n" for r in rows)
        zf.writestr(name, body)
    return buf.getvalue()


def kline_row(ts: int, price: float = 100.0) -> list:
    return [ts, price, price + 0.5, price - 0.5, price + 0.1,
            10.0, ts + MINUTE_MS - 1, 1000.0, 7, 5.0, 500.0, "0"]


# --------------------------------------------------------------------------- #
# import bootstrap — the bug this file was created for
# --------------------------------------------------------------------------- #
def test_module_imports_regardless_of_cwd():
    """The script must find ``engine/`` even when run from an unrelated cwd.

    It once lived at the repository root with a ``../`` path bootstrap written
    for ``scripts/``, so it raised ModuleNotFoundError from every location.
    """
    assert fb._ENGINE_ROOT.endswith("tbae")
    assert os.path.isdir(os.path.join(fb._ENGINE_ROOT, "engine"))
    assert CsvFeed is fb.CsvFeed


# --------------------------------------------------------------------------- #
# vision archive URLs and period arithmetic
# --------------------------------------------------------------------------- #
def test_vision_url_monthly_and_daily():
    assert fb.vision_url("BTCUSDT", "1m", "2024-03") == (
        "https://data.binance.vision/data/spot/monthly/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2024-03.zip")
    assert fb.vision_url("BTCUSDT", "1m", "2024-03-17") == (
        "https://data.binance.vision/data/spot/daily/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2024-03-17.zip")


def test_vision_url_honours_market_and_base():
    url = fb.vision_url("BTCUSDT", "1m", "2024-03", market="futures/um",
                        base="https://mirror.example/")
    assert "/data/futures/um/monthly/klines/" in url
    assert url.startswith("https://mirror.example/")


def test_months_covers_every_month_in_span():
    start = fb._parse_date("2024-01-15")
    end = fb._parse_date("2024-04-02")
    got = fb._months(start, end)
    assert got == [(2024, 1), (2024, 2), (2024, 3), (2024, 4)]


def test_days_covers_every_day_in_span():
    got = fb._days(fb._parse_date("2024-02-26"), fb._parse_date("2024-03-02"))
    assert [d.isoformat() for d in got] == [
        "2024-02-26", "2024-02-27", "2024-02-28", "2024-02-29",
        "2024-03-01", "2024-03-02"]


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def test_parse_kline_zip_reads_headerless_csv():
    rows = [kline_row(T0 + i * MINUTE_MS, 100.0 + i) for i in range(5)]
    parsed = fb.parse_kline_zip(kline_zip(rows))
    assert len(parsed) == 5
    assert [b.ts for b in parsed] == [T0 + i * MINUTE_MS for i in range(5)]
    assert parsed[0].open == 100.0
    assert parsed[0].trades == 7


def test_parse_kline_zip_rejects_archive_without_csv():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no data here")
    with pytest.raises(ValueError, match="no csv member"):
        fb.parse_kline_zip(buf.getvalue(), name="empty.zip")


# --------------------------------------------------------------------------- #
# checksum verification
# --------------------------------------------------------------------------- #
def test_verify_checksum_accepts_matching_digest(monkeypatch):
    import hashlib

    blob = b"payload"
    digest = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(fb, "http_get", lambda *a, **k: f"{digest}  file.zip\n".encode())
    assert fb.verify_checksum(blob, "https://x/file.zip") == digest


def test_verify_checksum_rejects_mismatch(monkeypatch):
    monkeypatch.setattr(fb, "http_get", lambda *a, **k: b"deadbeef  file.zip\n")
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        fb.verify_checksum(b"payload", "https://x/file.zip")


def test_verify_checksum_tolerates_missing_checksum(monkeypatch):
    monkeypatch.setattr(fb, "http_get", lambda *a, **k: None)
    assert fb.verify_checksum(b"payload", "https://x/file.zip").endswith(
        "(no published checksum)")


# --------------------------------------------------------------------------- #
# merge and QC
# --------------------------------------------------------------------------- #
def test_merge_dedupes_and_sorts():
    a = bars(T0, 5)
    b = bars(T0, 5)                       # fully overlapping
    c = bars(T0 + 5 * MINUTE_MS, 3)       # contiguous continuation
    merged = fb.merge(list(a) + list(b) + list(c))
    assert [x.ts for x in merged] == [x.ts for x in bars(T0, 8)]


def test_merge_trims_to_window():
    merged = fb.merge(bars(T0, 100), T0 + 10 * MINUTE_MS, T0 + 19 * MINUTE_MS)
    assert len(merged) == 10
    assert merged[0].ts == T0 + 10 * MINUTE_MS


def test_qc_flags_a_hole_and_a_duplicate():
    series = bars(T0, 10)
    holed = series[:3] + series[5:]                 # minutes 3 and 4 missing
    holed.append(holed[-1])                         # duplicate last bar
    q = fb.qc(holed)
    assert q["bars"] == 9
    assert q["missing_minutes"] == 2
    assert q["duplicates"] == 1
    assert q["missing_pct"] > 0
    assert q["largest_holes"], "a hole must be reported, not silently absorbed"


def test_qc_on_empty_series_reports_invalid():
    q = fb.qc([])
    assert q["bars"] == 0
    assert q["invalid"]


def test_qc_reports_a_corrupt_store_instead_of_raising():
    """A store that grows by appends will eventually contain a bad block.

    Killing the run over it is the wrong trade: the caller wants to *see* the
    corruption, named, in the report.
    """
    dup = bars(T0, 5) + [bars(T0, 5)[-1]]
    q = fb.qc(dup)
    assert q["duplicates"] == 1
    assert q["invalid"] and "duplicate" in q["invalid"]


# --------------------------------------------------------------------------- #
# incremental download — the arithmetic that must not drift
# --------------------------------------------------------------------------- #
def test_plan_append_fetches_everything_when_store_is_absent(tmp_path):
    p = tmp_path / "BTCUSDT_1m.csv"
    plan = fb.plan_append(str(p), T0, T0 + 100 * MINUTE_MS)
    assert plan["exists"] is False
    assert plan["fetch_start"] == T0
    assert plan["fetch_end"] == T0 + 100 * MINUTE_MS
    assert plan["cache_hit"] is False and plan["appending"] is False


def test_plan_append_extends_from_the_minute_after_the_last_bar(tmp_path):
    """The new block must start at last+1 — overlapping would duplicate,
    and leaving a gap would put a hole in the middle of the series."""
    p = tmp_path / "XRPUSDT_1m.csv"
    have = bars(T0, 50)
    write_minutes_csv(have, str(p))

    end = T0 + 100 * MINUTE_MS
    plan = fb.plan_append(str(p), T0, end)
    assert plan["appending"] is True
    assert plan["cache_hit"] is False
    assert plan["existing_bars"] == 50
    assert plan["fetch_start"] == T0 + 50 * MINUTE_MS
    assert plan["fetch_end"] == end


def test_plan_append_is_a_no_op_when_store_already_covers_window(tmp_path):
    p = tmp_path / "ETHUSDT_1m.csv"
    write_minutes_csv(bars(T0, 100), str(p))
    plan = fb.plan_append(str(p), T0, T0 + 50 * MINUTE_MS)
    assert plan["cache_hit"] is True
    assert plan["appending"] is False


def test_plan_append_reports_a_start_gap_without_backfilling(tmp_path):
    """Widening the window at the *start* must be reported loudly, not
    silently absorbed into the requested download."""
    p = tmp_path / "SOLUSDT_1m.csv"
    write_minutes_csv(bars(T0 + 30 * MINUTE_MS, 20), str(p))
    plan = fb.plan_append(str(p), T0, T0 + 90 * MINUTE_MS)
    assert plan["backfill_gap_minutes"] == 30
    assert plan["fetch_start"] == T0 + 50 * MINUTE_MS   # forward edge only


def test_plan_append_survives_an_unreadable_store(tmp_path):
    p = tmp_path / "BTCUSDT_1m.csv"
    p.write_text("ts,open,high,low,close\nnot,a,bar,at,all\n")
    plan = fb.plan_append(str(p), T0, T0 + 10 * MINUTE_MS)
    assert plan["exists"] is True
    assert plan["appending"] is False
    assert "load_error" in plan


# --------------------------------------------------------------------------- #
# gzip round-trip — the store has to be portable
# --------------------------------------------------------------------------- #
def test_gzip_round_trip_is_lossless(tmp_path):
    src = bars(T0, 40)
    p = tmp_path / "BTCUSDT_1m.csv.gz"
    write_minutes_csv(src, str(p))
    assert p.exists() and os.path.getsize(p) > 0
    back = CsvFeed(str(p)).load()
    assert [b.ts for b in back] == [b.ts for b in src]
    assert abs(back[7].close - src[7].close) < 1e-9


def test_gzip_store_is_much_smaller_than_plain(tmp_path):
    src = bars(T0, 2000)
    plain, gz = tmp_path / "a.csv", tmp_path / "a.csv.gz"
    write_minutes_csv(src, str(plain))
    write_minutes_csv(src, str(gz))
    assert os.path.getsize(gz) < 0.5 * os.path.getsize(plain)


def test_csv_feed_rejects_unknown_compression():
    with pytest.raises(ValueError, match="compression must be"):
        CsvFeed(compression="lzma")


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #
def test_default_out_path_is_stamped_with_both_ends(tmp_path):
    out = fb.default_out_path(str(tmp_path), "BTCUSDT", "1m",
                              fb._parse_date("2024-01-01"), fb._parse_date("2024-12-31"))
    assert os.path.basename(out) == "BTCUSDT_1m_20240101_20241231.csv"


def test_parse_date_accepts_three_shapes():
    assert fb._parse_date("2024-03-01") == fb._parse_date("2024-03-01T00:00:00")
    assert fb._parse_date("2024-03-01 00:00:00") == fb._parse_date("2024-03-01")


def test_parse_date_rejects_garbage():
    with pytest.raises(ValueError, match="unrecognised date"):
        fb._parse_date("yesterday")


def test_main_requires_a_window():
    with pytest.raises(SystemExit):
        fb.main(["--symbols", "BTCUSDT"])


# --------------------------------------------------------------------------- #
# end-to-end: does the store actually grow by contiguous blocks?
# --------------------------------------------------------------------------- #
def _day(ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc).strftime("%Y-%m-%d")


def test_main_append_grows_the_store_without_a_hole(tmp_path, monkeypatch):
    """The whole point of the incremental path.

    One day is already on disk; the run asks for four.  Exactly the missing
    block may be requested, it must start one minute after the last stored bar,
    and the result must be a single gap-free series — a hole in the middle would
    silently distort every indicator window that spans it.
    """
    calls: list[tuple[int, int]] = []

    def fake_fetch_rest(sym, interval, start_ms, end_ms, *, base=None, log=print):
        calls.append((start_ms, end_ms))
        n = (end_ms - start_ms) // MINUTE_MS + 1
        return bars(start_ms, n)

    monkeypatch.setattr(fb, "fetch_rest", fake_fetch_rest)

    stored_day = 1440
    p = tmp_path / "XRPUSDT_1m.csv"
    write_minutes_csv(bars(T0, stored_day), str(p))

    end_ms = T0 + 3 * 1440 * MINUTE_MS
    report_path = tmp_path / "report.json"
    rc = fb.main(["--symbols", "XRPUSDT", "--interval", "1m",
                  "--start", _day(T0), "--end", _day(end_ms),
                  "--source", "rest", "--append",
                  "--out", str(p), "--json", str(report_path), "--quiet"])

    assert rc == 0
    assert calls, "an append run must fetch the missing block"
    assert calls[0][0] == T0 + stored_day * MINUTE_MS, (
        "the request must begin exactly one minute after the last stored bar")

    final = CsvFeed(str(p)).load()
    assert len(final) > stored_day
    assert final[0].ts == T0
    gaps = [i for i in range(len(final) - 1) if final[i + 1].ts - final[i].ts != MINUTE_MS]
    assert not gaps, f"series is not contiguous at {gaps[:5]}"

    report = json.loads(report_path.read_text())["symbols"]["XRPUSDT"]
    assert report["reused_bars"] == stored_day
    assert report["appended_bars"] == len(final) - stored_day
    assert report["missing_pct"] == 0.0


def test_main_append_is_idempotent(tmp_path, monkeypatch):
    """A second run over a fully-covered window must fetch nothing."""
    calls: list[tuple[int, int]] = []

    def fake_fetch_rest(sym, interval, start_ms, end_ms, *, base=None, log=print):
        calls.append((start_ms, end_ms))
        return []

    monkeypatch.setattr(fb, "fetch_rest", fake_fetch_rest)

    p = tmp_path / "XRPUSDT_1m.csv"
    write_minutes_csv(bars(T0, 1440), str(p))
    rc = fb.main(["--symbols", "XRPUSDT", "--start", _day(T0),
                  "--end", _day(T0), "--source", "rest", "--append",
                  "--out", str(p), "--quiet"])
    assert rc == 0
    assert not calls, "nothing should be downloaded when the store already covers it"


def test_main_gzip_flag_changes_the_container(tmp_path, monkeypatch):
    def fake_fetch_rest(sym, interval, start_ms, end_ms, *, base=None, log=print):
        return bars(start_ms, (end_ms - start_ms) // MINUTE_MS + 1)

    monkeypatch.setattr(fb, "fetch_rest", fake_fetch_rest)
    rc = fb.main(["--symbols", "XRPUSDT", "--start", _day(T0), "--end", _day(T0),
                  "--source", "rest", "--gzip", "--out-dir", str(tmp_path), "--quiet"])
    assert rc == 0
    produced = list(tmp_path.glob("*.csv.gz"))
    assert produced, f"expected a .csv.gz store, found {[f.name for f in tmp_path.iterdir()]}"
    assert CsvFeed(str(produced[0])).load()
