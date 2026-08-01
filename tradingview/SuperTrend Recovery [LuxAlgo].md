// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("SuperTrend Recovery [LuxAlgo]", "LuxAlgo - SuperTrend Recovery", overlay = true, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR            = #089981
color BEAR_COLOR            = #f23645

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string ST_GROUP             = 'Supertrend Settings'
int lengthInput             = input.int(10, 'ATR Length', minval = 1, group = ST_GROUP)
float multiplierInput       = input.float(3.0, 'Base Multiplier', minval = 0.1, step = 0.1, group = ST_GROUP)

string RECOVERY_GROUP       = 'Recovery Logic'
float alphaInput            = input.float(5.0, 'Recovery Alpha (%)', minval = 0.1, maxval = 100, step = 0.1, group = RECOVERY_GROUP, tooltip = 'Percentage weight applied to price when "at a loss" relative to the switch price.')
float thresholdInput        = input.float(1.0, 'Recovery Threshold (xATR)', minval = 0, step = 0.1, group = RECOVERY_GROUP, tooltip = 'Recovery logic activates only if the loss exceeds this many ATRs from the switch price.')


string VISUAL_GROUP         = 'Visualization'
bool showFillsInput         = input.bool(true, 'Show Gradient Fills', group = VISUAL_GROUP)
bool showLabelsInput        = input.bool(true, 'Show Signal Labels', group = VISUAL_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
// Core Calculations
//---------------------------------------------------------------------------------------------------------------------{
// ATR Calculation
float atr = ta.atr(lengthInput)
float alpha = alphaInput / 100.0

// Supertrend Variables
var float stBand      = na
var float switchPrice = na
var int trend         = 1 // 1 for Bull, -1 for Bear

float src = hl2
float upperBase = src + multiplierInput * atr
float lowerBase = src - multiplierInput * atr

// Recovery Condition: Price deviating at a loss from the switch price beyond the threshold
float deviation = thresholdInput * atr
bool isAtLoss = (trend == 1 and (switchPrice - close) > deviation) or (trend == -1 and (close - switchPrice) > deviation)


// Band Calculation
float prevBand = nz(stBand[1], trend == 1 ? lowerBase : upperBase)

if trend == 1
    float targetBand = isAtLoss ? (alpha * close + (1.0 - alpha) * prevBand) : lowerBase
    stBand := math.max(targetBand, prevBand)
    
    if close < stBand
        trend := -1
        stBand := upperBase
        switchPrice := close
else
    float targetBand = isAtLoss ? (alpha * close + (1.0 - alpha) * prevBand) : upperBase
    stBand := math.min(targetBand, prevBand)
    
    if close > stBand
        trend := 1
        stBand := lowerBase
        switchPrice := close

if barstate.isfirst
    switchPrice := close

bool trendChanged = trend != trend[1]

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
color stColor = trend == 1 ? BULL_COLOR : BEAR_COLOR

// Switch Dot (using plot for precision)
plot(trendChanged ? stBand : na, "Trend Switch Dot", color = stColor, style = plot.style_circles, linewidth = 4, join = false)

// Main Plot
plotId = plot(stBand, "Supertrend Band", color = stColor, linewidth = 2)
srcId  = plot(src, "Source", color = na)

// Gradient Fill (Strictly following: less transparent near price)
float topValue    = math.max(src, stBand)
float bottomValue = math.min(src, stBand)
color topFillColor    = trend == 1 ? color.new(BULL_COLOR, 50) : color.new(BEAR_COLOR, 100)
color bottomFillColor = trend == 1 ? color.new(BULL_COLOR, 100) : color.new(BEAR_COLOR, 50)

fill(plotId, srcId, topValue, bottomValue, topFillColor, bottomFillColor, 
     title   = "Trend Fill", 
     display = showFillsInput ? display.all : display.none)

// Signal Labels
if showLabelsInput and trendChanged
    label.new(bar_index, stBand, 
         text = trend == 1 ? "BULL" : "BEAR", 
         color = stColor, 
         textcolor = #FFFFFF, 
         style = trend == 1 ? label.style_label_up : label.style_label_down, 
         size = size.tiny)

//---------------------------------------------------------------------------------------------------------------------}