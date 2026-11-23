"""TBAE live spot system: from an exchange API to entry/exit decisions.

Layers, top to bottom (each module owns exactly one)::

    EXCHANGE API          live.exchange      (Tabdeal native, CCXT for others)
    MARKET DATA ENGINE    live.market_data   (trades + order books, all symbols)
    ALL SYMBOLS SCANNER   live.scanner       (one snapshot row per symbol)
    PRELIMINARY FILTER    live.filters       (cheap vetoes: status, liquidity, spread)
    CANDIDATE SELECTOR    live.selector      (top-N with hysteresis)
    LIVE CANDLE ENGINE    live.candles       (trades -> 1-minute candles, SQLite)
    MARKET DNA ANALYZER   live.dna           (pandas/numpy features + tbae engine)
    OPPORTUNITY RANKING   live.ranking       (fee-aware score, persisted)
    SPOT DASHBOARD        live.dashboard     (FastAPI + one HTML page)
    ENTRY / EXIT ENGINE   live.execution     (paper by default; live is opt-in)

``live.runner`` wires them together.  Unlike ``engine/`` (pure standard library
by contract), this package uses pandas and NumPy for the analysis layer.
"""

__version__ = "0.1.0"
