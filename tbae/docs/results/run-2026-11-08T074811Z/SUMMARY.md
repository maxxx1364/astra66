## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.75s)
OK   vision_archive (0.64s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.6B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 351 | -17.27 | -1.09 | 18.23 | 42.7 | -0.0701 | 0.78 |
| random_entry_control | 214 | -14.55 | -1.19 | 18.01 | 38.3 | -0.1103 | 0.71 |
| every_bar_control | 210 | -18.00 | -1.65 | 18.08 | 34.8 | -0.1628 | 0.63 |

**verdict:** `exit_logic_dominates_entry_is_decoration`

Decomposition (cash): gross -4,934 − friction 12,335 = net -17,269 · E[R] -0.0701 · n=351

Entry funnel: 1182 signals → 738 fills → 351 positions (fill rate 0.62)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 351 | -17.27 | -1.09 | 18.23 | -0.0701 |
| 0.6 | 306 | -16.98 | -1.15 | 18.21 | -0.0864 |
| 0.75 | 186 | +1.33 | +0.13 | 5.75 | +0.0148 |
| 0.8 | 111 | +1.36 | +0.16 | 4.39 | +0.0180 |
| 0.85 | 35 | +2.13 | +0.43 | 1.93 | +0.0663 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.16 → out-of-sample -0.86 · overfit gap +1.02
deflated Sharpe: 0.037 (passes 95%: False) · PBO: 0.48 — elevated: a meaningful share of the ranking is selection noise

#### BTCUSDT — filter ablation

baseline: n=351 · E[R] -0.0701 · Sharpe -1.09

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 376 | -0.0745 | -0.0044 | +0.03 | review |
| volatility | 360 | -0.0694 | +0.0006 | +0.06 | review |
| volume | 346 | -0.0708 | -0.0007 | +0.01 | decoration |
| structure | 334 | -0.0706 | -0.0006 | -0.01 | decoration |
| momentum | 336 | -0.0677 | +0.0024 | +0.07 | review |
| extension | 318 | -0.0798 | -0.0097 | -0.07 | keep |
| timing | 404 | -0.0562 | +0.0139 | +0.16 | review |
| quality | 348 | -0.0700 | +0.0001 | +0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### ETHUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 974.3M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 456 | -17.21 | -0.89 | 18.34 | 43.4 | -0.0601 | 0.84 |
| random_entry_control | 155 | -17.91 | -1.68 | 18.06 | 38.7 | -0.1875 | 0.57 |
| every_bar_control | 428 | -18.03 | -0.98 | 18.06 | 42.8 | -0.0772 | 0.81 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -1,866 − friction 15,344 = net -17,210 · E[R] -0.0601 · n=456

Entry funnel: 1031 signals → 647 fills → 456 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### ETHUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 456 | -17.21 | -0.89 | 18.34 | -0.0601 |
| 0.6 | 419 | -0.93 | -0.01 | 10.90 | +0.0012 |
| 0.75 | 193 | -5.21 | -0.37 | 8.65 | -0.0195 |
| 0.8 | 124 | -3.37 | -0.29 | 8.78 | -0.0311 |
| 0.85 | 49 | +3.25 | +0.46 | 3.73 | +0.1113 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.22 → out-of-sample -0.01 · overfit gap +0.23
deflated Sharpe: 0.145 (passes 95%: False) · PBO: 0.34 — elevated: a meaningful share of the ranking is selection noise

#### ETHUSDT — filter ablation

baseline: n=456 · E[R] -0.0601 · Sharpe -0.89

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 829 | +0.0047 | +0.0648 | +0.87 | harmful |
| volatility | 621 | -0.0296 | +0.0305 | +0.28 | harmful |
| volume | 459 | -0.0600 | +0.0001 | -0.02 | decoration |
| structure | 485 | -0.0548 | +0.0053 | +0.02 | review |
| momentum | 540 | -0.0401 | +0.0200 | +0.18 | harmful |
| extension | 414 | -0.0657 | -0.0056 | -0.06 | keep |
| timing | 518 | -0.0504 | +0.0096 | +0.03 | review |
| quality | 437 | -0.0610 | -0.0009 | -0.04 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### SOLUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 458.1M (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 460 | +4.68 | +0.26 | 7.33 | 50.9 | +0.0395 | 1.05 |
| random_entry_control | 311 | -16.78 | -1.05 | 18.06 | 44.1 | -0.0865 | 0.78 |
| every_bar_control | 454 | -14.00 | -0.76 | 18.15 | 46.7 | -0.0871 | 0.86 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +20,995 − friction 16,316 = net +4,679 · E[R] +0.0395 · n=460

Entry funnel: 853 signals → 516 fills → 460 positions (fill rate 0.60)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### SOLUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 460 | +4.68 | +0.26 | 7.33 | +0.0395 |
| 0.6 | 310 | +10.16 | +0.62 | 8.52 | +0.0717 |
| 0.75 | 118 | +2.13 | +0.23 | 3.26 | +0.0584 |
| 0.8 | 66 | +4.63 | +0.63 | 1.85 | +0.1581 |
| 0.85 | 25 ⚠️ | +5.80 | +1.42 | 1.09 | +0.4071 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +1.65 → out-of-sample +1.31 · overfit gap +0.34
deflated Sharpe: 0.967 (passes 95%: True) · PBO: 0.23 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.75`** (best single point `0.8`, agrees: False, spikes: [0.6, 0.8])

#### SOLUSDT — filter ablation

baseline: n=460 · E[R] +0.0395 · Sharpe +0.26

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 690 | +0.0479 | +0.0085 | -0.03 | review |
| volatility | 520 | +0.0555 | +0.0160 | +0.21 | review |
| volume | 461 | +0.0364 | -0.0030 | -0.04 | decoration |
| structure | 451 | +0.0426 | +0.0031 | +0.04 | decoration |
| momentum | 440 | +0.0308 | -0.0087 | -0.14 | keep |
| extension | 471 | +0.0397 | +0.0002 | +0.03 | decoration |
| timing | 558 | +0.0448 | +0.0053 | +0.00 | review |
| quality | 464 | +0.0373 | -0.0022 | -0.01 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### XRPUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 213.7M (measured) · tick 0.0001

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 532 | +1.30 | +0.10 | 15.78 | 48.3 | +0.0220 | 1.01 |
| random_entry_control | 230 | -18.19 | -1.39 | 18.19 | 41.3 | -0.1400 | 0.67 |
| every_bar_control | 162 | -17.13 | -1.50 | 18.57 | 43.2 | -0.1832 | 0.61 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross +21,199 − friction 19,902 = net +1,297 · E[R] +0.0220 · n=532

Entry funnel: 941 signals → 591 fills → 532 positions (fill rate 0.63)

Accounting errors: **0** (net == gross − costs holds on every trade)

#### XRPUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 532 | +1.30 | +0.10 | 15.78 | +0.0220 |
| 0.6 | 364 | +13.29 | +0.74 | 5.85 | +0.0669 |
| 0.75 | 121 | +8.42 | +0.75 | 5.18 | +0.1355 |
| 0.8 | 52 | +0.40 | +0.07 | 5.60 | +0.0762 |
| 0.85 | 18 ⚠️ | +1.22 | +0.38 | 1.64 | +0.2097 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.88 → out-of-sample +0.66 · overfit gap +0.22
deflated Sharpe: 0.709 (passes 95%: False) · PBO: 0.72 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **1 of 5 grid points have n < 30** (0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> **plateau pick over the 4 grid points with n ≥ 30: `0.6`** (best single point `0.75`, agrees: False, spikes: [])

#### XRPUSDT — filter ablation

baseline: n=532 · E[R] +0.0220 · Sharpe +0.10

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 767 | +0.0063 | -0.0157 | -0.26 | keep |
| volatility | 567 | +0.0356 | +0.0136 | +0.14 | review |
| volume | 539 | +0.0233 | +0.0013 | +0.04 | decoration |
| structure | 525 | +0.0148 | -0.0072 | -0.09 | keep |
| momentum | 503 | +0.0243 | +0.0023 | +0.03 | review |
| extension | 541 | +0.0249 | +0.0030 | +0.02 | decoration |
| timing | 633 | +0.0556 | +0.0336 | +0.46 | harmful |
| quality | 541 | +0.0218 | -0.0001 | +0.03 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 351 | -17.27 | 18.23 | 42.7 | -0.0701 | -4,934 | 12,335 | -17,269 |
| ETHUSDT | 456 | -17.21 | 18.34 | 43.4 | -0.0601 | -1,866 | 15,344 | -17,210 |
| SOLUSDT | 460 | +4.68 | 7.33 | 50.9 | +0.0395 | +20,995 | 16,316 | +4,679 |
| XRPUSDT | 532 | +1.30 | 15.78 | 48.3 | +0.0220 | +21,199 | 19,902 | +1,297 |
| **pooled** | **1799** | — | — | — | **-0.0123** | **+35,394** | **63,897** | **-28,503** |

Signals 4007 → fills 2492 → positions 1799 · accounting errors **0** · friction ÷ gross = 1.81

> ✅ **pooled n = 1799 ≥ 569** — the study now has 80% power to detect a 0.10R per-trade edge, so the pooled E[R] can be read as evidence and not only as description. The individual symbols still cannot.

> positive E[R] in 2 of 4 symbols (SOLUSDT, XRPUSDT). An edge that appears in only one symbol is a symbol-specific story, not an edge.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

