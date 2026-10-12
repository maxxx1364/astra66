## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.62s)
OK   vision_archive (0.19s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 381 | -13.26 | -0.78 | 18.33 | 43.6 | -0.0464 | 0.85 |
| random_entry_control | 353 | -16.23 | -1.00 | 18.03 | 39.9 | -0.0869 | 0.80 |
| every_bar_control | 254 | -16.33 | -1.33 | 18.01 | 36.6 | -0.1264 | 0.70 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +1,072 − friction 14,329 = net -13,257 · E[R] -0.0464 · n=381

Entry funnel: 1246 signals → 785 fills → 381 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 381 | -13.26 | -0.78 | 18.33 | -0.0464 |
| 0.6 | 342 | -12.64 | -0.78 | 18.16 | -0.0511 |
| 0.75 | 201 | +8.08 | +0.62 | 6.21 | +0.0747 |
| 0.8 | 119 | +2.85 | +0.30 | 3.97 | +0.0485 |
| 0.85 | 37 | +2.77 | +0.55 | 2.24 | +0.0999 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.90 → out-of-sample -0.20 · overfit gap +1.10
deflated Sharpe: 0.171 (passes 95%: False) · PBO: 0.48 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=381 · E[R] -0.0464 · Sharpe -0.78

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 559 | -0.0298 | +0.0166 | +0.20 | review |
| volatility | 358 | -0.0606 | -0.0142 | -0.08 | keep |
| volume | 389 | -0.0457 | +0.0008 | +0.01 | decoration |
| structure | 365 | -0.0460 | +0.0004 | +0.01 | decoration |
| momentum | 372 | -0.0477 | -0.0013 | +0.00 | decoration |
| extension | 351 | -0.0518 | -0.0054 | -0.02 | review |
| timing | 442 | -0.0443 | +0.0021 | +0.02 | review |
| quality | 393 | -0.0447 | +0.0017 | +0.02 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 974.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 596 | -14.53 | -0.64 | 18.39 | 45.3 | -0.0352 | 0.89 |
| random_entry_control | 759 | -18.01 | -0.67 | 18.01 | 44.7 | -0.0542 | 0.90 |
| every_bar_control | 354 | -16.92 | -1.01 | 18.37 | 41.2 | -0.0921 | 0.80 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +6,948 − friction 21,478 = net -14,530 · E[R] -0.0352 · n=596

Entry funnel: 1103 signals → 691 fills → 596 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 596 | -14.53 | -0.64 | 18.39 | -0.0352 |
| 0.6 | 449 | +8.72 | +0.44 | 11.43 | +0.0336 |
| 0.75 | 217 | -2.62 | -0.16 | 6.61 | +0.0080 |
| 0.8 | 135 | -1.57 | -0.12 | 6.50 | +0.0029 |
| 0.85 | 59 | +2.46 | +0.33 | 4.67 | +0.0873 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.93 → out-of-sample +0.36 · overfit gap +0.57
deflated Sharpe: 0.512 (passes 95%: False) · PBO: 0.67 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=596 · E[R] -0.0352 · Sharpe -0.64

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 880 | +0.0094 | +0.0446 | +0.70 | harmful |
| volatility | 652 | -0.0214 | +0.0138 | +0.17 | review |
| volume | 600 | -0.0337 | +0.0015 | +0.04 | decoration |
| structure | 595 | -0.0285 | +0.0067 | +0.15 | review |
| momentum | 583 | -0.0270 | +0.0083 | +0.15 | review |
| extension | 505 | -0.0416 | -0.0064 | +0.02 | review |
| timing | 525 | -0.0443 | -0.0091 | -0.12 | keep |
| quality | 528 | -0.0397 | -0.0045 | +0.00 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 477 | +12.26 | +0.60 | 7.53 | 52.4 | +0.0644 | 1.12 |
| random_entry_control | 160 | -17.35 | -1.66 | 18.10 | 35.0 | -0.2459 | 0.56 |
| every_bar_control | 419 | -17.48 | -1.17 | 18.07 | 43.4 | -0.1260 | 0.79 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +30,107 − friction 17,850 = net +12,257 · E[R] +0.0644 · n=477

Entry funnel: 935 signals → 542 fills → 477 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 477 | +12.26 | +0.60 | 7.53 | +0.0644 |
| 0.6 | 346 | +12.37 | +0.72 | 5.78 | +0.0772 |
| 0.75 | 138 | +1.58 | +0.17 | 3.77 | +0.0498 |
| 0.8 | 73 | +2.93 | +0.39 | 2.06 | +0.0801 |
| 0.85 | 27 ⚠️ | +4.19 | +1.01 | 1.85 | +0.2269 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.38 → out-of-sample +0.21 · overfit gap +1.17
deflated Sharpe: 0.207 (passes 95%: False) · PBO: 0.73 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [0.8])

#### SOLUSDT — filter ablation

baseline: n=477 · E[R] +0.0644 · Sharpe +0.60

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 750 | +0.0483 | -0.0161 | -0.28 | keep |
| volatility | 536 | +0.0882 | +0.0238 | +0.24 | harmful |
| volume | 486 | +0.0619 | -0.0026 | -0.03 | decoration |
| structure | 479 | +0.0649 | +0.0004 | +0.01 | decoration |
| momentum | 470 | +0.0617 | -0.0028 | -0.09 | keep |
| extension | 487 | +0.0674 | +0.0030 | +0.06 | review |
| timing | 612 | +0.0687 | +0.0043 | +0.03 | review |
| quality | 495 | +0.0580 | -0.0064 | -0.06 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 219.1M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 560 | +3.57 | +0.20 | 14.77 | 47.9 | +0.0290 | 1.03 |
| random_entry_control | 168 | -17.11 | -1.53 | 18.30 | 35.7 | -0.1671 | 0.60 |
| every_bar_control | 263 | -18.19 | -1.21 | 18.19 | 44.1 | -0.1424 | 0.72 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +24,692 − friction 21,126 = net +3,566 · E[R] +0.0290 · n=560

Entry funnel: 996 signals → 626 fills → 560 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 560 | +3.57 | +0.20 | 14.77 | +0.0290 |
| 0.6 | 393 | +14.72 | +0.78 | 5.58 | +0.0727 |
| 0.75 | 131 | +11.43 | +0.97 | 5.19 | +0.1776 |
| 0.8 | 54 | +0.37 | +0.07 | 5.73 | +0.0749 |
| 0.85 | 12 ⚠️ | +0.74 | +0.32 | 1.04 | +0.2287 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.83 → out-of-sample +0.48 · overfit gap +0.35
deflated Sharpe: 0.501 (passes 95%: False) · PBO: 0.72 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=560 · E[R] +0.0290 · Sharpe +0.20

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 209 | -0.1372 | -0.1663 | -1.65 | keep |
| volatility | 597 | +0.0352 | +0.0061 | +0.00 | review |
| volume | 569 | +0.0302 | +0.0011 | +0.03 | decoration |
| structure | 553 | +0.0219 | -0.0072 | -0.11 | keep |
| momentum | 533 | +0.0313 | +0.0022 | +0.01 | decoration |
| extension | 570 | +0.0329 | +0.0038 | +0.05 | decoration |
| timing | 665 | +0.0542 | +0.0252 | +0.32 | harmful |
| quality | 572 | +0.0227 | -0.0064 | -0.10 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 381 | -13.26 | 18.33 | 43.6 | -0.0464 | +1,072 | 14,329 | -13,257 |
| ETHUSDT | 596 | -14.53 | 18.39 | 45.3 | -0.0352 | +6,948 | 21,478 | -14,530 |
| SOLUSDT | 477 | +12.26 | 7.53 | 52.4 | +0.0644 | +30,107 | 17,850 | +12,257 |
| XRPUSDT | 560 | +3.57 | 14.77 | 47.9 | +0.0290 | +24,692 | 21,126 | +3,566 |
| **pooled** | **2014** | — | — | — | **+0.0041** | **+62,818** | **74,782** | **-11,963** |

Signals 4280 → fills 2644 → positions 2014 · accounting errors **0** · friction ÷ gross = 1.19

> ✅ **pooled n = 2014 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

