// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Market Breadth Toolkit [LuxAlgo]','LuxAlgo - Market Breadth Toolkit', max_labels_count = 500, max_lines_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                       = #089981
RED                         = #F23645
GRAY                        = #808080

DEEMER_10                   = 'Breakaway Momentum 10 (Deemer)'
DEEMER_20                   = 'Breakaway Momentum 20 (Deemer)'
ZWEIG_ZBT                   = 'Breadth Thrust (Zweig)'
ZWEIG_MTI                   = 'Market Thrust (Zweig)'
WHALEY_ADT                  = 'Advance Decline Thrust (Whaley)'
WHALEY_UDT                  = 'Up/Down Volume Thrust (Whaley)'

NYSE                        = 'NYSE'
NASDAQ                      = 'NASDAQ'

DOTTED                      = 'Dotted'
DASHED                      = 'Dashed'
SOLID                       = 'Solid'

LEVELS                      = 'LEVELS'
STYLE_GROUP                 = 'STYLE'

fixedLevelsTooltip          = 'Use the top and bottom levels threshold detailed below'

breadthInput                = input.string( ZWEIG_ZBT,  'Breadth',          options = [DEEMER_10,DEEMER_20,ZWEIG_ZBT,ZWEIG_MTI,WHALEY_ADT,WHALEY_UDT])
exchangeInput               = input.string( NYSE,       'Data',             options = [NYSE,NASDAQ])
divergencesInput            = input.bool(   true,       'Divergences',      inline = 'divergences')
divergencesLengthInput      = input.int(    10,         '',                 inline = 'divergences')
fixedLevelsInput            = input.bool(   false,      'Use Fixed Levels', group = LEVELS, tooltip = fixedLevelsTooltip)
topLevelInput               = input.float(  61.5,       'Top Level',        group = LEVELS)
bottomLevelInput            = input.float(  40,         'Bottom Level',     group = LEVELS)
levelStyleInput             = input.string( SOLID,      'Levels Style',     group = LEVELS, options = [DOTTED, DASHED, SOLID])

bearishColorInput           = input.color(  RED,        'Breadth',          group = STYLE_GROUP, inline = 'breadth colors')
bullishColorInput           = input.color(  GREEN,      '',                 group = STYLE_GROUP, inline = 'breadth colors')
bearishDivergenceColorInput = input.color(  RED,        'Divergence',       group = STYLE_GROUP, inline = 'divergence colors')
bullishDivergenceColorInput = input.color(  GREEN,      '',                 group = STYLE_GROUP, inline = 'divergence colors')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
parsedAdvancingIssues = switch exchangeInput
    NYSE     => 'USI:ADV'    
    NASDAQ   => 'USI:ADVQ'    

parsedDecliningIssues = switch exchangeInput
    NYSE     => 'USI:DECL'    
    NASDAQ   => 'USI:DECLQ'    

parsedAdvancingVolume = switch exchangeInput
    NYSE     => 'USI:UVOL'    
    NASDAQ   => 'USI:UVOLQ'

parsedDecliningVolume = switch exchangeInput
    NYSE     => 'USI:DVOL'    
    NASDAQ   => 'USI:DVOLQ'    

parsedLevelStyle = switch levelStyleInput
    DASHED  => hline.style_dashed
    DOTTED  => hline.style_dotted
    => hline.style_solid

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
divergences(float data, int length, float baseLevel) =>
    var array<float> chartHighs     = array.new<float>()
    var array<float> chartLows      = array.new<float>()
    var array<chart.point> highs    = array.new<chart.point>()
    var array<chart.point> lows     = array.new<chart.point>()

    chartData   = close[length]
    pivotHigh   = ta.pivothigh(data,length,length)
    pivotLow    = ta.pivotlow(data,length,length)
    
    if not na(pivotHigh) and data > baseLevel
        currentHigh = chart.point.new(time[length],bar_index[length],pivotHigh)

        if highs.size() > 0 and currentHigh.price < highs.last().price and chartData >= chartHighs.last()
            line.new(highs.last(), currentHigh,xloc = xloc.bar_time, color = bearishDivergenceColorInput, width = 1)
        
        highs.push(currentHigh)
        chartHighs.push(chartData)
        
    if not na(pivotLow) and data < baseLevel
        currentLow = chart.point.new(time[length],bar_index[length],pivotLow)

        if lows.size() > 0  and currentLow.price > lows.last().price and chartData <= chartLows.last()
            line.new(lows.last(), currentLow, xloc = xloc.bar_time, color = bullishDivergenceColorInput, width = 1)

        lows.push(currentLow)
        chartLows.push(chartData)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
advancingIssues = request.security(parsedAdvancingIssues,'',close)
decliningIssues = request.security(parsedDecliningIssues,'',close)
advancingVolume = request.security(parsedAdvancingVolume,'',close)
decliningVolume = request.security(parsedDecliningVolume,'',close)

float parsedBreadth = switch breadthInput 
    DEEMER_10   => ta.sma((advancingIssues/decliningIssues),10)
    DEEMER_20   => ta.sma((advancingIssues/decliningIssues),20)
    ZWEIG_ZBT   => ta.ema(100 * advancingIssues / (advancingIssues + decliningIssues),10)
    ZWEIG_MTI   => (advancingIssues*advancingVolume) - (decliningIssues*decliningVolume)
    WHALEY_ADT  => ta.sma(100 * advancingIssues / (advancingIssues + decliningIssues),5)
    WHALEY_UDT  => ta.sma(100 * advancingVolume / (advancingVolume + decliningVolume),5)

float parsedTopLevel = switch breadthInput
    DEEMER_10   => 1.97
    DEEMER_20   => 1.72
    ZWEIG_ZBT   => 61.5
    ZWEIG_MTI   => 0
    WHALEY_ADT  => 73.66
    WHALEY_UDT  => 77.88

if fixedLevelsInput
    parsedTopLevel := topLevelInput

float parsedBottomLevel = switch breadthInput
    DEEMER_10   => 0.5
    DEEMER_20   => 0.5
    ZWEIG_ZBT   => 40
    ZWEIG_MTI   => 0
    WHALEY_ADT  => 19.05
    WHALEY_UDT  => 16.41

if fixedLevelsInput
    parsedBottomLevel := bottomLevelInput

bool breadthBelowThreshold = ta.lowest(parsedBreadth,11) < parsedBottomLevel

bool parsedThrust = switch breadthInput
    DEEMER_10   => ta.crossover(parsedBreadth,parsedTopLevel)
    DEEMER_20   => ta.crossover(parsedBreadth,parsedTopLevel)
    ZWEIG_ZBT   => ta.crossover(parsedBreadth,parsedTopLevel) and breadthBelowThreshold
    ZWEIG_MTI   => false
    WHALEY_ADT  => parsedBreadth > parsedTopLevel or parsedBreadth < parsedBottomLevel
    WHALEY_UDT  => parsedBreadth > parsedTopLevel or parsedBreadth < parsedBottomLevel

float parsedBaseLevel = switch breadthInput
    DEEMER_10   => 1
    DEEMER_20   => 1
    ZWEIG_ZBT   => 50
    ZWEIG_MTI   => 0
    WHALEY_ADT  => 50
    WHALEY_UDT  => 50

if parsedThrust
    labelStyle = (breadthInput == WHALEY_ADT or breadthInput == WHALEY_UDT) and (parsedBreadth < 50) ? label.style_label_up : label.style_label_down
    label.new(bar_index, parsedBreadth, 'Thrust', color = bullishColorInput, size = size.small, tooltip = str.format_time(time), style = labelStyle)

breadthPlot     = plot(parsedBreadth,   'Breadth',      color = na, display = display.none)
baseLevelPlot   = plot(parsedBaseLevel, 'Base Level',   color = na, display = display.none)

fill(breadthPlot,baseLevelPlot,math.max(parsedBreadth,parsedBaseLevel),math.min(parsedBreadth,parsedBaseLevel),parsedBreadth > parsedBaseLevel ? color.new(bullishColorInput,20) : color.new(bearishColorInput,100), parsedBreadth > parsedBaseLevel ? color.new(bullishColorInput,100) : color.new(bearishColorInput,20))

hline(parsedTopLevel,   'Top Level',    linestyle = parsedLevelStyle)
hline(parsedBottomLevel,'Bottom Level', linestyle = parsedLevelStyle)

if divergencesInput
    divergences(parsedBreadth,divergencesLengthInput,parsedBaseLevel)
    
//---------------------------------------------------------------------------------------------------------------------}