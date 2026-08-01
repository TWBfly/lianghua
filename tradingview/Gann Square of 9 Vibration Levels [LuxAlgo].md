// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Gann Square of 9 Vibration Levels [LuxAlgo]", "LuxAlgo - Gann Square of 9 Vibration Levels", overlay = true, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR            = #089981
color BEAR_COLOR            = #f23645

color DATA                  = #DBDBDB
color HEADERS               = #808080
color BACKGROUND            = #161616
color BORDERS               = #2E2E2E

string TOP_RIGHT            = 'Top Right'
string BOTTOM_RIGHT         = 'Bottom Right'
string BOTTOM_LEFT          = 'Bottom Left'

string TINY                 = 'Tiny'
string SMALL                = 'Small'
string NORMAL               = 'Normal'
string LARGE                = 'Large'
string HUGE                 = 'Huge'

string DASHBOARD_GROUP      = 'Dashboard'
string CALC_GROUP           = 'Calculation Settings'
string VISUAL_GROUP         = 'Visual Settings'

string dashboardTooltip         = 'Enable or disable the dashboard.'
string dashboardPositionTooltip = 'Select the dashboard location.'
string dashboardSizeTooltip     = 'Select the dashboard size.'
//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
// Calculation Inputs
anchorTypeInput         = input.string("Auto pivot", "Anchor Type", options = ["Auto pivot", "Manual"], group = CALC_GROUP)
manualPriceInput        = input.float(0.0, "Manual Anchor Price", minval = 0.0, group = CALC_GROUP, tooltip = "Used if Anchor Type is 'Manual'")
pivotLookbackInput      = input.int(20, "Pivot Lookback", minval = 5, group = CALC_GROUP, tooltip = "Lookback for detecting high/low pivots in 'Auto pivot' mode.")
directionInput          = input.string("Both", "Vibration Direction", options = ["Up", "Down", "Both"], group = CALC_GROUP)

// Visual Inputs
showCardinalInput       = input.bool(true, "Show Cardinal Levels (90°)", group = VISUAL_GROUP)
showOrdinalInput        = input.bool(true, "Show Ordinal Levels (45°)", group = VISUAL_GROUP)
levelLabelsInput        = input.bool(true, "Show Level Labels", group = VISUAL_GROUP)
cardinalColorInput      = input.color(color.new(#2962FF, 20), "Cardinal Level Color", group = VISUAL_GROUP)
ordinalColorInput       = input.color(color.new(#9c27b0, 40), "Ordinal Level Color", group = VISUAL_GROUP)

// Dashboard Inputs
dashboardInput          = input.bool(true, 'Dashboard', group = DASHBOARD_GROUP, tooltip = dashboardTooltip)
dashboardPositionInput  = input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, tooltip = dashboardPositionTooltip, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput      = input.string(SMALL, 'Size', group = DASHBOARD_GROUP, tooltip = dashboardSizeTooltip, options = [TINY, SMALL, NORMAL, LARGE, HUGE])
//---------------------------------------------------------------------------------------------------------------------}
// Types & Functions
//---------------------------------------------------------------------------------------------------------------------{
type Level
    float price
    float degree
    bool  isCardinal

// Calculate Gann Price based on degree displacement
// Formula: Price = (sqrt(Anchor) + (Degree / 180))^2
getGannPrice(float anchor, float degree, float direction) =>
    float res = math.pow(math.sqrt(anchor) + (degree / 180.0) * direction, 2)
    res

// Dashboard helper functions
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
    string rowDivider = '━━━━━━━━━━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)
//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
var float anchorPrice = na
var int anchorBar     = na
var bool isBullish    = true

// Determine Anchor
if anchorTypeInput == "Manual"
    if manualPriceInput > 0
        anchorPrice := manualPriceInput
        anchorBar   := bar_index
else
    float hi = ta.highest(pivotLookbackInput)
    float lo = ta.lowest(pivotLookbackInput)
    
    // Check for new pivots
    bool isNewHigh = high[pivotLookbackInput] == ta.highest(high, pivotLookbackInput * 2 + 1)[pivotLookbackInput]
    bool isNewLow  = low[pivotLookbackInput] == ta.lowest(low, pivotLookbackInput * 2 + 1)[pivotLookbackInput]
    
    if isNewHigh
        anchorPrice := high[pivotLookbackInput]
        anchorBar   := bar_index - pivotLookbackInput
        isBullish   := false
    else if isNewLow
        anchorPrice := low[pivotLookbackInput]
        anchorBar   := bar_index - pivotLookbackInput
        isBullish   := true

// Calculate Levels
var Level[] levels = array.new<Level>()

if not na(anchorPrice) and (anchorTypeInput == "Manual" ? barstate.islast : true)
    array.clear(levels)
    
    // Angles to calculate: 45, 90, 135, 180, 225, 270, 315, 360
    float[] angles = array.from(45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0, 360.0)
    
    for angle in angles
        bool isCardinal = angle % 90.0 == 0
        
        if directionInput == "Up" or directionInput == "Both"
            array.push(levels, Level.new(getGannPrice(anchorPrice, angle, 1.0), angle, isCardinal))
        
        if directionInput == "Down" or directionInput == "Both"
            array.push(levels, Level.new(getGannPrice(anchorPrice, angle, -1.0), -angle, isCardinal))

// Render Levels
var line[] levelLines = array.new_line()
var label[] levelLabels = array.new_label()

if barstate.islast and array.size(levels) > 0
    // Cleanup previous drawings
    for l in levelLines
        line.delete(l)
    for lb in levelLabels
        label.delete(lb)
    array.clear(levelLines)
    array.clear(levelLabels)
    
    for lvl in levels
        bool show = (lvl.isCardinal and showCardinalInput) or (not lvl.isCardinal and showOrdinalInput)
        if show
            color lvlColor = lvl.isCardinal ? cardinalColorInput : ordinalColorInput
            line ln = line.new(anchorBar, lvl.price, bar_index + 10, lvl.price, 
                 color = lvlColor, 
                 style = lvl.isCardinal ? line.style_solid : line.style_dashed,
                 width = lvl.isCardinal ? 2 : 1)
            array.push(levelLines, ln)
            
            if levelLabelsInput
                label lb = label.new(bar_index + 10, lvl.price, str.format("{0}°\n{1}", lvl.degree, str.tostring(lvl.price, format.mintick)), 
                     color = #00000000, 
                     style = label.style_label_left, 
                     textcolor = lvlColor, 
                     size = size.small)
                array.push(levelLabels, lb)

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var table t_able = table.new(parsedDashboardPosition, 3, 20, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1, force_overlay = true)

if dashboardInput and barstate.islast and not na(anchorPrice)
    t_able.merge_cells(0, 0, 2, 0)
    cell(t_able, 0, 0, "Vibration Levels", color = DATA, align = text.align_center)
    
    divider(t_able, 1, 2)
    
    cell(t_able, 0, 2, "Anchor", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 2, str.tostring(anchorPrice, format.mintick), color = DATA)
    cell(t_able, 2, 2, anchorTypeInput == "Manual" ? "Manual" : (isBullish ? "Low" : "High"), color = isBullish ? BULL_COLOR : BEAR_COLOR)
    
    divider(t_able, 3, 2)
    
    cell(t_able, 0, 4, "Degree", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 4, "Price", color = HEADERS, align = text.align_center)
    cell(t_able, 2, 4, "Type", color = HEADERS, align = text.align_right)
    
    int rowOffset = 5
    for i = 0 to array.size(levels) - 1
        Level lvl = array.get(levels, i)
        bool show = (lvl.isCardinal and showCardinalInput) or (not lvl.isCardinal and showOrdinalInput)
        
        if show and rowOffset < 20
            cell(t_able, 0, rowOffset, str.format("{0}°", lvl.degree), color = DATA, align = text.align_left)
            cell(t_able, 1, rowOffset, str.tostring(lvl.price, format.mintick), color = DATA, align = text.align_center)
            cell(t_able, 2, rowOffset, lvl.isCardinal ? "Cardinal" : "Ordinal", color = lvl.isCardinal ? cardinalColorInput : ordinalColorInput, align = text.align_right)
            rowOffset += 1

//---------------------------------------------------------------------------------------------------------------------}
