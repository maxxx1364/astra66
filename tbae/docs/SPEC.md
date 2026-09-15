# SPEC — مشخصات مهندسی موتور TBAE

> این سند قراردادِ پیاده‌سازی است: آنچه هر ماژول تضمین می‌کند، چرا به آن شکل است،
> و کدام اینواریانت‌ها با تست قفل شده‌اند. برای یافته‌های پژوهشی به
> [`RESEARCH.md`](RESEARCH.md) بروید.

نسخهٔ موتور: `0.2.0` — زبان: Python 3.11+ — تست: `562` (شش فایل)

---

## ۱. اصول طراحی

1. **`engine/` صددرصد کتابخانهٔ استاندارد است.** بدون numpy/pandas. هر عدد گزارش‌شده
   از سورس قابل بازتولید است و اختلاف نسخهٔ کتابخانهٔ عددی نمی‌تواند نتیجه را عوض کند.
   بها: حلقه‌های پای slower — با `days=45, tf=15` (~۴۶۰۰ میله) کل pipeline ≈ ۱ ثانیه.
2. **هیچ ماژولی از `engine/` به FastAPI یا DOM وابسته نیست.** یک تابع
   (`pipeline.run`) همهٔ خروجی‌ها را می‌سازد؛ `app/` فقط مصرف‌کننده است.
3. **علّیت (causality) قرارداد است، نه اختیار.** پیش‌فرض `reference_mode` و
   `timing_mode` برابر `expanding` است؛ بک‌تست حالت `full` را **رد می‌کند** مگر
   `allow_lookahead=True` — و در آن صورت override در manifest ثبت و در warnings اعلام می‌شود.
4. **هر عدد باید قابل تجزیه باشد.** `net == gross − costs` روی تک‌تک معامله‌ها، و
   `mean(net R) == mean(gross R) − mean(friction R)` بدون باقی‌مانده.
5. **شکست باید پرسروصدا باشد.** ورودی نامعتبر → `ValueError` با پیامِ راهنما؛
   نه سکوت، نه `0.0` که بعداً «نتیجه» خوانده شود.
6. **هر ادعا یک تست دارد.** اینواریانت‌های حسابداری، نبودِ look-ahead، و معنای
   fillها در `tests/` قفل شده‌اند (نه در مستندات).

---

## ۲. نقشهٔ ماژول‌ها

| ماژول | قرارداد خروجی | نکتهٔ پیاده‌سازی |
|---|---|---|
| `models.py` | `MinuteBar`, `Bar`, `Settings`, `Category`, `Side`, `PathPoint` | `Bar.minute_path` مسیر دقیقه‌ای را نگه می‌دارد؛ `align_ts`/`timeframe_ms` |
| `mathx.py` | آمار خالص | `safe_div` فقط صیرِ **دقیق** و NaN/inf را کنترل می‌کند؛ `linreg_r2` روی سری ثابت → `0.0` |
| `resample.py` | `1m → tf` | `drop_incomplete=True` **همهٔ** سطل‌های کوتاه را می‌اندازد؛ `validate_minutes` قیمت غیرممکن/غیرمتناهی را رد می‌کند |
| `systembar.py` | `S, S_up, S_down, S_intra`, `efficiency`, legs | `S_intra ≥ range` طبیعی است |
| `reference.py` | مرجع پویای ۱۰۰٪ | ۲٪ trim + صدک ۹۸؛ `annotate_reference` میله‌ها را **در جا** تغییر می‌دهد و `category` را reset می‌کند |
| `classify.py` | درخت پنج‌دسته‌ای | ترتیب قواعد بارِ معنایی دارد: weak → pressure → energetic → strong → medium |
| `timing.py` | نقشهٔ حرارتی ۷×۲۴ | `TimingCell.score` رتبهٔ صدکی ∈ [0,1] است (نه میانگین خام) |
| `volatility.py` | ATR/σ/GK/Parkinson/RV | `vol_summary`: `atr_mean, sigma_mean/median/p95, vol_regime_mean, rv_over_gk` |
| `path.py` | منحنی رشد درون‌میله‌ای | `formed_pct` = جابه‌جایی از open ÷ بدنهٔ نهایی؛ **یکنوا نیست** و به ۵.۰ clamp می‌شود |
| `indicators.py` | EMA/ADX/RSI/VWAP/Donchian/pivot | Donchian میلهٔ جاری را **حساب نمی‌کند**؛ `swing_hi/lo` فقط pivot تأییدشده |
| `feeds.py` | synthetic / csv / binance REST+WS | تولیدکنندهٔ synthetic هیچ‌گاه ساعت دیواری را نمی‌خواند (`DEFAULT_END_TS` ثابت) |
| `pipeline.py` | `run() → PipelineResult` | زنجیرهٔ کامل: raw → bars → reference → category → timing → stats |
| `signals.py` | `SignalSet` + `diagnose()` | فیلترهای hard/soft؛ یک پیچِ تنظیم: `min_edge_score` |
| `risk.py` | `RiskManager` | اندازه‌گیری، دروازه‌ها، kill-switch؛ قرارداد «۰ = غیرفعال» |
| `exits.py` | `ExitManager` | stop ساختاری + پلکانی (tranche) + رویدادهای بازگشتی |
| `portfolio.py` | `Position`, `Trade`, `Fill` | ledger سه‌گانه: قیمت مرجع / قیمت fill / پول |
| `backtest.py` | `run_backtest() → BacktestResult` | تصمیم در `i−1` → اقدام در `i`؛ خروج دقیقه‌به‌دقیقه |
| `metrics.py` | آمار عملکرد + DSR | تجزیهٔ R، bootstrap ایستا، آناتومی drawdown |
| `validation.py` | k-fold پاک‌شده، walk-forward، CSCV/PBO، ablation، plateau | گاردهای بیش‌برازش |
| `rules.py` | زبان قواعد رنگ کاربر | کامپایلر expression بدون `eval`؛ ۲۴ فرمان / ۲۳ کلید |

---

## ۳. ریاضیات هسته (طبق پروپوزال)

برای میله‌های منبع یک‌دقیقه‌ای `i = 1..n` در یک میلهٔ تایم‌فریم:

| کمیت | فرمول |
|---|---|
| بدنهٔ چارت | `chart_abs = |close_n − open_1|` |
| دامنهٔ چارت | `chart_range = high − low` |
| میلهٔ سیستمی | `S = Σ |legs|` (تحرک خنثی‌نشده) |
| تفکیک جهت | `S_up = Σ legs⁺`, `S_down = Σ legs⁻` |
| تحرک درون‌دقیقه‌ای | `S_intra = Σ (high_i − low_i)` |
| بازدهی | `efficiency = chart_abs / S ∈ [0,1]` |

**مرجع پویای ۱۰۰٪:** مرتب‌سازی → حذف `reference_max_outlier_share` (پیش‌فرض ۲٪) از
بالاترین‌ها به‌عنوان Max Bar → صدک `reference_percentile` (پیش‌فرض ۹۸) از باقی‌مانده.
سپس `chart_pct = chart_abs / chart_ref` و `system_pct = S / system_ref`.

**درخت دسته‌بندی (اولین تطابق برنده):**

| # | دسته | شرط | رنگ |
|---|---|---|---|
| ۱ | ضعیف | `chart_pct < 20%` و `system_pct < 20%` | `#8a94a6` |
| ۲ | پرفشار | `system_pct ≥ 80%` و `chart_pct < 20%` | `#a855f7` |
| ۳ | پرانرژی | `chart_pct ≥ 55%` و `system_pct ≥ 55%` | `#1e3a8a` |
| ۴ | قوی | `chart_pct ≥ 55%` و `system_pct < 55%` | `#3b82f6` |
| ۵ | متوسط | سایر | `#22c55e` / `#f97316` |

**امتیاز خانهٔ حرارتی:** `0.50 × mean(system_pct) + 0.35 × mean(chart_pct) + 0.15 × mean(efficiency)`،
سپس نرمال‌سازی رتبهٔ صدکی؛ برش‌ها `timing_dead_share` (۳۳٪ پایین) و `timing_hot_share` (۲۵٪ بالا).

---

## ۴. لایهٔ استراتژی

### ۴.۱ سیگنال و فیلترهای تأیید (`signals.py`)

هر میلهٔ آماده یک **کاندیدا** است؛ سپس از قیفی از فیلترها رد می‌شود. دو نوع فیلتر:

* **hard** (رد قطعی): دستهٔ نامناسب، جهت نامشخص، ADX کمتر از `min_adx`,
  RSI خارج از بازه، گسترش بیش از `max_extension`, شکست ساختار مخالف.
* **soft** (پرچم، نه رد): مواردی که شواهدشان ضعیف‌تر است — در `soft_flag_counts`
  شمرده می‌شوند و در `min_edge_score` اثر می‌گذارند.

**چرا این تقسیم؟** زنجیرهٔ فیلترهای hard حجم سیگنال را نابود می‌کند (از ۴۴۰۷ میله
به صفر). با تفکیک hard/soft و یک پیچ واحد (`min_edge_score`)، قیف خوانا می‌ماند و
تنظیم‌پذیر است.

خروجی `SignalSet`: `candidates`, `signals`, `funnel` (مرحله‌به‌مرحله: `key, entered,
passed, rejected, note`), `rejection_counts`, `soft_flag_counts`, `sole_killer`,
`n_bars`, `n_tradable`. تابع `diagnose()` گلوگاه را نام می‌برد
(`bottleneck{narrowest_stage, narrowest_pass_rate, most_decisive_filter, redundant_filters}`).

> `SignalConfig.validate()` بازهٔ همهٔ پارامترها را کنترل می‌کند و
> `config_hash()` اثر انگشت پیکربندی را می‌دهد (پیش‌فرض: `a8a98c245133`) تا دو اجرا
> با تنظیم متفاوت هرگز اشتباه گرفته نشوند.

### ۴.۲ مدیریت ریسک (`risk.py`)

* **اندازه‌گیری:** `qty × stop_distance == risk_cash` (دقیق). بودجه =
  `risk_per_trade_pct × equity` با `sizing_mode` (risk_and_vol / fixed / kelly).
* **دروازه‌ها:** `max_open_positions`, `max_trades_per_day`, `max_total_risk_pct`,
  `daily_loss_limit_pct`, `max_drawdown_kill_pct`, `max_consecutive_losses` + cooldown.
* **قرارداد «۰ = غیرفعال»** برای همهٔ limits *درصدی*. استثنا: سقف‌های *تعدادی*
  (`max_open_positions`, `max_trades_per_day`) باید `≥ 1` باشند، چون صفر برای آن‌ها
  بین «معامله نکن» و «نامحدود» مبهم است — `validate()` آن را رد می‌کند.
* `trades_today` در `record_trade()` افزایش **نمی‌یابد**: سقف روزانه باید موقعِ
  *باز شدن* پوزیشن شمرده شود، نه موقع بستن (وگرنه وقتی بسته شد، دیگر دیر است).
  بک‌تست آن را در لحظهٔ ورود افزایش می‌دهد.

### ۴.۳ خروج پلکانی و پویا (`exits.py`)

* **stop ساختاری:** از pivot تأییدشدهٔ اخیر، سپس clamp به بازهٔ
  `[1.2σ, 3.2σ]` و بعد بازهٔ درصدی؛ buffer بیرونِ clamp اضافه می‌شود.
  σ ترجیحاً `bar.sigma_atr` (هموارشده) است نه `bar.sigma` لحظه‌ای.
* **پلکان‌ها:** هدفِ tranche k = `entry + k · r_multiple · stop_distance`.
  هدف‌ها سفارش limit ساکن‌اند → fill در قیمت هدف، بدون slip، با نرخ maker.
* **رویدادهای بازگشتی:** `leg_flow_flip`, `effort_vs_result`, `efficiency_collapse`,
  `engulfing`, `wick_rejection`. شدت‌ها با `combine_severity` ترکیب و به
  tighten / close_partial / close_all نگاشت می‌شوند. میلهٔ `weak` **شاهد بازگشت نیست**؛
  فقط `pressure`. رویدادها به بلوغ معامله و نرمال‌سازی با RV خودِ میله نیاز دارند.
* **درون‌میله‌ای:** `intra_bar_check` فقط رویداد flow-flip را در
  `elapsed == floor(tf × event_check_elapsed)` ارزیابی می‌کند (شاهد واقعی درون‌میله‌ای
  وجود دارد؛ بقیه به میلهٔ کامل نیاز دارند و حدس زدنشان یعنی look-ahead).
* **`on_bar` استاپ را چک نمی‌کند** — استاپ/اهداف توسط بک‌تست‌کننده دقیقه‌به‌دقیقه
  با `stop_hit`/`tranches_hit` حل می‌شوند.

### ۴.۴ ورود limit (pullback)

ورود با قیمت بازار روی میلهٔ پرجابه‌جاهی یعنی **انتخاب نامساعد** (adverse selection):
دقیقاً همان‌جا که سیگنال می‌دهد، قیمت از شما دور شده است. پس سفارش limit داخلِ
میلهٔ سیگنال کاشته می‌شود (`pullback_mode`: `sigma` / `body` / `midpoint`) و:

* long: اگر `bar.low ≤ level` → fill در `min(bar.open, level)` (gap به نفع شماست)
* short: اگر `bar.high ≥ level` → fill در `max(bar.open, level)`
* اگر قیمت از extreme میلهٔ سیگنال فرار کند → سفارش **باطل** (`pullback_invalidated`)
* `ttl` تمام شود → `pullback_expired`

نتیجه در `pending_stats` و `entry_funnel` گزارش می‌شود (نرخ fill، نرخ عبور از دروازه،
نرخ سرتاسری).

---

## ۵. قرارداد حسابداری بک‌تست

سه ledger موازی و آشتی‌پذیر:

| ledger | قیمت | شامل |
|---|---|---|
| `gross_pnl` | **مرجع** (`entry_ref_price` / `exit_ref_price`) | هیچ هزینه‌ای |
| fillها | قیمت واقعی fill | slip نهفته در فاصلهٔ مرجع↔fill |
| `net_pnl` | — | `gross_pnl − (commission + funding + slippage)` |

* هزینهٔ ورود **یک بار** گرفته می‌شود.
* maker/taker: ورود limit و هدف‌های TP → maker (`maker_bps`, slip صفر)؛
  استاپ/رویداد/زمان → taker (`commission_bps` + slippage).
* `risk_cash` بودجهٔ نقدیِ یک استاپ کامل است؛ `r_multiple = net_pnl / risk_cash`.
* `entry_funnel` باید **آشتی کند**: `orders_placed == filled + invalidated + expired + resting`
  و `entry_attempts == positions_opened + gate_blocked`. در غیر این صورت در
  `accounting_errors` ثبت می‌شود.
* `Fill.minute_index` یک **اندیس صفر-بنیاد** در `bar.minute_path` است
  (`ts` فیل دقیقاً برابر `minute_path[minute_index].ts`)؛ `-1` یعنی «دقیقه‌ای حل نشده».
  آنچه `ExitManager.intra_bar_check` می‌گیرد *تعداد* دقیقه‌های سپری‌شده است، نه اندیس.

---

## ۶. گاردهای بیش‌برازش

| ابزار | قرارداد |
|---|---|
| `purged_kfold` | purge سمت **گذشته** و embargo سمت **آینده**ٔ پنجرهٔ تست |
| `walk_forward` | انتخاب بهترین config در IS، گزارش OOS + `overfit_gap` + DSR |
| `cscv_pbo` | PBO < 0.2 دلگرم‌کننده، > 0.5 یعنی دور ریختن انتخاب |
| `deflated_sharpe` | **همهٔ ورودی‌ها per-period**، از جمله `sr_std`؛ `kurt` غیراضافی (نرمال = ۳). اگر `n_trials > 1` و `sr_std == 0` باشد → `reliable=False` (جریمهٔ آزمون چندگانه غیرفعال است) |
| `stationary_bootstrap` | Politis–Romano؛ بلوک‌ها پیوسته‌اند تا وابستگی سری حفظ شود |
| `parameter_plateau` / `best_plateau` | spike = همسایه‌ها < ۰.۵× خود؛ انتخاب فقط از میان نقاط با پنجرهٔ کامل و غیر-spike |
| `minimum_detectable_trades` | کنار `n` گزارش می‌شود تا نتیجهٔ کم‌نمونه «اعتبارسنجی‌شده» خوانده نشود |
| `ablation` | verdict: `keep` / `decoration` / `harmful` / `review` |
| `profit_factor` | بدون معاملهٔ بازنده = `PROFIT_FACTOR_CAP` (۹۹۹) + پرچم `no_losing_trades`؛ JSON-safe |

---

## ۷. دادهٔ synthetic

چون در محیط توسعه دسترسی شبکه به صرافی نیست، منبعِ بک‌تست یک تولیدکنندهٔ
**قطعی و واقع‌گرا** است: GARCH(1,1) روی بازده لگاریتمی (`ω=0.02, α=0.08, β=0.90`)،
`base_sigma=4.2e-4` (≈ ۷.۳bp دقیقه‌ای، ≈ ۵۵٪ سالانه)، پرش‌ها فقط در diffusion
(نه در بازگشت GARCH، وگرنه قیمت منفجر می‌شود) با `jump_scale=3.5`،
`vol_mult_cap=3.0`، و حجم/تعداد معامله با کوپلینگ `taker_coupling=0.42`.

* `warmup_days=3` روزِ ابتدایی اضافه می‌کند؛ پس
  `load_feed("synthetic:days=N")` دقیقاً `(N + 3) × 1440` دقیقه می‌دهد و
  `split_warmup()` همان ۳ روز را جدا می‌کند.
* `follow_clock=False` (پیش‌فرض) ⇒ `end_ts = DEFAULT_END_TS` ثابت ⇒ دادهٔ
  bit-identical برای `(seed, days)`. این شرطِ بازتولیدپذیری پژوهش است.
* کد فید Binance (REST با pagination/retry و WS با ring buffer) نوشته شده و
  آفلاین با لایهٔ HTTP جایگزین‌شده تست می‌شود؛ روی ماشین شما با شبکهٔ واقعی کار می‌کند.

---

## ۸. اجرای سریع

```bash
cd tbae
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python3 -m pytest                                  # ۵۶۲ تست
python3 -m app.cli backtest --tf 15 --days 45      # بک‌تست کامل + هشدارها
python3 -m app.cli compare  --tf 15 --days 45      # استراتژی در برابر دو کنترل
python3 -m app.cli sweep    --tf 15 --days 45      # جاروب آستانه/هندسه
python3 -m app.cli ablation --tf 15 --days 45      # سهم هر فیلتر
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # API + /docs

python3 scripts/cost_attribution.py --seeds 20 --days 45 --tf 15 \
        --json reports/cost_attribution.json       # پژوهش هزینه (≈ ۲ دقیقه)
```

`reports/` و `tbae/data/` در `.gitignore` هستند: artefact تولیدی و وضعیت کاربر،
نه سورس.
