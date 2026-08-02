#property script_show_inputs
#property version "1.00"

const string CUSTOM_SYMBOL="CN_603986";
const string CSV_FILE="lianghua_603986_bars.csv";

bool Require(bool result,string property)
  {
   if(!result)
      PrintFormat("LIANGHUA_IMPORT_ERROR property=%s error=%d",property,GetLastError());
   return result;
  }

bool ConfigureSymbol()
  {
   bool is_custom=false;
   bool exists=SymbolExist(CUSTOM_SYMBOL,is_custom);
   if(exists && !is_custom)
     {
      Print("LIANGHUA_IMPORT_ERROR broker symbol collision");
      return false;
     }
   if(!exists && !CustomSymbolCreate(CUSTOM_SYMBOL,"Lianghua"))
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR create=%d",GetLastError());
      return false;
     }

   if(!Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_DIGITS,2),"SYMBOL_DIGITS") ||
      !Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_CHART_MODE,SYMBOL_CHART_MODE_LAST),"SYMBOL_CHART_MODE") ||
      !Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_TRADE_CALC_MODE,SYMBOL_CALC_MODE_EXCH_STOCKS),"SYMBOL_TRADE_CALC_MODE") ||
      !Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_FULL),"SYMBOL_TRADE_MODE") ||
      !Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_ORDER_MODE,SYMBOL_ORDER_MARKET),"SYMBOL_ORDER_MODE") ||
      !Require(CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_FILLING_MODE,SYMBOL_FILLING_FOK),"SYMBOL_FILLING_MODE") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_POINT,0.01),"SYMBOL_POINT") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_TICK_SIZE,0.01),"SYMBOL_TRADE_TICK_SIZE") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_TICK_VALUE,1.0),"SYMBOL_TRADE_TICK_VALUE") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_CONTRACT_SIZE,100.0),"SYMBOL_TRADE_CONTRACT_SIZE") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_VOLUME_MIN,1.0),"SYMBOL_VOLUME_MIN") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_VOLUME_STEP,1.0),"SYMBOL_VOLUME_STEP") ||
      !Require(CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_VOLUME_MAX,100000.0),"SYMBOL_VOLUME_MAX") ||
      !Require(CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_BASE,"CNY"),"SYMBOL_CURRENCY_BASE") ||
      !Require(CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_PROFIT,"CNY"),"SYMBOL_CURRENCY_PROFIT") ||
      !Require(CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_MARGIN,"CNY"),"SYMBOL_CURRENCY_MARGIN"))
      return false;

   datetime session_start=0;
   datetime session_end=(datetime)(24*60*60-1);
   for(int day=MONDAY;day<=FRIDAY;day++)
     {
      if(!Require(CustomSymbolSetSessionQuote(CUSTOM_SYMBOL,(ENUM_DAY_OF_WEEK)day,0,session_start,session_end),"SESSION_QUOTE") ||
         !Require(CustomSymbolSetSessionTrade(CUSTOM_SYMBOL,(ENUM_DAY_OF_WEEK)day,0,session_start,session_end),"SESSION_TRADE"))
         return false;
     }
   return true;
  }

bool ReadRates(MqlRates &rates[])
  {
   int file=FileOpen(CSV_FILE,FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(file==INVALID_HANDLE)
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR open=%d",GetLastError());
      return false;
     }
   for(int column=0;column<9;column++)
      FileReadString(file);

   int count=0;
   while(!FileIsEnding(file))
     {
      string date=FileReadString(file);
      if(date=="" && FileIsEnding(file))
         break;
      string clock=FileReadString(file);
      double open=FileReadNumber(file);
      double high=FileReadNumber(file);
      double low=FileReadNumber(file);
      double close=FileReadNumber(file);
      long tick_volume=(long)FileReadNumber(file);
      long real_volume=(long)FileReadNumber(file);
      int spread=(int)FileReadNumber(file);
      datetime time=StringToTime(date+" "+clock);
      if(time<=0 || open<=0 || high<=0 || low<=0 || close<=0 ||
         high<open || high<close || low>open || low>close)
        {
         FileClose(file);
         PrintFormat("LIANGHUA_IMPORT_ERROR invalid row=%d",count+2);
         return false;
        }
      ArrayResize(rates,count+1,1024);
      rates[count].time=time;
      rates[count].open=open;
      rates[count].high=high;
      rates[count].low=low;
      rates[count].close=close;
      rates[count].tick_volume=MathMax(1,tick_volume);
      rates[count].real_volume=MathMax(1,real_volume);
      rates[count].spread=MathMax(0,spread);
      count++;
     }
   FileClose(file);
   return count>0;
  }

void OnStart()
  {
   if(!ConfigureSymbol())
      return;
   MqlRates rates[];
   if(!ReadRates(rates))
      return;
   ResetLastError();
   int updated=CustomRatesReplace(CUSTOM_SYMBOL,0,LONG_MAX,rates);
   if(updated!=ArraySize(rates))
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR updated=%d expected=%d error=%d",
                  updated,ArraySize(rates),GetLastError());
      return;
     }
   if(!SymbolSelect(CUSTOM_SYMBOL,true))
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR select=%d",GetLastError());
      return;
     }
   PrintFormat("LIANGHUA_IMPORT_OK symbol=%s bars=%d first=%s last=%s",
               CUSTOM_SYMBOL,updated,TimeToString(rates[0].time),
               TimeToString(rates[updated-1].time));
  }
