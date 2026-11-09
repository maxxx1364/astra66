## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.43s)
OK   vision_archive (0.36s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 354 | -17.43 | -1.09 | 18.06 | 42.7 | -0.0720 | 0.78 |
| random_entry_control | 266 | -17.60 | -1.25 | 18.00 | 39.5 | -0.1192 | 0.72 |
| every_bar_control | 216 | -17.46 | -1.58 | 18.06 | 36.1 | -0.1540 | 0.64 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -5,042 − friction 12,390 = net -17,432 · E[R] -0.0720 · n=354

Entry funnel: 1179 signals → 737 fills → 354 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 354 | -17.43 | -1.09 | 18.06 | -0.0720 |
| 0.6 | 312 | -17.24 | -1.16 | 18.21 | -0.0870 |
| 0.75 | 190 | +2.47 | +0.22 | 5.95 | +0.0248 |
| 0.8 | 112 | +2.41 | +0.26 | 3.65 | +0.0295 |
| 0.85 | 37 | +2.92 | +0.56 | 1.98 | +0.1047 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.25 → out-of-sample -0.34 · overfit gap +0.59
deflated Sharpe: 0.117 (passes 95%: False) · PBO: 0.55 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=354 · E[R] -0.0720 · Sharpe -1.09

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 384 | -0.0743 | -0.0023 | +0.05 | review |
| volatility | 370 | -0.0761 | -0.0041 | +0.01 | decoration |
| volume | 359 | -0.0734 | -0.0014 | -0.02 | decoration |
| structure | 308 | -0.0831 | -0.0111 | -0.08 | keep |
| momentum | 359 | -0.0699 | +0.0021 | +0.06 | review |
| extension | 317 | -0.0845 | -0.0125 | -0.10 | keep |
| timing | 404 | -0.0576 | +0.0144 | +0.13 | review |
| quality | 364 | -0.0722 | -0.0002 | -0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 441 | -17.21 | -0.92 | 18.20 | 43.8 | -0.0601 | 0.83 |
| random_entry_control | 257 | -17.27 | -1.21 | 18.02 | 40.1 | -0.1013 | 0.72 |
| every_bar_control | 427 | -17.80 | -0.97 | 18.10 | 43.1 | -0.0749 | 0.82 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -2,134 − friction 15,075 = net -17,209 · E[R] -0.0601 · n=441

Entry funnel: 1036 signals → 650 fills → 441 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 441 | -17.21 | -0.92 | 18.20 | -0.0601 |
| 0.6 | 423 | -1.49 | -0.04 | 11.53 | +0.0025 |
| 0.75 | 198 | -5.41 | -0.38 | 9.30 | -0.0233 |
| 0.8 | 126 | -3.94 | -0.35 | 9.64 | -0.0322 |
| 0.85 | 53 | +3.26 | +0.44 | 3.98 | +0.1024 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.27 → out-of-sample -0.10 · overfit gap +0.37
deflated Sharpe: 0.158 (passes 95%: False) · PBO: 0.30 — elevated: a meaningful share of the ranking is selection noise

#### ETHUSDT — filter ablation

baseline: n=441 · E[R] -0.0601 · Sharpe -0.92

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 824 | -0.0037 | +0.0564 | +0.74 | harmful |
| volatility | 622 | -0.0318 | +0.0283 | +0.26 | harmful |
| volume | 441 | -0.0592 | +0.0008 | +0.00 | decoration |
| structure | 479 | -0.0535 | +0.0066 | +0.07 | review |
| momentum | 540 | -0.0394 | +0.0207 | +0.21 | harmful |
| extension | 419 | -0.0643 | -0.0042 | -0.05 | keep |
| timing | 504 | -0.0507 | +0.0094 | +0.04 | review |
| quality | 439 | -0.0604 | -0.0003 | -0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 456.8M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 458 | +4.63 | +0.26 | 7.14 | 51.1 | +0.0411 | 1.05 |
| random_entry_control | 259 | -17.47 | -1.24 | 18.28 | 43.6 | -0.1042 | 0.73 |
| every_bar_control | 403 | -14.57 | -0.89 | 18.06 | 45.9 | -0.1100 | 0.83 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +21,390 − friction 16,764 = net +4,626 · E[R] +0.0411 · n=458

Entry funnel: 860 signals → 516 fills → 458 positions (fill rate 0.60)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 458 | +4.63 | +0.26 | 7.14 | +0.0411 |
| 0.6 | 310 | +9.39 | +0.58 | 8.57 | +0.0716 |
| 0.75 | 122 | +3.39 | +0.36 | 2.97 | +0.0832 |
| 0.8 | 70 | +5.06 | +0.66 | 1.78 | +0.1636 |
| 0.85 | 27 ⚠️ | +6.58 | +1.51 | 1.10 | +0.4406 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.84 → out-of-sample +1.30 · overfit gap +0.54
deflated Sharpe: 0.946 (passes 95%: False) · PBO: 0.19 — low: in-sample selection mostly carries out-of-sample

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=458 · E[R] +0.0411 · Sharpe +0.26

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 690 | +0.0524 | +0.0113 | +0.01 | review |
| volatility | 515 | +0.0573 | +0.0162 | +0.19 | review |
| volume | 459 | +0.0381 | -0.0031 | -0.04 | decoration |
| structure | 450 | +0.0435 | +0.0024 | +0.03 | decoration |
| momentum | 438 | +0.0291 | -0.0120 | -0.19 | keep |
| extension | 467 | +0.0417 | +0.0006 | +0.03 | decoration |
| timing | 558 | +0.0398 | -0.0014 | -0.09 | keep |
| quality | 462 | +0.0389 | -0.0023 | -0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 213.4M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 534 | -0.63 | +0.01 | 17.81 | 47.6 | +0.0152 | 0.99 |
| random_entry_control | 145 | -18.14 | -1.72 | 18.20 | 35.9 | -0.2227 | 0.52 |
| every_bar_control | 160 | -17.23 | -1.52 | 18.45 | 43.8 | -0.1886 | 0.60 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +19,201 − friction 19,832 = net -631 · E[R] +0.0152 · n=534

Entry funnel: 947 signals → 595 fills → 534 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 534 | -0.63 | +0.01 | 17.81 | +0.0152 |
| 0.6 | 370 | +9.40 | +0.53 | 6.77 | +0.0511 |
| 0.75 | 126 | +8.51 | +0.75 | 5.18 | +0.1404 |
| 0.8 | 54 | -0.77 | -0.10 | 5.75 | +0.0389 |
| 0.85 | 19 ⚠️ | +1.37 | +0.41 | 1.67 | +0.2136 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.86 → out-of-sample +0.48 · overfit gap +0.38
deflated Sharpe: 0.581 (passes 95%: False) · PBO: 0.77 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=534 · E[R] +0.0152 · Sharpe +0.01

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 775 | +0.0041 | -0.0110 | -0.20 | keep |
| volatility | 571 | +0.0305 | +0.0154 | +0.14 | review |
| volume | 542 | +0.0225 | +0.0073 | +0.12 | review |
| structure | 526 | +0.0149 | -0.0002 | -0.00 | decoration |
| momentum | 504 | +0.0214 | +0.0062 | +0.07 | review |
| extension | 376 | -0.0609 | -0.0761 | -1.15 | keep |
| timing | 637 | +0.0499 | +0.0347 | +0.44 | harmful |
| quality | 543 | +0.0157 | +0.0006 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 354 | -17.43 | 18.06 | 42.7 | -0.0720 | -5,042 | 12,390 | -17,432 |
| ETHUSDT | 441 | -17.21 | 18.20 | 43.8 | -0.0601 | -2,134 | 15,075 | -17,209 |
| SOLUSDT | 458 | +4.63 | 7.14 | 51.1 | +0.0411 | +21,390 | 16,764 | +4,626 |
| XRPUSDT | 534 | -0.63 | 17.81 | 47.6 | +0.0152 | +19,201 | 19,832 | -631 |
| **pooled** | **1787** | — | — | — | **-0.0140** | **+33,415** | **64,061** | **-30,646** |

Signals 4022 → fills 2498 → positions 1787 · accounting errors **0** · friction ÷ gross = 1.92

> ✅ **pooled n = 1787 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

