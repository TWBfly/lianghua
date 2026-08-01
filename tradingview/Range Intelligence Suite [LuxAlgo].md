// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Range Intelligence Suite [LuxAlgo]", "LuxAlgo - Range Intel", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_polylines_count = 100)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR        = #089981
color BEAR_COLOR        = #f23645
color NEUTRAL_COLOR     = #787b86
color GOLD_COLOR        = #eab308

color DATA              = #DBDBDB
color HEADERS           = #808080
color BACKGROUND        = #161616
color BORDERS           = #2E2E2E

string TOP_RIGHT        = 'Top Right'
string BOTTOM_RIGHT     = 'Bottom Right'
string BOTTOM_LEFT      = 'Bottom Left'

string TINY             = 'Tiny'
string SMALL            = 'Small'
string NORMAL           = 'Normal'
string LARGE            = 'Large'
string HUGE             = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string DETECTION_GROUP  = 'Intelligence Core'
int lengthInput         = input.int(20, 'Detection Length', minval = 5, group = DETECTION_GROUP, tooltip = 'The lookback period used to identify consolidation ranges.')
float thresholdInput    = input.float(4.0, 'Range Sensitivity', minval = 0.1, step = 0.1, group = DETECTION_GROUP, tooltip = 'ATR multiplier that determines how "tight" the price must be to trigger a range.')
bool hideOverlapsInput  = input.bool(true, 'Hide Overlapping Ranges', group = DETECTION_GROUP, tooltip = 'When enabled, only the most recent range is shown if multiple ranges overlap in time.')

string VISUAL_GROUP     = 'Visual UX'
color bullColorInput    = input.color(BULL_COLOR, 'Bullish Color', inline = 'Colors', group = VISUAL_GROUP)
color bearColorInput    = input.color(BEAR_COLOR, 'Bearish Color', inline = 'Colors', group = VISUAL_GROUP)
int zoneTransparencyInput = input.int(85, 'Fill Transparency', minval = 0, maxval = 100, group = VISUAL_GROUP, tooltip = 'Transparency of the range background fills.')
bool showPOCInput       = input.bool(true, 'Show Point of Control (POC)', group = VISUAL_GROUP, tooltip = 'Displays the price level with the highest total volume within the range.')
bool showSweepsInput    = input.bool(true, 'Highlight Liquidity Sweeps', group = VISUAL_GROUP, tooltip = 'Highlights fakeouts where price briefly exits the range but closes back inside.')

string VP_GROUP         = 'Volume Profile'
bool showVPInput        = input.bool(true, 'Show Volume Profile', group = VP_GROUP, tooltip = 'Displays a volume histogram to the right of the consolidation range.')
int vpRowsInput         = input.int(10, 'Rows', minval = 5, maxval = 100, group = VP_GROUP, tooltip = 'Number of horizontal bins. Lower values make bins look thicker.')
int vpWidthInput        = input.int(30, 'Profile Max Width (%)', minval = 1, maxval = 100, group = VP_GROUP, tooltip = 'Maximum horizontal length of the volume bars as a percentage of the range duration.')

string DASHBOARD_GROUP  = 'Dashboard'
bool dashboardInput     = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP)
string dashboardPositionInput = input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
string dashboardSizeInput     = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Variables & State
//---------------------------------------------------------------------------------------------------------------------{
var float rangeHigh     = na
var float rangeLow      = na
var float mid           = na
var int   rangeStartIdx = na
var bool  rangeActive   = false

// VP & POC State
var float[] buyBins     = array.new_float(100, 0.0)
var float[] sellBins    = array.new_float(100, 0.0)
var float totalNetDelta = 0.0
var float pocPrice      = na

// Visual containers
var line activeTop      = na
var line activeBottom   = na
var line activeMid      = na
var line activePOC      = na
var line[] upperGrad    = array.new_line(0)
var line[] lowerGrad    = array.new_line(0)
var polyline activeVP   = na

// Overlap Management
type RangeVisuals
    int endIdx
    line top
    line bottom
    line mid
    line poc
    line[] grads
    polyline vp

var RangeVisuals[] historicalRanges = array.new<RangeVisuals>()

method delete(RangeVisuals this) =>
    this.top.delete()
    this.bottom.delete()
    this.mid.delete()
    if not na(this.poc)
        this.poc.delete()
    if not na(this.grads)
        for l in this.grads
            l.delete()
    if not na(this.vp)
        this.vp.delete()

// Core Logic Calculations
float atr               = ta.atr(lengthInput)
float highestHigh       = ta.highest(high, lengthInput)
float lowestLow         = ta.lowest(low, lengthInput)
float rangeWidth        = highestHigh - lowestLow
bool isConsolidating    = rangeWidth < (thresholdInput * atr)

// Liquidity Sweep Detection (Fakeouts)
bool sweepHigh = rangeActive and high > rangeHigh and close < rangeHigh
bool sweepLow  = rangeActive and low < rangeLow and close > rangeLow

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
// Format volume for the dashboard
formatVol(float vol) =>
    float absVol = math.abs(vol)
    string sign = vol >= 0 ? "" : "-"
    if absVol >= 1000000000
        sign + str.tostring(absVol / 1000000000, "#.#") + "B"
    else if absVol >= 1000000
        sign + str.tostring(absVol / 1000000, "#.#") + "M"
    else if absVol >= 1000
        sign + str.tostring(absVol / 1000, "#.#") + "K"
    else
        sign + str.tostring(absVol, "#")

// Draw the Volume Profile using a polyline
drawVP(int endIdx, float rHigh, float rLow, int rows, int maxWidth, float[] bBins, float[] sBins, float netDelta) =>
    float binSize   = (rHigh - rLow) / rows
    float[] totalV  = array.new_float(rows, 0.0)
    for i = 0 to rows - 1
        array.set(totalV, i, array.get(bBins, i) + array.get(sBins, i))
    
    float maxVol    = array.max(totalV)
    if maxVol == 0
        maxVol := 1.0
        
    chart.point[] points = array.new<chart.point>()
    
    // Determine profile color based on net delta of the range
    color vpColor = netDelta >= 0 ? color.new(bullColorInput, 50) : color.new(bearColorInput, 50)
    
    // Start at bottom-left of profile anchor
    array.push(points, chart.point.from_index(endIdx, rLow))
    
    for i = 0 to rows - 1
        float volWidth = (array.get(totalV, i) / maxVol) * maxWidth
        float yBottom  = rLow + (i * binSize)
        float yTop     = rLow + ((i + 1) * binSize)
        
        // Step out to the right (Volume width)
        array.push(points, chart.point.from_index(endIdx + math.round(volWidth), yBottom))
        // Step up (Row height)
        array.push(points, chart.point.from_index(endIdx + math.round(volWidth), yTop))
        
    // Close back at top-left anchor
    array.push(points, chart.point.from_index(endIdx, rHigh))
    polyline.new(points, curved = false, closed = true, line_color = na, fill_color = vpColor)

//---------------------------------------------------------------------------------------------------------------------}
// Main Range Logic
//---------------------------------------------------------------------------------------------------------------------{
// Trigger range start
if isConsolidating and not rangeActive
    rangeActive   := true
    rangeHigh     := highestHigh
    rangeLow      := lowestLow
    rangeStartIdx := bar_index - lengthInput + 1
    mid           := (rangeHigh + rangeLow) / 2

    // Overlap Management: Hide previous ranges if they overlap with the new detection window
    if hideOverlapsInput and historicalRanges.size() > 0
        for i = historicalRanges.size() - 1 to 0
            RangeVisuals r = historicalRanges.get(i)
            if rangeStartIdx <= r.endIdx
                r.delete()
                historicalRanges.remove(i)
    
    // Initialize profile data
    array.fill(buyBins, 0.0, 0, vpRowsInput)
    array.fill(sellBins, 0.0, 0, vpRowsInput)
    totalNetDelta := 0.0
    
    // Catch up: Process lookback bars to fill the profile from the start of consolidation
    float binSize_init = (rangeHigh - rangeLow) / vpRowsInput
    for i = rangeStartIdx to bar_index
        float b_high  = high[bar_index - i]
        float b_low   = low[bar_index - i]
        float b_open  = open[bar_index - i]
        float b_close = close[bar_index - i]
        float b_vol   = volume[bar_index - i]
        
        int minBin = math.max(0, math.min(vpRowsInput - 1, math.floor((b_low - rangeLow) / binSize_init)))
        int maxBin = math.max(0, math.min(vpRowsInput - 1, math.floor((b_high - rangeLow) / binSize_init)))
        int binsCovered = maxBin - minBin + 1
        
        float volShare = b_vol / binsCovered
        bool isBull = b_close >= b_open
        
        for j = minBin to maxBin
            if isBull
                array.set(buyBins, j, array.get(buyBins, j) + volShare)
            else
                array.set(sellBins, j, array.get(sellBins, j) + volShare)
        
        totalNetDelta += (isBull ? b_vol : -b_vol)

    // Calculate initial Point of Control (POC)
    int maxBinPOC_init = 0
    float maxVal_init = -1.0
    for i = 0 to vpRowsInput - 1
        float total = array.get(buyBins, i) + array.get(sellBins, i)
        if total > maxVal_init
            maxVal_init := total
            maxBinPOC_init := i
    pocPrice := rangeLow + (maxBinPOC_init * binSize_init) + (binSize_init / 2)

    // Create boundary visuals
    activeTop    := line.new(rangeStartIdx, rangeHigh, bar_index, rangeHigh, color = bullColorInput, width = 1)
    activeBottom := line.new(rangeStartIdx, rangeLow, bar_index, rangeLow, color = bearColorInput, width = 1)
    activeMid    := line.new(rangeStartIdx, mid, bar_index, mid, color = NEUTRAL_COLOR, style = line.style_dashed)
    
    // Create vertical gradient layers
    int layers = 10
    float stepH = (rangeHigh - mid) / layers
    float stepL = (mid - rangeLow) / layers
    for i = 1 to layers
        line uL = line.new(rangeStartIdx, rangeHigh - (stepH * i), bar_index, rangeHigh - (stepH * i), color = na)
        line lL = line.new(rangeStartIdx, mid - (stepL * i), bar_index, mid - (stepL * i), color = na)
        array.push(upperGrad, uL)
        array.push(lowerGrad, lL)
        int trans = int(zoneTransparencyInput + (i * (100 - zoneTransparencyInput) / layers))
        linefill.new(i == 1 ? activeTop : array.get(upperGrad, i-2), uL, color.new(bullColorInput, trans))
        linefill.new(i == 1 ? activeMid : array.get(lowerGrad, i-2), lL, color.new(bearColorInput, trans))

// Update or Close active range
if rangeActive
    float binSize = (rangeHigh - rangeLow) / vpRowsInput
    
    // Accumulate Volume Data accounting for wicks (for the current bar)
    int minBin = math.max(0, math.min(vpRowsInput - 1, math.floor((low - rangeLow) / binSize)))
    int maxBin = math.max(0, math.min(vpRowsInput - 1, math.floor((high - rangeLow) / binSize)))
    int binsCovered = maxBin - minBin + 1
    
    float bVol = close >= open ? volume / binsCovered : 0.0
    float sVol = close < open ? volume / binsCovered : 0.0
    
    for i = minBin to maxBin
        array.set(buyBins, i, array.get(buyBins, i) + bVol)
        array.set(sellBins, i, array.get(sellBins, i) + sVol)
        
    totalNetDelta += (close >= open ? volume : -volume)
    
    // Calculate Point of Control (POC)
    int maxBinPOC = 0
    float maxVal = -1.0
    for i = 0 to vpRowsInput - 1
        float total = array.get(buyBins, i) + array.get(sellBins, i)
        if total > maxVal
            maxVal := total
            maxBinPOC := i
    pocPrice := rangeLow + (maxBinPOC * binSize) + (binSize / 2)
    
    // Determine dynamic width based on range duration
    int dynamicWidth = math.round((bar_index - rangeStartIdx) * (vpWidthInput / 100.0))

    // Check for Breakout (Range Exit)
    if close > rangeHigh or close < rangeLow
        rangeActive := false
        
        // Finalize Visuals
        activeTop.set_x2(bar_index), activeBottom.set_x2(bar_index), activeMid.set_x2(bar_index)
        for l in upperGrad
            l.set_x2(bar_index)
        for l in lowerGrad
            l.set_x2(bar_index)
        
        if not na(activePOC)
            activePOC.set_x2(bar_index)
        if not na(activeVP)
            activeVP.delete()
            
        // Render permanent historical profile
        polyline histVP = na
        if showVPInput
            histVP := drawVP(bar_index, rangeHigh, rangeLow, vpRowsInput, dynamicWidth, buyBins, sellBins, totalNetDelta)
            
        // Store for overlap management
        historicalRanges.push(RangeVisuals.new(bar_index, activeTop, activeBottom, activeMid, activePOC, array.copy(upperGrad).concat(array.copy(lowerGrad)), histVP))
        if historicalRanges.size() > 50
            historicalRanges.shift().delete()

        // Clear active references
        activeTop := na, activeBottom := na, activeMid := na, activePOC := na, activeVP := na
        array.clear(upperGrad), array.clear(lowerGrad)
    else
        // Live update active range visuals
        activeTop.set_x2(bar_index), activeBottom.set_x2(bar_index), activeMid.set_x2(bar_index)
        for l in upperGrad
            l.set_x2(bar_index)
        for l in lowerGrad
            l.set_x2(bar_index)
            
        if showPOCInput
            if not na(activePOC)
                activePOC.delete()
            activePOC := line.new(rangeStartIdx, pocPrice, bar_index, pocPrice, color = GOLD_COLOR, width = 1, style = line.style_dotted)
            
        if showVPInput
            if not na(activeVP)
                activeVP.delete()
            activeVP := drawVP(bar_index, rangeHigh, rangeLow, vpRowsInput, dynamicWidth, buyBins, sellBins, totalNetDelta)

// Intelligence Markers
if sweepHigh and showSweepsInput
    label.new(bar_index, high, "SH", color = #00000000, textcolor = bearColorInput, style = label.style_label_down, size = size.tiny)
if sweepLow and showSweepsInput
    label.new(bar_index, low, "SL", color = #00000000, textcolor = bullColorInput, style = label.style_label_up, size = size.tiny)

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT    => position.top_right
    BOTTOM_RIGHT => position.bottom_right
    BOTTOM_LEFT  => position.bottom_left
    => position.top_right

var parsedDashboardSize = switch dashboardSizeInput
    TINY   => size.tiny
    SMALL  => size.small
    NORMAL => size.normal
    LARGE  => size.large
    HUGE   => size.huge
    => size.small

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

var table t_able = table.new(parsedDashboardPosition, 2, 7, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)

// Metrics for Dashboard
float recentVolSum = ta.sma(volume, lengthInput) * lengthInput
float duration     = rangeActive ? bar_index - rangeStartIdx + 1 : 0
float intensity    = rangeActive ? math.min(100, (duration / lengthInput) * 50 + (math.abs(totalNetDelta) / recentVolSum) * 50) : 0

if dashboardInput and barstate.islast
    t_able.merge_cells(0, 0, 1, 0)
    cell(t_able, 0, 0, 'Range Intelligence [LuxAlgo]', color = DATA, align = text.align_center)
    divider(t_able, 1, 1)
    
    cell(t_able, 0, 2, 'State', color = HEADERS, align = text.align_left)
    cell(t_able, 1, 2, not rangeActive ? 'Scanning Trend...' : (totalNetDelta >= 0 ? 'Accumulation' : 'Distribution'), color = not rangeActive ? NEUTRAL_COLOR : (totalNetDelta >= 0 ? bullColorInput : bearColorInput))
    
    divider(t_able, 3, 1)
    
    cell(t_able, 0, 4, 'Ready Score', color = HEADERS, align = text.align_left)
    cell(t_able, 1, 4, str.tostring(math.round(intensity)) + "%", color = intensity > 70 ? GOLD_COLOR : DATA)
    
    divider(t_able, 5, 1)
    
    cell(t_able, 0, 6, 'Range Net Delta', color = HEADERS, align = text.align_left)
    cell(t_able, 1, 6, rangeActive ? formatVol(totalNetDelta) : 'N/A', color = totalNetDelta >= 0 ? bullColorInput : bearColorInput)

//---------------------------------------------------------------------------------------------------------------------}
