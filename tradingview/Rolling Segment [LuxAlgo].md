// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Rolling Segment [LuxAlgo]", "LuxAlgo - Rolling Segment", overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
int   fastLengthInput       = input.int(5, "Fast Slope Length", minval = 1, group = "Slopes")
int   slowLengthInput       = input.int(10, "Slow Slope Length", minval = 1, group = "Slopes")
int   atrLengthInput        = input.int(200, "ATR Length", minval = 1, group = "ATR Settings")
float fastThresholdInput    = input.float(1.0, "Fast Slope Threshold (ATR Multiplier)", minval = 0, step = 0.1, group = "Thresholds")
float reverseThresholdInput = input.float(2.0, "Reverse Threshold (ATR Multiplier)", minval = 0, step = 0.1, group = "Thresholds")

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
float atr = ta.atr(atrLengthInput)

var float rollSeg     = close
var int   trend       = 1
var float activeSlope = 0.0
var bool  isFastMode  = false

bool bullReversal = false
bool bearReversal = false

// Logic processing
if not na(atr)
    float distFromSeg = close - rollSeg
    
    // Check for reversal
    bullReversal := trend == -1 and distFromSeg > reverseThresholdInput * atr
    bearReversal := trend == 1 and -distFromSeg > reverseThresholdInput * atr
    
    if bullReversal
        trend := 1
    else if bearReversal
        trend := -1
    
    // Check for speed change
    bool newIsFastMode = math.abs(distFromSeg) > fastThresholdInput * atr
    bool speedChanged  = newIsFastMode != isFastMode
    
    // Freeze ATR and update activeSlope when trend or speed mode changes
    if bullReversal or bearReversal or speedChanged or activeSlope == 0.0
        isFastMode  := newIsFastMode
        activeSlope := isFastMode ? atr / fastLengthInput : atr / slowLengthInput
    
    // Update Rolling Segment with linear movement
    rollSeg := rollSeg + (trend * activeSlope)
else
    rollSeg := close

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
color trendColor = trend == 1 ? BULL_COLOR : BEAR_COLOR

plotSeg   = plot(rollSeg, "Rolling Segment", color = trendColor, linewidth = 2)
plotPrice = plot(close, "Price Reference", display = display.none)

// Reversal signals
if bullReversal
    label.new(bar_index - 1, rollSeg, "▲", color = #00000000, textcolor = BULL_COLOR, style = label.style_label_up, size = size.normal)
if bearReversal
    label.new(bar_index - 1, rollSeg, "▼", color = #00000000, textcolor = BEAR_COLOR, style = label.style_label_down, size = size.normal)

// Vertical gradient fill: less transparent near price
fill(plotPrice, plotSeg, 
     top_value    = trend == 1 ? close : rollSeg, 
     bottom_value = trend == 1 ? rollSeg : close, 
     top_color    = trend == 1 ? color.new(BULL_COLOR, 50) : color.new(BEAR_COLOR, 90), 
     bottom_color = trend == 1 ? color.new(BULL_COLOR, 90) : color.new(BEAR_COLOR, 50),
     title        = "Trend Fill")

//---------------------------------------------------------------------------------------------------------------------}
