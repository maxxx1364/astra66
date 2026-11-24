"""MARKET DNA ANALYZER — what kind of market is this symbol right now?

Two layers:

1. **Features** (pandas/NumPy) on candles resampled to ``DnaConfig.timeframe``:
   trend (EMA slope, efficiency ratio, regression R²), volatility (ATR %,
   regime), momentum (RSI, recent return), persistence (lag-1 autocorrelation,
   variance ratio), participation (volume z-score, taker-buy share) and data
   quality (share of live vs. backfilled minutes, empty minutes).
2. **tbae engine** — once enough bars exist, the full research pipeline and
   confirmation-filter stack (``engine.pipeline`` + ``engine.signals``) run on
   the same minutes; its latest accepted signal, edge score and bar category
   are attached.  This is the stack the backtests in ``docs/RESEARCH.md`` judge.

Spot cannot go short, so the analyzer reports a bearish bias but downstream
ranking only scores long setups.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from engine.models import MinuteBar

from .candles import bars_to_frame
from .config import DnaConfig


def resample(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["bucket"] = (d["ts"] // (tf * 60_000)) * (tf * 60_000)
    g = d.groupby("bucket", sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(),
        "quote_volume": g["quote_volume"].sum(), "taker_buy_volume": g["taker_buy_volume"].sum(),
        "trades": g["trades"].sum(), "minutes": g["close"].size(),
    })
    out.index.name = "ts"
    return out.reset_index()


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / dn.iloc[-1] if dn.iloc[-1] > 0 else np.inf
    return float(100 - 100 / (1 + rs)) if np.isfinite(rs) else 100.0


def _efficiency(close: np.ndarray, n: int) -> float:
    if len(close) < n + 1:
        n = len(close) - 1
    if n < 2:
        return 0.0
    seg = close[-(n + 1):]
    path = np.abs(np.diff(seg)).sum()
    return float(abs(seg[-1] - seg[0]) / path) if path > 0 else 0.0


def _r2(close: np.ndarray, n: int) -> tuple[float, float]:
    """R² and slope (bp per bar) of a linear fit to log price."""
    seg = np.log(close[-n:]) if len(close) >= n else np.log(close)
    if len(seg) < 5:
        return 0.0, 0.0
    x = np.arange(len(seg), dtype=float)
    slope, icept = np.polyfit(x, seg, 1)
    fit = slope * x + icept
    ss_res = float(((seg - fit) ** 2).sum())
    ss_tot = float(((seg - seg.mean()) ** 2).sum())
    return (1 - ss_res / ss_tot if ss_tot > 0 else 0.0), float(slope * 1e4)


def _variance_ratio(close: np.ndarray, k: int = 4) -> float:
    """VR(k) > 1: trending/persistent; < 1: mean-reverting."""
    r = np.diff(np.log(close))
    if len(r) < k * 8:
        return 1.0
    v1 = r.var()
    rk = np.convolve(r, np.ones(k), "valid")
    return float(rk.var() / (k * v1)) if v1 > 0 else 1.0


def features(bars: pd.DataFrame) -> dict[str, Any]:
    c = bars["close"].astype(float)
    h, l = bars["high"].astype(float), bars["low"].astype(float)
    n = len(bars)
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_pct = atr / c * 100
    ema_f, ema_s = _ema(c, 12), _ema(c, 48)
    r2, slope_bps = _r2(c.to_numpy(), min(n, 48))
    ret = np.log(c).diff().dropna()
    vol = bars["quote_volume"].astype(float)
    vol_z = float((vol.iloc[-1] - vol.tail(96).mean()) / vol.tail(96).std()) \
        if n >= 10 and vol.tail(96).std() > 0 else 0.0
    tb = bars["taker_buy_volume"].astype(float).tail(8).sum()
    tv = bars["volume"].astype(float).tail(8).sum()
    regime_ref = atr_pct.tail(200).median()
    return {
        "bars": n,
        "close": float(c.iloc[-1]),
        "atr_pct": float(atr_pct.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "vol_regime": float(atr_pct.iloc[-1] / regime_ref) if regime_ref > 0 else 1.0,
        "ema_gap_pct": float((ema_f.iloc[-1] / ema_s.iloc[-1] - 1) * 100),
        "ema_slope_bps": float((ema_s.iloc[-1] / ema_s.iloc[-min(5, n)] - 1) * 1e4),
        "efficiency": _efficiency(c.to_numpy(), 20),
        "r2": r2, "slope_bps_per_bar": slope_bps,
        "rsi": _rsi(c),
        "ret_4_bps": float((c.iloc[-1] / c.iloc[-min(5, n)] - 1) * 1e4),
        "autocorr1": float(ret.autocorr(1)) if len(ret) > 10 else 0.0,
        "variance_ratio": _variance_ratio(c.to_numpy()),
        "vol_z": vol_z,
        "taker_buy_share": float(tb / tv) if tv > 0 else 0.5,
        "high_20": float(h.tail(20).max()), "low_20": float(l.tail(20).min()),
    }


def classify_regime(f: dict[str, Any]) -> tuple[str, int]:
    """Coarse regime label and direction bias (+1 / -1 / 0)."""
    bias = int(np.sign(f["ema_gap_pct"])) if abs(f["ema_gap_pct"]) > 0.05 else 0
    if f["vol_regime"] < 0.5:
        return "dead", 0
    if f["efficiency"] > 0.35 and f["r2"] > 0.5 and f["variance_ratio"] > 1.0 and bias:
        return "trend", bias
    if f["vol_regime"] > 2.0 and f["efficiency"] < 0.2:
        return "chaotic", 0
    if f["variance_ratio"] < 0.85 or f["autocorr1"] < -0.1:
        return "mean_reverting", bias
    return "range", bias


def engine_view(minutes: Sequence[MinuteBar], cfg: DnaConfig) -> dict[str, Any]:
    """Run the tbae research pipeline + signal stack on the minutes."""
    from engine import pipeline, signals as S
    try:
        res = pipeline.run(list(minutes), tf=cfg.timeframe, with_cohort_curves=True)
    except ValueError as e:
        return {"ready": False, "reason": str(e)}
    n = len(res.bars)
    if n - res.warmup_index < 3:
        return {"ready": False, "reason": f"{n} bars, warm-up {res.warmup_index}"}
    ss = S.generate(res.bars, res.indicators, res.settings,
                    warmup_index=res.warmup_index,
                    cohort_curves=res.stats.get("cohort_curves", {}))
    last = res.bars[-1]
    recent = [s for s in ss.accepted if s.index >= n - 2]
    out: dict[str, Any] = {
        "ready": True, "bars": n, "category": last.category.value,
        "chart_pct": last.chart_pct, "system_pct": last.system_pct,
        "accepted_total": len(ss.accepted),
    }
    if recent:
        s = recent[-1]
        out["signal"] = {"side": s.side, "score": s.score, "grade": s.grade,
                         "strategy": s.strategy, "ts": s.ts, "age_bars": n - 1 - s.index}
    return out


def analyze(minutes: Sequence[MinuteBar], cfg: DnaConfig, *,
            live_minutes: int | None = None) -> dict[str, Any]:
    df = bars_to_frame(minutes)
    out: dict[str, Any] = {"minutes": len(df), "timeframe": cfg.timeframe, "ready": False}
    if len(df) < cfg.min_minutes:
        out["reason"] = f"need {cfg.min_minutes} minutes, have {len(df)}"
        return out
    out["empty_minute_share"] = float((df["trades"] == 0).mean())
    if live_minutes is not None:
        out["live_share"] = live_minutes / len(df)
    bars = resample(df, cfg.timeframe)
    if len(bars) < 10:
        out["reason"] = f"only {len(bars)} bars at {cfg.timeframe}m"
        return out
    f = features(bars)
    regime, bias = classify_regime(f)
    out.update(ready=True, features=f, regime=regime, bias=bias)
    if len(df) >= cfg.engine_min_bars * cfg.timeframe:
        out["engine"] = engine_view(minutes, cfg)
    else:
        out["engine"] = {"ready": False,
                         "reason": f"need {cfg.engine_min_bars * cfg.timeframe} minutes"}
    return out
