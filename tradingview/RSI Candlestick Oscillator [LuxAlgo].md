// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("RSI Candlestick Oscillator [LuxAlgo]", "LuxAlgo - RSI Candlestick Oscillator", overlay = false, max_lines_count = 500)

len = input.int(14, minval = 2, title = "RSI Length", group = "RSI Candles")
src = close
upper = input.float(70, title = "Overbought", group = "RSI Candles")
lower = input.float(30, title = "Oversold", group = "RSI Candles")
cUpColor = input.color(#089981, title = "Up Candle Color", group = "RSI Candles")
cDownColor = input.color(#f23645, title = "Down Candle Color", group = "RSI Candles")
pS = input.bool(false, title = "Scale Open for Chart Accuracy", group = "RSI Candles", tooltip = "Places the candle open accurately relative to the previous candle close rather than scaling based on current RSI value. This produces a candlestick that is closer the on-chart candle, but does not effect the High, Low, or Close Values.")


showOnChart = input.bool(true, title = "Show on Chart", group = "Divergence")
pivWidth = input.int(10, title = "Divergence Length", group = "Divergence")
bullColor = input.color(#089981, title = "Bearish Color", group = "Divergence")
bearColor = input.color(#f23645, title = "Bullish Color", group = "Divergence")

regTog = input.bool(true, title = "Regular Divergence", inline = "reg", group = "Divergence")
hiddenTog = input.bool(true, title = "Hidden Divergence", inline = "hidden", group = "Divergence")
regStyle = input.string("___", title = "", options = ["___","- - -",". . ."], inline = "reg", group = "Divergence")
hiddenStyle = input.string(". . .", title = "", options = ["___","- - -",". . ."], inline = "hidden", group = "Divergence")

restrict = input.bool(true, title = "Use Divergence Filter", group = "Divergence", tooltip = "Requires an RSI divergence point to be outside of the RSI Upper or Lower. This is intended to filter out unwanted divergence detections, to focus around divergences occuring at or beyond the extremes.")

showChannel = input.bool(false, title = "Show RSI Channel on Chart", group = "RSI Channel")
channelColor = input.color(color.black, title = "Channel Color", group = "RSI Channel")



//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{

linestyle(_input) =>
    _input == "___"?line.style_solid:
     _input == "- - -"?line.style_dashed:
     _input == ". . ."?line.style_dotted:
     na

keep_in_range(_val,_max,_min) => math.min(math.max(_val,_min),_max)

//---------------------------------------------------------------------------------------------------------------------}
//UDTs
//---------------------------------------------------------------------------------------------------------------------{

type pb
    float price
    int bar

//---------------------------------------------------------------------------------------------------------------------}
//Variables
//---------------------------------------------------------------------------------------------------------------------{

var pb rsi_h_p1 = pb.new(na,na)
var pb rsi_h_p2 = pb.new(na,na)

var pb rsi_l_p1 = pb.new(na,na)
var pb rsi_l_p2 = pb.new(na,na)

var pb c_h_p1 = pb.new(na,na)
var pb c_h_p2 = pb.new(na,na)

var pb c_l_p1 = pb.new(na,na)
var pb c_l_p2 = pb.new(na,na)

//---------------------------------------------------------------------------------------------------------------------}
//Calcs
//---------------------------------------------------------------------------------------------------------------------{

rsi = ta.rsi(src,len)

rsi_hst = ta.highest(rsi,len)
rsi_lst = ta.lowest(rsi,len)

src_hst = ta.highest(src,len)
src_lst = ta.lowest(src,len)
 
rsi_rng = rsi_hst - rsi_lst
src_rng = src_hst - src_lst

dif = src_rng / rsi_rng
src_dif = rsi_rng / src_rng

rsi_mid = math.avg(upper,lower)

chart_upper = close + ((upper - rsi) * dif)
chart_lower = close + ((lower - rsi) * dif)
chart_mid = math.avg(chart_upper,chart_lower)

h_rsi = keep_in_range(rsi_mid + ((high - chart_mid) / dif),100,0)
l_rsi = keep_in_range(rsi_mid + ((low - chart_mid) / dif),100,0)
c_rsi = keep_in_range(rsi_mid + ((close - chart_mid) / dif),100,0)

rsi_scaled_open = keep_in_range(rsi_mid + ((open - chart_mid) / dif),100,0)
prev_scaled_open = keep_in_range(rsi_mid[1] + ((open - chart_mid[1]) / dif[1]),100,0)
o_rsi = pS ? prev_scaled_open : rsi_scaled_open


rg_color = close > open ? cUpColor : close < open ? cDownColor : color.gray

rsi_piv_h = ta.pivothigh(h_rsi,pivWidth,pivWidth)
rsi_piv_l = ta.pivotlow(l_rsi,pivWidth,pivWidth)

if not na(rsi_piv_h)
    rsi_h_p1 := rsi_h_p2
    rsi_h_p2 := pb.new(rsi_piv_h,bar_index-pivWidth)
    c_h_p1 := c_h_p2
    c_h_p2 := pb.new(high[pivWidth],bar_index-pivWidth)

if not na(rsi_piv_l)
    rsi_l_p1 := rsi_l_p2
    rsi_l_p2 := pb.new(rsi_piv_l,bar_index-pivWidth)
    c_l_p1 := c_l_p2
    c_l_p2 := pb.new(low[pivWidth],bar_index-pivWidth)

//---------------------------------------------------------------------------------------------------------------------}
//Divergences
//---------------------------------------------------------------------------------------------------------------------{

rsi_h_up = rsi_h_p1.price < rsi_h_p2.price
rsi_h_down = rsi_h_p1.price > rsi_h_p2.price

rsi_l_up = rsi_l_p1.price < rsi_l_p2.price
rsi_l_down = rsi_l_p1.price > rsi_l_p2.price

c_h_up = c_h_p1.price < c_h_p2.price
c_h_down = c_h_p1.price > c_h_p2.price

c_l_up = c_l_p1.price < c_l_p2.price
c_l_down = c_l_p1.price > c_l_p2.price

r_bull = c_l_down and rsi_l_up and (restrict ? rsi_l_p1.price < lower : true)
r_bear = c_h_up and rsi_h_down and (restrict ? rsi_h_p1.price > upper : true)

h_bull = c_l_up and rsi_l_down and (restrict ? rsi_l_p2.price < lower : true)
h_bear = c_h_down and rsi_h_up and (restrict ? rsi_h_p2.price > upper : true)


if not na(rsi_piv_h) and r_bear and regTog
    if showOnChart
        line.new(c_h_p1.bar,c_h_p1.price,c_h_p2.bar,c_h_p2.price, color = bearColor, style = linestyle(regStyle), force_overlay = true)
    line.new(rsi_h_p1.bar,rsi_h_p1.price,rsi_h_p2.bar,rsi_h_p2.price, color = bearColor, style = linestyle(regStyle))
if not na(rsi_piv_l) and h_bear and hiddenTog
    if showOnChart
        line.new(c_h_p1.bar,c_h_p1.price,c_h_p2.bar,c_h_p2.price, color = bearColor, style = linestyle(hiddenStyle), force_overlay = true)
    line.new(rsi_h_p1.bar,rsi_h_p1.price,rsi_h_p2.bar,rsi_h_p2.price, color = bearColor, style = linestyle(hiddenStyle))

if not na(rsi_piv_l) and r_bull and regTog
    if showOnChart
        line.new(c_l_p1.bar,c_l_p1.price,c_l_p2.bar,c_l_p2.price, color = bullColor, style = linestyle(regStyle), force_overlay = true)
    line.new(rsi_l_p1.bar,rsi_l_p1.price,rsi_l_p2.bar,rsi_l_p2.price, color = bullColor, style = linestyle(regStyle))
if not na(rsi_piv_h) and h_bull and hiddenTog
    if showOnChart
        line.new(c_l_p1.bar,c_l_p1.price,c_l_p2.bar,c_l_p2.price, color = bullColor, style = linestyle(hiddenStyle), force_overlay = true)
    line.new(rsi_l_p1.bar,rsi_l_p1.price,rsi_l_p2.bar,rsi_l_p2.price, color = bullColor, style = linestyle(hiddenStyle))

//---------------------------------------------------------------------------------------------------------------------}
//Display
//---------------------------------------------------------------------------------------------------------------------{

plotcandle(o_rsi,h_rsi,l_rsi,c_rsi,color = rg_color, bordercolor = rg_color, wickcolor = rg_color, title = "RSI Candles")
hline(upper, title = "OverBought", color = color.new(chart.fg_color,25))
hline(lower, title = "OverSold", color = color.new(chart.fg_color,25))
hline((upper+lower)/2, title = "Middle")

plot(chart_upper, force_overlay = true, color = channelColor, title = "Channel OB", display = showChannel?display.all:display.none)
plot(chart_lower, force_overlay = true, color = channelColor, title = "Channel OS", display = showChannel?display.all:display.none)
plot(chart_mid, force_overlay = true, title = "Channel Mid", color = channelColor, display = display.none, style = plot.style_circles)

//---------------------------------------------------------------------------------------------------------------------}