## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.87s)
OK   vision_archive (0.46s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 389 | -11.72 | -0.66 | 18.22 | 43.2 | -0.0358 | 0.87 |
| random_entry_control | 165 | -17.29 | -1.84 | 18.12 | 33.9 | -0.2054 | 0.54 |
| every_bar_control | 226 | -17.66 | -1.59 | 18.01 | 37.2 | -0.1535 | 0.62 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +3,214 − friction 14,935 = net -11,721 · E[R] -0.0358 · n=389

Entry funnel: 1293 signals → 803 fills → 389 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 389 | -11.72 | -0.66 | 18.22 | -0.0358 |
| 0.6 | 272 | -12.38 | -0.84 | 18.23 | -0.0590 |
| 0.75 | 220 | +2.45 | +0.20 | 6.55 | +0.0180 |
| 0.8 | 128 | +4.61 | +0.46 | 4.67 | +0.0622 |
| 0.85 | 42 | +3.82 | +0.69 | 1.99 | +0.1348 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.70 → out-of-sample -0.72 · overfit gap +1.43
deflated Sharpe: 0.058 (passes 95%: False) · PBO: 0.45 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=389 · E[R] -0.0358 · Sharpe -0.66

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 662 | -0.0383 | -0.0025 | -0.07 | keep |
| volatility | 368 | -0.0502 | -0.0143 | -0.09 | keep |
| volume | 412 | -0.0349 | +0.0010 | +0.02 | review |
| structure | 366 | -0.0394 | -0.0035 | -0.03 | review |
| momentum | 354 | -0.0423 | -0.0065 | -0.05 | review |
| extension | 369 | -0.0443 | -0.0084 | -0.07 | keep |
| timing | 478 | -0.0361 | -0.0003 | +0.03 | review |
| quality | 403 | -0.0385 | -0.0027 | -0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.0M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 463 | -11.91 | -0.59 | 18.15 | 46.4 | -0.0392 | 0.89 |
| random_entry_control | 213 | -18.41 | -1.55 | 18.41 | 40.4 | -0.1738 | 0.62 |
| every_bar_control | 228 | -18.05 | -1.51 | 18.41 | 38.2 | -0.1480 | 0.66 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +4,968 − friction 16,879 = net -11,912 · E[R] -0.0392 · n=463

Entry funnel: 1150 signals → 713 fills → 463 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 463 | -11.91 | -0.59 | 18.15 | -0.0392 |
| 0.6 | 471 | +0.08 | +0.04 | 12.32 | +0.0060 |
| 0.75 | 237 | -3.77 | -0.23 | 6.98 | -0.0027 |
| 0.8 | 151 | -3.24 | -0.25 | 9.05 | -0.0043 |
| 0.85 | 63 | +2.40 | +0.31 | 4.98 | +0.0897 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.56 → out-of-sample +0.05 · overfit gap +0.51
deflated Sharpe: 0.294 (passes 95%: False) · PBO: 0.66 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=463 · E[R] -0.0392 · Sharpe -0.59

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 911 | -0.0116 | +0.0276 | +0.27 | harmful |
| volatility | 598 | -0.0298 | +0.0093 | +0.05 | review |
| volume | 472 | -0.0362 | +0.0030 | +0.07 | review |
| structure | 497 | -0.0324 | +0.0068 | +0.11 | review |
| momentum | 533 | -0.0352 | +0.0040 | -0.03 | review |
| extension | 465 | -0.0393 | -0.0001 | -0.01 | decoration |
| timing | 557 | -0.0374 | +0.0018 | -0.09 | keep |
| quality | 466 | -0.0343 | +0.0049 | +0.07 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 457.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 512 | +7.03 | +0.36 | 13.56 | 51.8 | +0.0511 | 1.06 |
| random_entry_control | 704 | -16.66 | -0.63 | 18.06 | 45.7 | -0.0401 | 0.90 |
| every_bar_control | 195 | -15.09 | -1.32 | 18.11 | 39.0 | -0.1675 | 0.67 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +25,527 − friction 18,496 = net +7,031 · E[R] +0.0511 · n=512

Entry funnel: 1009 signals → 586 fills → 512 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 512 | +7.03 | +0.36 | 13.56 | +0.0511 |
| 0.6 | 366 | +18.20 | +0.99 | 5.38 | +0.1030 |
| 0.75 | 160 | +8.37 | +0.73 | 3.98 | +0.1239 |
| 0.8 | 92 | +4.91 | +0.59 | 2.26 | +0.1321 |
| 0.85 | 29 ⚠️ | +6.45 | +1.39 | 1.40 | +0.3538 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.88 → out-of-sample -0.08 · overfit gap +1.96
deflated Sharpe: 0.073 (passes 95%: False) · PBO: 0.39 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=512 · E[R] +0.0511 · Sharpe +0.36

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 502 | +0.0427 | -0.0084 | -0.29 | keep |
| volatility | 588 | +0.0673 | +0.0162 | +0.19 | review |
| volume | 527 | +0.0578 | +0.0066 | +0.13 | review |
| structure | 518 | +0.0605 | +0.0094 | +0.18 | review |
| momentum | 503 | +0.0573 | +0.0062 | +0.14 | review |
| extension | 524 | +0.0601 | +0.0089 | +0.13 | review |
| timing | 659 | +0.0639 | +0.0128 | +0.24 | review |
| quality | 538 | +0.0503 | -0.0008 | +0.05 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 215.2M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 587 | +8.66 | +0.41 | 13.78 | 49.6 | +0.0489 | 1.08 |
| random_entry_control | 230 | -17.56 | -1.29 | 18.23 | 37.8 | -0.1335 | 0.69 |
| every_bar_control | 233 | -16.52 | -1.26 | 18.12 | 41.2 | -0.1320 | 0.68 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +32,072 − friction 23,410 = net +8,662 · E[R] +0.0489 · n=587

Entry funnel: 1042 signals → 658 fills → 587 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 587 | +8.66 | +0.41 | 13.78 | +0.0489 |
| 0.6 | 412 | +14.82 | +0.78 | 5.98 | +0.0792 |
| 0.75 | 134 | +14.33 | +1.18 | 4.71 | +0.2058 |
| 0.8 | 59 | -1.92 | -0.27 | 5.73 | +0.0014 |
| 0.85 | 15 ⚠️ | +0.77 | +0.31 | 1.10 | +0.2127 |

plateau pick: `0.6` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.62 → out-of-sample +1.17 · overfit gap -0.55
deflated Sharpe: 0.822 (passes 95%: False) · PBO: 0.34 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=587 · E[R] +0.0489 · Sharpe +0.41

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 837 | +0.0148 | -0.0341 | -0.44 | keep |
| volatility | 623 | +0.0453 | -0.0036 | -0.13 | keep |
| volume | 597 | +0.0478 | -0.0010 | +0.00 | decoration |
| structure | 583 | +0.0379 | -0.0109 | -0.15 | keep |
| momentum | 561 | +0.0396 | -0.0093 | -0.20 | keep |
| extension | 596 | +0.0538 | +0.0049 | +0.06 | review |
| timing | 687 | +0.0491 | +0.0003 | -0.00 | review |
| quality | 603 | +0.0389 | -0.0100 | -0.15 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 389 | -11.72 | 18.22 | 43.2 | -0.0358 | +3,214 | 14,935 | -11,721 |
| ETHUSDT | 463 | -11.91 | 18.15 | 46.4 | -0.0392 | +4,968 | 16,879 | -11,912 |
| SOLUSDT | 512 | +7.03 | 13.56 | 51.8 | +0.0511 | +25,527 | 18,496 | +7,031 |
| XRPUSDT | 587 | +8.66 | 13.78 | 49.6 | +0.0489 | +32,072 | 23,410 | +8,662 |
| **pooled** | **1951** | — | — | — | **+0.0117** | **+65,781** | **73,721** | **-7,940** |

Signals 4494 → fills 2760 → positions 1951 · accounting errors **0** · friction ÷ gross = 1.12

> ✅ **pooled n = 1951 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

