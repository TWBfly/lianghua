// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Fair Value Gaps Mitigation Oscillator [LuxAlgo]" ,shorttitle = "LuxAlgo - FVG Mitigation Oscillator", explicit_plot_zorder = true)
//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
fvg_len = input.int(10, title = "FVG Lookback")

//Style
green =  input.color(#089981, title = "Bullish Color", group = "Style")
red = input.color(#f23645, title = "Bearish Color", group = "Style")
net_col = input.color(color.gray, title = "Net Color", group = "Style")
showNewFvg = input(true, "Show New FVG's Ratio", group = 'Style')
showFill = input(true, 'Show Gradient Areas', group = 'Style')

//---------------------------------------------------------------------------------------------------------------------}
//UDT
//---------------------------------------------------------------------------------------------------------------------{
type fvg
    float top
    float bot
    float tot

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{
fvg_manage(_ary, _bias) =>
    for [i,v] in _ary
        top = v.top
        bot = v.bot

        bot_x_in = close > bot and close < top and close[1] <= bot and _bias == -1  
        top_x_in = close < top and close > bot and close[1] >= top and _bias == 1  
        full_x_up = close > top and _bias == -1  
        full_x_down = close < bot and _bias == 1

        if full_x_up or full_x_down
            v.bot := close
            v.top := close

        if bot_x_in
            v.bot := close

        if top_x_in
            v.top := close
        
    float per_sum = 0 // Percent of Total FVG Remaining
    float raw_sum = 0 // Raw Value Remaining
    for i in _ary
        per_sum += (i.top - i.bot)/i.tot
        raw_sum += (i.top - i.bot)
    
    [per_sum * _bias, raw_sum]

//---------------------------------------------------------------------------------------------------------------------}
//Constants
//---------------------------------------------------------------------------------------------------------------------{
//FVG Detection
fvg_up = low > high[2] and close[1] > high[2] 
fvg_down = high < low[2] and close[1] < low[2]

//---------------------------------------------------------------------------------------------------------------------}
//Calculations
//---------------------------------------------------------------------------------------------------------------------{
var up_ary = array.new<fvg>(na)
var down_ary = array.new<fvg>(na)
float fvg_width = 0

if fvg_up
    up_ary.push(fvg.new(low, high[2], math.abs(low - high[2])))
    fvg_width := math.abs(low - high[2])

if fvg_down
    down_ary.push(fvg.new(low[2], high, math.abs(low[2] - high)))
    fvg_width := math.abs(low[2] - high)

//Array Size Management
if up_ary.size() > fvg_len
    up_ary.shift()

if down_ary.size() > fvg_len
    down_ary.shift()

[up_per,up_raw] = fvg_manage(up_ary, 1)
[down_per,down_raw] = fvg_manage(down_ary, -1)

//Scaled Sums
up_sum = up_per / fvg_len
down_sum = down_per / fvg_len
net = up_sum + down_sum

//Ratio of current FVG to directional Raw Sum
ratio = fvg_up ? fvg_width / up_raw * up_sum 
  : fvg_down ? fvg_width / down_raw * down_sum 
  : na

//---------------------------------------------------------------------------------------------------------------------}
//Display
//---------------------------------------------------------------------------------------------------------------------{
disp_0 = (up_sum != 0 and down_sum != 0) or (up_sum == 0 and up_sum[1] != 0) or (down_sum == 0 and down_sum[1] != 0)
plot(0, color = disp_0 ? color.gray : color.new(chart.bg_color,100), editable = false, display = display.pane)

hline(0.5, title = "Over-Bought Level", color = color.gray)
hline(-0.5, title = "Over-Sold Level", color = color.gray)

us = plot(up_sum, color = green, title = "Bullish")
ds = plot(down_sum, color = red, title = "Bearish")
zl = plot(0, display = display.none, editable = false)

fill(us, zl, 1, 0, green, color.new(chart.bg_color,100), display = showFill ? display.all : display.none)
fill(ds, zl, 0, -1, color.new(chart.bg_color,100), red, display = showFill ? display.all : display.none)

hline(0, title = "Zero",color = chart.bg_color, linestyle = hline.style_dotted, linewidth = 2, editable = false)

disp_net = (net == up_sum and net[1] != up_sum[1]) or (net == down_sum and net[1] != down_sum[1]) or ((net != up_sum) and (net != down_sum))

plot(net, color = disp_net ? net_col : color.new(chart.bg_color,100), title = "Net")
 
plot(showNewFvg ? ratio : na, "New FVG Ratio"
  , color = ratio > 0 ? green : red
  , editable = false
  , style = plot.style_histogram)

plot(not showNewFvg ? na : ratio > 0 ? up_sum : ratio < 0 ? down_sum : na
  , color = ratio > 0 ? color.new(green,80) : color.new(red,80)
  , style = plot.style_histogram
  , editable = false
  , display = display.pane)

plotchar(not showNewFvg ? na : ratio > 0 ? up_sum / 2 : ratio < 0 ? down_sum / 2 : na
  , location = location.absolute
  , char = "-"
  , color = ratio > 0 ? green : red
  , size = size.tiny
  , editable = false
  , display = display.pane)

//---------------------------------------------------------------------------------------------------------------------}