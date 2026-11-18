//+------------------------------------------------------------------+
//| TBAE_EffortResult.mq5                                            |
//| Two parallel lines on one percentage scale:                      |
//|   aqua   = volume % of the last InpBlock bars   (effort)         |
//|   orange = price move % of the last InpBlock bars (result)       |
//|                                                                  |
//| Reading:                                                         |
//|   both high               -> strong move with real participation |
//|   both low                -> quiet (yellow) range                |
//|   volume above price      -> effort without result: pressure /   |
//|                              absorption, typical at highs/lows   |
//|   price above volume      -> result without effort: explosive,   |
//|                              thin move                           |
//|   arrows mark the crosses: volume crossing up (purple, below)    |
//|   and price crossing up (orange, above).                         |
//|                                                                  |
//| Both use the same trimmed, causal reference as TBAE_FlowState:   |
//| prior complete blocks only, top InpMaxShare set aside as "max",  |
//| InpRefPercentile of the rest = 100%.  Port of                    |
//| tbae/engine/flow_state.py effort_result_lines().                 |
//+------------------------------------------------------------------+
#property copyright "astra66 TBAE"
#property version   "1.00"
#property indicator_separate_window
#property indicator_minimum 0
#property indicator_buffers 4
#property indicator_plots   4
#property indicator_label1  "Volume % (effort)"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrAqua
#property indicator_width1  2
#property indicator_label2  "Price move % (result)"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrOrange
#property indicator_width2  2
#property indicator_label3  "Volume crosses up"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrMediumOrchid
#property indicator_width3  1
#property indicator_label4  "Price crosses up"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrDarkOrange
#property indicator_width4  1
#property indicator_level1  20
#property indicator_level2  55
#property indicator_level3  100
#property indicator_levelcolor clrDimGray
#property indicator_levelstyle STYLE_DOT

input int    InpBlock          = 4;     // bars per block (H1->4h, M5->20m)
input double InpRefDays        = 30.0;  // reference window, days
input double InpRefPercentile  = 98.0;  // percentile taken as 100%
input double InpMaxShare       = 0.02;  // top share set aside as "max"
input int    InpMinRefBlocks   = 60;    // blocks before a reference exists
input int    InpPriceSmooth    = 1;     // EMA period on the price line (1 = none)
input double InpClip           = 200.0; // clip both lines for display
input bool   InpShowCrosses    = true;
input int    InpMaxBars        = 5000;  // history bars to compute

double VolBuf[];
double PriceBuf[];
double XVolBuf[];
double XPriceBuf[];

//+------------------------------------------------------------------+
double Percentile(double &sorted[], int n, double p)
  {
   if(n <= 0) return 0.0;
   if(n == 1) return sorted[0];
   double pos = p / 100.0 * (n - 1);
   int lo = (int)MathFloor(pos);
   int hi = (int)MathCeil(pos);
   return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

double TrimmedRef(double &vals[], int n)
  {
   if(n <= 0) return 0.0;
   ArraySort(vals);
   int nTrim = (int)(n * InpMaxShare);
   if(nTrim >= n) nTrim = 0;
   return Percentile(vals, n - nTrim, InpRefPercentile);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpBlock < 1 || InpPriceSmooth < 1) return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, VolBuf, INDICATOR_DATA);
   SetIndexBuffer(1, PriceBuf, INDICATOR_DATA);
   SetIndexBuffer(2, XVolBuf, INDICATOR_DATA);
   SetIndexBuffer(3, XPriceBuf, INDICATOR_DATA);
   for(int p = 0; p < 4; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetInteger(2, PLOT_ARROW, 233);   // arrow up
   PlotIndexSetInteger(3, PLOT_ARROW, 234);   // arrow down
   PlotIndexSetInteger(2, PLOT_ARROW_SHIFT, 12);
   PlotIndexSetInteger(3, PLOT_ARROW_SHIFT, -12);
   IndicatorSetInteger(INDICATOR_DIGITS, 1);
   IndicatorSetString(INDICATOR_SHORTNAME, "TBAE Effort vs Result");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   if(rates_total < InpBlock * 3) return 0;
   ArraySetAsSeries(time, false);  ArraySetAsSeries(open, false);
   ArraySetAsSeries(close, false); ArraySetAsSeries(tick_volume, false);
   ArraySetAsSeries(volume, false);
   ArraySetAsSeries(VolBuf, false);  ArraySetAsSeries(PriceBuf, false);
   ArraySetAsSeries(XVolBuf, false); ArraySetAsSeries(XPriceBuf, false);

   int start = MathMax(0, rates_total - InpMaxBars);
   for(int i = 0; i < rates_total; i++)
     {
      if(i < start || prev_calculated == 0)
        { VolBuf[i] = EMPTY_VALUE; PriceBuf[i] = EMPTY_VALUE; XVolBuf[i] = EMPTY_VALUE; XPriceBuf[i] = EMPTY_VALUE; }
     }

   // blocks aligned to clock boundaries: volume and |close - open| per block
   long blockSec = (long)PeriodSeconds() * InpBlock;
   int nb = 0;
   long   bKey[];  int bFirst[];  int bN[];  double bVol[];  double bMove[];
   ArrayResize(bKey, 0); ArrayResize(bFirst, 0); ArrayResize(bN, 0);
   ArrayResize(bVol, 0); ArrayResize(bMove, 0);
   int barBlock[];
   ArrayResize(barBlock, rates_total);
   double bOpen = 0.0;
   for(int i = start; i < rates_total; i++)
     {
      long key = (long)time[i] / blockSec;
      double v = volume[i] > 0 ? (double)volume[i] : (double)tick_volume[i];
      if(nb == 0 || bKey[nb - 1] != key)
        {
         ArrayResize(bKey, nb + 1, 1024); ArrayResize(bFirst, nb + 1, 1024); ArrayResize(bN, nb + 1, 1024);
         ArrayResize(bVol, nb + 1, 1024); ArrayResize(bMove, nb + 1, 1024);
         bKey[nb] = key; bFirst[nb] = i; bN[nb] = 0; bVol[nb] = 0.0; bMove[nb] = 0.0;
         bOpen = open[i];
         nb++;
        }
      bN[nb - 1]++;
      bVol[nb - 1] += v;
      bMove[nb - 1] = MathAbs(close[i] - bOpen);
      barBlock[i] = nb - 1;
     }

   int perDay = (int)MathMax(1, MathRound(86400.0 / (double)blockSec));
   int window = (int)MathMax(InpMinRefBlocks, MathRound(InpRefDays * perDay));
   double refV[], refM[];
   ArrayResize(refV, nb); ArrayResize(refM, nb);
   double vv[], mv[];
   ArrayResize(vv, window); ArrayResize(mv, window);
   for(int b = 0; b < nb; b++)
     {
      int c = 0;
      for(int j = MathMax(0, b - window); j < b; j++)
        {
         if(bN[j] != InpBlock) continue;
         vv[c] = bVol[j]; mv[c] = bMove[j]; c++;
        }
      refV[b] = c >= InpMinRefBlocks ? TrimmedRef(vv, c) : 0.0;
      refM[b] = c >= InpMinRefBlocks ? TrimmedRef(mv, c) : 0.0;
     }

   double alpha = 2.0 / (InpPriceSmooth + 1.0);
   double ema = EMPTY_VALUE;
   double prevSpread = EMPTY_VALUE;
   for(int i = start + InpBlock - 1; i < rates_total; i++)
     {
      int b = barBlock[i];
      if(refV[b] <= 0.0 || refM[b] <= 0.0)
        { VolBuf[i] = EMPTY_VALUE; PriceBuf[i] = EMPTY_VALUE; XVolBuf[i] = EMPTY_VALUE; XPriceBuf[i] = EMPTY_VALUE;
          prevSpread = EMPTY_VALUE; continue; }
      double sv = 0.0;
      for(int k = i - InpBlock + 1; k <= i; k++)
         sv += volume[k] > 0 ? (double)volume[k] : (double)tick_volume[k];
      double vp = 100.0 * sv / refV[b];
      double pp = 100.0 * MathAbs(close[i] - open[i - InpBlock + 1]) / refM[b];
      ema = (ema == EMPTY_VALUE || InpPriceSmooth == 1) ? pp : ema + alpha * (pp - ema);
      VolBuf[i]   = MathMin(vp, InpClip);
      PriceBuf[i] = MathMin(ema, InpClip);
      double spr = vp - ema;
      XVolBuf[i] = EMPTY_VALUE; XPriceBuf[i] = EMPTY_VALUE;
      if(InpShowCrosses && prevSpread != EMPTY_VALUE)
        {
         if(prevSpread < 0.0 && spr >= 0.0) XVolBuf[i]   = MathMin(vp, InpClip);
         if(prevSpread >= 0.0 && spr < 0.0) XPriceBuf[i] = MathMin(ema, InpClip);
        }
      prevSpread = spr;
     }
   return rates_total;
  }
//+------------------------------------------------------------------+
