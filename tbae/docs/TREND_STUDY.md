# Spot trend-following study (enter after confirmation, trailing exit)

Data: 620 Binance USDT coin pairs incl. delisted, daily bars, 2023-06-01 to 2026-11-22.
Rules: `live/trend.py` (fixed before results). Reproduce: `python3 scripts/trend_study.py`.

| set | trades | win rate | avg win | avg loss | mean / trade (Tabdeal) | 95% CI | median trade | profit factor |
|---|---|---|---|---|---|---|---|---|
| signals + BTC>MA50 filter | 2071 | 30% | +40.3% | -15.3% | **+1.21%** | [-4.32%, +6.84%] | -11.6% (gross) | 1.11 |
| signals, no market filter | 2373 | 29% | +40.0% | -15.4% | +0.48% | [-4.49%, +5.38%] | -11.8% (gross) | 1.04 |
| random entry, same exits | 8634 | 17% | +32.8% | -10.5% | -3.05% | [-4.87%, -1.13%] | | 0.65 |

By year (with market filter, Tabdeal costs): 2023 **+14.0%**, 2024 +1.6%, 2025 **-11.7%** (win rate 8%),
2026 no trades (BTC below its 50-day MA all year — the filter kept the account out).

Small-account portfolio (5 slots x 20%, compounding): with filter, Tabdeal costs: **1.01x in 2.4 years,
max drawdown -93%**. Without filter: 0.09x. BTC buy-and-hold over the same window: **+233%**.

## Verdict

Better than random entry by ~4% per trade and better than the wake-up scanner, but not tradeable:
the confidence interval includes zero, one bull year (2023) carries the result, 2025 lost heavily,
the typical trade loses (results depend on a few large winners), and the portfolio drawdown is
unacceptable. Simply holding BTC beat it by a wide margin.
