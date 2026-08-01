// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("HTF Fair Value Gap [LuxAlgo]", "LuxAlgo - HTF Fair Value Gap", overlay = true)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
tf = input.timeframe('D', 'Timeframe')

//Style
offset = input.int(20, minval = 1, group = 'Style')
width = input.int(20, minval = 1, group = 'Style')

bullCss = input(#089981, 'Bullish FVG', group = 'Style')
bearCss = input(#f23645, 'Bearish FVG', group = 'Style')

//Dashboard
showDash  = input(true, 'Show Dashboard', group = 'Dashboard')
dashLoc  = input.string('Top Right', 'Location', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = 'Dashboard')
textSize = input.string('Small', 'Size'        , options = ['Tiny', 'Small', 'Normal'], group = 'Dashboard')

//-----------------------------------------------------------------------------}
//UDT's
//-----------------------------------------------------------------------------{
type fvg
    float max
    float min
    int   left
    int   right
    bool  isbull
    bool  ismitigated = false

//-----------------------------------------------------------------------------}
//Functions
//-----------------------------------------------------------------------------{
detect(itf)=>
    var fvg fvg_object = na

    [h, l, t] = request.security_lower_tf(syminfo.tickerid, itf, [high, low, time])
    
    //If bullish FVG
    if low > high[2] and close > high[2]
        left = 0, right = 0, min_top = low, min_btm = low

        //Search for top time coordinate
        if l.size() > 0
            for i = 0 to l.size()-1
                dtop = math.abs(l.get(i) - low)
                min_top := math.min(dtop, min_top)
                right := dtop == min_top ? t.get(i) : right
                
        //Search for bottom time coordinate
        if (h[2]).size() > 0
            for i = 0 to (h[2]).size()-1
                dbtm = math.abs((h[2]).get(i) - high[2])
                min_btm := math.min(dbtm, min_btm)
                left := dbtm == min_btm ? (t[2]).get(i) : left

        fvg_object := fvg.new(low, high[2], left, right, true)

    //If bearish FVG
    else if high < low[2] and close < low[2]
        left = 0, right = 0, min_top = low, min_btm = low

        //Search for top time coordinate
        if (l[2]).size() > 0
            for i = 0 to (l[2]).size()-1
                dtop = math.abs((l[2]).get(i) - low[2])
                min_top := math.min(dtop, min_top)
                right := dtop == min_top ? (t[2]).get(i) : right

        //Search for bottom time coordinate
        if h.size() > 0
            for i = 0 to h.size()-1
                dbtm = math.abs(h.get(i) - high)
                min_btm := math.min(dbtm, min_btm)
                left := dbtm == min_btm ? t.get(i) : left

        fvg_object := fvg.new(low[2], high, left, right, false)
    
    fvg_object

method set_line_properties(line id, x1, y1, x2, y2, css)=>
    id.set_xy1(x1, y1)
    id.set_xy2(x2, y2)
    id.set_color(css)

//-----------------------------------------------------------------------------}
//Check TF
//-----------------------------------------------------------------------------{
if timeframe.in_seconds(timeframe.period) >= timeframe.in_seconds(tf)
    runtime.error('Chart timeframe needs to be lower than user set timeframe')
        
//-----------------------------------------------------------------------------}
//FVG Detection
//-----------------------------------------------------------------------------{
var float max = na
var float min = na
var int top_x1 = na
var int btm_x1 = na
var mitigated = false

n = bar_index

fvg_object = request.security(syminfo.tickerid, tf, detect(timeframe.period))
new_fvg = bar_index > 0 ? fvg_object.left != (fvg_object[1]).left : false

//Trailing maximum/minimum
if new_fvg
    max := high
    min := low
else
    max := math.max(high, max)
    min := math.min(low, min)

if fvg_object.isbull
    if close < fvg_object.min
        fvg_object.ismitigated := true
else
    if close > fvg_object.max
        fvg_object.ismitigated := true

//-----------------------------------------------------------------------------}
//Dashboard
//-----------------------------------------------------------------------------{
var table_position = dashLoc == 'Bottom Left' ? position.bottom_left 
  : dashLoc == 'Top Right' ? position.top_right 
  : position.bottom_right

var table_size = textSize == 'Tiny' ? size.tiny 
  : textSize == 'Small' ? size.small 
  : size.normal

var tb = table.new(table_position, 2, 2
  , bgcolor = #1e222d
  , border_color = #373a46
  , border_width = 1
  , frame_color = #373a46
  , frame_width = 1)

if barstate.isfirst and showDash
    tb.cell(0, 0, 'HTF FVG', text_color = color.white, text_size = table_size)
    tb.cell(0, 1, 'Status', text_color = color.white, text_size = table_size)
    tb.merge_cells(0, 0, 1, 0)

//-----------------------------------------------------------------------------}
//Display
//-----------------------------------------------------------------------------{
var area   = box.new(na,na,na,na,na)
var avgl   = line.new(na,na,na,na)
var upwick = line.new(na,na,na,na)
var dnwick = line.new(na,na,na,na)

var topcord = line.new(na,na,na,na, xloc.bar_time, style = line.style_dashed)
var btmcord = line.new(na,na,na,na, xloc.bar_time, style = line.style_dashed)
var topcord_ext = line.new(na,na,na,na, style = line.style_dashed)
var btmcord_ext = line.new(na,na,na,na, style = line.style_dashed)

var status = label.new(na,na, style = label.style_label_left, size = size.tiny)

if barstate.islast
    css = fvg_object.isbull ? bullCss : bearCss
    avg = math.avg(fvg_object.max, fvg_object.min)

    //FVG Area
    area.set_lefttop(n + offset, fvg_object.max)
    area.set_rightbottom(n + offset + width, fvg_object.min)
    area.set_bgcolor(color.new(css, 50))
    area.set_border_color(fvg_object.ismitigated ? na : css)

    //FVG Average
    avgl.set_line_properties(n + offset, avg, n + offset + width, avg, css)
    
    //Wicks
    upwick.set_line_properties(n + offset + int(width / 2), math.max(max, fvg_object.max), n + offset + int(width / 2), fvg_object.max, css)  
    dnwick.set_line_properties(n + offset + int(width / 2), math.min(min, fvg_object.min), n + offset + int(width / 2), fvg_object.min, css)

    //Coordinates
    topcord.set_line_properties(fvg_object.right, fvg_object.max, time, fvg_object.max, css)
    btmcord.set_line_properties(fvg_object.left, fvg_object.min, time, fvg_object.min, css)
    
    //Extend
    topcord_ext.set_line_properties(n, fvg_object.max, n + offset-1, fvg_object.max, css)
    btmcord_ext.set_line_properties(n, fvg_object.min, n + offset-1, fvg_object.min, css)

    //Set dashboard status
    if showDash
        tb.cell(1, 1, fvg_object.ismitigated ? 'Mitigated' : 'Unmitigated'
          , bgcolor = color.new(css, 80)
          , text_color = css
          , text_size = table_size)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
bgcolor(new_fvg and fvg_object.isbull ? color.new(bullCss, 50) 
  : new_fvg and not fvg_object.isbull ? color.new(bearCss, 50)
  : na
  , title = 'HTF FVG Detection')

//-----------------------------------------------------------------------------}