// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("CBC Flip with Targets and Filters [LuxAlgo]", "LuxAlgo - CBC Flip with Targets and Filters", overlay = true, max_labels_count = 500, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645

// Outcome Constants
int UNMET   = 0
int HIT     = 1
int STOPPED = 2

// Filter Options
string NONE         = "No Filter"
string CONFIRMATION = "Confirmation"
string CONTRARIAN   = "Contrarian"

// Dashboard Constants
DATA                    = #DBDBDB
HEADERS                 = #808080
BACKGROUND              = #161616
BORDERS                 = #2E2E2E

TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

DASHBOARD_GROUP         = 'Dashboard'
SETTINGS_GROUP          = 'Settings'
VISUALS_GROUP           = 'Visuals'

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
// Indicator Settings
bullColorInput    = input.color(BULL_COLOR, "Bullish Color", inline = "Colors", group = SETTINGS_GROUP)
bearColorInput    = input.color(BEAR_COLOR, "Bearish Color", inline = "Colors", group = SETTINGS_GROUP)

atrLengthInput    = input.int(30, "ATR Length", minval = 1, group = SETTINGS_GROUP)
targetMultInput   = input.float(1.0, "Target ATR Multiplier", minval = 0.1, step = 0.1, group = SETTINGS_GROUP)
stopMultInput     = input.float(0.5, "Stop ATR Multiplier", minval = 0.1, step = 0.1, group = SETTINGS_GROUP)
requireCloseStopInput = input.bool(false, "Require candle close to stop", group = SETTINGS_GROUP)

// VWAP Filter Settings
showVwapInput     = input.bool(true, "Show Daily Anchored VWAP", group = SETTINGS_GROUP)
vwapColorInput    = input.color(color.gray, "VWAP Color", group = SETTINGS_GROUP)
vwapFilterInput   = input.string(NONE, "Filter Bias by VWAP", options = [NONE, CONFIRMATION, CONTRARIAN], group = SETTINGS_GROUP)

// Visual Settings
showLabelsInput   = input.bool(true, "Show Flip Labels", group = VISUALS_GROUP)
showOutcomeInput  = input.bool(true, "Show Outcome Markers", group = VISUALS_GROUP)
labelSizeInput    = input.string(size.small, "Label Size", options = [size.tiny, size.small, size.normal, size.large], group = VISUALS_GROUP)

// Dashboard Settings
dashboardInput          = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput      = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])
historyLengthInput      = input.int(50, "Historical Trade Count", minval = 1, maxval = 500, group = DASHBOARD_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
var bool isBullish      = false
var float entryPrice    = na
var float targetPrice   = na
var float stopPrice     = na
var float maxProgress   = 0.0
var bool isStopped      = false
var bool targetWasHit   = false
var int signalBarIndex  = na

// Non-repainting state tracking
bool isConfirmedBar     = barstate.isconfirmed

// VWAP Logic (Anchored to Current Day)
bool isNewDay = ta.change(time("D")) != 0
float vwapValue = ta.vwap(close, isNewDay)

// History tracking: 0 = Unmet, 1 = Hit, 2 = Stopped
var int[] outcomeHistory = array.new_int(0)

float atr = ta.atr(atrLengthInput)

// Detect potential state changes
bool potentialBullishFlip = not isBullish and close > high[1]
bool potentialBearishFlip = isBullish and close < low[1]

// Apply VWAP Filter
bool isVwapConfirmed = switch vwapFilterInput
    NONE         => true
    CONFIRMATION => potentialBullishFlip ? close > vwapValue : (potentialBearishFlip ? close < vwapValue : true)
    CONTRARIAN   => potentialBullishFlip ? close < vwapValue : (potentialBearishFlip ? close > vwapValue : true)
    => true

// Confirmed Flip signals
bool isFlippingBullish = isConfirmedBar and potentialBullishFlip and isVwapConfirmed
bool isFlippingBearish = isConfirmedBar and potentialBearishFlip and isVwapConfirmed

// Update trade stats for the current bar
if not na(entryPrice) and not isStopped and not targetWasHit
    // Check for Stop Loss
    bool stopCondition = requireCloseStopInput ? 
         isConfirmedBar and ((isBullish and close <= stopPrice) or (not isBullish and close >= stopPrice)) :
         ((isBullish and low <= stopPrice) or (not isBullish and high >= stopPrice))

    if stopCondition
        isStopped := true
        if showOutcomeInput
            label.new(signalBarIndex, na, "✖", 
                 color       = #00000000, 
                 style       = isBullish ? label.style_label_up : label.style_label_down, 
                 textcolor   = bearColorInput, 
                 size        = size.tiny,
                 yloc        = isBullish ? yloc.belowbar : yloc.abovebar)
    
    // Check for Target Hit
    if not isStopped
        if (isBullish and high >= targetPrice) or (not isBullish and low <= targetPrice)
            targetWasHit := true
            maxProgress  := 100.0
            if showOutcomeInput
                label.new(signalBarIndex, na, "●", 
                     color       = #00000000, 
                     style       = isBullish ? label.style_label_up : label.style_label_down, 
                     textcolor   = bullColorInput, 
                     size        = size.tiny,
                     yloc        = isBullish ? yloc.belowbar : yloc.abovebar)
    
    // Update progress percentage
    if not isStopped and not targetWasHit
        float currentProgress = isBullish ? (high - entryPrice) / (targetPrice - entryPrice) * 100 : (entryPrice - low) / (entryPrice - targetPrice) * 100
        maxProgress := math.max(maxProgress, currentProgress)

// Record history and Reset on Flip
if isFlippingBullish or isFlippingBearish
    if not na(entryPrice)
        int outcome = targetWasHit ? HIT : (isStopped ? STOPPED : UNMET)
        array.push(outcomeHistory, outcome)
        if array.size(outcomeHistory) > historyLengthInput
            array.shift(outcomeHistory)

    // Setup new trade
    isBullish      := isFlippingBullish
    entryPrice     := close
    signalBarIndex := bar_index
    targetPrice    := isBullish ? close + (atr * targetMultInput) : close - (atr * targetMultInput)
    stopPrice      := isBullish ? close - (atr * stopMultInput)   : close + (atr * stopMultInput)
    maxProgress    := 0.0
    isStopped      := false
    targetWasHit   := false
    
    // Alert Functionality
    string flipMsg = "CBC Bias Flip: " + (isBullish ? "Bullish" : "Bearish") + " at " + str.tostring(close, format.mintick)
    alert(flipMsg, alert.freq_once_per_bar_close)

// Alert for trade outcomes
if isConfirmedBar
    if isStopped[1] == false and isStopped == true
        alert("CBC Bias: Stop Loss Hit", alert.freq_once_per_bar_close)
    if targetWasHit[1] == false and targetWasHit == true
        alert("CBC Bias: Target Reached", alert.freq_once_per_bar_close)

// Historical Calculation
int hitCount     = 0
int stoppedCount = 0
int unmetCount   = 0

if array.size(outcomeHistory) > 0
    for i = 0 to array.size(outcomeHistory) - 1
        int out = array.get(outcomeHistory, i)
        if out == HIT
            hitCount += 1
        else if out == STOPPED
            stoppedCount += 1
        else
            unmetCount += 1

int totalHistory   = array.size(outcomeHistory)
float hitRate      = totalHistory > 0 ? (float(hitCount) / totalHistory) * 100     : 0.0
float stoppedRate  = totalHistory > 0 ? (float(stoppedCount) / totalHistory) * 100 : 0.0
float unmetRate    = totalHistory > 0 ? (float(unmetCount) / totalHistory) * 100   : 0.0

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
// VWAP Plot
plot(showVwapInput ? vwapValue : na, "Daily Anchored VWAP", vwapColorInput, 1, plot.style_linebr)

// Plot labels on confirmed flip occurrences
if showLabelsInput
    if isFlippingBullish
        label.new(bar_index, low, "▲", 
             color       = #00000000, 
             style       = label.style_label_up, 
             textcolor   = bullColorInput, 
             size        = labelSizeInput,
             tooltip     = "Bullish Flip\nTarget: " + str.tostring(targetPrice, format.mintick) + "\nStop: " + str.tostring(stopPrice, format.mintick))

    if isFlippingBearish
        label.new(bar_index, high, "▼", 
             color       = #00000000, 
             style       = label.style_label_down, 
             textcolor   = bearColorInput, 
             size        = labelSizeInput, 
             tooltip     = "Bearish Flip\nTarget: " + str.tostring(targetPrice, format.mintick) + "\nStop: " + str.tostring(stopPrice, format.mintick))

// Levels
pTarget = plot(targetPrice, "Target", color.new(bullColorInput, 50), 1, plot.style_linebr)
pStop   = plot(stopPrice,   "Stop",   color.new(bearColorInput, 50), 1, plot.style_linebr)

// Shaded zone
fill(pTarget, pStop, isBullish ? color.new(bullColorInput, 90) : color.new(bearColorInput, 90), title = "Trend Zone")

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize     = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

if dashboardInput and barstate.islast
    var table t_able = table.new(parsedDashboardPosition, 2, 9, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)
    
    t_able.merge_cells(0, 0, 1, 0)
    cell(t_able, 0, 0, "CBC BIAS: " + (isBullish ? "BULLISH" : "BEARISH"), color = isBullish ? BULL_COLOR : BEAR_COLOR, align = text.align_center)

    divider(t_able, 1, 1)

    cell(t_able, 0, 2, "Current Target Progress", color = HEADERS, align = text.align_left)
    string progressText = isStopped ? "STOPPED" : (targetWasHit ? "HIT (" + str.tostring(maxProgress, "#.##") + "%)" : str.tostring(maxProgress, "#.##") + "%")
    color progressColor = isStopped ? BEAR_COLOR : (targetWasHit ? BULL_COLOR : DATA)
    cell(t_able, 1, 2, progressText, color = progressColor)

    divider(t_able, 3, 1)

    cell(t_able, 0, 4, "Historical Targets Reached", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 4, str.tostring(hitCount) + " / " + str.tostring(totalHistory) + " (" + str.tostring(hitRate, "#.##") + "%)", color = DATA)

    divider(t_able, 5, 1)

    cell(t_able, 0, 6, "Historical Targets Stopped", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 6, str.tostring(stoppedCount) + " / " + str.tostring(totalHistory) + " (" + str.tostring(stoppedRate, "#.##") + "%)", color = DATA)

    divider(t_able, 7, 1)

    cell(t_able, 0, 8, "Historical Targets Unmet", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 8, str.tostring(unmetCount) + " / " + str.tostring(totalHistory) + " (" + str.tostring(unmetRate, "#.##") + "%)", color = DATA)

//---------------------------------------------------------------------------------------------------------------------}
