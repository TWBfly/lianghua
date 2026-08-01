// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=5

indicator("Open Interest Inflows & Outflows [LuxAlgo]", 'LuxAlgo - Open Interest Inflows & Outflows', format = format.volume)

//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{
crO1 = "Price Sentiment"
crO2 = "Price"
crO3 = "Volume"
crO4 = "On Balance Volume"

crSH = input.bool(true, "OI Sentiment Correlation", inline = 'CRR')
crOP = input.string(crO1, '', options = [crO1, crO2, crO3, crO4], inline = 'CRR')
mimo = input.bool(true, 'Money Flow Estimates')

//Style
oiFS = input.bool(true, "OI Flow Sentiment", inline = 'style_oiflow', group = 'Style')
clUP = input.color(#00897B, '', inline = 'style_oiflow', group = 'Style')
clDW = input.color(#FF5252, '', inline = 'style_oiflow', group = 'Style')

prSS = input.bool(true, "Price Sentiment", inline = 'style_price', group = 'Style')
prSSCss = input.color(color.new(#9598a1, 50), ""
  , inline = 'style_price'
  , group = 'Style')

rUP = input.color(color.new(color.aqua, 50), 'Correlation Colors', inline = 'style_correlation', group = 'Style')
rDN = input.color(color.new(color.orange, 50), '', inline = 'style_correlation', group = 'Style')

smth = input.int(3, 'Smoothing', minval = 1
  , display = display.all - display.status_line
  , tooltip = 'Smoothing applicable for options\n -Open Interest Flow Sentiment\n -Price Sentiment'
  , group = 'Others')

//-----------------------------------------------------------------------------}
// User Defined Types
//-----------------------------------------------------------------------------{

type bar
    float h = high
    float l = low
    float c = close
    float v = volume

//-----------------------------------------------------------------------------}
// Variables
//-----------------------------------------------------------------------------{

bar b = bar.new()
futures = syminfo.type == "futures" 

//-----------------------------------------------------------------------------}
// Calculations
//-----------------------------------------------------------------------------{

oTF = futures and timeframe.isintraday ? "1D" : timeframe.period
sym = futures ? syminfo.ticker + "_OI" : str.endswith(syminfo.ticker, "USDT") ? syminfo.ticker + ".P_OI" : syminfo.ticker + "T.P_OI"
[oiH, oiL, oiC, cOI] = request.security(sym, oTF, [b.h, b.l, b.c, b.c > b.c[1]], ignore_invalid_symbol = true)

if barstate.islast and na(oiC)
    var table oiT = table.new(position.middle_center, 1, 1)
    table.cell(oiT, 0, 0, 'No Open Interest data found for the ' + syminfo.ticker + ' symbol.', text_size = size.normal, text_color = #ff9800, text_halign = text.align_left)

//-----------------------------------------------------------------------------}
// Calculations - Open Interest Flow Sentiment / Price Sentiment
//-----------------------------------------------------------------------------{

oiF  = ta.ema(oiH + oiL - 2 * ta.ema(oiC, 13), smth)
prF  = ta.ema(b.h + b.l - 2 * ta.ema(b.c, 13), smth)

pHST = ta.highest(prF, 89), pLST = ta.lowest (prF, 89)
oHST = ta.highest(oiF, 89), oLST = ta.lowest (oiF, 89)

plot(not futures and oiFS ? oiF : na, 'Open Interest Flow Sentiment'
  , oiF > 0 ? oiF[1] > oiF ? color.new(clUP, 50) : clUP : oiF[1] > oiF ? clDW : color.new(clDW, 50)
  , style = plot.style_columns
  , display = display.all - display.status_line)

plot(not futures and prSS ? prF * (oHST - oLST) / (pHST - pLST) : na, 'Price Sentiment'
  , prSSCss
  , 2
  , display = display.all - display.status_line)

//-----------------------------------------------------------------------------}
// Calculations - Correlation
//-----------------------------------------------------------------------------{
var float crX = na, var float crY = na
switch crOP
    crO1 => crX := prF, crY := oiF
    crO2 => crX := b.c, crY := oiC
    crO3 => crX := b.v, crY := oiF
    crO4 => crX := ta.obv, crY := oiC

crr   = ta.correlation(crX, crY, 13) 
pHST := ta.highest(crr, 89), pLST := ta.lowest (crr, 89)

a1 = plot(not futures and crSH ? crr * (oHST - oLST) / (pHST - pLST) : na, 'Correlation Line', color(na), editable = false, display = display.all - display.status_line)
a2 = plot(not futures and crSH ? 0 : na, 'Base Line', color(na), editable = false, display = display.all - display.status_line)

fill(a1, a2, pHST * (oHST - oLST) / (pHST - pLST), pLST * (oHST - oLST) / (pHST - pLST)
  , top_color = crr > 0 ? rUP : color.new(color.orange, 100)
  , bottom_color = crr > 0 ? color.new(color.aqua, 100) : rDN
  , title = 'Correlation Band')

//-----------------------------------------------------------------------------}
// Calculations - Money Flow Estimates
//-----------------------------------------------------------------------------{

B = (oiC - oiL) / (oiH - oiL)
S = (oiH - oiC) / (oiH - oiL) 

if mimo and not na(B)
    var oiTbl = table.new(position.top_right, 5, 1, bgcolor = color(na), border_width = 3, border_color=color(na))
    table.cell(oiTbl, 0, 0, text = 'Money Inflow %'  + str.tostring(B / (B + S) * 100, '#.##'), text_color = clUP, text_halign = text.align_left, text_size = size.small)
    table.cell(oiTbl, 1, 0, text = 'Money Outflow %' + str.tostring(S / (B + S) * 100, '#.##'), text_color = clDW, text_halign = text.align_left, text_size = size.small)

//-----------------------------------------------------------------------------}
// Calculations - Open Interest for Futures Markets
//-----------------------------------------------------------------------------{

plot(futures ? oiC : na, 'Futures Open Interest', cOI ? clUP : clDW, 3,  plot.style_stepline, display = display.all - display.status_line)

//-----------------------------------------------------------------------------}