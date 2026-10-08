## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.63s)
OK   vision_archive (0.20s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 380 | -13.59 | -0.80 | 18.16 | 43.2 | -0.0476 | 0.85 |
| random_entry_control | 316 | -17.17 | -1.16 | 18.28 | 39.9 | -0.1078 | 0.74 |
| every_bar_control | 265 | -16.67 | -1.32 | 18.57 | 37.0 | -0.1270 | 0.71 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +673 − friction 14,259 = net -13,585 · E[R] -0.0476 · n=380

Entry funnel: 1256 signals → 792 fills → 380 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 380 | -13.59 | -0.80 | 18.16 | -0.0476 |
| 0.6 | 345 | -12.27 | -0.74 | 18.16 | -0.0483 |
| 0.75 | 203 | +6.25 | +0.49 | 6.21 | +0.0607 |
| 0.8 | 121 | +3.12 | +0.32 | 3.85 | +0.0469 |
| 0.85 | 40 | +4.48 | +0.83 | 2.27 | +0.1774 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.97 → out-of-sample -0.42 · overfit gap +1.38
deflated Sharpe: 0.087 (passes 95%: False) · PBO: 0.52 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=380 · E[R] -0.0476 · Sharpe -0.80

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 594 | -0.0345 | +0.0131 | +0.14 | review |
| volatility | 358 | -0.0661 | -0.0185 | -0.16 | keep |
| volume | 386 | -0.0451 | +0.0025 | +0.02 | decoration |
| structure | 365 | -0.0471 | +0.0005 | -0.00 | decoration |
| momentum | 357 | -0.0531 | -0.0055 | -0.07 | keep |
| extension | 359 | -0.0513 | -0.0036 | -0.02 | review |
| timing | 442 | -0.0448 | +0.0029 | +0.04 | review |
| quality | 391 | -0.0447 | +0.0030 | +0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 544 | -14.80 | -0.68 | 18.11 | 45.4 | -0.0410 | 0.89 |
| random_entry_control | 177 | -16.72 | -1.47 | 18.11 | 38.4 | -0.1670 | 0.63 |
| every_bar_control | 369 | -17.82 | -1.05 | 18.32 | 41.2 | -0.0921 | 0.79 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +4,946 − friction 19,749 = net -14,803 · E[R] -0.0410 · n=544

Entry funnel: 1117 signals → 699 fills → 544 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 544 | -14.80 | -0.68 | 18.11 | -0.0410 |
| 0.6 | 455 | +7.29 | +0.37 | 11.42 | +0.0283 |
| 0.75 | 223 | -1.98 | -0.11 | 7.16 | +0.0090 |
| 0.8 | 139 | -3.88 | -0.32 | 8.27 | -0.0271 |
| 0.85 | 61 | +0.43 | +0.07 | 5.13 | +0.0207 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.86 → out-of-sample +0.36 · overfit gap +0.50
deflated Sharpe: 0.495 (passes 95%: False) · PBO: 0.62 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=544 · E[R] -0.0410 · Sharpe -0.68

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 888 | +0.0167 | +0.0577 | +0.92 | harmful |
| volatility | 655 | -0.0308 | +0.0103 | +0.02 | review |
| volume | 537 | -0.0398 | +0.0012 | +0.03 | decoration |
| structure | 528 | -0.0285 | +0.0126 | +0.25 | review |
| momentum | 585 | -0.0343 | +0.0068 | +0.06 | review |
| extension | 498 | -0.0419 | -0.0008 | +0.03 | review |
| timing | 528 | -0.0369 | +0.0041 | +0.03 | decoration |
| quality | 537 | -0.0397 | +0.0013 | +0.04 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 493 | +8.89 | +0.45 | 9.68 | 51.5 | +0.0465 | 1.08 |
| random_entry_control | 485 | -11.72 | -0.53 | 18.42 | 44.5 | -0.0562 | 0.91 |
| every_bar_control | 360 | -16.05 | -1.12 | 18.21 | 44.2 | -0.1227 | 0.78 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +26,738 − friction 17,846 = net +8,892 · E[R] +0.0465 · n=493

Entry funnel: 961 signals → 559 fills → 493 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 493 | +8.89 | +0.45 | 9.68 | +0.0465 |
| 0.6 | 349 | +13.86 | +0.80 | 5.78 | +0.0779 |
| 0.75 | 139 | +4.87 | +0.49 | 2.79 | +0.0885 |
| 0.8 | 79 | +4.13 | +0.54 | 2.35 | +0.1105 |
| 0.85 | 27 ⚠️ | +3.81 | +0.93 | 1.85 | +0.1960 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.33 → out-of-sample +0.08 · overfit gap +1.25
deflated Sharpe: 0.109 (passes 95%: False) · PBO: 0.92 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=493 · E[R] +0.0465 · Sharpe +0.45

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 669 | +0.0207 | -0.0258 | -0.59 | keep |
| volatility | 556 | +0.0650 | +0.0186 | +0.19 | review |
| volume | 504 | +0.0433 | -0.0032 | -0.02 | decoration |
| structure | 495 | +0.0473 | +0.0008 | +0.04 | decoration |
| momentum | 484 | +0.0433 | -0.0032 | -0.07 | keep |
| extension | 504 | +0.0475 | +0.0010 | +0.04 | decoration |
| timing | 626 | +0.0695 | +0.0230 | +0.21 | harmful |
| quality | 512 | +0.0405 | -0.0060 | -0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 219.1M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 565 | +3.99 | +0.22 | 15.32 | 48.3 | +0.0322 | 1.04 |
| random_entry_control | 244 | -17.46 | -1.27 | 18.45 | 44.7 | -0.1304 | 0.69 |
| every_bar_control | 265 | -17.78 | -1.17 | 18.19 | 44.5 | -0.1342 | 0.73 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +25,077 − friction 21,083 = net +3,994 · E[R] +0.0322 · n=565

Entry funnel: 1008 signals → 631 fills → 565 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 565 | +3.99 | +0.22 | 15.32 | +0.0322 |
| 0.6 | 394 | +16.38 | +0.86 | 5.96 | +0.0789 |
| 0.75 | 128 | +10.87 | +0.95 | 5.19 | +0.1665 |
| 0.8 | 56 | -0.38 | -0.04 | 5.73 | +0.0365 |
| 0.85 | 14 ⚠️ | +1.04 | +0.41 | 1.06 | +0.2329 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.57 → out-of-sample +0.99 · overfit gap -0.43
deflated Sharpe: 0.698 (passes 95%: False) · PBO: 0.48 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=565 · E[R] +0.0322 · Sharpe +0.22

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 196 | -0.1388 | -0.1710 | -1.70 | keep |
| volatility | 599 | +0.0353 | +0.0031 | -0.01 | review |
| volume | 572 | +0.0348 | +0.0025 | +0.05 | decoration |
| structure | 555 | +0.0273 | -0.0049 | -0.08 | keep |
| momentum | 535 | +0.0390 | +0.0068 | +0.09 | review |
| extension | 577 | +0.0369 | +0.0047 | +0.06 | review |
| timing | 157 | -0.1857 | -0.2179 | -1.95 | keep |
| quality | 576 | +0.0283 | -0.0039 | -0.07 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 380 | -13.59 | 18.16 | 43.2 | -0.0476 | +673 | 14,259 | -13,585 |
| ETHUSDT | 544 | -14.80 | 18.11 | 45.4 | -0.0410 | +4,946 | 19,749 | -14,803 |
| SOLUSDT | 493 | +8.89 | 9.68 | 51.5 | +0.0465 | +26,738 | 17,846 | +8,892 |
| XRPUSDT | 565 | +3.99 | 15.32 | 48.3 | +0.0322 | +25,077 | 21,083 | +3,994 |
| **pooled** | **1982** | — | — | — | **+0.0004** | **+57,434** | **72,937** | **-15,503** |

Signals 4342 → fills 2681 → positions 1982 · accounting errors **0** · friction ÷ gross = 1.27

> ✅ **pooled n = 1982 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

