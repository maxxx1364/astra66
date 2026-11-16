## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.46s)
OK   vision_archive (0.18s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 394 | -17.13 | -1.07 | 18.27 | 41.9 | -0.0642 | 0.79 |
| random_entry_control | 562 | -18.20 | -0.98 | 18.28 | 41.5 | -0.0565 | 0.83 |
| every_bar_control | 265 | -14.37 | -1.10 | 18.15 | 39.2 | -0.0854 | 0.74 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -7,950 − friction 9,180 = net -17,130 · E[R] -0.0642 · n=394

Entry funnel: 1160 signals → 729 fills → 394 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 394 | -17.13 | -1.07 | 18.27 | -0.0642 |
| 0.6 | 431 | -13.78 | -0.78 | 17.03 | -0.0459 |
| 0.75 | 186 | +6.24 | +0.52 | 5.71 | +0.0554 |
| 0.8 | 106 | +2.72 | +0.31 | 4.31 | +0.0428 |
| 0.85 | 37 | +2.21 | +0.43 | 1.95 | +0.0760 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.51 → out-of-sample -0.21 · overfit gap +0.72
deflated Sharpe: 0.234 (passes 95%: False) · PBO: 0.80 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=394 · E[R] -0.0642 · Sharpe -1.07

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 587 | -0.0443 | +0.0199 | +0.26 | review |
| volatility | 416 | -0.0655 | -0.0012 | +0.03 | review |
| volume | 397 | -0.0638 | +0.0005 | +0.01 | decoration |
| structure | 393 | -0.0642 | +0.0001 | -0.00 | decoration |
| momentum | 382 | -0.0609 | +0.0033 | +0.08 | review |
| extension | 400 | -0.0629 | +0.0013 | +0.02 | decoration |
| timing | 492 | -0.0484 | +0.0159 | +0.15 | review |
| quality | 399 | -0.0628 | +0.0015 | +0.02 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 971.9M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 560 | -15.23 | -0.71 | 15.36 | 44.6 | -0.0419 | 0.88 |
| random_entry_control | 326 | -17.59 | -1.14 | 18.22 | 40.5 | -0.0784 | 0.76 |
| every_bar_control | 1092 | -14.92 | -0.46 | 18.13 | 45.0 | -0.0278 | 0.94 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -306 − friction 14,920 = net -15,226 · E[R] -0.0419 · n=560

Entry funnel: 1025 signals → 639 fills → 560 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 560 | -15.23 | -0.71 | 15.36 | -0.0419 |
| 0.6 | 421 | -3.49 | -0.15 | 11.21 | -0.0068 |
| 0.75 | 196 | -3.19 | -0.22 | 8.44 | -0.0043 |
| 0.8 | 123 | -2.10 | -0.18 | 8.79 | -0.0134 |
| 0.85 | 52 | +1.97 | +0.29 | 4.47 | +0.0832 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.01 → out-of-sample -0.31 · overfit gap +0.32
deflated Sharpe: 0.054 (passes 95%: False) · PBO: 0.62 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=560 · E[R] -0.0419 · Sharpe -0.71

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 813 | +0.0013 | +0.0432 | +0.62 | harmful |
| volatility | 613 | -0.0189 | +0.0230 | +0.35 | harmful |
| volume | 563 | -0.0430 | -0.0012 | -0.04 | decoration |
| structure | 564 | -0.0396 | +0.0022 | +0.04 | decoration |
| momentum | 542 | -0.0312 | +0.0106 | +0.20 | review |
| extension | 574 | -0.0471 | -0.0053 | -0.10 | keep |
| timing | 645 | -0.0363 | +0.0056 | +0.04 | review |
| quality | 566 | -0.0434 | -0.0016 | -0.06 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 452.9M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 457 | +9.23 | +0.47 | 6.72 | 51.9 | +0.0621 | 1.09 |
| random_entry_control | 454 | -17.85 | -0.94 | 18.04 | 42.7 | -0.0804 | 0.83 |
| every_bar_control | 454 | -15.26 | -0.83 | 18.20 | 45.6 | -0.0994 | 0.85 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +24,289 − friction 15,063 = net +9,227 · E[R] +0.0621 · n=457

Entry funnel: 872 signals → 517 fills → 457 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 457 | +9.23 | +0.47 | 6.72 | +0.0621 |
| 0.6 | 315 | +12.62 | +0.75 | 6.81 | +0.0900 |
| 0.75 | 123 | +3.76 | +0.39 | 3.26 | +0.0931 |
| 0.8 | 70 | +4.78 | +0.65 | 1.74 | +0.1416 |
| 0.85 | 27 ⚠️ | +5.89 | +1.34 | 1.08 | +0.3732 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.75 → out-of-sample +0.18 · overfit gap +1.57
deflated Sharpe: 0.247 (passes 95%: False) · PBO: 0.50 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=457 · E[R] +0.0621 · Sharpe +0.47

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 700 | +0.0646 | +0.0026 | -0.02 | review |
| volatility | 516 | +0.0704 | +0.0084 | +0.07 | review |
| volume | 459 | +0.0622 | +0.0002 | -0.00 | decoration |
| structure | 451 | +0.0667 | +0.0047 | +0.06 | review |
| momentum | 438 | +0.0567 | -0.0053 | -0.14 | keep |
| extension | 466 | +0.0627 | +0.0007 | +0.05 | decoration |
| timing | 558 | +0.0633 | +0.0012 | -0.04 | review |
| quality | 463 | +0.0619 | -0.0002 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 209.2M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 537 | +2.21 | +0.14 | 15.36 | 47.9 | +0.0260 | 1.02 |
| random_entry_control | 125 | -18.02 | -1.95 | 18.40 | 33.6 | -0.2457 | 0.44 |
| every_bar_control | 297 | -17.66 | -1.14 | 18.35 | 42.8 | -0.0920 | 0.74 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +19,417 − friction 17,210 = net +2,206 · E[R] +0.0260 · n=537

Entry funnel: 953 signals → 599 fills → 537 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 537 | +2.21 | +0.14 | 15.36 | +0.0260 |
| 0.6 | 372 | +8.88 | +0.51 | 7.98 | +0.0519 |
| 0.75 | 128 | +7.90 | +0.69 | 5.09 | +0.1254 |
| 0.8 | 55 | +0.43 | +0.07 | 3.34 | +0.0568 |
| 0.85 | 18 ⚠️ | +0.99 | +0.30 | 1.62 | +0.1570 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.56 → out-of-sample +0.38 · overfit gap +0.18
deflated Sharpe: 0.386 (passes 95%: False) · PBO: 0.80 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=537 · E[R] +0.0260 · Sharpe +0.14

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 778 | +0.0128 | -0.0133 | -0.20 | keep |
| volatility | 568 | +0.0417 | +0.0157 | +0.16 | review |
| volume | 547 | +0.0320 | +0.0059 | +0.10 | review |
| structure | 529 | +0.0223 | -0.0037 | -0.07 | keep |
| momentum | 505 | +0.0265 | +0.0005 | +0.03 | review |
| extension | 549 | +0.0286 | +0.0026 | +0.02 | decoration |
| timing | 642 | +0.0607 | +0.0346 | +0.49 | harmful |
| quality | 548 | +0.0260 | +0.0000 | +0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 394 | -17.13 | 18.27 | 41.9 | -0.0642 | -7,950 | 9,180 | -17,130 |
| ETHUSDT | 560 | -15.23 | 15.36 | 44.6 | -0.0419 | -306 | 14,920 | -15,226 |
| SOLUSDT | 457 | +9.23 | 6.72 | 51.9 | +0.0621 | +24,289 | 15,063 | +9,227 |
| XRPUSDT | 537 | +2.21 | 15.36 | 47.9 | +0.0260 | +19,417 | 17,210 | +2,206 |
| **pooled** | **1948** | — | — | — | **-0.0033** | **+35,450** | **56,373** | **-20,923** |

Signals 4010 → fills 2484 → positions 1948 · accounting errors **0** · friction ÷ gross = 1.59

> ✅ **pooled n = 1948 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

