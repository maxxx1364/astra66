"""Wake-up scanner: features are causal, the rule fires on the pattern it
describes, and the daily trade simulation is conservative."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from live.wakeup import (BinanceDaily, TradeRule, WakeupConfig, features, is_coin_pair,
                         klines_frame, scan_today, signals, simulate)

DAY = 86_400_000


def _frame(n=120, seed=1, wake_at=None):
    rng = np.random.default_rng(seed)
    close = 10 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.02, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.02, n))
    qv = rng.uniform(1.5e6, 2.5e6, n)
    tbq = qv * 0.5
    if wake_at is not None:
        # quiet, tight range for 30 days, then a 5x volume day with buyers in control
        for i in range(wake_at - 30, wake_at):
            close[i] = close[wake_at - 31]
            open_[i], high[i], low[i] = close[i], close[i] * 1.004, close[i] * 0.996
        close[wake_at] = close[wake_at - 1] * 1.04
        open_[wake_at] = close[wake_at - 1]
        high[wake_at], low[wake_at] = close[wake_at] * 1.01, open_[wake_at] * 0.99
        qv[wake_at] = 5 * np.median(qv[wake_at - 20:wake_at])
        tbq[wake_at] = qv[wake_at] * 0.7
    ts = 1_700_000_000_000 - (1_700_000_000_000 % DAY) + np.arange(n) * DAY
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close,
                         "volume": qv / close, "quote_volume": qv, "trades": 1000,
                         "taker_buy_base": tbq / close, "taker_buy_quote": tbq})


def test_signal_fires_on_wakeup_pattern_only():
    df = _frame(wake_at=100)
    s = signals(features(df), WakeupConfig())
    assert s["signal"].iat[100]
    assert {"squeeze", "taker_buy", "breakout"} <= {k for k in ("squeeze", "taker_buy", "breakout")
                                                     if s[k].iat[100]}
    assert s["signal"].sum() <= 2
    assert not signals(features(_frame()), WakeupConfig())["signal"].any()


def test_features_are_causal():
    df = _frame(wake_at=100)
    full = features(df)
    cut = features(df.iloc[:101].copy())
    cols = ["rvol", "day_move", "move_5d", "atr_ratio", "taker_buy", "rel_20d"]
    pd.testing.assert_frame_equal(full.loc[:100, cols], cut.loc[:100, cols])


def test_simulate_target_stop_timeout_and_same_bar_rule():
    rule = TradeRule(target=0.10, stop=0.05, max_days=3, fee_per_side=0.0, slippage_per_side=0.0)
    base = dict(ts=[0, 1, 2, 3], volume=1, quote_volume=1, trades=1, taker_buy_base=0,
                taker_buy_quote=0)
    up = pd.DataFrame({**base, "open": [100, 100, 104, 108], "high": [101, 105, 111, 109],
                       "low": [99, 99, 103, 107], "close": [100, 104, 108, 108]})
    assert simulate(up, 0, rule)["exit"] == "target"
    both = up.copy()
    both.loc[1, ["high", "low"]] = [115, 90]
    r = simulate(both, 0, rule)
    assert r["exit"] == "stop" and r["gross"] == pytest.approx(-0.05)
    flat = up.copy()
    flat["high"], flat["low"], flat["close"] = 101, 99, 100.5
    r = simulate(flat, 0, rule)
    assert r["exit"] == "timeout" and r["gross"] == pytest.approx(0.005)
    assert simulate(flat, 2, rule) is None               # trade would still be open
    gap = up.copy()
    gap.loc[1, ["open", "low"]] = [90, 88]               # gaps through the stop
    assert simulate(gap, 0, rule)["gross"] == pytest.approx(-0.10)
    assert TradeRule().cost == pytest.approx(0.009)


def test_pair_filter():
    assert is_coin_pair("SOLUSDT", "SOL", "USDT")
    assert is_coin_pair("JUPUSDT", "JUP", "USDT")
    assert not is_coin_pair("USDCUSDT", "USDC", "USDT")
    assert not is_coin_pair("BTCUPUSDT", "BTCUP", "USDT")
    assert not is_coin_pair("SOLBTC", "SOL", "BTC")


def test_scan_today_with_fake_api(monkeypatch):
    now = 1_700_000_000_000 - (1_700_000_000_000 % DAY) + 121 * DAY
    monkeypatch.setattr("live.wakeup.time.time", lambda: now / 1000)
    frames = {"WAKEUSDT": _frame(121, seed=2, wake_at=120), "BTCUSDT": _frame(121, seed=3),
              "SLEEPUSDT": _frame(121, seed=4)}

    def rows(df):
        return [[int(r.ts), r.open, r.high, r.low, r.close, r.volume, int(r.ts) + DAY - 1,
                 r.quote_volume, 1000, r.taker_buy_base, r.taker_buy_quote, "0"]
                for r in df.itertuples()]

    def opener(url):
        if "exchangeInfo" in url:
            return json.dumps({"symbols": [{"symbol": s, "baseAsset": s[:-4], "quoteAsset": "USDT",
                                            "status": "TRADING"} for s in frames]}).encode()
        if "ticker/24hr" in url:
            return json.dumps([{"symbol": s, "quoteVolume": "5000000"} for s in frames]).encode()
        sym = url.split("symbol=")[1].split("&")[0]
        return json.dumps(rows(frames[sym])).encode()

    data = BinanceDaily(spacing_s=0, opener=opener)
    out = scan_today(data)
    assert [r["symbol"] for r in out] == ["WAKEUSDT"]
    assert out[0]["rvol"] >= 3 and "taker_buy" in out[0]["confirm"]
    assert len(klines_frame(rows(frames["BTCUSDT"]))) == 121
