// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Volumetric Regression Heatmap [LuxAlgo]", "LuxAlgo - Volumetric Regression Heatmap", overlay = true, max_labels_count = 500, max_polylines_count = 100, max_boxes_count = 100)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{

var string G_CORE = "Core Settings"
var string G_HEATMAP = "Heatmap Settings"
var string G_HEATMAP_COLORS = "Heatmap Colors"
var string G_SIGNALS = "Mean Reversion Signals"
var string G_DELTA = "Delta Histograms"
var string G_STYLE = "Style & Options"
var string G_DASH = "Dashboard"

color DATA                    = #DBDBDB
color HEADERS                 = #808080
color BACKGROUND              = #161616
color BORDERS                 = #2E2E2E

string TOP_RIGHT               = 'Top Right'
string BOTTOM_RIGHT            = 'Bottom Right'
string BOTTOM_LEFT             = 'Bottom Left'

string TINY                    = 'Tiny'
string SMALL                   = 'Small'
string NORMAL                  = 'Normal'
string LARGE                   = 'Large'
string HUGE                    = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{

sourceInput = input.source(hl2, "Source", group = G_CORE, tooltip = "The price data used to calculate the regression channel.")
baseLengthInput = input.int(400, "Base Period", minval = 50, maxval = 1000, group = G_CORE, tooltip = "The base number of bars back used to calculate the regression fit window.")
dynamicLengthInput = input.bool(true, "Dynamic Auto-Adjusting Period", group = G_CORE, tooltip = "When enabled, the channel period automatically adapts based on market volatility (shrinks in high volatility, expands in low volatility).")

numBinsInput = input.int(40, "Grid Rows Each Side", minval = 5, maxval = 45, group = G_HEATMAP, tooltip = "The number of parallel channel levels plotted above and below the center line.")
smoothBinsInput = input.int(4, "Gradient Smoothing", minval = 0, maxval = 20, group = G_HEATMAP, tooltip = "Smoothes the volume profile to create a gradual color gradient across the channels.")

color1Input = input.color(color.new(#000000, 100), "Color 1 (Low Volume)", group = G_HEATMAP_COLORS)
color2Input = input.color(color.new(#5b9cf6, 95), "Color 2", group = G_HEATMAP_COLORS)
color3Input = input.color(color.new(#089981, 90), "Color 3", group = G_HEATMAP_COLORS)
color4Input = input.color(color.new(#ff9800, 80), "Color 4", group = G_HEATMAP_COLORS)
color5Input = input.color(color.new(#f23645, 60), "Color 5 (High Volume)", group = G_HEATMAP_COLORS)

showSignalsInput = input.bool(true, "Show Mean Reversion Signals", group = G_SIGNALS)
signalBandInput = input.float(2.0, "Signal Band (SD Multiplier)", group = G_SIGNALS, tooltip = "The standard deviation level price must reach to trigger a reversion signal.")
slopeThresholdInput = input.float(2.5, "Flat Slope Threshold", step = 0.5, group = G_SIGNALS, tooltip = "Maximum ratio of channel height to standard deviation. Lower values require the channel to be flatter for signals to appear.")

showDeltaInput = input.bool(true, "Show Top/Bottom Delta Histograms", group = G_DELTA)
deltaScaleInput = input.float(0.6, "Histogram Height Scale", minval=0.1, maxval=2.0, step=0.1, group=G_DELTA, tooltip="Scales the height of the volume delta bars extending from the top and bottom of the channel.")
deltaWidthInput = input.int(3, "Histogram Bar Width", minval=1, maxval=10, group=G_DELTA)
buyColorInput = input.color(color.new(#089981, 40), "Buy Volume Color", group = G_DELTA)
sellColorInput = input.color(color.new(#f23645, 40), "Sell Volume Color", group = G_DELTA)

lineWidthInput = input.int(10, "Heatmap Line Width", minval = 1, maxval = 100, group = G_STYLE, tooltip = "Controls the thickness of the heatmap bands to fill empty spaces.")
extendLengthInput = input.int(30, "Future Projection Length", minval = 0, maxval = 200, group = G_STYLE, tooltip = "Number of bars to extend the heatmap into the future.")
showProfileInput = input.bool(true, "Show Volume Profile Histogram", group = G_STYLE, tooltip = "Displays a bookmap-style volume histogram extending to the right of the current price.")
profileWidthInput = input.int(30, "Histogram Width", minval = 5, maxval = 100, group = G_STYLE)

dashboardInput          = input.bool(   true,       'Dashboard',    group = G_DASH, tooltip = 'Enable or disable the dashboard.')
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',     group = G_DASH, tooltip = 'Select the dashboard location.' , options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput      = input.string( SMALL,      'Size',         group = G_DASH, tooltip = 'Select the dashboard size.',      options = [TINY,SMALL,NORMAL,LARGE,HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Types and Variables
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

var polyline[] activeLines = array.new<polyline>()
var label[] signalLabels = array.new<label>()
var box[] profileBoxes = array.new<box>()

var table dashTable = table.new(parsedDashboardPosition, 2, 9, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1, force_overlay = false)

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{

cell(table t_able, int column, int row, string data, color textCol = color.white, string align = text.align_right, color background = na, float h = 0) => 
    t_able.cell(column, row, data, text_color = textCol, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = h)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, BORDERS, text.align_center, na, 0.5)

get_gradient_color(float value, float max_value) =>
    float ratio = max_value > 0 ? value / max_value : 0
    ratio := math.pow(ratio, 0.7) // Elevate lower ratios for a broader gradient
    result = ratio < 0.25 ? color.from_gradient(ratio, 0.0, 0.25, color1Input, color2Input) : ratio < 0.5 ? color.from_gradient(ratio, 0.25, 0.5, color2Input, color3Input) : ratio < 0.75 ? color.from_gradient(ratio, 0.5, 0.75, color3Input, color4Input) : color.from_gradient(ratio, 0.75, 1.0, color4Input, color5Input)
    result

get_linreg(series float src, int len) =>
    float sumX = 0.0
    float sumY = 0.0
    float sumXY = 0.0
    float sumX2 = 0.0
    for i = 0 to len - 1
        float y = src[i]
        float x = (len - 1) - i
        sumX += x
        sumY += y
        sumXY += x * y
        sumX2 += x * x
    float m = len > 1 ? (len * sumXY - sumX * sumY) / (len * sumX2 - sumX * sumX) : 0
    float b = len > 0 ? (sumY - m * sumX) / len : 0
    [b, b + m * (len - 1)]

get_stdev(series float src, int len) =>
    float sum = 0.0
    for i = 0 to len - 1
        sum += src[i]
    float mean = sum / len
    float sumSq = 0.0
    for i = 0 to len - 1
        sumSq += math.pow(src[i] - mean, 2)
    math.sqrt(sumSq / len)

//---------------------------------------------------------------------------------------------------------------------}
// Core Logic
//---------------------------------------------------------------------------------------------------------------------{

// Force Pine to keep enough history for our dynamic lookback operations
var float _historicalSrc = sourceInput[1000]
var float _historicalClose = close[1000]
var float _historicalHigh = high[1000]
var float _historicalLow = low[1000]
var float _historicalVol = volume[1000]

float atrFast = nz(ta.atr(20))
float atrSlow = nz(ta.atr(200))

int currentLength = baseLengthInput
if dynamicLengthInput and atrFast > 0 and atrSlow > 0
    float ratio = atrSlow / atrFast
    currentLength := math.round(baseLengthInput * ratio)
    currentLength := math.max(50, math.min(currentLength, 1000)) // Constrain between 50 and 1000

[startVal, endVal] = get_linreg(sourceInput, currentLength)
float stdevVal = get_stdev(sourceInput, currentLength)
float slope = currentLength > 1 ? (endVal - startVal) / (currentLength - 1) : 0

float totalRise = math.abs(endVal - startVal)
bool isContraction = totalRise < (stdevVal * slopeThresholdInput)

// Dashboard Update
if barstate.islast and dashboardInput
    dashTable.merge_cells(0, 0, 1, 0)
    cell(dashTable, 0, 0, 'Heatmap Analytics', DATA, text.align_center, na, 0)
    
    divider(dashTable, 1, 1)
    
    cell(dashTable, 0, 2, 'Market State', HEADERS, text.align_left, na, 0)
    cell(dashTable, 1, 2, isContraction ? 'Contraction' : 'Expansion', isContraction ? color.new(#ff9800, 0) : color.new(#089981, 0), text.align_right, na, 0)
    
    cell(dashTable, 0, 3, 'Trend Bias', HEADERS, text.align_left, na, 0)
    cell(dashTable, 1, 3, slope > 0 ? 'Bullish' : 'Bearish', slope > 0 ? color.new(#089981, 0) : color.new(#f23645, 0), text.align_right, na, 0)

    divider(dashTable, 4, 1)

    cell(dashTable, 0, 5, 'Channel Length', HEADERS, text.align_left, na, 0)
    cell(dashTable, 1, 5, str.tostring(currentLength), DATA, text.align_right, na, 0)
    
    cell(dashTable, 0, 6, 'Channel Width', HEADERS, text.align_left, na, 0)
    cell(dashTable, 1, 6, str.tostring(math.round(stdevVal * 6, 2)), DATA, text.align_right, na, 0)
else if barstate.islast and not dashboardInput
    dashTable.clear(0, 0, 1, 6)

// Heatmap Drawing
if barstate.islast
    int totalLen = currentLength + extendLengthInput
    float[] predictions = array.new<float>()
    for i = 0 to totalLen - 1
        predictions.push(startVal + slope * i)

    float dev = (stdevVal * 3) / numBinsInput
    int predSize = array.size(predictions)

    if array.size(signalLabels) > 0
        for lbl in signalLabels
            label.delete(lbl)
        array.clear(signalLabels)

    if showSignalsInput and isContraction
        for i = 1 to currentLength - 1
            int lookupIdx = math.min(i, currentLength - 1)
            int prevIdx = math.min(i - 1, currentLength - 1)
            
            float currClose = close[currentLength - 1 - lookupIdx]
            float prevClose = close[currentLength - 1 - prevIdx]
            
            float currPred = array.get(predictions, lookupIdx)
            float prevPred = array.get(predictions, prevIdx)
            
            float currUpper = currPred + (stdevVal * signalBandInput)
            float prevUpper = prevPred + (stdevVal * signalBandInput)
            
            float currLower = currPred - (stdevVal * signalBandInput)
            float prevLower = prevPred - (stdevVal * signalBandInput)
            
            bool crossUnderLower = prevClose >= prevLower and currClose < currLower
            bool crossOverUpper  = prevClose <= prevUpper and currClose > currUpper
            
            int targetX = bar_index - currentLength + 1 + lookupIdx
            
            if crossUnderLower
                signalLabels.push(label.new(targetX, low[currentLength - 1 - lookupIdx], text="", style=label.style_circle, color=color.new(#089981, 0), size=size.tiny))
            if crossOverUpper
                signalLabels.push(label.new(targetX, high[currentLength - 1 - lookupIdx], text="", style=label.style_circle, color=color.new(#f23645, 0), size=size.tiny))
    
    float[] binVolumes = array.new<float>(numBinsInput * 2, 0.0)
    float[] buyVols = array.new<float>()
    float[] sellVols = array.new<float>()
    float maxDeltaVol = 0.0
    
    // Accumulate volume into bins only on historical bars
    for i = 0 to currentLength - 1
        int lookupIdx = math.min(i, predSize - 1)
        float currClose = sourceInput[currentLength - 1 - lookupIdx]
        float basePred  = array.get(predictions, lookupIdx)
        
        float diff = currClose - basePred
        int binIndex = math.floor(diff / dev) + numBinsInput
        
        float v = nz(volume[currentLength - 1 - lookupIdx])
        
        if binIndex >= 0 and binIndex < numBinsInput * 2
            array.set(binVolumes, binIndex, array.get(binVolumes, binIndex) + v)
            
        float c = close[currentLength - 1 - lookupIdx]
        float o = open[currentLength - 1 - lookupIdx]
        float h = high[currentLength - 1 - lookupIdx]
        float l = low[currentLength - 1 - lookupIdx]
        
        float hlRange = h - l
        float buyVol = hlRange == 0 ? v / 2 : v * (c - l) / hlRange
        float sellVol = hlRange == 0 ? v / 2 : v * (h - c) / hlRange
        
        buyVols.push(buyVol)
        sellVols.push(sellVol)
        
        if buyVol > maxDeltaVol
            maxDeltaVol := buyVol
        if sellVol > maxDeltaVol
            maxDeltaVol := sellVol

    // Smooth the volume distribution for a gradual gradient
    float[] smoothedBins = array.copy(binVolumes)
    if smoothBinsInput > 0
        for s = 1 to smoothBinsInput
            float[] temp = array.copy(smoothedBins)
            for i = 0 to (numBinsInput * 2) - 1
                float val = array.get(temp, i)
                float left1 = i > 0 ? array.get(temp, i - 1) : val
                float right1 = i < (numBinsInput * 2) - 1 ? array.get(temp, i + 1) : val
                float left2 = i > 1 ? array.get(temp, i - 2) : left1
                float right2 = i < (numBinsInput * 2) - 2 ? array.get(temp, i + 2) : right1
                array.set(smoothedBins, i, (left2 + left1 * 4.0 + val * 6.0 + right1 * 4.0 + right2) / 16.0)

    float maxVol = array.max(smoothedBins)

    // Clear previous lines and boxes
    if array.size(activeLines) > 0
        for p in activeLines
            polyline.delete(p)
        array.clear(activeLines)
        
    if array.size(profileBoxes) > 0
        for b in profileBoxes
            box.delete(b)
        array.clear(profileBoxes)

    // Draw Heatmap & Profile
    if maxVol > 0
        for step = 0 to (numBinsInput * 2) - 1
            float volWeight = array.get(smoothedBins, step)
            
            float binOffset = (step - numBinsInput) * dev + (dev / 2) // center of the bin
            
            chart.point[] profilePoints = array.new<chart.point>()
            color colBin = get_gradient_color(volWeight, maxVol)
            
            for idx = 0 to totalLen - 1
                float baseP = array.get(predictions, idx)
                int targetX = bar_index + idx - currentLength + 1
                profilePoints.push(chart.point.from_index(targetX, baseP + binOffset))

            if array.size(profilePoints) > 1
                activeLines.push(polyline.new(profilePoints, line_width = lineWidthInput, line_style = line.style_solid, line_color = colBin))

            // Draw right side Volume Profile Histogram
            if showProfileInput and volWeight > 0
                // Anchor the histogram at the end of the projection
                float boxTop = array.get(predictions, totalLen - 1) + binOffset + (dev / 2)
                float boxBot = array.get(predictions, totalLen - 1) + binOffset - (dev / 2)
                
                int boxLen = math.max(1, math.round((volWeight / maxVol) * profileWidthInput))
                int startX = bar_index + extendLengthInput + 1
                int endX = startX + boxLen
                
                profileBoxes.push(box.new(startX, boxTop, endX, boxBot, bgcolor = color.new(colBin, 40), border_color = color.new(colBin, 70), border_width = 1))

    // Draw Delta Histograms
    if showDeltaInput and maxDeltaVol > 0
        chart.point[] buyPoints = array.new<chart.point>()
        chart.point[] sellPoints = array.new<chart.point>()

        float maxHeight = (stdevVal * 3) * deltaScaleInput

        for i = 0 to currentLength - 1
            int lookupIdx = math.min(i, predSize - 1)
            float basePred = array.get(predictions, lookupIdx)
            int targetX = bar_index - currentLength + 1 + lookupIdx

            float topBand = basePred + (stdevVal * 3)
            float botBand = basePred - (stdevVal * 3)

            float bV = array.get(buyVols, i)
            float sV = array.get(sellVols, i)

            float buyH = topBand + (bV / maxDeltaVol) * maxHeight
            float sellH = botBand - (sV / maxDeltaVol) * maxHeight

            buyPoints.push(chart.point.from_index(targetX, topBand))
            buyPoints.push(chart.point.from_index(targetX, buyH))
            buyPoints.push(chart.point.from_index(targetX, topBand))

            sellPoints.push(chart.point.from_index(targetX, botBand))
            sellPoints.push(chart.point.from_index(targetX, sellH))
            sellPoints.push(chart.point.from_index(targetX, botBand))

        if array.size(buyPoints) > 1
            activeLines.push(polyline.new(buyPoints, line_width = deltaWidthInput, line_style = line.style_solid, line_color = buyColorInput))
            activeLines.push(polyline.new(sellPoints, line_width = deltaWidthInput, line_style = line.style_solid, line_color = sellColorInput))

//---------------------------------------------------------------------------------------------------------------------}