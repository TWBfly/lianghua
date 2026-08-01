// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Power Hour Trendlines [LuxAlgo]','LuxAlgo - Power Hour Trendlines', overlay = true, max_bars_back = 5000)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
RED                 = #F23645
GREEN               = #089981
BLUE                = #2962FF
ORANGE              = #FF5D00
ORANGE_LIGHT        = #FEF1E8
GREEN_90            = color.new(GREEN,90)
RED_90              = color.new(RED,90)

STYLE_GROUP         = 'Style'

EM_SPACE            = ' '
EN_SPACE            = ' '
FOUR_PER_EM_SPACE   = ' '
SIX_PER_EM_SPACE    = ' '

topTag              = 'Top'+EM_SPACE+EN_SPACE+SIX_PER_EM_SPACE
middleTag           = 'Middle'+FOUR_PER_EM_SPACE

sessionInput        = input.session('1500-1600','Power Hour (NY Time)')
memoryInput         = input.int(    10,         'Sessions Memory', tooltip = 'The amount of trading sessions to consider when fitting the trendlines')

topInput            = input.bool(   true,       topTag,         group = STYLE_GROUP, inline = 'top')
topColorInput       = input.color(  GREEN,      '',             group = STYLE_GROUP, inline = 'top')
topFillInput        = input.color(  GREEN_90,   '',             group = STYLE_GROUP, inline = 'top')
middleInput         = input.bool(   true,       middleTag,      group = STYLE_GROUP, inline = 'middle')
middleColorInput    = input.color(  BLUE,       '',             group = STYLE_GROUP, inline = 'middle')
bottomInput         = input.bool(   true,       'Bottom',       group = STYLE_GROUP, inline = 'bottom')
bottomColorInput    = input.color(  RED,        '',             group = STYLE_GROUP, inline = 'bottom')
bottomFillInput     = input.color(  RED_90,     '',             group = STYLE_GROUP, inline = 'bottom')
backgroundInput     = input.bool(   true,       'Background',   group = STYLE_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type vector
    float[] y
    int[]   x
    int[]   t

type lines
    line top
    line middle
    line bottom

var lines trendlines        = lines.new(na,na,na)
var array<vector> sessions  = array.new<vector>(0)
var int session             = na
var bool powerHour          = false

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
error(bool wrongTimeframe = true) =>
    var table t_able= table.new(position.top_center,1,1
     , bgcolor      = ORANGE_LIGHT
     , border_color = ORANGE
     , border_width = 1
     , frame_color  = ORANGE
     , frame_width  = 1)

    if wrongTimeframe
        t_able.cell(0,0,'⚠ Warning: The tool will not display trendlines on higher timeframes.\nPlease select a chart timeframe equal or lower than 1H.',text_color = ORANGE, text_size = 0)
    else
        t_able.cell(0,0,'⚠ Warning: The tool is not detecting power hours.\nPlease select different hours for the Power Hour (NY Time) parameter.',text_color = ORANGE, text_size = 0)

plotLine(a, b, x1Time, x1Bar, lineColor) => line.new(x1Time, a * x1Bar + b, time, a * bar_index + b, xloc.bar_time, color = lineColor)

fit_line(x, y) =>
    a = y.covariance(x) / x.variance()
    b = y.avg() - a * x.avg()
    [a, b]

trendlines() =>
    if session.isfirstbar_regular
        sessions.push(vector.new(array.new<float>(0), array.new<int>(0),array.new<int>(0)))
        if sessions.size() > memoryInput
            sessions.shift()

    if powerHour and sessions.size() > 0
        sessions.last().y.push(close)
        sessions.last().x.push(bar_index)
        sessions.last().t.push(time)

    if barstate.islast        
        if sessions.size() > 0 and sessions.first().t.size() > 0
            concatY = array.new<float>(0)
            concatX = array.new<int>(0)
            concatT = array.new<int>(0)

            for element in sessions
                concatY := concatY.concat(element.y)
                concatX := concatX.concat(element.x)
                concatT := concatT.concat(element.t)
            
            int x1Time  = concatT.first()
            int x1Bar   = concatX.first()
            [a, b]      = fit_line(concatX, concatY)

            if middleInput
                trendlines.middle.delete()
                trendlines.middle := plotLine(a,b, x1Time, x1Bar, middleColorInput)

            upper = vector.new(array.new<float>(0), array.new<int>(0))
            lower = vector.new(array.new<float>(0), array.new<int>(0))
                
            for [idx, element] in concatX
                point   = a * element + b
                getY    = concatY.get(idx)

                if getY > point
                    upper.y.push(getY), upper.x.push(element)
                else
                    lower.y.push(getY), lower.x.push(element)

            if topInput
                [topA,topB] = fit_line(upper.x, upper.y)        
                trendlines.top.delete()
                trendlines.top := plotLine(topA,topB, x1Time, x1Bar, topColorInput)

            if bottomInput
                [bottomA,bottomB] = fit_line(lower.x, lower.y)
                trendlines.bottom.delete()
                trendlines.bottom := plotLine(bottomA,bottomB, x1Time, x1Bar, bottomColorInput)
            
            if backgroundInput            
                linefill.new(trendlines.top,trendlines.middle,topFillInput)
                linefill.new(trendlines.middle,trendlines.bottom,bottomFillInput)
        else
            error(false)
            na
            
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
session     := time(timeframe.period, session=sessionInput, timezone = 'America/New_York')
powerHour   := not na(session)

if timeframe.in_seconds() > 3600
    error()
else
    trendlines()  

plot(powerHour ? close : na, color = ORANGE, style = plot.style_circles)

//---------------------------------------------------------------------------------------------------------------------}