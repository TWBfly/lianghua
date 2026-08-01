// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Extrapolated Previous Trend [LuxAlgo]", "LuxAlgo - Extrapolated Previous Trend", overlay = true)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
tf = input.timeframe('D', 'Timeframe')

//Dashboard
showDash  = input(false, 'Show Dashboard', group = 'Dashboard')
dashLoc  = input.string('Top Right', 'Location', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = 'Dashboard')
textSize = input.string('Small', 'Size'        , options = ['Tiny', 'Small', 'Normal']                 , group = 'Dashboard')

//-----------------------------------------------------------------------------}
//Compute previous day trend
//-----------------------------------------------------------------------------{
//Hold variables
var y = array.new<float>(0)
var x = array.new<int>(0)

var float a = na
var float b = na
var color css = na
var up_per = 0
var up_den = 0
var dn_per = 0
var dn_den = 0

n = bar_index

dtf = timeframe.change(tf)

//Test for timeframe change
if dtf
    if y.size() > 0
        //Calculate regression coefficients
        slope = x.covariance(y) / x.variance()
        
        up_per += slope > 0 and a > 0 ? 1 : 0
        up_den += a > 0 ? 1 : 0
        dn_per += slope < 0 and a < 0 ? 1 : 0
        dn_den += a < 0 ? 1 : 0

        a := slope
        b := y.avg() - a * x.avg()
        css := a > 0 ? #00897B : #FF5252

    //Clear arrays and push data
    y.clear(), x.clear()
    y.push(close), x.push(n)
else
    y.push(close)
    x.push(n)

//output
epdt = a * n + b

//-----------------------------------------------------------------------------}
//Dashboard
//-----------------------------------------------------------------------------{
var table_position = dashLoc == 'Bottom Left' ? position.bottom_left 
  : dashLoc == 'Top Right' ? position.top_right 
  : position.bottom_right

var table_size = textSize == 'Tiny' ? size.tiny 
  : textSize == 'Small' ? size.small 
  : size.normal

var tb = table.new(table_position, 2, 3
  , bgcolor = #1e222d
  , border_color = #373a46
  , border_width = 1
  , frame_color = #373a46
  , frame_width = 1)

if showDash
    if barstate.isfirst
        tb.cell(0, 0, 'Trend Persistence', text_color = color.white, text_size = table_size)
        tb.merge_cells(0,0,1,0)

        tb.cell(0, 1, 'Uptrend', text_color = #089981, text_size = table_size)
        tb.cell(1, 1, 'Downtrend', text_color = #f23645, text_size = table_size)
    
    if barstate.islast
        tb.cell(0, 2, str.tostring(up_per / up_den * 100, format.percent), text_color = #089981, text_size = table_size)
        tb.cell(1, 2, str.tostring(dn_per / dn_den * 100, format.percent), text_color = #f23645, text_size = table_size)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot(epdt, 'Extrapolated Previous Trend', dtf ? na : css)

barcolor(a > 0 ? #00897b80 : #ff525280)

bgcolor(dtf ? #787b8680 : na, title = 'Timeframe Change')

//-----------------------------------------------------------------------------}