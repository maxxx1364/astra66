## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.59s)
OK   vision_archive (0.23s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 379 | -13.29 | -0.78 | 18.14 | 42.7 | -0.0447 | 0.85 |
| random_entry_control | 151 | -17.13 | -1.87 | 18.01 | 29.1 | -0.2393 | 0.52 |
| every_bar_control | 279 | -17.97 | -1.43 | 18.21 | 35.8 | -0.1276 | 0.69 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +961 − friction 14,253 = net -13,292 · E[R] -0.0447 · n=379

Entry funnel: 1268 signals → 792 fills → 379 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 379 | -13.29 | -0.78 | 18.14 | -0.0447 |
| 0.6 | 335 | -12.96 | -0.80 | 18.43 | -0.0556 |
| 0.75 | 208 | +4.07 | +0.32 | 6.03 | +0.0335 |
| 0.8 | 123 | +5.08 | +0.51 | 4.33 | +0.0763 |
| 0.85 | 38 | +3.79 | +0.73 | 1.99 | +0.1479 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.71 → out-of-sample -0.35 · overfit gap +1.06
deflated Sharpe: 0.149 (passes 95%: False) · PBO: 0.44 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=379 · E[R] -0.0447 · Sharpe -0.78

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 619 | -0.0399 | +0.0048 | +0.07 | review |
| volatility | 358 | -0.0599 | -0.0153 | -0.08 | keep |
| volume | 398 | -0.0423 | +0.0024 | +0.02 | review |
| structure | 351 | -0.0484 | -0.0037 | -0.02 | review |
| momentum | 348 | -0.0507 | -0.0060 | -0.05 | review |
| extension | 360 | -0.0504 | -0.0057 | -0.04 | review |
| timing | 456 | -0.0411 | +0.0036 | +0.07 | review |
| quality | 400 | -0.0428 | +0.0019 | +0.02 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.1M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 489 | -13.17 | -0.64 | 18.33 | 45.8 | -0.0394 | 0.89 |
| random_entry_control | 150 | -16.14 | -1.53 | 18.05 | 37.3 | -0.2107 | 0.62 |
| every_bar_control | 350 | -17.26 | -1.07 | 18.14 | 40.6 | -0.0912 | 0.79 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +4,618 − friction 17,787 = net -13,170 · E[R] -0.0394 · n=489

Entry funnel: 1138 signals → 703 fills → 489 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 489 | -13.17 | -0.64 | 18.33 | -0.0394 |
| 0.6 | 455 | +6.00 | +0.32 | 11.41 | +0.0266 |
| 0.75 | 228 | -2.33 | -0.13 | 6.47 | +0.0133 |
| 0.8 | 141 | -1.83 | -0.14 | 8.08 | +0.0090 |
| 0.85 | 64 | +3.62 | +0.45 | 4.74 | +0.1116 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.78 → out-of-sample +0.31 · overfit gap +0.47
deflated Sharpe: 0.560 (passes 95%: False) · PBO: 0.69 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=489 · E[R] -0.0394 · Sharpe -0.64

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 899 | +0.0097 | +0.0492 | +0.70 | harmful |
| volatility | 657 | -0.0282 | +0.0112 | +0.01 | review |
| volume | 491 | -0.0375 | +0.0019 | +0.06 | review |
| structure | 609 | -0.0266 | +0.0129 | +0.14 | review |
| momentum | 585 | -0.0290 | +0.0104 | +0.06 | review |
| extension | 465 | -0.0413 | -0.0018 | -0.01 | decoration |
| timing | 541 | -0.0350 | +0.0044 | -0.01 | review |
| quality | 463 | -0.0371 | +0.0023 | +0.05 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 494 | +13.16 | +0.64 | 10.55 | 52.4 | +0.0702 | 1.12 |
| random_entry_control | 201 | -18.13 | -1.60 | 18.43 | 39.3 | -0.1875 | 0.63 |
| every_bar_control | 363 | -18.19 | -1.27 | 18.19 | 42.7 | -0.1354 | 0.75 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +31,592 − friction 18,430 = net +13,161 · E[R] +0.0702 · n=494

Entry funnel: 976 signals → 563 fills → 494 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 494 | +13.16 | +0.64 | 10.55 | +0.0702 |
| 0.6 | 355 | +18.95 | +1.05 | 5.38 | +0.1056 |
| 0.75 | 141 | +5.62 | +0.54 | 3.21 | +0.0971 |
| 0.8 | 84 | +2.76 | +0.36 | 2.05 | +0.0791 |
| 0.85 | 28 ⚠️ | +5.01 | +1.10 | 1.63 | +0.2282 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.86 → out-of-sample +0.06 · overfit gap +1.80
deflated Sharpe: 0.031 (passes 95%: False) · PBO: 0.73 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=494 · E[R] +0.0702 · Sharpe +0.64

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 471 | +0.0298 | -0.0405 | -0.71 | keep |
| volatility | 558 | +0.0840 | +0.0138 | +0.16 | review |
| volume | 503 | +0.0757 | +0.0054 | +0.10 | review |
| structure | 496 | +0.0729 | +0.0027 | +0.09 | review |
| momentum | 486 | +0.0708 | +0.0005 | +0.05 | review |
| extension | 503 | +0.0715 | +0.0013 | +0.04 | decoration |
| timing | 634 | +0.0701 | -0.0001 | +0.07 | review |
| quality | 516 | +0.0694 | -0.0008 | +0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 217.7M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 579 | +2.06 | +0.13 | 16.29 | 48.2 | +0.0280 | 1.02 |
| random_entry_control | 62 | -17.91 | -2.93 | 18.01 | 21.0 | -0.5775 | 0.18 |
| every_bar_control | 250 | -17.54 | -1.23 | 18.29 | 43.2 | -0.1369 | 0.70 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +23,367 − friction 21,303 = net +2,063 · E[R] +0.0280 · n=579

Entry funnel: 1016 signals → 644 fills → 579 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 579 | +2.06 | +0.13 | 16.29 | +0.0280 |
| 0.6 | 401 | +13.16 | +0.71 | 6.39 | +0.0702 |
| 0.75 | 130 | +13.16 | +1.11 | 4.70 | +0.1922 |
| 0.8 | 56 | -1.10 | -0.15 | 5.73 | +0.0174 |
| 0.85 | 14 ⚠️ | +1.02 | +0.41 | 1.08 | +0.2718 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.70 → out-of-sample +1.51 · overfit gap -0.81
deflated Sharpe: 0.959 (passes 95%: True) · PBO: 0.38 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=579 · E[R] +0.0280 · Sharpe +0.13

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 201 | -0.1287 | -0.1567 | -1.52 | keep |
| volatility | 613 | +0.0354 | +0.0074 | +0.05 | review |
| volume | 588 | +0.0315 | +0.0035 | +0.07 | review |
| structure | 570 | +0.0248 | -0.0032 | -0.05 | decoration |
| momentum | 549 | +0.0363 | +0.0083 | +0.12 | review |
| extension | 588 | +0.0333 | +0.0053 | +0.07 | review |
| timing | 162 | -0.1802 | -0.2082 | -1.84 | keep |
| quality | 592 | +0.0251 | -0.0029 | -0.04 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 379 | -13.29 | 18.14 | 42.7 | -0.0447 | +961 | 14,253 | -13,292 |
| ETHUSDT | 489 | -13.17 | 18.33 | 45.8 | -0.0394 | +4,618 | 17,787 | -13,170 |
| SOLUSDT | 494 | +13.16 | 10.55 | 52.4 | +0.0702 | +31,592 | 18,430 | +13,161 |
| XRPUSDT | 579 | +2.06 | 16.29 | 48.2 | +0.0280 | +23,367 | 21,303 | +2,063 |
| **pooled** | **1941** | — | — | — | **+0.0076** | **+60,537** | **71,774** | **-11,237** |

Signals 4398 → fills 2702 → positions 1941 · accounting errors **0** · friction ÷ gross = 1.19

> ✅ **pooled n = 1941 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

