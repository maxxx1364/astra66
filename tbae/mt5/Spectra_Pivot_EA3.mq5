//+------------------------------------------------------------------+
//| Spectra_Pivot_EA3 - adaptive pivot trend EA + TBAE order flow    |
//| Cloud   : prior-bar typical-price 20/50/80 percentiles           |
//| Pivot   : swing level near the median, most tested, hysteresis   |
//| State   : MTF_ColorLine causal state, computed internally        |
//| Flow    : TBAE flow state (TBAE_FlowState / TBAE_EffortResult),  |
//|           computed internally from size-weighted delta, volume   |
//|           and move per InpFlowBlock-bar block                    |
//| Entries : liquidity sweep, pivot retest (one per touch), cloud   |
//|           edge retest (level 2), projected level retest (level   |
//|           3), narrow-cloud breakout - each filtered by the flow  |
//| Stops   : beyond the cloud, trailed by cloud / pivot / hybrid    |
//| All values are computed once per closed bar, no indicators.      |
//| Outside the Strategy Tester it only logs unless InpAllowLive.    |
//|                                                                  |
//| What the flow layer adds (measured on 3y of BTC/ETH/SOL/XRP,     |
//| 1h chart / 4h blocks, see tbae/docs/FLOW_STATE.md):              |
//|  * veto after a "balanced" (white) or "explosive" block: entries |
//|    after a balanced block averaged -0.09R in-sample and -0.07R   |
//|    out-of-sample in the TBAE strategy; the veto lifted its       |
//|    out-of-sample E[R] from -0.012R to +0.012R                    |
//|  * breakouts: a level break on a max block held 68% vs 54% for   |
//|    all breaks; on an absorption block only 37%; against the      |
//|    delta 48%  -> the squeeze breakout needs max/strong/trend     |
//|    and an agreeing delta                                         |
//|  * reversals (optional, untested in this EA): swing highs/lows   |
//|    sit on volume% far above move% (45% vs 27% base), pressure    |
//|    and max blocks                                                |
//| These were measured on crypto with exchange aggressor delta and  |
//| on a different strategy.  Run this EA in the tester with         |
//| InpUseFlow on and off, and InpExport on, before trusting them.   |
//+------------------------------------------------------------------+
#property strict
#property version "3.00"
#property description "Adaptive pivot trend EA with TBAE order-flow filters"
#include <Trade/Trade.mqh>

enum ENUM_TRAIL { TRAIL_CLOUD=0, TRAIL_PIVOT=1, TRAIL_HYBRID=2 };

input group "Safety"
input bool   InpAllowLive=false;        // false: outside the tester only log signals
input long   InpMagic=26111603;
input group "Signals"
input bool   InpUseSweep=true;          // liquidity sweep aligned with the pivot inside the cloud
input bool   InpUsePivotRetest=true;    // retest of a respected pivot
input bool   InpUseLevel2=true;         // retest of the cloud edge while trending away from the pivot
input bool   InpUseLevel3=true;         // retest of edge + (edge - pivot)
input bool   InpUseSqueeze=true;        // close out of a narrow cloud
input double InpSqueezeMax=2.0;         // cloud width / ATR at or below this counts as narrow
input double InpMinPulse=0.35;          // squeeze bar close-to-close move, ATR
input double InpRearmATR=1.0;           // a level re-arms after price closes this far from it
input bool   InpAllowRange=true;        // allow retests while the state is RANGE
input bool   InpBlockMixed=false;
input bool   InpShortInBounce=false;    // gold: the colour line's down-bounce state is not a reliable downtrend
input group "Order flow (TBAE)"
input bool   InpUseFlow=true;                       // master switch for every flow filter below
input string InpFlowVeto="balanced,explosive";      // no entry after a block in these states
input bool   InpBreakoutFlow=true;                  // squeeze breakout needs a state below and an agreeing delta
input string InpBreakoutStates="max,strong,trend";  // states a squeeze breakout may fire in
input bool   InpReversalEffort=false;               // sweep/pivot retest need effort > result (untested here)
input double InpEffortSpread=10.0;                  // volume% - move% at or above this counts as effort
input bool   InpFlowDeltaAgree=false;               // every entry needs the last block's delta on its side
input bool   InpFlowNeedReady=false;                // block entries until the flow reference exists
input int    InpFlowBlock=4;                        // bars per block (H1 -> 4h, M5 -> 20m)
input bool   InpFlowTicks=true;                     // weighted delta from ticks (else bar approximation)
input double InpFlowRefDays=30.0;                   // reference window, days
input double InpFlowPct=98.0;                       // percentile taken as 100%
input double InpFlowMaxShare=0.02;                  // top share set aside as "max"
input int    InpFlowMinRef=60;                      // complete blocks before a reference exists
input double InpFlowWeak=20.0;                      // weak level, %
input double InpFlowBig=55.0;                       // strong level, %
input double InpFlowMax=100.0;                      // volume% at or above = max
input group "Risk and exits"
input double InpRiskPercent=1.0;        // equity % risked per trade
input double InpSLBufferATR=0.30;       // stop distance beyond the cloud edge
input double InpMaxSLATR=6.0;           // skip if the cloud stop is farther than this
input ENUM_TRAIL InpTrail=TRAIL_HYBRID;
input double InpHybridR=3.0;            // HYBRID: once profit has reached this R, also trail with the pivot
input double InpTargetR=0.0;            // fixed target in R (0 = none, the trail exits)
input double InpBreakevenR=0.0;         // 0 = off
input bool   InpExitOppositeImpulse=false;
input group "Cloud and pivot"
input int    InpLookback=96;
input int    InpATRPeriod=14;
input int    InpSwingStrength=3;
input double InpSnapATR=0.75;
input double InpHysteresisATR=0.35;
input double InpTouchATR=0.20;
input int    InpRespectWindow=120;
input int    InpMinTouches=3;
input double InpMinRespect=0.55;
input double InpSweepATR=0.10;
input int    InpWarmupBars=1000;
input group "Research"
input bool   InpExport=false;           // write bars/signals/trades CSV to the Common\Files folder
input string InpExportTag="spv3";

#define ST_UP_IMPULSE 0
#define ST_UP_PULLBACK 1
#define ST_DN_IMPULSE 2
#define ST_DN_BOUNCE 3
#define ST_RANGE 4
#define ST_CLIMAX 5
#define ST_MIXED 6
const int CELL2CLASS[9]={0,0,4, 1,5,4, 2,2,3};
const string TYPES[5]={"sweep","pivot","level2","level3","squeeze"};

//--- TBAE flow states (same rules as tbae/engine/flow_state.py)
#define FS_UNREADY   -1
#define FS_MAX        0
#define FS_EXPLOSIVE  1
#define FS_PRESSURE   2
#define FS_BALANCED   3
#define FS_QUIET      4
#define FS_STRONG     5
#define FS_TREND      6
#define FS_ABSORPTION 7
#define FS_COUNT      8
const string FSNAME[8]={"max","explosive","pressure","balanced","quiet","strong","trend","absorption"};

CTrade trade;
bool   tradingOn=false;
int    g_N=24;
int    n=0;
datetime T[];
double O[],H[],L[],C[],V[],TR[];
double ATRc[],Lo[],Up[],Mid[],Piv[],Resp[];
int    Tch[];
double ATRm[],DR[],E24[],E96[];
int    BC[],StRaw[],St[];
double g_s[];
bool   armP=true,armL2=true,armL3=true;
int    l2Dir=0,l3Dir=0;
ulong  g_pivotLatch=0;          // position whose profit has already reached InpHybridR
int    dSig[5],dState=0,dMaxSL=0,dLots=0,dFlow=0;
string g_sig[]; int g_nsig=0;   // research log of every candidate signal

//--- flow, per bar: volume, weighted delta, and the state known at the bar's close
double FV[],FD[],FVp[],FDp[],FMp[];
int    FS[];
//--- flow, per block
long   bKey[];
int    bCnt[],bState[];
double bVol[],bDel[],bOpen[],bClose[],bVp[],bDp[],bMp[];
bool   bDone[];
int    nb=0;
long   g_blockSec=0;
int    g_refWin=180;
double g_fv[],g_fd[],g_fm[];
bool   g_veto[FS_COUNT];
bool   g_breakOk[FS_COUNT];

string FlowName(const int fs) { return (fs>=0 && fs<FS_COUNT)?FSNAME[fs]:"unready"; }

void LogSignal(const int i,const int type,const int dir,const string status,const double sl,const double atr)
{
   if(!InpExport) return;
   if(g_nsig>=ArraySize(g_sig)) ArrayResize(g_sig,g_nsig+1024);
   g_sig[g_nsig++]=StringFormat("%s,%d,%s,%d,%s,%.5f,%.5f,%.5f,%d,%.3f,%d,%.3f,%s,%.1f,%.1f,%.1f",
      TimeToString(T[i],TIME_DATE|TIME_MINUTES),i,TYPES[type],dir,status,C[i],sl,atr,St[i],
      (Up[i]-Lo[i])/atr,Tch[i],Resp[i],FlowName(FS[i]),FVp[i],FDp[i],FMp[i]);
}

bool Num(const double x) { return MathIsValidNumber(x) && x!=EMPTY_VALUE; }
int  Level(const double x,const double lo,const double hi) { return (x<lo)?0:((x>=hi)?2:1); }

double Quantile(const double &s[],const int cnt,const double q)
{
   double p=q*(cnt-1);
   int a=(int)MathFloor(p),b=(int)MathCeil(p);
   return s[a]+(s[b]-s[a])*(p-a);
}

void Grow()
{
   if(ArraySize(C)>n) return;
   int m=n+4096;
   ArrayResize(T,m); ArrayResize(O,m); ArrayResize(H,m); ArrayResize(L,m); ArrayResize(C,m);
   ArrayResize(V,m); ArrayResize(TR,m); ArrayResize(ATRc,m); ArrayResize(Lo,m); ArrayResize(Up,m);
   ArrayResize(Mid,m); ArrayResize(Piv,m); ArrayResize(Resp,m); ArrayResize(Tch,m);
   ArrayResize(ATRm,m); ArrayResize(DR,m); ArrayResize(E24,m); ArrayResize(E96,m);
   ArrayResize(BC,m); ArrayResize(StRaw,m); ArrayResize(St,m);
   ArrayResize(FV,m); ArrayResize(FD,m); ArrayResize(FVp,m); ArrayResize(FDp,m); ArrayResize(FMp,m);
   ArrayResize(FS,m);
}

void GrowBlocks()
{
   if(ArraySize(bKey)>nb) return;
   int m=nb+1024;
   ArrayResize(bKey,m); ArrayResize(bCnt,m); ArrayResize(bState,m); ArrayResize(bVol,m);
   ArrayResize(bDel,m); ArrayResize(bOpen,m); ArrayResize(bClose,m); ArrayResize(bVp,m);
   ArrayResize(bDp,m); ArrayResize(bMp,m); ArrayResize(bDone,m);
}

// chronological indexing: 0 = oldest; a swing at c is confirmed at bar c+r
bool SwHigh(const int c,const int r)
{
   if(c-r<0 || c+r>=n) return false;
   for(int j=1;j<=r;j++) if(H[c+j]>=H[c] || H[c-j]>H[c]) return false;
   return true;
}

bool SwLow(const int c,const int r)
{
   if(c-r<0 || c+r>=n) return false;
   for(int j=1;j<=r;j++) if(L[c+j]<=L[c] || L[c-j]<L[c]) return false;
   return true;
}

//--- MTF_ColorLine causal state (same formulas as the indicator)
void ComputeState(const int i)
{
   double a24=2.0/25.0,a96=2.0/97.0,alN=2.0/(g_N+1.0);
   int minp=g_N/2;
   if(i>=13) { double s=0; for(int j=i-13;j<=i;j++) s+=TR[j]; ATRm[i]=s/14.0; } else ATRm[i]=0;
   if(i<minp-1) DR[i]=0;
   else
   {
      int cnt=MathMin(i+1,g_N); double mx=H[i],mn=L[i];
      for(int j=i-cnt+1;j<i;j++) { if(H[j]>mx) mx=H[j]; if(L[j]<mn) mn=L[j]; }
      double raw=mx-mn;
      DR[i]=(i==minp-1 || DR[i-1]<=0)?raw:alN*raw+(1.0-alN)*DR[i-1];
   }
   E24[i]=(i==0)?C[0]:a24*C[i]+(1.0-a24)*E24[i-1];
   E96[i]=(i==0)?C[0]:a96*C[i]+(1.0-a96)*E96[i-1];
   int bc=6,j0=MathMax(0,i-50),m=i-j0;
   if(m>=30)
   {
      double sv=0,st=0;
      for(int j=j0;j<i;j++)
      {
         sv+=V[j];
         double hh=H[j],ll=L[j]; if(j>0) { hh=MathMax(hh,C[j-1]); ll=MathMin(ll,C[j-1]); }
         st+=hh-ll;
      }
      double h0=H[i],l0=L[i]; if(i>0) { h0=MathMax(h0,C[i-1]); l0=MathMin(l0,C[i-1]); }
      double vb=sv/m,tb=st/m;
      if(vb>0 && tb>0) bc=CELL2CLASS[Level(V[i]/vb,0.75,1.20)*3+Level((h0-l0)/tb,0.70,1.10)];
   }
   BC[i]=bc;
   int raw=-1;
   double atr=ATRm[i],dr=DR[i];
   if(i>=30 && dr>0 && atr>0)
   {
      double mx24=H[i],mn24=L[i];
      for(int j=i-23;j<i;j++) { if(H[j]>mx24) mx24=H[j]; if(L[j]<mn24) mn24=L[j]; }
      double path=0; for(int j=i-29;j<=i;j++) path+=MathAbs(C[j]-C[j-1]);
      if(path>0)
      {
         double er30=MathAbs(C[i]-C[i-30])/path;
         double slope96=(E96[i]-E96[i-16])/atr,dist96=(C[i]-E96[i])/atr,dist24=(C[i]-E24[i])/atr;
         double ret4=(C[i]-C[i-4])/atr,ret12=(C[i]-C[i-12])/atr;
         double wid24=(mx24-mn24)/dr,pos24=(mx24>mn24)?(C[i]-mn24)/(mx24-mn24):0.5;
         bool upT=(slope96>0.15 && dist96>0),dnT=(slope96<-0.15 && dist96<0);
         bool push=(ret4>=0 && dist24>=0),neg=(ret4<=0 && dist24<=0);
         bool rng=(wid24<=0.6 && er30<=0.25);
         bool climax=(bc==3) && MathAbs(ret12)>=2.5 && ((pos24>=0.9 && ret12>0)||(pos24<=0.1 && ret12<0));
         raw=6;
         if(upT && push) raw=0; else if(upT) raw=1; else if(dnT && neg) raw=2; else if(dnT) raw=3;
         if(rng) raw=4;
         if(climax) raw=5;
      }
   }
   StRaw[i]=raw;
   if(i==0) St[i]=raw;
   else
   {
      int cur=St[i-1];
      if(raw==cur || raw==5 || raw==StRaw[i-1]) cur=raw;
      St[i]=cur;
   }
}

double StructPivot(const int i,const double mid,const double atr)
{
   double best=mid,bestScore=0.0,tol=InpTouchATR*atr;
   int r=InpSwingStrength;
   for(int c=i-r;c>=i-InpLookback && c-r>=0;c--)
   {
      for(int side=0;side<2;side++)
      {
         double level;
         if(side==0) { if(!SwHigh(c,r)) continue; level=H[c]; }
         else        { if(!SwLow(c,r))  continue; level=L[c]; }
         double dist=MathAbs(level-mid)/atr;
         if(dist>InpSnapATR) continue;
         int touches=0;
         for(int j=c+r+1;j<=i;j++) if(L[j]<=level+tol && H[j]>=level-tol) touches++;
         double score=(1.0+touches)*(1.0-0.5*dist/InpSnapATR);
         if(score>bestScore) { bestScore=score; best=level; }
      }
   }
   return best;
}

void ComputeCloud(const int i)
{
   Lo[i]=Up[i]=Mid[i]=Piv[i]=ATRc[i]=EMPTY_VALUE; Resp[i]=0; Tch[i]=0;
   if(i<InpLookback || i<InpATRPeriod+1) return;
   for(int j=0;j<InpLookback;j++) { int k=i-1-j; g_s[j]=(H[k]+L[k]+C[k])/3.0; }
   ArraySort(g_s);
   double lo=Quantile(g_s,InpLookback,0.20),up=Quantile(g_s,InpLookback,0.80),mid=Quantile(g_s,InpLookback,0.50);
   double sum=0; for(int j=1;j<=InpATRPeriod;j++) sum+=TR[i-j];
   double atr=sum/InpATRPeriod;
   if(atr<=0 || up<=lo) return;
   Lo[i]=lo; Up[i]=up; Mid[i]=mid; ATRc[i]=atr;
   double cand=StructPivot(i,mid,atr),prev=Piv[i-1],piv=cand;
   if(Num(prev) && MathAbs(cand-prev)<InpHysteresisATR*atr && prev>=lo-atr && prev<=up+atr) piv=prev;
   Piv[i]=piv;
   int touches=0,holds=0;
   for(int k=i;k>i-InpRespectWindow && k-1>=0;k--)
   {
      double p=Piv[k],pp=Piv[k-1],a=ATRc[k];
      if(!Num(p) || !Num(pp) || !Num(a) || a<=0) continue;
      double tol=InpTouchATR*a;
      if(L[k]>p+tol || H[k]<p-tol) continue;
      double before=C[k-1]-pp;
      if(MathAbs(before)<=tol) continue;
      touches++;
      if(before*(C[k]-p)>0) holds++;
   }
   Tch[i]=touches; Resp[i]=(touches>0)?(double)holds/touches:0.0;
}

//==================================================================
// TBAE order flow
//==================================================================
// Size-weighted delta of one bar.  Exchange ticks with buy/sell flags count
// +volume/-volume; otherwise the tick rule (up-tick = buy) weighted by the
// tick's volume, or by the size of its price change when the feed carries no
// volume (forex/CFD), so a large tick and a one-point flicker never weigh the
// same.  Falls back to volume * body / range without ticks.
double BarDelta(const MqlRates &r,const double vol)
{
   if(InpFlowTicks)
   {
      MqlTick ticks[];
      ulong from=(ulong)r.time*1000;
      ulong to=((ulong)r.time+(ulong)PeriodSeconds(_Period))*1000-1;
      int cnt=CopyTicksRange(_Symbol,ticks,COPY_TICKS_ALL,from,to);
      if(cnt>1)
      {
         double delta=0.0,prev=0.0;
         int lastSign=0;
         for(int k=0;k<cnt;k++)
         {
            double px=ticks[k].last;
            if(px<=0.0) px=(ticks[k].bid>0.0 && ticks[k].ask>0.0)?0.5*(ticks[k].bid+ticks[k].ask):ticks[k].bid;
            double w=(ticks[k].volume_real>0.0)?ticks[k].volume_real:(double)ticks[k].volume;
            uint f=ticks[k].flags;
            bool fb=((f&TICK_FLAG_BUY)!=0),fs=((f&TICK_FLAG_SELL)!=0);
            if(w>0.0 && fb && !fs) { delta+=w; if(px>0.0) prev=px; lastSign=1; continue; }
            if(w>0.0 && fs && !fb) { delta-=w; if(px>0.0) prev=px; lastSign=-1; continue; }
            if(prev>0.0 && px>0.0)
            {
               double ch=px-prev;
               int s=(ch>0.0)?1:((ch<0.0)?-1:lastSign);
               double wt=(w>0.0)?w:MathAbs(ch)/_Point;
               delta+=s*wt;
               if(s!=0) lastSign=s;
            }
            if(px>0.0) prev=px;
         }
         return delta;
      }
   }
   double rng=r.high-r.low;
   return (rng>0.0)?vol*(r.close-r.open)/rng:0.0;
}

// trimmed reference: drop the top share, take the percentile of the rest
double TrimRef(const double &src[],const int cnt,double &trimMean)
{
   trimMean=0.0;
   if(cnt<=0) return 0.0;
   double tmp[];
   ArrayResize(tmp,cnt);
   ArrayCopy(tmp,src,0,0,cnt);
   ArraySort(tmp);
   int nTrim=(int)(cnt*InpFlowMaxShare);
   if(nTrim>=cnt) nTrim=0;
   int kept=cnt-nTrim;
   double s=0.0;
   for(int k=0;k<kept;k++) s+=tmp[k];
   trimMean=s/kept;
   return Quantile(tmp,kept,InpFlowPct/100.0);
}

int FlowClassify(const double vol,const double meanV,const double vp,const double dp,const double mp,const double mv)
{
   if(vp>=InpFlowMax) return FS_MAX;
   if(vol<meanV && mp>=InpFlowBig) return FS_EXPLOSIVE;
   if(MathAbs(dp)<InpFlowWeak)                     // balanced delta: never a trend
   {
      if(vp>=InpFlowBig)  return FS_PRESSURE;
      if(vp>=InpFlowWeak) return FS_BALANCED;
      return FS_QUIET;
   }
   bool followed=(mp>=InpFlowWeak) && ((mv>0.0 && dp>0.0) || (mv<0.0 && dp<0.0));
   if(followed) return (vp>=InpFlowBig)?FS_STRONG:FS_TREND;
   return FS_ABSORPTION;
}

// reference from complete blocks strictly before b: causal
void FinalizeBlock(const int b)
{
   bDone[b]=true; bState[b]=FS_UNREADY; bVp[b]=0; bDp[b]=0; bMp[b]=0;
   int c=0;
   for(int j=b-1;j>=0 && c<g_refWin;j--)
   {
      if(!bDone[j] || bCnt[j]!=InpFlowBlock) continue;
      g_fv[c]=bVol[j]; g_fd[c]=MathAbs(bDel[j]); g_fm[c]=MathAbs(bClose[j]-bOpen[j]); c++;
   }
   if(c<InpFlowMinRef) return;
   double meanV=0.0,dummy=0.0;
   double rv=TrimRef(g_fv,c,meanV);
   double rd=TrimRef(g_fd,c,dummy);
   double rm=TrimRef(g_fm,c,dummy);
   if(rv<=0.0 || rd<=0.0 || rm<=0.0) return;
   double mv=bClose[b]-bOpen[b];
   bVp[b]=100.0*bVol[b]/rv;
   bDp[b]=100.0*bDel[b]/rd;
   bMp[b]=100.0*MathAbs(mv)/rm;
   bState[b]=FlowClassify(bVol[b],meanV,bVp[b],bDp[b],bMp[b],mv);
}

void FlowAddBar(const int i)
{
   long key=(long)T[i]/g_blockSec;
   if(nb==0 || bKey[nb-1]!=key)
   {
      if(nb>0 && !bDone[nb-1]) FinalizeBlock(nb-1);
      GrowBlocks();
      int nbIdx=nb++;
      bKey[nbIdx]=key; bCnt[nbIdx]=0; bVol[nbIdx]=0.0; bDel[nbIdx]=0.0;
      bOpen[nbIdx]=O[i]; bClose[nbIdx]=C[i]; bState[nbIdx]=FS_UNREADY; bDone[nbIdx]=false;
      bVp[nbIdx]=0.0; bDp[nbIdx]=0.0; bMp[nbIdx]=0.0;
   }
   int b=nb-1;
   bCnt[b]++; bVol[b]+=FV[i]; bDel[b]+=FD[i]; bClose[b]=C[i];
   if((long)T[i]+(long)PeriodSeconds(_Period)>=(key+1)*g_blockSec) FinalizeBlock(b);   // this bar closes its block
   // the state a decision at this bar's close may use: the latest finished block, if complete
   FS[i]=FS_UNREADY; FVp[i]=0.0; FDp[i]=0.0; FMp[i]=0.0;
   for(int k=nb-1;k>=0 && k>=nb-2;k--)
   {
      if(!bDone[k]) continue;
      if(bCnt[k]==InpFlowBlock) { FS[i]=bState[k]; FVp[i]=bVp[k]; FDp[i]=bDp[k]; FMp[i]=bMp[k]; }
      break;
   }
}

bool FlowAllows(const int i,const int dir,const int type,string &why)
{
   why="";
   if(!InpUseFlow) return true;
   int fs=FS[i];
   if(fs<0)
   {
      if(InpFlowNeedReady) { why="unready"; return false; }
      return true;
   }
   if(g_veto[fs]) { why="veto_"+FSNAME[fs]; return false; }
   int dsg=(FDp[i]>0.0)?1:((FDp[i]<0.0)?-1:0);
   if(type==4 && InpBreakoutFlow && (!g_breakOk[fs] || dsg!=dir))
   {
      why="break_"+FSNAME[fs]+(dsg!=dir?"_delta":"");
      return false;
   }
   if((type==0 || type==1) && InpReversalEffort)
   {
      bool effort=(FVp[i]-FMp[i]>=InpEffortSpread) || fs==FS_PRESSURE || fs==FS_MAX || fs==FS_ABSORPTION;
      if(!effort) { why="noeffort_"+FSNAME[fs]; return false; }
   }
   if(InpFlowDeltaAgree && dsg!=0 && dsg!=dir) { why="delta_"+FSNAME[fs]; return false; }
   return true;
}

bool ParseStates(const string list,bool &mask[],const string what)
{
   for(int k=0;k<FS_COUNT;k++) mask[k]=false;
   string parts[];
   int cnt=StringSplit(list,',',parts);
   for(int k=0;k<cnt;k++)
   {
      string s=parts[k];
      StringTrimLeft(s); StringTrimRight(s); StringToLower(s);
      if(s=="") continue;
      bool found=false;
      for(int q=0;q<FS_COUNT;q++) if(FSNAME[q]==s) { mask[q]=true; found=true; }
      if(!found)
      {
         PrintFormat("[SPV3] unknown flow state '%s' in %s; known: max, explosive, pressure, balanced, quiet, strong, trend, absorption",s,what);
         return false;
      }
   }
   return true;
}

void AddBar(const MqlRates &r)
{
   Grow();
   int i=n++;
   T[i]=r.time; O[i]=r.open; H[i]=r.high; L[i]=r.low; C[i]=r.close; V[i]=(double)r.tick_volume;
   double pc=(i>0)?C[i-1]:C[i];
   TR[i]=MathMax(H[i],pc)-MathMin(L[i],pc);
   FV[i]=(r.real_volume>0)?(double)r.real_volume:(double)r.tick_volume;
   FD[i]=BarDelta(r,FV[i]);
   ComputeState(i);
   ComputeCloud(i);
   FlowAddBar(i);
}

//--- +1/-1: untouched swing inside the cloud near the pivot swept and reclaimed on bar i
int Sweep(const int i)
{
   double lo=Lo[i],up=Up[i],piv=Piv[i],atr=ATRc[i];
   int r=InpSwingStrength;
   for(int c=i-1-r;c>=i-InpLookback && c-r>=0;c--)
   {
      if(SwLow(c,r))
      {
         double lv=L[c];
         if(lv>=lo && lv<=up && MathAbs(lv-piv)<=InpSnapATR*atr && L[i]<lv-InpSweepATR*atr && C[i]>MathMax(lv,piv))
         {
            bool fresh=true;
            for(int j=c+1;j<i;j++) if(L[j]<lv) { fresh=false; break; }
            if(fresh) return 1;
         }
      }
      if(SwHigh(c,r))
      {
         double hv=H[c];
         if(hv>=lo && hv<=up && MathAbs(hv-piv)<=InpSnapATR*atr && H[i]>hv+InpSweepATR*atr && C[i]<MathMin(hv,piv))
         {
            bool fresh=true;
            for(int j=c+1;j<i;j++) if(H[j]>hv) { fresh=false; break; }
            if(fresh) return -1;
         }
      }
   }
   return 0;
}

bool StateAllows(const int dir,const int st,const bool rangeOk)
{
   if(st<0 || st==ST_CLIMAX) return false;
   if(st==ST_MIXED) return !InpBlockMixed;
   if(st==ST_RANGE) return rangeOk;
   if(dir>0) return (st==ST_UP_IMPULSE || st==ST_UP_PULLBACK);
   return (st==ST_DN_IMPULSE || (InpShortInBounce && st==ST_DN_BOUNCE));
}

double LotsForRisk(const double dist)
{
   double tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tv<=0) tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tv<=0 || ts<=0 || dist<=0) return 0;
   double lots=AccountInfoDouble(ACCOUNT_EQUITY)*InpRiskPercent/100.0/(dist/ts*tv);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(step<=0) return 0;
   lots=MathFloor(lots/step)*step;
   if(lots<vmin) return 0; // never round up past the risk budget
   return MathMin(lots,vmax);
}

bool FindPosition(ulong &ticket)
{
   for(int k=PositionsTotal()-1;k>=0;k--)
   {
      ulong t=PositionGetTicket(k);
      if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol && PositionGetInteger(POSITION_MAGIC)==InpMagic)
      { ticket=t; return true; }
   }
   return false;
}

// comment: "SPV3 <type> r=<risk> f=<flow>"
double InitialRisk(const string comment)
{
   int p=StringFind(comment,"r=");
   if(p<0) return 0;
   int e=StringFind(comment," ",p);
   string s=(e<0)?StringSubstr(comment,p+2):StringSubstr(comment,p+2,e-p-2);
   return StringToDouble(s);
}

int FlowFromComment(const string comment)
{
   int p=StringFind(comment,"f=");
   if(p<0) return FS_UNREADY;
   return (int)StringToInteger(StringSubstr(comment,p+2));
}

void Manage(const ulong ticket,const int i)
{
   if(!PositionSelectByTicket(ticket)) return;
   bool isLong=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double open=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP);
   double r=InitialRisk(PositionGetString(POSITION_COMMENT));
   double atr=ATRc[i],piv=Piv[i],lo=Lo[i],up=Up[i];
   if(!Num(atr) || !Num(piv)) return;
   if(InpExitOppositeImpulse && (isLong ? St[i]==ST_DN_IMPULSE : St[i]==ST_UP_IMPULSE))
   {
      trade.PositionClose(ticket);
      return;
   }
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID),ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double profit=isLong?bid-open:open-ask;
   double buf=InpSLBufferATR*atr;
   double cloudL=isLong?lo-buf:up+buf,pivL=isLong?piv-buf:piv+buf,lvl=cloudL;
   if(InpTrail==TRAIL_PIVOT) lvl=pivL;
   else if(InpTrail==TRAIL_HYBRID && r>0)
   {
      if(profit>=InpHybridR*r) g_pivotLatch=ticket; // stays on after a pullback below the threshold
      if(g_pivotLatch==ticket) lvl=isLong?MathMax(cloudL,pivL):MathMin(cloudL,pivL);
   }
   double newSL=isLong?MathMax(sl,lvl):MathMin(sl,lvl);
   if(InpBreakevenR>0 && r>0 && profit>=InpBreakevenR*r) newSL=isLong?MathMax(newSL,open):MathMin(newSL,open);
   double gap=(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+1)*_Point;
   if(isLong && newSL>bid-gap) return;
   if(!isLong && newSL<ask+gap) return;
   newSL=NormalizeDouble(newSL,_Digits);
   if(MathAbs(newSL-sl)>=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE))
      trade.PositionModify(ticket,newSL,tp);
}

void TryEntry(const int i,const bool busy=false)
{
   double atr=ATRc[i],piv=Piv[i],lo=Lo[i],up=Up[i];
   if(!Num(atr) || !Num(piv) || !Num(Piv[i-1])) return;
   double tol=InpTouchATR*atr;
   bool respected=(Tch[i]>=InpMinTouches && Resp[i]>=InpMinRespect);
   int dir=0,type=-1;
   if(InpUseSweep) { int s=Sweep(i); if(s!=0) { dir=s; type=0; } }
   if(dir==0 && InpUsePivotRetest && respected && armP)
   {
      if(C[i-1]>Piv[i-1]+tol && L[i]<=piv+tol && C[i]>piv && C[i]>O[i]) { dir=1; type=1; }
      else if(C[i-1]<Piv[i-1]-tol && H[i]>=piv-tol && C[i]<piv && C[i]<O[i]) { dir=-1; type=1; }
   }
   if(dir==0 && InpUseLevel2 && armL2)
   {
      if(C[i-1]>Up[i-1]+tol && L[i]<=up+tol && C[i]>up && C[i]>O[i]) { dir=1; type=2; }
      else if(C[i-1]<Lo[i-1]-tol && H[i]>=lo-tol && C[i]<lo && C[i]<O[i]) { dir=-1; type=2; }
   }
   if(dir==0 && InpUseLevel3 && armL3)
   {
      double u3=2*up-piv,u3p=2*Up[i-1]-Piv[i-1],d3=2*lo-piv,d3p=2*Lo[i-1]-Piv[i-1];
      if(up>piv && C[i-1]>u3p+tol && L[i]<=u3+tol && C[i]>u3 && C[i]>O[i]) { dir=1; type=3; }
      else if(lo<piv && C[i-1]<d3p-tol && H[i]>=d3-tol && C[i]<d3 && C[i]<O[i]) { dir=-1; type=3; }
   }
   if(dir==0 && InpUseSqueeze && Num(ATRc[i-1]) && ATRc[i-1]>0)
   {
      double wp=(Up[i-1]-Lo[i-1])/ATRc[i-1],pulse=(C[i]-C[i-1])/atr;
      if(wp<=InpSqueezeMax)
      {
         if(C[i-1]<=Up[i-1] && C[i]>up && pulse>=InpMinPulse) { dir=1; type=4; }
         else if(C[i-1]>=Lo[i-1] && C[i]<lo && pulse<=-InpMinPulse) { dir=-1; type=4; }
      }
   }
   if(dir==0) return;
   if(busy)
   {
      // research only: a position is open; record the signal without touching any state
      double b=InpSLBufferATR*atr;
      string why;
      bool ok=StateAllows(dir,St[i],type==4 || InpAllowRange) && FlowAllows(i,dir,type,why);
      LogSignal(i,type,dir,ok?"busy":"busyfilter",dir>0?MathMin(lo,L[i])-b:MathMax(up,H[i])+b,atr);
      return;
   }
   dSig[type]++;
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK),bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double entry=dir>0?ask:bid;
   double buf=InpSLBufferATR*atr;
   double sl=dir>0?MathMin(lo,L[i])-buf:MathMax(up,H[i])+buf;
   double risk=dir>0?entry-sl:sl-entry;
   if(!StateAllows(dir,St[i],type==4 || InpAllowRange)) { dState++; LogSignal(i,type,dir,"state",sl,atr); return; }
   string why;
   if(!FlowAllows(i,dir,type,why)) { dFlow++; LogSignal(i,type,dir,"flow:"+why,sl,atr); return; }
   if(risk<=0) { LogSignal(i,type,dir,"badrisk",sl,atr); return; }
   if(risk>InpMaxSLATR*atr) { dMaxSL++; LogSignal(i,type,dir,"maxsl",sl,atr); return; }
   double gap=(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+1)*_Point;
   if(risk<gap) return;
   double tp=(InpTargetR>0)?entry+dir*InpTargetR*risk:0.0;
   double lots=LotsForRisk(risk);
   if(lots<=0) { dLots++; LogSignal(i,type,dir,"lots",sl,atr); return; }
   LogSignal(i,type,dir,"taken",sl,atr);
   if(type==1) armP=false;
   if(type==2) { armL2=false; l2Dir=dir; }
   if(type==3) { armL3=false; l3Dir=dir; }
   string tag=StringFormat("SPV3 %s r=%s f=%d",TYPES[type],DoubleToString(risk,_Digits),FS[i]);
   PrintFormat("[SPV3] %s %s entry=%.*f sl=%.*f lots=%.2f state=%d flow=%s vol%%=%.0f delta%%=%.0f move%%=%.0f",
               dir>0?"BUY":"SELL",TYPES[type],_Digits,entry,_Digits,sl,lots,St[i],
               FlowName(FS[i]),FVp[i],FDp[i],FMp[i]);
   if(!tradingOn) return;
   sl=NormalizeDouble(sl,_Digits); tp=NormalizeDouble(tp,_Digits);
   if(dir>0) trade.Buy(lots,_Symbol,0,sl,tp,tag);
   else      trade.Sell(lots,_Symbol,0,sl,tp,tag);
}

// a level re-arms once a bar closes far enough from it
void UpdateArms(const int i)
{
   double atr=ATRc[i];
   if(!Num(atr) || !Num(Piv[i])) return;
   double far=InpRearmATR*atr;
   if(!armP && MathAbs(C[i]-Piv[i])>far) armP=true;
   if(!armL2 && MathAbs(C[i]-(l2Dir>0?Up[i]:Lo[i]))>far) armL2=true;
   if(!armL3 && MathAbs(C[i]-(l3Dir>0?2*Up[i]-Piv[i]:2*Lo[i]-Piv[i]))>far) armL3=true;
}

int OnInit()
{
   int sec=PeriodSeconds(_Period);
   if(InpLookback<16 || InpLookback>1000 || InpATRPeriod<2 || InpSwingStrength<1 || InpSnapATR<=0 ||
      InpTouchATR<=0 || InpRespectWindow<10 || InpRiskPercent<=0 || InpRiskPercent>5 ||
      InpMaxSLATR<=0 || InpWarmupBars<InpLookback+InpRespectWindow+50)
      return INIT_PARAMETERS_INCORRECT;
   if(InpFlowBlock<1 || InpFlowMinRef<2 || InpFlowRefDays<=0 || InpFlowPct<=0 || InpFlowPct>100 ||
      InpFlowMaxShare<0 || InpFlowMaxShare>=0.5 ||
      !(InpFlowWeak>0 && InpFlowWeak<InpFlowBig && InpFlowBig<InpFlowMax))
      return INIT_PARAMETERS_INCORRECT;
   if(!ParseStates(InpFlowVeto,g_veto,"InpFlowVeto") ||
      !ParseStates(InpBreakoutStates,g_breakOk,"InpBreakoutStates"))
      return INIT_PARAMETERS_INCORRECT;
   g_N=MathMax(6,(int)MathRound(1440.0/(sec/60)));
   ArrayResize(g_s,InpLookback);
   g_blockSec=(long)sec*InpFlowBlock;
   g_refWin=(int)MathMax(InpFlowMinRef,MathRound(InpFlowRefDays*86400.0/(double)g_blockSec));
   ArrayResize(g_fv,g_refWin); ArrayResize(g_fd,g_refWin); ArrayResize(g_fm,g_refWin);
   tradingOn=(bool)MQLInfoInteger(MQL_TESTER) || InpAllowLive;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(20);
   PrintFormat("[SPV3] started %s %s, trading=%s, flow=%s (block %d bars, veto '%s', breakout '%s')",
               _Symbol,EnumToString(_Period),tradingOn?"ON":"LOG ONLY",InpUseFlow?"ON":"OFF",
               InpFlowBlock,InpFlowVeto,InpBreakoutFlow?InpBreakoutStates:"off");
   if(InpUseFlow && InpWarmupBars<InpFlowBlock*(InpFlowMinRef+2))
      PrintFormat("[SPV3] note: warm-up %d bars < %d needed for the flow reference; early entries see no flow state",
                  InpWarmupBars,InpFlowBlock*(InpFlowMinRef+2));
   return INIT_SUCCEEDED;
}

void OnTick()
{
   datetime t1=iTime(_Symbol,_Period,1);
   if(t1==0 || (n>0 && T[n-1]>=t1)) return;
   MqlRates r[];
   int want=(n==0)?InpWarmupBars:64;
   int got=CopyRates(_Symbol,_Period,1,want,r);
   if(got<=0) return;
   bool warm=(n==0);
   for(int k=0;k<got;k++)
   {
      if(n>0 && r[k].time<=T[n-1]) continue;
      AddBar(r[k]);
      if(k<got-1 || warm) UpdateArms(n-1);
   }
   if(warm || n<InpLookback+2) return;
   int i=n-1;
   ulong ticket;
   if(FindPosition(ticket))
   {
      if(tradingOn) Manage(ticket,i);
      if(InpExport) TryEntry(i,true);
   }
   else TryEntry(i);
   UpdateArms(i);
}

void OnDeinit(const int reason)
{
   PrintFormat("[SPV3-DIAG] bars=%d signals: sweep=%d pivot=%d level2=%d level3=%d squeeze=%d | blocked state=%d flow=%d maxSL=%d lots=%d",
               n,dSig[0],dSig[1],dSig[2],dSig[3],dSig[4],dState,dFlow,dMaxSL,dLots);
   if(!MQLInfoInteger(MQL_TESTER) || !HistorySelect(0,TimeCurrent()+86400)) return;
   long ids[]; int typ[]; int fst[]; int cnt=0;
   double net[5],win[5],tot[5];
   double fnet[9],fwin[9],ftot[9];          // index = flow state + 1 (0 = unready)
   ArrayInitialize(net,0); ArrayInitialize(win,0); ArrayInitialize(tot,0);
   ArrayInitialize(fnet,0); ArrayInitialize(fwin,0); ArrayInitialize(ftot,0);
   int deals=HistoryDealsTotal();
   for(int k=0;k<deals;k++)
   {
      ulong d=HistoryDealGetTicket(k);
      if(HistoryDealGetInteger(d,DEAL_MAGIC)!=InpMagic || HistoryDealGetInteger(d,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
      string cm=HistoryDealGetString(d,DEAL_COMMENT);
      for(int t=0;t<5;t++) if(StringFind(cm," "+TYPES[t]+" ")>=0)
      {
         ArrayResize(ids,cnt+1); ArrayResize(typ,cnt+1); ArrayResize(fst,cnt+1);
         ids[cnt]=HistoryDealGetInteger(d,DEAL_POSITION_ID); typ[cnt]=t;
         int f=FlowFromComment(cm); fst[cnt]=(f>=0 && f<FS_COUNT)?f:FS_UNREADY;
         cnt++; break;
      }
   }
   for(int q=0;q<cnt;q++)
   {
      if(!HistorySelectByPosition(ids[q])) continue;
      double p=0;
      for(int k=0;k<HistoryDealsTotal();k++)
      {
         ulong d=HistoryDealGetTicket(k);
         p+=HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_COMMISSION);
      }
      net[typ[q]]+=p; tot[typ[q]]++; if(p>0) win[typ[q]]++;
      int fi=fst[q]+1;
      fnet[fi]+=p; ftot[fi]++; if(p>0) fwin[fi]++;
   }
   for(int t=0;t<5;t++)
      if(tot[t]>0) PrintFormat("[SPV3-TYPE] %-8s trades=%3d win=%5.1f%% net=%.2f",TYPES[t],(int)tot[t],100.0*win[t]/tot[t],net[t]);
   for(int fi=0;fi<9;fi++)
      if(ftot[fi]>0) PrintFormat("[SPV3-FLOW] %-10s trades=%3d win=%5.1f%% net=%.2f",FlowName(fi-1),(int)ftot[fi],
                                 100.0*fwin[fi]/ftot[fi],fnet[fi]);
   if(InpExport) ExportResearch(ids,typ,fst,cnt);
}

void ExportResearch(const long &ids[],const int &typ[],const int &fst[],const int cnt)
{
   string pre=InpExportTag+"_"+_Symbol+"_"+EnumToString(_Period);
   int f=FileOpen(pre+"_bars.csv",FILE_WRITE|FILE_ANSI|FILE_TXT|FILE_COMMON);
   if(f!=INVALID_HANDLE)
   {
      FileWriteString(f,"time,open,high,low,close,tickvol,lo,up,mid,piv,atr,atrm,dr,state,touches,respect,flowvol,flowdelta,flow,volpct,deltapct,movepct\n");
      for(int i=0;i<n;i++)
         FileWriteString(f,StringFormat("%s,%.5f,%.5f,%.5f,%.5f,%.0f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%d,%d,%.3f,%.2f,%.2f,%s,%.1f,%.1f,%.1f\n",
            TimeToString(T[i],TIME_DATE|TIME_MINUTES),O[i],H[i],L[i],C[i],V[i],
            Num(Lo[i])?Lo[i]:0,Num(Up[i])?Up[i]:0,Num(Mid[i])?Mid[i]:0,Num(Piv[i])?Piv[i]:0,
            Num(ATRc[i])?ATRc[i]:0,ATRm[i],DR[i],St[i],Tch[i],Resp[i],
            FV[i],FD[i],FlowName(FS[i]),FVp[i],FDp[i],FMp[i]));
      FileClose(f);
   }
   f=FileOpen(pre+"_signals.csv",FILE_WRITE|FILE_ANSI|FILE_TXT|FILE_COMMON);
   if(f!=INVALID_HANDLE)
   {
      FileWriteString(f,"time,bar,type,dir,status,close,sl,atr,state,width,touches,respect,flow,volpct,deltapct,movepct\n");
      for(int k=0;k<g_nsig;k++) FileWriteString(f,g_sig[k]+"\n");
      FileClose(f);
   }
   f=FileOpen(pre+"_trades.csv",FILE_WRITE|FILE_ANSI|FILE_TXT|FILE_COMMON);
   if(f!=INVALID_HANDLE)
   {
      FileWriteString(f,"open_time,close_time,type,dir,open,close,volume,risk,profit,flow\n");
      for(int q=0;q<cnt;q++)
      {
         if(!HistorySelectByPosition(ids[q])) continue;
         datetime t0=0,t1=0; double po=0,pc=0,vol=0,p=0,risk=0; int dir=0;
         for(int k=0;k<HistoryDealsTotal();k++)
         {
            ulong d=HistoryDealGetTicket(k);
            p+=HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_COMMISSION);
            if(HistoryDealGetInteger(d,DEAL_ENTRY)==DEAL_ENTRY_IN)
            {
               t0=(datetime)HistoryDealGetInteger(d,DEAL_TIME); po=HistoryDealGetDouble(d,DEAL_PRICE);
               vol=HistoryDealGetDouble(d,DEAL_VOLUME); risk=InitialRisk(HistoryDealGetString(d,DEAL_COMMENT));
               dir=(HistoryDealGetInteger(d,DEAL_TYPE)==DEAL_TYPE_BUY)?1:-1;
            }
            else { t1=(datetime)HistoryDealGetInteger(d,DEAL_TIME); pc=HistoryDealGetDouble(d,DEAL_PRICE); }
         }
         FileWriteString(f,StringFormat("%s,%s,%s,%d,%.5f,%.5f,%.2f,%.5f,%.2f,%s\n",
            TimeToString(t0,TIME_DATE|TIME_MINUTES),TimeToString(t1,TIME_DATE|TIME_MINUTES),
            TYPES[typ[q]],dir,po,pc,vol,risk,p,FlowName(fst[q])));
      }
      FileClose(f);
   }
   PrintFormat("[SPV3] research files written: %s_*.csv (%d bars, %d signals, %d trades)",pre,n,g_nsig,cnt);
}
