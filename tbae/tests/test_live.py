"""Live spot system — fully offline.

Tabdeal payloads below are copied from https://docs.tabdeal.org; the signing
check reproduces the official SDK's algorithm independently.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import random
import urllib.parse

import pytest

from live import dna as dna_mod
from live import filters, ranking
from live.candles import MINUTE_MS, SymbolCandles, fill_gaps, trades_to_minutes
from live.config import DnaConfig, ExecutionConfig, FeeConfig, FilterConfig, LiveConfig, SelectorConfig
from live.exchange.base import ExchangeError, Market, OrderBook, Trade
from live.exchange.tabdeal import (TabdealAdapter, TabdealDepthStream, parse_account,
                                   parse_book, parse_market, sign)
from live.execution import ExecutionEngine
from live.market_data import MarketDataEngine
from live.runner import Runner
from live.selector import CandidateSelector
from live.storage import Store

T0 = 1_760_000_000_000 - (1_760_000_000_000 % MINUTE_MS)   # a minute boundary

DOC_MARKET = {
    "symbol": "BTCIRT", "tabdealSymbol": "BTC_IRT", "status": "TRADING",
    "baseAsset": "BTC", "quoteAsset": "IRT",
    "filters": [
        {"filterType": "PRICE_FILTER", "minPrice": "300.0", "maxPrice": "3e10", "tickSize": "1.00000000"},
        {"filterType": "LOT_SIZE", "minQty": "0.00005000", "stepSize": "0.00000001"},
        {"filterType": "MIN_NOTIONAL", "minNotional": "99000.00000000", "applyToMarket": False},
    ],
}
DOC_TRADES = [
    {"id": 18, "price": "100000000.0", "qty": "0.025", "quoteQty": "0.0249",
     "time": 1648990888735, "isBuyerMaker": False},
    {"id": 17, "price": "99999999.0", "qty": "0.025", "quoteQty": "2489999.97",
     "time": 1648990780492, "isBuyerMaker": True},
]
DOC_ACCOUNT = {"makerCommission": 40, "takerCommission": 40, "canTrade": True,
               "canWithdraw": False, "canDeposit": False,
               "balances": [{"asset": "BTC", "free": "0.052972", "freeze": "0.047"},
                            {"asset": "IRT", "free": "99990721.2", "freeze": "0"}]}


# --------------------------------------------------------------------------- #
# Tabdeal adapter
# --------------------------------------------------------------------------- #
class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode()


def _adapter(responses, **kw):
    clock = kw.pop("clock", lambda: 1_700_000_000.0)
    return TabdealAdapter("KEY", "SECRET", transport=FakeTransport(responses),
                          min_spacing_s=0, clock=clock, sleep=lambda s: None, **kw)


def test_parse_documented_payloads():
    m = parse_market(DOC_MARKET)
    assert (m.symbol, m.base, m.quote, m.tick_size, m.step_size, m.min_notional) == \
        ("BTCIRT", "BTC", "IRT", 1.0, 1e-8, 99000.0)
    assert m.round_price(123.9) == 123.0 and m.round_qty(0.123456789) == 0.12345678
    acc = parse_account(DOC_ACCOUNT)
    assert acc.maker_bps == 40 and acc.taker_bps == 40 and not acc.can_withdraw
    assert acc.balances["BTC"] == (0.052972, 0.047)


def test_public_get_routes_to_read_prefix_and_sorts_trades():
    ad = _adapter([(200, DOC_TRADES)])
    trades = ad.recent_trades("BTC_IRT", limit=5000)
    method, url, headers, body = ad.transport.calls[0]
    assert method == "GET" and body is None
    assert url.startswith("https://api1.tabdeal.org/r/api/v1/trades?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q == {"tabdealSymbol": ["BTC_IRT"], "limit": ["1000"]}     # capped at 1000
    assert "X-MBX-APIKEY" not in headers
    assert [t.id for t in trades] == [17, 18]
    assert trades[0].taker_buy is False and trades[1].taker_buy is True


def test_signed_post_uses_form_body_and_sdk_signature():
    ad = _adapter([(200, {"orderId": 139, "symbol": "BTCIRT", "status": "NEW", "side": "BUY",
                          "type": "LIMIT", "price": "100", "origQty": "0.001",
                          "executedQty": "0", "cummulativeQuoteQty": "0"})])
    o = ad.place_order("BTCIRT", "buy", "limit", 0.001, 100.0, "cid-1")
    method, url, headers, body = ad.transport.calls[0]
    assert method == "POST" and url == "https://api1.tabdeal.org/api/v1/order"
    assert headers["X-MBX-APIKEY"] == "KEY"
    params = urllib.parse.parse_qsl(body.decode())
    assert params[-1][0] == "signature" and params[-2] == ("timestamp", "1700000000000")
    unsigned = urllib.parse.urlencode(params[:-1])
    expected = hmac.new(b"SECRET", unsigned.encode(), hashlib.sha256).hexdigest()
    assert params[-1][1] == expected == sign("SECRET", dict(params[:-1]))
    assert dict(params)["quantity"] == "0.001" and dict(params)["newClientOrderId"] == "cid-1"
    assert o.order_id == 139 and o.is_open


def test_signed_call_without_keys_is_refused():
    ad = TabdealAdapter(transport=FakeTransport([]), min_spacing_s=0)
    with pytest.raises(ExchangeError, match="not configured"):
        ad.account()


def test_rate_limit_is_retried_and_client_errors_raise():
    ad = _adapter([(429, {"code": 1216, "msg": "too many"}), (200, [DOC_MARKET])])
    assert ad.markets()[0].symbol == "BTCIRT"
    assert len(ad.transport.calls) == 2
    ad = _adapter([(400, {"code": 1206, "msg": "market not found"})])
    with pytest.raises(ExchangeError) as e:
        ad.order_book("NOPE")
    assert e.value.code == 1206 and not e.value.rate_limited


def test_depth_websocket_message_parsing():
    got = []
    msg = {"stream": "usdtirt@depth@2000ms", "data": {
        "e": "depthUpdate", "E": 1657530675579, "s": "USDTIRT",
        "b": [["32267", "31.5"], ["32290", "155.9"]], "a": [["32427", "9.8"], ["32311", "76.3"]]}}
    assert TabdealDepthStream.handle_message(json.dumps(msg), got.append)
    b = got[0]
    assert b.symbol == "USDTIRT" and b.best_bid == 32290 and b.best_ask == 32311
    assert 0 < b.spread_bps < 10
    assert not TabdealDepthStream.handle_message(json.dumps({"result": None, "id": 1}), got.append)
    # the futures stream sends ``data`` as a JSON string
    msg["data"] = json.dumps(msg["data"])
    assert TabdealDepthStream.handle_message(json.dumps(msg), got.append)


# --------------------------------------------------------------------------- #
# live candle engine
# --------------------------------------------------------------------------- #
def _t(i, minute, sec, price, qty=1.0, buy=True):
    return Trade(id=i, ts=T0 + minute * MINUTE_MS + sec * 1000, price=price, qty=qty,
                 is_buyer_maker=not buy)


def test_trades_to_minutes_ohlcv_and_taker_flow():
    df = trades_to_minutes([_t(1, 0, 1, 10, 2, True), _t(2, 0, 30, 12, 1, False),
                            _t(3, 0, 59, 11, 1, True), _t(4, 2, 5, 13, 1, True)])
    r = df.iloc[0]
    assert (r.open, r.high, r.low, r.close, r.volume, r.taker_buy_volume, r.trades) == \
        (10, 12, 10, 11, 4, 3, 3)
    assert r.quote_volume == 10 * 2 + 12 + 11
    full = fill_gaps(df)
    assert list(full.ts) == [T0, T0 + MINUTE_MS, T0 + 2 * MINUTE_MS]
    flat = full.iloc[1]
    assert flat.open == flat.close == 11 and flat.volume == 0 and flat.trades == 0


def test_symbol_candles_dedupe_closed_only_and_gap_fill():
    sc = SymbolCandles("X")
    w1 = [_t(1, 0, 10, 10), _t(2, 0, 50, 11), _t(3, 1, 5, 12)]
    r = sc.ingest(w1, now_ms=T0 + MINUTE_MS + 20_000)           # inside minute 1
    assert r.new_trades == 3 and [b.ts for b in r.closed] == [T0]
    assert r.closed[0].close == 11 and r.forming.close == 12
    # overlapping window + nothing for minute 2, now inside minute 4
    w2 = w1 + [_t(4, 1, 40, 9)]
    r = sc.ingest(w2, now_ms=T0 + 4 * MINUTE_MS + 1_000)
    assert r.new_trades == 1
    assert [b.ts for b in r.closed] == [T0 + MINUTE_MS, T0 + 2 * MINUTE_MS, T0 + 3 * MINUTE_MS]
    m1, m2, m3 = r.closed
    assert (m1.open, m1.high, m1.low, m1.close, m1.trades) == (12, 12, 9, 9, 2)
    assert m2.volume == 0 and m2.open == m2.close == 9 and m3.close == 9
    # re-polling the same window adds nothing
    assert sc.ingest(w2, now_ms=T0 + 4 * MINUTE_MS + 2_000).new_trades == 0


def test_full_window_of_unseen_trades_is_a_gap():
    sc = SymbolCandles("X")
    sc.ingest([_t(1, 0, 1, 10), _t(2, 0, 2, 10)], now_ms=T0 + 30_000, limit=2)
    r = sc.ingest([_t(50, 0, 20, 10), _t(51, 0, 21, 10)], now_ms=T0 + 40_000, limit=2)
    assert r.gap
    r = sc.ingest([_t(51, 0, 21, 10), _t(52, 0, 22, 10)], now_ms=T0 + 45_000, limit=2)
    assert not r.gap


def test_first_full_window_drops_truncated_minute():
    sc = SymbolCandles("X")
    w = [_t(1, 0, 50, 10), _t(2, 1, 10, 11), _t(3, 1, 20, 12)]
    r = sc.ingest(w, now_ms=T0 + 2 * MINUTE_MS + 1, limit=3)
    assert [b.ts for b in r.closed] == [T0 + MINUTE_MS]


# --------------------------------------------------------------------------- #
# simulated exchange
# --------------------------------------------------------------------------- #
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class SimExchange:
    """Random-walk markets whose trades appear as the clock advances."""

    name = "sim"

    def __init__(self, clock, specs, seed=7):
        self.clock = clock
        self.rng = random.Random(seed)
        self.specs = specs            # symbol -> dict(price, drift_bps, vol_bps, rate, qty)
        self.tape = {s: [] for s in specs}
        self.price = {s: v["price"] for s, v in specs.items()}
        self.next_id = 1
        self.t_gen = clock() - 60.0 * 60 * 3
        self.orders = []

    def _advance(self):
        now = self.clock()
        while self.t_gen < now:
            self.t_gen += 1.0
            for s, v in self.specs.items():
                if self.rng.random() < v["rate"]:
                    p = self.price[s] * math.exp(v["drift_bps"] / 1e4 / 60
                                                 + self.rng.gauss(0, v["vol_bps"] / 1e4))
                    self.price[s] = p
                    self.tape[s].append(Trade(self.next_id, int(self.t_gen * 1000), p,
                                              v["qty"] * (0.5 + self.rng.random()),
                                              self.rng.random() > v.get("buy", 0.55)))
                    self.next_id += 1
                    if len(self.tape[s]) > 5000:
                        del self.tape[s][:1000]

    def markets(self):
        return [Market(s, s[:-4], s[-4:], tick_size=1e-6, step_size=1e-6, min_qty=1e-6,
                       min_notional=5.0) for s in self.specs]

    def recent_trades(self, symbol, limit=1000):
        self._advance()
        return list(self.tape[symbol][-limit:])

    def order_book(self, symbol, limit=50):
        self._advance()
        p = self.price[symbol]
        sp = self.specs[symbol].get("spread_bps", 4) / 2e4
        lv = [(p * (1 - sp - i * 1e-4), 50_000 / p) for i in range(10)]
        la = [(p * (1 + sp + i * 1e-4), 50_000 / p) for i in range(10)]
        return OrderBook(symbol, int(self.clock() * 1000), lv, la)

    def history_ohlcv(self, symbol, since_ms, limit=1000):
        return None

    def account(self):
        raise ExchangeError("paper")


SPECS = {
    "TRNDUSDT": dict(price=100.0, drift_bps=6.0, vol_bps=4.0, rate=0.6, qty=50.0, buy=0.35),
    "FLATUSDT": dict(price=50.0, drift_bps=0.0, vol_bps=0.3, rate=0.5, qty=100.0),
    "WIDEUSDT": dict(price=10.0, drift_bps=0.0, vol_bps=6.0, rate=0.5, qty=500.0, spread_bps=300),
    "DEADUSDT": dict(price=1.0, drift_bps=0.0, vol_bps=3.0, rate=0.002, qty=10.0),
}


def _cfg(**kw):
    cfg = LiveConfig(db_path=":memory:", scan_interval_s=60, trades_poll_s=20,
                     universe_poll_s=3600,
                     selector=SelectorConfig(max_candidates=3, min_hold_s=600),
                     dna=DnaConfig(timeframe=15, min_minutes=60, engine_min_bars=260))
    cfg.filters.quote_assets = ("USDT",)
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_filters_and_selector_on_simulated_universe():
    clock = Clock(T0 / 1000)
    ex = SimExchange(clock, SPECS)
    store = Store()
    cfg = _cfg()
    md = MarketDataEngine(ex, store, cfg, clock=clock)
    md.refresh_markets()
    for _ in range(40):                       # 40 minutes of sweeps
        clock.t += 60
        md.sweep(len(SPECS))
    from live import scanner
    rows = filters.apply(scanner.scan_all(md), cfg.filters, cfg.fees)
    by = {r["symbol"]: r for r in rows}
    assert by["TRNDUSDT"]["passed"], by["TRNDUSDT"]["reasons"]
    assert "range_vs_fees" in by["FLATUSDT"]["reasons"]
    assert "spread" in by["WIDEUSDT"]["reasons"]
    assert "activity" in by["DEADUSDT"]["reasons"]
    sel = CandidateSelector(cfg.selector, cfg.fees)
    assert sel.select(rows, clock()) == ["TRNDUSDT"]
    # candles were persisted for every symbol, with no gaps in the grid
    bars = store.candles("FLATUSDT")
    assert len(bars) >= 35
    assert all(b.ts - a.ts == MINUTE_MS for a, b in zip(bars, bars[1:]))


def test_selector_hysteresis_keeps_protected_incumbent():
    sel = CandidateSelector(SelectorConfig(max_candidates=1, min_hold_s=100, evict_margin=1.2),
                            FeeConfig())
    row = lambda s, rng: {"symbol": s, "passed": True, "range_bps": rng, "spread_bps": 5,
                          "notional_per_min": 1e4, "buy_share": 0.5}
    assert sel.select([row("A", 500), row("B", 400)], 0) == ["A"]
    assert sel.select([row("A", 400), row("B", 600)], 50) == ["A"]       # protected
    assert sel.select([row("A", 400), row("B", 450)], 200) == ["A"]      # margin not beaten
    assert sel.select([row("A", 400), row("B", 600)], 200) == ["B"]


# --------------------------------------------------------------------------- #
# DNA + ranking
# --------------------------------------------------------------------------- #
def _walk(n, drift_bps, vol_bps, seed=3):
    from engine.models import MinuteBar
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        o = p
        p = p * math.exp(drift_bps / 1e4 + rng.gauss(0, vol_bps / 1e4))
        hi, lo = max(o, p) * (1 + abs(rng.gauss(0, vol_bps / 3e4))), min(o, p) * (1 - abs(rng.gauss(0, vol_bps / 3e4)))
        v = 10 + rng.random()
        out.append(MinuteBar(T0 + i * MINUTE_MS, o, hi, lo, p, v, v * p, v * 0.6, 5))
    return out


def test_dna_detects_uptrend_and_ranking_scores_it():
    cfg = DnaConfig(timeframe=15, min_minutes=240, engine_min_bars=10_000)
    d = dna_mod.analyze(_walk(15 * 120, 5, 20), cfg, live_minutes=15 * 120)
    assert d["ready"] and d["bias"] == 1 and d["regime"] == "trend", d
    assert d["engine"]["ready"] is False
    o = ranking.score("X", d, {"spread_bps": 5, "book_imbalance": 0.2}, FeeConfig(),
                      ExecutionConfig())
    assert o["side"] == 1 and 0 < o["score"] <= 0.75
    assert o["net_edge_bps"] > 0 and o["stop"] < o["price"] < o["target"]
    assert any("warm-up" in n for n in o["notes"])


def test_ranking_is_zero_when_fees_eat_the_move_and_long_only():
    cfg = DnaConfig(timeframe=15, min_minutes=240, engine_min_bars=10_000)
    calm = dna_mod.analyze(_walk(15 * 120, 0.3, 0.5), cfg)
    o = ranking.score("X", calm, {"spread_bps": 2}, FeeConfig(), ExecutionConfig())
    assert o["score"] == 0.0
    assert any("cost" in n or "long" in n for n in o["notes"])
    down = dna_mod.analyze(_walk(15 * 120, -5, 20), cfg)
    assert down["bias"] == -1
    o = ranking.score("X", down, {"spread_bps": 2}, FeeConfig(), ExecutionConfig())
    assert o["score"] == 0.0 and o["side"] == 0
    # cheaper fees turn the calm market back on only if the move clears 3x cost
    cheap = FeeConfig(maker_bps=1.0, taker_bps=2.0)
    assert ranking.score("X", calm, {"spread_bps": 2}, cheap,
                         ExecutionConfig())["net_edge_bps"] > 0


@pytest.mark.slow
def test_dna_runs_tbae_engine_when_history_is_long_enough():
    cfg = DnaConfig(timeframe=15, min_minutes=240, engine_min_bars=260)
    d = dna_mod.analyze(_walk(15 * 300, 0.5, 6), cfg)
    eng = d["engine"]
    assert eng["ready"], eng
    assert eng["bars"] >= 290 and eng["category"]


# --------------------------------------------------------------------------- #
# execution (paper)
# --------------------------------------------------------------------------- #
def _exec_env(price_path):
    clock = Clock(T0 / 1000)
    store = Store()
    cfg = _cfg()

    class Ex:
        name = "x"

        def markets(self):
            return [Market("AAAUSDT", "AAA", "USDT", tick_size=0.0001, step_size=0.001,
                           min_qty=0.001, min_notional=5)]

        def account(self):
            raise ExchangeError("paper")

    md = MarketDataEngine(Ex(), store, cfg, clock=clock)
    md.refresh_markets()
    st = md.state["AAAUSDT"]
    st.book = OrderBook("AAAUSDT", T0, [(100.0, 1e6)], [(100.1, 1e6)])
    eng = ExecutionEngine(Ex(), store, md, ExecutionConfig(min_score=0.5), FeeConfig(30, 40),
                          clock=clock)

    def feed(prices):
        for p in prices:
            clock.t += 10
            st.trades.append(Trade(len(st.trades) + 1, int(clock.t * 1000), p, 1.0, False))
            eng.tick()
    return clock, store, eng, feed


OPP = {"symbol": "AAAUSDT", "side": 1, "score": 0.8, "stop_bps": 200.0,
       "expected_move_bps": 500.0, "id": None}


def test_paper_trade_hits_target_net_of_fees():
    clock, store, eng, feed = _exec_env(None)
    assert eng.consider([OPP, {**OPP, "symbol": "NOPE"}]) != []
    p = store.positions()[0]
    assert p["status"] == "pending" and p["entry_price"] == 100.0
    assert p["stop"] == 98.0 and p["target"] == 105.0
    # risk 0.5% of 1000 = 5 USDT over a 2 USDT stop -> 2.5, capped at 20% equity = 2.0
    assert p["qty"] == 2.0
    feed([100.0, 100.2])                     # a print *at* the limit does not fill
    assert store.positions()[0]["status"] == "pending"
    feed([99.9, 103, 105.2])
    p = store.positions()[0]
    assert p["status"] == "closed" and p["exit_reason"] == "target"
    fees = 100 * 2 * 30 / 1e4 + 105 * 2 * 30 / 1e4
    assert p["pnl_quote"] == pytest.approx(5 * 2 - fees)
    assert p["pnl_r"] == pytest.approx((10 - fees) / 4.0)
    assert eng.consider([OPP]) != []         # slot free again


def test_paper_stop_is_taker_and_ttl_cancels():
    clock, store, eng, feed = _exec_env(None)
    eng.consider([OPP])
    feed([99.5, 97.5])
    p = store.positions()[0]
    assert p["exit_reason"] == "stop" and p["exit_price"] < 98.0
    assert p["pnl_r"] < -1.0                 # fees and spread make a stop worse than -1R
    eng.consider([OPP])
    clock.t += 1000
    eng.tick()
    assert store.positions()[0]["status"] == "cancelled"


def test_live_mode_requires_environment_arming(monkeypatch):
    monkeypatch.delenv("TBAE_LIVE_TRADING", raising=False)
    with pytest.raises(RuntimeError, match="TBAE_LIVE_TRADING"):
        ExecutionEngine(None, Store(), None, ExecutionConfig(mode="live"), FeeConfig())
    with pytest.raises(ValueError):
        LiveConfig.from_dict({"execution": {"mode": "yolo"}})
    with pytest.raises(ValueError, match="unknown"):
        LiveConfig.from_dict({"filterz": {}})


# --------------------------------------------------------------------------- #
# runner + dashboard
# --------------------------------------------------------------------------- #
def test_runner_end_to_end_and_dashboard():
    clock = Clock(T0 / 1000)
    ex = SimExchange(clock, SPECS)
    store = Store()
    r = Runner(_cfg(), exchange=ex, store=store, clock=clock)
    info = {}
    for _ in range(12 * 80):                 # 80 minutes of 5-second ticks
        clock.t += 5
        info = r.step(sweep_budget=4)
    assert r.candidates == ["TRNDUSDT"]
    opps = store.latest_opportunities()
    assert opps and opps[0]["symbol"] == "TRNDUSDT" and "dna" in opps[0]
    assert store.candle_stats("TRNDUSDT")["n"] >= 75
    assert info["funnel"]["total"] == 4

    from fastapi.testclient import TestClient
    from live.dashboard import create_app
    c = TestClient(create_app(store, r))
    assert "داشبورد" in c.get("/").text
    st = c.get("/api/live/status").json()
    assert st["mode"] == "paper" and st["candidates"] == ["TRNDUSDT"]
    assert c.get("/api/live/opportunities").json()[0]["symbol"] == "TRNDUSDT"
    assert len(c.get("/api/live/scan").json()) == 4
    cd = c.get("/api/live/candles/TRNDUSDT?tf=15").json()
    assert cd["candles"] and set(cd["candles"][0]) == {"time", "open", "high", "low", "close", "volume"}
    assert c.get("/api/live/candles/NOPE").status_code == 404
    assert isinstance(c.get("/api/live/events").json(), list)
