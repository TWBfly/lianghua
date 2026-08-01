// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Candle 2 Closure [LuxAlgo]','LuxAlgo - Candle 2 Closure', overlay = true, max_boxes_count = 500, max_labels_count = 500, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN               = #089981
RED                 = #F23645
SILVER              = color.silver

STYLE_GROUP         = 'STYLE'
ALERTS_GROUP        = 'ALERTS'

wickSizeTooltip     = 'Max wick size as % of candle'
transparencyTooltip = 'Choose the zone\'s transparency. 0 is solid, and 100 is fully transparent.'

EM_SPACE            = ' '
EN_SPACE            = ' '
SIX_PER_EM_SPACE    = ' '

MS                  = EM_SPACE
NS                  = EN_SPACE
SS                  = SIX_PER_EM_SPACE

candle2Input        = input.bool(   true,   'Candle 2 (Reversal)')
candle3Input        = input.bool(   true,   'Candle 3 (Expansion)')
reversalFilterInput = input.bool(   false,  'Reversals Filter',         inline = 'filter')
filterLengthInput   = input.int(    20,      '',                        inline = 'filter')
wickPercentInput    = input.int(    40,     'Wick Threshold %'+NS+SS,   tooltip = wickSizeTooltip)

bullishColorInput   = input.color(  GREEN,  'Bullish Color',            group = STYLE_GROUP)
bearishColorInput   = input.color(  RED,    'Bearish Color',            group = STYLE_GROUP)
transparencyInput   = input.int(    80,     'Transparency',             group = STYLE_GROUP, tooltip = transparencyTooltip, minval = 0, maxval = 100)
levelsInput         = input.bool(   true,   'Levels',                   group = STYLE_GROUP, inline = 'levels')
levelsColorInput    = input.color(  SILVER, MS+MS+MS+MS,                group = STYLE_GROUP, inline = 'levels')
levelsAutoInput     = input.bool(   true,   'Auto',                     group = STYLE_GROUP, inline = 'levels')
candle2ZoneInput    = input.bool(   true,   'Candle 2 Zone',            group = STYLE_GROUP)
candle3ZoneInput    = input.bool(   true,   'Candle 3 Zone',            group = STYLE_GROUP)

candle2AlertInput   = input.bool(   true,   'Candle 2 Alerts',          group = ALERTS_GROUP)
candle3AlertInput   = input.bool(   true,   'Candle 3 Alerts',          group = ALERTS_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type trigger
    bool candle2 = false
    bool candle3 = false

trigger alertTrigger    = trigger.new()
var int barMilliseconds = 1000 * timeframe.in_seconds()

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
drawLevels() =>
    bool bullishReversalClose   = (reversalFilterInput ? low == ta.lowest(filterLengthInput) : true) and close[1] < open[1] and low < low[1] and close > low[1]
    bool bearishReversalClose   = (reversalFilterInput ? high == ta.highest(filterLengthInput) : true) and close[1] > open[1] and high > high[1] and close < high[1]
    bool candle2Reversal        = bullishReversalClose or bearishReversalClose    
    float wickThreshold         = math.round_to_mintick(0.01*wickPercentInput*(high - low))
    bool bullishBigWick         = (math.min(close,open) - low) > wickThreshold
    bool bearishBigWick         = (high - math.max(close,open)) > wickThreshold
    bool bigWick                = (bullishReversalClose and bullishBigWick) or (bearishBigWick and bearishReversalClose)
    bool bearishExpansion       = bearishReversalClose[1] and high < high[1] and close < low[1]
    bool bullishExpansion       = bullishReversalClose[1] and low > low[1] and close > high[1]
    bool candle3Expansion       = bearishExpansion or bullishExpansion

    if candle2Reversal and candle2Input
        label.new(chart.point.new(time,na,bullishReversalClose ? low : high),'2',xloc.bar_time,bullishReversalClose ? yloc.belowbar : yloc.abovebar, color(na), bullishReversalClose ? label.style_label_up : label.style_label_down, bullishReversalClose ? bullishColorInput : bearishColorInput,size.small)
        alertTrigger.candle2 := true

        if levelsInput
            line.new(chart.point.new(time[1],na,bullishReversalClose ? low[1] : high[1]),chart.point.new(time + barMilliseconds,na,bullishReversalClose ? low[1] : high[1]),xloc.bar_time,color = levelsAutoInput ? chart.fg_color : levelsColorInput)        

        if candle2ZoneInput
            float top           = 0
            float bottom        = 0
            float bodyTop       = math.max(close,open)
            float bodyBottom    = math.min(close,open)

            if bigWick
                top     := bullishReversalClose ? bodyBottom : high - math.round_to_mintick(0.5*(high - bodyTop))
                bottom  := bullishReversalClose ? bodyBottom - math.round_to_mintick(0.5*(bodyBottom - low)) : bodyTop
            else
                top     := bullishReversalClose ? bodyTop : hl2
                bottom  := bullishReversalClose ? hl2 : bodyBottom

            box.new(chart.point.new(time,na,top),chart.point.new(time + barMilliseconds,na,bottom),border_color = color(na),xloc = xloc.bar_time, bgcolor = bullishReversalClose ? color.new(bullishColorInput,transparencyInput) : color.new(bearishColorInput,transparencyInput))

            if levelsInput
                line.new(chart.point.new(time,na,bullishReversalClose ? bottom : top),chart.point.new(time + barMilliseconds,na,bullishReversalClose ? bottom : top),xloc.bar_time,color = levelsAutoInput ? chart.fg_color : levelsColorInput)
                    
    if candle3Expansion and candle3Input
        label.new(chart.point.new(time,na,bullishExpansion ? low : high),'3',xloc.bar_time,bullishExpansion ? yloc.belowbar : yloc.abovebar, color(na), bullishExpansion ? label.style_label_up : label.style_label_down, bullishExpansion ? bullishColorInput : bearishColorInput,size.small)
        alertTrigger.candle3 := true
        
        if candle3ZoneInput
            float top       = bullishExpansion ? close : hl2
            float bottom    = bullishExpansion ? hl2 : close
            box.new(chart.point.new(time,na,top),chart.point.new(time + barMilliseconds,na,bottom),border_color = color(na),xloc = xloc.bar_time, bgcolor = bullishExpansion ? color.new(bullishColorInput,transparencyInput) : color.new(bearishColorInput,transparencyInput))

            if levelsInput
                line.new(chart.point.new(time,na,bullishExpansion ? bottom : top),chart.point.new(time + barMilliseconds,na,bullishExpansion ? bottom : top),xloc.bar_time,color = levelsAutoInput ? chart.fg_color : levelsColorInput)            
 
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
drawLevels()

if candle2AlertInput and alertTrigger.candle2
    alert('Candle 2 Reversal Trigger',alert.freq_once_per_bar_close)

if candle3AlertInput and alertTrigger.candle3
    alert('Candle 3 Reversal Trigger',alert.freq_once_per_bar_close)

//---------------------------------------------------------------------------------------------------------------------}