// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Session Streaks [LuxAlgo]','LuxAlgo - Session Streaks', overlay = true, max_lines_count = 500, max_labels_count = 500, behind_chart = false)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645

BULLISH                 = 'Bullish'
BEARISH                 = 'Bearish'

HORIZONTAL              = 'Horizontal'
VERTICAL                = 'Vertical'

TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

DASHBOARD_GROUP         = 'Dashboard'
STYLE_GROUP             = 'Style'

dashboardTooltip        = 'Enable or disable the dashboard.'
dashboardPositionTooltip= 'Select the dashboard location.'
dashboardSizeTooltip    = 'Select the dashboard size.'

dashboardInput          = input.bool(   false,      'Dashboard',        group=DASHBOARD_GROUP, tooltip = dashboardTooltip)
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',         group=DASHBOARD_GROUP, tooltip = dashboardPositionTooltip , options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput      = input.string( NORMAL,     'Size',             group=DASHBOARD_GROUP, tooltip = dashboardSizeTooltip,      options = [TINY,SMALL,NORMAL,LARGE,HUGE])

bullishColorInput       = input.color(  GREEN,      'Bullish',          group = STYLE_GROUP)
bearishColorInput       = input.color(  RED,        'Bearish',          group = STYLE_GROUP)
transparencyInput       = input.int(    80,         'Transparency',     group = STYLE_GROUP)
gradientTypeInput       = input.string( HORIZONTAL, 'Gradient',         group = STYLE_GROUP, options = [HORIZONTAL,VERTICAL])

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type session
    int startTime
    int endTime            
    float openPrice
    float closePrice
    float top
    float bottom
    float labelTop
    float labelBottom
    int timeClose   = na
    label tag       = na
    line topLine    = na
    line bottomLine = na
    
type streak
    string bias
    int number

var array<session> sessions     = array.new<session>()
var array<int> bullishStreaks   = array.new<int>()
var array<int> bearishStreaks   = array.new<int>()
var currentStreak               = streak.new('',0)
bool sessionStart               = session.isfirstbar_regular
bool largerThanDailyTimeframe   = timeframe.in_seconds() > 86400      

var parsedDashboardPosition     = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize         = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

var table t_able                = table.new(parsedDashboardPosition,3,12
     , bgcolor      = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color  = #373a46
     , frame_width  = 1)

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
gatherStatistics() =>
    var bool wasLastBullish     = true

    if sessions.size() > 0        
        session currentSession  = sessions.last()
        bool bullishSession     = currentSession.closePrice >= currentSession.openPrice

        if bullishSession
            if bullishStreaks.size() != 0 and wasLastBullish
                bullishStreaks.set(-1,bullishStreaks.get(-1) + 1)
            else
                bullishStreaks.push(1)
        else
            if bearishStreaks.size() != 0 and not wasLastBullish
                bearishStreaks.set(-1,bearishStreaks.get(-1) + 1)
            else
                bearishStreaks.push(1)

        wasLastBullish := bullishSession

gatherData() =>
    if sessionStart
        gatherStatistics()

        if sessions.size() > 500
            sessions.shift()

        sessions.push(session.new(time,time,open,close,high,low))        
                        
    if sessions.size() > 0
        session currentSession      = sessions.last()
        currentSession.endTime      := time
        currentSession.closePrice   := close
        currentSession.top          := math.max(currentSession.top,high)
        currentSession.bottom       := math.min(currentSession.bottom,low)
        currentSession.labelTop     := currentSession.top
        currentSession.labelBottom  := currentSession.bottom

getHTFSession() => session.new(time,time,open,close,high,low,time_close)

gatherDataHTF() =>    
    gatherStatistics()

    if sessions.size() > 500
        sessions.shift()

    session lastSession     = request.security('','D',getHTFSession())
    lastSession.startTime   := time
    lastSession.endTime     := time
    lastSession.labelTop    := high
    lastSession.labelBottom := low
    sessions.push(lastSession)

cell(table t_able, int column, int row, string data, color = color.white, align = text.align_right) => t_able.cell(column,row,data,text_color = color, text_size = parsedDashboardSize, text_halign = align)
cellBG(table t_able, int column, int row, string data, color background, color = color.white, align = text.align_right) => t_able.cell(column,row,data,text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background)

updateDashboard() =>
    color currentColor  = sessions.size() > 0 ? (sessions.last().closePrice >= sessions.last().openPrice ? bullishColorInput : bearishColorInput) : color(na)
    string currentTag   = sessions.size() > 0 ? sessions.last().tag.get_text() : ''
    cellBG(t_able,1,0,currentTag,color.new(currentColor,transparencyInput),currentColor,align = text.align_center)

drawDashboard() =>    
    t_able.merge_cells(1,0,2,0)
    cell(t_able,0,0,'Current',  align = text.align_center)    

    t_able.merge_cells(0,1,2,1)
    cell(t_able,0,1,'Streaks',  align = text.align_center)
    cell(t_able,1,2,'Bullish',  align = text.align_center)
    cell(t_able,2,2,'Bearish',  align = text.align_center)
    cell(t_able,0,3,'Number',   align = text.align_left)
    cell(t_able,0,4,'Median',   align = text.align_left)
    cell(t_able,0,5,'Mode',     align = text.align_left)        

    updateDashboard()

    array<int> parsedBullishStreaks = array.new<int>()
    for eachStreak in bullishStreaks
        if eachStreak > 1
            parsedBullishStreaks.push(eachStreak)

    array<int> parsedBearishStreaks = array.new<int>()
    for eachStreak in bearishStreaks
        if eachStreak > 1
            parsedBearishStreaks.push(eachStreak)

    cell(t_able,1,3,str.format('{0, number, 0}',parsedBullishStreaks.size()))
    cell(t_able,2,3,str.format('{0, number, 0}',parsedBearishStreaks.size()))
    cell(t_able,1,4,str.format('{0, number, 0.00}',parsedBullishStreaks.median()))
    cell(t_able,2,4,str.format('{0, number, 0.00}',parsedBearishStreaks.median()))
    cell(t_able,1,5,str.format('{0, number, 0.00}',parsedBullishStreaks.mode()))
    cell(t_able,2,5,str.format('{0, number, 0.00}',parsedBearishStreaks.mode()))

drawSession(session currentSession) =>    
    bool bullishArea = currentSession.closePrice >= currentSession.openPrice

    if bullishArea
        if currentStreak.bias == BULLISH
            currentStreak.number    += 1
        else
            currentStreak.bias      := BULLISH
            currentStreak.number    := 1
    else
        if currentStreak.bias == BEARISH
            currentStreak.number    += 1
        else
            currentStreak.bias      := BEARISH
            currentStreak.number    := 1

    string currentTag   = currentStreak.bias +' ('+ str.tostring(currentStreak.number) +')'
    color currentColor  = bullishArea ? bullishColorInput : bearishColorInput

    currentSession.tag.delete()
    currentSession.topLine.delete()
    currentSession.bottomLine.delete()
    currentSession.tag          := label.new(chart.point.new(currentSession.startTime + math.round(0.5*(currentSession.endTime - currentSession.startTime)),na,bullishArea ? currentSession.labelBottom : currentSession.labelTop),currentTag,xloc.bar_time,yloc.price,color(na),bullishArea ? label.style_label_up : label.style_label_down, currentColor, size.normal)
    currentSession.topLine      := line.new(chart.point.new(currentSession.startTime,na,currentSession.top),chart.point.new(currentSession.endTime,na,currentSession.top),xloc.bar_time, color = color.new(currentColor,50))
    currentSession.bottomLine   := line.new(chart.point.new(currentSession.startTime,na,currentSession.bottom),chart.point.new(currentSession.endTime,na,currentSession.bottom),xloc.bar_time, color = color.new(currentColor,50))                           
    
drawSessions() =>    
    for eachSession in sessions
        drawSession(eachSession)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
if timeframe.isintraday
    gatherData()
else
    gatherDataHTF()

if barstate.islastconfirmedhistory
    drawSessions()

    if dashboardInput
        drawDashboard()   
        
if barstate.islast
    if timeframe.isintraday
        currentStreak.number -= 1
        
    drawSession(sessions.last())

    if dashboardInput
        updateDashboard()

bool existingSessions   = sessions.size() > 0
float topLevel          = existingSessions ? (sessions.last().top) : na
float bottomLevel       = existingSessions ? (sessions.last().bottom) : na
color fillColor         = existingSessions ? (sessionStart ? na : (sessions.last().closePrice >= sessions.last().openPrice ? bullishColorInput : bearishColorInput)) : color(na)
float delta             = existingSessions ? close - sessions.last().openPrice : na
float smooth            = ta.sma(math.sign(delta), 10)
color smoothGradient    = color.from_gradient(smooth, -1, 1, color.new(bearishColorInput,transparencyInput),color.new(bullishColorInput,transparencyInput))

topPlot                 = plot(topLevel,    'Top',      color.new(fillColor,transparencyInput), style = plot.style_linebr)
bottomPlot              = plot(bottomLevel, 'Bottom',   color.new(fillColor,transparencyInput), style = plot.style_linebr)

fill(topPlot,bottomPlot,gradientTypeInput == VERTICAL ? smoothGradient : color(na))
fill(topPlot,bottomPlot,topLevel,bottomLevel,gradientTypeInput == HORIZONTAL ? color.new(bullishColorInput,transparencyInput) : color(na),gradientTypeInput == HORIZONTAL ? color.new(bearishColorInput,transparencyInput) : color(na))

//---------------------------------------------------------------------------------------------------------------------}