// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Buy Sell Calendar [LuxAlgo]", overlay = true
  , max_lines_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
freq     = input.string('Daily', 'Frequency', options = ['Daily', 'Monthly'])
method   = input.string('Linreg', 'Trend Method', options = ['Linreg', 'Accumulated Delta', 'Max/Min'])
tzOffset = input(0, 'Timezone Offset')

useDate = input(false, 'Choose Date', inline = 'inline0')
setDate = input.time(0, ''          , inline = 'inline0')

//Calendar
showDash = input(true, 'Show Calendar'                                                                 , group = 'Calendar')
dashLoc  = input.string('Top Right', 'Location', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = 'Calendar')
textSize = input.string('Small', 'Size'        , options = ['Tiny', 'Small', 'Normal']                 , group = 'Calendar')

//-----------------------------------------------------------------------------}
//Functions
//-----------------------------------------------------------------------------{
trend_lreg(reset, accumulate)=>
    var float wma = na
    var float sma = na
    var bull = 0
    var den = 1
    
    if reset
        bull := 0
        wma := close
        sma := close
        den := 1

    if accumulate
        bull += wma / (den*(den+1)/2) > sma / den ? 1 : 0
        
        wma := close
        sma := close
        den := 1
    else
        den += 1
        wma += close * den
        sma += close

    trend = wma / (den*(den+1)/2) > sma / den ? 1 : 0

    [trend, bull]

trend_delta(reset, accumulate)=>
    var up = 0.
    var dn = 0.
    var bull = 0

    d = close - open

    if reset 
        bull := 0
        up := math.max(d, 0)
        dn := math.max(-d, 0)

    if accumulate 
        bull += up > dn ? 1 : 0
        up := math.max(d, 0)
        dn := math.max(-d, 0)
    else
        up += math.max(d, 0)
        dn += math.max(-d, 0)
    
    trend = up > dn ? 1 : 0
    
    [trend, bull]

trend_maxmin(reset, accumulate)=>
    var max = high
    var min = low
    var bull = 0

    if reset 
        bull := 0
        max := high
        min := low

    if accumulate 
        bull += close[1] > math.avg(max, min) ? 1 : 0
        max := high
        min := low
    else
        max := math.max(high, max)
        min := math.min(low, min)

    trend = close > math.avg(max, min) ? 1 : 0

    [trend, bull]

trend_fun(reset, accumulate)=>
    [trend, bull] = switch method
        'Linreg'=> trend_lreg(reset, accumulate)
        'Accumulated Delta'=> trend_delta(reset, accumulate)
        'Max/Min'=> trend_maxmin(reset, accumulate)

//-----------------------------------------------------------------------------}
//Global variables
//-----------------------------------------------------------------------------{
var line l = na

var months = array.from('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')

var tz = str.format('UTC{0}{1}', tzOffset > 0 ? '+' : '', tzOffset)
tz_year  = year(time, tz)
tz_month = month(time, tz)
dmonth   = dayofmonth(time, tz)
dweek    = dayofweek(time, tz)

//Dashboard
var table_position = dashLoc == 'Bottom Left' ? position.bottom_left 
  : dashLoc == 'Top Right' ? position.top_right 
  : position.bottom_right

var table_size = textSize == 'Tiny' ? size.tiny 
  : textSize == 'Small' ? size.small 
  : size.normal

var tb = table.new(table_position, 7, 9
  , bgcolor = #1e222d
  , border_color = #373a46
  , border_width = 1
  , frame_color = #373a46
  , frame_width = 1)

n = bar_index

display = useDate ? time < setDate : true

//-----------------------------------------------------------------------------}
//Daily Calendar
//-----------------------------------------------------------------------------{
var row = 2

//Set calendar days
if barstate.isfirst and freq == 'Daily'
    table.cell(tb, 0, 1, 'Su', text_color = color.white, text_size = table_size)
    table.cell(tb, 1, 1, 'Mo', text_color = color.white, text_size = table_size)
    table.cell(tb, 2, 1, 'Tu', text_color = color.white, text_size = table_size)
    table.cell(tb, 3, 1, 'We', text_color = color.white, text_size = table_size)
    table.cell(tb, 4, 1, 'Th', text_color = color.white, text_size = table_size)
    table.cell(tb, 5, 1, 'Fr', text_color = color.white, text_size = table_size)
    table.cell(tb, 6, 1, 'Sa', text_color = color.white, text_size = table_size)

if display and freq == 'Daily'
    //Set month and clear table
    if dmonth < dmonth[1]
        table.cell(tb, 0, 0, str.tostring(array.get(months, month-1)) + ' ' + str.tostring(year)
          , text_color = color.white
          , text_size = table_size)
        table.merge_cells(tb, 0, 0, 6, 0)

        table.clear(tb, 0, 2, 6, 8)
        row := 2

    if dweek < dweek[1]
        row += 1

    //Set line and most recent line color/calendar cell
    if dmonth != dmonth[1]
        l := line.new(n, close + syminfo.mintick,n, close - syminfo.mintick
          , extend = extend.both
          , style = line.style_dashed
          , color = na)
    
    [trend, bull] = trend_fun(dmonth < dmonth[1], dmonth > dmonth[1])

    trend_css = trend
      ? color.teal 
      : color.red

    line.set_color(l, trend_css)

    table.cell(tb, dweek-1, row, str.tostring(dmonth)
      , text_color = color.white
      , bgcolor = trend_css
      , text_size = table_size)

    table.cell(tb, 0, 8, str.format('{0, number, percent} Bullish', (bull + trend) / dmonth)
      , text_color = color.white
      , text_size = table_size)

if freq == 'Daily'
    table.merge_cells(tb, 0, 8, 6, 8)

//-----------------------------------------------------------------------------}
//Monthly Calendar
//-----------------------------------------------------------------------------{
if display and freq == 'Monthly'
    //Set month and clear table
    if tz_year > nz(tz_year[1])
        for i = 1 to 12
            table.cell(tb, (i-1)%4, math.ceil(i/4)
              , text = str.substring(array.get(months, i-1), 0, 3)
              , text_color = color.white
              , text_size = table_size)

        table.cell(tb, 0, 0, str.tostring(tz_year)
          , text_color = color.white
          , text_size = table_size)
        
        table.merge_cells(tb, 0, 0, 3, 0)
    
    if tz_month != tz_month[1]
        l := line.new(n, close + syminfo.mintick, n, close - syminfo.mintick
          , style = line.style_dashed, extend = extend.both)

    [trend, bull] = trend_fun(tz_year > nz(tz_year[1]), tz_month != tz_month[1])
    
    trend_css = trend
      ? color.teal 
      : color.red

    line.set_color(l, trend_css)

    table.cell(tb, (tz_month-1) % 4, math.ceil(tz_month / 4)
      , text = str.substring(array.get(months, tz_month - 1), 0, 3)
      , text_color = color.white
      , bgcolor = trend_css
      , text_size = table_size)

    table.cell(tb, 0, 4, str.format('{0, number, percent} Bullish', (bull + trend) / tz_month)
      , text_color = color.white
      , text_size = table_size)

if freq == 'Monthly'
    table.merge_cells(tb, 0, 4, 3, 4)

//-----------------------------------------------------------------------------}