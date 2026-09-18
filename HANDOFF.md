# HANDOFF — تغییرات commit‌نشده و نقشهٔ قدم بعدی

**تاریخ:** 2026-09-17 · **نویسنده:** session `arena/01a09cb9-astra66` (بسته‌شده)

این session به‌دلیل ادغام PR #1 و #2 بسته شد، پس نتوانست کارهای زیر را push کند.
هر session جدیدی که این مخزن را باز می‌کند باید از همین‌جا ادامه دهد.

وضعیت `main` در زمان نوشتن این سند: `a218bcb` — شامل موتور کامل (`tbae/**`، ۵۶۲ تست)،
`README.md` بازنویسی‌شده، `.gitignore`، کانفیگ‌های Next.js (دست‌نخورده)، و
`.github/workflows/main.yml` که کاربر نسخهٔ workflow را در آن paste کرده است.
CI تأییدشده: اجرای #4 → job `research (real Binance data)` موفق در ۲m۵۷s،
artifact `real-data-reports` (۱۶.۱ KB). یعنی **رانر GitHub به Binance می‌رسد** و
اولین پژوهش روی دادهٔ واقعی انجام شد (نتایجش هنوز خوانده نشده — پشت sign-in است).

---

## ۱. فهرست فایل‌های commit‌نشده

| فایل | نوع | اندازه | چرا لازم است |
|---|---|---:|---|
| `.github/workflows/backtest.yml` | جدید | 507 خط | نسخهٔ اصلاح‌شدهٔ workflow + قدم `Publish report` |
| `tbae/scripts/fetch_binance.py` | جدید | 431 خط | دانلودر (vision archive + REST + mirror + QC) |
| `tbae/scripts/real_data_research.py` | جدید | 425 خط | پژوهش چندپنجره‌ای روی دادهٔ واقعی |
| `tbae/tests/test_fetch_binance.py` | جدید | 262 خط | ۲۱ تست آفلاین برای دانلودر |
| `tbae/engine/feeds.py` | ویرایش | +1,084 بایت | پشتیبانی `.csv.gz` در `CsvFeed` |
| `tbae/app/main.py` | ویرایش | +741 بایت | آپلود `.csv.gz` + پیام شفاف برای parquet |
| `tbae/tests/test_feeds.py` | ویرایش | +3,799 بایت | ۵ تست gzip (۵۹ → ۶۴) |
| `tbae/tests/test_api.py` | ویرایش | +1,713 بایت | ۲ تست آپلود (۵۶ → ۵۸) |
| `README.md` | ویرایش | +3,242 بایت | بخش ۹ «دادهٔ واقعی و CI» + شمار ۵۹۰ |
| `tbae/docs/SPEC.md` | ویرایش | +2 بایت | شمار تست |

**تست‌ها در این وضعیت: ۵۹۰ پاس** (۵۶۲ روی `main` + ۲۸ جدید).

---

## ۲. سه باگی که در workflow اصلاح شدند (برای مرورگر کد)

1. **`reports/` ساخته نمی‌شد** — قدم `Probe` با `tee ../reports/reachability.txt`
   می‌نوشت قبل از آنکه پوشه وجود داشته باشد → exit 1 در ۱۱ ثانیه و skip شدن همهٔ
   قدم‌های بعد، درحالی‌که `continue-on-error: true` تیک سبز نشان می‌داد.
   اصلاح: قدم `Prepare output directories` قبل از همه، و نویسنده‌ها هم خودشان
   `os.makedirs(..., exist_ok=True)` می‌زنند.
2. **وابستگی به اسکریپت‌های push‌نشده** — نسخهٔ اول `scripts/fetch_binance.py` را
   صدا می‌زد که روی `main` نبود (404). اصلاح: دانلود و پژوهش حالا **inline** با
   `engine.feeds.BinanceRestFeed` و `app.cli compare/sweep/ablation` انجام می‌شوند
   که همه روی `main` هستند.
3. **خلاصهٔ مبهم** — حالا قدم `Job summary` با `✅`/`❌` شروع می‌شود و در حالت شکست
   `::error::` صادر می‌کند تا تیک سبز گمراه‌کننده نباشد.

قدم جدید `Publish report to the repository` گزارش را در
`tbae/docs/results/run-<UTC>/` و `tbae/docs/results/LATEST.md` commit می‌کند تا
بدون sign-in قابل خواندن باشد. `permissions: contents: write` فقط روی همان job؛
push با `GITHUB_TOKEN` در Actions اجرای جدید trigger نمی‌کند (پس حلقه نمی‌شود) و
`[skip ci]` هم در پیام commit هست؛ و فقط وقتی commit می‌کند که `reports/real_*.json`
وجود داشته باشد.

---

## ۳. مشخصات بازسازی (اگر فایل‌ها از دست رفته باشند)

### `tbae/scripts/fetch_binance.py` — pure stdlib
* `http_get(url, timeout, retries, accept_404, pause)` با backoff روی 418/429/5xx و
  خواندن `Retry-After`.
* `vision_url(symbol, interval, period, base, market="spot")` →
  `https://data.binance.vision/data/spot/{monthly|daily}/klines/SYM/1m/SYM-1m-<period>.zip`
  (period = `YYYY-MM` → monthly، `YYYY-MM-DD` → daily).
* `parse_kline_zip(blob)` → عضو `.csv` را با `CsvFeed().load_fileobj(TextIOWrapper(...))`
  می‌خواند. آرشیو vision **بدون header** و با ترتیب خام kline است؛ `CsvFeed` همین
  ترتیب را می‌شناسد، پس parser دوم نوشته نشود.
* `verify_checksum` با `<url>.CHECKSUM` (sha256).
* `fetch_vision(..., granularity, tail="daily")`: **نکتهٔ کلیدی** — آرشیو ماهانهٔ ماهِ
  جاری منتشر نشده، پس دنباله با آرشیو **روزانه** پر می‌شود؛ وگرنه سری بی‌صدا تا یک
  ماه قدیمی می‌ماند. اگر هیچ آرشیو ماهانه‌ای پیدا نشد (کل بازه داخل ماه جاری)، به
  daily fallback می‌کند.
* `fetch_rest` با `BinanceRestFeed(base_url=...)`؛ `--mirror` → `https://data-api.binance.vision`.
* `merge` (dedupe بر اساس `ts` + trim به بازه) و `qc` (span، missing_minutes،
  missing_pct، duplicates، بزرگ‌ترین حفره‌ها، `validate_minutes`).
* خروجی با `feeds.write_minutes_csv` → قرارداد رفت‌وبرگشت با `CsvFeed` تضمین شود.

### `tbae/scripts/real_data_research.py`
* `windows(minutes, window_days, stride_days, min_fill)` با `bisect`؛ حلقه تا وقتی
  ادامه یابد که بلوک بعدی حداقل `min_fill` دقیقه داشته باشد (نه مقایسهٔ روزِ کامل —
  وگرنه آخرین بلوک دور ریخته می‌شود).
* `collect_block(res, ...)` دقیقاً همان شکل رکورد `cost_attribution.collect`
  (`gross_r`/`fric_r`/`net_r`/`bp`/`wins`/`losses`/`net_cash`/`start`/`max_dd_pct`/`n`)
  تا `CA.pooled` بدون تغییر قابل استفاده باشد. `pipeline.run(minutes=block, tf=tf)`
  یک‌بار برای هر پنجره (کش) چون به knobهای استراتژی وابسته نیست.
* `verdict(st)` بر اساس `n` در برابر `mde_trades` و CI:
  `no_trades` / `too_few_for_bootstrap` / `underpowered` / `net_edge_validated` /
  `net_edge_negative` / `inconclusive`.
* کنترل‌ها با `BacktestConfig(entry_mode="random"|"every_bar")` و `selection_gap_r`.
* خروجی JSON + Markdown؛ `SYNTHETIC_REFERENCE` (n=372، gross +0.1115، t=2.69،
  fric 0.1078، net +0.0037، CI [-0.067, +0.082]، PF 1.02، mde 569) برای مقایسه.

### `.csv.gz` در `engine/feeds.py`
`CsvFeed.__init__(..., compression="auto")` + `_is_gzip()` (پسوند `.gz`/`.gzip` یا
flag صریح) و در `load()` استفاده از `gzip.open(path, "rt", newline="", encoding="utf-8-sig")`.
دلیل: دادهٔ دقیقه‌ای به ~۳۴٪ فشرده می‌شود (۱۲۰ روز: ۱۸.۶ → ۶.۳۵ مگابایت).
parquet عمداً پشتیبانی **نمی‌شود** (pure-stdlib بودن = بازتولیدپذیری).

---

## ۴. نقشهٔ قدم بعدی (به ترتیب اولویت)

1. **commit کردن ۱۰ فایل بالا** و باز کردن PR؛ `pytest` باید ۵۹۰ پاس بدهد.
2. **خواندن نتایج اجرای #4** (`real-data-reports`) — اولین عدد واقعی پروژه. اگر قدم
   `Publish report` فعال باشد، از اجرای بعد در `tbae/docs/results/LATEST.md` قابل
   خواندن است.
3. **بازتولید صادقانهٔ `final_profitable_system.py`** (اسکریپت بیرونی که کاربر آورد).
   یافته‌های مرورِ آن — همه باید در نسخهٔ بازتولیدشده اصلاح شوند:
   * **fill ناممکن:** قفل استاپ روی `entry+1.5R` در میله‌ای که فقط به `+1R` رسیده
     → خروج در قیمتی **بالای high همان میله** ثبت می‌شود. اثبات مکانیکی:
     هر میله با `high ∈ [+1.0R, +1.5R)` یک برد تضمینی +1.5R می‌سازد.
     (بازتولید ایزوله انجام شد: entry=100, stop0=98, میله [99.5, 102.0] → خروج 103.0)
   * **look-ahead در دروازهٔ ورود:** `cr_entry_min = dd["capital_ratio"].dropna().quantile(0.5)`
     روی کل ۲۰۲۰-۲۰۲۶ محاسبه و به همهٔ میله‌ها اعمال می‌شود. باید صدک **expanding**
     در میلهٔ i باشد.
   * **ترتیب درون‌میله‌ای:** trailing با `high` همان میله بالا می‌رود و با `low` همان
     میله تست می‌شود.
   * **پای پیرامید بعد از `break` بی‌استاپ می‌ماند** و با `closes[entry_idx+10]` بسته می‌شود.
   * **sizing:** `stop_dist` از `stop0` اولیه (نه `cur_stop` واقعی) → هویت
     `qty × stop_distance == risk_cash` نقض؛ پای پیرامید `2×risk` فاصله می‌گیرد؛
     سقف لوریج binding است؛ `maxDD` فقط در لحظهٔ بسته‌شدن معامله نمونه‌برداری می‌شود؛
     لیکوییدیشن و گپ مدل نشده.
   * **هزینه:** فقط 14bp؛ funding و impact و گپِ استاپ نیست.
   * **آمار:** ~۲۷ عدد آزاد روی ۶ سالِ یک نماد؛ «test» نسبت به انتخاب پارامتر
     درون‌نمونه است؛ هیچ CI/DSR/PBO/MDE گزارش نشده.
4. **ایده‌هایی که ارزش آزمون دارند** (به‌عنوان فرضیه، نه نتیجه):
   `capital_ratio` (حرکت واقعی ÷ حرکت انتظاریِ شرطی به بینِ حجم × بینِ |عدم‌تعادل|)،
   پیش‌شرط فشردگی برای شکست (`avg_range(20) ≤ median_range(250)` و
   `range_width_rank ≤ 0.5`)، وتو فقط در افراط (`h4_strength_rank ≥ 0.9`)،
   دروازهٔ نهنگ (taker-buy بالای صدک ۹۵ رولینگ + هم‌علامتی delta)،
   trailing پلکانی به‌عنوان `EXIT_FAMILY` جدید، سقف فاجعهٔ ۳٪ مستقل،
   و scale-**IN** در `portfolio.py`.
   پروتکل آزمون هرکدام: پیاده‌سازی علّی در موتور → قیف ورود → کنترل‌های
   random/every-bar → pooling در سطح معامله با bootstrap ایستا → DSR با شمارش
   آزمون‌ها → PBO → walk-forward با refit → `mde_trades` → مقایسه با baseline روی
   **همان** داده (و روی دادهٔ واقعی از طریق CI).
5. **دادهٔ لازم برای بازتولید:** BTCUSDT یک‌ساعتهٔ ۲۰۲۰-۲۰۲۶ ≈ ۵۲٬۰۰۰ میله ≈ ۴ مگابایت
   CSV — با `fetch_binance.py --interval 1h --start 2020-01-01 --end 2026-09-16`
   از آرشیو vision قابل گرفتن است. **نیازی به ارسال فایل پارکت کاربر نیست.**
6. **موارد بازِ قدیمی‌تر:** کانفیگ‌های Next.js روی `main` (تصمیم حذف با کاربر)،
   داشبورد `static/` (بازسازی روی API موجود)، و عبور `n` از ۵۶۹ معامله برای
   اعتبارسنجی لبهٔ خالص.

---

## ۵. فرمان‌های راستی‌آزمایی

```bash
cd tbae && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 -m pytest -q                                   # انتظار: 590 passed
python3 scripts/fetch_binance.py --symbols BTCUSDT --days 45
python3 scripts/real_data_research.py --feed csv:data/binance/BTCUSDT_1m.csv --tf 15 --window 45
python3 -m app.cli compare --feed csv:data/binance/BTCUSDT_1m.csv --tf 15
```
