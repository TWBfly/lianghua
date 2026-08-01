// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("FVG Channel [LuxAlgo]", shorttitle = "LuxAlgo - FVG Channel", overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
//User Inputs
//---------------------------------------------------------------------------------------------------------------------{

fvgLen = input.int(14, minval = 1,  title = "Unmitigated FVG Lookback")
smoothLen = input.int(9, minval = 1, title = "Smoothing Length")

//Style
fillType = input.string("Gradient", title = "Fill Type", options = ["Gradient", "Single Color", "No Fill"], group = "Style", tooltip = "Use a non-gradient fill to reduce lag caused by graphical performances.")

upperTopColor =  input.color(#089981, title = "      Upper Extremities", inline = 'upper', group = "Style")
upperBtmColor =  input.color(color.new(#089981, 50), title = "", inline = 'upper', group = "Style")
fillTopColor = input.color(color.new(#089981, 80), title = "", inline = 'upper', group = "Style")

lowerBtmColor = input.color(#f23645, title = "      Lower Extremities", inline = 'lower', group = "Style")
lowerTopColor = input.color(color.new(#f23645, 50), title = "", inline = 'lower', group = "Style")
fillBtmColor = input.color(color.new(#f23645, 80), title = "", inline = 'lower', group = "Style")

midColor = input.color(color.gray, title = "      Average Color", group = "Style")

showBreakouts = input(true, 'Breakout Levels', group = "Style")
upperBOColor  = input.color(#f23645, title = "      Upper", group = "Style")
lowerBOColor  = input.color(#089981, title = "      Lower", group = "Style")

showSignals = input(true, 'Show Signals', inline = 'signals', group = 'Style')
upSignal = input(#089981, '      Bullish', group = 'Style')
dnSignal = input(#f23645, '      Bearish', group = 'Style')

colorCandles = input(true, 'Apply Candle Coloring', inline = 'candle', group = "Style")

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{

fz(_val,_standin) => _val > 0 ? _val : _standin

dash() => (bar_index/2 - math.floor(bar_index/2)) > 0

fib_get(_range,_multi,_anchor) => _anchor + (_range * _multi)

//---------------------------------------------------------------------------------------------------------------------}
//FVG Level Arrays
//---------------------------------------------------------------------------------------------------------------------{

var bull_lvls = array.new<float>(0)

var bear_lvls = array.new<float>(0)

//---------------------------------------------------------------------------------------------------------------------}
//Calculations
//---------------------------------------------------------------------------------------------------------------------{

//FVG Detection
if low > high[2] and close[1] > high[2]
    bull_lvls.push(high[2])


if high < low[2] and close[1] < low[2]
    bear_lvls.push(low[2])

//Array Size Management
if bull_lvls.size() > fvgLen
    bull_lvls.shift()

if bear_lvls.size() > fvgLen
    bear_lvls.shift()

//FVG Mitigation Detection
if bull_lvls.size() > 0
    for i = bull_lvls.size()-1 to 0
        if close < bull_lvls.get(i)
            bull_lvls.remove(i)


if bear_lvls.size() > 0
    for i = bear_lvls.size()-1 to 0
        if close > bear_lvls.get(i)
            bear_lvls.remove(i)

//Bars to calc SMAs
bull_bs = fz(ta.barssince(not na(bull_lvls.avg())),1)
bear_bs = fz(ta.barssince(not na(bear_lvls.avg())),1)

//Progressive SMAs 
//Calc starts at 1 when FVG array is empty and Maxes out at Smoothing Length
bull_sma = ta.sma(close,math.min(bull_bs,smoothLen))
bear_sma = ta.sma(close,math.min(bear_bs,smoothLen))

//Displayed Extreme Values
bull_disp = ta.sma(nz(bull_lvls.avg(),bull_sma),smoothLen)
bear_disp = ta.sma(nz(bear_lvls.avg(),bear_sma),smoothLen)

//Bar color Calc
css = bull_lvls.size() == 0 ? lowerBtmColor : bear_lvls.size() == 0 ? upperTopColor : na

//Extreme Range for Fib Levels
fvg_rng = math.abs(bull_disp - bear_disp)
//Fib Levels
f5 = fib_get(fvg_rng,0.786,bull_disp)
f3 = fib_get(fvg_rng,0.5,bull_disp)
f1 = fib_get(fvg_rng,0.236,bull_disp)

//---------------------------------------------------------------------------------------------------------------------}
//Signal Generation
//---------------------------------------------------------------------------------------------------------------------{

down_signal = false
var down_check = false

up_signal = false
var up_check = false

rc = close < open
gc = close > open

//Signals fire when FVG array is empty.
//Price must cross inner fib level before generating another signal.
if close < f5 and down_check == false
    down_check := true
if bear_lvls.size() == 0 and down_check and (gc[1] and rc and close < open[1])
    down_signal := true
    down_check := false

if close > f1 and up_check == false
    up_check := true
if bull_lvls.size() == 0 and up_check and (rc[1] and gc and close > open[1])
    up_signal := true
    up_check := false


//---------------------------------------------------------------------------------------------------------------------}
//Display
//---------------------------------------------------------------------------------------------------------------------{

//Channel Lines
uo = plot(bear_disp, color = bear_lvls.size() == 0?color.new(upperTopColor,100):color.new(upperTopColor,0), style = plot.style_linebr, title = "Upper Extreme", display = display.pane + display.price_scale)
ui = plot(f5, color =  dash()?color.new(upperBtmColor,100):upperBtmColor, title = "Upper Inner", display = display.pane + display.price_scale)

plot(f3, color = midColor, title = "Mid Point", display = display.pane + display.price_scale)

li = plot(f1, color = dash()?color.new(lowerTopColor,100):lowerTopColor, title = "Lower Inner", display = display.pane + display.price_scale)
lo = plot(bull_disp, color = bull_lvls.size() == 0?color.new(lowerBtmColor,100):color.new(lowerBtmColor,0), style = plot.style_linebr, title = "Lower Extreme", display = display.pane + display.price_scale)

//Fills
fill(uo,ui,bear_disp,f5,fillTopColor,color.new(chart.bg_color,100), display = fillType == "Gradient" ? display.all : display.none)
fill(li,lo,f1,bull_disp,color.new(chart.bg_color,100),fillBtmColor, display = fillType == "Gradient" ? display.all : display.none)
fill(uo,ui,fillTopColor, display = fillType == "Single Color" ? display.all : display.none)
fill(li,lo,fillBtmColor, display = fillType == "Single Color" ? display.all : display.none)

//Break Out Lines
plot(bull_lvls.size() == 1 and showBreakouts ? bull_lvls.avg(): na, style = plot.style_linebr, color = lowerBOColor, title = "Lower Support", display = display.pane + display.price_scale)
plot(bear_lvls.size() == 1 and showBreakouts ? bear_lvls.avg(): na, style = plot.style_linebr, color = upperBOColor, title = "Upper Resistance", display = display.pane + display.price_scale)

//Signals
plotshape(up_signal and showSignals, style = shape.triangleup, location = location.belowbar, color = upSignal, size = size.tiny, display = display.pane, title = "Up Signal")
plotshape(down_signal and showSignals, style = shape.triangledown, location = location.abovebar, color = dnSignal, size = size.tiny, display = display.pane, title = "Down Signal")

//Bar Colors
barcolor(css, display = colorCandles ? display.all : display.none)

//---------------------------------------------------------------------------------------------------------------------}