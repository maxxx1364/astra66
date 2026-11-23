"""PRELIMINARY FILTER — cheap vetoes, each with a named reason.

The question every rule answers is the same: *could a trade here possibly
pay for itself after fees?*  A symbol whose spread, depth or range cannot cover
a round trip never reaches the expensive analysis.
"""

from __future__ import annotations

import math
from typing import Any

from .config import FeeConfig, FilterConfig


def evaluate(row: dict[str, Any], f: FilterConfig, fees: FeeConfig) -> list[str]:
    """Return the list of failed rule names (empty = passed)."""
    reasons: list[str] = []
    q = row.get("quote", "")
    if row.get("symbol") in f.exclude:
        reasons.append("excluded")
    if str(row.get("status", "")).upper() != "TRADING":
        reasons.append("not_trading")
    if f.quote_assets and q not in f.quote_assets:
        reasons.append("quote")
    if row.get("error"):
        reasons.append("data_error")
    spread = row.get("spread_bps", math.inf)
    if not math.isfinite(spread) or spread > f.max_spread_bps:
        reasons.append("spread")
    min_depth = f.min_depth_quote.get(q, 0.0)
    if min(row.get("depth_bid", 0.0), row.get("depth_ask", 0.0)) < min_depth:
        reasons.append("depth")
    if row.get("notional", 0.0) < f.min_window_notional.get(q, 0.0):
        reasons.append("volume")
    if row.get("trades", 0) < f.min_trades:
        reasons.append("activity")
    # the window's range must cover the round trip (maker in, taker out) plus spread
    cost = fees.round_trip_bps(maker_entry=True, maker_exit=False) + (
        spread if math.isfinite(spread) else 0.0)
    if row.get("range_bps", 0.0) < f.min_range_fee_multiple * cost:
        reasons.append("range_vs_fees")
    return reasons


def apply(rows: list[dict[str, Any]], f: FilterConfig, fees: FeeConfig) -> list[dict[str, Any]]:
    for r in rows:
        r["reasons"] = evaluate(r, f, fees)
        r["passed"] = not r["reasons"]
    return rows


def funnel(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many symbols each rule rejected (a symbol can fail several)."""
    out: dict[str, int] = {"total": len(rows), "passed": sum(1 for r in rows if r.get("passed"))}
    for r in rows:
        for k in r.get("reasons", []):
            out[k] = out.get(k, 0) + 1
    return out
