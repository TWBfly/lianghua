// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("DR/IDR Candles [LuxAlgo]",overlay=true
  , max_lines_count = 500
  , max_boxes_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
useRegular     = input(true, '', inline = 'regular')
regularSession = input.session('0930-1030', 'Regular', inline = 'regular')

useOvernight     = input(true, '', inline = 'overnight')
overnightSession = input.session('0300-0400', 'Overnight', inline = 'overnight')

tzOffset  = input.int(-5, 'UTC Offset')

//Retracements
reverse = input(false, 'Reverse', group = 'Fibonacci Retracements')

//Fib 0.236
fib236      = input(false, '', inline = '0', group = 'Fibonacci Retracements')
fib236Value = input(0.236, '', inline = '0', group = 'Fibonacci Retracements')
fib236Css   = input(color.yellow, '', inline = '0', group = 'Fibonacci Retracements')

//Fib 0.382
fib382      = input(false, '', inline = '0', group = 'Fibonacci Retracements')
fib382Value = input(0.382, '', inline = '0', group = 'Fibonacci Retracements')
fib382Css   = input(color.fuchsia, '', inline = '0', group = 'Fibonacci Retracements')

//Fib 0.5
fib5      = input(true, '', inline = '5', group = 'Fibonacci Retracements')
fib5Value = input(0.5, '', inline = '5', group = 'Fibonacci Retracements')
fib5Css   = input(color.red, '', inline = '5', group = 'Fibonacci Retracements')

//Fib 0.618
fib618      = input(false, '', inline = '5', group = 'Fibonacci Retracements')
fib618Value = input(0.618, '', inline = '5', group = 'Fibonacci Retracements')
fib618Css   = input(color.aqua, '', inline = '5', group = 'Fibonacci Retracements')

//Fib 0.782
fib782      = input(false, '', inline = '782', group = 'Fibonacci Retracements')
fib782Value = input(0.782, '', inline = '782', group = 'Fibonacci Retracements')
fib782Css   = input(color.green, '', inline = '782', group = 'Fibonacci Retracements')

fromTarget  = input.string('IDR', 'From', options = ['DR', 'IDR'], group = 'Fibonacci Retracements')

//Display elements
showDR    = input(true, 'Show DR'            , group = 'Style')
showIDR   = input(true, 'Show IDR'           , group = 'Style')
showWicks = input(true, 'Show Wicks'         , group = 'Style')
showFill  = input(true, 'Show Range Fill'    , group = 'Style')
showArea  = input(true, 'Show Outside Areas' , group = 'Style')
showBg    = input(true, 'Highlight Session'  , group = 'Style')

//Colors
aboveLvlCss  = input(#2157f3,    'Line Colors', inline = 'lvl_colors', group = 'Style')
insideLvlCss = input(color.gray, ''           , inline = 'lvl_colors', group = 'Style')
belowLvlCss  = input(#ff5d00,    ''           , inline = 'lvl_colors', group = 'Style')

aboveAreaCss  = input(color.new(#2157f3, 80),    'Area Colors', inline = 'area_colors', group = 'Style')
insideAreaCss = input(color.new(color.gray, 90), ''           , inline = 'area_colors', group = 'Style')
belowAreaCss  = input(color.new(#ff5d00, 80),    ''           , inline = 'area_colors', group = 'Style')

//-----------------------------------------------------------------------------}
//Functions
//-----------------------------------------------------------------------------{
avg(val, idr_max, idr_min, dr_max, dr_min)=> 
    var float fib = na
    max = fromTarget == 'IDR' ? idr_max : dr_max
    min = fromTarget == 'IDR' ? idr_min : dr_min

    if reverse
        fib := val * min + (1 - val) * max
    else
        fib := val * max + (1 - val) * min

//-----------------------------------------------------------------------------}
//Global variables
//-----------------------------------------------------------------------------{
var float dr_max  = na
var float dr_min  = na
var float idr_max = na
var float idr_min = na

var float max = na
var float min = na

var int start_anchor = na
var int end_anchor   = na
var int count = 0

var box  count_bx = na
var line upper_wick = na
var line lower_wick = na

var line dr_range_upper  = na
var line dr_range_lower  = na
var line idr_range_upper = na
var line idr_range_lower = na

var tz = str.format('UTC{0}{1}', tzOffset >= 0 ? '+' : '', tzOffset)

n = bar_index
regular_session = time(timeframe.period, regularSession, tz) and useRegular
overnight_session = time(timeframe.period, overnightSession, tz) and useOvernight
session = regular_session or overnight_session

//-----------------------------------------------------------------------------}
//Set DR/IDR
//-----------------------------------------------------------------------------{
if session and not session[1]
    dr_max := high
    dr_min := low
    idr_max := math.max(close, open)
    idr_min := math.min(close, open)
    
    if showDR
        dr_range_upper  := line.new(n, dr_max, n, dr_max)
        dr_range_lower  := line.new(n, dr_min, n, dr_min)

    if showIDR
        idr_range_upper := line.new(n, idr_max, n, idr_max, style = line.style_dashed)
        idr_range_lower := line.new(n, idr_min, n, idr_min, style = line.style_dashed)

    start_anchor := n
    count := 0

else if not session and session[1]
    max := dr_max
    min := dr_min
    
    if showWicks
        upper_wick := line.new(n, max, n, max)
        lower_wick := line.new(n, min, n, min)

    if showFill
        count_bx := box.new(n, dr_max, n, dr_min, border_color = na)
    
    end_anchor := n

else if session
    dr_max := math.max(high, dr_max)
    dr_min := math.min(low, dr_min)
    idr_max := math.max(close, open, idr_max)
    idr_min := math.min(close, open, idr_min)
    
    if showDR
        line.set_xy2(dr_range_upper, n, dr_max)
        line.set_y1(dr_range_upper, dr_max)
        line.set_xy2(dr_range_lower, n, dr_min)
        line.set_y1(dr_range_lower, dr_min)
        
    if showIDR
        line.set_xy2(idr_range_upper, n, idr_max)
        line.set_y1(idr_range_upper, idr_max)
        line.set_xy2(idr_range_lower, n, idr_min)
        line.set_y1(idr_range_lower, idr_min)

if not session
    count += low < idr_max and high > idr_min ? 1 : 0  
    
    max := math.max(high, max)
    min := math.min(low, min)

    lvl_css = close > dr_max ? aboveLvlCss 
      : close < dr_min ? belowLvlCss
      : insideLvlCss
    
    area_css = close > dr_max ? aboveAreaCss 
      : close < dr_min ? belowAreaCss
      : insideAreaCss

    //Show DR/IDR ranges
    if showDR
        line.set_x2(dr_range_upper, n)
        line.set_x2(dr_range_lower, n)
        line.set_color(dr_range_upper, lvl_css)
        line.set_color(dr_range_lower, lvl_css)
        
    if showIDR
        line.set_x2(idr_range_upper, n)
        line.set_x2(idr_range_lower, n)
        line.set_color(idr_range_upper, lvl_css)
        line.set_color(idr_range_lower, lvl_css)

    //Show outside wicks
    if showWicks
        line.set_xy2(upper_wick, int(math.avg(n, start_anchor)), max)
        line.set_x1(upper_wick, int(math.avg(n, start_anchor)))
        
        line.set_xy2(lower_wick, int(math.avg(n, start_anchor)), min)
        line.set_x1(lower_wick, int(math.avg(n, start_anchor)))
        
        line.set_color(upper_wick, lvl_css)
        line.set_color(lower_wick, lvl_css)
    
    //Show interior fill
    if showFill
        box.set_right(count_bx, end_anchor + count)
        box.set_bgcolor(count_bx, area_css)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot_idr_max = plot(idr_max, 'Rolling IDR Maximum', display = display.none)
plot_idr_min = plot(idr_min, 'Rolling IDR Minimum', display = display.none)
plot_close   = plot(close, display = display.none, editable = false)

plot_dr_max = plot(dr_max, 'Rolling DR Maximum', display = display.none)
plot_dr_min = plot(dr_min, 'Rolling DR Minimum', display = display.none)

//Fills
fill(plot_dr_max, plot_close
  , showArea and not session and not ta.cross(close, dr_max) and close > dr_max ? aboveAreaCss : na
  , 'Upper Fill')

fill(plot_close, plot_dr_min
  , showArea and not session and not ta.cross(close, dr_min) and close < dr_min ? belowAreaCss : na
  , 'Lower Fill')

//Retracements
plot(fib236 ? avg(fib236Value, idr_max, idr_min, dr_max, dr_min) : na, 'Fib 0.236', session ? na : fib236Css) 
plot(fib382 ? avg(fib382Value, idr_max, idr_min, dr_max, dr_min) : na, 'Fib 0.382', session ? na : fib382Css) 
plot(fib5 ? avg(fib5Value, idr_max, idr_min, dr_max, dr_min) : na, 'Fib 0.5', session ? na : fib5Css) 
plot(fib618 ? avg(fib618Value, idr_max, idr_min, dr_max, dr_min) : na, 'Fib 0.618', session ? na : fib618Css) 
plot(fib782 ? avg(fib782Value, idr_max, idr_min, dr_max, dr_min) : na, 'Fib 0.782', session ? na : fib782Css) 

//Highlight session
bgcolor(showBg and session ? color.new(color.gray, 80) : na)

//-----------------------------------------------------------------------------}