## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.65s)
OK   vision_archive (0.60s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Data: **129,601** minutes (90.0 of 90 days requested) · 2026-06-20T00:10:00Z .. 2026-09-18T00:10:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 125 | -12.28 | -7.63 | 13.77 | 32.8 | -0.3622 | 0.40 |
| random_entry_control | 193 | -17.87 | -11.67 | 18.09 | 29.0 | -0.5434 | 0.35 |
| every_bar_control | 200 | -17.97 | -9.27 | 18.21 | 36.0 | -0.3262 | 0.46 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -2,791 − friction 9,492 = net -12,283 · E[R] -0.3622 · n=125

Entry funnel: 236 signals → 141 fills → 125 positions (fill rate 0.60)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=125 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 125 | -12.28 | -7.63 | 13.77 | -0.3622 |
| 0.6 | 98 | -10.50 | -7.32 | 11.87 | -0.3745 |
| 0.75 | 56 | -1.48 | -1.19 | 3.91 | -0.0878 |
| 0.8 | 45 | -0.64 | -0.52 | 3.13 | -0.0399 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.57 → out-of-sample -3.37 · overfit gap +4.95
deflated Sharpe: 0.002 (passes 95%: False) · PBO: 0.00 — low: in-sample selection mostly carries out-of-sample

#### BTCUSDT — filter ablation

baseline: n=125 · E[R] -0.3622 · Sharpe -7.63

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 164 | -0.4166 | -0.0544 | -3.08 | keep |
| volatility | 149 | -0.3428 | +0.0194 | -0.03 | review |
| volume | 127 | -0.3551 | +0.0070 | +0.05 | review |
| structure | 127 | -0.3551 | +0.0070 | +0.05 | review |
| momentum | 122 | -0.3676 | -0.0054 | -0.42 | keep |
| extension | 138 | -0.3374 | +0.0248 | -0.14 | keep |
| timing | 152 | -0.3774 | -0.0152 | -1.29 | keep |
| quality | 127 | -0.3551 | +0.0070 | +0.05 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

