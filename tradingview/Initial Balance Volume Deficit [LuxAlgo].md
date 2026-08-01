// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Initial Balance Volume Deficit [LuxAlgo]", "LuxAlgo - IB Volume Deficit", overlay = false, format = format.volume)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645
color MA_COLOR   = #ff9800

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
maLength = input(20, "Moving Average Length")
averageLength = input(100, "Tops/Bottoms Average Length")

color  bullColorInput  = input.color(BULL_COLOR,    "Bullish Color", group = 'Style')
color  bearColorInput  = input.color(BEAR_COLOR,    "Bearish Color", group = 'Style')
color  maColorInput    = input.color(MA_COLOR  ,    "MA Color"     , group = 'Style')

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
var int isNewSessionT = na
var osc = 0.
var oscAMA = 0.

isNewSession = session.isfirstbar
isNewSessionT := isNewSession ? time : isNewSessionT

isInIB = (time - isNewSessionT) / 1000 / 60 <= 60

osc := isNewSession ? volume : isInIB ? osc + volume : osc - volume
oscAMA := isNewSession ? math.avg(osc, 0) : oscAMA + (osc - oscAMA) / maLength

// Peak Average
var tops = array.new_float(0)
var btms = array.new_float(0)

// Tops
if not isInIB and isInIB[1]
    tops.push(osc[1])

    if tops.size() > averageLength
        tops.shift()

// Deficit bottoms
if isNewSession
    btms.push(osc[1])

    if btms.size() > averageLength
        btms.shift()

topsAvg = tops.avg()
btmsAvg = btms.avg()

// No deficit detection
bgcolor(isNewSession and osc[1] > 0 ? color.new(#089981, 80) : na)

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
// Gradient colors based on oscillator value
color plotColor = osc > 0 ? color.new(bullColorInput, isInIB ? 0 : 50) : bearColorInput

// Oscillator Plots
plot(osc, "IB Volume Deficit", color = plotColor, style = plot.style_columns)
plot(oscAMA, "IB Volume Anchored Moving Average", color = isNewSession ? na : maColorInput)

// Tops/Bottoms averages
plot(topsAvg, "Tops Average", bullColorInput, linestyle = plot.linestyle_dashed)
plot(btmsAvg, "Bottoms Average", bearColorInput, linestyle = plot.linestyle_dashed)

//---------------------------------------------------------------------------------------------------------------------}
