"""Flow-state: weighted delta, trimmed percentage reference, block states."""

from __future__ import annotations

import dataclasses
import random

import pytest

from engine import flow_state as fs
from engine.models import MinuteBar


def _m(ts_min: int, o: float, c: float, vol: float, buy: float) -> MinuteBar:
    hi, lo = max(o, c) + 0.1, min(o, c) - 0.1
    return MinuteBar(ts=ts_min * 60_000, open=o, high=hi, low=lo, close=c,
                     volume=vol, taker_buy_volume=buy)


def _blk(volume: float, delta: float, move: float, *, vol_pct: float, delta_pct: float,
         move_pct: float, mean_volume: float = 100.0, consistency: int = 4) -> fs.FlowBlock:
    b = fs.FlowBlock(ts=0, open=100.0, high=110.0, low=90.0, close=100.0 + move,
                     volume=volume, delta=delta, n_bars=4)
    b.vol_pct, b.delta_pct, b.move_pct = vol_pct, delta_pct, move_pct
    b.mean_volume, b.consistency = mean_volume, consistency
    return b


class TestWeightedDelta:
    def test_delta_is_size_weighted_buy_minus_sell(self):
        bars = fs.flow_bars([_m(0, 1, 2, vol=10, buy=7)], tf=1)
        assert bars[0].delta == pytest.approx(4.0)   # 7 bought - 3 sold

    def test_one_large_print_outweighs_many_small_ones(self):
        # nine small buy-side minutes vs one large sell-side minute
        mins = [_m(i, 1, 1, vol=1, buy=1) for i in range(9)] + [_m(9, 1, 1, vol=50, buy=0)]
        bar = fs.flow_bars(mins, tf=10)[0]
        assert bar.delta == pytest.approx(9 - 50)
        assert bar.delta < 0, "a tick count would say buyers won 9:1; size says sellers did"


class TestAggregation:
    def test_bars_and_blocks_align_to_clock_boundaries(self):
        mins = [_m(i, 1, 1, vol=1, buy=0.5) for i in range(5, 5 + 60 * 9)]
        bars = fs.flow_bars(mins, tf=60)
        assert [b.ts % 3_600_000 for b in bars] == [0] * len(bars)
        blocks = fs.flow_blocks(bars, tf=60, block=4)
        assert all(b.ts % (4 * 3_600_000) == 0 for b in blocks)
        assert sum(b.n_bars for b in blocks) == len(bars)

    def test_block_totals_equal_the_sum_of_their_bars(self):
        rng = random.Random(3)
        mins = [_m(i, 1, 1, vol=rng.uniform(1, 5), buy=0) for i in range(240)]
        for m in mins:
            m.taker_buy_volume = m.volume * rng.random()
        bars = fs.flow_bars(mins, tf=15)
        blk = fs.flow_blocks(bars, tf=15, block=4)[0]
        assert blk.volume == pytest.approx(sum(b.volume for b in bars[:4]))
        assert blk.delta == pytest.approx(sum(b.delta for b in bars[:4]))


class TestClassification:
    cfg = fs.FlowConfig()

    def test_max_wins_over_everything(self):
        b = _blk(500, 400, 5, vol_pct=150, delta_pct=90, move_pct=90)
        assert fs.classify_block(b, self.cfg) == "max"

    def test_explosive_is_thin_volume_with_a_big_move(self):
        b = _blk(50, 30, 8, vol_pct=30, delta_pct=60, move_pct=80, mean_volume=100)
        assert fs.classify_block(b, self.cfg) == "explosive"

    def test_pressure_is_heavy_volume_with_balanced_delta(self):
        b = _blk(300, 2, 0.5, vol_pct=70, delta_pct=5, move_pct=10)
        assert fs.classify_block(b, self.cfg) == "pressure"

    def test_strong_and_trend_need_price_to_agree_with_delta(self):
        assert fs.classify_block(_blk(150, 80, 6, vol_pct=40, delta_pct=70, move_pct=40), self.cfg) == "strong"
        assert fs.classify_block(_blk(150, 80, -6, vol_pct=40, delta_pct=70, move_pct=40), self.cfg) == "medium"
        assert fs.classify_block(_blk(150, 30, 3, vol_pct=40, delta_pct=30, move_pct=30), self.cfg) == "trend"

    def test_trend_needs_consistent_bars(self):
        b = _blk(150, 30, 3, vol_pct=40, delta_pct=30, move_pct=30, consistency=2)
        assert fs.classify_block(b, self.cfg) == "medium"

    def test_quiet_two_sided_flow_is_weak(self):
        assert fs.classify_block(_blk(80, 3, 1, vol_pct=20, delta_pct=8, move_pct=10), self.cfg) == "weak"

    def test_every_ready_block_gets_exactly_one_known_state(self):
        rng = random.Random(1)
        for _ in range(2000):
            b = _blk(rng.uniform(1, 300), rng.uniform(-100, 100), rng.uniform(-10, 10),
                     vol_pct=rng.uniform(0, 160), delta_pct=rng.uniform(-150, 150),
                     move_pct=rng.uniform(0, 160), mean_volume=rng.uniform(1, 300),
                     consistency=rng.randint(0, 4))
            assert fs.classify_block(b, self.cfg) in fs.STATES


def _series(n_blocks: int, seed: int = 0) -> list[MinuteBar]:
    rng = random.Random(seed)
    mins, px = [], 100.0
    for i in range(n_blocks * 4 * 60):
        nxt = px * (1 + rng.gauss(0, 0.001))
        vol = rng.lognormvariate(0, 0.6)
        mins.append(_m(i, px, nxt, vol=vol, buy=vol * rng.random()))
        px = nxt
    return mins


class TestAnnotate:
    def test_early_blocks_are_unready_then_every_block_is_scored(self):
        cfg = fs.FlowConfig(min_reference_blocks=20, reference_window_days=10)
        bars = fs.flow_bars(_series(80), tf=60)
        blocks = fs.annotate(fs.flow_blocks(bars, 60, 4), 60, cfg)
        assert all(b.state == "unready" for b in blocks[:20])
        assert all(b.state in fs.STATES for b in blocks[21:])

    def test_states_are_causal(self):
        cfg = fs.FlowConfig(min_reference_blocks=20, reference_window_days=10)
        mins = _series(90, seed=5)
        full = fs.annotate(fs.flow_blocks(fs.flow_bars(mins, 60), 60, 4), 60, cfg)
        cut = fs.annotate(fs.flow_blocks(fs.flow_bars(mins[: 60 * 4 * 60], 60), 60, 4), 60, cfg)
        assert [b.state for b in cut] == [b.state for b in full[: len(cut)]], \
            "adding later data changed an earlier state: the reference looked ahead"

    def test_a_liquidation_spike_does_not_rescale_normal_blocks(self):
        # default 30-day window = 180 blocks, so the 2% trim drops the top 3
        cfg = fs.FlowConfig()
        mins = _series(240, seed=9)
        base = fs.annotate(fs.flow_blocks(fs.flow_bars(mins, 60), 60, 4), 60, cfg)
        spiked = [dataclasses.replace(m) for m in mins]
        k = 150 * 4 * 60 + 10                        # one minute inside block 150
        spiked[k].volume *= 400
        spiked[k].taker_buy_volume = spiked[k].volume
        out = fs.annotate(fs.flow_blocks(fs.flow_bars(spiked, 60), 60, 4), 60, cfg)
        assert out[150].state == "max"
        for i in (170, 200, 230):
            assert out[i].vol_pct == pytest.approx(base[i].vol_pct, rel=0.05), \
                "trimming the top values must keep one spike from redefining 100%"

    def test_bar_line_carries_the_state_of_its_block(self):
        cfg = fs.FlowConfig(min_reference_blocks=20, reference_window_days=10)
        bars = fs.flow_bars(_series(40), tf=60)
        blocks = fs.annotate(fs.flow_blocks(bars, 60, 4), 60, cfg)
        line = fs.bar_line(bars, blocks, 60, cfg)
        assert len(line) == len(bars)
        by_ts = {b.ts: b.state for b in blocks}
        for pt in line:
            assert pt["state"] == by_ts[(pt["ts"] // (4 * 3_600_000)) * (4 * 3_600_000)]


def test_config_validation():
    with pytest.raises(ValueError):
        fs.FlowConfig(weak=60, big=55).validate()
    with pytest.raises(ValueError):
        fs.FlowConfig(trend_consistency=5, block=4).validate()
