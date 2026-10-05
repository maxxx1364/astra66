## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.60s)
OK   vision_archive (0.36s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 378 | -13.53 | -0.79 | 18.04 | 42.6 | -0.0471 | 0.84 |
| random_entry_control | 172 | -18.04 | -1.73 | 18.07 | 33.7 | -0.2128 | 0.59 |
| every_bar_control | 272 | -17.92 | -1.41 | 18.09 | 35.7 | -0.1385 | 0.70 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +570 − friction 14,103 = net -13,533 · E[R] -0.0471 · n=378

Entry funnel: 1271 signals → 797 fills → 378 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 378 | -13.53 | -0.79 | 18.04 | -0.0471 |
| 0.6 | 352 | -13.09 | -0.79 | 18.16 | -0.0535 |
| 0.75 | 207 | +6.38 | +0.49 | 6.04 | +0.0574 |
| 0.8 | 118 | +3.46 | +0.36 | 5.08 | +0.0569 |
| 0.85 | 41 | +4.28 | +0.78 | 2.27 | +0.1626 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.86 → out-of-sample -0.54 · overfit gap +1.40
deflated Sharpe: 0.095 (passes 95%: False) · PBO: 0.50 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### BTCUSDT — filter ablation

baseline: n=378 · E[R] -0.0471 · Sharpe -0.79

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 566 | -0.0320 | +0.0151 | +0.20 | review |
| volatility | 360 | -0.0635 | -0.0164 | -0.10 | keep |
| volume | 385 | -0.0468 | +0.0003 | -0.01 | decoration |
| structure | 350 | -0.0534 | -0.0062 | -0.06 | keep |
| momentum | 368 | -0.0512 | -0.0041 | -0.05 | decoration |
| extension | 359 | -0.0543 | -0.0071 | -0.05 | keep |
| timing | 448 | -0.0424 | +0.0047 | +0.07 | review |
| quality | 389 | -0.0458 | +0.0014 | +0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 972.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 526 | -14.20 | -0.66 | 18.23 | 45.8 | -0.0410 | 0.89 |
| random_entry_control | 213 | -17.43 | -1.33 | 18.35 | 37.1 | -0.1552 | 0.67 |
| every_bar_control | 335 | -17.86 | -1.11 | 18.03 | 40.3 | -0.1000 | 0.77 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +4,776 − friction 18,978 = net -14,202 · E[R] -0.0410 · n=526

Entry funnel: 1128 signals → 706 fills → 526 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 526 | -14.20 | -0.66 | 18.23 | -0.0410 |
| 0.6 | 457 | +4.62 | +0.25 | 11.39 | +0.0206 |
| 0.75 | 226 | -1.89 | -0.10 | 6.22 | +0.0099 |
| 0.8 | 138 | -2.50 | -0.20 | 7.98 | -0.0065 |
| 0.85 | 64 | +1.38 | +0.18 | 4.87 | +0.0540 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.55 → out-of-sample +0.28 · overfit gap +0.27
deflated Sharpe: 0.403 (passes 95%: False) · PBO: 0.80 — high: the configuration search was fitting noise — discard the best-in-sample pick

#### ETHUSDT — filter ablation

baseline: n=526 · E[R] -0.0410 · Sharpe -0.66

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 888 | +0.0052 | +0.0461 | +0.64 | harmful |
| volatility | 652 | -0.0313 | +0.0097 | +0.00 | review |
| volume | 504 | -0.0447 | -0.0037 | +0.00 | decoration |
| structure | 604 | -0.0305 | +0.0105 | +0.12 | review |
| momentum | 582 | -0.0347 | +0.0063 | +0.03 | review |
| extension | 463 | -0.0420 | -0.0011 | +0.03 | review |
| timing | 530 | -0.0383 | +0.0027 | -0.01 | decoration |
| quality | 495 | -0.0431 | -0.0021 | +0.00 | review |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 459.2M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 505 | +13.30 | +0.64 | 8.36 | 52.3 | +0.0668 | 1.12 |
| random_entry_control | 195 | -15.33 | -1.32 | 18.29 | 44.1 | -0.1443 | 0.69 |
| every_bar_control | 329 | -18.11 | -1.35 | 18.11 | 41.9 | -0.1532 | 0.73 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +31,835 − friction 18,534 = net +13,300 · E[R] +0.0668 · n=505

Entry funnel: 981 signals → 569 fills → 505 positions (fill rate 0.58)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 505 | +13.30 | +0.64 | 8.36 | +0.0668 |
| 0.6 | 360 | +16.64 | +0.92 | 5.78 | +0.0917 |
| 0.75 | 146 | +7.41 | +0.69 | 2.80 | +0.1155 |
| 0.8 | 82 | +5.55 | +0.70 | 2.05 | +0.1494 |
| 0.85 | 28 ⚠️ | +3.56 | +0.85 | 1.85 | +0.1603 |

plateau pick: `0.75` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.41 → out-of-sample +0.27 · overfit gap +1.14
deflated Sharpe: 0.144 (passes 95%: False) · PBO: 0.97 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.6`, agrees: False, spikes: [])

#### SOLUSDT — filter ablation

baseline: n=505 · E[R] +0.0668 · Sharpe +0.64

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 763 | +0.0418 | -0.0251 | -0.37 | keep |
| volatility | 570 | +0.0840 | +0.0172 | +0.18 | review |
| volume | 517 | +0.0666 | -0.0002 | +0.00 | decoration |
| structure | 507 | +0.0701 | +0.0033 | +0.06 | review |
| momentum | 495 | +0.0680 | +0.0011 | -0.03 | decoration |
| extension | 515 | +0.0684 | +0.0016 | +0.04 | decoration |
| timing | 637 | +0.0679 | +0.0011 | +0.01 | review |
| quality | 524 | +0.0645 | -0.0023 | -0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 218.8M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 570 | +5.16 | +0.27 | 14.85 | 48.4 | +0.0345 | 1.05 |
| random_entry_control | 266 | -16.69 | -1.16 | 18.25 | 42.1 | -0.1198 | 0.72 |
| every_bar_control | 273 | -17.93 | -1.17 | 18.16 | 44.0 | -0.1342 | 0.73 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +26,575 − friction 21,416 = net +5,159 · E[R] +0.0345 · n=570

Entry funnel: 1008 signals → 638 fills → 570 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 570 | +5.16 | +0.27 | 14.85 | +0.0345 |
| 0.6 | 398 | +14.81 | +0.79 | 6.39 | +0.0746 |
| 0.75 | 129 | +12.80 | +1.10 | 5.19 | +0.1890 |
| 0.8 | 54 | -0.28 | -0.03 | 5.73 | +0.0456 |
| 0.85 | 13 ⚠️ | +0.96 | +0.39 | 1.06 | +0.2673 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.70 → out-of-sample +1.30 · overfit gap -0.60
deflated Sharpe: 0.883 (passes 95%: False) · PBO: 0.44 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [0.75])

#### XRPUSDT — filter ablation

baseline: n=570 · E[R] +0.0345 · Sharpe +0.27

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 824 | +0.0106 | -0.0239 | -0.39 | keep |
| volatility | 608 | +0.0436 | +0.0091 | +0.07 | review |
| volume | 578 | +0.0360 | +0.0015 | +0.03 | decoration |
| structure | 560 | +0.0301 | -0.0044 | -0.07 | keep |
| momentum | 538 | +0.0396 | +0.0051 | +0.05 | review |
| extension | 580 | +0.0388 | +0.0043 | +0.05 | review |
| timing | 160 | -0.1794 | -0.2139 | -1.98 | keep |
| quality | 582 | +0.0295 | -0.0050 | -0.08 | keep |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 378 | -13.53 | 18.04 | 42.6 | -0.0471 | +570 | 14,103 | -13,533 |
| ETHUSDT | 526 | -14.20 | 18.23 | 45.8 | -0.0410 | +4,776 | 18,978 | -14,202 |
| SOLUSDT | 505 | +13.30 | 8.36 | 52.3 | +0.0668 | +31,835 | 18,534 | +13,300 |
| XRPUSDT | 570 | +5.16 | 14.85 | 48.4 | +0.0345 | +26,575 | 21,416 | +5,159 |
| **pooled** | **1979** | — | — | — | **+0.0071** | **+63,756** | **73,031** | **-9,275** |

Signals 4388 → fills 2710 → positions 1979 · accounting errors **0** · friction ÷ gross = 1.15

> ✅ **pooled n = 1979 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

