## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.43s)
OK   vision_archive (0.15s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 319 | -15.15 | -0.99 | 18.10 | 43.3 | -0.0610 | 0.79 |
| random_entry_control | 165 | -18.29 | -1.79 | 18.44 | 33.9 | -0.2057 | 0.54 |
| every_bar_control | 215 | -18.11 | -1.61 | 18.27 | 33.5 | -0.1689 | 0.64 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -3,584 − friction 11,570 = net -15,155 · E[R] -0.0610 · n=319

Entry funnel: 1193 signals → 746 fills → 319 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 319 | -15.15 | -0.99 | 18.10 | -0.0610 |
| 0.6 | 318 | -14.23 | -0.93 | 18.41 | -0.0627 |
| 0.75 | 192 | +4.56 | +0.38 | 5.85 | +0.0459 |
| 0.8 | 114 | +3.75 | +0.39 | 3.71 | +0.0552 |
| 0.85 | 38 | +2.54 | +0.49 | 2.27 | +0.0896 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.55 → out-of-sample -0.43 · overfit gap +0.98
deflated Sharpe: 0.130 (passes 95%: False) · PBO: 0.75 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=319 · E[R] -0.0610 · Sharpe -0.99

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 406 | -0.0600 | +0.0010 | +0.10 | review |
| volatility | 337 | -0.0637 | -0.0027 | +0.03 | review |
| volume | 346 | -0.0561 | +0.0050 | +0.03 | review |
| structure | 311 | -0.0622 | -0.0011 | -0.01 | decoration |
| momentum | 306 | -0.0641 | -0.0030 | -0.02 | decoration |
| extension | 310 | -0.0637 | -0.0026 | -0.01 | decoration |
| timing | 417 | -0.0457 | +0.0153 | +0.14 | review |
| quality | 351 | -0.0551 | +0.0059 | +0.04 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 980.1M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 561 | -16.35 | -0.76 | 18.26 | 44.2 | -0.0425 | 0.87 |
| random_entry_control | 178 | -18.06 | -1.59 | 18.21 | 36.0 | -0.1870 | 0.60 |
| every_bar_control | 413 | -16.65 | -0.91 | 18.02 | 42.9 | -0.0716 | 0.82 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +2,885 − friction 19,235 = net -16,349 · E[R] -0.0425 · n=561

Entry funnel: 1049 signals → 656 fills → 561 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 561 | -16.35 | -0.76 | 18.26 | -0.0425 |
| 0.6 | 425 | +3.95 | +0.23 | 11.25 | +0.0233 |
| 0.75 | 198 | -5.10 | -0.35 | 8.23 | -0.0236 |
| 0.8 | 124 | -3.23 | -0.28 | 9.02 | -0.0222 |
| 0.85 | 51 | +3.55 | +0.50 | 3.86 | +0.1252 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.52 → out-of-sample +0.55 · overfit gap -0.04
deflated Sharpe: 0.523 (passes 95%: False) · PBO: 0.38 — elevated: a meaningful share of the ranking is selection noise

#### ETHUSDT — filter ablation

baseline: n=561 · E[R] -0.0425 · Sharpe -0.76

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 836 | +0.0018 | +0.0443 | +0.69 | harmful |
| volatility | 628 | -0.0269 | +0.0156 | +0.19 | review |
| volume | 564 | -0.0419 | +0.0006 | +0.01 | decoration |
| structure | 564 | -0.0373 | +0.0052 | +0.10 | review |
| momentum | 554 | -0.0345 | +0.0080 | +0.14 | review |
| extension | 499 | -0.0498 | -0.0073 | -0.04 | review |
| timing | 510 | -0.0457 | -0.0032 | -0.06 | keep |
| quality | 494 | -0.0508 | -0.0083 | -0.07 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 458.4M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 465 | +11.77 | +0.58 | 7.86 | 51.6 | +0.0688 | 1.11 |
| random_entry_control | 372 | -17.40 | -1.01 | 18.32 | 43.8 | -0.1005 | 0.80 |
| every_bar_control | 444 | -15.87 | -0.97 | 18.16 | 45.9 | -0.1227 | 0.82 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +29,436 − friction 17,662 = net +11,773 · E[R] +0.0688 · n=465

Entry funnel: 885 signals → 526 fills → 465 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 465 | +11.77 | +0.58 | 7.86 | +0.0688 |
| 0.6 | 319 | +14.34 | +0.84 | 9.54 | +0.1022 |
| 0.75 | 126 | +4.30 | +0.44 | 3.59 | +0.0967 |
| 0.8 | 70 | +5.42 | +0.72 | 1.56 | +0.1657 |
| 0.85 | 26 ⚠️ | +5.85 | +1.40 | 1.10 | +0.3915 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.91 → out-of-sample -0.23 · overfit gap +2.14
deflated Sharpe: 0.030 (passes 95%: False) · PBO: 0.41 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=465 · E[R] +0.0688 · Sharpe +0.58

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 710 | +0.0782 | +0.0094 | +0.09 | review |
| volatility | 523 | +0.0848 | +0.0160 | +0.20 | review |
| volume | 467 | +0.0659 | -0.0029 | -0.04 | decoration |
| structure | 458 | +0.0722 | +0.0034 | +0.04 | decoration |
| momentum | 447 | +0.0516 | -0.0172 | -0.22 | keep |
| extension | 473 | +0.0713 | +0.0025 | +0.05 | decoration |
| timing | 573 | +0.0615 | -0.0073 | -0.11 | keep |
| quality | 470 | +0.0694 | +0.0006 | +0.02 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 216.2M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 530 | +1.72 | +0.12 | 14.30 | 48.1 | +0.0233 | 1.02 |
| random_entry_control | 317 | -18.11 | -1.17 | 18.22 | 40.1 | -0.1323 | 0.74 |
| every_bar_control | 318 | -16.11 | -0.94 | 18.16 | 43.4 | -0.1026 | 0.78 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +21,547 − friction 19,829 = net +1,718 · E[R] +0.0233 · n=530

Entry funnel: 937 signals → 588 fills → 530 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 530 | +1.72 | +0.12 | 14.30 | +0.0233 |
| 0.6 | 370 | +10.35 | +0.59 | 5.95 | +0.0568 |
| 0.75 | 124 | +9.19 | +0.82 | 5.18 | +0.1382 |
| 0.8 | 52 | +0.56 | +0.09 | 5.73 | +0.0877 |
| 0.85 | 15 ⚠️ | +1.86 | +0.70 | 1.08 | +0.3383 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.78 → out-of-sample +0.77 · overfit gap +0.01
deflated Sharpe: 0.581 (passes 95%: False) · PBO: 0.86 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=530 · E[R] +0.0233 · Sharpe +0.12

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 766 | +0.0235 | +0.0002 | -0.00 | review |
| volatility | 562 | +0.0332 | +0.0099 | +0.09 | review |
| volume | 540 | +0.0255 | +0.0022 | +0.04 | decoration |
| structure | 524 | +0.0122 | -0.0111 | -0.16 | keep |
| momentum | 505 | +0.0288 | +0.0055 | +0.07 | review |
| extension | 541 | +0.0266 | +0.0033 | +0.03 | decoration |
| timing | 636 | +0.0499 | +0.0266 | +0.35 | harmful |
| quality | 541 | +0.0232 | -0.0001 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 319 | -15.15 | 18.10 | 43.3 | -0.0610 | -3,584 | 11,570 | -15,155 |
| ETHUSDT | 561 | -16.35 | 18.26 | 44.2 | -0.0425 | +2,885 | 19,235 | -16,349 |
| SOLUSDT | 465 | +11.77 | 7.86 | 51.6 | +0.0688 | +29,436 | 17,662 | +11,773 |
| XRPUSDT | 530 | +1.72 | 14.30 | 48.1 | +0.0233 | +21,547 | 19,829 | +1,718 |
| **pooled** | **1875** | — | — | — | **+0.0006** | **+50,284** | **68,296** | **-18,013** |

Signals 4064 → fills 2516 → positions 1875 · accounting errors **0** · friction ÷ gross = 1.36

> ✅ **pooled n = 1875 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

