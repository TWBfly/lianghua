// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Volume Zones Internal Visualizer [LuxAlgo]", "LuxAlgo - Volume Zones Internal Visualizer", overlay = true, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
size = input.int(5, 'Row Size', minval = 2)
tf = input.timeframe('1', 'Intrabar Timeframe')

showLast = input(5, "Show Last Unmitigated PAL's")

//Style
bullBorder      = input(true, 'Bullish Border', inline = 'bull_candles', group = 'Style')
bullBorderColor = input(#089981, '', inline = 'bull_candles', group = 'Style')

bearBorder      = input(true, 'Bearish Border', inline = 'bear_border', group = 'Style')
bearBorderColor = input(#f23645, ''         , inline = 'bear_border', group = 'Style')

bullHighVolArea = input(#089981, 'Bullish Volume Area', inline = 'bull_area', group = 'Style')
bullLowVolArea  = input(color.new(#089981, 80), ''    , inline = 'bull_area', group = 'Style')
bearHighVolArea = input(#f23645, 'Bearish Volume Area', inline = 'bear_area', group = 'Style')
bearLowVolArea  = input(color.new(#f23645, 80), ''    , inline = 'bear_area', group = 'Style')

showPal = input(true, 'PAL', inline = 'pal', group = 'Style')
palCss  = input(#ff5d00, '', inline = 'pal', group = 'Style')
palAuto = input(true, 'Auto', inline = 'pal', group = 'Style')

//---------------------------------------------------------------------------------------------------------------------}
//UDT
//---------------------------------------------------------------------------------------------------------------------{
type pal
    float value
    int   loc
    float vol

type pal_display
    line level
    label lbl

//---------------------------------------------------------------------------------------------------------------------}
//Display unmitigated PAL's
//---------------------------------------------------------------------------------------------------------------------{
var pals = array.new<pal>(0)

n = bar_index

//Evaluate buffer size
if pals.size() > 100
    pals.pop()

//Test for mitigation
if pals.size() > 0
    for i = pals.size()-1 to 0
        get_pal = pals.get(i)
        if high > get_pal.value and low < get_pal.value
            pals.remove(i)

//---------------------------------------------------------------------------------------------------------------------}
//Get Data
//---------------------------------------------------------------------------------------------------------------------{
float pal_value = na

[o, h, l, c, v] = request.security_lower_tf(syminfo.tickerid, tf, [open, high, low, close, volume])

r = (high - low) / size

vols = array.new_float(0)
buy_vol = 0.
buy_vols = array.new_float(0)

//Get accumulated volume
if v.size() > 0
    min = low
    max = low

    //Divide candle into "size" ranges and count accumulated volume
    for i = 0 to size-1
        sum = 0.
        max += r

        //Loop trough intrabar candles and accumulate intrabar volume within range
        for [index, vol] in v
            if h.get(index) > min and l.get(index) < max
                sum += vol
                buy_vol += c.get(index) > o.get(index) ? vol : 0

        //Populate arrays
        vols.push(sum)
        buy_vols.push(buy_vol)
        min := max

    pal_v = v.max() 
    pal_value := c.get(v.indexof(pal_v))

    //Populate pals array 
    if showPal and not na(pal_value)
        pals.unshift(pal.new(pal_value, n, pal_v))

index_of_max = vols.indexof(vols.max())
index_of_min = vols.indexof(vols.min())

max_top = low + r * (index_of_max + 1)
max_btm = low + r * index_of_max

min_top = low + r * (index_of_min + 1)
min_btm = low + r * index_of_min

//---------------------------------------------------------------------------------------------------------------------}
//Display pals
//---------------------------------------------------------------------------------------------------------------------{
var displayed_pals = array.new<pal_display>(0)

//Delete previously displayed elements
if displayed_pals.size() > 0
    for element in displayed_pals
        element.level.delete()
        element.lbl.delete()
    
    displayed_pals.clear()

//Display pals
if barstate.islast and pals.size() > 0 and showLast > 0
    for i = 0 to math.min(showLast-1, pals.size()-1)
        get_pal = pals.get(i)
        
        displayed_pals.push(pal_display.new(
          line.new(get_pal.loc, get_pal.value, n, get_pal.value, color = palAuto ? chart.fg_color : palCss)
          , label.new(n+1, get_pal.value, str.tostring(get_pal.vol, format.volume)
          , color = color(na)
          , size = size.tiny
          , style = label.style_label_left
          , textcolor = palAuto ? chart.fg_color : palCss))
          )

//---------------------------------------------------------------------------------------------------------------------}
//Volume Tooltip
//---------------------------------------------------------------------------------------------------------------------{
extend = '\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n'

//Display label with tooltip
if vols.size() > 0
    str = 'Highest Volume Area: {0, number}\n\nLowest Volume Area: {1, number}'
    vol_tooltip = str.format(str, vols.get(index_of_max), vols.get(index_of_min))

    label.new(bar_index, high
      , style = label.style_label_up
      , size = size.auto
      , color = color(na)
      , textcolor = chart.fg_color
      , tooltip = vol_tooltip
      , text = extend)

//---------------------------------------------------------------------------------------------------------------------}
//Plots
//---------------------------------------------------------------------------------------------------------------------{
//Highlight range
plotcandle(high, high, low, low
  , color = na
  , wickcolor = na
  , bordercolor = close > open and bullBorder ? #089981 : close < open and bearBorder ? #f23645 : na
  , display = display.all - display.status_line)

color max_css = na
color min_css = na

if buy_vols.size() > 1
    max_css := buy_vols.get(index_of_max) > vols.get(index_of_max) / 2 ? bullHighVolArea : bearHighVolArea
    min_css := buy_vols.get(index_of_min) > vols.get(index_of_min) / 2 ? bullLowVolArea  : bearLowVolArea

//Highest volume area
plotcandle(max_btm, max_btm, max_top, max_top
  , color = max_css
  , wickcolor = na
  , bordercolor = na
  , display = display.all - display.status_line)

//Lowest volume area
plotcandle(min_btm, min_btm, min_top, min_top
  , color = min_css
  , wickcolor = na
  , bordercolor = na
  , display = display.all - display.status_line)

//PAL
plotcandle(pal_value, pal_value, pal_value, pal_value
  , color = na
  , wickcolor = na
  , bordercolor = not showPal ? na : palAuto ? chart.fg_color : palCss
  , display = display.all - display.status_line)

//---------------------------------------------------------------------------------------------------------------------}