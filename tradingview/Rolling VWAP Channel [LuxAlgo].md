// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Rolling VWAP Channel [LuxAlgo]", "LuxAlgo - Rolling VWAP Channel", overlay = true, calc_bars_count = 10000)

//---------------------------------------------------------------------------------------------------------------------}
//User inputs
//---------------------------------------------------------------------------------------------------------------------{
anchor = input.timeframe("60", title = "Anchor Period", group = "Rolling VWAP Parameters")
src = input.source(hlc3, title = "VWAP Source", group = "Rolling VWAP Parameters")
vwapNum = input.int(20, maxval = 500, minval = 1, title = "VWAP Amount", tooltip = "Max: 500 VWAPs", group = "Rolling VWAP Parameters")

g = "Toggle                 Percentile                  Width                 Color"

maxTog = input.bool(true, title = "", inline = "max", group = g)
maxPer = input.float(100, maxval = 100, minval = 0, title = "Max   ", inline = "max", group = g)
maxWid = input.int(1, minval = 1, title = "",inline = "max", group = g)
maxColor = input.color(color.new(#089981,50), title = "", inline = "max", group = g)

hiTog = input.bool(true, title = "", inline  = "hi", group= g)
hiPer = input.float(70, maxval = 100, minval = 0, title = "Upper ", inline = "hi", group = g)
hiWid = input.int(1, minval = 1, title = "",inline = "hi", group = g)
hiColor = input.color(color.new(color.gray,50),title = "", inline = "hi", group = g)

medTog = input.bool(true, title = "", inline  = "med", group= g)
medPer = input.float(50, maxval = 100, minval = 0, title = "Median", inline = "med", group = g)
medWid = input.int(1, minval = 1, title = "",inline = "med", group = g)
medColor = input.color(color.new(color.gray,50),title = "", inline = "med", group = g)

loTog = input.bool(true, title = "", inline  = "lo", group= g)
loPer = input.float(30, maxval = 100, minval = 0, title = "Lower ", inline = "lo", group = g)
loWid = input.int(1, minval = 1, title = "",inline = "lo", group = g)
loColor = input.color(color.new(color.gray,50),title = "", inline = "lo", group = g)

minTog = input.bool(true, title = "", inline = "min", group = g)
minPer = input.float(0, maxval = 100, minval = 0, title = "Min   ", inline = "min", group = g)
minWid = input.int(1, minval = 1, title = "",inline = "min", group = g)
minColor = input.color(color.new(#f23645,50), title = "", inline = "min", group = g)

useDash = input.bool(true, title = "Dashed Lines", group = "Style")
useGrad = input.bool(true, title = "Gradient Fill", group = "Style")
showAnchor = input(true, 'Show Anchor', group = "Style")

bg_invis = color.new(chart.bg_color,100)

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{

//Dash
dash() => useDash ? (math.floor(bar_index/2) - bar_index/2) == 0 : true

//Smoothing
smooth(_val,_interval) =>
    var smoothed_val = nz(_val)
    smoothed_val += nz((_val - smoothed_val) / _interval)
    smoothed_val

//---------------------------------------------------------------------------------------------------------------------}
//Rolling VWAP Calculations
//---------------------------------------------------------------------------------------------------------------------{

//Variables
var int count = 0

var vwaps_num = array.new_float(na)
var vwaps_den = array.new_float(na)
var vwaps = array.new_float(na)

//Triggers
new_tf = timeframe.change(anchor)

not_full = vwaps.size() < vwapNum

var last_tf = bar_index
var tf_dif = 1

//Counter
if new_tf
    tf_dif := bar_index - last_tf
    last_tf := bar_index
    switch
        count == vwapNum => count := 0
        => count += 1

//Push values
if not_full and new_tf
    vwaps_num.push(volume * src)
    vwaps_den.push(volume)
    vwaps.push(src)

//Updating Values
for [idx,value] in vwaps
    if idx == count and new_tf
        vwaps_num.set(idx, volume * src)
        vwaps_den.set(idx, volume)
        vwaps.set(idx, src)
    else
        vwaps_num.set(idx, vwaps_num.get(idx) + volume * src)
        vwaps_den.set(idx, vwaps_den.get(idx) + volume)
        vwaps.set(idx, vwaps_num.get(idx) / vwaps_den.get(idx))

//---------------------------------------------------------------------------------------------------------------------}
//Displays
//---------------------------------------------------------------------------------------------------------------------{

//Levels
max = vwaps.percentile_linear_interpolation(maxPer)
hi = vwaps.percentile_linear_interpolation(hiPer)
med = vwaps.percentile_linear_interpolation(medPer)
lo = vwaps.percentile_linear_interpolation(loPer)
min = vwaps.percentile_linear_interpolation(minPer)

//Plots
p5 = plot(max, color = src == max ? na : maxColor, display = (maxTog?display.all:display.none), title = "Max % VWAP ", linewidth = maxWid)
p4 = plot(hi, color = dash() or new_tf?hiColor:bg_invis, display = (hiTog?display.all:display.none), title = "Upper % VWAP", linewidth = hiWid)
p3 = plot(med, color = medColor, display = (medTog?display.all:display.none), title = "Median % VWAP", linewidth = medWid)
p2 = plot(lo, color = dash() or new_tf?loColor:bg_invis, display = (loTog?display.all:display.none), title = "Lower % VWAP", linewidth = loWid)
p1 = plot(min, color = src == min ? na : minColor, display = (minTog?display.all:display.none), title = "Min % VWAP", linewidth = minWid)

//Fills
fill(p1,p3, useGrad?smooth(med,tf_dif):na, smooth(min,tf_dif), bg_invis, color.new(minColor,70))
fill(p5,p3, useGrad?smooth(max,tf_dif):na, smooth(med,tf_dif), color.new(maxColor,70), bg_invis) 

//Data Readout
plot(vwaps.size(), title = "VWAPs Generated", display = display.status_line, color = chart.fg_color)

//Anchors
bgcolor(new_tf and showAnchor ? color.new(color.gray, 80) : na, title = 'Anchor')

//---------------------------------------------------------------------------------------------------------------------}