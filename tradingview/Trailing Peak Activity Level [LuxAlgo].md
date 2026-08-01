// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Trailing Peak Activity Level [LuxAlgo]", "LuxAlgo - TPAL", overlay = true, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
// Groups
string SETTINGS_GROUP   = 'Settings'
string STYLING_GROUP    = 'Styling'
string DASHBOARD_GROUP  = 'Dashboard'

// Core Settings
float multInput         = input.float(0.0, "Sensitivity", minval = 0, step = 0.1, tooltip = "ATR multiplier used to determine when a new peak activity level can be established.", group = SETTINGS_GROUP)
int atrLenInput         = input.int(200, "ATR Length", minval = 1, group = SETTINGS_GROUP)

// Styling
int levelWidthInput     = input.int(2, "Level Width", minval = 1, group = STYLING_GROUP)
bool showFillInput      = input.bool(true, "Show Area Fill", tooltip = "Display a subtle background fill between the price and the activity level.", group = STYLING_GROUP)
color upColorInput      = input.color(#089981, "Up / Bullish", inline = "Colors", group = STYLING_GROUP)
color downColorInput    = input.color(#f23645, "Down / Bearish", inline = "Colors", group = STYLING_GROUP)

// Dashboard
bool dashboardInput     = input.bool(true, "Dashboard", group = DASHBOARD_GROUP)
string dashboardPosInput= input.string('Top Right', 'Position', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = DASHBOARD_GROUP)
string dashboardSizeInput= input.string('Small', 'Size', options = ['Tiny', 'Small', 'Normal', 'Large', 'Huge'], group = DASHBOARD_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
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
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
var float maxVol = 0.
var float lvl    = na

float atr = ta.atr(atrLenInput) * multInput
bool isNewDay = session.isfirstbar

if isNewDay
    lvl := close
    maxVol := volume
else
    maxVol := math.max(volume, maxVol)

    if math.abs(close - lvl) > atr
        lvl := maxVol == volume ? close : lvl

var int lvlDir = 1
if lvl != lvl[1] and not na(lvl[1])
    lvlDir := lvl > lvl[1] ? 1 : -1

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
color lvlColor = lvlDir == 1 ? upColorInput : downColorInput

// Activity Level Plot
p1 = plot(lvl, "Peak Activity Level", color = lvl != lvl[1] ? na : lvlColor, linewidth = levelWidthInput, style = plot.style_linebr)

// Price Plot for filling
p2 = plot(close, "Price Reference", color = na, display = display.none)

// Background Fill
color fillColor = close > lvl ? color.new(upColorInput, 90) : color.new(downColorInput, 90)
fill(p1, p2, fillColor, "Area Fill", display = showFillInput ? display.all : display.none)

// Change Connection Lines
if isNewDay
    line.new(bar_index, lvl[1], bar_index, lvl, color = lvl > lvl[1] ? upColorInput : downColorInput, style = line.style_dotted, width = levelWidthInput)

// Session Separator
if isNewDay
    line.new(bar_index, low, bar_index, high, color = color.new(chart.fg_color, 80), style = line.style_dashed, extend = extend.both)

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPosInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

var table t_able = table.new(parsedDashboardPosition, 2, 5, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)

if dashboardInput and barstate.islast
    t_able.merge_cells(0, 0, 1, 0)
    cell(t_able, 0, 0, "TPAL Analysis", color = DATA, align = text.align_center)
    
    divider(t_able, 1, 1)
    
    cell(t_able, 0, 2, "Peak Level", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 2, str.tostring(lvl, format.mintick), color = lvlColor)
    
    divider(t_able, 3, 1)
    
    cell(t_able, 0, 4, "Max Volume", color = HEADERS, align = text.align_left)
    cell(t_able, 1, 4, str.tostring(maxVol, format.volume), color = DATA)

//---------------------------------------------------------------------------------------------------------------------}