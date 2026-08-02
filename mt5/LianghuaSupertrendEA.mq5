#property strict
#property version "1.00"

#include <Trade/Trade.mqh>

input int InpAtrPeriod=10;
input double InpMultiplier=3.0;
input double InpTargetFraction=0.20;
input double InpSlippageRate=0.001;
input ulong InpMagic=60398610;
input int InpHistoryBars=5000;

CTrade trade;
datetime last_bar=0;
int signal_file=INVALID_HANDLE;

int Direction(datetime &decision_date)
  {
   int available=Bars(_Symbol,PERIOD_D1)-1;
   int count=MathMin(available,InpHistoryBars);
   if(count<2)
      return 0;
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   count=CopyRates(_Symbol,PERIOD_D1,1,count,rates);
   if(count<2)
      return 0;

   double atr=0.0;
   double previous_upper=0.0;
   double previous_lower=0.0;
   int direction=1;
   for(int i=0;i<count;i++)
     {
      double previous_close=(i==0 ? rates[i].close : rates[i-1].close);
      double tr=MathMax(
         rates[i].high-rates[i].low,
         MathMax(MathAbs(rates[i].high-previous_close),
                 MathAbs(rates[i].low-previous_close))
      );
      atr=(i==0 ? tr : atr+(tr-atr)/InpAtrPeriod);
      double upper=(rates[i].high+rates[i].low)/2.0+InpMultiplier*atr;
      double lower=(rates[i].high+rates[i].low)/2.0-InpMultiplier*atr;
      if(i>0)
        {
         if(!(lower>previous_lower || rates[i-1].close<previous_lower))
            lower=previous_lower;
         if(!(upper<previous_upper || rates[i-1].close>previous_upper))
            upper=previous_upper;
         if(direction==-1 && rates[i].close>previous_upper)
            direction=1;
         else if(direction==1 && rates[i].close<previous_lower)
            direction=-1;
        }
      previous_upper=upper;
      previous_lower=lower;
     }
   decision_date=rates[count-1].time;
   return direction;
  }

double TradePrice(double fallback)
  {
   double price=trade.ResultPrice();
   if(price>0)
      return price;
   ulong deal=trade.ResultDeal();
   if(deal>0 && HistoryDealSelect(deal))
     {
      price=HistoryDealGetDouble(deal,DEAL_PRICE);
      if(price>0)
         return price;
     }
   return fallback;
  }

bool DeductCosts(double price,double volume,bool selling)
  {
   if(!MQLInfoInteger(MQL_TESTER))
      return true;
   double gross=price*volume*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
   double commission=MathMax(5.0,gross*0.00025);
   double costs=commission+gross*0.00001+gross*InpSlippageRate;
   if(selling)
      costs+=gross*0.0005;
   if(!TesterWithdrawal(costs))
     {
      PrintFormat("LIANGHUA_TRADE_ERROR fee=%.2f error=%d",costs,GetLastError());
      return false;
     }
   return true;
  }

double BuyVolume(double ask)
  {
   double contract=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(ask<=0 || contract<=0 || step<=0)
      return 0.0;
   double budget=AccountInfoDouble(ACCOUNT_EQUITY)*InpTargetFraction;
   double estimated=ask*(1.0+InpSlippageRate)*contract;
   double lots=MathFloor((budget/estimated)/step)*step;
   lots=MathMin(lots,maximum);
   return lots>=minimum ? lots : 0.0;
  }

void RecordSignal(datetime decision_date,int direction)
  {
   if(signal_file==INVALID_HANDLE)
      return;
   FileWrite(signal_file,TimeToString(decision_date,TIME_DATE),direction);
   FileFlush(signal_file);
  }

int OnInit()
  {
   if(InpAtrPeriod<1 || InpMultiplier<=0 ||
      InpTargetFraction<=0 || InpTargetFraction>1 ||
      InpSlippageRate<0)
      return INIT_PARAMETERS_INCORRECT;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   last_bar=iTime(_Symbol,PERIOD_D1,0);
   signal_file=FileOpen(
      "lianghua_mt5_signals.csv",
      FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,
      ','
   );
   if(signal_file==INVALID_HANDLE)
     {
      PrintFormat("LIANGHUA_TRADE_ERROR signal_file=%d",GetLastError());
      return INIT_FAILED;
     }
   FileWrite(signal_file,"Date","Direction");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(signal_file!=INVALID_HANDLE)
      FileClose(signal_file);
  }

void OnTick()
  {
   datetime current=iTime(_Symbol,PERIOD_D1,0);
   if(current<=0 || current==last_bar)
      return;
   last_bar=current;

   datetime decision_date=0;
   int direction=Direction(decision_date);
   if(direction==0)
      return;
   RecordSignal(decision_date,direction);

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick))
      return;
   double ask=(tick.ask>0 ? tick.ask : tick.last);
   double bid=(tick.bid>0 ? tick.bid : tick.last);

   if(direction>0 && !PositionSelect(_Symbol))
     {
      double volume=BuyVolume(ask);
      if(volume<=0)
        {
         Print("LIANGHUA_TRADE_ERROR insufficient volume");
         return;
        }
      if(!trade.Buy(volume,_Symbol,0,0,0,"Lianghua Supertrend"))
        {
         PrintFormat("LIANGHUA_TRADE_ERROR buy=%u %s",
                     trade.ResultRetcode(),trade.ResultRetcodeDescription());
         return;
        }
      double price=TradePrice(ask);
      if(!DeductCosts(price,trade.ResultVolume(),false))
         return;
      PrintFormat("LIANGHUA_TRADE date=%s side=BUY direction=%d price=%.2f volume=%.2f",
                  TimeToString(decision_date,TIME_DATE),direction,price,
                  trade.ResultVolume());
     }
   else if(direction<0 && PositionSelect(_Symbol))
     {
      double volume=PositionGetDouble(POSITION_VOLUME);
      if(!trade.PositionClose(_Symbol))
        {
         PrintFormat("LIANGHUA_TRADE_ERROR sell=%u %s",
                     trade.ResultRetcode(),trade.ResultRetcodeDescription());
         return;
        }
      double price=TradePrice(bid);
      if(!DeductCosts(price,volume,true))
         return;
      PrintFormat("LIANGHUA_TRADE date=%s side=SELL direction=%d price=%.2f volume=%.2f",
                  TimeToString(decision_date,TIME_DATE),direction,price,volume);
     }
  }

double OnTester()
  {
   double profit=TesterStatistics(STAT_PROFIT);
   PrintFormat("LIANGHUA_TEST_DONE profit=%.2f trades=%.0f",
               profit,TesterStatistics(STAT_TRADES));
   return profit;
  }
