// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Relative Performance Areas [LuxAlgo]','LuxAlgo - Relative Performance Areas', overlay = true, max_boxes_count = 500, max_polylines_count = 100, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645
GREEN_80                = color.new(GREEN,80)
RED_80                  = color.new(RED,80)

NET_RETURN              = 'Net Returns'
NORMALIZED              = 'Rescaled Returns'
STANDARDIZED            = 'Standardized Returns'

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

EM_SPACE                = ' '
EN_SPACE                = ' '
FOUR_PER_EM_SPACE       = ' '
HAIR_SPACE              = ' '

bullishSpacing          = EM_SPACE+FOUR_PER_EM_SPACE+HAIR_SPACE
bearishSpacing          = EN_SPACE+FOUR_PER_EM_SPACE+HAIR_SPACE

benchmarkTooltip        = 'Benchmark for comparison'
displayModeTooltip      = 'Choose how to display the benchmark:'+
     '\n- Net Returns: Uses the raw net returns of the benchmark.'+
     '\n- Rescaled Returns: Uses the benchmark net returns multiplied by the ratio of the benchmark and asset standard deviations.'+
     '\n- Standardized Returns: Uses the benchmark z-score multiplied by the asset standard deviation.'
dashboardTooltip        = 'Enable or disable the dashboard.'
dashboardPositionTooltip= 'Select the dashboard location.'
dashboardSizeTooltip    = 'Select the dashboard size.'
showBullishTooltip      = 'Enable or disable displaying overperforming sessions and choose a color.'
showBearishTooltip      = 'Enable or disable displaying underperforming sessions and choose a color.'
showBenchmarkTooltip    = 'Enable or disable displaying the benchmark and choose colors.'

benchmarkInput          = input.symbol( 'TVC:SPX',  'Benchmark',        tooltip = benchmarkTooltip)
displayModeInput        = input.string( STANDARDIZED,'Display Mode',     tooltip = displayModeTooltip, options = [NET_RETURN,NORMALIZED,STANDARDIZED])

dashboardInput          = input.bool(   false,      'Dashboard',        group=DASHBOARD_GROUP, tooltip = dashboardTooltip)
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',         group=DASHBOARD_GROUP, tooltip = dashboardPositionTooltip , options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput      = input.string( NORMAL,     'Size',             group=DASHBOARD_GROUP, tooltip = dashboardSizeTooltip,      options = [TINY,SMALL,NORMAL,LARGE,HUGE])

showBullishInput        = input.bool(   true,       'Overperforming',   group = STYLE_GROUP, inline = 'bullish')
bullishColorInput       = input.color(  GREEN_80,   bullishSpacing,     group = STYLE_GROUP, inline = 'bullish',    tooltip = showBullishTooltip)
showBearishInput        = input.bool(   true,       'Underperforming',  group = STYLE_GROUP, inline = 'bearish')
bearishColorInput       = input.color(  RED_80,     bearishSpacing,     group = STYLE_GROUP, inline = 'bearish',    tooltip = showBearishTooltip)

showBenchmarkInput      = input.bool(   true,       'Benchmark',        group = STYLE_GROUP, inline = 'benchmark')
benchBullColorInput     = input.color(  GREEN,      '',                 group = STYLE_GROUP, inline = 'benchmark')
benchBearColorInput     = input.color(  RED,        '',                 group = STYLE_GROUP, inline = 'benchmark',  tooltip = showBenchmarkTooltip)

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
    box area
    float benchmarkTop
    float benchmarkBottom
    box benchmarkArea
    array<int> times
    array<float> assetReturns
    array<float> benchmarkReturns
    array<chart.point> benchmarkPoints    
    polyline benchmarkLine              = na    
    float cumulativeBenchmarkReturns    = na
    line topLine                        = na
    line bottomLine                     = na
    
var array<session> sessions             = array.new<session>()         
var array<int> overperformingSessions   = array.new<int>()
var array<int> winningStreaks           = array.new<int>()
var array<int> losingStreaks            = array.new<int>()

sessionStart                            = session.isfirstbar_regular

var parsedDashboardPosition             = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize                 = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
netReturns(session currentSession) =>    
    currentSession.cumulativeBenchmarkReturns   := currentSession.benchmarkReturns.sum()    
    float currentBenchmarkPrice                 = currentSession.openPrice * (1 + currentSession.cumulativeBenchmarkReturns)
    currentSession.benchmarkTop                 := math.max(currentSession.benchmarkTop,currentBenchmarkPrice)
    currentSession.benchmarkBottom              := math.min(currentSession.benchmarkBottom,currentBenchmarkPrice)

    currentSession.benchmarkPoints.push(chart.point.new(time,na,currentBenchmarkPrice))

normalizedReturns(session currentSession) =>    
    float deviationRatio = currentSession.assetReturns.stdev()/currentSession.benchmarkReturns.stdev()    

    currentSession.benchmarkPoints.clear()
    currentSession.cumulativeBenchmarkReturns   := 0
    currentSession.benchmarkTop                 := currentSession.openPrice
    currentSession.benchmarkBottom              := currentSession.openPrice

    for [index,eachReturn] in currentSession.benchmarkReturns
        currentSession.cumulativeBenchmarkReturns   += eachReturn * deviationRatio
        float currentBenchmarkPrice                 = currentSession.openPrice * (1 + currentSession.cumulativeBenchmarkReturns)
        currentSession.benchmarkTop                 := math.max(currentSession.benchmarkTop,currentBenchmarkPrice)
        currentSession.benchmarkBottom              := math.min(currentSession.benchmarkBottom,currentBenchmarkPrice)

        currentSession.benchmarkPoints.push(chart.point.new(currentSession.times.get(index),na,index == 0 ? currentSession.openPrice : currentBenchmarkPrice))

standarizedReturns(session currentSession) =>
    float assetDeviation = currentSession.assetReturns.stdev()

    currentSession.benchmarkPoints.clear()
    currentSession.cumulativeBenchmarkReturns   := 0
    currentSession.benchmarkTop                 := currentSession.openPrice
    currentSession.benchmarkBottom              := currentSession.openPrice

    for [index,eachScore] in currentSession.benchmarkReturns.standardize()
        currentSession.cumulativeBenchmarkReturns   += eachScore * assetDeviation
        float currentBenchmarkPrice                 = currentSession.openPrice * (1 + currentSession.cumulativeBenchmarkReturns)
        currentSession.benchmarkTop                 := math.max(currentSession.benchmarkTop,currentBenchmarkPrice)
        currentSession.benchmarkBottom              := math.min(currentSession.benchmarkBottom,currentBenchmarkPrice)

        currentSession.benchmarkPoints.push(chart.point.new(currentSession.times.get(index),na,index == 0 ? currentSession.openPrice : currentBenchmarkPrice))

gatherStatistics() =>
    var bool wasLastOverperforming = true

    if sessions.size() > 0
        session currentSession  = sessions.last()
        bool overperforming     = currentSession.closePrice >= (currentSession.openPrice * (1 + currentSession.cumulativeBenchmarkReturns))    

        overperformingSessions.push(overperforming ? 1 : 0)

        if overperforming                    
            if wasLastOverperforming and winningStreaks.size() > 0
                winningStreaks.set(-1,winningStreaks.get(-1) + 1)
            else
                winningStreaks.push(1)            
        else
            if not wasLastOverperforming and losingStreaks.size() > 0
                losingStreaks.set(-1,losingStreaks.get(-1) + 1)
            else
                losingStreaks.push(1)

        wasLastOverperforming := overperforming

gatherData() =>
    if sessionStart
        gatherStatistics()

        if sessions.size() > 500
            sessions.shift()

        sessions.push(session.new(time,time,open,close,high,low,na,open,open,na,array.new<int>(),array.new<float>(),array.new<float>(),array.new<chart.point>()))        
        sessions.last().benchmarkPoints.push(chart.point.new(time,na,open))
                
    if sessions.size() > 0
        session currentSession  = sessions.last()
        currentSession.times.push(time)
        currentSession.endTime      := time
        currentSession.closePrice   := close
        currentSession.top          := math.max(currentSession.top,high)
        currentSession.bottom       := math.min(currentSession.bottom,low)

        assetReturn                 = sessionStart ? (close - open)/open : (close - close[1])/close[1]
        benchmarkReturn             = request.security(benchmarkInput,'',assetReturn)      

        currentSession.assetReturns.push(assetReturn)            
        currentSession.benchmarkReturns.push(benchmarkReturn)
        
        if not sessionStart
            switch displayModeInput
                NET_RETURN  => netReturns(currentSession)
                NORMALIZED  => normalizedReturns(currentSession)
                STANDARDIZED => standarizedReturns(currentSession)

cell(table t_able, int column, int row, string data, color = color.white, align = text.align_right) => t_able.cell(column,row,data,text_color = color, text_size = parsedDashboardSize, text_halign = align)

drawDashboard() =>
    var table t_able = table.new(parsedDashboardPosition,3,12
     , bgcolor      = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color  = #373a46
     , frame_width  = 1)

    t_able.merge_cells(0,0,2,0)
    cell(t_able,0,0,'Sessions',         align = text.align_center)
    cell(t_able,1,1,'Over',             align = text.align_center)
    cell(t_able,2,1,'Under',            align = text.align_center)
    cell(t_able,0,2,'Performance',      align = text.align_left)
    t_able.merge_cells(0,3,2,3)
    cell(t_able,0,3,'Streaks',          align = text.align_center)
    cell(t_able,1,4,'Winning',          align = text.align_center)
    cell(t_able,2,4,'Losing',           align = text.align_center)
    cell(t_able,0,5,'Number',           align = text.align_left)
    cell(t_able,0,6,'Median',           align = text.align_left)
    cell(t_able,0,7,'Mode',             align = text.align_left)
    cell(t_able,0,8,'>= 3 Sessions',    align = text.align_left)
    cell(t_able,0,9,'>= 4 Sessions',    align = text.align_left)
    cell(t_able,0,10,'>= 5 Sessions',   align = text.align_left)
    cell(t_able,0,11,'>= 6 Sessions',   align = text.align_left)

    cell(t_able,1,2,str.format('{0, number, 0.00%}',overperformingSessions.sum()/overperformingSessions.size()))
    cell(t_able,2,2,str.format('{0, number, 0.00%}',1 - overperformingSessions.sum()/overperformingSessions.size()))

    array<int> parsedWinningStreaks = array.new<int>()
    for eachStreak in winningStreaks
        if eachStreak > 1
            parsedWinningStreaks.push(eachStreak)

    array<int> parsedLosingStreaks = array.new<int>()
    for eachStreak in losingStreaks
        if eachStreak > 1
            parsedLosingStreaks.push(eachStreak)

    cell(t_able,1,5,str.format('{0, number, 0}',parsedWinningStreaks.size()))
    cell(t_able,2,5,str.format('{0, number, 0}',parsedLosingStreaks.size()))
    cell(t_able,1,6,str.format('{0, number, 0.00}',parsedWinningStreaks.median()))
    cell(t_able,2,6,str.format('{0, number, 0.00}',parsedLosingStreaks.median()))
    cell(t_able,1,7,str.format('{0, number, 0.00}',parsedWinningStreaks.mode()))
    cell(t_able,2,7,str.format('{0, number, 0.00}',parsedLosingStreaks.mode()))

    parsedWinningStreaks.sort()
    parsedLosingStreaks.sort()

    cell(t_able,1,8,str.format('{0, number, 0.00%}',1 - parsedWinningStreaks.binary_search_leftmost(3)/parsedWinningStreaks.size()))
    cell(t_able,2,8,str.format('{0, number, 0.00%}',1 - parsedLosingStreaks.binary_search_leftmost(3)/parsedLosingStreaks.size()))
    cell(t_able,1,9,str.format('{0, number, 0.00%}',1 - parsedWinningStreaks.binary_search_leftmost(4)/parsedWinningStreaks.size()))
    cell(t_able,2,9,str.format('{0, number, 0.00%}',1 - parsedLosingStreaks.binary_search_leftmost(4)/parsedLosingStreaks.size()))
    cell(t_able,1,10,str.format('{0, number, 0.00%}',1 - parsedWinningStreaks.binary_search_leftmost(5)/parsedWinningStreaks.size()))
    cell(t_able,2,10,str.format('{0, number, 0.00%}',1 - parsedLosingStreaks.binary_search_leftmost(5)/parsedLosingStreaks.size()))
    cell(t_able,1,11,str.format('{0, number, 0.00%}',1 - parsedWinningStreaks.binary_search_leftmost(6)/parsedWinningStreaks.size()))
    cell(t_able,2,11,str.format('{0, number, 0.00%}',1 - parsedLosingStreaks.binary_search_leftmost(6)/parsedLosingStreaks.size()))
    
drawSession(session currentSession) =>    
    bool bullishArea = currentSession.closePrice >= (currentSession.openPrice * (1 + currentSession.cumulativeBenchmarkReturns))

    if (showBullishInput and bullishArea) or (showBearishInput and not bullishArea)

        bool topExtension       = currentSession.benchmarkTop       > currentSession.top
        bool bottomExtension    = currentSession.benchmarkBottom    < currentSession.bottom

        if topExtension or bottomExtension
            color benchmarkAreaColor    = bullishArea       ? bearishColorInput                 : bullishColorInput
            float topLevel              = bottomExtension   ? currentSession.bottom             : currentSession.benchmarkTop
            float bottomLevel           = bottomExtension   ? currentSession.benchmarkBottom    : currentSession.top
            currentSession.benchmarkArea.delete()
            currentSession.benchmarkArea := box.new(chart.point.new(currentSession.startTime,na,topLevel),chart.point.new(currentSession.endTime,na,bottomLevel),color(na),xloc = xloc.bar_time,bgcolor = benchmarkAreaColor)
        
        color areaColor = bullishArea ? bullishColorInput : bearishColorInput    

        currentSession.area.delete()
        currentSession.area := box.new(chart.point.new(currentSession.startTime,na,currentSession.top),chart.point.new(currentSession.endTime,na,currentSession.bottom),color(na),xloc = xloc.bar_time,bgcolor = areaColor)

        currentSession.topLine.delete()
        currentSession.bottomLine.delete()
        currentSession.topLine      := line.new(chart.point.new(currentSession.startTime,na,currentSession.top),chart.point.new(currentSession.endTime,na,currentSession.top),xloc.bar_time, color = color.new(bullishColorInput,0))
        currentSession.bottomLine   := line.new(chart.point.new(currentSession.startTime,na,currentSession.bottom),chart.point.new(currentSession.endTime,na,currentSession.bottom),xloc.bar_time, color = color.new(bearishColorInput,0))                    

        if showBenchmarkInput
            currentSession.benchmarkLine.delete()
            currentSession.benchmarkLine := polyline.new(currentSession.benchmarkPoints,false,false,xloc.bar_time,bullishArea ? benchBearColorInput : benchBullColorInput)
    
drawSessions() =>    
    for eachSession in sessions.slice(0,sessions.size() - 1)
        drawSession(eachSession)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
gatherData()

if barstate.islastconfirmedhistory
    if dashboardInput
        drawDashboard()

    drawSessions()

if barstate.islast
    drawSession(sessions.last())

//---------------------------------------------------------------------------------------------------------------------}
