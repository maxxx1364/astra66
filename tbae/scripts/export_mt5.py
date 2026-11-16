#!/usr/bin/env python3
"""Export the engine's strategy configuration as a MetaTrader 5 ``.set`` file.

Run::

    python3 scripts/export_mt5.py                         # engine defaults
    python3 scripts/export_mt5.py --preset edge           # the study's best pick
    python3 scripts/export_mt5.py --stop-sigma 4.4 --min-score 0.8 \
            --out mt5/TBAE_EdgeEA_custom.set

Why this script exists
----------------------
``mt5/TBAE_EdgeEA.mq5`` is a port of the strategy core, and a port drifts the
moment its parameters are retyped by hand.  This script reads the SAME dataclass
defaults the Python backtest runs on (``SignalConfig``, ``ExitConfig``,
``RiskConfig``) and writes them in the Strategy Tester's ``.set`` format, so the
two implementations are parameterised from one source of truth.

The ``edge`` preset encodes the cost-attribution study's best configuration
(RESEARCH.md §3): ``min_edge_score 0.80``, sigma stop ``4.4σ``, maker targets —
the configuration that reaches net ``+0.019R`` at a 2 bp taker tier.

What the file cannot carry
--------------------------
MT5 models costs itself (spread in the price feed, commission per lot in the
tester settings).  The engine's ``commission_bps``/``slippage_bps`` therefore
do NOT appear as EA inputs — set the tester's commission to match the venue
you are studying, or the backtest answers a different question than the
Python one.  The export prints the engine's cost assumptions as comments at
the top of the file so they end up in front of the person clicking "Start".
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.exits import ExitConfig                              # noqa: E402
from engine.risk import CostConfig, RiskConfig                   # noqa: E402
from engine.signals import SignalConfig                          # noqa: E402

#: the cost-attribution study's best configuration (RESEARCH.md §3-4)
EDGE_PRESET = {"min_edge_score": 0.80, "stop_mode": "sigma", "stop_sigma_mult": 4.40}


def build_inputs(scfg: SignalConfig, xcfg: ExitConfig, rcfg: RiskConfig) -> dict[str, object]:
    """Map engine dataclass fields onto the EA's ``input`` names.

    Every key here must exist in ``TBAE_EdgeEA.mq5``; the mapping is the
    contract between the two implementations and is documented field-by-field
    in ``mt5/README.md``.
    """
    tr = list(xcfg.tranches)
    fixed = [t for t in tr if t[0] > 0.0]
    tp1 = fixed[0] if fixed else (1.0, 0.0)
    tp2 = fixed[1] if len(fixed) > 1 else (2.0, 0.0)
    return {
        # signal / candidate gate
        "InpMinEdgeScore": scfg.min_edge_score,
        "InpCooldownBars": scfg.cooldown_bars,
        "InpMaxSignalsPerDay": scfg.max_signals_per_day,
        # trend
        "InpFTrend": scfg.f_trend,
        "InpMinADX": scfg.min_adx,
        "InpAllowCounterTrend": scfg.allow_counter_trend,
        # volatility
        "InpFVolatility": scfg.f_volatility,
        "InpAtrRankMin": scfg.atr_rank_min,
        "InpAtrRankMax": scfg.atr_rank_max,
        "InpVolRegimeMin": scfg.vol_regime_min,
        "InpVolRegimeMax": scfg.vol_regime_max,
        # volume
        "InpFVolume": scfg.f_volume,
        "InpMinVolZ": scfg.min_vol_z,
        "InpGoodVolZ": scfg.good_vol_z,
        # momentum
        "InpFMomentum": scfg.f_momentum,
        "InpMinEfficiency": scfg.min_efficiency_trend,
        "InpGoodEfficiency": scfg.good_efficiency_trend,
        "InpRsiLongMax": scfg.rsi_long_max,
        "InpRsiShortMin": scfg.rsi_short_min,
        # extension
        "InpFExtension": scfg.f_extension,
        "InpMaxExtensionSigma": scfg.max_extension_sigma,
        "InpExtensionSoftSigma": scfg.extension_soft_sigma,
        # structure / timing
        "InpFStructure": scfg.f_structure,
        "InpFTiming": scfg.f_timing,
        # weights
        "InpWCategory": scfg.w_category,
        "InpWEfficiency": scfg.w_efficiency,
        "InpWTrend": scfg.w_trend,
        "InpWVolume": scfg.w_volume,
        "InpWFlow": scfg.w_flow,
        "InpWTiming": scfg.w_timing,
        "InpWVolatility": scfg.w_volatility,
        "InpWStructure": scfg.w_structure,
        # entry
        "InpPullbackEntry": scfg.entry_timing == "pullback_limit",
        "InpPullbackSigma": scfg.pullback_retrace_sigma,
        "InpPullbackTTLBars": scfg.pullback_ttl_bars,
        # stop geometry
        "InpStopSigmaMult": xcfg.stop_sigma_mult,
        "InpMinStopPct": xcfg.min_stop_pct,
        "InpMaxStopPct": xcfg.max_stop_pct,
        # staged exits
        "InpTp1R": tp1[0], "InpTp1Share": tp1[1],
        "InpTp2R": tp2[0], "InpTp2Share": tp2[1],
        "InpBeAfterR": xcfg.move_stop_to_be_after_r,
        "InpBeBufferSigma": xcfg.be_buffer_sigma,
        # trailing
        "InpTrailEnabled": xcfg.trail_mode != "none",
        "InpChandelierPeriod": xcfg.chandelier_period,
        "InpChandelierMult": xcfg.chandelier_mult,
        "InpTrailStartR": xcfg.trail_start_r,
        # time / giveback exits
        "InpMaxBarsHeld": xcfg.max_bars_held,
        "InpTimeStopBars": xcfg.time_stop_bars,
        "InpTimeStopMinR": xcfg.time_stop_min_r,
        "InpGivebackPeakR": xcfg.giveback_peak_r,
        "InpGivebackGiveR": xcfg.ratchet_give_back_r,
        # risk
        "InpRiskPerTradePct": rcfg.risk_per_trade_pct,
        "InpMaxOpenPositions": rcfg.max_open_positions,
        "InpMaxTradesPerDay": rcfg.max_trades_per_day,
        "InpAllowShort": rcfg.allow_short,
    }


def fmt(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset", choices=("default", "edge"), default="default",
                    help="'edge' = the cost study's best configuration "
                         "(thr 0.8, sigma stop 4.4)")
    ap.add_argument("--min-score", type=float, help="override min_edge_score")
    ap.add_argument("--stop-sigma", type=float, help="override stop_sigma_mult")
    ap.add_argument("--risk-pct", type=float, help="override risk_per_trade_pct")
    ap.add_argument("--commission-bps", type=float, default=2.0,
                    help="engine fee assumption echoed into the file header")
    ap.add_argument("--out", default="",
                    help="output path (default mt5/TBAE_EdgeEA_<preset>.set)")
    a = ap.parse_args()

    scfg, xcfg, rcfg = SignalConfig(), ExitConfig(), RiskConfig()
    if a.preset == "edge":
        scfg.min_edge_score = EDGE_PRESET["min_edge_score"]
        xcfg.stop_mode = EDGE_PRESET["stop_mode"]
        xcfg.stop_sigma_mult = EDGE_PRESET["stop_sigma_mult"]
    if a.min_score is not None:
        scfg.min_edge_score = a.min_score
    if a.stop_sigma is not None:
        xcfg.stop_sigma_mult = a.stop_sigma
    if a.risk_pct is not None:
        rcfg.risk_per_trade_pct = a.risk_pct
    scfg.validate(); xcfg.validate(); rcfg.validate()
    costs = CostConfig(commission_bps=a.commission_bps)

    inputs = build_inputs(scfg, xcfg, rcfg)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = a.out or os.path.join(root, "mt5", f"TBAE_EdgeEA_{a.preset}.set")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    lines = [
        "; TBAE_EdgeEA parameter set — generated by scripts/export_mt5.py",
        f"; preset={a.preset}  min_edge_score={scfg.min_edge_score:g}  "
        f"stop={xcfg.stop_mode}/{xcfg.stop_sigma_mult:g}sigma",
        "; The engine's cost assumptions are NOT EA inputs — reproduce them in",
        "; the Strategy Tester's settings or the backtests answer different",
        "; questions:",
        f";   taker commission {costs.commission_bps:g} bp/side, "
        f"maker {costs.maker_bps:g} bp/side,",
        f";   slippage {costs.slippage_bps:g} bp, sqrt impact "
        f"(coeff {costs.impact_coeff:g}).",
        ";",
    ]
    lines += [f"{k}={fmt(v)}" for k, v in inputs.items()]
    with open(out, "w", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {out} ({len(inputs)} inputs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
