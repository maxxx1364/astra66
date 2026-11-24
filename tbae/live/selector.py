"""CANDIDATE SELECTOR — which passed symbols get candles + DNA analysis.

The preliminary score is deliberately simple (liquidity x movement, scaled by
cost): its job is ordering, not prediction.  Hysteresis keeps a candidate for
``min_hold_s`` and makes challengers beat incumbents by ``evict_margin`` so
the list does not churn on every scan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import FeeConfig, SelectorConfig


def preliminary_score(row: dict[str, Any], fees: FeeConfig) -> float:
    cost = fees.round_trip_bps(True, False) + row.get("spread_bps", 0.0)
    if cost <= 0 or not math.isfinite(cost):
        return 0.0
    move = row.get("range_bps", 0.0) / cost                    # range in units of cost
    liq = math.log10(1.0 + row.get("notional_per_min", 0.0))   # diminishing returns
    flow = 1.0 + abs(row.get("buy_share", 0.5) - 0.5)          # one-sided flow, mild bonus
    return float(move * liq * flow)


@dataclass
class CandidateSelector:
    cfg: SelectorConfig
    fees: FeeConfig
    since: dict[str, float] = field(default_factory=dict)      # symbol -> selected at

    def select(self, rows: list[dict[str, Any]], now_s: float) -> list[str]:
        passed = {r["symbol"]: r for r in rows if r.get("passed")}
        for r in rows:
            r["pre_score"] = preliminary_score(r, self.fees) if r.get("passed") else 0.0
        ranked = sorted(passed, key=lambda s: -passed[s]["pre_score"])

        # incumbents that still pass stay while they are protected or competitive
        keep = [s for s in self.since if s in passed]
        protected = {s for s in keep if now_s - self.since[s] < self.cfg.min_hold_s}
        chosen = list(keep)
        for s in ranked:
            if s in chosen:
                continue
            if len(chosen) < self.cfg.max_candidates:
                chosen.append(s)
                continue
            evictable = [c for c in chosen if c not in protected]
            if not evictable:
                break
            weakest = min(evictable, key=lambda c: passed[c]["pre_score"])
            if passed[s]["pre_score"] > passed[weakest]["pre_score"] * self.cfg.evict_margin:
                chosen.remove(weakest)
                chosen.append(s)
        chosen = sorted(chosen, key=lambda s: -passed[s]["pre_score"])[: self.cfg.max_candidates]
        self.since = {s: self.since.get(s, now_s) for s in chosen}
        for r in rows:
            r["candidate"] = r["symbol"] in self.since
        return chosen
