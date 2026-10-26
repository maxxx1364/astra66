## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.50s)
OK   vision_archive (0.50s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 323 | -13.95 | -0.90 | 18.21 | 43.7 | -0.0565 | 0.81 |
| random_entry_control | 261 | -18.03 | -1.36 | 18.31 | 39.5 | -0.1291 | 0.71 |
| every_bar_control | 224 | -18.38 | -1.61 | 18.49 | 33.5 | -0.1667 | 0.64 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -2,031 − friction 11,916 = net -13,947 · E[R] -0.0565 · n=323

Entry funnel: 1212 signals → 762 fills → 323 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 323 | -13.95 | -0.90 | 18.21 | -0.0565 |
| 0.6 | 309 | -14.22 | -0.93 | 18.12 | -0.0658 |
| 0.75 | 196 | +4.68 | +0.38 | 5.66 | +0.0461 |
| 0.8 | 114 | +4.70 | +0.49 | 3.75 | +0.0728 |
| 0.85 | 38 | +3.70 | +0.71 | 2.27 | +0.1513 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.66 → out-of-sample -0.43 · overfit gap +1.09
deflated Sharpe: 0.164 (passes 95%: False) · PBO: 0.53 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=323 · E[R] -0.0565 · Sharpe -0.90

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 419 | -0.0542 | +0.0024 | +0.09 | review |
| volatility | 332 | -0.0640 | -0.0075 | -0.02 | decoration |
| volume | 329 | -0.0539 | +0.0026 | +0.02 | decoration |
| structure | 313 | -0.0607 | -0.0042 | -0.04 | decoration |
| momentum | 312 | -0.0603 | -0.0038 | -0.04 | decoration |
| extension | 273 | -0.0681 | -0.0115 | -0.08 | keep |
| timing | 421 | -0.0446 | +0.0119 | +0.08 | review |
| quality | 334 | -0.0529 | +0.0036 | +0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 509 | -13.30 | -0.63 | 18.10 | 45.2 | -0.0378 | 0.89 |
| random_entry_control | 120 | -18.17 | -2.00 | 18.19 | 34.2 | -0.2603 | 0.48 |
| every_bar_control | 478 | -17.83 | -0.90 | 18.50 | 42.3 | -0.0716 | 0.83 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +5,321 − friction 18,618 = net -13,297 · E[R] -0.0378 · n=509

Entry funnel: 1078 signals → 676 fills → 509 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 509 | -13.30 | -0.63 | 18.10 | -0.0378 |
| 0.6 | 436 | +6.24 | +0.33 | 12.37 | +0.0281 |
| 0.75 | 208 | -4.12 | -0.28 | 8.38 | -0.0060 |
| 0.8 | 133 | -2.62 | -0.21 | 8.55 | -0.0052 |
| 0.85 | 58 | +3.25 | +0.43 | 5.15 | +0.1167 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.82 → out-of-sample +0.27 · overfit gap +0.54
deflated Sharpe: 0.464 (passes 95%: False) · PBO: 0.52 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=509 · E[R] -0.0378 · Sharpe -0.63

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 851 | +0.0039 | +0.0417 | +0.61 | harmful |
| volatility | 641 | -0.0222 | +0.0156 | +0.13 | review |
| volume | 511 | -0.0346 | +0.0032 | +0.06 | review |
| structure | 505 | -0.0268 | +0.0110 | +0.21 | review |
| momentum | 561 | -0.0220 | +0.0158 | +0.23 | review |
| extension | 494 | -0.0444 | -0.0066 | -0.06 | keep |
| timing | 506 | -0.0437 | -0.0060 | -0.15 | keep |
| quality | 513 | -0.0343 | +0.0035 | +0.06 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 472 | +11.92 | +0.59 | 7.13 | 52.1 | +0.0640 | 1.11 |
| random_entry_control | 255 | -17.10 | -1.21 | 18.11 | 39.6 | -0.1291 | 0.75 |
| every_bar_control | 484 | -16.94 | -1.01 | 18.00 | 45.7 | -0.1159 | 0.83 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +29,419 − friction 17,500 = net +11,918 · E[R] +0.0640 · n=472

Entry funnel: 899 signals → 534 fills → 472 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 472 | +11.92 | +0.59 | 7.13 | +0.0640 |
| 0.6 | 331 | +10.82 | +0.66 | 7.63 | +0.0828 |
| 0.75 | 128 | +2.21 | +0.24 | 4.34 | +0.0658 |
| 0.8 | 71 | +5.28 | +0.72 | 1.63 | +0.1532 |
| 0.85 | 27 ⚠️ | +4.25 | +1.04 | 1.85 | +0.2416 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.49 → out-of-sample +0.15 · overfit gap +1.34
deflated Sharpe: 0.138 (passes 95%: False) · PBO: 0.75 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [0.8])

#### SOLUSDT — filter ablation

baseline: n=472 · E[R] +0.0640 · Sharpe +0.59

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 721 | +0.0458 | -0.0182 | -0.33 | keep |
| volatility | 528 | +0.0748 | +0.0109 | +0.10 | review |
| volume | 476 | +0.0581 | -0.0059 | -0.07 | keep |
| structure | 468 | +0.0626 | -0.0014 | -0.01 | decoration |
| momentum | 454 | +0.0402 | -0.0238 | -0.34 | keep |
| extension | 480 | +0.0665 | +0.0025 | +0.05 | decoration |
| timing | 581 | +0.0610 | -0.0030 | -0.12 | keep |
| quality | 479 | +0.0617 | -0.0023 | -0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 217.7M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 547 | +2.64 | +0.16 | 15.02 | 48.4 | +0.0281 | 1.03 |
| random_entry_control | 232 | -18.17 | -1.35 | 18.17 | 40.5 | -0.1696 | 0.69 |
| every_bar_control | 213 | -14.57 | -1.03 | 18.27 | 44.1 | -0.1288 | 0.74 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +23,077 − friction 20,435 = net +2,641 · E[R] +0.0281 · n=547

Entry funnel: 968 signals → 608 fills → 547 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 547 | +2.64 | +0.16 | 15.02 | +0.0281 |
| 0.6 | 383 | +10.41 | +0.58 | 8.67 | +0.0594 |
| 0.75 | 124 | +10.23 | +0.90 | 5.19 | +0.1684 |
| 0.8 | 52 | -0.44 | -0.05 | 5.73 | +0.0441 |
| 0.85 | 15 ⚠️ | +1.66 | +0.66 | 1.10 | +0.3168 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.79 → out-of-sample +0.60 · overfit gap +0.19
deflated Sharpe: 0.455 (passes 95%: False) · PBO: 0.83 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=547 · E[R] +0.0281 · Sharpe +0.16

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 217 | -0.1298 | -0.1579 | -1.54 | keep |
| volatility | 583 | +0.0347 | +0.0066 | +0.03 | review |
| volume | 558 | +0.0270 | -0.0011 | +0.01 | decoration |
| structure | 542 | +0.0181 | -0.0099 | -0.15 | keep |
| momentum | 520 | +0.0302 | +0.0021 | +0.01 | decoration |
| extension | 557 | +0.0320 | +0.0039 | +0.05 | decoration |
| timing | 652 | +0.0546 | +0.0265 | +0.33 | harmful |
| quality | 560 | +0.0201 | -0.0080 | -0.11 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 323 | -13.95 | 18.21 | 43.7 | -0.0565 | -2,031 | 11,916 | -13,947 |
| ETHUSDT | 509 | -13.30 | 18.10 | 45.2 | -0.0378 | +5,321 | 18,618 | -13,297 |
| SOLUSDT | 472 | +11.92 | 7.13 | 52.1 | +0.0640 | +29,419 | 17,500 | +11,918 |
| XRPUSDT | 547 | +2.64 | 15.02 | 48.4 | +0.0281 | +23,077 | 20,435 | +2,641 |
| **pooled** | **1851** | — | — | — | **+0.0044** | **+55,785** | **68,469** | **-12,684** |

Signals 4157 → fills 2580 → positions 1851 · accounting errors **0** · friction ÷ gross = 1.23

> ✅ **pooled n = 1851 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

