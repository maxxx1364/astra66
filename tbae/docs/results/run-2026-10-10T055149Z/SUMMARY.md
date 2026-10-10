## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.64s)
OK   vision_archive (0.57s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 345 | -12.93 | -0.80 | 18.05 | 42.9 | -0.0510 | 0.84 |
| random_entry_control | 369 | -17.38 | -1.06 | 18.01 | 39.6 | -0.0886 | 0.77 |
| every_bar_control | 259 | -16.85 | -1.35 | 18.33 | 35.9 | -0.1319 | 0.70 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +33 − friction 12,967 = net -12,934 · E[R] -0.0510 · n=345

Entry funnel: 1251 signals → 790 fills → 345 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 345 | -12.93 | -0.80 | 18.05 | -0.0510 |
| 0.6 | 327 | -12.59 | -0.78 | 18.12 | -0.0522 |
| 0.75 | 205 | +5.69 | +0.45 | 6.69 | +0.0562 |
| 0.8 | 119 | +1.06 | +0.12 | 4.62 | +0.0189 |
| 0.85 | 40 | +3.69 | +0.68 | 2.27 | +0.1475 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.89 → out-of-sample -0.74 · overfit gap +1.62
deflated Sharpe: 0.029 (passes 95%: False) · PBO: 0.41 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=345 · E[R] -0.0510 · Sharpe -0.80

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 559 | -0.0311 | +0.0199 | +0.19 | review |
| volatility | 347 | -0.0655 | -0.0145 | -0.10 | keep |
| volume | 385 | -0.0456 | +0.0054 | +0.04 | review |
| structure | 342 | -0.0509 | +0.0001 | -0.02 | decoration |
| momentum | 333 | -0.0547 | -0.0038 | -0.03 | decoration |
| extension | 339 | -0.0556 | -0.0046 | -0.01 | decoration |
| timing | 441 | -0.0446 | +0.0064 | +0.04 | review |
| quality | 389 | -0.0447 | +0.0063 | +0.05 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 974.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 563 | -13.45 | -0.61 | 18.01 | 45.5 | -0.0335 | 0.90 |
| random_entry_control | 213 | -17.83 | -1.41 | 18.28 | 41.8 | -0.1512 | 0.65 |
| every_bar_control | 361 | -16.45 | -0.97 | 18.35 | 41.3 | -0.0848 | 0.81 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +6,955 − friction 20,403 = net -13,447 · E[R] -0.0335 · n=563

Entry funnel: 1110 signals → 694 fills → 563 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 563 | -13.45 | -0.61 | 18.01 | -0.0335 |
| 0.6 | 452 | +6.36 | +0.33 | 11.65 | +0.0255 |
| 0.75 | 218 | -4.06 | -0.26 | 7.25 | -0.0083 |
| 0.8 | 138 | -3.04 | -0.25 | 7.43 | -0.0170 |
| 0.85 | 60 | +1.26 | +0.17 | 4.70 | +0.0520 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.72 → out-of-sample +0.36 · overfit gap +0.37
deflated Sharpe: 0.442 (passes 95%: False) · PBO: 0.67 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=563 · E[R] -0.0335 · Sharpe -0.61

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 878 | +0.0031 | +0.0366 | +0.58 | harmful |
| volatility | 654 | -0.0247 | +0.0089 | +0.09 | review |
| volume | 566 | -0.0340 | -0.0005 | -0.01 | decoration |
| structure | 594 | -0.0261 | +0.0074 | +0.16 | review |
| momentum | 585 | -0.0290 | +0.0045 | +0.10 | review |
| extension | 499 | -0.0374 | -0.0039 | +0.02 | review |
| timing | 525 | -0.0424 | -0.0088 | -0.13 | keep |
| quality | 530 | -0.0402 | -0.0067 | -0.06 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 488 | +13.36 | +0.65 | 7.87 | 52.0 | +0.0678 | 1.13 |
| random_entry_control | 236 | -16.59 | -1.29 | 18.12 | 42.8 | -0.1355 | 0.72 |
| every_bar_control | 428 | -16.62 | -1.09 | 18.20 | 43.9 | -0.1189 | 0.80 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +31,516 − friction 18,153 = net +13,363 · E[R] +0.0678 · n=488

Entry funnel: 953 signals → 552 fills → 488 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 488 | +13.36 | +0.65 | 7.87 | +0.0678 |
| 0.6 | 345 | +15.29 | +0.87 | 5.89 | +0.0919 |
| 0.75 | 137 | +4.54 | +0.46 | 2.79 | +0.0865 |
| 0.8 | 76 | +4.47 | +0.59 | 1.68 | +0.1105 |
| 0.85 | 27 ⚠️ | +4.19 | +1.01 | 1.85 | +0.2269 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.49 → out-of-sample +0.09 · overfit gap +1.40
deflated Sharpe: 0.100 (passes 95%: False) · PBO: 0.81 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=488 · E[R] +0.0678 · Sharpe +0.65

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 683 | +0.0259 | -0.0419 | -0.78 | keep |
| volatility | 550 | +0.0861 | +0.0183 | +0.18 | review |
| volume | 499 | +0.0628 | -0.0050 | -0.04 | decoration |
| structure | 492 | +0.0651 | -0.0027 | -0.01 | decoration |
| momentum | 480 | +0.0655 | -0.0023 | -0.06 | keep |
| extension | 498 | +0.0706 | +0.0028 | +0.05 | review |
| timing | 619 | +0.0678 | +0.0000 | -0.01 | review |
| quality | 510 | +0.0593 | -0.0085 | -0.06 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 219.1M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 561 | +4.94 | +0.26 | 14.09 | 48.3 | +0.0352 | 1.05 |
| random_entry_control | 169 | -15.85 | -1.42 | 18.02 | 41.4 | -0.1583 | 0.63 |
| every_bar_control | 263 | -17.51 | -1.16 | 18.22 | 44.9 | -0.1322 | 0.73 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +26,139 − friction 21,200 = net +4,938 · E[R] +0.0352 · n=561

Entry funnel: 997 signals → 625 fills → 561 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 561 | +4.94 | +0.26 | 14.09 | +0.0352 |
| 0.6 | 396 | +17.50 | +0.92 | 5.96 | +0.0838 |
| 0.75 | 131 | +12.85 | +1.08 | 5.19 | +0.1928 |
| 0.8 | 56 | -0.21 | -0.02 | 5.73 | +0.0488 |
| 0.85 | 15 ⚠️ | +1.14 | +0.44 | 1.08 | +0.2558 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.66 → out-of-sample +1.21 · overfit gap -0.55
deflated Sharpe: 0.781 (passes 95%: False) · PBO: 0.48 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=561 · E[R] +0.0352 · Sharpe +0.26

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 204 | -0.1399 | -0.1752 | -1.72 | keep |
| volatility | 603 | +0.0393 | +0.0040 | +0.00 | review |
| volume | 570 | +0.0363 | +0.0010 | +0.03 | decoration |
| structure | 554 | +0.0285 | -0.0068 | -0.11 | keep |
| momentum | 533 | +0.0434 | +0.0081 | +0.10 | review |
| extension | 571 | +0.0396 | +0.0044 | +0.06 | review |
| timing | 159 | -0.1811 | -0.2164 | -1.94 | keep |
| quality | 573 | +0.0287 | -0.0065 | -0.10 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 345 | -12.93 | 18.05 | 42.9 | -0.0510 | +33 | 12,967 | -12,934 |
| ETHUSDT | 563 | -13.45 | 18.01 | 45.5 | -0.0335 | +6,955 | 20,403 | -13,447 |
| SOLUSDT | 488 | +13.36 | 7.87 | 52.0 | +0.0678 | +31,516 | 18,153 | +13,363 |
| XRPUSDT | 561 | +4.94 | 14.09 | 48.3 | +0.0352 | +26,139 | 21,200 | +4,938 |
| **pooled** | **1957** | — | — | — | **+0.0084** | **+64,643** | **72,723** | **-8,079** |

Signals 4311 → fills 2661 → positions 1957 · accounting errors **0** · friction ÷ gross = 1.12

> ✅ **pooled n = 1957 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

