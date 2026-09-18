## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.45s)
OK   vision_archive (0.37s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Data: **525,601** minutes (365.0 of 365 days requested) · 2025-09-18T00:00:00Z .. 2026-09-18T00:00:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 159 | -8.23 | -1.26 | 10.62 | 41.5 | -0.0827 | 0.79 |
| random_entry_control | 211 | -17.63 | -2.72 | 18.03 | 36.0 | -0.1566 | 0.62 |
| every_bar_control | 181 | -18.49 | -2.87 | 18.49 | 36.5 | -0.1975 | 0.61 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +1,712 − friction 9,941 = net -8,228 · E[R] -0.0827 · n=159

Entry funnel: 301 signals → 183 fills → 159 positions (fill rate 0.61)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=159 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 159 | -8.23 | -1.26 | 10.62 | -0.0827 |
| 0.6 | 121 | -0.42 | -0.04 | 5.97 | +0.0046 |
| 0.75 | 47 | +2.15 | +0.64 | 2.51 | +0.0535 |
| 0.8 | 33 | +3.73 | +1.27 | 1.81 | +0.1742 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.65 → out-of-sample -0.11 · overfit gap +0.76
deflated Sharpe: 0.181 (passes 95%: False) · PBO: 0.14 — low: in-sample selection mostly carries out-of-sample

#### BTCUSDT — filter ablation

baseline: n=159 · E[R] -0.0827 · Sharpe -1.26

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 207 | -0.0601 | +0.0226 | +0.05 | harmful |
| volatility | 174 | -0.0631 | +0.0195 | +0.03 | review |
| volume | 161 | -0.0885 | -0.0059 | -0.11 | keep |
| structure | 159 | -0.0904 | -0.0077 | -0.13 | keep |
| momentum | 152 | -0.0787 | +0.0040 | +0.06 | review |
| extension | 163 | -0.0754 | +0.0073 | +0.04 | decoration |
| timing | 193 | -0.1478 | -0.0651 | -1.31 | keep |
| quality | 161 | -0.0885 | -0.0059 | -0.11 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

