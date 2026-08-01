// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Standardized Cumulative Deltas [LuxAlgo]','LuxAlgo - Standardized Cumulative Deltas', max_bars_back = 5000)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

EM_SPACE                = ' '
SPACING                 = EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE
TICKER_GROUP            = SPACING+'TICKER'+SPACING+'COLOR'
DASHBOARD_GROUP         = 'DASHBOARD'
STYLE_GROUP             = 'STYLE'

lengthInput             = input.int(    250,            'Lookback', inline = 'length', maxval = 5000, minval = 10)
autoLengthInput         = input.bool(   true,           'Auto',     inline = 'length')
densityMode             = input.string( 'Average',      'Desnsity Mode', options = ['Average', 'Envelope'])

showTicker00Input       = input.bool(   true,           '', group = TICKER_GROUP, inline = '00')
ticker00Input           = input.symbol( 'BTCUSDT',      '', group = TICKER_GROUP, inline = '00')
ticker00ColorInput      = input(        color.yellow, '', group = TICKER_GROUP, inline = '00')

showTicker01Input       = input.bool(   true,           '', group = TICKER_GROUP, inline = '01')
ticker01Input           = input.symbol( 'ETHUSDT',      '', group = TICKER_GROUP, inline = '01')
ticker01ColorInput      = input(        color.aqua,   '', group = TICKER_GROUP, inline = '01')

showTicker02Input       = input.bool(   true,           '', group = TICKER_GROUP, inline = '02')
ticker02Input           = input.symbol( 'XRPUSDT',      '', group = TICKER_GROUP, inline = '02')
ticker02ColorInput      = input(        color.blue,   '', group = TICKER_GROUP, inline = '02')

showTicker03Input       = input.bool(   true,           '', group = TICKER_GROUP, inline = '03')
ticker03Input           = input.symbol( 'SOLUSDT',      '', group = TICKER_GROUP, inline = '03')
ticker03ColorInput      = input(        color.fuchsia,'', group = TICKER_GROUP, inline = '03')

showTicker04Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '04')
ticker04Input           = input.symbol( 'BNBUSDT',      '', group = TICKER_GROUP, inline = '04')
ticker04ColorInput      = input(        color.green,  '', group = TICKER_GROUP, inline = '04')

showTicker05Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '05')
ticker05Input           = input.symbol( 'DOGEUSDT',     '', group = TICKER_GROUP, inline = '05')
ticker05ColorInput      = input(        color.lime,   '', group = TICKER_GROUP, inline = '05')

showTicker06Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '06')
ticker06Input           = input.symbol( 'ADAUSDT',      '', group = TICKER_GROUP, inline = '06')
ticker06ColorInput      = input(        color.maroon, '', group = TICKER_GROUP, inline = '06')

showTicker07Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '07')
ticker07Input           = input.symbol( 'TRXUSDT',      '', group = TICKER_GROUP, inline = '07')
ticker07ColorInput      = input(        color.silver, '', group = TICKER_GROUP, inline = '07')

showTicker08Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '08')
ticker08Input           = input.symbol( 'LINKUSDT',     '', group = TICKER_GROUP, inline = '08')
ticker08ColorInput      = input(        color.olive,  '', group = TICKER_GROUP, inline = '08')

showTicker09Input       = input.bool(   false,          '', group = TICKER_GROUP, inline = '09')
ticker09Input           = input.symbol( 'AVAXUSDT',     '', group = TICKER_GROUP, inline = '09')
ticker09ColorInput      = input(        color.orange, '', group = TICKER_GROUP, inline = '09')

showDashboardInput      = input.bool(   true,       'Show Dashboard',   group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',         group = DASHBOARD_GROUP, options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput      = input.string( NORMAL,     'Size',             group = DASHBOARD_GROUP, options = [TINY,SMALL,NORMAL,LARGE,HUGE])

histogramInput          = input.bool(   true,               'Density',    group = STYLE_GROUP)
upperColorInput         = input(color.new(#5B9CF6, 80),   'Bullish Density',        group = STYLE_GROUP)
lowerColorInput         = input(color.new(#808080, 80),   'Bearish Density',        group = STYLE_GROUP)
smoothingInput          = input.int(    14,                 'Smoothing',    group = STYLE_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type ticker
    string      tickerID
    color       c_olor        
    array<float> deltas             = na
    array<float> cumulativeDeltas   = na
    string      tag                 = ''    
    polyline    l_ine               = na

var array<ticker> t_ickers      = array.new<ticker>()
var int left_visible_bar_index  = last_bar_index
var int parsedLength            = 10

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

addTicker(bool enabled, string tickerID, color c_olor) =>
    if enabled
        t_ickers.push(ticker.new(tickerID, c_olor, array.new<float>(), array.new<float>()))

if barstate.isfirst
    addTicker(showTicker00Input,ticker00Input,ticker00ColorInput)
    addTicker(showTicker01Input,ticker01Input,ticker01ColorInput)
    addTicker(showTicker02Input,ticker02Input,ticker02ColorInput)
    addTicker(showTicker03Input,ticker03Input,ticker03ColorInput)
    addTicker(showTicker04Input,ticker04Input,ticker04ColorInput)
    addTicker(showTicker05Input,ticker05Input,ticker05ColorInput)
    addTicker(showTicker06Input,ticker06Input,ticker06ColorInput)
    addTicker(showTicker07Input,ticker07Input,ticker07ColorInput)
    addTicker(showTicker08Input,ticker08Input,ticker08ColorInput)
    addTicker(showTicker09Input,ticker09Input,ticker09ColorInput)

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
fetchData() =>
    for eachTicker in t_ickers
        [c_lose,o_pen,t_ag] = request.security(eachTicker.tickerID, timeframe.period, [close, open, syminfo.ticker])
        eachTicker.tag      := t_ag
        delta               = nz(c_lose - o_pen)
        eachTicker.deltas.unshift(delta)        

        if eachTicker.deltas.size() > parsedLength
            eachTicker.deltas.pop()            

workData() =>
    for eachTicker in t_ickers        
        eachTicker.cumulativeDeltas.clear()
        standarizedDeltas   = eachTicker.deltas.standardize()
        float sum           = 0

        for index = eachTicker.deltas.size() - 1 to 0        
            sum += standarizedDeltas.get(index)
            eachTicker.cumulativeDeltas.unshift(sum)            

drawLines() =>
    for eachTicker in t_ickers
        eachTicker.l_ine.delete()
        array<chart.point> points   = array.new<chart.point>()
        int length                  = eachTicker.cumulativeDeltas.size()
        points.unshift(chart.point.new(na,last_bar_index - length,0))

        for index = length - 1 to 0
            points.unshift(chart.point.new(na,last_bar_index - index,eachTicker.cumulativeDeltas.get(index)))

        eachTicker.l_ine := polyline.new(points,line_color = eachTicker.c_olor)

deltaExtremes(int index) =>
    float max = 0
    float min = 0
    den = 0

    for eachTicker in t_ickers
        delta   = eachTicker.cumulativeDeltas.get(index)
        max     := densityMode == 'Average' ? max + math.max(delta, 0) : math.max(delta, max)
        min     := densityMode == 'Average' ? min + math.min(delta, 0) : math.min(delta, min)
        den     += 1

    if densityMode == 'Average'
        max /= den
        min /= den

    [max, min]

twoPassFilter() =>
    var float alpha                 = 2 / (smoothingInput + 1)
    int length                      = t_ickers.first().cumulativeDeltas.size()
    float upperDelta                = 0
    float lowerDelta                = 0
    array<float> upperDeltas        = array.new<float>()
    array<float> lowerDeltas        = array.new<float>()
    array<chart.point> upperPoints  = array.new<chart.point>()
    array<chart.point> lowerPoints  = array.new<chart.point>()

    for index = length - 1 to 0    
        [max, min] = deltaExtremes(index)
        upperDelta += alpha * (max - upperDelta)
        lowerDelta += alpha * (min - lowerDelta)        
        upperDeltas.unshift(upperDelta)
        lowerDeltas.unshift(lowerDelta)
        upperPoints.unshift(chart.point.new(na, last_bar_index - index, 0))
        lowerPoints.unshift(chart.point.new(na, last_bar_index - index, 0))
    
    float upperDeltaSecondPass = upperDeltas.last()
    float lowerDeltaSecondPass = lowerDeltas.last()

    for index = 0 to length - 1
        upperDeltaSecondPass += alpha * (upperDeltas.get(index) - upperDeltaSecondPass)
        lowerDeltaSecondPass += alpha * (lowerDeltas.get(index) - lowerDeltaSecondPass)
        upperPoints.unshift(chart.point.new(na, last_bar_index - index, upperDeltaSecondPass))
        lowerPoints.unshift(chart.point.new(na, last_bar_index - index, lowerDeltaSecondPass))

    [upperPoints,lowerPoints]

drawHistogram() =>
    var polyline upperLine = na
    var polyline lowerLine = na    
    upperLine.delete()
    lowerLine.delete()
    [upperPoints,lowerPoints]   = twoPassFilter()    
    upperLine                   := polyline.new(upperPoints,false,true,line_color = upperColorInput,fill_color = upperColorInput)
    lowerLine                   := polyline.new(lowerPoints,false,true,line_color = lowerColorInput,fill_color = lowerColorInput)
    
drawBaseLine() =>
    int length          = t_ickers.first().cumulativeDeltas.size()
    var line baseLine   = line.new(chart.point.new(na,last_bar_index - length,0),chart.point.new(na,last_bar_index,0), color = color.gray)
    baseLine.set_first_point(chart.point.new(na,last_bar_index - length + 1,0))
    baseLine.set_second_point(chart.point.new(na,last_bar_index,0))

drawDashboard() =>
    var table t_able = table.new(parsedDashboardPosition, 1, t_ickers.size()
     , bgcolor = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color = #373a46
     , frame_width = 1)

    for [index,eachTicker] in t_ickers
        t_able.cell(0,index,eachTicker.tag,text_color = eachTicker.c_olor, text_size = parsedDashboardSize)
    
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
left_visible_bar_index  := time == chart.left_visible_bar_time ? bar_index : left_visible_bar_index
parsedLength            := autoLengthInput ? math.max(10,last_bar_index - left_visible_bar_index - 5) : lengthInput
executionWindow         = bar_index >= last_bar_index - parsedLength

if executionWindow
    fetchData()

    if barstate.islastconfirmedhistory            
        workData()    
        drawLines()
        drawBaseLine()

        if histogramInput
            drawHistogram()

        if showDashboardInput
            drawDashboard()

//---------------------------------------------------------------------------------------------------------------------}