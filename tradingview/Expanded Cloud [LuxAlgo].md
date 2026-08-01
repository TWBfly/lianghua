// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Expanded Cloud [LuxAlgo]', 'LuxAlgo - Expanded Cloud', overlay = true)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645

TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

DASHBOARD_GROUP         = 'DASHBOARD'

lengthInput             = input.int(    20,         'Length',           minval = 1)
reactivityInput         = input.float(  50,         'Expansion %',      minval = 0, maxval = 100) / 100
sourceInput             = input.source( close,      'Source')

showStatisticsInput     = input.bool(   false,      'Show Statistics',  group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',         group = DASHBOARD_GROUP, options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput      = input.string( NORMAL,     'Size',             group = DASHBOARD_GROUP, options = [TINY,SMALL,NORMAL,LARGE,HUGE])

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type stats
    float pnl           = 0
    float profit        = 0
    float loss          = 0
    int trades          = 0
    int winners         = 0
    int losers          = 0
    int winnerBars      = 0
    int loserBars       = 0
    int firstTouch      = 0

type trade
    int bias            = na
    int bar             = na
    float price         = na
    bool touched        = false
    int firstTouch      = na

var stats longs         = stats.new()
var stats shorts        = stats.new()
var trade currentTrade  = trade.new()
var float max           = sourceInput
var float min           = sourceInput
var int trend           = 0

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

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
gatherStats(int bias, float top, float bottom) =>
    log.info('gatherStats')
    bool long           = bias > bias[1]
    bool short          = bias < bias[1]
    var int BULLISH     = 1
    var int BEARISH     = 0
    var int currentBias = 0
    currentBias         := long ? BULLISH : short ? BEARISH : currentBias
    bool newTrade       = currentBias != currentBias[1]

    if newTrade
        float priceDelta  = currentBias == BULLISH ? currentTrade.price - close : close - currentTrade.price
        stats s_tats      = currentBias == BULLISH ? shorts : longs
        
        if not na(priceDelta)
            s_tats.trades   += 1
            s_tats.pnl      += priceDelta

            if currentTrade.touched
                s_tats.firstTouch += currentTrade.firstTouch
            
            if priceDelta > 0
                s_tats.winners    += 1
                s_tats.winnerBars += bar_index - currentTrade.bar
                s_tats.profit     += priceDelta
            else
                s_tats.losers     += 1
                s_tats.loserBars  += bar_index - currentTrade.bar
                s_tats.loss       += priceDelta
            
        currentTrade.bar      := bar_index
        currentTrade.price    := close
        currentTrade.touched  := false
        currentTrade.bias     := currentBias        
        
    else if not currentTrade.touched        
        if (currentTrade.bias == BULLISH and low <= bottom) or (currentTrade.bias == BEARISH and high >= top)
            currentTrade.touched    := true
            currentTrade.firstTouch := bar_index - currentTrade.bar

plotHeader(table t_able, int col, int row, string data, color textColor = #FFFFFF) => t_able.cell(col,row,data,text_color = textColor,text_size = parsedDashboardSize)

plotCell(table t_able, int col, int row, string data, color textColor = #FFFFFF, bool noBackground = true) => t_able.cell(col,row,data,text_color = noBackground ? textColor : color.new(str.tonumber(data) > 0 ? GREEN : RED,0),text_size = parsedDashboardSize, bgcolor = noBackground ? #1e222d : color.new(str.tonumber(data) > 0 ? GREEN : RED,75))

plotHeaders(table t_able) =>
    plotHeader(t_able,1,0,'LONGS')    
    plotHeader(t_able,2,0,'SHORTS')
    plotHeader(t_able,3,0,'TOTAL')

    plotHeader(t_able,0,1,'PNL')
    plotHeader(t_able,0,2,'GROSS PROFIT')
    plotHeader(t_able,0,3,'GROSS LOSS')
    plotHeader(t_able,0,4,'TRADES')
    plotHeader(t_able,0,5,'WINNERS')
    plotHeader(t_able,0,6,'LOSERS')
    plotHeader(t_able,0,7,'AVG. WINNER')
    plotHeader(t_able,0,8,'AVG. LOSER')
    plotHeader(t_able,0,9,'WIN RATE')
    plotHeader(t_able,0,10,'R/R')
    plotHeader(t_able,0,11,'EXPECT.')
    plotHeader(t_able,0,12,'AVG. BARS')
    plotHeader(t_able,0,13,'AVG. WIN. BARS')
    plotHeader(t_able,0,14,'AVG. LOS. BARS')
    plotHeader(t_able,0,15,'AVG. 1st TOUCH')

plotData(table t_able, stats s_tats, int col) =>
    pnl         = col == 3 ? longs.pnl + shorts.pnl : s_tats.pnl
    profit      = col == 3 ? longs.profit + shorts.profit : s_tats.profit
    loss        = col == 3 ? longs.loss + shorts.loss : s_tats.loss
    trades      = col == 3 ? longs.trades + shorts.trades : s_tats.trades
    winners     = col == 3 ? longs.winners + shorts.winners : s_tats.winners
    losers      = col == 3 ? longs.losers + shorts.losers : s_tats.losers
    avgWinner   = col == 3 ? (longs.profit + shorts.profit)/(longs.winners + shorts.winners) : s_tats.profit / s_tats.winners
    avgLoser    = col == 3 ? (longs.loss + shorts.loss)/(longs.losers + shorts.losers) : s_tats.loss / s_tats.losers
    winRate     = col == 3 ? (longs.winners + shorts.winners)/(longs.trades + shorts.trades) : s_tats.winners / s_tats.trades
    risk2reward = math.abs(avgWinner / avgLoser)
    expectacy   = (winRate * avgWinner) - (1 - winRate) * math.abs(avgLoser)
    winnerBars  = col == 3 ? longs.winnerBars + shorts.winnerBars : s_tats.winnerBars
    loserBars   = col == 3 ? longs.loserBars + shorts.loserBars : s_tats.loserBars
    bars        = math.round((winnerBars + loserBars)/trades)
    firstTouch  = (col == 3 ? longs.firstTouch + shorts.firstTouch : s_tats.firstTouch) / trades

    plotCell(t_able,col,1,str.tostring(pnl,format.mintick),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,2,str.tostring(profit,format.mintick),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,3,str.tostring(loss,format.mintick),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,4,str.tostring(trades),color.new(chart.fg_color,25))
    plotCell(t_able,col,5,str.tostring(winners),color.new(chart.fg_color,25))
    plotCell(t_able,col,6,str.tostring(losers),color.new(chart.fg_color,25))
    plotCell(t_able,col,7,str.tostring(avgWinner,format.mintick),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,8,str.tostring(avgLoser,format.mintick),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,9,str.tostring(100*winRate,format.percent),color.new(chart.fg_color,25))
    plotCell(t_able,col,10,str.tostring(risk2reward,'0.00'),color.new(chart.fg_color,25))
    plotCell(t_able,col,11,str.tostring(expectacy,'0.00'),color.new(chart.fg_color,25),false)
    plotCell(t_able,col,12,str.tostring(bars),color.new(chart.fg_color,25))
    plotCell(t_able,col,13,str.tostring(math.round(winnerBars/winners)),color.new(chart.fg_color,25))
    plotCell(t_able,col,14,str.tostring(math.round(loserBars/losers)),color.new(chart.fg_color,25))
    plotCell(t_able,col,15,str.tostring(math.round(firstTouch)),color.new(chart.fg_color,25))

statsDashboard() =>
    var table t_able = table.new(parsedDashboardPosition,4,16
     , bgcolor      = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color  = #373a46
     , frame_width  = 1)

    plotHeaders(t_able)
    plotData(t_able,longs,1)
    plotData(t_able,shorts,2)
    plotData(t_able,na,3)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
// Rolling Max/Min
float upper = ta.highest(sourceInput, lengthInput)
float lower = ta.lowest(sourceInput, lengthInput)

// Expansion operation
max     := math.max(sourceInput, max + nz(upper - upper[1]) - nz(math.max(lower[1] - lower, 0)) * reactivityInput)
min     := math.min(sourceInput, min + nz(lower - lower[1]) + nz(math.max(upper - upper[1], 0)) * reactivityInput)
trend   := min != lower and min[1] == lower[1] ? 1 : max != upper and max[1] == upper[1] ? -1 : trend 

float expansionSource = trend == 1 ? upper : lower

if barstate.isconfirmed
    gatherStats(trend,max,min)

if barstate.islast and showStatisticsInput
    statsDashboard()

plot_max1 = plot(upper, display = display.none, editable = false)
plot_min1 = plot(lower, display = display.none, editable = false)
plot_max2 = plot(max, 'Upper Expansion', color = RED, display = display.none)
plot_min2 = plot(min, 'Lower Expansion', color = GREEN, display = display.none)

plot(expansionSource, 'Expansion Source',
  color = trend != trend[1] ? na : trend == 1 ? color.new(GREEN, 50) : color.new(RED, 50),
  style = plot.style_cross
  )

plot(trend > trend[1] ? lower : trend < trend[1] ? upper : na,
  'Trend Dot',
  trend == 1 ? GREEN : RED,
  2,
  style = plot.style_circles,
  offset = -1
  )

// Area fills
fill(plot_max1, plot_max2, upper, max, color.new(RED, 70), color.new(RED, 50), title = 'Bearish Cloud Gradient')
fill(plot_min1, plot_min2, min, lower, color.new(GREEN, 50), color.new(GREEN, 70), title = 'Bullish Cloud Gradient')

//---------------------------------------------------------------------------------------------------------------------}