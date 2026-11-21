"""Order blocks and trendline third touches: rules and causality."""

from __future__ import annotations

import random
from types import SimpleNamespace as B

import pytest

from engine import structure_setups as ss


def _flat(n: int, px: float = 100.0) -> list:
    return [B(open=px, high=px + 0.5, low=px - 0.5, close=px) for _ in range(n)]


class TestSwings:
    def test_a_swing_needs_k_bars_on_each_side(self):
        bars = _flat(30)
        bars[10] = B(open=100, high=105, low=99.5, close=100)
        highs, lows = ss.swing_points([b.high for b in bars], [b.low for b in bars], 3)
        assert highs == [10] and lows == []
        highs, _ = ss.swing_points([b.high for b in bars[:13]], [b.low for b in bars[:13]], 3)
        assert highs == [], "a swing three bars from the end is not confirmed yet"


class TestOrderBlocks:
    def _series(self) -> list:
        bars = _flat(30)
        bars[10] = B(open=100, high=105, low=99.5, close=100)        # swing high, known at bar 13
        bars[20] = B(open=101, high=101.5, low=98.5, close=99)        # last down candle
        bars[21] = B(open=99, high=108.5, low=98.8, close=108)        # impulsive break of 105
        for t in range(22, 30):
            bars[t] = B(open=108, high=108.5, low=107.5, close=108)
        return bars

    def test_bullish_block_is_the_last_down_candle_before_the_break(self):
        out = ss.order_blocks(self._series())
        assert len(out) == 1
        s = out[0]
        assert (s.kind, s.side, s.signal_index, s.entry) == ("order_block", 1, 21, "limit")
        assert s.meta["ob_index"] == 20
        assert s.entry_price == pytest.approx(101.5)              # proximal edge
        assert s.stop < 98.5 and s.cancel_level == pytest.approx(98.5)

    def test_no_block_without_displacement(self):
        bars = self._series()
        bars[21] = B(open=99, high=105.6, low=98.8, close=105.5)    # breaks 105 but weakly
        cfg = ss.SetupConfig(disp_atr=10.0)
        assert ss.order_blocks(bars, cfg) == []

    def test_bearish_block_mirrors(self):
        bars = [B(open=200 - b.open, high=200 - b.low, low=200 - b.high, close=200 - b.close)
                for b in self._series()]
        out = ss.order_blocks(bars)
        assert len(out) == 1 and out[0].side == -1
        assert out[0].entry_price == pytest.approx(200 - 101.5)
        assert out[0].stop > 200 - 98.5


def _line_series(break_at: int | None = None) -> list:
    y = lambda t: 100 + 0.2 * (t - 10)                            # noqa: E731
    pivots = (10, 20, 35)
    bars = []
    for t in range(46):
        d = min(3.0, min(abs(t - p) for p in pivots))
        mid = y(t) + d
        if d == 0:
            bars.append(B(open=y(t) + 0.5, high=y(t) + 1.0, low=y(t), close=y(t) + 0.5))
        else:
            bars.append(B(open=mid, high=mid + 0.5, low=mid - 0.5, close=mid))
    if break_at is not None:
        bars[break_at] = B(open=y(break_at), high=y(break_at) + 0.2, low=y(break_at) - 0.9,
                           close=y(break_at) - 0.3)
    return bars


class TestTrendlineThirdTouch:
    def test_third_touch_of_a_rising_line_is_a_long(self):
        out = ss.trendline_third_touches(_line_series())
        hits = [s for s in out if s.meta["a"] == 10 and s.meta["b"] == 20]
        assert len(hits) == 1
        s = hits[0]
        assert (s.kind, s.side, s.signal_index, s.entry) == ("trendline3", 1, 35, "market")
        assert s.stop < s.meta["line"]

    def test_a_close_below_the_line_kills_it(self):
        out = ss.trendline_third_touches(_line_series(break_at=28))
        assert not [s for s in out if s.meta["a"] == 10 and s.meta["b"] == 20]

    def test_no_touch_before_the_second_swing_is_confirmed(self):
        out = ss.trendline_third_touches(_line_series())
        assert all(s.signal_index > s.meta["b"] + ss.SetupConfig().swing_k for s in out)


def _walk(n: int, seed: int) -> list:
    rng = random.Random(seed)
    px, out = 100.0, []
    for _ in range(n):
        o = px
        c = o * (1 + rng.gauss(0, 0.01))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        out.append(B(open=o, high=h, low=lo, close=c))
        px = c
    return out


@pytest.mark.parametrize("fn", [ss.order_blocks, ss.trendline_third_touches])
def test_setups_are_causal(fn):
    bars = _walk(1500, seed=4)
    full = fn(bars)
    assert full, "the random walk should produce some setups"
    for cut in (600, 1000, 1400):
        part = fn(bars[:cut])
        key = lambda s: (s.kind, s.side, s.signal_index, round(s.stop, 9),          # noqa: E731
                         None if s.entry_price is None else round(s.entry_price, 9))
        assert [key(s) for s in part if s.signal_index < cut - 1] == \
               [key(s) for s in full if s.signal_index < cut - 1], \
            f"{fn.__name__}: data after bar {cut} changed an earlier setup"


def test_config_validation():
    with pytest.raises(ValueError):
        ss.SetupConfig(min_risk_atr=5, max_risk_atr=4).validate()
