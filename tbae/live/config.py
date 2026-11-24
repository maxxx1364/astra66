"""Configuration for the live system.

Secrets never live here or in any file in the repository: the API key and
secret are read from the environment (``TABDEAL_API_KEY`` / ``TABDEAL_API_SECRET``)
only when an authenticated call is made.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass(slots=True)
class FilterConfig:
    """PRELIMINARY FILTER thresholds — cheap vetoes applied to every symbol."""

    quote_assets: tuple[str, ...] = ("USDT", "IRT")
    #: spread above this (basis points) makes a round trip too expensive.
    max_spread_bps: float = 60.0
    #: minimum resting liquidity within ``depth_band_bps`` of mid, per side,
    #: expressed in quote currency.  Keyed by quote asset.
    min_depth_quote: dict[str, float] = field(
        default_factory=lambda: {"USDT": 2_000.0, "IRT": 200_000_000.0})
    depth_band_bps: float = 100.0
    #: minimum traded notional seen in the observation window (quote currency).
    min_window_notional: dict[str, float] = field(
        default_factory=lambda: {"USDT": 5_000.0, "IRT": 500_000_000.0})
    #: minimum trades seen in the observation window.
    min_trades: int = 20
    #: the symbol must have moved at least ``min_range_fee_multiple`` x the
    #: round-trip fee within the window — otherwise no trade can pay its costs.
    min_range_fee_multiple: float = 2.0
    exclude: tuple[str, ...] = ()


@dataclass(slots=True)
class SelectorConfig:
    """CANDIDATE SELECTOR — how many symbols get the expensive analysis."""

    max_candidates: int = 15
    #: a selected symbol is kept at least this long even if it drops in rank,
    #: so its candle history is not thrown away by one noisy scan.
    min_hold_s: float = 1800.0
    #: a challenger must beat the weakest incumbent by this factor to evict it.
    evict_margin: float = 1.15


@dataclass(slots=True)
class FeeConfig:
    """Fees in basis points per side.  Tabdeal's base level is ~33/35 bp
    (maker/taker); the account endpoint reports the real figures and
    :func:`live.execution.ExecutionEngine.refresh_fees` overwrites these."""

    maker_bps: float = 33.0
    taker_bps: float = 35.0

    def round_trip_bps(self, maker_entry: bool = True, maker_exit: bool = True) -> float:
        return ((self.maker_bps if maker_entry else self.taker_bps)
                + (self.maker_bps if maker_exit else self.taker_bps))


@dataclass(slots=True)
class DnaConfig:
    timeframe: int = 15          # minutes; must be one the tbae engine supports
    min_minutes: int = 240       # below this, DNA features are not computed
    #: minutes needed before the full tbae signal stack is run (reference +
    #: indicator warm-up at the chosen timeframe).
    engine_min_bars: int = 260
    lookback_minutes: int = 60 * 24 * 7


@dataclass(slots=True)
class ExecutionConfig:
    #: ``paper`` simulates fills against the live book; ``live`` sends orders.
    mode: str = "paper"
    risk_per_trade_pct: float = 0.5     # % of equity risked between entry and stop
    max_open_positions: int = 3
    max_position_pct: float = 20.0      # cap on one position's notional, % equity
    min_score: float = 0.60             # opportunity score needed to enter
    stop_atr: float = 1.5               # stop distance in ATR (DNA timeframe)
    target_r: float = 2.5               # take-profit distance in multiples of risk
    #: the expected move to target must exceed this multiple of round-trip cost.
    min_target_fee_multiple: float = 3.0
    entry_offset_bps: float = 0.0       # limit price offset from best bid
    order_ttl_s: float = 300.0          # cancel unfilled entry orders after this
    paper_equity: float = 1_000.0       # quote currency, paper mode only
    paper_quote: str = "USDT"


@dataclass(slots=True)
class LiveConfig:
    exchange: str = "tabdeal"
    db_path: str = "data/live.sqlite3"
    scan_interval_s: float = 60.0
    trades_poll_s: float = 15.0          # per candidate; all-symbol polls are slower
    universe_poll_s: float = 120.0
    request_spacing_s: float = 0.25      # min gap between REST calls (rate limit)
    #: optional CCXT exchange id used to backfill history for symbols that
    #: exist there too (e.g. "binance" for USDT pairs).  Empty = disabled.
    history_exchange: str = ""
    filters: FilterConfig = field(default_factory=FilterConfig)
    selector: SelectorConfig = field(default_factory=SelectorConfig)
    fees: FeeConfig = field(default_factory=FeeConfig)
    dna: DnaConfig = field(default_factory=DnaConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LiveConfig":
        sub = {"filters": FilterConfig, "selector": SelectorConfig, "fees": FeeConfig,
               "dna": DnaConfig, "execution": ExecutionConfig}
        kw: dict[str, Any] = {}
        names = {f.name for f in fields(cls)}
        for k, v in d.items():
            if k not in names:
                raise ValueError(f"unknown config key: {k}")
            if k in sub:
                allowed = {f.name for f in fields(sub[k])}
                bad = set(v) - allowed
                if bad:
                    raise ValueError(f"unknown {k} keys: {sorted(bad)}")
                kw[k] = sub[k](**{kk: (tuple(vv) if isinstance(vv, list) else vv)
                                  for kk, vv in v.items()})
            else:
                kw[k] = v
        cfg = cls(**kw)
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: str | None) -> "LiveConfig":
        if not path:
            return cls()
        # utf-8-sig: Windows PowerShell 5 writes a BOM with "Out-File -Encoding utf8"
        with open(path, encoding="utf-8-sig") as fh:
            return cls.from_dict(json.load(fh))

    def validate(self) -> "LiveConfig":
        if self.execution.mode not in ("paper", "live"):
            raise ValueError("execution.mode must be 'paper' or 'live'")
        if self.selector.max_candidates < 1:
            raise ValueError("selector.max_candidates must be >= 1")
        return self


def credentials(prefix: str = "TABDEAL") -> tuple[str, str]:
    """Read ``<PREFIX>_API_KEY`` / ``<PREFIX>_API_SECRET`` from the environment."""
    return (os.environ.get(f"{prefix}_API_KEY", ""),
            os.environ.get(f"{prefix}_API_SECRET", ""))


def live_trading_armed() -> bool:
    """Real orders need *both* ``execution.mode = "live"`` in the config *and*
    ``TBAE_LIVE_TRADING=yes`` in the environment, so a config file copied from
    somewhere else can never place orders by itself."""
    return os.environ.get("TBAE_LIVE_TRADING", "").strip().lower() == "yes"
