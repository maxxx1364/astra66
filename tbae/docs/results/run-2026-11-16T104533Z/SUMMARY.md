## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.43s)
OK   vision_archive (0.37s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 386 | -17.15 | -1.08 | 18.33 | 42.2 | -0.0655 | 0.79 |
| random_entry_control | 236 | -17.73 | -1.52 | 18.02 | 35.2 | -0.1251 | 0.64 |
| every_bar_control | 265 | -14.06 | -1.08 | 18.15 | 39.2 | -0.0814 | 0.75 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -8,196 − friction 8,950 = net -17,147 · E[R] -0.0655 · n=386

Entry funnel: 1161 signals → 730 fills → 386 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 386 | -17.15 | -1.08 | 18.33 | -0.0655 |
| 0.6 | 431 | -13.55 | -0.77 | 17.03 | -0.0449 |
| 0.75 | 186 | +6.24 | +0.52 | 5.71 | +0.0554 |
| 0.8 | 106 | +2.72 | +0.31 | 4.31 | +0.0428 |
| 0.85 | 37 | +2.21 | +0.43 | 1.95 | +0.0760 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.51 → out-of-sample -0.21 · overfit gap +0.72
deflated Sharpe: 0.234 (passes 95%: False) · PBO: 0.80 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=386 · E[R] -0.0655 · Sharpe -1.08

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 588 | -0.0432 | +0.0222 | +0.29 | harmful |
| volatility | 413 | -0.0645 | +0.0010 | +0.06 | review |
| volume | 382 | -0.0649 | +0.0006 | +0.01 | decoration |
| structure | 381 | -0.0656 | -0.0001 | +0.01 | decoration |
| momentum | 371 | -0.0620 | +0.0035 | +0.08 | review |
| extension | 389 | -0.0639 | +0.0015 | +0.02 | decoration |
| timing | 492 | -0.0484 | +0.0171 | +0.16 | review |
| quality | 388 | -0.0648 | +0.0007 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 971.9M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 560 | -15.83 | -0.75 | 15.97 | 44.5 | -0.0432 | 0.87 |
| random_entry_control | 308 | -17.64 | -1.22 | 18.15 | 41.9 | -0.1014 | 0.73 |
| every_bar_control | 1093 | -15.53 | -0.49 | 18.09 | 44.9 | -0.0294 | 0.93 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -935 − friction 14,897 = net -15,833 · E[R] -0.0432 · n=560

Entry funnel: 1025 signals → 638 fills → 560 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 560 | -15.83 | -0.75 | 15.97 | -0.0432 |
| 0.6 | 420 | -2.98 | -0.12 | 11.21 | -0.0045 |
| 0.75 | 196 | -3.33 | -0.23 | 8.57 | -0.0046 |
| 0.8 | 122 | -2.92 | -0.26 | 9.55 | -0.0229 |
| 0.85 | 52 | +1.97 | +0.29 | 4.47 | +0.0832 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.04 → out-of-sample -0.31 · overfit gap +0.35
deflated Sharpe: 0.050 (passes 95%: False) · PBO: 0.59 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=560 · E[R] -0.0432 · Sharpe -0.75

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 815 | -0.0035 | +0.0396 | +0.54 | harmful |
| volatility | 614 | -0.0204 | +0.0227 | +0.35 | harmful |
| volume | 564 | -0.0428 | +0.0003 | -0.02 | decoration |
| structure | 564 | -0.0409 | +0.0023 | +0.04 | decoration |
| momentum | 542 | -0.0326 | +0.0106 | +0.20 | review |
| extension | 574 | -0.0484 | -0.0052 | -0.10 | keep |
| timing | 645 | -0.0363 | +0.0069 | +0.07 | review |
| quality | 566 | -0.0447 | -0.0016 | -0.06 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 452.9M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 459 | +6.15 | +0.33 | 6.68 | 51.9 | +0.0505 | 1.06 |
| random_entry_control | 268 | -17.39 | -1.23 | 18.05 | 43.3 | -0.1250 | 0.71 |
| every_bar_control | 447 | -17.34 | -0.97 | 18.14 | 44.7 | -0.1126 | 0.82 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +20,799 − friction 14,652 = net +6,147 · E[R] +0.0505 · n=459

Entry funnel: 872 signals → 519 fills → 459 positions (fill rate 0.60)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 459 | +6.15 | +0.33 | 6.68 | +0.0505 |
| 0.6 | 317 | +10.04 | +0.61 | 8.25 | +0.0780 |
| 0.75 | 123 | +2.65 | +0.29 | 3.26 | +0.0722 |
| 0.8 | 71 | +5.14 | +0.69 | 1.74 | +0.1502 |
| 0.85 | 28 ⚠️ | +6.26 | +1.40 | 1.08 | +0.3868 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.70 → out-of-sample +0.26 · overfit gap +1.44
deflated Sharpe: 0.407 (passes 95%: False) · PBO: 0.28 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [0.8])

#### SOLUSDT — filter ablation

baseline: n=459 · E[R] +0.0505 · Sharpe +0.33

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 702 | +0.0567 | +0.0062 | -0.01 | review |
| volatility | 518 | +0.0602 | +0.0097 | +0.07 | review |
| volume | 461 | +0.0507 | +0.0002 | -0.00 | decoration |
| structure | 453 | +0.0550 | +0.0045 | +0.05 | review |
| momentum | 440 | +0.0447 | -0.0058 | -0.14 | keep |
| extension | 468 | +0.0514 | +0.0009 | +0.05 | review |
| timing | 558 | +0.0629 | +0.0124 | +0.10 | review |
| quality | 465 | +0.0505 | -0.0000 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 209.2M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 536 | +1.57 | +0.11 | 15.71 | 47.8 | +0.0238 | 1.02 |
| random_entry_control | 321 | -15.91 | -1.07 | 18.33 | 41.4 | -0.1131 | 0.78 |
| every_bar_control | 298 | -17.68 | -1.14 | 18.40 | 42.6 | -0.0917 | 0.74 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +18,689 − friction 17,116 = net +1,573 · E[R] +0.0238 · n=536

Entry funnel: 952 signals → 598 fills → 536 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 536 | +1.57 | +0.11 | 15.71 | +0.0238 |
| 0.6 | 370 | +8.64 | +0.50 | 7.98 | +0.0517 |
| 0.75 | 126 | +7.66 | +0.67 | 5.09 | +0.1260 |
| 0.8 | 54 | +0.16 | +0.03 | 3.46 | +0.0500 |
| 0.85 | 17 ⚠️ | +0.71 | +0.23 | 1.62 | +0.1412 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.56 → out-of-sample +0.34 · overfit gap +0.22
deflated Sharpe: 0.362 (passes 95%: False) · PBO: 0.80 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=536 · E[R] +0.0238 · Sharpe +0.11

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 776 | +0.0178 | -0.0059 | -0.09 | keep |
| volatility | 566 | +0.0411 | +0.0173 | +0.18 | review |
| volume | 546 | +0.0298 | +0.0060 | +0.10 | review |
| structure | 528 | +0.0200 | -0.0038 | -0.07 | keep |
| momentum | 504 | +0.0241 | +0.0003 | +0.02 | review |
| extension | 548 | +0.0264 | +0.0026 | +0.02 | decoration |
| timing | 642 | +0.0607 | +0.0369 | +0.52 | harmful |
| quality | 547 | +0.0238 | +0.0001 | +0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 386 | -17.15 | 18.33 | 42.2 | -0.0655 | -8,196 | 8,950 | -17,147 |
| ETHUSDT | 560 | -15.83 | 15.97 | 44.5 | -0.0432 | -935 | 14,897 | -15,833 |
| SOLUSDT | 459 | +6.15 | 6.68 | 51.9 | +0.0505 | +20,799 | 14,652 | +6,147 |
| XRPUSDT | 536 | +1.57 | 15.71 | 47.8 | +0.0238 | +18,689 | 17,116 | +1,573 |
| **pooled** | **1941** | — | — | — | **-0.0070** | **+30,357** | **55,616** | **-25,259** |

Signals 4010 → fills 2485 → positions 1941 · accounting errors **0** · friction ÷ gross = 1.83

> ✅ **pooled n = 1941 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

