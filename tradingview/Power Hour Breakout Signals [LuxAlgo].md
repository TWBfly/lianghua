// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Power Hour Breakout [LuxAlgo]','LuxAlgo - Power Hour Breakout', overlay = true, max_lines_count = 500, max_boxes_count = 500, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645
SILVER_50               = color.new(color.silver,50)
SILVER_80               = color.new(color.silver,80)

DOTTED                  = 'Dotted'
DASHED                  = 'Dashed'
SOLID                   = 'Solid'

EM_SPACE                = ' '
EN_SPACE                = ' '
FOUR_PER_EM_SPACE       = ' '
SIX_PER_EM_SPACE        = ' '

extensionSpacing        = EM_SPACE+EN_SPACE+SIX_PER_EM_SPACE

BREAKOUT_GROUP          = 'BREAKOUTS'
EXTENSION_GROUP         = 'EXTENSIONS'
FIBONACCI_GROUP         = 'FIBONACCI LEVELS'
STYLE_GROUP             = 'STYLE'

displayAllTooltip       = 'Select how many Power Hours to display or enable the Display All feature.'
powerHourTooltip        = 'Choose a custom Power Hour in New York time.'
breakoutsTooltip        = 'Enable or disable breakouts.'
topExtensionTooltip     = 'Enable or disable the top extension and choose the percentage of Power Hour to use.'
bottomExtensionTooltip  = 'Enable or disable the bottom extension and choose the percentage of Power Hour to use.'
fiboReverseTooltip      = 'Reverse Fibonacci levels.'
fibosLabelsTooltip      = 'Enable or disable labels and choose text size.'
transparencyTooltip     = 'Choose the extension\'s transparency. 0 is solid, and 100 is fully transparent.'

powerHoursLengthInput   = input.int(    10,         'Display Last X Power Hours',   inline = 'powerhours')
displayAllInput         = input.bool(   true,       'Display All',                  inline = 'powerhours', tooltip = displayAllTooltip)
powerHourInput          = input.session('1500-1600','Power Hour (NY Time)',         tooltip = powerHourTooltip)

breakoutsInput          = input.bool(   true,       'Show Breakouts',                   group = BREAKOUT_GROUP,     tooltip = breakoutsTooltip)
bullBreakColorInput     = input.color(  GREEN,      'Bullish Breakout',                 group = BREAKOUT_GROUP)
bearBreakColorInput     = input.color(  RED,        'Bearish Breakout',                 group = BREAKOUT_GROUP)

topExtensionInput       = input.bool(   true,       'Top Extension %'+extensionSpacing, group = EXTENSION_GROUP,    inline = 'top')
topMultiplierInput      = input.int(    50,         '',                                 group = EXTENSION_GROUP,    inline = 'top',     tooltip = topExtensionTooltip,      minval = 1, step = 5) / 100
bottomExtensionInput    = input.bool(   true,       'Bottom Extension %',               group = EXTENSION_GROUP,    inline = 'bottom')
bottomMultiplierInput   = input.int(    50,         '',                                 group = EXTENSION_GROUP,    inline = 'bottom',  tooltip = bottomExtensionTooltip,   minval = 1, step = 5) / 100

fibonacciInput          = input.bool(   true,       'Display Fibonnaci',                group = FIBONACCI_GROUP)
fiboReverseInput        = input.bool(   false,      'Reverse',                          group = FIBONACCI_GROUP,    tooltip = fiboReverseTooltip)

fiboLevel5DisplayInput  = input.bool(   true,       '',     group = FIBONACCI_GROUP,    inline = 'fibo5')
fiboLevel5Input         = input.float(  0.786,      '',     group = FIBONACCI_GROUP,    inline = 'fibo5')
fiboLevel5ColorInput    = input.color(  SILVER_50,  '',     group = FIBONACCI_GROUP,    inline = 'fibo5')
fiboLevel5StyleInput    = input.string( DASHED,     '',     group = FIBONACCI_GROUP,    inline = 'fibo5',   options = [DOTTED,DASHED,SOLID])

fiboLevel4DisplayInput  = input.bool(   true,       '',     group = FIBONACCI_GROUP,    inline = 'fibo4')
fiboLevel4Input         = input.float(  0.618,      '',     group = FIBONACCI_GROUP,    inline = 'fibo4')
fiboLevel4ColorInput    = input.color(  SILVER_50,  '',     group = FIBONACCI_GROUP,    inline = 'fibo4')
fiboLevel4StyleInput    = input.string( DASHED,     '',     group = FIBONACCI_GROUP,    inline = 'fibo4',   options = [DOTTED,DASHED,SOLID])

fiboLevel3DisplayInput  = input.bool(   true,       '',     group = FIBONACCI_GROUP,    inline = 'fibo3')
fiboLevel3Input         = input.float(  0.500,      '',     group = FIBONACCI_GROUP,    inline = 'fibo3')
fiboLevel3ColorInput    = input.color(  SILVER_50,  '',     group = FIBONACCI_GROUP,    inline = 'fibo3')
fiboLevel3StyleInput    = input.string( DASHED,     '',     group = FIBONACCI_GROUP,    inline = 'fibo3',   options = [DOTTED,DASHED,SOLID])

fiboLevel2DisplayInput  = input.bool(   true,       '',     group = FIBONACCI_GROUP,    inline = 'fibo2')
fiboLevel2Input         = input.float(  0.382,      '',     group = FIBONACCI_GROUP,    inline = 'fibo2')
fiboLevel2ColorInput    = input.color(  SILVER_50,  '',     group = FIBONACCI_GROUP,    inline = 'fibo2')
fiboLevel2StyleInput    = input.string( DASHED,     '',     group = FIBONACCI_GROUP,    inline = 'fibo2',   options = [DOTTED,DASHED,SOLID])

fiboLevel1DisplayInput  = input.bool(   true,       '',     group = FIBONACCI_GROUP,    inline = 'fibo1')
fiboLevel1Input         = input.float(  0.236,      '',     group = FIBONACCI_GROUP,    inline = 'fibo1')
fiboLevel1ColorInput    = input.color(  SILVER_50,  '',     group = FIBONACCI_GROUP,    inline = 'fibo1')
fiboLevel1StyleInput    = input.string( DASHED,     '',     group = FIBONACCI_GROUP,    inline = 'fibo1',   options = [DOTTED,DASHED,SOLID])

fibosLabelsInput        = input.bool(   false,      'Display Labels'+FOUR_PER_EM_SPACE,                     group = FIBONACCI_GROUP,    inline = 'fiboLabels')
fibosLabelSizeInput     = input.int(    10,         '|'+FOUR_PER_EM_SPACE+' Text Size'+FOUR_PER_EM_SPACE,   group = FIBONACCI_GROUP,    inline = 'fiboLabels', tooltip = fibosLabelsTooltip)

topColorInput           = input.color(  GREEN,      'Top Color',                group = STYLE_GROUP)
bottomColorInput        = input.color(  RED,        'Bottom Color',             group = STYLE_GROUP)
transparencyInput       = input.int(    80,         'Extension Transparency',   group = STYLE_GROUP,        tooltip = transparencyTooltip,  minval = 0, maxval = 100)
sessionStartInput       = input.bool(   true,       'Session Breaks',           group = STYLE_GROUP,        inline = 'start')
backgroundColorInput    = input.color(  SILVER_80,  '',                         group = STYLE_GROUP,        inline = 'start')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type powerHour
    int startTime
    int endTime            
    int endSession
    float top
    float bottom    
    box area
    array<line> lines    
    array<line> fibos
    array<label> labels
    
var array<powerHour> powerHours = array.new<powerHour>()         
insidePowerHour                 = not na(time(timeframe.period, powerHourInput, 'America/New_York'))
powerHourStart                  = insidePowerHour and not insidePowerHour[1]

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
gatherData() =>
    if powerHourStart
        powerHours.push(powerHour.new(time,time,time,high,low,na,array.new<line>(),array.new<line>(),array.new<label>()))
        
    if powerHours.size() > 0
        powerHour currentPowerHour  = powerHours.last()
        currentPowerHour.endSession := time
        
        if insidePowerHour            
            currentPowerHour.endTime    := time             
            currentPowerHour.top        := math.max(currentPowerHour.top,high)
            currentPowerHour.bottom     := math.min(currentPowerHour.bottom,low)
        
breakouts() =>    
    bool bullishBreakout = false
    bool bearishBreakout = false
    
    if breakoutsInput and powerHours.size() > 0 and not insidePowerHour
        powerHour currentPowerHour  = powerHours.last()
        bullishBreakout := close[1] < currentPowerHour.top and close > currentPowerHour.top
        bearishBreakout := close[1] > currentPowerHour.bottom and close < currentPowerHour.bottom

    [bullishBreakout,bearishBreakout]        

style(string style) =>
    switch style
        DOTTED  => line.style_dotted
        DASHED  => line.style_dashed
        SOLID   => line.style_solid

drawFibonacciLevel(bool drawLevel, powerHour currentPowerHour, float fibonacciLevel, color fibonacciColor, string fibonacciStyle) =>
    if drawLevel
        float fibonacciRange    = math.round_to_mintick(fibonacciLevel * (currentPowerHour.top - currentPowerHour.bottom))
        float priceLevel        = fiboReverseInput ? currentPowerHour.bottom + fibonacciRange : currentPowerHour.top - fibonacciRange
        chart.point lastPoint   = chart.point.new(currentPowerHour.endSession,na,priceLevel)
        currentPowerHour.fibos.push(line.new(chart.point.new(currentPowerHour.startTime,na,priceLevel),lastPoint,xloc.bar_time, color = fibonacciColor, style = fibonacciStyle, width = 1))
        
        if fibosLabelsInput
            currentPowerHour.labels.push(label.new(lastPoint,str.format('{0} ({1})',fibonacciLevel,priceLevel),xloc = xloc.bar_time, yloc = yloc.price, color = color(na), textcolor = fibonacciColor, style = label.style_label_left, size = fibosLabelSizeInput))

drawFibonnaciLevels(powerHour currentPowerHour) =>

    for eachLine in currentPowerHour.fibos
        eachLine.delete()

    for eachLabel in currentPowerHour.labels
        eachLabel.delete()    

    drawFibonacciLevel(fiboLevel1DisplayInput,currentPowerHour,fiboLevel1Input,fiboLevel1ColorInput,style(fiboLevel1StyleInput))
    drawFibonacciLevel(fiboLevel2DisplayInput,currentPowerHour,fiboLevel2Input,fiboLevel2ColorInput,style(fiboLevel2StyleInput))
    drawFibonacciLevel(fiboLevel3DisplayInput,currentPowerHour,fiboLevel3Input,fiboLevel3ColorInput,style(fiboLevel3StyleInput))
    drawFibonacciLevel(fiboLevel4DisplayInput,currentPowerHour,fiboLevel4Input,fiboLevel4ColorInput,style(fiboLevel4StyleInput))   
    drawFibonacciLevel(fiboLevel5DisplayInput,currentPowerHour,fiboLevel5Input,fiboLevel5ColorInput,style(fiboLevel5StyleInput))

drawPowerHourLevel(powerHour currentPowerHour, float level, bool extension, float multiplier, color c_olor) =>
    currentPowerHour.lines.push(line.new(chart.point.new(currentPowerHour.startTime,na,level),chart.point.new(currentPowerHour.endSession,na,level),xloc.bar_time, color = c_olor, width = 1))            
    if extension
        float extensionLevel = math.round_to_mintick(level + multiplier * (currentPowerHour.top - currentPowerHour.bottom))
        currentPowerHour.lines.push(line.new(chart.point.new(currentPowerHour.startTime,na,extensionLevel),chart.point.new(currentPowerHour.endSession,na,extensionLevel),xloc.bar_time, color = c_olor, width = 1))
        linefill.new(currentPowerHour.lines.get(-1),currentPowerHour.lines.get(-2), color.new(c_olor,transparencyInput))

drawPowerHour(powerHour currentPowerHour) =>
    if fibonacciInput
        drawFibonnaciLevels(currentPowerHour)
                                    
    for eachLine in currentPowerHour.lines
        eachLine.delete()

    drawPowerHourLevel(currentPowerHour,currentPowerHour.top,topExtensionInput,topMultiplierInput,topColorInput)
    drawPowerHourLevel(currentPowerHour,currentPowerHour.bottom,bottomExtensionInput,-1*bottomMultiplierInput,bottomColorInput)   

    currentPowerHour.area.delete()            
    currentPowerHour.area := box.new(chart.point.new(currentPowerHour.startTime,na,currentPowerHour.top),chart.point.new(currentPowerHour.endTime,na,currentPowerHour.bottom),border_color = color.new(color.silver,90),bgcolor = color.new(color.silver,90), xloc = xloc.bar_time)

drawPowerHours(int powerHoursLength) =>    
    size = powerHours.size()
    if size > 0
        int startIndex = size - (displayAllInput ? size : powerHoursLength)
        for eachPowerHour in powerHours.slice(startIndex,size)
            drawPowerHour(eachPowerHour)
                        
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
gatherData()

[bullishBreakout,bearishBreakout] = breakouts()
plotshape(bullishBreakout,  'Bullish Breakout', shape.triangleup,   location.belowbar,  bullBreakColorInput, size = size.tiny)
plotshape(bearishBreakout,  'Bearish Breakout', shape.triangledown, location.abovebar,  bearBreakColorInput, size = size.tiny)

color backgroundColor = sessionStartInput and session.isfirstbar_regular ? backgroundColorInput : na
bgcolor(backgroundColor)

if barstate.islastconfirmedhistory        
    drawPowerHours(powerHoursLengthInput)        

if barstate.islast
    if powerHours.size() > 0    
        drawPowerHour(powerHours.last())
    
//---------------------------------------------------------------------------------------------------------------------}