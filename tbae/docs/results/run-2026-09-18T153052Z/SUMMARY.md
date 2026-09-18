## Real-data research

### Exchange reachability from this runner
```
FAIL rest: HTTPError: HTTP Error 451: 
OK   rest_mirror (0.62s)
OK   vision_archive (0.72s)
```

> ### ✅ Real-data study completed

### BTCUSDT

Costs: fee +4.0000/+1.0000 bp (taker/maker) · slippage +2.0000 bp · ADV 1.1B (measured) · tick 0.01

| configuration | trades | return% | Sharpe | maxDD% | win% | E[R] | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| strategy | 40 | -2.99 | -2.85 | 3.57 | 40.0 | -0.1566 | 0.58 |
| random_entry_control | 65 | -5.32 | -3.61 | 5.61 | 35.4 | -0.2497 | 0.62 |
| every_bar_control | 275 | -15.33 | -4.98 | 17.08 | 40.4 | -0.1463 | 0.69 |

**verdict:** `entry_selection_has_edge`

Decomposition (cash): gross -1,241 − friction 1,753 = net -2,994 · E[R] -0.1566 · n=40

Entry funnel: 81 signals → 46 fills → 40 positions (fill rate 0.57)

Accounting errors: **0** (net == gross − costs holds on every trade)

> ⚠️ n=40 is far below the ~569 trades needed for 80% power at 0.10R. Treat every number above as descriptive, not as evidence.

#### BTCUSDT — confirmation-threshold sweep

| min_edge_score | trades | return% | Sharpe | maxDD% | E[R] |
|---:|---:|---:|---:|---:|---:|
| 0.45 | 40 | -2.99 | -2.85 | 3.57 | -0.1566 |
| 0.6 | 32 | -3.53 | -3.90 | 4.24 | -0.2173 |
| 0.75 | 15 ⚠️ | -2.98 | -5.01 | 2.98 | -0.4089 |
| 0.8 | 11 ⚠️ | -0.97 | -2.23 | 1.59 | -0.1528 |
| 0.85 | 4 ⚠️ | -0.16 | -0.85 | 0.35 | -0.1027 |

plateau pick: `0.8` (agrees with the best single point: False)
walk-forward: in-sample Sharpe +0.43 → out-of-sample -3.45 · overfit gap +3.88
deflated Sharpe: 0.005 (passes 95%: False) · PBO: 0.56 — high: the configuration search was fitting noise — discard the best-in-sample pick

> ⚠️ **3 of 5 grid points have n < 30** (0.75, 0.8, 0.85). Their Sharpe values are noise. The CLI computes the plateau, walk-forward and PBO over **all** grid points, so those three readings just above are contaminated by these rows — read the filtered pick below instead.

> filtered plateau pick unavailable: only 2 grid point(s) have n ≥ 30, and a plateau needs at least 3.

#### BTCUSDT — filter ablation

baseline: n=40 · E[R] -0.1566 · Sharpe -2.85

| filter removed | trades | E[R] | Δ E[R] | Δ Sharpe | reading |
|---|---:|---:|---:|---:|---|
| trend | 63 | -0.0402 | +0.1164 | +2.37 | harmful |
| volatility | 41 | -0.1261 | +0.0305 | +0.86 | harmful |
| volume | 42 | -0.1215 | +0.0352 | +0.90 | harmful |
| structure | 40 | -0.1552 | +0.0014 | +0.03 | decoration |
| momentum | 38 | -0.1536 | +0.0030 | +0.12 | review |
| extension | 42 | -0.1145 | +0.0421 | +1.10 | harmful |
| timing | 42 | -0.1625 | -0.0059 | -0.74 | keep |
| quality | 42 | -0.1215 | +0.0352 | +0.90 | harmful |

_Δ is (filter removed) − baseline, so a **negative** Δ E[R] means the filter was earning money; `harmful` means removing it improves the result._

### Pooled across symbols

| symbol | trades | return% | maxDD% | win% | E[R] | gross$ | friction$ | net$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 40 | -2.99 | 3.57 | 40.0 | -0.1566 | -1,241 | 1,753 | -2,994 |
| **pooled** | **40** | — | — | — | **-0.1566** | **-1,241** | **1,753** | **-2,994** |

Signals 81 → fills 46 → positions 40 · accounting errors **0** · friction ÷ gross = -1.41

> ⚠️ pooled n = 40 is still below the ~569 trades needed for 80% power at 0.10R.

---

Costs are modelled (commission/funding bps + slippage + sqrt impact), not taken from a real fee tier or realised fills; and there is no order-book depth model, so a live position would move the price more than these numbers assume.

