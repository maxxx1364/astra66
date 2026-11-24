# Wake-up scanner study — 2023-06-01 to 2026-11-22

620 Binance USDT coin pairs (delisted included). Rule: +15% target / -8% stop / 14 days, entry next open, stop first if both in one bar.

| set | n | signal days | target hit | stop hit | +15% within 14d | net (Tabdeal) | 95% CI | net (Nobitex) | gross |
|---|---|---|---|---|---|---|---|---|---|
| all signals | 1140 | 575 | 30.9% | 63.2% | 31.6% | -1.16% | [-1.94%, -0.34%] | -0.72% | -0.26% |
| top 3 per day | 967 | 575 | 30.5% | 63.3% | 31.2% | -1.25% | [-2.04%, -0.47%] | -0.81% | -0.35% |
| random liquid coin-day | 289987 | 1271 | 29.5% | 62.3% | 30.1% | -1.30% | [-1.67%, -0.93%] | -0.86% | -0.40% |

## By year

| | signals n | signals net (Tabdeal) | baseline net (Tabdeal) |
|---|---|---|---|
| 2023 | 238 | -1.93% | +0.38% |
| 2024 | 468 | -0.01% | -0.76% |
| 2025 | 387 | -1.97% | -2.43% |
| 2026 | 47 | -2.18% | -1.96% |

## By market regime (BTC vs its 50-day MA)

| | signals n | signals net (Tabdeal) | baseline net (Tabdeal) |
|---|---|---|---|
| btc_above_ma50 | 663 | -0.66% | -1.17% |
| btc_below_ma50 | 477 | -1.86% | -1.45% |

## Per condition (descriptive only — do not pick the best row)

| condition | days true | mean gross when true | all liquid days |
|---|---|---|---|
| rvol | 21688 | -0.21% | -0.40% |
| not_jumped | 237980 | -0.27% | -0.40% |
| squeeze | 90563 | -0.79% | -0.40% |
| taker_buy | 8479 | -0.18% | -0.40% |
| rel_strength | 88911 | -1.01% | -0.40% |
| breakout | 10647 | -0.57% | -0.40% |
| obv_trend | 7991 | -0.55% | -0.40% |

## Verdict

No edge. The signal set behaves like a randomly chosen liquid coin:
gross -0.26% per trade vs -0.40% for random liquid coin-days, with the
signal's 95% CI ([-1.04%, +0.56%] gross) containing the baseline. In the
regime that matters now (BTC below its 50-day MA) signals did *worse* than
random after costs (-1.86% vs -1.45%). After Tabdeal costs the mean is
-1.16% per trade with a CI entirely below zero.

Caveats: one pre-registered rule set and one trade rule; daily bars cannot
order intraday stop/target hits (stop assumed first, which is conservative).
Reproduce: `python3 scripts/wakeup_study.py --start 2023-06-01`.
