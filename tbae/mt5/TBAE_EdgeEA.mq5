//+------------------------------------------------------------------+
//| TBAE_EdgeEA.mq5                                                  |
//| MetaTrader 5 port of the TBAE strategy core (tbae/engine).       |
//|                                                                  |
//| Scope — read this before trusting a backtest:                    |
//|   PORTED      confirmation-filter edge score (trend, volatility, |
//|               volume, momentum/efficiency, extension, structure, |
//|               timing), pullback-limit entry with TTL, sigma stop |
//|               with pct clamps, 3-tranche exits (1R/2R/runner),   |
//|               breakeven promotion, chandelier trail, time stops, |
//|               profit-giveback guard, risk-per-trade sizing,      |
//|               cooldown and daily signal cap.                     |
//|   APPROXIMATED the engine's percentile "category" gate (dynamic  |
//|               98th-percentile reference) is replaced by a sigma  |
//|               displacement gate (InpCandidateSigma); the timing  |
//|               7x24 heatmap is replaced by a dead-hours list.     |
//|   NOT PORTED  the full reversal-event ladder (12 weighted        |
//|               events), intra-bar minute-path exits, vol-target   |
//|               sizing, kill-switches.  See mt5/README.md.         |
//|                                                                  |
//| Decision timing matches the engine exactly: every decision is    |
//| taken on the CLOSED bar and acted on from the next bar — there   |
//| is no look-ahead anywhere in this file.                          |
//+------------------------------------------------------------------+
#property copyright "astra66 TBAE"
#property version   "0.20"
#property strict

#include <Trade/Trade.mqh>

//---------------------------------------------------------------- inputs
input group "=== Signal / candidate gate ==="
input double InpCandidateSigma     = 1.50;   // body displacement >= N sigma to be a candidate
input double InpMinEdgeScore       = 0.45;   // SignalConfig.min_edge_score
input int    InpCooldownBars       = 2;      // SignalConfig.cooldown_bars
input int    InpMaxSignalsPerDay   = 8;      // SignalConfig.max_signals_per_day

input group "=== Trend filter (f_trend) ==="
input bool   InpFTrend             = true;
input int    InpEmaFast            = 21;
input int    InpEmaSlow            = 55;
input double InpMinADX             = 18.0;   // SignalConfig.min_adx
input bool   InpAllowCounterTrend  = false;

input group "=== Volatility filter (f_volatility) ==="
input bool   InpFVolatility        = true;
input double InpAtrRankMin         = 0.10;   // SignalConfig.atr_rank_min
input double InpAtrRankMax         = 0.997;  // SignalConfig.atr_rank_max
input double InpVolRegimeMin       = 0.30;   // SignalConfig.vol_regime_min
input double InpVolRegimeMax       = 7.00;   // SignalConfig.vol_regime_max
input int    InpAtrPeriod          = 14;
input int    InpAtrRankLookback    = 240;    // bars for the percentile rank

input group "=== Volume filter (f_volume) ==="
input bool   InpFVolume            = true;
input double InpMinVolZ            = -0.75;  // SignalConfig.min_vol_z (hard floor)
input double InpGoodVolZ           = 0.50;   // SignalConfig.good_vol_z (soft target)
input int    InpVolZLookback       = 96;

input group "=== Momentum filter (f_momentum) ==="
input bool   InpFMomentum          = true;
input double InpMinEfficiency      = 0.12;   // SignalConfig.min_efficiency_trend
input double InpGoodEfficiency     = 0.38;   // SignalConfig.good_efficiency_trend
input double InpRsiLongMax         = 78.0;   // SignalConfig.rsi_long_max
input double InpRsiShortMin        = 22.0;   // SignalConfig.rsi_short_min
input int    InpRsiPeriod          = 14;

input group "=== Extension filter (f_extension) ==="
input bool   InpFExtension         = true;
input double InpMaxExtensionSigma  = 5.0;    // SignalConfig.max_extension_sigma (hard)
input double InpExtensionSoftSigma = 1.5;    // SignalConfig.extension_soft_sigma

input group "=== Structure filter (f_structure) ==="
input bool   InpFStructure         = true;
input int    InpDonchianPeriod     = 20;

input group "=== Timing filter (f_timing) ==="
input bool   InpFTiming            = true;
input string InpDeadHoursUTC       = "";     // e.g. "3,4,5" — hours to skip (empty = none)

input group "=== Edge-score weights (renormalised) ==="
input double InpWCategory          = 0.22;
input double InpWEfficiency        = 0.16;
input double InpWTrend             = 0.18;
input double InpWVolume            = 0.12;
input double InpWFlow              = 0.10;
input double InpWTiming            = 0.10;
input double InpWVolatility        = 0.12;
input double InpWStructure         = 0.10;

input group "=== Entry (pullback limit) ==="
input bool   InpPullbackEntry      = true;   // false = market at next open
input double InpPullbackSigma      = 0.90;   // SignalConfig.pullback_retrace_sigma
input int    InpPullbackTTLBars    = 4;      // SignalConfig.pullback_ttl_bars

input group "=== Stop geometry (ExitConfig) ==="
input double InpStopSigmaMult      = 4.40;   // ExitConfig.stop_sigma_mult (wide study pick)
input double InpMinStopPct         = 0.12;   // ExitConfig.min_stop_pct (% of price)
input double InpMaxStopPct         = 1.60;   // ExitConfig.max_stop_pct (% of price)

input group "=== Staged exits (ExitConfig.tranches) ==="
input double InpTp1R               = 1.00;   // tranche 1 target (R)
input double InpTp1Share           = 0.40;   // tranche 1 share
input double InpTp2R               = 2.00;   // tranche 2 target (R)
input double InpTp2Share           = 0.35;   // tranche 2 share of remainder... (of initial)
input double InpBeAfterR           = 1.00;   // ExitConfig.move_stop_to_be_after_r
input double InpBeBufferSigma      = 0.10;   // ExitConfig.be_buffer_sigma

input group "=== Trailing (chandelier) ==="
input bool   InpTrailEnabled       = true;
input int    InpChandelierPeriod   = 10;     // ExitConfig.chandelier_period
input double InpChandelierMult     = 3.00;   // ExitConfig.chandelier_mult
input double InpTrailStartR        = 0.80;   // ExitConfig.trail_start_r

input group "=== Time / giveback exits ==="
input int    InpMaxBarsHeld        = 64;     // ExitConfig.max_bars_held
input int    InpTimeStopBars       = 8;      // ExitConfig.time_stop_bars
input double InpTimeStopMinR       = 0.30;   // ExitConfig.time_stop_min_r
input double InpGivebackPeakR      = 1.00;   // ExitConfig.giveback_peak_r
input double InpGivebackGiveR      = 1.00;   // ExitConfig.ratchet_give_back_r

input group "=== Risk ==="
input double InpRiskPerTradePct    = 0.75;   // RiskConfig.risk_per_trade_pct
input int    InpMaxOpenPositions   = 1;      // RiskConfig.max_open_positions
input int    InpMaxTradesPerDay    = 12;     // RiskConfig.max_trades_per_day
input bool   InpAllowShort         = true;   // RiskConfig.allow_short
input long   InpMagic              = 662026;

//---------------------------------------------------------------- state
CTrade  trade;
int     hEmaFast = INVALID_HANDLE, hEmaSlow = INVALID_HANDLE;
int     hATR = INVALID_HANDLE, hADX = INVALID_HANDLE, hRSI = INVALID_HANDLE;
datetime lastBarTime = 0;
int     lastSignalBarIndexAgo = 1000000;  // bars since last accepted signal
int     signalsToday = 0, tradesToday = 0;
int     todayKey = -1;
bool    deadHour[24];

// pending pullback order bookkeeping
ulong   pendingTicket = 0;
int     pendingAgeBars = 0;

// per-position management state (single position: MaxOpenPositions=1)
double  posEntry = 0, posStop0 = 0, posRiskDist = 0, posPeakR = 0;
int     posBarsHeld = 0;
bool    tp1Done = false, tp2Done = false, beDone = false;

//---------------------------------------------------------------- helpers
double Sigma(int shift, int period = 20)
  {
   // close-to-close stdev over `period` bars, in price units — the engine's
   // sigma proxy for stop and pullback geometry.
   double sum = 0, sum2 = 0;
   int n = 0;
   for(int i = shift; i < shift + period; i++)
     {
      double r = iClose(_Symbol, _Period, i) - iClose(_Symbol, _Period, i + 1);
      sum += r; sum2 += r * r; n++;
     }
   if(n < 2) return 0.0;
   double var = (sum2 - sum * sum / n) / (n - 1);
   return var > 0 ? MathSqrt(var) : 0.0;
  }

double Buf(int handle, int bufIndex, int shift)
  {
   double v[1];
   if(CopyBuffer(handle, bufIndex, shift, 1, v) != 1) return EMPTY_VALUE;
   return v[0];
  }

double Tanh01(double x)
  {
   // MQL5 has no MathTanh; tanh(x) = (e^2x - 1) / (e^2x + 1), clamped to x>=0
   double z = MathMax(0.0, x);
   double e = MathExp(2.0 * z);
   return (e - 1.0) / (e + 1.0);
  }

double AtrRank(int shift)
  {
   // percentile rank of the current ATR within the lookback window
   double cur = Buf(hATR, 0, shift);
   if(cur == EMPTY_VALUE) return 0.5;
   int below = 0, n = 0;
   for(int i = shift + 1; i <= shift + InpAtrRankLookback; i++)
     {
      double a = Buf(hATR, 0, i);
      if(a == EMPTY_VALUE) break;
      if(a <= cur) below++;
      n++;
     }
   return n > 0 ? (double)below / n : 0.5;
  }

double VolZ(int shift)
  {
   long v[];
   if(CopyTickVolume(_Symbol, _Period, shift, InpVolZLookback, v) < InpVolZLookback)
      return 0.0;
   double sum = 0, sum2 = 0;
   int n = ArraySize(v);
   for(int i = 0; i < n; i++) { sum += (double)v[i]; sum2 += (double)v[i] * v[i]; }
   double m = sum / n;
   double sd = MathSqrt(MathMax(0.0, (sum2 - sum * sum / n) / (n - 1)));
   // index n-1 is the oldest; the requested `shift` bar is index 0 of the copy?
   // CopyTickVolume fills as series when the target array is not set otherwise:
   ArraySetAsSeries(v, true);
   return sd > 0 ? ((double)v[0] - m) / sd : 0.0;
  }

void ParseDeadHours()
  {
   for(int i = 0; i < 24; i++) deadHour[i] = false;
   string parts[];
   int n = StringSplit(InpDeadHoursUTC, ',', parts);
   for(int i = 0; i < n; i++)
     {
      int h = (int)StringToInteger(parts[i]);
      if(h >= 0 && h < 24) deadHour[h] = true;
     }
  }

bool IsNewBar()
  {
   datetime t = iTime(_Symbol, _Period, 0);
   if(t == lastBarTime) return false;
   lastBarTime = t;
   return true;
  }

//---------------------------------------------------------------- signal
// Evaluate the confirmation stack on the CLOSED bar (shift=1).
// Returns 0 = no signal, +1 = long, -1 = short; fills `score`.
int EvaluateSignal(double &score, double &sigma)
  {
   const int s = 1;                         // the just-closed bar
   score = 0.0;
   sigma = Sigma(s);
   if(sigma <= 0) return 0;

   double op = iOpen(_Symbol, _Period, s),  cl = iClose(_Symbol, _Period, s);
   double hi = iHigh(_Symbol, _Period, s),  lo = iLow(_Symbol, _Period, s);
   double body = cl - op, range = hi - lo;
   if(range <= 0) return 0;

   // ---- candidate gate (proxy for the engine's percentile category gate) ----
   double disp = MathAbs(body) / sigma;
   if(disp < InpCandidateSigma) return 0;
   int side = body > 0 ? 1 : -1;
   if(side < 0 && !InpAllowShort) return 0;

   // ---- hard filters (veto) + score contributions in [0,1] ----
   double emaF = Buf(hEmaFast, 0, s), emaS = Buf(hEmaSlow, 0, s);
   double adx  = Buf(hADX, 0, s);
   double rsi  = Buf(hRSI, 0, s);
   double atr  = Buf(hATR, 0, s);
   if(emaF == EMPTY_VALUE || emaS == EMPTY_VALUE || adx == EMPTY_VALUE ||
      rsi == EMPTY_VALUE || atr == EMPTY_VALUE) return 0;

   // trend (hard): price side must agree with the ribbon unless counter-trend
   double cTrend = 0.5;
   if(InpFTrend)
     {
      bool up = emaF > emaS, dn = emaF < emaS;
      bool agree = (side > 0 && up) || (side < 0 && dn);
      if(!agree && !InpAllowCounterTrend) return 0;
      if(adx < InpMinADX) return 0;
      cTrend = 0.5 * (agree ? 1.0 : 0.3) + 0.5 * Tanh01((adx - InpMinADX) / 20.0);
     }

   // volatility (hard band): ATR percentile rank + regime ratio
   double cVol = 0.5;
   if(InpFVolatility)
     {
      double rank = AtrRank(s);
      if(rank < InpAtrRankMin || rank > InpAtrRankMax) return 0;
      double atrSlowSum = 0; int m = 0;
      for(int i = s; i < s + 96; i++)
        { double a = Buf(hATR, 0, i); if(a == EMPTY_VALUE) break; atrSlowSum += a; m++; }
      double regime = (m > 0 && atrSlowSum > 0) ? atr / (atrSlowSum / m) : 1.0;
      if(regime < InpVolRegimeMin || regime > InpVolRegimeMax) return 0;
      cVol = 1.0 - MathAbs(rank - 0.55) / 0.55;      // best mid-band
     }

   // extension (hard cap, soft penalty): distance of close from slow EMA in sigma
   double cExt = 1.0;
   if(InpFExtension)
     {
      double ext = MathAbs(cl - emaS) / sigma;
      if(ext > InpMaxExtensionSigma) return 0;
      cExt = ext <= InpExtensionSoftSigma
             ? 1.0
             : MathMax(0.0, 1.0 - (ext - InpExtensionSoftSigma)
                                 / (InpMaxExtensionSigma - InpExtensionSoftSigma));
     }

   // timing (hard): dead hours in UTC
   double cTiming = 1.0;
   if(InpFTiming)
     {
      MqlDateTime dt;
      TimeToStruct(iTime(_Symbol, _Period, s), dt);
      if(deadHour[dt.hour]) return 0;
     }

   // volume (soft, hard floor): tick-volume z-score
   double cVolu = 0.5;
   if(InpFVolume)
     {
      double vz = VolZ(s);
      if(vz < InpMinVolZ) return 0;
      cVolu = Tanh01((vz - InpMinVolZ) / MathMax(0.1, InpGoodVolZ - InpMinVolZ));
     }

   // momentum / efficiency (soft, hard floor): |body| / range and RSI guard
   double cEff = 0.5;
   if(InpFMomentum)
     {
      double eff = MathAbs(body) / range;
      if(eff < InpMinEfficiency) return 0;
      if(side > 0 && rsi > InpRsiLongMax) return 0;
      if(side < 0 && rsi < InpRsiShortMin) return 0;
      cEff = Tanh01((eff - InpMinEfficiency)
                    / MathMax(0.05, InpGoodEfficiency - InpMinEfficiency));
     }

   // structure (soft): Donchian breakout of the prior channel
   double cStruct = 0.4;
   if(InpFStructure)
     {
      int hiIdx = iHighest(_Symbol, _Period, MODE_HIGH, InpDonchianPeriod, s + 1);
      int loIdx = iLowest(_Symbol, _Period, MODE_LOW, InpDonchianPeriod, s + 1);
      double chHi = iHigh(_Symbol, _Period, hiIdx);
      double chLo = iLow(_Symbol, _Period, loIdx);
      bool breakout = (side > 0 && cl > chHi) || (side < 0 && cl < chLo);
      cStruct = breakout ? 1.0 : 0.4;
     }

   // flow proxy: close location within the range, in the trade direction
   double loc = (cl - lo) / range;                    // 1 = closed on the high
   double cFlow = side > 0 ? loc : 1.0 - loc;

   // category contribution: how far above the candidate gate the bar is
   double cCat = Tanh01((disp - InpCandidateSigma) / 1.5);

   // ---- weighted edge score (weights renormalised, engine-style) ----
   double w = InpWCategory + InpWEfficiency + InpWTrend + InpWVolume
            + InpWFlow + InpWTiming + InpWVolatility + InpWStructure;
   if(w <= 0) return 0;
   score = (InpWCategory * cCat + InpWEfficiency * cEff + InpWTrend * cTrend
          + InpWVolume * cVolu + InpWFlow * cFlow + InpWTiming * cTiming
          + InpWVolatility * cVol + InpWStructure * cStruct) / w;

   if(score < InpMinEdgeScore) return 0;              // quality gate (hard)
   return side;
  }

//---------------------------------------------------------------- orders
double NormalizeVolume(double vol)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) vol = MathFloor(vol / step) * step;
   return MathMax(vmin, MathMin(vmax, vol));
  }

double SizeByRisk(double stopDistance)
  {
   if(stopDistance <= 0) return 0;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskCash = equity * InpRiskPerTradePct / 100.0;
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return 0;
   double lossPerLot = stopDistance / tickSize * tickVal;
   return lossPerLot > 0 ? NormalizeVolume(riskCash / lossPerLot) : 0;
  }

void CancelPending()
  {
   if(pendingTicket == 0) return;
   if(OrderSelect(pendingTicket)) trade.OrderDelete(pendingTicket);
   pendingTicket = 0;
   pendingAgeBars = 0;
  }

bool HavePosition() { return PositionSelect(_Symbol)
        && PositionGetInteger(POSITION_MAGIC) == InpMagic; }

void PlaceEntry(int side, double sigma)
  {
   double stopDist = InpStopSigmaMult * sigma;
   double price = side > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                           : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // clamp the stop to the engine's pct band
   double minD = price * InpMinStopPct / 100.0;
   double maxD = price * InpMaxStopPct / 100.0;
   stopDist = MathMax(minD, MathMin(maxD, stopDist));

   double vol = SizeByRisk(stopDist);
   if(vol <= 0) return;

   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(InpPullbackEntry)
     {
      double limit = side > 0 ? price - InpPullbackSigma * sigma
                              : price + InpPullbackSigma * sigma;
      limit = NormalizeDouble(limit, dg);
      double sl = NormalizeDouble(side > 0 ? limit - stopDist : limit + stopDist, dg);
      bool ok = side > 0
         ? trade.BuyLimit(vol, limit, _Symbol, sl, 0, ORDER_TIME_GTC, 0, "tbae")
         : trade.SellLimit(vol, limit, _Symbol, sl, 0, ORDER_TIME_GTC, 0, "tbae");
      if(ok) { pendingTicket = trade.ResultOrder(); pendingAgeBars = 0; }
     }
   else
     {
      double sl = NormalizeDouble(side > 0 ? price - stopDist : price + stopDist, dg);
      if(side > 0) trade.Buy(vol, _Symbol, 0, sl, 0, "tbae");
      else         trade.Sell(vol, _Symbol, 0, sl, 0, "tbae");
     }
  }

void InitPositionState()
  {
   posEntry   = PositionGetDouble(POSITION_PRICE_OPEN);
   posStop0   = PositionGetDouble(POSITION_SL);
   posRiskDist = MathAbs(posEntry - posStop0);
   posPeakR = 0; posBarsHeld = 0;
   tp1Done = tp2Done = beDone = false;
  }

void ManagePosition()
  {
   if(!PositionSelect(_Symbol)) return;
   long side = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
   double vol = PositionGetDouble(POSITION_VOLUME);
   double price = side > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                           : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(posRiskDist <= 0) { InitPositionState(); if(posRiskDist <= 0) return; }

   posBarsHeld++;
   double r = side > 0 ? (price - posEntry) / posRiskDist
                       : (posEntry - price) / posRiskDist;
   posPeakR = MathMax(posPeakR, r);
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   // ---- staged targets (checked on bar close, engine-style) ----
   if(!tp1Done && r >= InpTp1R && InpTp1Share > 0)
     {
      trade.PositionClosePartial(_Symbol, NormalizeVolume(vol * InpTp1Share));
      tp1Done = true;
      return;      // one management action per bar, like the engine's ordering
     }
   if(tp1Done && !tp2Done && r >= InpTp2R && InpTp2Share > 0)
     {
      vol = PositionGetDouble(POSITION_VOLUME);
      trade.PositionClosePartial(_Symbol, NormalizeVolume(vol * InpTp2Share));
      tp2Done = true;
      return;
     }

   // ---- breakeven promotion ----
   double curSL = PositionGetDouble(POSITION_SL);
   if(!beDone && r >= InpBeAfterR)
     {
      double buf = InpBeBufferSigma * Sigma(1);
      double be = side > 0 ? posEntry + buf : posEntry - buf;
      if((side > 0 && be > curSL) || (side < 0 && be < curSL))
         trade.PositionModify(_Symbol, NormalizeDouble(be, dg),
                              PositionGetDouble(POSITION_TP));
      beDone = true;
     }

   // ---- chandelier trail (never loosens) ----
   if(InpTrailEnabled && posPeakR >= InpTrailStartR)
     {
      double atr = Buf(hATR, 0, 1);
      if(atr != EMPTY_VALUE)
        {
         double newSL;
         if(side > 0)
           {
            int hiIdx = iHighest(_Symbol, _Period, MODE_HIGH, InpChandelierPeriod, 1);
            newSL = iHigh(_Symbol, _Period, hiIdx) - InpChandelierMult * atr;
            if(newSL > curSL)
               trade.PositionModify(_Symbol, NormalizeDouble(newSL, dg),
                                    PositionGetDouble(POSITION_TP));
           }
         else
           {
            int loIdx = iLowest(_Symbol, _Period, MODE_LOW, InpChandelierPeriod, 1);
            newSL = iLow(_Symbol, _Period, loIdx) + InpChandelierMult * atr;
            if(newSL < curSL || curSL == 0)
               trade.PositionModify(_Symbol, NormalizeDouble(newSL, dg),
                                    PositionGetDouble(POSITION_TP));
           }
        }
     }

   // ---- profit giveback: peaked >= 1R, gave back >= GiveR ----
   if(posPeakR >= InpGivebackPeakR && (posPeakR - r) >= InpGivebackGiveR)
     { trade.PositionClose(_Symbol); return; }

   // ---- time stops ----
   if(posBarsHeld >= InpTimeStopBars && r < InpTimeStopMinR)
     { trade.PositionClose(_Symbol); return; }
   if(posBarsHeld >= InpMaxBarsHeld)
     { trade.PositionClose(_Symbol); return; }
  }

//---------------------------------------------------------------- events
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   hEmaFast = iMA(_Symbol, _Period, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow = iMA(_Symbol, _Period, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hATR     = iATR(_Symbol, _Period, InpAtrPeriod);
   hADX     = iADX(_Symbol, _Period, 14);
   hRSI     = iRSI(_Symbol, _Period, InpRsiPeriod, PRICE_CLOSE);
   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE ||
      hATR == INVALID_HANDLE || hADX == INVALID_HANDLE || hRSI == INVALID_HANDLE)
      return INIT_FAILED;
   ParseDeadHours();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) {}

void OnTick()
  {
   if(!IsNewBar()) return;                 // closed-bar logic only: no look-ahead

   // day rollover for the cadence caps
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int key = dt.year * 1000 + dt.day_of_year;
   if(key != todayKey) { todayKey = key; signalsToday = 0; tradesToday = 0; }

   // position bookkeeping: detect a fresh fill from the pending order
   if(HavePosition())
     {
      if(posEntry == 0) { PositionSelect(_Symbol); InitPositionState(); tradesToday++; }
      if(pendingTicket != 0 && !OrderSelect(pendingTicket)) { pendingTicket = 0; pendingAgeBars = 0; }
      ManagePosition();
      lastSignalBarIndexAgo++;
      return;
     }
   posEntry = 0;                           // flat: reset per-position state

   // pending order TTL (SignalConfig.pullback_ttl_bars)
   if(pendingTicket != 0)
     {
      if(!OrderSelect(pendingTicket)) { pendingTicket = 0; pendingAgeBars = 0; }
      else
        {
         pendingAgeBars++;
         if(pendingAgeBars >= InpPullbackTTLBars) CancelPending();
         else { lastSignalBarIndexAgo++; return; }   // one working order at a time
        }
     }

   lastSignalBarIndexAgo++;

   // cadence guards (SignalConfig.cooldown_bars / max_signals_per_day,
   // RiskConfig.max_trades_per_day)
   if(lastSignalBarIndexAgo <= InpCooldownBars) return;
   if(InpMaxSignalsPerDay > 0 && signalsToday >= InpMaxSignalsPerDay) return;
   if(InpMaxTradesPerDay > 0 && tradesToday >= InpMaxTradesPerDay) return;

   double score = 0, sigma = 0;
   int side = EvaluateSignal(score, sigma);
   if(side == 0) return;

   signalsToday++;
   lastSignalBarIndexAgo = 0;
   PlaceEntry(side, sigma);
  }
//+------------------------------------------------------------------+
