// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/

// © LuxAlgo
//@version=6
indicator("Midnight Open Retracement [LuxAlgo]", shorttitle="LuxAlgo - Midnight Open Retracement", overlay=true, max_lines_count=500, max_labels_count=500, max_boxes_count=500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR  = #089981
color BEAR_COLOR  = #f23645
color CYAN        = #5b9cf6
color NEUTRAL     = #808080

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

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string sessionGroup     = "Session Settings"
string tzMode           = input.string("America/New_York", "Timezone Mode", options=["Exchange", "America/New_York"], group=sessionGroup)
string tzInput          = tzMode == "Exchange" ? syminfo.timezone : "America/New_York"
string midnightTime     = input.session("0000-0001", "Midnight Open Time", group=sessionGroup)
string nyOpenTime       = input.session("0930-0931", "NY Open Time", group=sessionGroup)
string nySession        = input.session("0930-1600", "NY Session Range", group=sessionGroup)

string visualGroup      = "Visual Settings"
bool showLevelsInput    = input.bool(true, "Show Midnight Level", group=visualGroup, inline="levels")
color midnightColorInput = input.color(CYAN, "", group=visualGroup, inline="levels")
bool showMarkersInput   = input.bool(true, "Show Retrace Circle", group=visualGroup, inline="markers")
color markerColorInput  = input.color(CYAN, "", group=visualGroup, inline="markers")
bool showSessionInput   = input.bool(true, "Show NY Session Box", group=visualGroup, inline="session")
color bullColorInput    = input.color(BULL_COLOR, "Bull", group=visualGroup, inline="session")
color bearColorInput    = input.color(BEAR_COLOR, "Bear", group=visualGroup, inline="session")

string dashGroup        = "Dashboard Settings"
bool showDashInput      = input.bool(true, "Show Insights Report", group=dashGroup)
string dashPosInput     = input.string(TOP_RIGHT, "Position", group=dashGroup, options=[TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
string dashSizeInput    = input.string(SMALL, "Size", group=dashGroup, options=[TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
var float midnightPrice = na
var float nyOpenPrice   = na
var bool  isRetraced    = false
var line  midnightLine  = na
var line  retraceLine   = na

// Detect Midnight Open
isMidnight = not na(time(timeframe.period, midnightTime, tzInput))
if isMidnight and not isMidnight[1]
    midnightPrice   := open
    nyOpenPrice     := na
    isRetraced      := false
    if showLevelsInput
        midnightLine := line.new(bar_index, midnightPrice, bar_index, midnightPrice, color=color.new(midnightColorInput, 30), width=1, style=line.style_solid)
        retraceLine  := na

// Detect NY Open
isNYOpen = not na(time(timeframe.period, nyOpenTime, tzInput))
if isNYOpen and not isNYOpen[1]
    nyOpenPrice := open

// Bias and Retracement Logic
biasBearish = nyOpenPrice > midnightPrice
biasBullish = nyOpenPrice < midnightPrice

if not na(nyOpenPrice) and not isRetraced
    if (biasBearish and low <= midnightPrice) or (biasBullish and high >= midnightPrice)
        isRetraced := true
        if showLevelsInput
            line.set_x2(midnightLine, bar_index)
            retraceLine := line.new(bar_index, midnightPrice, bar_index, midnightPrice, color=color.new(midnightColorInput, 30), width=1, style=line.style_dotted)

// Manage Line Lengths
if not na(midnightLine) and not isRetraced
    line.set_x2(midnightLine, bar_index)

if not na(retraceLine)
    line.set_x2(retraceLine, bar_index)

// Today's Probability Logic
currentWeekday = dayofweek(time, tzInput)
float probValue = na
string probStr  = "Waiting for NY Open..."

if not na(nyOpenPrice)
    if biasBearish
        probValue := switch currentWeekday
            dayofweek.monday    => 47
            dayofweek.wednesday => 89
            => 74
    else if biasBullish
        probValue := switch currentWeekday
            dayofweek.monday    => 56
            dayofweek.wednesday => 75
            => 63

    if not na(probValue)
        probStr := str.format("{0}% ({1})", probValue, probValue >= 60 ? "High" : "Avoid")

color statsColor = not na(probValue) ? (probValue >= 60 ? bullColorInput : bearColorInput) : NEUTRAL

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
// Midnight Circle Marker (Only at start)
if isMidnight and not isMidnight[1] and showMarkersInput
    label.new(bar_index, midnightPrice, "", color=markerColorInput, style=label.style_circle, size=size.tiny)
    label.new(bar_index, midnightPrice, "midnight\nopen", color=color.new(chart.bg_color, 100), textcolor=markerColorInput, style=label.style_label_up, yloc=yloc.belowbar)

// Retrace Marker
if isRetraced and isRetraced != isRetraced[1] and showMarkersInput
    label.new(bar_index, midnightPrice, "", color=markerColorInput, style=label.style_circle, size=size.small)
    label.new(bar_index, midnightPrice, "RETRACED TO\nMIDNIGHT OPEN", color=color.new(chart.bg_color, 100), textcolor=markerColorInput, style=label.style_label_down, yloc=yloc.abovebar)

// NY Session Box (Dynamic Border and Text)
var box sessionBox = na
isSession = not na(time(timeframe.period, nySession, tzInput))
if isSession and not isSession[1] and showSessionInput
    sessionBox := box.new(bar_index, high, bar_index, low, 
     border_style=line.style_dashed, 
     border_color=color.new(NEUTRAL, 30), 
     bgcolor=color.new(NEUTRAL, 96),
     text = "NY",
     text_color = color.new(NEUTRAL, 40),
     text_size = size.small,
     text_halign = text.align_left,
     text_valign = text.align_top)

if not na(sessionBox) and isSession
    color dynamicColor = close > nyOpenPrice ? bullColorInput : bearColorInput
    box.set_border_color(sessionBox, color.new(dynamicColor, 30))
    box.set_bgcolor(sessionBox, color.new(dynamicColor, 96))
    box.set_text_color(sessionBox, color.new(dynamicColor, 40))
    box.set_right(sessionBox, bar_index)
    box.set_top(sessionBox, math.max(box.get_top(sessionBox), high))
    box.set_bottom(sessionBox, math.min(box.get_bottom(sessionBox), low))

// Dashboard
var parsedDashboardPosition = switch dashPosInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize = switch dashSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background)

if showDashInput and barstate.islast
    var table t_able = table.new(parsedDashboardPosition, 3, 11, bgcolor=BACKGROUND, border_width=1, border_color=BORDERS, frame_color=BORDERS, frame_width=1)
    
    t_able.merge_cells(0, 0, 2, 0)
    cell(t_able, 0, 0, "ICT OPENING RETRACEMENT REPORT", color=DATA, align=text.align_center)
    
    t_able.merge_cells(0, 1, 2, 1)
    cell(t_able, 0, 1, "insights | NQ ICT opening retracement", color=HEADERS, align=text.align_left)
    
    cell(t_able, 0, 2, "category", color=HEADERS, align=text.align_left)
    cell(t_able, 1, 2, "frequency", color=HEADERS, align=text.align_center)
    cell(t_able, 2, 2, "percentage", color=HEADERS, align=text.align_center)

    cell(t_able, 0, 3, "session opened above 00:00 open", color=DATA, align=text.align_left)
    cell(t_able, 1, 3, "74", color=DATA, align=text.align_center)
    cell(t_able, 2, 3, "57%", color=DATA, align=text.align_center)

    cell(t_able, 0, 4, "opened above retraced to 00:00 open", color=midnightColorInput, align=text.align_left)
    cell(t_able, 1, 4, "55", color=midnightColorInput, align=text.align_center)
    cell(t_able, 2, 4, "74%", color=midnightColorInput, align=text.align_center)

    cell(t_able, 0, 5, "opened above did not retrace...", color=DATA, align=text.align_left)
    cell(t_able, 1, 5, "19", color=DATA, align=text.align_center)
    cell(t_able, 2, 5, "26%", color=DATA, align=text.align_center)

    t_able.merge_cells(0, 6, 2, 6)
    cell(t_able, 0, 6, "────────────────────────", color=BORDERS, align=text.align_center)

    cell(t_able, 0, 7, "session opened below 00:00 open", color=DATA, align=text.align_left)
    cell(t_able, 1, 7, "54", color=DATA, align=text.align_center)
    cell(t_able, 2, 7, "43%", color=DATA, align=text.align_center)

    cell(t_able, 0, 8, "opened below retraced to 00:00 open", color=midnightColorInput, align=text.align_left)
    cell(t_able, 1, 8, "34", color=midnightColorInput, align=text.align_center)
    cell(t_able, 2, 8, "63%", color=midnightColorInput, align=text.align_center)

    cell(t_able, 0, 9, "opened below did not retrace...", color=DATA, align=text.align_left)
    cell(t_able, 1, 9, "20", color=DATA, align=text.align_center)
    cell(t_able, 2, 9, "37%", color=DATA, align=text.align_center)

    t_able.merge_cells(0, 10, 2, 10)
    cell(t_able, 0, 10, "PROBABILITY OF RETRACEMENT: " + probStr, color=statsColor, align=text.align_center)

//---------------------------------------------------------------------------------------------------------------------}
