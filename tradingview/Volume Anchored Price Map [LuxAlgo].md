// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Volume Anchored Price Map [LuxAlgo]", "LuxAlgo - VolAnchoredMap", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR      = #089981
color BEAR_COLOR      = #f23645
color NEUTRAL_COLOR   = #787b86

string PROFILE_GROUP  = "Price Map Profile"
string BUBBLE_GROUP   = "Volume Bubbles"
string DASHBOARD_GROUP= "Dashboard"

// Dashboard constants
color DATA            = #DBDBDB
color HEADERS         = #808080
color BACKGROUND      = #161616
color BORDERS         = #2E2E2E

string TOP_RIGHT      = 'Top Right'
string BOTTOM_RIGHT   = 'Bottom Right'
string BOTTOM_LEFT    = 'Bottom Left'

string TINY           = 'Tiny'
string SMALL          = 'Small'
string NORMAL         = 'Normal'
string LARGE          = 'Large'
string HUGE           = 'Huge'
//---------------------------------------------------------------------------------------------------------------------}

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
// Price Map Profile Inputs
profileLengthInput    = input.int(200, "Lookback Length", minval = 50, maxval = 5000, group = PROFILE_GROUP)
profileBinsInput      = input.int(80, "Price Bins", minval = 10, maxval = 200, group = PROFILE_GROUP)
showProfileInput      = input.bool(true, "Show Price Map Profile", group = PROFILE_GROUP)
profileColorInput     = input.color(color.new(#787b86, 80), "Profile Color", group = PROFILE_GROUP)

// Volume Bubbles Inputs
showBubblesInput      = input.bool(true, "Show Volume Bubbles", group = BUBBLE_GROUP)
bubbleThresholdInput  = input.float(2.0, "Bubble Sensitivity (Z-Score)", minval = 0.5, step = 0.5, group = BUBBLE_GROUP)
projectLevelsInput    = input.bool(true, "Project Levels from Bubbles", group = BUBBLE_GROUP)
levelsQtyInput        = input.int(5, "Max Projected Levels", minval = 1, group = BUBBLE_GROUP)
labelOffsetInput      = input.int(10, "Label Horizontal Offset", minval = 0, group = BUBBLE_GROUP, tooltip = "Increase this if TIER labels overlap with the profile.")

// Dashboard Inputs
dashboardInput        = input.bool(true, 'Enable Dashboard', group = DASHBOARD_GROUP)
dashboardPositionInput= input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput    = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])
//---------------------------------------------------------------------------------------------------------------------}

//---------------------------------------------------------------------------------------------------------------------}
// Types & Variables
//---------------------------------------------------------------------------------------------------------------------{
var box[] profileBoxes     = array.new<box>()
var line[] projectedLines  = array.new<line>()
var label[] bubbleLabels   = array.new<label>()
var label[] levelLabels    = array.new<label>()
var float[] volBins        = array.new<float>()

// Dashboard Logic
var parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT    => position.top_right
    BOTTOM_RIGHT => position.bottom_right
    BOTTOM_LEFT  => position.bottom_left

var parsedDashboardSize = switch dashboardSizeInput
    TINY   => size.tiny
    SMALL  => size.small
    NORMAL => size.normal
    LARGE  => size.large
    HUGE   => size.huge
//---------------------------------------------------------------------------------------------------------------------}

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
// Global series calculations
volAvg   = ta.sma(volume, 200)
volStd   = ta.stdev(volume, 200)
volZ     = (volume - volAvg) / nz(volStd, 1)
totalVol = ta.cum(volume)

isBubble = volZ > bubbleThresholdInput

// Buffer Assignment for stability
srcHl2    = hl2
srcVol    = volume
srcHi     = high
srcLo     = low
srcCl     = close
srcOp     = open
srcZ      = volZ
srcAvg    = volAvg
srcBub    = isBubble

max_bars_back(srcHl2, 5000)
max_bars_back(srcVol, 5000)
max_bars_back(srcHi, 5000)
max_bars_back(srcLo, 5000)
max_bars_back(srcCl, 5000)
max_bars_back(srcOp, 5000)
max_bars_back(srcZ, 5000)
max_bars_back(srcAvg, 5000)
max_bars_back(srcBub, 5000)

// Sensitive Bubble size logic based on Z-Score
get_bubble_size(float z) =>
    string sz = size.tiny
    if z > 5.0
        sz := size.huge
    else if z > 3.8
        sz := size.large
    else if z > 2.8
        sz := size.normal
    else if z > 2.3
        sz := size.small
    sz

// Importance Text Logic
get_importance_text(float z) =>
    if z > 6.0
        "TIER I"
    else if z > 4.0
        "TIER II"
    else
        "TIER III"

// Window variables
float windowHi = ta.highest(srcHi, profileLengthInput)
float windowLo = ta.lowest(srcLo, profileLengthInput)

// Perform Visual Rendering on the last bar
if barstate.islast
    // 1. Clear old objects
    if array.size(profileBoxes) > 0
        for b in profileBoxes
            box.delete(b)
        array.clear(profileBoxes)

    if array.size(bubbleLabels) > 0
        for l in bubbleLabels
            label.delete(l)
        array.clear(bubbleLabels)

    if array.size(projectedLines) > 0
        for ln in projectedLines
            line.delete(ln)
        array.clear(projectedLines)

    if array.size(levelLabels) > 0
        for lb in levelLabels
            label.delete(lb)
        array.clear(levelLabels)

    // 2. Profile Logic
    if showProfileInput
        float priceStep = (windowHi - windowLo) / profileBinsInput
        array.clear(volBins)
        for i = 0 to profileBinsInput - 1
            array.push(volBins, 0.0)
        
        for i = 0 to profileLengthInput - 1
            float barPrice = srcHl2[i]
            float barVol   = srcVol[i]
            if barPrice >= windowLo and barPrice <= windowHi
                int binIdx = math.min(profileBinsInput - 1, int((barPrice - windowLo) / priceStep))
                array.set(volBins, binIdx, array.get(volBins, binIdx) + barVol)
                
        float maxVolInBin = array.max(volBins)
        if maxVolInBin > 0
            for i = 0 to profileBinsInput - 1
                float binVol = array.get(volBins, i)
                if binVol > 0
                    float lowerPrice = windowLo + (i * priceStep)
                    float upperPrice = lowerPrice + priceStep
                    int width = int((binVol / maxVolInBin) * 40) 
                    color binColor = color.from_gradient(binVol, 0, maxVolInBin, color.new(profileColorInput, 90), color.new(profileColorInput, 40))
                    
                    array.push(profileBoxes, box.new(bar_index + 2, upperPrice, bar_index + 2 + width, lowerPrice, na, bgcolor = binColor))

    // 3. Bubbles & Projected Levels Logic
    if showBubblesInput
        int levelsCount = 0
        int labelX = bar_index + 45 + labelOffsetInput

        for i = 0 to profileLengthInput - 1
            float bubblePrice = srcHl2[i]
            if srcBub[i] and bubblePrice <= windowHi and bubblePrice >= windowLo
                color bubbleColor = srcCl[i] > srcOp[i] ? color.new(BULL_COLOR, 40) : color.new(BEAR_COLOR, 40)
                string bubbleSize = get_bubble_size(srcZ[i])
                
                label lbl = label.new(
                  x = bar_index - i, 
                  y = bubblePrice, 
                  text = "", 
                  style = label.style_circle, 
                  color = bubbleColor, 
                  size = bubbleSize,
                  tooltip = "Vol Z-Score: " + str.tostring(srcZ[i], "#.##") + "\nVolume: " + str.tostring(srcVol[i], format.volume)
                  )
                array.push(bubbleLabels, lbl)

                // Projected Levels & Importance Tags
                if projectLevelsInput and levelsCount < levelsQtyInput
                    line l = line.new(
                      x1 = bar_index - i, 
                      y1 = bubblePrice, 
                      x2 = labelX, 
                      y2 = bubblePrice, 
                      color = bubbleColor, 
                      style = line.style_dashed, 
                      extend = extend.none
                      )
                    array.push(projectedLines, l)
                    
                    label impLbl = label.new(
                      x = labelX, 
                      y = bubblePrice, 
                      text = get_importance_text(srcZ[i]), 
                      style = label.style_label_left, 
                      textcolor = bubbleColor, 
                      color = color.new(chart.bg_color, 100), 
                      size = size.small
                      )
                    array.push(levelLabels, impLbl)
                    
                    levelsCount += 1
//---------------------------------------------------------------------------------------------------------------------}

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
cell(table t, int col, int row, string txt, color color = color.white, string halign = text.align_right, color bg = na, float h = 0) => 
    table.cell(t, col, row, txt, text_color = color, text_size = parsedDashboardSize, text_halign = halign, bgcolor = bg, height = h)

divider(table t, int row, int lastCol) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━━━'
    table.merge_cells(t, 0, row, lastCol, row)
    cell(t, 0, row, rowDivider, color = BORDERS, halign = text.align_center, h = 0.5)

if dashboardInput and barstate.islast
    var table dashTable = table.new(parsedDashboardPosition, 2, 7, bgcolor = BACKGROUND, frame_color = BORDERS, frame_width = 1)
    
    table.merge_cells(dashTable, 0, 0, 1, 0)
    cell(dashTable, 0, 0, "Volume Price Map", DATA, text.align_center)
    
    divider(dashTable, 1, 1)
    
    cell(dashTable, 0, 2, "Anchored Lookback", HEADERS, text.align_left)
    cell(dashTable, 1, 2, str.tostring(profileLengthInput), DATA)
    
    divider(dashTable, 3, 1)
    
    cell(dashTable, 0, 4, "Max Vol Level", HEADERS, text.align_left)
    float hiVal = array.size(volBins) > 0 ? array.max(volBins) : 0.0
    int hiIdx   = array.size(volBins) > 0 ? array.indexof(volBins, hiVal) : 0
    float hiLevelLo = windowLo + (hiIdx * ((windowHi - windowLo) / profileBinsInput))
    cell(dashTable, 1, 4, str.tostring(hiLevelLo, "#.##"), DATA)
    
    divider(dashTable, 5, 1)
    
    cell(dashTable, 0, 6, "Vol Z-Score", HEADERS, text.align_left)
    cell(dashTable, 1, 6, str.tostring(volZ, "#.##"), volZ > bubbleThresholdInput ? BULL_COLOR : DATA)
//---------------------------------------------------------------------------------------------------------------------}