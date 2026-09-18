## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.69s)
OK   vision_archive (0.37s)
```

> ### ✅ Real-data study completed

### BNBUSDT

Data: **525,601** minutes (365.0 of 365 days requested) · 2025-09-18T00:00:00Z .. 2026-09-18T00:00:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 70 | +2.13 | +0.46 | 4.84 | 45.7 | +0.0568 | 1.14 |
| random_entry_control | 125 | -12.80 | -2.42 | 14.52 | 38.4 | -0.1979 | 0.59 |
| every_bar_control | 141 | -16.94 | -2.91 | 18.14 | 37.6 | -0.2416 | 0.55 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +5,937 − friction 3,809 = net +2,128 · E[R] +0.0568 · n=70

Entry funnel: 137 signals → 79 fills → 70 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=70 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BNBUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 70 | +2.13 | +0.46 | 4.84 | +0.0568 |
| 0.6 | 47 | +4.37 | +1.18 | 3.17 | +0.1746 |
| 0.75 | 19 ⚠️ | +0.78 | +0.36 | 1.73 | +0.0733 |
| 0.8 | 16 ⚠️ | -2.98 | -1.57 | 3.11 | -0.3568 |
| 0.85 | 5 ⚠️ | -1.29 | -1.78 | 1.46 | -0.6149 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +2.36 → out-of-sample +0.69 · overfit gap +1.67
deflated Sharpe: 0.304 (passes 95%: False) · PBO: 0.39 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **3 of 5 grid points have n < 30** (0.75, 0.8, 0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> filtered plateau pick unavailable: only 2 grid point(s) have n ≥ 30, and a plateau needs at least 3.

#### BNBUSDT — filter ablation

baseline: n=70 · E[R] +0.0568 · Sharpe +0.46

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 113 | -0.0428 | -0.0995 | -0.93 | keep |
| volatility | 89 | -0.0097 | -0.0664 | -0.64 | keep |
| volume | 70 | +0.0568 | +0.0000 | +0.00 | decoration |
| structure | 69 | +0.0761 | +0.0193 | +0.15 | review |
| momentum | 65 | +0.0756 | +0.0188 | +0.15 | review |
| extension | 72 | +0.0604 | +0.0036 | +0.07 | review |
| timing | 94 | +0.0515 | -0.0052 | -0.10 | keep |
| quality | 71 | +0.0618 | +0.0050 | +0.05 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

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
| 0.85 | 14 ⚠️ | +2.00 | +1.50 | 0.67 | +0.3104 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.93 → out-of-sample +1.11 · overfit gap +0.82
deflated Sharpe: 0.665 (passes 95%: False) · PBO: 0.31 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [])

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

### ETHUSDT

Data: **525,601** minutes (365.0 of 365 days requested) · 2025-09-18T00:00:00Z .. 2026-09-18T00:00:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 117 | -12.30 | -2.20 | 12.62 | 36.8 | -0.1671 | 0.61 |
| random_entry_control | 172 | -17.48 | -2.74 | 17.73 | 37.2 | -0.1824 | 0.60 |
| every_bar_control | 231 | -17.19 | -2.12 | 18.05 | 39.8 | -0.1242 | 0.72 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -6,184 − friction 6,114 = net -12,298 · E[R] -0.1671 · n=117

Entry funnel: 201 signals → 125 fills → 117 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=117 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 117 | -12.30 | -2.20 | 12.62 | -0.1671 |
| 0.6 | 82 | -9.12 | -2.11 | 9.49 | -0.1655 |
| 0.75 | 34 | -4.95 | -1.80 | 7.16 | -0.2119 |
| 0.8 | 23 ⚠️ | -3.54 | -1.62 | 4.63 | -0.2304 |
| 0.85 | 6 ⚠️ | -0.70 | -0.87 | 1.32 | -0.2408 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.00 → out-of-sample -1.69 · overfit gap +2.69
deflated Sharpe: 0.000 (passes 95%: False) · PBO: 0.64 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **2 of 5 grid points have n < 30** (0.8, 0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 3 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [])

#### ETHUSDT — filter ablation

baseline: n=117 · E[R] -0.1671 · Sharpe -2.20

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 161 | -0.1415 | +0.0257 | -0.16 | keep |
| volatility | 135 | -0.1260 | +0.0411 | +0.25 | harmful |
| volume | 117 | -0.1671 | +0.0000 | +0.00 | decoration |
| structure | 117 | -0.1671 | +0.0000 | +0.00 | decoration |
| momentum | 117 | -0.1674 | -0.0003 | +0.01 | decoration |
| extension | 119 | -0.1720 | -0.0049 | -0.14 | keep |
| timing | 145 | -0.1481 | +0.0190 | -0.12 | keep |
| quality | 118 | -0.1635 | +0.0036 | +0.04 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Data: **525,601** minutes (365.0 of 365 days requested) · 2025-09-18T00:00:00Z .. 2026-09-18T00:00:00Z · missing 0 min (0.0%) · source `https://data-api.binance.vision`

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 81 | +5.65 | +1.09 | 4.48 | 53.1 | +0.1216 | 1.36 |
| random_entry_control | 136 | -7.75 | -1.31 | 9.63 | 43.4 | -0.0938 | 0.75 |
| every_bar_control | 161 | -17.73 | -2.55 | 18.14 | 41.0 | -0.1668 | 0.62 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +9,132 − friction 3,478 = net +5,655 · E[R] +0.1216 · n=81

Entry funnel: 154 signals → 86 fills → 81 positions (fill rate 0.56)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=81 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 81 | +5.65 | +1.09 | 4.48 | +0.1216 |
| 0.6 | 65 | +6.75 | +1.39 | 4.25 | +0.1690 |
| 0.75 | 26 ⚠️ | +1.60 | +0.69 | 2.00 | +0.1507 |
| 0.8 | 15 ⚠️ | +0.58 | +0.34 | 1.97 | +0.1133 |
| 0.85 | 6 ⚠️ | +0.59 | +0.68 | 0.66 | +0.2144 |

plateau pick: `0.6` (agrees with the best single point: True)
walk-forward: in-sample Sharpe +1.84 → out-of-sample +0.53 · overfit gap +1.31
deflated Sharpe: 0.132 (passes 95%: False) · PBO: 0.83 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **3 of 5 grid points have n < 30** (0.75, 0.8, 0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> filtered plateau pick unavailable: only 2 grid point(s) have n ≥ 30, and a plateau needs at least 3.

#### SOLUSDT — filter ablation

baseline: n=81 · E[R] +0.1216 · Sharpe +1.09

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 125 | +0.0576 | -0.0640 | -0.40 | keep |
| volatility | 97 | +0.1810 | +0.0594 | +0.53 | harmful |
| volume | 80 | +0.1008 | -0.0208 | -0.22 | keep |
| structure | 82 | +0.1171 | -0.0045 | -0.03 | decoration |
| momentum | 78 | +0.1352 | +0.0136 | +0.10 | review |
| extension | 81 | +0.1323 | +0.0107 | +0.09 | review |
| timing | 99 | +0.1192 | -0.0024 | +0.05 | review |
| quality | 80 | +0.1105 | -0.0111 | -0.14 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BNBUSDT | 70 | +2.13 | 4.84 | 45.7 | +0.0568 | +5,937 | 3,809 | +2,128 |
| BTCUSDT | 159 | -8.23 | 10.62 | 41.5 | -0.0827 | +1,712 | 9,941 | -8,228 |
| ETHUSDT | 117 | -12.30 | 12.62 | 36.8 | -0.1671 | -6,184 | 6,114 | -12,298 |
| SOLUSDT | 81 | +5.65 | 4.48 | 53.1 | +0.1216 | +9,132 | 3,478 | +5,655 |
| **pooled** | **427** | — | — | — | **-0.0442** | **+10,598** | **23,342** | **-12,744** |

Signals 793 → fills 473 → positions 427 · accounting errors **0** · friction ÷ gross = 2.20

> ⚠️ pooled n = 427 is still below the ~569 trades needed for 80% power at 0.10R.

> positive E[R] in 2 of 4 symbols (BNBUSDT, SOLUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

