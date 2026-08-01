// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Internal Candle Strength [LuxAlgo]', 'LuxAlgo - Internal Candle Strength', overlay=true, max_lines_count = 500, max_boxes_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
timeframeInput  = input.timeframe(  '1',  'Timeframe')
sizeInput       = input(            20.,  'Row Size', inline = 'size')
autoInput       = input.bool(       true, 'Auto',     inline = 'size')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
var table t_able = table.new(position.bottom_right,2,2
     , bgcolor      = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color  = #373a46
     , frame_width  = 1)

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
ohlc()=> [open, high, low, close]

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
volatility    = math.round_to_mintick(0.1 * ta.atr(200))
parsedSize    = autoInput ? volatility : sizeInput
n             = bar_index
idx           = math.max(math.round((high - low) / parsedSize), 1)
[o, h, l, c]  = request.security_lower_tf(syminfo.tickerid, timeframeInput, ohlc())

min           = low
max           = low
float avg     = na 
color css     = na

for i = 0 to idx-1
    max += (high - low) / idx
    num = array.new<float>()
    den = array.new<float>()

    for [index, value] in o
        if array.get(h, index) > min and array.get(l, index) < max
            diff = array.get(c, index) - array.get(o, index)

            array.push(num, diff)
            array.push(den, math.abs(diff))

    strength  = 50 * (array.sum(num) / array.sum(den)) + 50
    css       := color.from_gradient(strength, 0, 100, color.red, color.teal)

    box.new(n, max, n+1, min
      , text = str.tostring(strength, format.percent)
      , text_color = css
      , bgcolor = color.new(#5d606b, 80)
      , border_color = na)

    line.new(n, min, n+1, min, color = css)    
    
    min := max

line.new(n, min, n+1, min, color = css)

plotcandle(open, math.max(close, open), math.min(close, open), open
  , bordercolor = #00000000
  , color = #00000000
  , wickcolor = close > open ? color.teal : color.red)

if barstate.islast
    t_able.cell(0,0,'Current Row Size',text_color = color.new(color.white,50))
    t_able.cell(0,1,'Optimal Row Size',text_color = color.new(color.white,50))
    t_able.cell(1,0,str.tostring(parsedSize),text_color = color.new(color.white,50))
    t_able.cell(1,1,str.tostring(volatility),text_color = color.new(color.white,50))
    
//---------------------------------------------------------------------------------------------------------------------}