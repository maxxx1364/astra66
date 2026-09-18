## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.66s)
OK   vision_archive (0.26s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Data: **525,601** minutes (365.0 of 365 days requested) · 2025-09-18T06:03:00Z .. 2026-09-18T06:03:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 161 | -8.01 | -1.23 | 10.62 | 42.2 | -0.0768 | 0.79 |
| random_entry_control | 174 | -16.45 | -2.76 | 18.05 | 40.2 | -0.1840 | 0.60 |
| every_bar_control | 180 | -17.74 | -2.75 | 18.14 | 37.2 | -0.1872 | 0.63 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +1,987 − friction 10,001 = net -8,014 · E[R] -0.0768 · n=161

Entry funnel: 301 signals → 184 fills → 161 positions (fill rate 0.61)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=161 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 161 | -8.01 | -1.23 | 10.62 | -0.0768 |
| 0.6 | 120 | +1.71 | +0.32 | 5.98 | +0.0352 |
| 0.75 | 48 | +1.65 | +0.49 | 2.48 | +0.0392 |
| 0.8 | 34 | +2.95 | +0.99 | 2.12 | +0.1306 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.82 → out-of-sample +0.82 · overfit gap +0.01
deflated Sharpe: 0.581 (passes 95%: False) · PBO: 0.52 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=161 · E[R] -0.0768 · Sharpe -1.23

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 211 | -0.0540 | +0.0229 | +0.08 | harmful |
| volatility | 175 | -0.0612 | +0.0156 | -0.01 | review |
| volume | 163 | -0.0827 | -0.0059 | -0.11 | keep |
| structure | 161 | -0.0844 | -0.0076 | -0.13 | keep |
| momentum | 155 | -0.0707 | +0.0061 | +0.10 | review |
| extension | 165 | -0.0698 | +0.0070 | +0.04 | decoration |
| timing | 192 | -0.1435 | -0.0667 | -1.29 | keep |
| quality | 163 | -0.0792 | -0.0023 | -0.04 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

