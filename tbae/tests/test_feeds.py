"""Data sources: the synthetic generator, CSV ingest, and the Binance clients.

Everything downstream is only as good as the bars it is fed, so this file pins
three different kinds of contract:

* the **synthetic generator** has to be deterministic (a seed must reproduce bits,
  never the wall clock) and realistic enough that conclusions drawn from it are
  not artefacts — 60s spacing, valid OHLC, GARCH volatility clustering, bounded
  jumps;
* **CSV ingest** has to round-trip what the engine wrote, de-duplicate and sort,
  and refuse malformed rows loudly instead of shifting every timestamp downstream;
* the **Binance clients** cannot be exercised against the network here, so they
  are tested through their parsing and pagination logic with the HTTP layer
  replaced — the part that would silently produce wrong bars on the user's
  machine.
"""
from __future__ import annotations

import io
import math
import os
import statistics

import pytest

from engine import feeds as F
from engine.feeds import (BinanceRestFeed, BinanceWsFeed, CsvFeed, SyntheticConfig,
                          SyntheticFeed, load_feed, write_minutes_csv)
from engine.mathx import autocorr
from engine.models import MinuteBar


def closes(bars):
    return [b.close for b in bars]


def log_returns(bars):
    return [math.log(bars[i].close / bars[i - 1].close) for i in range(1, len(bars))]


@pytest.fixture(scope="module")
def synth():
    return SyntheticFeed(SyntheticConfig(days=3, seed=1)).load()


# --------------------------------------------------------------------- #
# 1. the synthetic generator
# --------------------------------------------------------------------- #
class TestSyntheticFeed:
    def test_the_same_seed_reproduces_the_series_exactly(self):
        a = SyntheticFeed(SyntheticConfig(days=2, seed=7)).load()
        b = SyntheticFeed(SyntheticConfig(days=2, seed=7)).load()
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert (x.ts, x.open, x.high, x.low, x.close, x.volume) == \
                   (y.ts, y.open, y.high, y.low, y.close, y.volume)

    def test_a_different_seed_gives_a_different_series(self):
        a = SyntheticFeed(SyntheticConfig(days=2, seed=7)).load()
        b = SyntheticFeed(SyntheticConfig(days=2, seed=8)).load()
        assert closes(a) != closes(b)

    def test_it_does_not_read_the_wall_clock(self):
        """The single most important property for reproducible research: the same
        (seed, days) yields bit-identical data whenever it is generated."""
        bars = SyntheticFeed(SyntheticConfig(days=1, seed=3)).load()
        assert bars[-1].ts == F.DEFAULT_END_TS
        assert F.DEFAULT_END_TS % 60_000 == 0

    def test_follow_clock_is_opt_in_and_moves_the_window(self):
        live = SyntheticFeed(SyntheticConfig(days=1, seed=3, follow_clock=True)).load()
        assert live[-1].ts > F.DEFAULT_END_TS, "anchoring to now must move the end"

    def test_bar_count_includes_the_warmup_days(self):
        cfg = SyntheticConfig(days=2, seed=1)
        bars = SyntheticFeed(cfg).load()
        assert len(bars) == (cfg.days + cfg.warmup_days) * 1440

    def test_split_warmup_cuts_exactly_the_leading_warmup_days(self):
        cfg = SyntheticConfig(days=2, seed=1)
        feed = SyntheticFeed(cfg)
        bars = feed.load()
        warm, live = feed.split_warmup(bars)
        assert len(warm) == cfg.warmup_days * 1440
        assert len(live) == cfg.days * 1440
        assert warm + live == bars

    def test_minutes_are_exactly_60s_apart_and_strictly_increasing(self, synth):
        deltas = {synth[i].ts - synth[i - 1].ts for i in range(1, len(synth))}
        assert deltas == {60_000}

    def test_ohlc_is_internally_consistent(self, synth):
        for b in synth:
            assert b.high >= max(b.open, b.close)
            assert b.low <= min(b.open, b.close)
            assert b.high >= b.low > 0.0
            for v in (b.open, b.high, b.low, b.close, b.volume):
                assert math.isfinite(v)

    def test_volume_and_quote_volume_are_positive_and_coherent(self, synth):
        for b in synth:
            assert b.volume > 0.0
            assert b.quote_volume > 0.0
            # quote volume is notional, so it must be in the ballpark of vol*price
            implied = b.quote_volume / b.volume
            assert 0.5 * b.low <= implied <= 2.0 * b.high

    def test_taker_buy_volume_never_exceeds_total_volume(self, synth):
        assert all(0.0 <= b.taker_buy_volume <= b.volume for b in synth)

    def test_trade_counts_are_positive_integers(self, synth):
        assert all(isinstance(b.trades, int) and b.trades > 0 for b in synth)

    def test_the_series_starts_at_the_configured_price(self):
        bars = SyntheticFeed(SyntheticConfig(days=1, seed=1, start_price=42_000.0)).load()
        assert bars[0].open == pytest.approx(42_000.0, rel=1e-9)

    def test_per_minute_volatility_matches_the_documented_calibration(self, synth):
        """README-level claim: base_sigma 4.2e-4 -> ~7.3bp per minute, ~55%
        annualised.  If the generator drifted, every threshold calibrated against
        it would silently mean something else."""
        r = log_returns(synth)
        sd_bp = statistics.pstdev(r) * 10_000.0
        assert 5.5 < sd_bp < 9.5, f"1-minute sd is {sd_bp:.2f}bp, expected ~7.3"
        annual = statistics.pstdev(r) * math.sqrt(365 * 1440) * 100.0
        assert 35.0 < annual < 85.0, f"annualised vol {annual:.1f}%, expected ~55%"

    def test_volatility_clusters_like_a_garch_process(self, synth):
        """iid Gaussian minutes would make every volatility-regime filter in the
        engine meaningless; |r| must be autocorrelated."""
        r = log_returns(synth)
        absr = [abs(x) for x in r]
        assert autocorr(absr, 1) > 0.05, f"|r| lag-1 autocorr {autocorr(absr, 1):.3f}"
        assert autocorr([x * x for x in r], 1) > 0.05
        # and the level itself should not be predictable from its own past
        assert abs(autocorr(r, 1)) < 0.15

    def test_high_and_low_volatility_regimes_both_occur(self, synth):
        r = log_returns(synth)
        win = 60
        rolling = [statistics.pstdev(r[i:i + win]) for i in range(0, len(r) - win, win)]
        assert max(rolling) > 2.0 * min(rolling), (
            f"vol range too narrow: {min(rolling):.2e} .. {max(rolling):.2e}")

    def test_jumps_are_bounded_and_do_not_compound_into_an_explosion(self, synth):
        r = log_returns(synth)
        assert max(abs(x) for x in r) < 0.02, "a single minute moved more than 2%"
        lo, hi = min(closes(synth)), max(closes(synth))
        start = synth[0].open
        assert 0.2 * start < lo <= hi < 5.0 * start, (
            f"price escaped a sane band: {lo:.0f} .. {hi:.0f} from {start:.0f}")

    def test_a_long_run_stays_stable(self):
        bars = SyntheticFeed(SyntheticConfig(days=30, seed=11)).load()
        r = log_returns(bars)
        assert max(abs(x) for x in r) < 0.03
        assert statistics.pstdev(r) * 10_000.0 < 15.0

    def test_the_generator_passes_the_engine_own_minute_validator(self, synth):
        from engine.resample import validate_minutes
        assert validate_minutes(synth) is None, "the generator's own output must be valid"

    def test_tiny_requests_still_return_something_usable(self):
        bars = SyntheticFeed(SyntheticConfig(days=1, seed=1)).load()
        assert len(bars) >= 1440


# --------------------------------------------------------------------- #
# 2. CSV round trip
# --------------------------------------------------------------------- #
class TestCsvFeed:
    def test_write_then_read_round_trips(self, tmp_path, synth):
        path = str(tmp_path / "minutes.csv")
        sample = synth[:500]
        write_minutes_csv(sample, path)
        back = CsvFeed(path).load()
        assert len(back) == len(sample)
        for a, b in zip(sample, back):
            assert a.ts == b.ts
            # write_minutes_csv serialises prices with %.8g, so the round trip is
            # lossy at the 8th significant digit — plenty for BTC, and documented
            # here so nobody mistakes it for an exact copy
            for attr in ("open", "high", "low", "close"):
                assert getattr(a, attr) == pytest.approx(getattr(b, attr), rel=1e-7)
            assert a.volume == pytest.approx(b.volume, rel=1e-7)
            assert a.trades == b.trades

    def test_the_written_file_has_a_header_and_one_row_per_minute(self, tmp_path, synth):
        path = str(tmp_path / "minutes.csv")
        write_minutes_csv(synth[:10], path)
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        assert len(lines) == 11
        assert "ts" in lines[0] and "close" in lines[0]

    def test_duplicate_timestamps_are_collapsed(self, tmp_path):
        path = str(tmp_path / "dupes.csv")
        rows = ["ts,open,high,low,close,volume,quote_volume,taker_buy_volume,trades"]
        for _ in range(2):
            rows.append("1700000000000,1,2,0.5,1.5,10,15,4,3")
        rows.append("1700000060000,1.5,2.5,1.4,2.0,11,22,5,4")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        bars = CsvFeed(path).load()
        assert len(bars) == 2, "a duplicated minute must not become two bars"
        assert len(CsvFeed(path, drop_duplicates=False).load()) == 3

    def test_unsorted_rows_are_sorted_by_timestamp(self, tmp_path):
        path = str(tmp_path / "unsorted.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("ts,open,high,low,close,volume\n")
            for ts in (1700000120000, 1700000000000, 1700000060000):
                fh.write(f"{ts},1,2,0.5,1.5,10\n")
        bars = CsvFeed(path).load()
        assert [b.ts for b in bars] == sorted(b.ts for b in bars)
        assert CsvFeed(path, sort=False).load()[0].ts == 1700000120000

    def test_a_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises((ValueError, FileNotFoundError)):
            CsvFeed(str(tmp_path / "nope.csv")).load()

    @pytest.mark.parametrize("body", [
        "open,high,low,close\n1,2,0.5,1.5\n",                    # no ts column
        "ts,open,high,low,close,volume\n",                        # header only
        "",                                                        # no rows at all
        "ts,open,high,low,close,volume\nnot_a_number,1,2,0.5,1.5,10\n",
        "ts,open,high,low,close,volume\n1700000000000,1,2,0.5,NaN,10\n",
        "ts,open,high,low,close,volume\n1700000000000,1,2,0.5,-3,10\n",
    ])
    def test_unusable_files_are_rejected_loudly(self, tmp_path, body):
        """A NaN price parses as a float and survives every ``<= 0`` check, so it
        would otherwise walk into the indicators, the reference percentile and the
        backtest.  An empty result must be an error, not a silent []."""
        path = str(tmp_path / "bad.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        with pytest.raises(ValueError):
            CsvFeed(path).load()

    def test_a_bad_row_is_skipped_and_counted_while_the_rest_survive(self, tmp_path):
        path = str(tmp_path / "partial.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("ts,open,high,low,close,volume\n")
            fh.write("1700000000000,1,2,0.5,1.5,10\n")
            fh.write("1700000060000,1,2,0.5,NaN,10\n")     # dropped
            fh.write("1700000120000,1.5,2.5,1.4,2.0,11\n")
        feed = CsvFeed(path)
        bars = feed.load()
        assert [b.ts for b in bars] == [1700000000000, 1700000120000]
        assert feed.skipped_rows == 1

    def test_impossible_ohlc_is_repaired_rather_than_propagated(self, tmp_path):
        """Exchange exports are messy; the loader widens high/low to cover open and
        close so resample.validate_minutes never sees an impossible bar."""
        path = str(tmp_path / "impossible.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("ts,open,high,low,close,volume\n")
            fh.write("1700000000000,10,9,11,12,5\n")     # high < low < close
        b = CsvFeed(path).load()[0]
        assert b.high >= max(b.open, b.close)
        assert b.low <= min(b.open, b.close)

    def test_a_custom_delimiter_is_honoured(self, tmp_path, synth):
        path = str(tmp_path / "semi.csv")
        write_minutes_csv(synth[:20], path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read().replace(",", ";")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        assert len(CsvFeed(path, delimiter=";").load()) == 20

    def test_load_fileobj_accepts_an_open_stream(self, tmp_path, synth):
        path = str(tmp_path / "stream.csv")
        write_minutes_csv(synth[:20], path)
        with open(path, encoding="utf-8") as fh:
            assert len(CsvFeed().load_fileobj(fh)) == 20

    def test_load_fileobj_accepts_a_string_buffer(self, synth):
        buf = io.StringIO()
        rows = ["ts,open,high,low,close,volume,quote_volume,taker_buy_volume,trades"]
        for b in synth[:5]:
            rows.append(f"{b.ts},{b.open},{b.high},{b.low},{b.close},{b.volume},"
                        f"{b.quote_volume},{b.taker_buy_volume},{b.trades}")
        buf.write("\n".join(rows) + "\n")
        buf.seek(0)
        assert len(CsvFeed().load_fileobj(buf)) == 5


# --------------------------------------------------------------------- #
# 3. feed spec resolution
# --------------------------------------------------------------------- #
class TestLoadFeed:
    def test_bare_synthetic_spec(self):
        assert len(load_feed("synthetic:days=1,seed=5")) == 4 * 1440

    def test_spec_aliases(self):
        assert len(load_feed("synth:days=1")) == len(load_feed("demo:days=1"))

    def test_kwargs_override_the_spec(self):
        assert len(load_feed("synthetic", days=1, seed=5)) == 4 * 1440
        a = load_feed("synthetic", days=1, seed=5)
        b = load_feed("synthetic", days=1, seed=6)
        assert closes(a) != closes(b)

    def test_csv_spec(self, tmp_path, synth):
        path = str(tmp_path / "spec.csv")
        write_minutes_csv(synth[:50], path)
        assert len(load_feed(f"csv:{path}")) == 50

    def test_unknown_spec_is_rejected(self):
        with pytest.raises(ValueError, match="unknown feed spec"):
            load_feed("magic:days=1")

    def test_a_minute_bar_is_a_plain_value_object(self, synth):
        b = synth[0]
        assert isinstance(b, MinuteBar)
        assert b.ts > 0 and b.open > 0


# --------------------------------------------------------------------- #
# 4. the Binance clients (HTTP layer replaced: no network in CI)
# --------------------------------------------------------------------- #
def kline(ts, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0, qv=1005.0,
          taker=4.0, trades=7):
    """A row in Binance's kline array format (open time first)."""
    return [ts, str(o), str(h), str(l), str(c), str(v), ts + 59_999, str(qv),
            trades, str(taker), str(taker * 100.0), "0"]


def _kline_msg(ts, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0, qv=1005.0,
               taker=4.0, trades=7):
    """The same minute as it arrives over the websocket (``k`` object form)."""
    return {"t": ts, "o": str(o), "h": str(h), "l": str(l), "c": str(c),
            "v": str(v), "q": str(qv), "n": trades, "V": str(taker), "x": True}


class TestBinanceRestFeed:
    def test_construction_does_not_touch_the_network(self):
        feed = BinanceRestFeed(symbol="ethusdt", interval="1m")
        assert feed.symbol == "ETHUSDT", "symbols are case-normalised for the API"
        assert feed.base_url.startswith("https://")
        assert not feed.base_url.endswith("/")

    def test_kline_rows_are_parsed_into_minute_bars(self):
        rows = [kline(1_700_000_000_000 + i * 60_000) for i in range(3)]
        bars = BinanceRestFeed._parse(rows)
        assert len(bars) == 3
        assert bars[0].ts == 1_700_000_000_000
        assert bars[0].open == 100.0 and bars[0].close == 100.5
        assert bars[0].quote_volume == 1005.0
        assert bars[0].taker_buy_volume == 4.0
        assert bars[0].trades == 7

    def test_short_rows_do_not_crash_the_parser(self):
        bars = BinanceRestFeed._parse([[1_700_000_000_000, "1", "2", "0.5", "1.5", "3"]])
        assert len(bars) == 1
        assert bars[0].quote_volume == 0.0 and bars[0].trades == 0

    def test_load_paginates_until_the_window_is_covered(self, monkeypatch):
        calls: list[dict] = []

        def fake_get(path, params):
            calls.append(dict(params))
            start = params["startTime"]
            return [kline(start + i * 60_000) for i in range(1000)]

        feed = BinanceRestFeed()
        monkeypatch.setattr(feed, "_get", fake_get)
        t0 = 1_700_000_040_000                    # minute-aligned, like a real cursor
        assert t0 % 60_000 == 0
        end = t0 + 2_500 * 60_000
        bars = feed.load(start_ms=t0, end_ms=end)
        assert len(bars) == 2501, "the end bucket is inclusive and the last page is trimmed"
        assert bars[-1].ts == end
        assert len(calls) == 3, f"2501 minutes at 1000/page needs 3 calls, got {len(calls)}"
        assert all(c["interval"] == "1m" and c["symbol"] == "BTCUSDT" for c in calls)
        assert [b.ts for b in bars] == sorted(b.ts for b in bars)

    def test_load_stops_on_a_short_page(self, monkeypatch):
        calls: list[dict] = []

        def fake_get(path, params):
            calls.append(dict(params))
            return [kline(params["startTime"] + i * 60_000) for i in range(10)]

        feed = BinanceRestFeed()
        monkeypatch.setattr(feed, "_get", fake_get)
        bars = feed.load(start_ms=1_700_000_000_000, end_ms=None)
        assert len(bars) == 10 and len(calls) == 1, "a short page means the end of data"

    def test_load_honours_a_minute_limit(self, monkeypatch):
        def fake_get(path, params):
            return [kline(params["startTime"] + i * 60_000) for i in range(1000)]

        feed = BinanceRestFeed()
        monkeypatch.setattr(feed, "_get", fake_get)
        bars = feed.load(start_ms=1_700_000_000_000, limit_minutes=25)
        assert len(bars) == 25

    def test_load_refuses_to_run_without_a_window(self):
        with pytest.raises(ValueError, match="start_ms or limit_minutes"):
            BinanceRestFeed().load()

    def test_the_start_cursor_is_snapped_to_a_minute(self, monkeypatch):
        seen: list[int] = []

        def fake_get(path, params):
            seen.append(params["startTime"])
            return []

        feed = BinanceRestFeed()
        monkeypatch.setattr(feed, "_get", fake_get)
        feed.load(start_ms=1_700_000_000_000 + 12_345)
        assert seen[0] % 60_000 == 0

    def test_an_http_failure_is_reported_after_the_retries(self, monkeypatch):
        attempts = {"n": 0}

        def boom(path, params):
            attempts["n"] += 1
            raise OSError("no network in the sandbox")

        feed = BinanceRestFeed(max_retries=1)
        monkeypatch.setattr(feed, "_get", boom)
        with pytest.raises(OSError):
            feed.load(start_ms=1_700_000_000_000, end_ms=1_700_000_060_000)
        assert attempts["n"] == 1

    def test_an_api_key_is_taken_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "secret")
        assert BinanceRestFeed().api_key == "secret"
        monkeypatch.delenv("BINANCE_API_KEY")
        assert BinanceRestFeed().api_key is None

    def test_load_feed_parses_a_binance_spec_without_calling_out(self, monkeypatch):
        seen: list[dict] = []

        def fake_get(self, path, params):        # patched on the class: self is bound
            seen.append(dict(params))
            return []

        monkeypatch.setattr(BinanceRestFeed, "_get", fake_get)
        assert load_feed("binance:ETHUSDT:days=1,interval=1m") == []
        assert seen, "the spec should have driven a request"
        assert seen[0]["symbol"] == "ETHUSDT"
        # load_feed anchors on "now" (not minute-aligned) and the cursor is snapped
        # down to the minute, so the span is a day plus at most one partial minute
        delta = seen[0]["endTime"] - seen[0]["startTime"]
        assert 1440 * 60_000 <= delta <= 1440 * 60_000 + 59_999


class TestBinanceWsFeed:
    def test_construction_is_offline_and_configures_the_buffer(self):
        ws = BinanceWsFeed(symbol="btcusdt", interval="1m", capacity=10)
        assert ws.symbol == "BTCUSDT"
        assert ws.capacity == 10
        assert ws.snapshot() == [], "nothing has arrived yet"

    def test_the_ring_buffer_drops_the_oldest_minutes(self):
        ws = BinanceWsFeed(capacity=3)
        for i in range(6):
            ws._ingest({"k": _kline_msg(1_700_000_000_000 + i * 60_000)})
        snap = ws.snapshot(closed_only=False)
        assert len(snap) == 3
        assert [b.ts for b in snap] == [1_700_000_000_000 + i * 60_000 for i in (3, 4, 5)]

    def test_snapshot_is_sorted_and_deduplicated(self):
        ws = BinanceWsFeed(capacity=50)
        for i in (2, 0, 1, 0):        # the forming candle is re-sent, then re-ordered
            ws._ingest({"k": _kline_msg(1_700_000_000_000 + i * 60_000)})
        snap = ws.snapshot(closed_only=False)
        assert [b.ts for b in snap] == sorted(b.ts for b in snap)
        assert len(snap) == 3

    def test_a_still_forming_candle_is_not_handed_to_the_strategy(self):
        """Binance streams the forming candle repeatedly.  Publishing it would let
        the engine act on a bar that has not finished — the classic divergence
        between a live run and a backtest."""
        import time
        ws = BinanceWsFeed(capacity=10)
        now = int(time.time() * 1000)
        future = (now // 60_000 + 5) * 60_000          # a candle still in progress
        past = (now // 60_000 - 5) * 60_000
        ws._ingest({"k": _kline_msg(future)})
        ws._ingest({"k": _kline_msg(past)})
        assert [b.ts for b in ws.snapshot()] == [past], (
            "closed_only must withhold the unfinished minute")
        assert len(ws.snapshot(closed_only=False)) == 2

    def test_a_message_without_a_kline_is_ignored(self):
        ws = BinanceWsFeed(capacity=5)
        ws._ingest({})
        ws._ingest({"k": {}})
        assert ws.snapshot(closed_only=False) == []

    def test_the_stream_url_names_the_symbol_and_interval(self):
        ws = BinanceWsFeed(symbol="ethusdt", interval="1m")
        assert ws.url == f"{ws.base_url}/ws/ethusdt@kline_1m", "url is a property"
        assert ws.url.endswith("@kline_1m")

    def test_the_websocket_dependency_is_optional(self):
        """The engine must import and run without ``websockets`` installed; only
        connecting may fail, and it must say what to install."""
        assert not os.environ.get("TBAE_REQUIRE_WS")
        ws = BinanceWsFeed()
        assert hasattr(ws, "snapshot")
