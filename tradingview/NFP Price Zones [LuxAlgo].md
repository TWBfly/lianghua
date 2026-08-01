// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("NFP Price Zones [LuxAlgo]", "LuxAlgo - NFP Zones", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color GREEN             = #089981
color RED               = #f23645
color GRAY              = #808080

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

string CALC_GROUP       = "Calculations"
string VIS_GROUP        = "Visuals"
string DASHBOARD_GROUP  = 'Dashboard'

//---------------------------------------------------------------------------------------------------------------------}
// Helper Functions
//---------------------------------------------------------------------------------------------------------------------{
// Function to find the timestamp of the first Friday of a given month at a specific release time
getFirstFridayTime(int year, int month, int hour, int minute) =>
    int firstFridayDay = 0
    for d = 1 to 7
        if dayofweek(timestamp("America/New_York", year, month, d, hour, minute)) == dayofweek.friday
            firstFridayDay := d
            break
    timestamp("America/New_York", year, month, firstFridayDay, hour, minute)

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
int lookbackInput       = input.int(12, "Historical NFPs to Analyze", minval = 1, group = CALC_GROUP, tooltip = "Number of past NFP events to include in the statistical average.")
int releaseHourInput    = input.int(8, "NFP Release Hour (24h)", minval = 0, maxval = 23, group = CALC_GROUP)
int releaseMinInput     = input.int(30, "NFP Release Minute", minval = 0, maxval = 59, group = CALC_GROUP)

bool showBoxesInput     = input.bool(true, "Show Historical Zones", group = VIS_GROUP)
color zoneColorInput    = input.color(color.new(GRAY, 85), "Zone Color", group = VIS_GROUP)

bool dashboardInput     = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP)
string dashboardPosInput= input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
string dashboardSizeInput= input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Logic & Calculations
//---------------------------------------------------------------------------------------------------------------------{
// Window Calculations: 30 mins before release to 60 mins after release
releaseTotalMinutes = releaseHourInput * 60 + releaseMinInput
windowStartTotal    = releaseTotalMinutes - 30
windowEndTotal      = releaseTotalMinutes + 60

formatTime(int totalMinutes) =>
    int h = math.floor(totalMinutes / 60)
    int m = totalMinutes % 60
    str.format("{0,number,00}{1,number,00}", h, m)

windowSession = formatTime(windowStartTotal) + "-" + formatTime(windowEndTotal)

// NFP detection
isFirstFriday = dayofweek == dayofweek.friday and dayofmonth <= 7
nfpTimeSession = time(timeframe.period, windowSession, "America/New_York")
isInWindow = not na(nfpTimeSession) and isFirstFriday and timeframe.isintraday

var float windowHigh = na
var float windowLow  = na
var float windowOpen = na
var int windowStartBar = na

var float[] historicalRanges = array.new_float()
var float[] historicalExpUps = array.new_float()
var float[] historicalExpDns = array.new_float()

bool isStart = isInWindow and not isInWindow[1]
bool isEnd   = not isInWindow and isInWindow[1]

if isStart
    windowHigh     := high
    windowLow      := low
    windowOpen     := open
    windowStartBar := bar_index
else if isInWindow
    windowHigh := math.max(windowHigh, high)
    windowLow  := math.min(windowLow, low)

if isEnd
    float rangeVal = windowHigh - windowLow
    float expUp    = windowHigh - windowOpen
    float expDn    = windowOpen - windowLow
    
    array.push(historicalRanges, rangeVal)
    array.push(historicalExpUps, expUp)
    array.push(historicalExpDns, expDn)
    
    if array.size(historicalRanges) > lookbackInput
        array.remove(historicalRanges, 0)
        array.remove(historicalExpUps, 0)
        array.remove(historicalExpDns, 0)
    
    if showBoxesInput
        box.new(windowStartBar, windowHigh, bar_index, windowLow, 
             bgcolor = zoneColorInput, 
             border_color = color.new(chart.fg_color, 70),
             border_style = line.style_dotted)
        
        label.new(math.round(math.avg(windowStartBar, bar_index)), windowHigh, 
             text = "NFP\n" + str.format("{0,date,short}", time), 
             color = #00000000, 
             textcolor = chart.fg_color, 
             style = label.style_label_down, 
             size = size.tiny)

bgcolor(isInWindow ? color.new(GRAY, 90) : na)

// Stats Processing
float avgRange = array.size(historicalRanges) > 0 ? array.avg(historicalRanges) : na
float maxRange = array.size(historicalRanges) > 0 ? array.max(historicalRanges) : na
float avgExpUp = array.size(historicalExpUps) > 0 ? array.avg(historicalExpUps) : na
float avgExpDn = array.size(historicalExpDns) > 0 ? array.avg(historicalExpDns) : na

// Next NFP Calculation
int referenceTime = last_bar_time
int currYear      = year(referenceTime, "America/New_York")
int currMonth     = month(referenceTime, "America/New_York")
int nextNFP_T     = getFirstFridayTime(currYear, currMonth, releaseHourInput, releaseMinInput)

// Shift logic: Only shift after the window has fully concluded (release + 60 mins)
if referenceTime >= nextNFP_T + 3600000 
    int nextMonth = currMonth == 12 ? 1 : currMonth + 1
    int nextYear  = currMonth == 12 ? currYear + 1 : currYear
    nextNFP_T := getFirstFridayTime(nextYear, nextMonth, releaseHourInput, releaseMinInput)

//---------------------------------------------------------------------------------------------------------------------}
// Frozen Anchor Logic
//---------------------------------------------------------------------------------------------------------------------{
var float frozenAnchor = na

// Freeze precisely at the start bar's open, and keep it until the window is closed
if isStart
    frozenAnchor := open
else if not isInWindow
    frozenAnchor := close

//---------------------------------------------------------------------------------------------------------------------}
// Visual Future Projection
//---------------------------------------------------------------------------------------------------------------------{
// Use extend.right to ensure zones expand to the right of the chart
var line projHigh = line.new(na, na, na, na, xloc = xloc.bar_time, color = GREEN, style = line.style_solid, width = 2, extend = extend.right)
var line projLow  = line.new(na, na, na, na, xloc = xloc.bar_time, color = RED, style = line.style_solid, width = 2, extend = extend.right)
var line projMid  = line.new(na, na, na, na, xloc = xloc.bar_time, color = color.new(chart.fg_color, 80), style = line.style_dashed)
var label lblHigh = label.new(na, na, "", xloc = xloc.bar_time, color = #00000000, textcolor = GREEN, style = label.style_label_down, size = size.small)
var label lblLow  = label.new(na, na, "", xloc = xloc.bar_time, color = #00000000, textcolor = RED, style = label.style_label_up, size = size.small)

if barstate.islast and not na(avgRange)
    float anchorPrice = frozenAnchor
    
    // Position lines at the future NFP time, extending right
    projHigh.set_xy1(nextNFP_T, anchorPrice + avgExpUp)
    projHigh.set_xy2(nextNFP_T + 3600000, anchorPrice + avgExpUp) // Second point just for direction
    
    projLow.set_xy1(nextNFP_T, anchorPrice - avgExpDn)
    projLow.set_xy2(nextNFP_T + 3600000, anchorPrice - avgExpDn)
    
    projMid.set_xy1(nextNFP_T, anchorPrice + avgExpUp)
    projMid.set_xy2(nextNFP_T, anchorPrice - avgExpDn)
    
    // Labels follow the line start
    lblHigh.set_xy(nextNFP_T, anchorPrice + avgExpUp)
    lblHigh.set_text("Avg High Expansion")
    
    lblLow.set_xy(nextNFP_T, anchorPrice - avgExpDn)
    lblLow.set_text("Avg Low Expansion")

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPosInput
    TOP_RIGHT    => position.top_right
    BOTTOM_RIGHT => position.bottom_right
    BOTTOM_LEFT  => position.bottom_left

var parsedDashboardSize = switch dashboardSizeInput
    TINY   => size.tiny
    SMALL  => size.small
    NORMAL => size.normal
    LARGE  => size.large
    HUGE   => size.huge

cell(table t, int col, int row, string txt, color c = #DBDBDB, align = text.align_right) => 
    t.cell(col, row, txt, text_color = c, text_size = parsedDashboardSize, text_halign = align, bgcolor = na)

divider(table t, int row, int lastCol) =>    
    t.merge_cells(0, row, lastCol, row)
    t.cell(0, row, '━━━━━━━━━━━━━━━━━━', text_color = BORDERS, text_size = parsedDashboardSize, text_halign = text.align_center, height = 0.5)

var table dash = table.new(parsedDashboardPosition, 2, 14, bgcolor = BACKGROUND, frame_color = BORDERS, frame_width = 1)

if dashboardInput and barstate.islast
    dash.clear(0, 0, 1, 13)
    dash.merge_cells(0, 0, 1, 0)
    cell(dash, 0, 0, "NFP Statistics (" + str.tostring(array.size(historicalRanges)) + ")", align = text.align_center)
    
    divider(dash, 1, 1)
    
    cell(dash, 0, 2, "Avg Range:", HEADERS, text.align_left)
    cell(dash, 1, 2, str.tostring(avgRange, format.mintick))
    
    cell(dash, 0, 3, "Max Range:", HEADERS, text.align_left)
    cell(dash, 1, 3, str.tostring(maxRange, format.mintick))
    
    divider(dash, 4, 1)
    
    cell(dash, 0, 5, "Avg Up Exp:", GREEN, text.align_left)
    cell(dash, 1, 5, str.tostring(avgExpUp, format.mintick))
    
    cell(dash, 0, 6, "Avg Dn Exp:", RED, text.align_left)
    cell(dash, 1, 6, str.tostring(avgExpDn, format.mintick))
    
    divider(dash, 7, 1)
    
    cell(dash, 0, 8, "Next NFP:", HEADERS, text.align_left)
    cell(dash, 1, 8, str.format("{0,date,short}", nextNFP_T), DATA)
    
    // Countdown logic
    int diffMs = nextNFP_T - referenceTime
    string countdownText = ""
    
    if referenceTime >= nextNFP_T - 1800000 and referenceTime < nextNFP_T + 3600000
        countdownText := "EVENT LIVE"
    else
        int days = math.floor(diffMs / 86400000)
        int hours = math.floor((diffMs % 86400000) / 3600000)
        countdownText := str.tostring(days) + "d " + str.tostring(hours) + "h"

    cell(dash, 0, 9, "Countdown:", HEADERS, text.align_left)
    cell(dash, 1, 9, countdownText, countdownText == "EVENT LIVE" ? GREEN : DATA)

    divider(dash, 10, 1)

    // Price Distance Logic
    float distToHigh = (frozenAnchor + avgExpUp) - close
    float distToLow  = close - (frozenAnchor - avgExpDn)

    cell(dash, 0, 11, "To High Exp:", HEADERS, text.align_left)
    cell(dash, 1, 11, str.tostring(distToHigh / syminfo.mintick / 10, "#.0") + " pips", distToHigh > 0 ? DATA : RED)

    cell(dash, 0, 12, "To Low Exp:", HEADERS, text.align_left)
    cell(dash, 1, 12, str.tostring(distToLow / syminfo.mintick / 10, "#.0") + " pips", distToLow > 0 ? DATA : GREEN)

//---------------------------------------------------------------------------------------------------------------------}