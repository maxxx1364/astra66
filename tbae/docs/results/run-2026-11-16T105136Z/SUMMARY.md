## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.44s)
OK   vision_archive (0.15s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +2.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.2B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 40 | -5.94 | -5.10 | 6.39 | 25.0 | -0.2334 | 0.28 |
| random_entry_control | 59 | +0.81 | +0.55 | 2.25 | 44.1 | +0.0364 | 1.09 |
| every_bar_control | 242 | -9.40 | -3.05 | 13.25 | 40.9 | -0.0538 | 0.79 |

**verdict:** `entry_selection_is_negative`

Decomposition (cash): gross -5,002 − friction 945 = net -5,947 · E[R] -0.2334 · n=40

Entry funnel: 71 signals → 43 fills → 40 positions (fill rate 0.61)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=40 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 40 | -5.94 | -5.10 | 6.39 | -0.2334 |
| 0.6 | 24 ⚠️ | -2.35 | -2.86 | 2.59 | -0.1679 |
| 0.75 | 10 ⚠️ | -0.85 | -2.21 | 1.02 | -0.1953 |
| 0.8 | 8 ⚠️ | -0.12 | -0.40 | 0.52 | -0.0405 |
| 0.85 | 6 ⚠️ | -0.17 | -0.77 | 0.49 | -0.0766 |

plateau pick: `0.8` (agrees with the best single point: True)
walk-forward: in-sample Sharpe -0.67 → out-of-sample -2.70 · overfit gap +2.04
deflated Sharpe: 0.070 (passes 95%: False) · PBO: 0.36 — elevated: a meaningful share of the ranking is selection noise

> ⚠️ **4 of 5 grid points have n < 30** (0.6, 0.75, 0.8, 0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> filtered plateau pick unavailable: only 1 grid point(s) have n ≥ 30, and a plateau needs at least 3.

#### BTCUSDT — filter ablation

baseline: n=40 · E[R] -0.2334 · Sharpe -5.10

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 57 | -0.0625 | +0.1709 | +2.98 | harmful |
| volatility | 42 | -0.2726 | -0.0392 | -0.78 | keep |
| volume | 40 | -0.2334 | +0.0000 | +0.00 | decoration |
| structure | 39 | -0.2299 | +0.0035 | +0.12 | review |
| momentum | 39 | -0.2206 | +0.0128 | +0.24 | review |
| extension | 40 | -0.2334 | +0.0000 | +0.00 | decoration |
| timing | 45 | -0.2011 | +0.0323 | +0.45 | harmful |
| quality | 40 | -0.2334 | +0.0000 | +0.00 | decoration |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 40 | -5.94 | 6.39 | 25.0 | -0.2334 | -5,002 | 945 | -5,947 |
| **pooled** | **40** | — | — | — | **-0.2334** | **-5,002** | **945** | **-5,947** |

Signals 71 → fills 43 → positions 40 · accounting errors **0** · friction ÷ gross = -0.19

> ⚠️ pooled n = 40 is still below the ~569 trades needed for 80% power at 0.10R.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

