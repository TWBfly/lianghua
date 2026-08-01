// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=5
indicator("Donchian MA Bands [LuxAlgo]", shorttitle="LuxAlgo - Donchian MA Bands", overlay=true)
 
//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{
opt     = input.string(  'clouds' , 'Style'  , options=['clouds', 'Upper band', 'Lower band', 'bands']                                   , group='Bands'        )
typeMA1 = input.string(   "VWMA"  , 'Type MA', options=["SMA", "EMA", "SMMA (RMA)", "HullMA", "WMA", "VWMA", "DEMA", "TEMA", "NONE"]     , group='Bands'        )
len1    = input.int   (     50    , 'Length'                                                                                             , group='Bands'        )
colU    = input.color (#2962ffc0, 'colour bands'                                                                           , inline='1', group='Bands'        ) 
colD    = input.color (#ff5e00c0, ''                                                                                       , inline='1', group='Bands'        )
typeMA2 = input.string(   "VWMA"  , 'Type MA', options=["SMA", "EMA", "SMMA (RMA)", "HullMA", "WMA", "VWMA", "DEMA", "TEMA", "NONE"]     , group= 'S/R'         )
len2    = input.int   (     50    , 'Length'                                                                                             , group= 'S/R'         )
colU2   = input.color (#08998180, 'colour S/R     '                                                                        , inline='2', group= 'S/R'         )
colD2   = input.color (#f2364580, ''                                                                                       , inline='2', group= 'S/R'         )
cMidD   = input.color (#B2B5BE  , 'Colour Mid Donchian'                                                                    , inline='2', group= 'Mid Donchian')
 
//-----------------------------------------------------------------------------}      
// Variables
//-----------------------------------------------------------------------------{
var bool inPosition = false
int         n  = bar_index
var int trend  = 0
var float  gU  = na
var float  gD  = na
var line   lU  = line.new(na, na, na, na, color=colU2)
var line   lD  = line.new(na, na, na, na, color=colD2)

//-----------------------------------------------------------------------------}
// Methods
//-----------------------------------------------------------------------------{
method ma(string type, int length) =>
    //
    ema1 = ta.ema(close, length)
    ema2 = ta.ema(ema1 , length)
    ema3 = ta.ema(ema2 , length)
    //
    switch type
        "SMA"        => ta.sma (close, length)
        "EMA"        => ema1
        "SMMA (RMA)" => ta.rma (close, length)
        "HullMA"     => ta.hma (close, length)
        "WMA"        => ta.wma (close, length)
        "VWMA"       => ta.vwma(close, length)
        "DEMA"       =>  2 * ema1  -      ema2
        "TEMA"       => (3 * ema1) - (3 * ema2) + ema3
        => na

method fun(string typeMA, len) =>
    ma   = typeMA    .ma (len)  

    H    = ta.highest(ma, len)
    L    = ta.lowest (ma, len)

    HH   = ta.highest( H, len)
    HL   = ta.lowest ( H, len)

    LH   = ta.highest( L, len)
    LL   = ta.lowest ( L, len)

    HHH  = ta.highest(HH, len)
    HHL  = ta.lowest (HH, len)

    HLH  = ta.highest(HL, len)
    HLL  = ta.lowest (HL, len)

    LLH  = ta.highest(LL, len)
    LLL  = ta.lowest (LL, len)

    LHH  = ta.highest(LH, len)
    LHL  = ta.lowest (LH, len)

    [HHH, HH, HHL, H, HLH, HL, HLL, ma, LHH, LH, LHL, L, LLH, LL, LLL] 


//-----------------------------------------------------------------------------}
// Calculations
//-----------------------------------------------------------------------------{
// Bands
bands = opt == 'bands'
[HHH1 , HH1   , HHL1, H1 , HLH1, HL1, HLL1, ma1, LHH1, LH1, LHL1,  L1, LLH1, LL1, LLL1]  =  typeMA1.fun(len1)
arr1  = bands ? array.from(HHH1, HH1, HHL1,  H1, HLH1, HL1, HLL1, ma1, LHH1, LH1, LHL1 , L1, LLH1, LL1, LLL1) 
      :         array.from(      HH1,        H1,       HL1,       ma1,  LH1,  L1,  LL1),          arr1.sort()

// S/R
[  _  , HH2   ,  _  , H2 ,  _  , HL2,  _  , ma2, LHH2, LH2, LHL2,  L2, LLH2, LL2, LLL2]  =  typeMA2.fun(len2)
arr2  =         array.from(      HH2,        H2,       HL2,       ma2,  LH2,  L2,  LL2),          arr2.sort()


//-----------------------------------------------------------------------------}
// Execution
//-----------------------------------------------------------------------------{
// Bands
gt0  = bands ? arr1.get( 0) : na
gt1  =         arr1.get( 1) 
gt5  =         arr1.get( 5) 
gt13 = bands ? arr1.get(13) : na
gt14 = bands ? arr1.get(14) : na

trend      :=  trend  <  1 and close > gt14 ?  1 
           :   trend  > -1 and close < gt0  ? -1 
           :   trend
inPosition := (trend ==  1 and trend[1]     <  1 )  
           or (trend == -1 and trend[1]     > -1 ) 
  ?   true :  (trend  <  1 and trend[1]    ==  1 )
           or (trend  > -1 and trend[1]    == -1 )
  ?  false :  inPosition

// S/R
L_1 = arr2.get(1)
L_2 = arr2.get(2)
H_4 = arr2.get(4)
H_5 = arr2.get(5) 

gU := L_1 != L_2 ? L_1 : gU
gD := H_4 != H_5 ? H_5 : gD

if not bands
    lU.set_xy1(n, gU), lU.set_xy2(n + 10, gU) // Upper S/R line
    lD.set_xy1(n, gD), lD.set_xy2(n + 10, gD) // lower S/R line

//-----------------------------------------------------------------------------}
// Plot - Fill
//-----------------------------------------------------------------------------{

plot(bands ? math.avg(gt0, gt14) : math.avg(L_1, H_5)
                                          , 'Mid Donchian', color=cMidD      , style=plot.style_linebr)
plot(ma1   ,         linewidth=2          , title='MA'    , color=color.yellow, display=display.none)

// Clouds - Upper/Lower Bands
_h2  = plot(opt == 'clouds'     ? gt5 : na,   'Cloud H'                         , display=display.none)
_l2  = plot(opt == 'clouds'     ? gt1 : na,   'Cloud L'                         , display=display.none)

HHs  = plot(    not bands       ? HH1 : na,   'H-H sma'   , color=color.red   , display=display.none)
_Hs  = plot(    not bands       ?  H1 : na,     'H sma'   , color=color.red   , display=display.none)
LHs  = plot(opt == 'Upper band' ? HL1 : na,   'L-H sma'   , color=color.yellow, display=display.none)
HLs  = plot(opt == 'Lower band' ? LH1 : na,   'H-L sma'   , color=color.yellow, display=display.none)
_Ls  = plot(    not bands       ?  L1 : na,     'L sma'   , color=color.lime  , display=display.none)
LLs  = plot(    not bands       ? LL1 : na,   'L-L sma'   , color=color.lime  , display=display.none)

fill(HHs, _h2, top_value = H1  
  ,  bottom_value        = HH1           
  ,  top_color           = color.new(colD, 85)
  ,  bottom_color        = color.new(colD, 25), title="")

fill(LLs, _l2, top_value = L1  
  ,  bottom_value        = LL1 
  ,  top_color           = color.new(colU, 85)
  ,  bottom_color        = color.new(colU, 25), title="")

fill(HHs, LHs, top_value = H1 == HH1 ?  HH1 : HL1, bottom_value=H1 == HH1 ? HL1 : HH1
  ,  top_color           = color.new(H1 == HH1 ? colU : H1 == HL1 ? colD : chart.bg_color, 85)
  ,  bottom_color        = color.new(H1 == HH1 ? colU : H1 == HL1 ? colD : chart.bg_color, 25), title="")

fill(LLs, HLs, top_value = L1 == LL1 ?  LL1 : LH1, bottom_value=L1 == LL1 ? LH1 : LL1
  ,  top_color           = color.new(L1 == LL1 ? colD : L1 == LH1 ? colU : chart.bg_color, 85) 
  ,  bottom_color        = color.new(L1 == LL1 ? colD : L1 == LH1 ? colU : chart.bg_color, 25), title="")

// Bands
p1  = plot(    bands ? gt0  : na, 'Bands get1'  , color=colU                                 )
p2  = plot(    bands ? gt1  : na, 'Bands get2'  , color=chart.bg_color, display=display.none )
p14 = plot(    bands ? gt13 : na, 'Bands get14' , color=chart.bg_color, display=display.none )
p15 = plot(    bands ? gt14 : na, 'Bands get15' , color=colD                                 )

fill(p1 , p2 , top_value=gt1 , bottom_value=gt0 , top_color=color.new(colU, 85), bottom_color=color.new(colU, 25), title="")
fill(p14, p15, top_value=gt13, bottom_value=gt14, top_color=color.new(colD, 85), bottom_color=color.new(colD, 25), title="")

plotshape(trend ==  1 and   trend[1] <  1 ? low  : na, 'Up', style=shape.circle, color=colU, location=location.abovebar, size=size.tiny)
plotshape(trend == -1 and   trend[1] > -1 ? high : na, 'Dn', style=shape.circle, color=colD, location=location.belowbar, size=size.tiny)

// S/R
plot      (not bands and gU == gU[1] ? gU  : na, 'S/R Upper', color=colU2  ,   style=plot.style_linebr)
plot      (not bands and gD == gD[1] ? gD  : na, 'S/R Lower', color=colD2  ,   style=plot.style_linebr)

g1  = plot(not bands                 ? L_1 : na, 'S/R get 1', color=color.lime, display=display.none)
g2  = plot(not bands                 ? L_2 : na, 'S/R get 2', color=color.lime, display=display.none)
g4  = plot(not bands                 ? H_4 : na, 'S/R get 4', color=color.red , display=display.none)
g5  = plot(not bands                 ? H_5 : na, 'S/R get 5', color=color.red , display=display.none)

fill(g1, g2, color=colU2)
fill(g4, g5, color=colD2)

//-----------------------------------------------------------------------------}