// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator('Historical Correlation [LuxAlgo]','LuxAlgo - Historical Correlation')
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
NONE                    = 'NONE'
HOURLY                  = 'HOURLY'
DAILY                   = 'DAILY'
WEEKLY                  = 'WEEKLY'
MONTHLY                 = 'MONTHLY'
QUARTERLY               = 'QUARTERLY'
YEARLY                  = 'YEARLY'

LINES                   = 'LINES'
HEATMAP                 = 'HEATMAP'

GREEN                   = #089981
RED                     = #F23645

PAIR01_COLOR            = color.aqua 
PAIR02_COLOR            = color.blue
PAIR03_COLOR            = color.fuchsia
PAIR04_COLOR            = color.lime
PAIR05_COLOR            = color.maroon
PAIR06_COLOR            = color.teal
PAIR07_COLOR            = color.olive
PAIR08_COLOR            = color.orange
PAIR09_COLOR            = color.purple
PAIR10_COLOR            = color.yellow

DATA_GROUP              = 'Data gathering'
STYLE_GROUP             = 'Style'

anchoringPointTooltip   = 'Starting point from which the tool is executed.'
anchoringPeriodTooltip  = 'At the beginning of each new period, the tool will reset the calculations.'
pairDefaultTooltip      = 'For each pair of tickers, you can: enable/disable the pair, select the colour and specify the two tickers from which you wish to obtain the correlation.'
drawingModeTooltip      = 'Output style, `LINES` will show the historical correlations as lines, `HEATMAP` will show the current correlations with a colour gradient from green for correlations near 1 to red for correlations near -1.'

anchoringPointInput     = input.time(timestamp('1 Jan 2020 00:00 +0100'),   'Anchor point',     tooltip = anchoringPointTooltip,    group = DATA_GROUP, confirm = true)
anchoringPeriodInput    = input.string( NONE,                               'Anchor period',    tooltip = anchoringPeriodTooltip,   group = DATA_GROUP, options=[NONE,HOURLY,DAILY,WEEKLY,MONTHLY,QUARTERLY,YEARLY])
 
pair01EnabledInput      = input.bool(   true,        'Pair  1',     tooltip = '',                   inline = '0', group = DATA_GROUP)
pair01ColorInput        = input.color(  PAIR01_COLOR,'',            tooltip = '',                   inline = '0', group = DATA_GROUP)
pair01Ticker1Input      = ticker.modify(input.symbol('EURUSD','',   tooltip = '',                   inline = '0', group = DATA_GROUP))
pair01Ticker2Input      = ticker.modify(input.symbol('GBPUSD','',   tooltip = pairDefaultTooltip,   inline = '0', group = DATA_GROUP))

pair02EnabledInput      = input.bool(   true,        'Pair  2',     tooltip = '',                   inline = '1', group = DATA_GROUP)
pair02ColorInput        = input.color(  PAIR02_COLOR,'',            tooltip = '',                   inline = '1', group = DATA_GROUP)
pair02Ticker1Input      = ticker.modify(input.symbol('EURUSD','',   tooltip = '',                   inline = '1', group = DATA_GROUP))
pair02Ticker2Input      = ticker.modify(input.symbol('USDJPY','',   tooltip = pairDefaultTooltip,   inline = '1', group = DATA_GROUP))

pair03EnabledInput      = input.bool(   true,        'Pair  3',     tooltip = '',                   inline = '2', group = DATA_GROUP)
pair03ColorInput        = input.color(  PAIR03_COLOR,'',            tooltip = '',                   inline = '2', group = DATA_GROUP)
pair03Ticker1Input      = ticker.modify(input.symbol('EURUSD','',   tooltip = '',                   inline = '2', group = DATA_GROUP))
pair03Ticker2Input      = ticker.modify(input.symbol('AUDUSD','',   tooltip = pairDefaultTooltip,   inline = '2', group = DATA_GROUP))

pair04EnabledInput      = input.bool(   true,        'Pair  4',     tooltip = '',                   inline = '3', group = DATA_GROUP)
pair04ColorInput        = input.color(  PAIR04_COLOR,'',            tooltip = '',                   inline = '3', group = DATA_GROUP)
pair04Ticker1Input      = ticker.modify(input.symbol('GBPUSD','',   tooltip = '',                   inline = '3', group = DATA_GROUP))
pair04Ticker2Input      = ticker.modify(input.symbol('USDJPY','',   tooltip = pairDefaultTooltip,   inline = '3', group = DATA_GROUP))

pair05EnabledInput      = input.bool(   true,        'Pair  5',     tooltip = '',                   inline = '4', group = DATA_GROUP)
pair05ColorInput        = input.color(  PAIR05_COLOR,'',            tooltip = '',                   inline = '4', group = DATA_GROUP)
pair05Ticker1Input      = ticker.modify(input.symbol('GBPUSD','',   tooltip = '',                   inline = '4', group = DATA_GROUP))
pair05Ticker2Input      = ticker.modify(input.symbol('AUDUSD','',   tooltip = pairDefaultTooltip,   inline = '4', group = DATA_GROUP))

pair06EnabledInput      = input.bool(   true,        'Pair  6',     tooltip = '',                   inline = '5', group = DATA_GROUP)
pair06ColorInput        = input.color(  PAIR06_COLOR,'',            tooltip = '',                   inline = '5', group = DATA_GROUP)
pair06Ticker1Input      = ticker.modify(input.symbol('USDJPY','',   tooltip = '',                   inline = '5', group = DATA_GROUP))
pair06Ticker2Input      = ticker.modify(input.symbol('AUDUSD','',   tooltip = pairDefaultTooltip,   inline = '5', group = DATA_GROUP))

pair07EnabledInput      = input.bool(   true,        'Pair  7',     tooltip = '',                   inline = '6', group = DATA_GROUP)
pair07ColorInput        = input.color(  PAIR07_COLOR,'',            tooltip = '',                   inline = '6', group = DATA_GROUP)
pair07Ticker1Input      = ticker.modify(input.symbol('EURUSD','',   tooltip = '',                   inline = '6', group = DATA_GROUP))
pair07Ticker2Input      = ticker.modify(input.symbol('EURCAD','',   tooltip = pairDefaultTooltip,   inline = '6', group = DATA_GROUP))

pair08EnabledInput      = input.bool(   true,        'Pair  8',     tooltip = '',                   inline = '7', group = DATA_GROUP)
pair08ColorInput        = input.color(  PAIR08_COLOR,'',            tooltip = '',                   inline = '7', group = DATA_GROUP)
pair08Ticker1Input      = ticker.modify(input.symbol('GBPUSD','',   tooltip = '',                   inline = '7', group = DATA_GROUP))
pair08Ticker2Input      = ticker.modify(input.symbol('EURCAD','',   tooltip = pairDefaultTooltip,   inline = '7', group = DATA_GROUP))

pair09EnabledInput      = input.bool(   true,        'Pair  9',     tooltip = '',                   inline = '8', group = DATA_GROUP)
pair09ColorInput        = input.color(  PAIR09_COLOR,'',            tooltip = '',                   inline = '8', group = DATA_GROUP)
pair09Ticker1Input      = ticker.modify(input.symbol('USDJPY','',   tooltip = '',                   inline = '8', group = DATA_GROUP))
pair09Ticker2Input      = ticker.modify(input.symbol('EURCAD','',   tooltip = pairDefaultTooltip,   inline = '8', group = DATA_GROUP))

pair10EnabledInput      = input.bool(   true,        'Pair 10',     tooltip = '',                   inline = '9', group = DATA_GROUP)
pair10ColorInput        = input.color(  PAIR10_COLOR,'',            tooltip = '',                   inline = '9', group = DATA_GROUP)
pair10Ticker1Input      = ticker.modify(input.symbol('AUDUSD','',   tooltip = '',                   inline = '9', group = DATA_GROUP))
pair10Ticker2Input      = ticker.modify(input.symbol('EURCAD','',   tooltip = pairDefaultTooltip,   inline = '9', group = DATA_GROUP))

drawingModeInput        = input.string( LINES,      'Drawing Mode', tooltip = drawingModeTooltip,   group = STYLE_GROUP,    options=[LINES,HEATMAP])

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
// @variable   new period from anchor input, it will be true if current bar is the first bar of a new period
bool newPeriod = switch anchoringPeriodInput
    HOURLY      => timeframe.change('60')
    DAILY       => timeframe.change('D')
    WEEKLY      => timeframe.change('W')
    MONTHLY     => timeframe.change('M')
    QUARTERLY   => timeframe.change('3M')
    YEARLY      => timeframe.change('12M')
    => time == anchoringPointInput

// @type                Storage UDT for ticker pairs
// @field name          (string) name of the pair in `TICKER/TICKER` format 
// @field correlation   (float) correlation value of the pair
// @field lineColor     (color) style for the historical correlation lines
type pair
    string name         = na
    float correlation   = na    
    color lineColor     = na

// @function        Helper function to get ticker name from string formatted as `EXCHANGE:TICKER`
// @param ticker    (string) The name of the ticker in the format `EXCHANGE:TICKER`
// @returns         string
getTickerName(string ticker) => str.substring(ticker, str.pos(ticker, ':') + 1)

// @function        Helper function to take two strings formatted as `EXCHANGE:TICKER` and get the name of a pair formatted as `TICKER/TICKER`
// @param ticker1   (string) The name of the ticker in the format `EXCHANGE:TICKER`
// @param ticker2   (string) The name of the ticker in the format `EXCHANGE:TICKER`
// @returns         string
getPairName(string ticker1, string ticker2) => getTickerName(ticker1) + '/' + getTickerName(ticker2)

// @variable        pairs from pair01 to pair10 as new `pair` UDT from input values with help of `getPairName()` function
var pair pair01 = pair.new( getPairName(pair01Ticker1Input, pair01Ticker2Input), na, pair01ColorInput)
var pair pair02 = pair.new( getPairName(pair02Ticker1Input, pair02Ticker2Input), na, pair02ColorInput)
var pair pair03 = pair.new( getPairName(pair03Ticker1Input, pair03Ticker2Input), na, pair03ColorInput)
var pair pair04 = pair.new( getPairName(pair04Ticker1Input, pair04Ticker2Input), na, pair04ColorInput)
var pair pair05 = pair.new( getPairName(pair05Ticker1Input, pair05Ticker2Input), na, pair05ColorInput)
var pair pair06 = pair.new( getPairName(pair06Ticker1Input, pair06Ticker2Input), na, pair06ColorInput)
var pair pair07 = pair.new( getPairName(pair07Ticker1Input, pair07Ticker2Input), na, pair07ColorInput)
var pair pair08 = pair.new( getPairName(pair08Ticker1Input, pair08Ticker2Input), na, pair08ColorInput)
var pair pair09 = pair.new( getPairName(pair09Ticker1Input, pair09Ticker2Input), na, pair09ColorInput)
var pair pair10 = pair.new( getPairName(pair10Ticker1Input, pair10Ticker2Input), na, pair10ColorInput)

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
// @function                Calculates the correlation coefficient between two tickers, resetting the calculations if `resetCondition` is true.
// @param ticker1           (string) The name of the first ticker
// @param ticker2           (string) The name of the second ticker
// @param resetCondition    (bool) condition to reset the calculations
// @returns                 float
getCorrelationCoefficient(string ticker1, string ticker2, bool resetCondition) =>

    var int occurrences                         = 0
    var float sumPriceTicker1                   = 0
    var float sumPriceTicker2                   = 0
    var float sumSquaredPriceTicker1            = 0
    var float sumSquaredPriceTicker2            = 0
    var float sumSquaredPriceTicker1ByTicker2   = 0

    priceTicker1                                = request.security(ticker1, timeframe.period, close)
    priceTicker2                                = request.security(ticker2, timeframe.period, close)
   
    if resetCondition
        occurrences                             := 1
        sumPriceTicker1                         := priceTicker1
        sumPriceTicker2                         := priceTicker2
        sumSquaredPriceTicker1                  := priceTicker1 * priceTicker1
        sumSquaredPriceTicker2                  := priceTicker2 * priceTicker2
        sumSquaredPriceTicker1ByTicker2         := priceTicker1 * priceTicker2

    else if priceTicker1 != priceTicker1[1] and priceTicker2 != priceTicker2[1]
        occurrences                             += 1
        sumPriceTicker1                         += priceTicker1
        sumPriceTicker2                         += priceTicker2
        sumSquaredPriceTicker1                  += priceTicker1 * priceTicker1
        sumSquaredPriceTicker2                  += priceTicker2 * priceTicker2
        sumSquaredPriceTicker1ByTicker2         += priceTicker1 * priceTicker2

    varianceTicker1                             = sumSquaredPriceTicker1 / occurrences          - ( (sumPriceTicker1 / occurrences) * (sumPriceTicker1 / occurrences) )
    varianceTicker2                             = sumSquaredPriceTicker2 / occurrences          - ( (sumPriceTicker2 / occurrences) * (sumPriceTicker2 / occurrences) )
    covarianceTicker1AndTicker2                 = sumSquaredPriceTicker1ByTicker2 / occurrences - ( (sumPriceTicker1 / occurrences) * (sumPriceTicker2 / occurrences) )

    correlationCoefficient                      = covarianceTicker1AndTicker2 / math.sqrt( varianceTicker1 * varianceTicker2 )

    correlationCoefficient

// @function        Helper function to return `data` if `condition` is met (pair is enabled) or `na` if is not
// @param condition (bool) condition to check, if true returns `data`
// @param data      (float) The data to return
// @returns         float
plottableData(bool condition, float data) => condition ? data : na

// @function        Helper function to return `data` if `drawingModeInput` is set to `LINES`
// @param data      (float) The data to return
// @returns         float
usePlot(float data) => drawingModeInput == LINES ? data : na

// @function        Updates correlation coefficient values on all enabled pairs
// @returns         float
updatePairs() => 
    pair01.correlation := plottableData( pair01EnabledInput, getCorrelationCoefficient( pair01Ticker1Input, pair01Ticker2Input, newPeriod))
    pair02.correlation := plottableData( pair02EnabledInput, getCorrelationCoefficient( pair02Ticker1Input, pair02Ticker2Input, newPeriod))
    pair03.correlation := plottableData( pair03EnabledInput, getCorrelationCoefficient( pair03Ticker1Input, pair03Ticker2Input, newPeriod))
    pair04.correlation := plottableData( pair04EnabledInput, getCorrelationCoefficient( pair04Ticker1Input, pair04Ticker2Input, newPeriod))
    pair05.correlation := plottableData( pair05EnabledInput, getCorrelationCoefficient( pair05Ticker1Input, pair05Ticker2Input, newPeriod))
    pair06.correlation := plottableData( pair06EnabledInput, getCorrelationCoefficient( pair06Ticker1Input, pair06Ticker2Input, newPeriod))
    pair07.correlation := plottableData( pair07EnabledInput, getCorrelationCoefficient( pair07Ticker1Input, pair07Ticker2Input, newPeriod))
    pair08.correlation := plottableData( pair08EnabledInput, getCorrelationCoefficient( pair08Ticker1Input, pair08Ticker2Input, newPeriod))
    pair09.correlation := plottableData( pair09EnabledInput, getCorrelationCoefficient( pair09Ticker1Input, pair09Ticker2Input, newPeriod))
    pair10.correlation := plottableData( pair10EnabledInput, getCorrelationCoefficient( pair10Ticker1Input, pair10Ticker2Input, newPeriod))

// @function        Create a new label on the last bar at the specified price level
// @param name      (string) Text to show in the label
// @param data      (float) Price level to anchor the label
// @param lineColor (color) Label color
// @returns         label ID
drawLabel(string name, float data, color lineColor) => label.new(chart.point.new(na, last_bar_index, data), name, color = color(na) , style=label.style_label_left, textcolor = lineColor, textalign = text.align_right)

// @function        Create labels for all enabled pairs
// @returns         label ID
drawLabels() =>
    for eachLabel in label.all
        label.delete(eachLabel)
    
    if pair01EnabledInput
        drawLabel(pair01.name, pair01.correlation, pair01.lineColor)    
    if pair02EnabledInput
        drawLabel(pair02.name, pair02.correlation, pair02.lineColor)
    if pair03EnabledInput
        drawLabel(pair03.name, pair03.correlation, pair03.lineColor)
    if pair04EnabledInput
        drawLabel(pair04.name, pair04.correlation, pair04.lineColor)
    if pair05EnabledInput
        drawLabel(pair05.name, pair05.correlation, pair05.lineColor)
    if pair06EnabledInput
        drawLabel(pair06.name, pair06.correlation, pair06.lineColor)
    if pair07EnabledInput
        drawLabel(pair07.name, pair07.correlation, pair07.lineColor)
    if pair08EnabledInput
        drawLabel(pair08.name, pair08.correlation, pair08.lineColor)
    if pair09EnabledInput
        drawLabel(pair09.name, pair09.correlation, pair09.lineColor)
    if pair10EnabledInput
        drawLabel(pair10.name,pair10.correlation,pair10.lineColor)

// @function        Helper function to get a row from a pair correlation 
// @param data      (float) Pair correlation
// @returns         int
parsedRow(float data) => math.abs( int(data * 10) - 9)

// @function        Create a new cell
// @param t_able    (table) Table to place the cell
// @param column    (int) Column to place the cell
// @param name      (string) Text to display
// @param data      (float) Pair correlation to display and calculate the row
// @returns         void
drawCell(table t_able, int column, string name, float data) => 
    row = parsedRow(data)
    gradientColor = color.from_gradient(row, 2, 16, GREEN, RED)    
    table.cell(t_able, column, row, name +'\n'+ str.format("{0,number,percent}", data), width = 0, height = 0, text_color = gradientColor, bgcolor = color.new(chart.fg_color,90), text_size = size.auto)

// @function        Create a new empty cell as background for the table
// @param t_able    (table) Table to place the cell
// @param column    (int) Column to place the cell
// @param row       (int) Row to place the cell
// @returns         void
drawBackgroundCell(table t_able, int column, int row) => table.cell(t_able, column, row, ' ', width = 0, height = 0, text_color = chart.fg_color, bgcolor = color.new(chart.fg_color,90), text_size = size.auto)

// @function        Create a new table to display all enabled pairs correlation
// @returns         void
drawTable() =>
    var table t_able = table.new(position.middle_center,10,19)    

    for row = 0 to 18
        drawBackgroundCell(t_able,0,row)
        drawBackgroundCell(t_able,1,row)
        drawBackgroundCell(t_able,2,row)
        drawBackgroundCell(t_able,3,row)
        drawBackgroundCell(t_able,4,row)
        drawBackgroundCell(t_able,5,row)
        drawBackgroundCell(t_able,6,row)
        drawBackgroundCell(t_able,7,row)
        drawBackgroundCell(t_able,8,row)
        drawBackgroundCell(t_able,9,row)

    drawCell(t_able,0,pair01.name,pair01.correlation)
    drawCell(t_able,1,pair02.name,pair02.correlation)
    drawCell(t_able,2,pair03.name,pair03.correlation)
    drawCell(t_able,3,pair04.name,pair04.correlation)
    drawCell(t_able,4,pair05.name,pair05.correlation)
    drawCell(t_able,5,pair06.name,pair06.correlation)
    drawCell(t_able,6,pair07.name,pair07.correlation)
    drawCell(t_able,7,pair08.name,pair08.correlation)
    drawCell(t_able,8,pair09.name,pair09.correlation)
    drawCell(t_able,9,pair10.name,pair10.correlation)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
// @variable    bool variable to check if current bar is within the execution window
executionWindow = time >= anchoringPointInput
    
if executionWindow
    // we update the correlation values on each enabled pair
    updatePairs()

    // on the chart last bar we draw either the labels for the lines or the table for the heatmap
    if barstate.islastconfirmedhistory or barstate.islast
        if drawingModeInput == LINES
            drawLabels()
        else
            drawTable()

// we plot a line at zero level for convenience
hline(0, color = color.new(chart.fg_color, 50))

// we plot the historical correlation lines if `drawingModeInput` is set to LINES
plot(usePlot(pair01.correlation), '', pair01.lineColor)
plot(usePlot(pair02.correlation), '', pair02.lineColor)
plot(usePlot(pair03.correlation), '', pair03.lineColor)
plot(usePlot(pair04.correlation), '', pair04.lineColor)
plot(usePlot(pair05.correlation), '', pair05.lineColor)
plot(usePlot(pair06.correlation), '', pair06.lineColor)
plot(usePlot(pair07.correlation), '', pair07.lineColor)
plot(usePlot(pair08.correlation), '', pair08.lineColor)
plot(usePlot(pair09.correlation), '', pair09.lineColor)
plot(usePlot(pair10.correlation), '', pair10.lineColor)

//---------------------------------------------------------------------------------------------------------------------}