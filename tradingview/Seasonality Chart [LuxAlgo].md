// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Seasonality Chart [LuxAlgo]", max_lines_count = 500, max_boxes_count = 500, overlay = false)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
lookback = input(20,      'Lookback (Years)')
useCsum  = input(true,    'Cumulate')
relative = input(true,    'Use Percent Change')
showLinreg = input(false, 'Linear Regression')

//Style
showBars = input(true, 'Show Bars'              , inline = 'bars', group = 'Style')
barUpCss = input(color.new(color.teal, 80), '', inline = 'bars', group = 'Style')
barDnCss = input(color.new(color.red, 80),  '', inline = 'bars', group = 'Style')

showLine = input(true, 'Show Line'   , inline = 'line', group = 'Style')
upCss    = input(color.teal, ''    , inline = 'line', group = 'Style')
dnCss    = input(color.red,  ''    , inline = 'line', group = 'Style')

showAxes = input(true, 'Show Axes', inline = 'axes', group = 'Style')

linregCss = input(#ff5d00, 'Linear Regression', group = 'Style')

//-----------------------------------------------------------------------------}
//UDT's
//-----------------------------------------------------------------------------{
type dataholder
    array<float> v   = na
    array<int> count = na

//-----------------------------------------------------------------------------}
//Arrays
//-----------------------------------------------------------------------------{
var year_data = array.from(
  dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(29), array.new<int>(29, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(30), array.new<int>(30, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(30), array.new<int>(30, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(30), array.new<int>(30, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0))
  , dataholder.new(array.new<float>(30), array.new<int>(30, 0))
  , dataholder.new(array.new<float>(31), array.new<int>(31, 0)))

var lines = array.new<line>(0)
var axes  = array.new<line>(0)
var boxes = array.new<box>(0)

if barstate.isfirst
    for i = 0 to 365
        if showLine
            lines.push(line.new(na,na,na,na))
        if showBars
            boxes.push(box.new(na,na,na,na,na))
        
        if i < 12 and showAxes
            axes.push(line.new(na,na,na,na
              , color = chart.fg_color
              , extend = extend.both))

//-----------------------------------------------------------------------------}
//Set values in dataholders
//-----------------------------------------------------------------------------{
d = request.security(syminfo.tickerid, 'D', relative ? (close - open) / open * 100 : close - open)

if dayofmonth != dayofmonth[1] and year >= year(timenow) - lookback
    getm = year_data.get(month-1)
    getd = getm.v.get(dayofmonth-1)
    getm.v.set(dayofmonth-1, nz(getd) + d)
    
    getcount = getm.count.get(dayofmonth-1)
    getm.count.set(dayofmonth-1, getcount + 1)

//-----------------------------------------------------------------------------}
//Display seasonal chart
//-----------------------------------------------------------------------------{
var linreg = line.new(na,na,na,na, color = linregCss)

n = bar_index

if barstate.islast
    k   = 0, out = 0., float y1 = na
    x1 = useCsum ? n - 366 : n - 365
    x2 = n - 365
    use_solid = true

    //Weighted/Simple mean
    wma = 0.
    sma = 0.

    //Loop trough dataholders in yearly array
    for [midx, M] in year_data
        getm = M.v
        getcount = M.count

        //Vertical axes
        if showAxes
            get_axes = axes.get(midx)
            get_axes.set_xy1(x2 + k, 0)
            get_axes.set_xy2(x2 + k, 0 + syminfo.mintick)
            get_axes.set_style(k == 0 ? line.style_solid : line.style_dotted)
            get_axes.set_width(k == 0 ? 2 : 1)

        //Loop trough elements in dataholders
        for [idx, D] in getm
            out := useCsum ? out + nz(D / getcount.get(idx)) : nz(D / getcount.get(idx))

            css    = out > 0 ? upCss : dnCss
            cssbar = out > 0 ? barUpCss : barDnCss
            
            //Set Line
            if showLine
                get_l = lines.get(k)
                get_l.set_xy1(x1 + k, y1)
                get_l.set_xy2(x2 + k, out)
                get_l.set_color(css)

            //Set Bar
            if showBars
                get_b = boxes.get(k)
                get_b.set_lefttop(x2 + k, out)
                get_b.set_rightbottom(x2 + k, 0)
                get_b.set_border_color(cssbar)
                get_b.set_bgcolor(cssbar)
            
            //Cumulate results
            k += 1
            y1 := useCsum ? out : 0
            wma += out * k 
            sma += out
    
    //Set linreg
    if showLinreg
        wma := wma / (k*(k+1)/2)
        sma := sma / k

        linreg.set_xy1(n-365, 4 * sma - 3 * wma)
        linreg.set_xy2(n, 3 * wma - 2 * sma)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot(showAxes ? 0 : na, 'Horizontal Axe', chart.fg_color, 2, show_last = 366)

//-----------------------------------------------------------------------------}