"""TBAE engine — motor-e mohasebesati-ye mostaghel (no web/DOM dependency).

The package is intentionally **pure standard library**: every module below runs
on a stock CPython 3.9+ interpreter with no third-party imports.  Only
``tbae.app`` (FastAPI dashboard) and the test-suite require extra packages.

Layering contract
-----------------
    feeds      -> raw 1-minute bars
    resample   -> 1m -> any timeframe (keeps the intra-bar minute path)
    systembar  -> non-neutralised mobility (S, S_up, S_down, S_intra)
    reference  -> dynamic 100% reference with outlier trimming
    classify   -> decision tree -> category + colour
    volatility -> intra-candle sigma (RV / Garman-Klass / ATR blend)
    indicators -> trend, momentum, volume, structure
    signals    -> raw candidates + confirmation-filter stack + funnel audit
    risk       -> sizing, limits, kill-switch
    exits      -> staged tranches, dynamic TP/SL, reversal-event ladder
    backtest   -> event-driven replay with 1-minute path resolution
    metrics    -> performance statistics + overfitting guards
    pipeline   -> single entry point that wires all of the above
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
