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
| strategy | 383 | -12.48 | -0.72 | 18.26 | 42.6 | -0.0414 | 0.86 |
| random_entry_control | 429 | -17.25 | -0.99 | 18.37 | 42.2 | -0.0821 | 0.81 |
| every_bar_control | 240 | -17.94 | -1.56 | 18.07 | 37.1 | -0.1483 | 0.64 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +2,156 − friction 14,639 = net -12,483 · E[R] -0.0414 · n=383

Entry funnel: 1279 signals → 795 fills → 383 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 383 | -12.48 | -0.72 | 18.26 | -0.0414 |
| 0.6 | 310 | -13.45 | -0.85 | 18.01 | -0.0604 |
| 0.75 | 219 | +3.90 | +0.31 | 6.03 | +0.0287 |
| 0.8 | 126 | +3.77 | +0.38 | 4.81 | +0.0546 |
| 0.85 | 41 | +4.26 | +0.77 | 1.99 | +0.1545 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.67 → out-of-sample -0.41 · overfit gap +1.08
deflated Sharpe: 0.168 (passes 95%: False) · PBO: 0.42 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=383 · E[R] -0.0414 · Sharpe -0.72

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 658 | -0.0375 | +0.0039 | +0.04 | review |
| volatility | 367 | -0.0603 | -0.0189 | -0.13 | keep |
| volume | 404 | -0.0411 | +0.0003 | +0.01 | review |
| structure | 365 | -0.0441 | -0.0027 | -0.02 | decoration |
| momentum | 355 | -0.0465 | -0.0051 | -0.04 | review |
| extension | 362 | -0.0482 | -0.0068 | -0.04 | review |
| timing | 475 | -0.0395 | +0.0019 | +0.06 | review |
| quality | 396 | -0.0420 | -0.0006 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.0M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 492 | -13.69 | -0.66 | 18.24 | 46.1 | -0.0427 | 0.88 |
| random_entry_control | 400 | -13.88 | -0.74 | 18.09 | 44.8 | -0.0533 | 0.86 |
| every_bar_control | 250 | -18.18 | -1.42 | 18.18 | 38.4 | -0.1424 | 0.68 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross +4,124 − friction 17,817 = net -13,694 · E[R] -0.0427 · n=492

Entry funnel: 1145 signals → 707 fills → 492 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 492 | -13.69 | -0.66 | 18.24 | -0.0427 |
| 0.6 | 469 | +2.25 | +0.14 | 12.34 | +0.0136 |
| 0.75 | 229 | -3.83 | -0.24 | 6.77 | -0.0007 |
| 0.8 | 147 | -2.77 | -0.22 | 8.80 | +0.0002 |
| 0.85 | 65 | +3.38 | +0.43 | 5.00 | +0.1186 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.81 → out-of-sample +0.10 · overfit gap +0.71
deflated Sharpe: 0.251 (passes 95%: False) · PBO: 0.59 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=492 · E[R] -0.0427 · Sharpe -0.66

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 909 | -0.0049 | +0.0379 | +0.50 | harmful |
| volatility | 656 | -0.0289 | +0.0139 | +0.05 | review |
| volume | 498 | -0.0408 | +0.0020 | +0.06 | review |
| structure | 538 | -0.0351 | +0.0077 | +0.10 | review |
| momentum | 586 | -0.0332 | +0.0095 | +0.03 | review |
| extension | 469 | -0.0459 | -0.0031 | -0.04 | decoration |
| timing | 558 | -0.0380 | +0.0047 | -0.02 | review |
| quality | 471 | -0.0419 | +0.0008 | +0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 458.1M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 506 | +7.99 | +0.41 | 11.97 | 52.4 | +0.0590 | 1.07 |
| random_entry_control | 330 | -10.00 | -0.58 | 18.16 | 46.1 | -0.0348 | 0.88 |
| every_bar_control | 188 | -15.56 | -1.41 | 18.10 | 38.8 | -0.1732 | 0.64 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +26,206 − friction 18,216 = net +7,990 · E[R] +0.0590 · n=506

Entry funnel: 998 signals → 578 fills → 506 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 506 | +7.99 | +0.41 | 11.97 | +0.0590 |
| 0.6 | 360 | +15.91 | +0.89 | 5.37 | +0.0969 |
| 0.75 | 156 | +4.88 | +0.45 | 4.55 | +0.0849 |
| 0.8 | 88 | +2.90 | +0.36 | 2.26 | +0.0893 |
| 0.85 | 28 ⚠️ | +5.47 | +1.17 | 1.63 | +0.2849 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.59 → out-of-sample -0.22 · overfit gap +1.81
deflated Sharpe: 0.056 (passes 95%: False) · PBO: 0.52 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [0.6])

#### SOLUSDT — filter ablation

baseline: n=506 · E[R] +0.0590 · Sharpe +0.41

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 484 | +0.0398 | -0.0192 | -0.41 | keep |
| volatility | 579 | +0.0693 | +0.0103 | +0.15 | review |
| volume | 519 | +0.0732 | +0.0141 | +0.21 | review |
| structure | 509 | +0.0725 | +0.0134 | +0.21 | review |
| momentum | 497 | +0.0607 | +0.0016 | +0.09 | review |
| extension | 519 | +0.0629 | +0.0038 | +0.06 | review |
| timing | 656 | +0.0629 | +0.0038 | +0.18 | review |
| quality | 530 | +0.0683 | +0.0092 | +0.15 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 215.5M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 580 | +5.97 | +0.30 | 13.42 | 49.3 | +0.0408 | 1.05 |
| random_entry_control | 279 | -17.34 | -1.22 | 18.15 | 42.3 | -0.1054 | 0.74 |
| every_bar_control | 227 | -17.78 | -1.40 | 18.38 | 39.6 | -0.1576 | 0.65 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +28,560 − friction 22,588 = net +5,972 · E[R] +0.0408 · n=580

Entry funnel: 1027 signals → 647 fills → 580 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 580 | +5.97 | +0.30 | 13.42 | +0.0408 |
| 0.6 | 404 | +17.04 | +0.89 | 6.41 | +0.0873 |
| 0.75 | 128 | +13.56 | +1.15 | 4.71 | +0.2063 |
| 0.8 | 59 | -1.66 | -0.23 | 5.73 | +0.0119 |
| 0.85 | 16 ⚠️ | +1.33 | +0.50 | 1.13 | +0.2857 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.85 → out-of-sample +1.64 · overfit gap -0.79
deflated Sharpe: 0.991 (passes 95%: True) · PBO: 0.41 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=580 · E[R] +0.0408 · Sharpe +0.30

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 228 | -0.1091 | -0.1499 | -1.52 | keep |
| volatility | 613 | +0.0417 | +0.0009 | -0.06 | keep |
| volume | 590 | +0.0431 | +0.0023 | +0.06 | review |
| structure | 575 | +0.0344 | -0.0064 | -0.09 | keep |
| momentum | 557 | +0.0397 | -0.0012 | -0.05 | decoration |
| extension | 589 | +0.0459 | +0.0051 | +0.06 | review |
| timing | 154 | -0.1853 | -0.2261 | -1.98 | keep |
| quality | 596 | +0.0345 | -0.0063 | -0.09 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 383 | -12.48 | 18.26 | 42.6 | -0.0414 | +2,156 | 14,639 | -12,483 |
| ETHUSDT | 492 | -13.69 | 18.24 | 46.1 | -0.0427 | +4,124 | 17,817 | -13,694 |
| SOLUSDT | 506 | +7.99 | 11.97 | 52.4 | +0.0590 | +26,206 | 18,216 | +7,990 |
| XRPUSDT | 580 | +5.97 | 13.42 | 49.3 | +0.0408 | +28,560 | 22,588 | +5,972 |
| **pooled** | **1961** | — | — | — | **+0.0085** | **+61,046** | **73,261** | **-12,215** |

Signals 4449 → fills 2727 → positions 1961 · accounting errors **0** · friction ÷ gross = 1.20

> ✅ **pooled n = 1961 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

