// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=5

indicator('Liquidation Estimates (Real-Time) [LuxAlgo]', 'LuxAlgo - Liquidation Estimates (Real-Time)', false, format.volume)

//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{

liqS1 = "Longs/Shorts Liquidations"
liqS2 = "Total Liquidations"
liqS3 = "Liquidations Dominance (Difference)"
liqS4 = "Cumulative Liquidations"
liqTT = "Mode Options:\n -" + 
         liqS1 + " : displays long and short liquidations individually\n -" +
         liqS2 + " : displays sum of long and short liquidations\n -" +
         liqS3 + " : displays difference between the long and short liquidations\n -" +
         liqS4 + " : displays the cumulative sum of the difference between short and long liquidations"
         
liqSH = input.string(liqS1, "Mode", options = [liqS1, liqS3, liqS2, liqS4], tooltip = liqTT)

refPL = input.string("open", "Longs Reference Price", options = ["open", "close", "oc2", "hl2", "ooc3", "occ3", "hlc3", "ohlc4", "hlcc4"])
refPS = input.string("oc2", "Shorts Reference Price", options = ["open", "close", "oc2", "hl2", "ooc3", "occ3", "hlc3", "ohlc4", "hlcc4"])

//-----------------------------------------------------------------------------}
// User Defined Types
//-----------------------------------------------------------------------------{

// @type        bar properties with their values 
//
// @field h     (float) high price of the bar
// @field l     (float) low price of the bar
// @field v     (float) volume of the bar

type bar
    float h = high
    float l = low
    float v = volume

//-----------------------------------------------------------------------------}
// Variables
//-----------------------------------------------------------------------------{

bar b = bar.new()
nzV = nz(b.v)

//-----------------------------------------------------------------------------}
// Functions/methods
//-----------------------------------------------------------------------------{

f_gSRC(_s) =>
    switch _s
        "open"  => open
        "close" => close
        "oc2"   => math.avg(open, close)
        "hl2"   => hl2
        "ooc3"  => math.avg(open, open, close)
        "occ3"  => math.avg(open, close, close)
        "hlc3"  => hlc3
        "ohlc4" => ohlc4
        "hlcc4" => hlcc4

//-----------------------------------------------------------------------------}
// Calculations
//-----------------------------------------------------------------------------{

rPS = f_gSRC(refPS)
rPL = f_gSRC(refPL)
lLQ = nzV / (rPL / (rPL - b.l))
sLQ = nzV / (rPS / (b.h - rPS))

plot(liqSH == liqS1 ?  lLQ : na, 'Longs' , color.new(#26a69a, 17), style = plot.style_columns)
plot(liqSH == liqS1 ? -sLQ : na, 'Shorts', color.new(#ef5350, 17), style = plot.style_columns)

plot(liqSH == liqS2 ?  lLQ + sLQ : na, 'Total', color.new(#9fafdd, 17), style = plot.style_columns)

plot(liqSH == liqS3 ?  lLQ - sLQ : na, 'Dominance', lLQ > sLQ ? color.new(#26a69a, 17) : color.new(#ef5350, 17), style = plot.style_columns)

plot(liqSH == liqS4 ?  ta.cum(sLQ - lLQ) : na, 'Cumulative', color.orange, 2)

//-----------------------------------------------------------------------------}