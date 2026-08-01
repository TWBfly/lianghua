// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Support & Resistance Pro Toolkit [LuxAlgo]", "LuxAlgo - S&R Pro Toolkit", overlay = true, max_lines_count = 500, max_boxes_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Types
//---------------------------------------------------------------------------------------------------------------------{
BULL_COLOR = #089981
BEAR_COLOR = #f23645
NONE_COLOR = #00000000

DATA       = #DBDBDB
HEADERS    = #808080
BACKGROUND = #161616
BORDERS    = #2E2E2E

TOP_RIGHT    = 'Top Right'
BOTTOM_RIGHT = 'Bottom Right'
BOTTOM_LEFT  = 'Bottom Left'

TINY   = 'Tiny'
SMALL  = 'Small'
NORMAL = 'Normal'
LARGE  = 'Large'
HUGE   = 'Huge'

type level
    float top
    float btm
    float basePrice
    int   startBar
    int   startTime
    int   mitigationBar
    int   mitigationTime
    bool  isSupport
    bool  isMitigated
    bool  isUserHidden
    int   entries
    int   strength
    int   sweeps
    float tradedVolume
    line  lineId
    box   boxId
    line  extLineId
    box   extBoxId
    label statsLabel

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
G1 = 'Detection Settings'
METHOD_PIVOTS   = 'Pivots'
METHOD_DONCHIAN = 'Donchian'
METHOD_CSID     = 'CSID'
METHOD_ZIGZAG   = 'ZigZag'

methodInput      = input.string(METHOD_DONCHIAN, 'Detection Method', group = G1, options = [METHOD_PIVOTS, METHOD_DONCHIAN, METHOD_CSID, METHOD_ZIGZAG])
sensitivityInput = input.float(10.0, 'Swing Sensitivity', minval = 0.1, group = G1, tooltip = 'Lookback for Pivots/Donchian/CSID, Deviation % for ZigZag.')

G2 = 'Zone & Level Sizing'
displayTypeInput  = input.string('Zones', 'Display Style', options = ['Levels', 'Zones'], group = G2)
atrPeriodInput    = input.int(200, 'ATR Period', minval = 1, group = G2)
atrMultInput      = input.float(0.5, 'Zone Depth (ATR Mult)', minval = 0.0, group = G2)
securityMultInput = input.float(0.0, 'Breakout Buffer (ATR Mult)', minval = 0.0, group = G2)

G3 = 'Filtering & Visibility'
OVERLAP_NONE        = 'None'
OVERLAP_MERGE       = 'Merge Overlapping'
OVERLAP_HIDE_OLD    = 'Hide Overlapping (Oldest Precedence)'
OVERLAP_HIDE_YOUNG  = 'Hide Overlapping (Youngest Precedence)'
overlapModeInput    = input.string(OVERLAP_HIDE_OLD, 'Overlap Handling', options = [OVERLAP_NONE, OVERLAP_MERGE, OVERLAP_HIDE_OLD, OVERLAP_HIDE_YOUNG], group = G3)
maxLevelsInput      = input.int(5, 'Max Active (Unmitigated)', minval = 1, maxval = 50, group = G3)
showBrokenSRInput   = input.bool(true, 'Show Broken S&R', group = G3)
extendUnmitigated   = input.bool(true, 'Extend Active S&R', group = G3)

G4 = 'Minimum Requirements'
minEntriesInput  = input.int(0, 'Min Price Entries', minval = 0, group = G4)
minStrengthInput = input.int(0, 'Min Overall Strength', minval = 0, group = G4)
minSweepsInput   = input.int(0, 'Min Sweeps', minval = 0, group = G4)
minVolumeInput   = input.float(0, 'Min Traded Volume', minval = 0, group = G4)
minDurationInput = input.int(0, 'Min Duration (Bars)', minval = 0, group = G4)

G5 = 'Visuals & Styles'
supColorInput  = input.color(BULL_COLOR, 'Support Color', group = G5)
resColorInput  = input.color(BEAR_COLOR, 'Resistance Color', group = G5)
sweepHighlight = input.bool(true, 'Highlight Sweeps', group = G5)
breakHighlight = input.bool(true, 'Highlight Breakouts', group = G5)

DASHBOARD_GROUP = 'Dashboard'
dashboardInput          = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput      = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Global ta.* Calls
//---------------------------------------------------------------------------------------------------------------------{
int sensInt = math.max(1, int(sensitivityInput))
float globalAtr = ta.atr(atrPeriodInput)
float cumRange  = ta.cum(math.abs(high - low))
float donchHighest = ta.highest(high, sensInt)
float donchLowest  = ta.lowest(low, sensInt)
float csidHighest = ta.highest(high, sensInt)
float csidLowest  = ta.lowest(low, sensInt)
int   csidHbars   = ta.highestbars(high, sensInt)
int   csidLbars   = ta.lowestbars(low, sensInt)

//---------------------------------------------------------------------------------------------------------------------}
// User-Defined Functions
//---------------------------------------------------------------------------------------------------------------------{
get_atr() =>
    float res = globalAtr
    if na(res)
        res := cumRange / (bar_index + 1)
    res

format_val(float val) =>
    if val >= 1000000000
        str.format("{0,number,#.#}B", val / 1000000000)
    else if val >= 1000000
        str.format("{0,number,#.#}M", val / 1000000)
    else if val >= 1000
        str.format("{0,number,#.#}K", val / 1000)
    else
        str.tostring(val, "#.#")

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

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

//---------------------------------------------------------------------------------------------------------------------}
// Logic & Calculations
//---------------------------------------------------------------------------------------------------------------------{
var level[] levelsArray = array.new<level>()
float currentAtr = get_atr()

float ph = na
float pl = na
int phBar = na
int plBar = na

// Stats tracking
var int totalSupCount = 0
var int totalResCount = 0
var int supMitigated = 0
var int resMitigated = 0
var int supDuration = 0
var int resDuration = 0
var int supSweepsCount = 0
var int resSweepsCount = 0
var float supCumVolume = 0.0
var float resCumVolume = 0.0

// Method 1: Pivots
if methodInput == METHOD_PIVOTS
    ph := ta.pivothigh(sensInt, sensInt)
    pl := ta.pivotlow(sensInt, sensInt)
    if not na(ph)
        phBar := bar_index - sensInt
    if not na(pl)
        plBar := bar_index - sensInt

// Method 2: Donchian (Alternating)
var int donchOs = 0
var float donchVal = na
var int donchValLoc = na
if methodInput == METHOD_DONCHIAN
    donchOs := donchHighest > donchHighest[1] ? 1 : donchLowest < donchLowest[1] ? -1 : donchOs
    if donchOs != donchOs[1]
        if donchOs == 1 
            pl := donchVal
            plBar := donchValLoc
            donchVal := high
            donchValLoc := bar_index
        else 
            ph := donchVal
            phBar := donchValLoc
            donchVal := low
            donchValLoc := bar_index
    else
        if donchOs == 1
            if high >= nz(donchVal, -1.0e10)
                donchVal := high
                donchValLoc := bar_index
        else if donchOs == -1
            if low <= nz(donchVal, 1.0e10)
                donchVal := low
                donchValLoc := bar_index

// Method 3: CSID
var int bullCount = 0
var int bearCount = 0
if methodInput == METHOD_CSID
    bullCount := close > open ? bullCount + 1 : 0
    bearCount := close < open ? bearCount + 1 : 0
    if bullCount == sensInt
        ph := csidHighest
        phBar := bar_index + csidHbars
    if bearCount == sensInt
        pl := csidLowest
        plBar := bar_index + csidLbars

// Method 4: ZigZag
var float zzHigh = na, var float zzLow  = na, var int zzHighBar = na, var int zzLowBar = na, var int zzDir = 0 
if methodInput == METHOD_ZIGZAG
    float dev = (close * sensitivityInput) / 100
    if zzDir == 0
        zzHigh := high, zzLow := low, zzHighBar := bar_index, zzLowBar := bar_index, zzDir := close > open ? 1 : -1
    else if zzDir == 1
        if high > zzHigh
            zzHigh := high, zzHighBar := bar_index
        else if low < zzHigh - dev
            ph := zzHigh, phBar := zzHighBar, zzLow := low, zzLowBar := bar_index, zzDir := -1
    else
        if low < zzLow
            zzLow := low, zzLowBar := bar_index
        else if high > zzLow + dev
            pl := zzLow, plBar := zzLowBar, zzHigh := high, zzHighBar := bar_index, zzDir := 1

// Highlight Swings
if not na(ph)
    label.new(time[bar_index - phBar], ph, "▼", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = resColorInput, style = label.style_label_center, size = size.small)
if not na(pl)
    label.new(time[bar_index - plBar], pl, "▲", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = supColorInput, style = label.style_label_center, size = size.small)

// Creation & Overlap Logic
handle_structure(float top, float btm, float base, int start, bool isSup) =>
    bool shouldAdd = true
    if levelsArray.size() > 0
        for i = levelsArray.size() - 1 to 0
            level l = levelsArray.get(i)
            if not l.isMitigated and not l.isUserHidden and l.isSupport == isSup
                bool overlaps = math.max(btm, l.btm) < math.min(top, l.top)
                if overlaps
                    if overlapModeInput == OVERLAP_HIDE_OLD
                        shouldAdd := false
                        break
                    else if overlapModeInput == OVERLAP_HIDE_YOUNG
                        l.isUserHidden := true
                    else if overlapModeInput == OVERLAP_MERGE
                        l.top := math.max(l.top, top)
                        l.btm := math.min(l.btm, btm)
                        shouldAdd := false
                        break
    if shouldAdd
        level newL = level.new(top, btm, base, start, time[bar_index - start], 0, 0, isSup, false, false, 0, 0, 0, 0.0, na, na, na, na, na)
        levelsArray.unshift(newL)
        true
    else
        false

if not na(ph)
    if handle_structure(ph + currentAtr * securityMultInput, ph - currentAtr * atrMultInput, ph, phBar, false)
        totalResCount += 1
if not na(pl)
    if handle_structure(pl + currentAtr * atrMultInput, pl - currentAtr * securityMultInput, pl, plBar, true)
        totalSupCount += 1

// Mitigation Loop
if levelsArray.size() > 100
    levelsArray.pop()

int activeSupCount = 0
int activeResCount = 0
int activeTotal = 0

if levelsArray.size() > 0
    for i = 0 to levelsArray.size() - 1
        level l = levelsArray.get(i)
        if not l.isMitigated
            if l.isSupport
                if close < l.btm
                    l.isMitigated := true
                    l.mitigationBar := bar_index
                    l.mitigationTime := time
                    supMitigated += 1
                    supDuration += (l.mitigationBar - l.startBar)
                    supCumVolume += l.tradedVolume
                    if breakHighlight
                        label.new(time, low, "✖", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = supColorInput, style = label.style_label_center, size = size.tiny)
            else
                if close > l.top
                    l.isMitigated := true
                    l.mitigationBar := bar_index
                    l.mitigationTime := time
                    resMitigated += 1
                    resDuration += (l.mitigationBar - l.startBar)
                    resCumVolume += l.tradedVolume
                    if breakHighlight
                        label.new(time, high, "✖", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = resColorInput, style = label.style_label_center, size = size.tiny)
            
            if not l.isMitigated
                if high >= l.btm and low <= l.top
                    l.tradedVolume += volume
                if l.isSupport
                    if low <= l.top and close >= l.btm
                        l.entries += 1
                    if low < l.btm and math.min(close, open) > l.btm
                        l.sweeps += 1
                        supSweepsCount += 1
                        if sweepHighlight
                            label.new(time, low, "●", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = supColorInput, style = label.style_label_center, size = size.small)
                else
                    if high >= l.btm and close <= l.top
                        l.entries += 1
                    if high > l.top and math.max(close, open) < l.top
                        l.sweeps += 1
                        resSweepsCount += 1
                        if sweepHighlight
                            label.new(time, high, "●", xloc = xloc.bar_time, color = NONE_COLOR, textcolor = resColorInput, style = label.style_label_center, size = size.small)

        int curD = l.isMitigated ? l.mitigationBar - l.startBar : bar_index - l.startBar
        bool meets = l.entries >= minEntriesInput and l.strength >= minStrengthInput and l.sweeps >= minSweepsInput and l.tradedVolume >= minVolumeInput and curD >= minDurationInput and not l.isUserHidden
        bool show = false
        if meets
            if not l.isMitigated and activeTotal < maxLevelsInput
                show := true
                activeTotal += 1
                if l.isSupport
                    activeSupCount += 1
                else
                    activeResCount += 1
            else if l.isMitigated and showBrokenSRInput
                show := true

        if show
            int endT = l.isMitigated ? l.mitigationTime : time
            color c = l.isSupport ? supColorInput : resColorInput
            float avgY = (l.top + l.btm) / 2
            
            // Primary Line/Box using xloc.bar_time
            if na(l.lineId)
                l.lineId := line.new(l.startTime, l.basePrice, endT, l.basePrice, xloc = xloc.bar_time, color = c)
            else
                l.lineId.set_xy1(l.startTime, l.basePrice)
                l.lineId.set_xy2(endT, l.basePrice)
            
            if displayTypeInput == 'Zones'
                if na(l.boxId)
                    l.boxId := box.new(l.startTime, l.top, endT, l.btm, xloc = xloc.bar_time, border_color = NONE_COLOR, bgcolor = color.new(c, 85))
                else
                    l.boxId.set_left(l.startTime)
                    l.boxId.set_top(l.top)
                    l.boxId.set_right(endT)
                    l.boxId.set_bottom(l.btm)
            else
                if not na(l.boxId)
                    l.boxId.delete()
                    l.boxId := na

            // Extension objects using xloc.bar_index
            if not l.isMitigated and extendUnmitigated
                int endExt = bar_index + 25
                if na(l.extLineId)
                    l.extLineId := line.new(bar_index, l.basePrice, endExt, l.basePrice, xloc = xloc.bar_index, color = c)
                else
                    l.extLineId.set_xy1(bar_index, l.basePrice)
                    l.extLineId.set_xy2(endExt, l.basePrice)
                
                if displayTypeInput == 'Zones'
                    if na(l.extBoxId)
                        l.extBoxId := box.new(bar_index, l.top, endExt, l.btm, xloc = xloc.bar_index, border_color = NONE_COLOR, bgcolor = color.new(c, 85))
                    else
                        l.extBoxId.set_left(bar_index)
                        l.extBoxId.set_top(l.top)
                        l.extBoxId.set_right(endExt)
                        l.extBoxId.set_bottom(l.btm)
                else
                    if not na(l.extBoxId)
                        l.extBoxId.delete()
                        l.extBoxId := na
                
                // Stats Label
                string txt = str.format("E:{0} | S:{1} | SW:{2} | V:{3} | D:{4}", l.entries, l.strength, l.sweeps, format_val(l.tradedVolume), curD)
                if na(l.statsLabel)
                    l.statsLabel := label.new(endExt, avgY, txt, xloc = xloc.bar_index, color = NONE_COLOR, textcolor = c, style = label.style_label_left, size = size.tiny)
                else
                    l.statsLabel.set_xy(endExt, avgY)
                    l.statsLabel.set_text(txt)
            else
                if not na(l.extLineId)
                    l.extLineId.delete()
                    l.extLineId := na
                if not na(l.extBoxId)
                    l.extBoxId.delete()
                    l.extBoxId := na
                if not na(l.statsLabel)
                    l.statsLabel.delete()
                    l.statsLabel := na
        else
            if not na(l.lineId)
                l.lineId.delete()
                l.lineId := na
            if not na(l.boxId)
                l.boxId.delete()
                l.boxId := na
            if not na(l.extLineId)
                l.extLineId.delete()
                l.extLineId := na
            if not na(l.extBoxId)
                l.extBoxId.delete()
                l.extBoxId := na
            if not na(l.statsLabel)
                l.statsLabel.delete()
                l.statsLabel := na

// Dashboard
if dashboardInput and barstate.islast
    var table t = table.new(parsedDashboardPosition, 4, 7, BACKGROUND, BORDERS, 1, BORDERS, 1)
    t.merge_cells(0, 0, 3, 0)
    cell(t, 0, 0, 'Support & Resistance Pro Statistics', DATA, text.align_center)
    cell(t, 1, 1, 'Support', HEADERS, text.align_center)
    cell(t, 2, 1, 'Resistance', HEADERS, text.align_center)
    cell(t, 3, 1, 'Total', HEADERS, text.align_center)
    
    cell(t, 0, 2, 'Active / Total', HEADERS, text.align_left)
    cell(t, 1, 2, str.format("{0} / {1}", activeSupCount, totalSupCount), DATA)
    cell(t, 2, 2, str.format("{0} / {1}", activeResCount, totalResCount), DATA)
    cell(t, 3, 2, str.format("{0} / {1}", activeTotal, totalSupCount + totalResCount), DATA)
    
    cell(t, 0, 3, 'Mitigated %', HEADERS, text.align_left)
    cell(t, 1, 3, str.format("{0,number,#.#}%", supMitigated * 100 / math.max(1, totalSupCount)), DATA)
    cell(t, 2, 3, str.format("{0,number,#.#}%", resMitigated * 100 / math.max(1, totalResCount)), DATA)
    cell(t, 3, 3, str.format("{0,number,#.#}%", (supMitigated + resMitigated) * 100 / math.max(1, totalSupCount + totalResCount)), DATA)
    
    cell(t, 0, 4, 'Avg Duration', HEADERS, text.align_left)
    cell(t, 1, 4, str.format("{0,number,#}b", supDuration / math.max(1, supMitigated)), DATA)
    cell(t, 2, 4, str.format("{0,number,#}b", resDuration / math.max(1, resMitigated)), DATA)
    cell(t, 3, 4, str.format("{0,number,#}b", (supDuration + resDuration) / math.max(1, supMitigated + resMitigated)), DATA)

    cell(t, 0, 5, 'Avg Volume', HEADERS, text.align_left)
    cell(t, 1, 5, format_val(supCumVolume / math.max(1, supMitigated)), DATA)
    cell(t, 2, 5, format_val(resCumVolume / math.max(1, resMitigated)), DATA)
    cell(t, 3, 5, format_val((supCumVolume + resCumVolume) / math.max(1, supMitigated + resMitigated)), DATA)
    
    cell(t, 0, 6, 'Total Sweeps', HEADERS, text.align_left)
    cell(t, 1, 6, str.tostring(supSweepsCount), DATA)
    cell(t, 2, 6, str.tostring(resSweepsCount), DATA)
    cell(t, 3, 6, str.tostring(supSweepsCount + resSweepsCount), DATA)
//---------------------------------------------------------------------------------------------------------------------}
