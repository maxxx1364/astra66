## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.44s)
OK   vision_archive (0.18s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 404 | -17.65 | -1.09 | 18.10 | 41.8 | -0.0664 | 0.79 |
| random_entry_control | 421 | -16.58 | -0.99 | 18.31 | 40.9 | -0.0578 | 0.81 |
| every_bar_control | 182 | -13.31 | -1.23 | 18.21 | 37.9 | -0.1096 | 0.69 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -8,297 − friction 9,349 = net -17,646 · E[R] -0.0664 · n=404

Entry funnel: 1147 signals → 724 fills → 404 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 404 | -17.65 | -1.09 | 18.10 | -0.0664 |
| 0.6 | 425 | -11.16 | -0.62 | 16.50 | -0.0360 |
| 0.75 | 183 | +6.08 | +0.51 | 6.12 | +0.0569 |
| 0.8 | 102 | +4.37 | +0.49 | 3.54 | +0.0679 |
| 0.85 | 33 | +2.61 | +0.55 | 1.79 | +0.1081 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.56 → out-of-sample -0.34 · overfit gap +0.90
deflated Sharpe: 0.115 (passes 95%: False) · PBO: 0.94 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=404 · E[R] -0.0664 · Sharpe -1.09

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 588 | -0.0469 | +0.0195 | +0.27 | review |
| volatility | 429 | -0.0669 | -0.0005 | +0.05 | review |
| volume | 378 | -0.0706 | -0.0041 | -0.01 | review |
| structure | 412 | -0.0656 | +0.0008 | +0.01 | decoration |
| momentum | 401 | -0.0606 | +0.0059 | +0.12 | review |
| extension | 399 | -0.0666 | -0.0002 | +0.01 | decoration |
| timing | 482 | -0.0544 | +0.0121 | +0.12 | review |
| quality | 392 | -0.0681 | -0.0017 | -0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.1M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 543 | -18.11 | -0.89 | 18.19 | 43.8 | -0.0534 | 0.85 |
| random_entry_control | 209 | -15.17 | -1.19 | 18.10 | 39.2 | -0.1018 | 0.70 |
| every_bar_control | 1066 | -12.27 | -0.37 | 18.30 | 45.1 | -0.0240 | 0.95 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -4,161 − friction 13,950 = net -18,111 · E[R] -0.0534 · n=543

Entry funnel: 1017 signals → 632 fills → 543 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 543 | -18.11 | -0.89 | 18.19 | -0.0534 |
| 0.6 | 412 | -5.75 | -0.27 | 11.34 | -0.0176 |
| 0.75 | 190 | -2.16 | -0.14 | 7.02 | +0.0038 |
| 0.8 | 120 | -2.07 | -0.18 | 8.26 | -0.0121 |
| 0.85 | 52 | +3.09 | +0.45 | 4.47 | +0.1131 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.09 → out-of-sample -0.13 · overfit gap +0.22
deflated Sharpe: 0.116 (passes 95%: False) · PBO: 0.47 — elevated: a meaningful share of the ranking is selection noise

#### ETHUSDT — filter ablation

baseline: n=543 · E[R] -0.0534 · Sharpe -0.89

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 814 | -0.0123 | +0.0411 | +0.54 | harmful |
| volatility | 610 | -0.0295 | +0.0239 | +0.33 | harmful |
| volume | 442 | -0.0699 | -0.0165 | -0.08 | keep |
| structure | 547 | -0.0517 | +0.0017 | +0.01 | decoration |
| momentum | 542 | -0.0493 | +0.0041 | +0.08 | review |
| extension | 481 | -0.0650 | -0.0116 | -0.07 | keep |
| timing | 639 | -0.0357 | +0.0177 | +0.24 | review |
| quality | 430 | -0.0705 | -0.0171 | -0.11 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 452.8M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 455 | +6.04 | +0.33 | 6.54 | 51.2 | +0.0491 | 1.06 |
| random_entry_control | 155 | -18.22 | -1.74 | 18.24 | 34.2 | -0.2387 | 0.56 |
| every_bar_control | 346 | -16.39 | -1.16 | 18.07 | 44.2 | -0.1364 | 0.77 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +20,366 − friction 14,322 = net +6,044 · E[R] +0.0491 · n=455

Entry funnel: 858 signals → 509 fills → 455 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 455 | +6.04 | +0.33 | 6.54 | +0.0491 |
| 0.6 | 311 | +6.82 | +0.44 | 6.57 | +0.0580 |
| 0.75 | 127 | +2.42 | +0.26 | 3.26 | +0.0654 |
| 0.8 | 69 | +4.64 | +0.63 | 2.03 | +0.1625 |
| 0.85 | 26 ⚠️ | +6.36 | +1.50 | 1.08 | +0.4370 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.77 → out-of-sample +1.35 · overfit gap +0.42
deflated Sharpe: 0.965 (passes 95%: True) · PBO: 0.17 — low: in-sample selection mostly carries out-of-sample

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [0.8])

#### SOLUSDT — filter ablation

baseline: n=455 · E[R] +0.0491 · Sharpe +0.33

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 689 | +0.0614 | +0.0123 | +0.09 | review |
| volatility | 517 | +0.0527 | +0.0036 | -0.02 | review |
| volume | 456 | +0.0466 | -0.0025 | -0.04 | decoration |
| structure | 449 | +0.0523 | +0.0032 | +0.04 | decoration |
| momentum | 438 | +0.0455 | -0.0036 | -0.11 | keep |
| extension | 463 | +0.0524 | +0.0033 | +0.07 | review |
| timing | 555 | +0.0531 | +0.0040 | -0.05 | review |
| quality | 459 | +0.0474 | -0.0017 | -0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 208.8M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 539 | +2.71 | +0.16 | 15.90 | 47.9 | +0.0275 | 1.03 |
| random_entry_control | 482 | -16.12 | -0.85 | 18.19 | 44.2 | -0.0512 | 0.85 |
| every_bar_control | 301 | -17.95 | -1.13 | 18.47 | 42.9 | -0.0941 | 0.76 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +20,076 − friction 17,364 = net +2,712 · E[R] +0.0275 · n=539

Entry funnel: 958 signals → 601 fills → 539 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 539 | +2.71 | +0.16 | 15.90 | +0.0275 |
| 0.6 | 375 | +7.29 | +0.43 | 9.51 | +0.0444 |
| 0.75 | 126 | +8.71 | +0.76 | 5.09 | +0.1315 |
| 0.8 | 55 | +1.96 | +0.28 | 2.81 | +0.0962 |
| 0.85 | 17 ⚠️ | +1.17 | +0.37 | 1.60 | +0.1964 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.68 → out-of-sample +0.48 · overfit gap +0.20
deflated Sharpe: 0.465 (passes 95%: False) · PBO: 0.72 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=539 · E[R] +0.0275 · Sharpe +0.16

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 774 | +0.0100 | -0.0175 | -0.28 | keep |
| volatility | 573 | +0.0331 | +0.0056 | +0.01 | review |
| volume | 547 | +0.0290 | +0.0015 | +0.03 | decoration |
| structure | 166 | -0.1948 | -0.2223 | -1.88 | keep |
| momentum | 507 | +0.0186 | -0.0089 | -0.11 | keep |
| extension | 549 | +0.0285 | +0.0010 | +0.01 | decoration |
| timing | 639 | +0.0585 | +0.0310 | +0.44 | harmful |
| quality | 547 | +0.0235 | -0.0040 | -0.05 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 404 | -17.65 | 18.10 | 41.8 | -0.0664 | -8,297 | 9,349 | -17,646 |
| ETHUSDT | 543 | -18.11 | 18.19 | 43.8 | -0.0534 | -4,161 | 13,950 | -18,111 |
| SOLUSDT | 455 | +6.04 | 6.54 | 51.2 | +0.0491 | +20,366 | 14,322 | +6,044 |
| XRPUSDT | 539 | +2.71 | 15.90 | 47.9 | +0.0275 | +20,076 | 17,364 | +2,712 |
| **pooled** | **1941** | — | — | — | **-0.0096** | **+27,984** | **54,985** | **-27,000** |

Signals 3980 → fills 2466 → positions 1941 · accounting errors **0** · friction ÷ gross = 1.96

> ✅ **pooled n = 1941 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

