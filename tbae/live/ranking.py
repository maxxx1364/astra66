"""OPPORTUNITY RANKING — fee-aware score for each analysed candidate.

The score is in [0, 1] and is **zero** whenever the expected move cannot pay
the round trip.  That gate comes first because, at Tabdeal's base fee level
(~0.33 % maker / 0.35 % taker per side), cost dominates everything else on
short timeframes — the research log already shows friction at 2.2x the gross
edge on cheaper venues.

Expected move = ``target_r`` x stop distance, with the stop at ``stop_atr`` x
ATR on the DNA timeframe; that is exactly the trade the execution engine would
place, so the ranking and the orders cannot disagree about what is being bought.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import ExecutionConfig, FeeConfig


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def score(symbol: str, dna: dict[str, Any], scan_row: dict[str, Any],
          fees: FeeConfig, ex: ExecutionConfig) -> dict[str, Any]:
    out: dict[str, Any] = {"symbol": symbol, "score": 0.0, "side": 0, "regime": dna.get("regime"),
                           "notes": []}
    if not dna.get("ready"):
        out["notes"].append(dna.get("reason", "dna not ready"))
        return out
    f = dna["features"]
    spread = float(scan_row.get("spread_bps", 0.0) or 0.0)
    stop_bps = ex.stop_atr * f["atr_pct"] * 100.0
    move_bps = ex.target_r * stop_bps
    cost_bps = fees.round_trip_bps(maker_entry=True, maker_exit=True) + spread / 2
    stop_cost_bps = fees.round_trip_bps(maker_entry=True, maker_exit=False) + spread
    out.update(price=f["close"], stop_bps=stop_bps, expected_move_bps=move_bps,
               cost_bps=cost_bps, net_edge_bps=move_bps - cost_bps,
               # cost expressed in R: what a win must first pay back
               cost_r=stop_cost_bps / stop_bps if stop_bps > 0 else float("inf"))

    eng = dna.get("engine", {})
    sig = eng.get("signal") if eng.get("ready") else None
    long_bias = dna.get("bias", 0) > 0 or (sig and sig["side"] > 0)
    if not long_bias:
        out["notes"].append("no long bias (spot is long-only)")
        return out
    if move_bps < ex.min_target_fee_multiple * cost_bps:
        out["notes"].append(f"target {move_bps:.0f}bp < {ex.min_target_fee_multiple}x cost "
                            f"{cost_bps:.0f}bp")
        return out

    # component scores, each in [0, 1]
    trend = _clip01(0.5 * f["efficiency"] / 0.5 + 0.5 * max(f["r2"], 0.0)) \
        if f["slope_bps_per_bar"] > 0 else 0.0
    persistence = _clip01((f["variance_ratio"] - 0.8) / 0.6)
    momentum = _clip01(1.0 - abs(f["rsi"] - 60.0) / 30.0)     # strong but not stretched
    flow = _clip01((f["taker_buy_share"] - 0.4) / 0.3)
    book = _clip01((scan_row.get("book_imbalance", 0.0) + 0.5))
    vol_ok = _clip01(1.0 - abs(np.log(max(f["vol_regime"], 1e-6))) / np.log(3.0))
    fee_room = _clip01((move_bps / cost_bps - ex.min_target_fee_multiple) / 6.0)
    engine_c = _clip01(sig["score"]) if sig and sig["side"] > 0 else 0.0

    w = {"trend": 0.22, "persistence": 0.10, "momentum": 0.10, "flow": 0.12, "book": 0.06,
         "volatility": 0.10, "fee_room": 0.15, "engine": 0.15}
    comps = {"trend": trend, "persistence": persistence, "momentum": momentum, "flow": flow,
             "book": book, "volatility": vol_ok, "fee_room": fee_room, "engine": engine_c}
    if not eng.get("ready"):
        # without the engine the remaining weights are renormalised, but the
        # score is capped so an engine-confirmed setup always ranks above it.
        w.pop("engine")
        comps.pop("engine")
    total = sum(w.values())
    s = sum(w[k] * comps[k] for k in w) / total
    if not eng.get("ready"):
        s = min(s, 0.75)
        out["notes"].append("engine warm-up: score capped at 0.75")
    if dna["regime"] in ("chaotic", "dead"):
        s *= 0.5
        out["notes"].append(f"regime {dna['regime']}: score halved")
    if dna.get("live_share", 1.0) < 0.5:
        out["notes"].append("mostly backfilled history (not this venue's prices)")
    out.update(score=round(float(s), 4), side=1, components=comps,
               engine_signal=sig, stop=f["close"] * (1 - stop_bps / 1e4),
               target=f["close"] * (1 + move_bps / 1e4))
    return out


def rank(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(scored, key=lambda o: (-o["score"], -o.get("net_edge_bps", 0.0)))
    for i, o in enumerate(ordered, 1):
        o["rank"] = i
    return ordered
