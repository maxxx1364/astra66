## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.72s)
OK   vision_archive (0.19s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Data: **129,601** minutes (90.0 of 90 days requested) · 2026-06-20T05:53:00Z .. 2026-09-18T05:53:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 124 | -12.57 | -7.82 | 14.28 | 32.3 | -0.3739 | 0.39 |
| random_entry_control | 136 | -18.09 | -14.24 | 18.09 | 25.0 | -0.6837 | 0.19 |
| every_bar_control | 211 | -18.06 | -9.10 | 18.31 | 37.4 | -0.3115 | 0.48 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -3,161 − friction 9,421 = net -12,581 · E[R] -0.3739 · n=124

Entry funnel: 234 signals → 138 fills → 124 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=124 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 124 | -12.57 | -7.82 | 14.28 | -0.3739 |
| 0.6 | 93 | -9.71 | -6.90 | 11.26 | -0.3600 |
| 0.75 | 54 | -1.45 | -1.21 | 3.95 | -0.0940 |
| 0.8 | 44 | -0.20 | -0.15 | 2.75 | -0.0127 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +2.37 → out-of-sample -3.96 · overfit gap +6.32
deflated Sharpe: 0.001 (passes 95%: False) · PBO: 0.00 — low: in-sample selection mostly carries out-of-sample

#### BTCUSDT — filter ablation

baseline: n=124 · E[R] -0.3739 · Sharpe -7.82

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 175 | -0.4063 | -0.0324 | -2.64 | keep |
| volatility | 149 | -0.3450 | +0.0289 | +0.14 | harmful |
| volume | 125 | -0.3719 | +0.0020 | -0.08 | keep |
| structure | 125 | -0.3719 | +0.0020 | -0.08 | keep |
| momentum | 118 | -0.3793 | -0.0054 | -0.26 | keep |
| extension | 136 | -0.3308 | +0.0431 | +0.27 | harmful |
| timing | 151 | -0.3650 | +0.0089 | -0.77 | keep |
| quality | 125 | -0.3719 | +0.0020 | -0.08 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

