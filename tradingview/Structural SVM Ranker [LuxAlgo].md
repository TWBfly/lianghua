// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Structural SVM Ranker [LuxAlgo]", "LuxAlgo - Structural SVM Ranker", overlay = true, max_labels_count = 500, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645
color DATA       = #DBDBDB
color HEADERS    = #808080
color BACKGROUND = #161616
color BORDERS    = #2E2E2E

string TOP_RIGHT    = 'Top Right'
string BOTTOM_RIGHT = 'Bottom Right'
string BOTTOM_LEFT  = 'Bottom Left'

string TINY   = 'Tiny'
string SMALL  = 'Small'
string NORMAL = 'Normal'
string LARGE  = 'Large'
string HUGE   = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string G1 = "Market Structure"
pivotLenInput   = input.int(5, "Pivot Lookback", minval = 1, group = G1)
showBosInput    = input.bool(true, "Show BOS", group = G1)
showChochInput  = input.bool(true, "Show CHoCH", group = G1)

string G2 = "SVM Ranking Parameters"
volWeightInput  = input.float(0.4, "Relative Volume Weight", minval = 0, maxval = 1, step = 0.1, group = G2)
rsiWeightInput  = input.float(0.3, "RSI Momentum Weight", minval = 0, maxval = 1, step = 0.1, group = G2)
distWeightInput = input.float(0.3, "Break Distance Weight", minval = 0, maxval = 1, step = 0.1, group = G2)
atrLenInput     = input.int(14, "ATR Length for Normalization", minval = 1, group = G2)

string DASHBOARD_GROUP = 'Dashboard'
dashboardInput          = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput      = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type BreakInfo
    string typeStr
    float  score
    int    time
    bool   isBullish

//---------------------------------------------------------------------------------------------------------------------}
// Global Variables & Arrays
//---------------------------------------------------------------------------------------------------------------------{
var breakHistoryArray = array.new<BreakInfo>(0)

// Market Structure State
var float lastPivotHi = na
var int   lastPivotHiIdx = na
var float lastPivotLo = na
var int   lastPivotLoIdx = na
var int   trend = 0 // 1 Bull, -1 Bear

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard State Parsing
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
// Sigmoid function to normalize SVM score to 0-100 range
sigmoid(float x) =>
    100 / (1 + math.exp(-x))

// Helper for LuxAlgo Tables
cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

//---------------------------------------------------------------------------------------------------------------------}
// Core Logic
//---------------------------------------------------------------------------------------------------------------------{
// Pivot Detection
ph = ta.pivothigh(high, pivotLenInput, pivotLenInput)
pl = ta.pivotlow(low, pivotLenInput, pivotLenInput)

if not na(ph)
    lastPivotHi := ph
    lastPivotHiIdx := bar_index - pivotLenInput

if not na(pl)
    lastPivotLo := pl
    lastPivotLoIdx := bar_index - pivotLenInput

// Features for SVM
relVol = volume / ta.sma(volume, 20)
rsiVal = ta.rsi(close, 14)
rsiFeature = math.abs(rsiVal - 50) / 50 // Normalized deviation from midpoint
atr = ta.atr(atrLenInput)

// Logic to identify breaks
bool isBosBull   = false
bool isChochBull  = false
bool isBosBear   = false
bool isChochBear  = false

float currentScore = 0.0

if not na(lastPivotHi) and close > lastPivotHi and high[1] <= lastPivotHi
    // Bullish Break
    distFeature = (close - lastPivotHi) / (atr > 0 ? atr : 1)
    
    // Linear SVM-like weighted sum
    rawScore = (relVol * volWeightInput) + (rsiFeature * rsiWeightInput) + (distFeature * distWeightInput)
    currentScore := sigmoid(rawScore * 2 - 1) // Scaling for better distribution
    
    if trend == -1
        isChochBull := true
        trend := 1
    else
        isBosBull := true
        trend := 1
    
    // Visuals
    lineColor = isChochBull ? BULL_COLOR : BULL_COLOR
    lineStyle = isChochBull ? line.style_dashed : line.style_solid
    string breakType = isChochBull ? "CHoCH" : "BOS"
    
    line.new(lastPivotHiIdx, lastPivotHi, bar_index, lastPivotHi, color = lineColor, style = lineStyle)
    label.new(math.round((lastPivotHiIdx + bar_index) / 2), lastPivotHi, breakType + "\n" + str.format("{0,number,#.##}", currentScore), 
         color = BACKGROUND, 
         textcolor = BULL_COLOR, 
         style = label.style_label_down, 
         size = size.small)
    
    // Store in history
    array.unshift(breakHistoryArray, BreakInfo.new(breakType, currentScore, time, true))
    if array.size(breakHistoryArray) > 5
        array.pop(breakHistoryArray)
        
    lastPivotHi := na // Reset so it doesn't trigger again for the same level

else if not na(lastPivotLo) and close < lastPivotLo and low[1] >= lastPivotLo
    // Bearish Break
    distFeature = (lastPivotLo - close) / (atr > 0 ? atr : 1)
    
    rawScore = (relVol * volWeightInput) + (rsiFeature * rsiWeightInput) + (distFeature * distWeightInput)
    currentScore := sigmoid(rawScore * 2 - 1)
    
    if trend == 1
        isChochBear := true
        trend := -1
    else
        isBosBear := true
        trend := -1
        
    lineColor = isChochBear ? BEAR_COLOR : BEAR_COLOR
    lineStyle = isChochBear ? line.style_dashed : line.style_solid
    string breakType = isChochBear ? "CHoCH" : "BOS"
    
    line.new(lastPivotLoIdx, lastPivotLo, bar_index, lastPivotLo, color = lineColor, style = lineStyle)
    label.new(math.round((lastPivotLoIdx + bar_index) / 2), lastPivotLo, breakType + "\n" + str.format("{0,number,#.##}", currentScore), 
         color = BACKGROUND, 
         textcolor = BEAR_COLOR, 
         style = label.style_label_up, 
         size = size.small)
         
    array.unshift(breakHistoryArray, BreakInfo.new(breakType, currentScore, time, false))
    if array.size(breakHistoryArray) > 5
        array.pop(breakHistoryArray)
        
    lastPivotLo := na // Reset

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
if dashboardInput and barstate.islast
    var table t_able = table.new(parsedDashboardPosition, 3, 13, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)
    
    t_able.merge_cells(0, 0, 2, 0)
    cell(t_able, 0, 0, "Structural SVM Ranking", color = DATA, align = text.align_center)
    
    divider(t_able, 1, 2)
    
    cell(t_able, 0, 2, "Break Type", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 2, "Direction", color = HEADERS)
    cell(t_able, 2, 2, "SVM Score", color = HEADERS)
    
    if array.size(breakHistoryArray) > 0
        for i = 0 to array.size(breakHistoryArray) - 1
            BreakInfo info = array.get(breakHistoryArray, i)
            row = 3 + (i * 2)
            divider(t_able, row, 2)
            
            dataRow = row + 1
            cell(t_able, 0, dataRow, info.typeStr, color = DATA, align = text.align_left)
            cell(t_able, 1, dataRow, info.isBullish ? "Bullish" : "Bearish", color = info.isBullish ? BULL_COLOR : BEAR_COLOR)
            cell(t_able, 2, dataRow, str.format("{0,number,#.##}", info.score), color = info.score > 70 ? BULL_COLOR : info.score < 30 ? BEAR_COLOR : DATA)

//---------------------------------------------------------------------------------------------------------------------}