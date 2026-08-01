// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Currency Strength [LuxAlgo]")
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
display = input.string('Trailing Relative Strength', options = ['Trailing Relative Strength', 'Relative Strength Scatter Graph'])

freq = input.timeframe('D', 'Timeframe')

currencyA = input('USD',     '', inline = 'A')
ACss      = input(#ff1100, '', inline = 'A')

currencyB = input('EUR',     '', inline = 'B')
BCss      = input(#2157f3, '', inline = 'B')

currencyC = input('GBP',     '', inline = 'C')
CCss      = input(#4caf50, '', inline = 'C')

currencyD = input('JPY',     '', inline = 'D')
DCss      = input(#e91e63, '', inline = 'D')

currencyE = input('AUD',     '', inline = 'E')
ECss      = input(#ff9800, '', inline = 'E')

//Meter
showDash   = input(true, 'Show Strength Meter'                                                           , group = 'Meter')
resolution = input(20, 'Strength Meter Resolution'                                                       , group = 'Meter')
dashLoc    = input.string('Top Right', 'Location', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = 'Meter')
textSize   = input.string('Small', 'Size'        , options = ['Tiny', 'Small', 'Normal']                 , group = 'Meter')

//Scatter Graph
scatterRes       = input.int(20, 'Scatter Graph Resolution', maxval = 500 , group = 'Scatter Graph')
scatterStrong    = input(color.new(color.green, 80), 'Strong'           , group = 'Scatter Graph')
scatterImprove   = input(color.new(color.aqua, 80), 'Improving'         , group = 'Scatter Graph')
scatterWeakening = input(color.new(color.yellow, 80), 'Weakening'       , group = 'Scatter Graph')
scatterWeak      = input(color.new(color.red, 80), 'Weak'               , group = 'Scatter Graph')   

//-----------------------------------------------------------------------------}
//Functions
//-----------------------------------------------------------------------------{
n = bar_index

set_meter(tb, col, strength, min, max, bg_css)=>
    scale = (strength - min) / (max - min) * (resolution-1)
    
    table.clear(tb, col, 2 , col, resolution+1)
    for i = 0 to scale
        css = color.from_gradient(i, 0, scale, color.new(bg_css, 100), bg_css)
        table.cell(tb, col, resolution+1 - i, bgcolor = css, text_size = size.tiny, height = 0.1)
    
    table.cell(tb, col, 1, str.format('{0}{1}', strength > 0 ? '+' : '', strength)
      , bgcolor = bg_css
      , text_size = size.tiny
      , text_color = color.white
      , width = 2)

set_point(strength, prev_strength, min, max, css)=>
    var label lbl = label.new(na, na, '•'
      , color = #00000000
      , style = label.style_label_center
      , textcolor = css
      , size = size.large)

    if barstate.islast
        scale_prev = (strength - prev_strength - min) / (max - min)
        label.set_x(lbl, n + int(scale_prev * scatterRes))
        label.set_y(lbl, strength)

//-----------------------------------------------------------------------------}
//Get relative currency strength
//-----------------------------------------------------------------------------{
dt = timeframe.change(freq)

AB = request.security(str.format('{0}{1}', currencyA, currencyB), timeframe.period, (close - open) / open * 100)
AC = request.security(str.format('{0}{1}', currencyA, currencyC), timeframe.period, (close - open) / open * 100)
AD = request.security(str.format('{0}{1}', currencyA, currencyD), timeframe.period, (close - open) / open * 100)
AE = request.security(str.format('{0}{1}', currencyA, currencyE), timeframe.period, (close - open) / open * 100)

BA = -AB
BC = request.security(str.format('{0}{1}', currencyB, currencyC), timeframe.period, (close - open) / open * 100)
BD = request.security(str.format('{0}{1}', currencyB, currencyD), timeframe.period, (close - open) / open * 100)
BE = request.security(str.format('{0}{1}', currencyB, currencyE), timeframe.period, (close - open) / open * 100)

CA = -AC
CB = -BC
CD = request.security(str.format('{0}{1}', currencyC, currencyD), timeframe.period, (close - open) / open * 100)
CE = request.security(str.format('{0}{1}', currencyC, currencyE), timeframe.period, (close - open) / open * 100)

DA = -AD
DB = -BD
DC = -CD
DE = request.security(str.format('{0}{1}', currencyD, currencyE), timeframe.period, (close - open) / open * 100)

EA = -AE
EB = -BE
EC = -CE
ED = -DE

//-----------------------------------------------------------------------------}
//Get trailing relative strength
//-----------------------------------------------------------------------------{
var sumA = 0., var prev_A = 0.
var sumB = 0., var prev_B = 0.
var sumC = 0., var prev_C = 0.
var sumD = 0., var prev_D = 0.
var sumE = 0., var prev_E = 0.

if dt
    prev_A := sumA
    prev_B := sumB
    prev_C := sumC
    prev_D := sumD
    prev_E := sumE

    sumA := math.avg(AB, AC, AD, AE)
    sumB := math.avg(BA, BC, BD, BE)
    sumC := math.avg(CA, CB, CD, CE)
    sumD := math.avg(DA, DB, DC, DE)
    sumE := math.avg(EA, EB, EC, ED)
else
    sumA += math.avg(AB, AC, AD, AE)
    sumB += math.avg(BA, BC, BD, BE)
    sumC += math.avg(CA, CB, CD, CE)
    sumD += math.avg(DA, DB, DC, DE)
    sumE += math.avg(EA, EB, EC, ED)

//-----------------------------------------------------------------------------}
//Meter
//-----------------------------------------------------------------------------{
var table_position = dashLoc == 'Bottom Left' ? position.bottom_left 
  : dashLoc == 'Top Right' ? position.top_right 
  : position.bottom_right

var table_size = textSize == 'Tiny' ? size.tiny 
  : textSize == 'Small' ? size.small 
  : size.normal

var tb = table.new(table_position, 11, resolution+3
  , bgcolor = #1e222d
  , border_width = 1
  , frame_color = #373a46
  , frame_width = 1)

if barstate.isfirst and showDash
    table.cell(tb, 0, 0, str.format('Currency Relative Strength ({0})', freq)
      , text_size = table_size
      , text_color = color.white)
    table.merge_cells(tb, 0, 0, 10, 0)

    for i = 0 to 10 by 2
        table.cell(tb, i, 1, bgcolor = #1e222d, width = 0.1)
        table.merge_cells(tb, i, 1, i, resolution+2)

    table.cell(tb, 1, resolution+2, currencyA, text_color = color.white, text_size = table_size, bgcolor = ACss)
    table.cell(tb, 3, resolution+2, currencyB, text_color = color.white, text_size = table_size, bgcolor = BCss)
    table.cell(tb, 5, resolution+2, currencyC, text_color = color.white, text_size = table_size, bgcolor = CCss)
    table.cell(tb, 7, resolution+2, currencyD, text_color = color.white, text_size = table_size, bgcolor = DCss)
    table.cell(tb, 9, resolution+2, currencyE, text_color = color.white, text_size = table_size, bgcolor = ECss)

if barstate.islast and showDash
    min = math.min(sumA, sumB, sumC, sumD, sumE)
    max = math.max(sumA, sumB, sumC, sumD, sumE)
    
    set_meter(tb, 1, sumA, min, max, ACss)
    set_meter(tb, 3, sumB, min, max, BCss)
    set_meter(tb, 5, sumC, min, max, CCss)
    set_meter(tb, 7, sumD, min, max, DCss)
    set_meter(tb, 9, sumE, min, max, ECss)

//-----------------------------------------------------------------------------}
//Scatter Plot
//-----------------------------------------------------------------------------{
var bx_strong    = box.new(na, na, na, na, na
  , bgcolor = scatterStrong)

var bx_improve   = box.new(na, na, na, na, na
  , bgcolor = scatterImprove)

var bx_weakening = box.new(na, na, na, na, na
  , bgcolor = scatterWeakening)

var bx_weak      = box.new(na, na, na, na, na
  , bgcolor = scatterWeak)

var label x_label = label.new(na, na, 'Previous Currency Strength' 
  , style = label.style_label_up
  , color = #00000000
  , textcolor = chart.fg_color) 

var label y_label = label.new(na, 0, 'Currency\nStrength' 
  , style = label.style_label_right
  , color = #00000000
  , textcolor = chart.fg_color) 

//Display Graph
if display == 'Relative Strength Scatter Graph'
    min = math.min(sumA, sumB, sumC, sumD, sumE)
    max = math.max(sumA, sumB, sumC, sumD, sumE)

    prev_min = math.min(sumA - prev_A, sumB - prev_B, sumC - prev_C, sumD - prev_D, sumE - prev_E)
    prev_max = math.max(sumA - prev_A, sumB - prev_B, sumC - prev_C, sumD - prev_D, sumE - prev_E)
    
    if barstate.islast
        //Set areas
        box.set_lefttop(bx_strong, n + int(scatterRes / 2), max)
        box.set_rightbottom(bx_strong, n + scatterRes, 0)
        
        box.set_lefttop(bx_improve, n, max)
        box.set_rightbottom(bx_improve, n + int(scatterRes / 2), 0)
        
        box.set_lefttop(bx_weakening, n + int(scatterRes / 2), 0)
        box.set_rightbottom(bx_weakening, n + scatterRes, min)
        
        box.set_lefttop(bx_weak, n, 0)
        box.set_rightbottom(bx_weak, n + int(scatterRes / 2), min)
        
        //Set axis labels
        label.set_xy(x_label, n + int(scatterRes / 2), min)
        label.set_x(y_label, n)
    
    //Set points
    set_point(sumA, prev_A, prev_min, prev_max, ACss)
    set_point(sumB, prev_B, prev_min, prev_max, BCss)
    set_point(sumC, prev_C, prev_min, prev_max, CCss)
    set_point(sumD, prev_D, prev_min, prev_max, DCss)
    set_point(sumE, prev_E, prev_min, prev_max, ECss)
    
//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot(display == 'Trailing Relative Strength' ? sumA : na
  , color = dt ? na : ACss)
plot(display == 'Trailing Relative Strength' ? sumB : na
  , color = dt ? na : BCss)
plot(display == 'Trailing Relative Strength' ? sumC : na
  , color = dt ? na : CCss)
plot(display == 'Trailing Relative Strength' ? sumD : na
  , color = dt ? na : DCss)
plot(display == 'Trailing Relative Strength' ? sumE : na
  , color = dt ? na : ECss)

//Delimit
bgcolor(display == 'Trailing Relative Strength' and dt
  ? color.new(color.gray, 50) : na)

//-----------------------------------------------------------------------------}