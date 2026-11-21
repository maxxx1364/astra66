//+------------------------------------------------------------------+
//| TBAE_FlowState.mq5                                               |
//| Volume-flow state line — MT5 port of tbae/engine/flow_state.py.  |
//|                                                                  |
//| Line   : mean weighted-delta % of the last InpBlock bars.        |
//| Colour : state of the block (InpBlock bars: H1 -> 4h, M5 -> 20m) |
//|  balanced delta (never a trend):                                 |
//|     quiet=yellow (low volume), balanced=white (more volume),     |
//|     pressure=purple (strong volume)                              |
//|  one-sided delta: trend=green (price followed, vol weak/medium), |
//|     strong=blue (price followed, strong volume),                 |
//|     absorption=pink (price did not follow the delta)             |
//|  explosive=orange (thin volume, big move), max=red               |
//|                                                                  |
//| Weighted delta: every tick counts by its size.                   |
//|   * exchange feeds with buy/sell flags: +volume / -volume;       |
//|   * otherwise the tick rule (up-tick = buy) weighted by the      |
//|     tick's volume, or by the size of its price change when the   |
//|     feed carries no volume (forex/CFD) — so a large tick and a   |
//|     one-point flicker never weigh the same.                      |
//|   * InpDeltaSource=DELTA_BAR is a fast fallback without ticks.   |
//|                                                                  |
//| Percentages use a trimmed reference from PRIOR blocks only: the  |
//| top InpMaxShare of the window is set aside as "max" before the   |
//| InpRefPercentile is taken as 100%.  The forming block repaints   |
//| until it closes; closed blocks never change.                     |
//+------------------------------------------------------------------+
#property copyright "astra66 TBAE"
#property version   "1.00"
#property indicator_separate_window
#property indicator_buffers 2
#property indicator_plots   1
#property indicator_label1  "Flow state"
#property indicator_type1   DRAW_COLOR_LINE
#property indicator_color1  clrGold,clrWhiteSmoke,clrLimeGreen,clrDodgerBlue,clrDarkViolet,clrHotPink,clrDarkOrange,clrRed,clrDimGray
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2
#property indicator_level1  0
#property indicator_level2  20
#property indicator_level3  -20
#property indicator_level4  55
#property indicator_level5  -55
#property indicator_levelcolor clrDimGray
#property indicator_levelstyle STYLE_DOT

enum ENUM_DELTA_SOURCE
  {
   DELTA_TICKS = 0,   // weighted ticks (accurate, slower)
   DELTA_BAR   = 1    // bar approximation: volume * body / range
  };

input int               InpBlock            = 4;     // bars per block (H1->4h, M5->20m)
input double            InpRefDays          = 30.0;  // reference window, days
input double            InpRefPercentile    = 98.0;  // percentile taken as 100%
input double            InpMaxShare         = 0.02;  // top share set aside as "max"
input int               InpMinRefBlocks     = 60;    // blocks before a reference exists
input double            InpWeak             = 20.0;  // weak threshold, %
input double            InpBig              = 55.0;  // big threshold, %
input double            InpMaxLevel         = 100.0; // vol% at/above = max
input ENUM_DELTA_SOURCE InpDeltaSource      = DELTA_TICKS;
input int               InpMaxBars          = 5000;  // history bars to compute

//--- state indexes = colour indexes above
#define ST_QUIET      0
#define ST_BALANCED   1
#define ST_TREND      2
#define ST_STRONG     3
#define ST_PRESSURE   4
#define ST_ABSORPTION 5
#define ST_EXPLOSIVE  6
#define ST_MAX        7
#define ST_UNREADY    8

string StateName[9] = {"quiet","balanced","trend","strong","pressure","absorption","explosive","max","no reference"};

double LineBuf[];
double ColorBuf[];
double gVol[];
double gDelta[];
bool   gHave[];

struct Block
  {
   long   key;
   int    first;
   int    last;
   int    n;
   double vol;
   double delta;
   double open;
   double close;
   double refDelta;
   int    state;
  };
Block gBlocks[];

//+------------------------------------------------------------------+
double Percentile(double &sorted[], int n, double p)
  {
   if(n <= 0) return 0.0;
   if(n == 1) return sorted[0];
   double pos = p / 100.0 * (n - 1);
   int lo = (int)MathFloor(pos);
   int hi = (int)MathCeil(pos);
   double fr = pos - lo;
   return sorted[lo] + (sorted[hi] - sorted[lo]) * fr;
  }

// trimmed reference: drop the top share, take the percentile of the rest
double TrimmedRef(double &vals[], int n, double &trimmedMean)
  {
   trimmedMean = 0.0;
   if(n <= 0) return 0.0;
   ArraySort(vals);
   int nTrim = (int)(n * InpMaxShare);
   if(nTrim >= n) nTrim = 0;
   int kept = n - nTrim;
   double s = 0.0;
   for(int k = 0; k < kept; k++) s += vals[k];
   trimmedMean = s / kept;
   return Percentile(vals, kept, InpRefPercentile);
  }

//+------------------------------------------------------------------+
double TickDelta(datetime t0, datetime t1)
  {
   MqlTick ticks[];
   ulong from = (ulong)t0 * 1000;
   ulong to   = (ulong)t1 * 1000 - 1;
   int n = CopyTicksRange(_Symbol, ticks, COPY_TICKS_ALL, from, to);
   if(n <= 0) return EMPTY_VALUE;
   double delta = 0.0, prev = 0.0;
   int lastSign = 0;
   for(int k = 0; k < n; k++)
     {
      double px = ticks[k].last;
      if(px <= 0.0)
         px = (ticks[k].bid > 0.0 && ticks[k].ask > 0.0) ? 0.5 * (ticks[k].bid + ticks[k].ask) : ticks[k].bid;
      double w = ticks[k].volume_real > 0.0 ? ticks[k].volume_real : (double)ticks[k].volume;
      uint f = ticks[k].flags;
      if(w > 0.0 && (f & TICK_FLAG_BUY) != 0 && (f & TICK_FLAG_SELL) == 0) { delta += w; prev = px; lastSign = 1; continue; }
      if(w > 0.0 && (f & TICK_FLAG_SELL) != 0 && (f & TICK_FLAG_BUY) == 0) { delta -= w; prev = px; lastSign = -1; continue; }
      if(prev > 0.0 && px > 0.0)
        {
         double ch = px - prev;
         int s = ch > 0.0 ? 1 : (ch < 0.0 ? -1 : lastSign);
         double wt = w > 0.0 ? w : MathAbs(ch) / _Point;
         delta += s * wt;
         if(s != 0) lastSign = s;
        }
      if(px > 0.0) prev = px;
     }
   return delta;
  }

//+------------------------------------------------------------------+
void ComputeBarFlow(int i, const datetime &time[], const double &open[], const double &high[],
                    const double &low[], const double &close[], const long &tick_volume[],
                    const long &volume[], int rates_total)
  {
   double vol = volume[i] > 0 ? (double)volume[i] : (double)tick_volume[i];
   double delta = EMPTY_VALUE;
   if(InpDeltaSource == DELTA_TICKS)
     {
      datetime t1 = (i + 1 < rates_total) ? time[i + 1] : time[i] + PeriodSeconds();
      delta = TickDelta(time[i], t1);
     }
   if(delta == EMPTY_VALUE)
     {
      double rng = high[i] - low[i];
      delta = rng > 0.0 ? vol * (close[i] - open[i]) / rng : 0.0;
     }
   gVol[i] = vol;
   gDelta[i] = delta;
   gHave[i] = true;
  }

int Classify(const Block &b, double volPct, double deltaPct, double movePct, double meanVol)
  {
   double mv = b.close - b.open;
   if(volPct >= InpMaxLevel) return ST_MAX;
   if(b.vol < meanVol && movePct >= InpBig) return ST_EXPLOSIVE;
   if(MathAbs(deltaPct) < InpWeak)                 // balanced delta: never a trend
     {
      if(volPct >= InpBig)  return ST_PRESSURE;
      if(volPct >= InpWeak) return ST_BALANCED;
      return ST_QUIET;
     }
   bool followed = movePct >= InpWeak && ((mv > 0.0 && deltaPct > 0.0) || (mv < 0.0 && deltaPct < 0.0));
   if(followed) return volPct >= InpBig ? ST_STRONG : ST_TREND;
   return ST_ABSORPTION;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpBlock < 1 || !(InpWeak > 0 && InpWeak < InpBig && InpBig < InpMaxLevel))
      return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, LineBuf, INDICATOR_DATA);
   SetIndexBuffer(1, ColorBuf, INDICATOR_COLOR_INDEX);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetInteger(INDICATOR_DIGITS, 1);
   IndicatorSetString(INDICATOR_SHORTNAME, "TBAE Flow State");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   if(rates_total < InpBlock * 3) return 0;
   ArraySetAsSeries(time, false);   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);  ArraySetAsSeries(tick_volume, false);
   ArraySetAsSeries(volume, false);
   ArraySetAsSeries(LineBuf, false); ArraySetAsSeries(ColorBuf, false);

   if(prev_calculated == 0)
     {
      ArrayResize(gVol, 0); ArrayResize(gDelta, 0); ArrayResize(gHave, 0);
     }
   int oldSize = ArraySize(gHave);
   ArrayResize(gVol, rates_total); ArrayResize(gDelta, rates_total); ArrayResize(gHave, rates_total);
   for(int k = oldSize; k < rates_total; k++) gHave[k] = false;

   int start = MathMax(0, rates_total - InpMaxBars);
   // flow: compute missing bars, always redo the two newest (the last one is forming)
   for(int i = start; i < rates_total; i++)
      if(!gHave[i] || i >= rates_total - 2)
         ComputeBarFlow(i, time, open, high, low, close, tick_volume, volume, rates_total);

   // blocks aligned to clock boundaries
   long blockSec = (long)PeriodSeconds() * InpBlock;
   ArrayResize(gBlocks, 0);
   int nb = 0;
   for(int i = start; i < rates_total; i++)
     {
      long key = (long)time[i] / blockSec;
      if(nb == 0 || gBlocks[nb - 1].key != key)
        {
         ArrayResize(gBlocks, nb + 1, 1024);
         gBlocks[nb].key = key; gBlocks[nb].first = i; gBlocks[nb].n = 0;
         gBlocks[nb].vol = 0.0; gBlocks[nb].delta = 0.0; gBlocks[nb].open = open[i];
         gBlocks[nb].refDelta = 0.0; gBlocks[nb].state = ST_UNREADY;
         nb++;
        }
      gBlocks[nb - 1].last = i;
      gBlocks[nb - 1].n++;
      gBlocks[nb - 1].vol += gVol[i];
      gBlocks[nb - 1].delta += gDelta[i];
      gBlocks[nb - 1].close = close[i];
     }

   int perDay = (int)MathMax(1, MathRound(86400.0 / (double)blockSec));
   int window = (int)MathMax(InpMinRefBlocks, MathRound(InpRefDays * perDay));
   double vv[], dv[], mv[];
   ArrayResize(vv, window); ArrayResize(dv, window); ArrayResize(mv, window);

   for(int b = 0; b < nb; b++)
     {
      int c = 0;
      for(int j = MathMax(0, b - window); j < b; j++)
        {
         if(gBlocks[j].n != InpBlock) continue;
         vv[c] = gBlocks[j].vol;
         dv[c] = MathAbs(gBlocks[j].delta);
         mv[c] = MathAbs(gBlocks[j].close - gBlocks[j].open);
         c++;
        }
      if(c < InpMinRefBlocks) { gBlocks[b].state = ST_UNREADY; continue; }
      double meanVol = 0.0, dummy = 0.0;
      double refVol = TrimmedRef(vv, c, meanVol);
      double refDel = TrimmedRef(dv, c, dummy);
      double refMov = TrimmedRef(mv, c, dummy);
      if(refVol <= 0.0 || refDel <= 0.0 || refMov <= 0.0) { gBlocks[b].state = ST_UNREADY; continue; }
      double volPct = 100.0 * gBlocks[b].vol / refVol;
      double delPct = 100.0 * gBlocks[b].delta / refDel;
      double movPct = 100.0 * MathAbs(gBlocks[b].close - gBlocks[b].open) / refMov;
      gBlocks[b].refDelta = refDel;
      gBlocks[b].state = Classify(gBlocks[b], volPct, delPct, movPct, meanVol);
     }

   // line: mean of the last InpBlock bar delta %, coloured by the bar's block
   for(int i = 0; i < start; i++) { LineBuf[i] = EMPTY_VALUE; ColorBuf[i] = ST_UNREADY; }
   double win[];
   ArrayResize(win, InpBlock);
   int wn = 0, wpos = 0;
   for(int b = 0; b < nb; b++)
     {
      for(int i = gBlocks[b].first; i <= gBlocks[b].last; i++)
        {
         ColorBuf[i] = gBlocks[b].state;
         if(gBlocks[b].refDelta <= 0.0) { LineBuf[i] = EMPTY_VALUE; wn = 0; wpos = 0; continue; }
         double pct = gDelta[i] * 100.0 / gBlocks[b].refDelta * InpBlock;
         win[wpos] = pct; wpos = (wpos + 1) % InpBlock; if(wn < InpBlock) wn++;
         double s = 0.0;
         for(int k = 0; k < wn; k++) s += win[k];
         LineBuf[i] = s / wn;
        }
     }

   if(nb > 0)
      IndicatorSetString(INDICATOR_SHORTNAME,
                         "TBAE Flow State: " + StateName[gBlocks[nb - 1].state] +
                         (gBlocks[nb - 1].n < InpBlock ? " (forming)" : ""));
   return rates_total;
  }
//+------------------------------------------------------------------+
