# Calm-trend study: trend rule + anti-excitement / anti-junk filters

Script: `scripts/calm_trend_study.py`. Filters tuned on TRAIN (2023-06 .. 2024-12) over a
4,320-point grid; TEST (2025-01 .. 2026-11) evaluated once. Costs: Tabdeal taker + slippage.

| variant | train mean/trade | train CI | test n | test mean/trade | test CI | test win rate | test portfolio (5 slots) | test max DD |
|---|---|---|---|---|---|---|---|---|
| no filters | +5.4% | [-0.9%, +11.2%] | 514 | **-13.1%** | [-15.1%, -10.0%] | 8% | — | — |
| train-best grid point | +18.7% | [+6.8%, +29.7%] | 44 | -4.9% | [-10.9%, +2.3%] | 18% | 0.88x | -12% |
| moderate preset (fixed beforehand) | +14.2% | [+3.6%, +24.2%] | 25 | -2.5% | [-9.1%, +4.8%] | 24% | 1.03x | -8% |

BTC buy-and-hold over TEST: -3.3%.

Train-best: ATR <= 6%, not more than 20% ahead of BTC over 30 days, signal candle <= 15%,
liquidity >= 10M USDT/day, listed >= 180 days. Moderate preset: ATR <= 6%, <= 10% ahead of BTC,
<= 15% above EMA50, volume ratio <= 5, candle <= 15%, liquidity >= 5M, listed >= 180 days.

## Verdict

The filters work as **damage control**: in the bad period they cut the loss per trade from
-13% to -2.5..-5% and the portfolio drawdown from -93% (unfiltered, full period) to -8..-12%.
They do **not** produce a proven positive edge out of sample: test means are negative, CIs
include zero, and the test samples are small (25-44 trades). The large train results shrank
on unseen data, which is the expected signature of tuning. The test winners were large,
established coins (BNB, ETH, BCH, HBAR, LTC).
