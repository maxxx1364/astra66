## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.60s)
OK   vision_archive (0.23s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 374 | -15.20 | -0.91 | 18.14 | 44.1 | -0.0552 | 0.82 |
| random_entry_control | 135 | -17.15 | -1.97 | 18.12 | 33.3 | -0.2342 | 0.47 |
| every_bar_control | 246 | -18.07 | -1.50 | 18.38 | 37.0 | -0.1451 | 0.66 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -1,503 − friction 13,699 = net -15,202 · E[R] -0.0552 · n=374

Entry funnel: 1223 signals → 773 fills → 374 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 374 | -15.20 | -0.91 | 18.14 | -0.0552 |
| 0.6 | 335 | -14.46 | -0.91 | 18.10 | -0.0620 |
| 0.75 | 200 | +4.53 | +0.36 | 6.76 | +0.0476 |
| 0.8 | 119 | +3.61 | +0.37 | 3.91 | +0.0557 |
| 0.85 | 36 | +2.83 | +0.57 | 2.24 | +0.1239 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.58 → out-of-sample -0.33 · overfit gap +0.91
deflated Sharpe: 0.196 (passes 95%: False) · PBO: 0.69 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=374 · E[R] -0.0552 · Sharpe -0.91

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 623 | -0.0396 | +0.0156 | +0.23 | review |
| volatility | 354 | -0.0655 | -0.0102 | -0.07 | keep |
| volume | 376 | -0.0542 | +0.0010 | +0.01 | decoration |
| structure | 357 | -0.0576 | -0.0023 | -0.03 | decoration |
| momentum | 376 | -0.0557 | -0.0005 | +0.01 | decoration |
| extension | 339 | -0.0625 | -0.0072 | -0.04 | review |
| timing | 426 | -0.0487 | +0.0065 | +0.06 | review |
| quality | 383 | -0.0543 | +0.0009 | +0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 986.0M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 585 | -14.67 | -0.66 | 18.10 | 45.1 | -0.0351 | 0.89 |
| random_entry_control | 345 | -17.87 | -1.09 | 18.16 | 40.3 | -0.0835 | 0.78 |
| every_bar_control | 499 | -17.50 | -0.86 | 18.07 | 42.7 | -0.0671 | 0.84 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +6,359 − friction 21,029 = net -14,670 · E[R] -0.0351 · n=585

Entry funnel: 1077 signals → 678 fills → 585 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 585 | -14.67 | -0.66 | 18.10 | -0.0351 |
| 0.6 | 437 | +8.80 | +0.45 | 12.03 | +0.0391 |
| 0.75 | 212 | -3.45 | -0.22 | 7.51 | +0.0048 |
| 0.8 | 134 | -4.27 | -0.37 | 8.84 | -0.0312 |
| 0.85 | 57 | +2.01 | +0.27 | 5.75 | +0.0702 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.00 → out-of-sample +0.36 · overfit gap +0.63
deflated Sharpe: 0.532 (passes 95%: False) · PBO: 0.56 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=585 · E[R] -0.0351 · Sharpe -0.66

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 857 | +0.0054 | +0.0405 | +0.64 | harmful |
| volatility | 642 | -0.0174 | +0.0178 | +0.23 | review |
| volume | 585 | -0.0310 | +0.0041 | +0.07 | review |
| structure | 510 | -0.0293 | +0.0059 | +0.20 | review |
| momentum | 563 | -0.0239 | +0.0112 | +0.19 | review |
| extension | 523 | -0.0411 | -0.0059 | -0.02 | review |
| timing | 507 | -0.0451 | -0.0099 | -0.11 | keep |
| quality | 518 | -0.0343 | +0.0008 | +0.08 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 472 | +10.44 | +0.53 | 7.61 | 51.7 | +0.0589 | 1.10 |
| random_entry_control | 398 | -15.35 | -0.87 | 18.18 | 45.0 | -0.0610 | 0.84 |
| every_bar_control | 524 | -14.09 | -0.79 | 18.24 | 46.0 | -0.0889 | 0.87 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +27,642 − friction 17,207 = net +10,435 · E[R] +0.0589 · n=472

Entry funnel: 910 signals → 534 fills → 472 positions (fill rate 0.59)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 472 | +10.44 | +0.53 | 7.61 | +0.0589 |
| 0.6 | 333 | +13.73 | +0.81 | 6.85 | +0.0916 |
| 0.75 | 130 | +3.63 | +0.38 | 4.26 | +0.0785 |
| 0.8 | 70 | +3.52 | +0.48 | 2.51 | +0.1110 |
| 0.85 | 25 ⚠️ | +3.72 | +0.96 | 1.84 | +0.2225 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.37 → out-of-sample +0.20 · overfit gap +1.17
deflated Sharpe: 0.233 (passes 95%: False) · PBO: 0.78 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=472 · E[R] +0.0589 · Sharpe +0.53

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 735 | +0.0625 | +0.0036 | -0.02 | review |
| volatility | 528 | +0.0785 | +0.0196 | +0.18 | review |
| volume | 480 | +0.0555 | -0.0034 | -0.04 | decoration |
| structure | 471 | +0.0615 | +0.0027 | +0.04 | decoration |
| momentum | 459 | +0.0476 | -0.0113 | -0.18 | keep |
| extension | 481 | +0.0613 | +0.0024 | +0.05 | decoration |
| timing | 597 | +0.0570 | -0.0018 | -0.13 | keep |
| quality | 485 | +0.0578 | -0.0011 | +0.02 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 219.1M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 389 | -17.57 | -1.10 | 18.05 | 44.5 | -0.0547 | 0.77 |
| random_entry_control | 392 | -17.35 | -1.00 | 18.44 | 42.1 | -0.0867 | 0.80 |
| every_bar_control | 375 | -14.41 | -0.76 | 18.34 | 44.8 | -0.0821 | 0.84 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -3,609 − friction 13,962 = net -17,571 · E[R] -0.0547 · n=389

Entry funnel: 981 signals → 609 fills → 389 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 389 | -17.57 | -1.10 | 18.05 | -0.0547 |
| 0.6 | 387 | +12.91 | +0.70 | 6.90 | +0.0678 |
| 0.75 | 125 | +10.75 | +0.94 | 5.19 | +0.1720 |
| 0.8 | 53 | +0.15 | +0.03 | 5.73 | +0.0660 |
| 0.85 | 12 ⚠️ | +0.59 | +0.30 | 1.04 | +0.2235 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.63 → out-of-sample +0.70 · overfit gap -0.06
deflated Sharpe: 0.413 (passes 95%: False) · PBO: 0.61 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.75`, agrees: True, spikes: [0.6, 0.75])

#### XRPUSDT — filter ablation

baseline: n=389 · E[R] -0.0547 · Sharpe -1.10

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 231 | -0.1313 | -0.0767 | -0.33 | keep |
| volatility | 421 | -0.0425 | +0.0121 | +0.03 | review |
| volume | 397 | -0.0540 | +0.0007 | -0.01 | decoration |
| structure | 382 | -0.0575 | -0.0029 | -0.03 | decoration |
| momentum | 525 | +0.0152 | +0.0698 | +1.05 | harmful |
| extension | 394 | -0.0554 | -0.0007 | -0.01 | decoration |
| timing | 657 | +0.0471 | +0.1017 | +1.46 | harmful |
| quality | 186 | -0.1670 | -0.1123 | -0.47 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 374 | -15.20 | 18.14 | 44.1 | -0.0552 | -1,503 | 13,699 | -15,202 |
| ETHUSDT | 585 | -14.67 | 18.10 | 45.1 | -0.0351 | +6,359 | 21,029 | -14,670 |
| SOLUSDT | 472 | +10.44 | 7.61 | 51.7 | +0.0589 | +27,642 | 17,207 | +10,435 |
| XRPUSDT | 389 | -17.57 | 18.05 | 44.5 | -0.0547 | -3,609 | 13,962 | -17,571 |
| **pooled** | **1820** | — | — | — | **-0.0191** | **+28,889** | **65,897** | **-37,008** |

Signals 4191 → fills 2594 → positions 1820 · accounting errors **0** · friction ÷ gross = 2.28

> ✅ **pooled n = 1820 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 1 of 4 symbols (SOLUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

