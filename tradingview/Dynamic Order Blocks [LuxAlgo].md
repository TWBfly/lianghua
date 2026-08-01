// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Dynamic Order Blocks [LuxAlgo]", "LuxAlgo - Dynamic Order Blocks", overlay = true)
//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
length   = input.int(10, 'Swing Lookback', minval = 3)
useBody  = input(true, 'Use Candle Body')

//Sweeps
showBullSweep = input(true, 'Dynamic Bullish Sweeps', inline = 'inline1', group = 'Dynamic Sweeps')
bullSweepCss  = input(#089981, '', inline = 'inline1', group = 'Dynamic Sweeps')

showBearSweep = input(true, 'Dynamic Bearish Sweeps', inline = 'inline2', group = 'Dynamic Sweeps')
bearSweepCss  = input(#f23645, '', inline = 'inline2', group = 'Dynamic Sweeps')

//---------------------------------------------------------------------------------------------------------------------}
//UDT
//---------------------------------------------------------------------------------------------------------------------{
type ob
    float top = na
    float btm = na

type swing
    float y = na
    int   x = na
    bool  crossed = false

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{
swings(len)=>
    var os = 0
    var swing top = swing.new(na, na)
    var swing btm = swing.new(na, na)
    
    upper = ta.highest(len)
    lower = ta.lowest(len)

    os := high[len] > upper ? 0 
      : low[len] < lower ? 1 : os

    if os == 0 and os[1] != 0
        top := swing.new(high[length], bar_index[length])
    
    if os == 1 and os[1] != 1
        btm := swing.new(low[length], bar_index[length])

    [top, btm]

//---------------------------------------------------------------------------------------------------------------------}
//Detect Swings
//---------------------------------------------------------------------------------------------------------------------{
n = bar_index

[top, btm] = swings(length)
max = useBody ? math.max(close, open) : high
min = useBody ? math.min(close, open) : low

//---------------------------------------------------------------------------------------------------------------------}
//Bullish OB
//---------------------------------------------------------------------------------------------------------------------{
var bullish_ob = array.new<ob>(0)
bull_break_conf = 0

if close > top.y and not top.crossed
    top.crossed := true

    minima = max[1]
    maxima = min[1]

    for i = 1 to (n - top.x)-1
        minima := math.min(min[i], minima)
        maxima := minima == min[i] ? max[i] : maxima

    bullish_ob.unshift(ob.new(maxima, minima))

if bullish_ob.size() > 0
    for i = bullish_ob.size()-1 to 0
        element = bullish_ob.get(i)
    
        if math.min(close, open) < element.btm
            bullish_ob.remove(i)

bull_top = bullish_ob.size() > 0 ? bullish_ob.get(0).top : na
bull_btm = bullish_ob.size() > 0 ? bullish_ob.get(0).btm : na

//---------------------------------------------------------------------------------------------------------------------}
//Bearish OB
//---------------------------------------------------------------------------------------------------------------------{
var bearish_ob = array.new<ob>(0)
bear_break_conf = 0

if close < btm.y and not btm.crossed
    btm.crossed := true

    minima = min[1]
    maxima = max[1]

    for i = 1 to (n - btm.x)-1
        maxima := math.max(max[i], maxima)
        minima := maxima == max[i] ? min[i] : minima

    bearish_ob.unshift(ob.new(maxima, minima))

if bearish_ob.size() > 0
    for i = bearish_ob.size()-1 to 0
        element = bearish_ob.get(i)
 
        if math.max(close, open) > element.top
            bearish_ob.remove(i)

bear_top = bearish_ob.size() > 0 ? bearish_ob.get(0).top : na
bear_btm = bearish_ob.size() > 0 ? bearish_ob.get(0).btm : na

avg = math.avg(bear_top, bull_btm)

//---------------------------------------------------------------------------------------------------------------------}
//Plot
//---------------------------------------------------------------------------------------------------------------------{
//Bull
plot_bull_top = plot(bull_top, 'Bullish OB Top'
  , bull_btm != bull_btm[1] ? na : color.new(#089981, 100)
  , style = plot.style_linebr)

plot_bull_btm = plot(bull_btm, 'Bullish OB Bottom'
  , bull_btm != bull_btm[1] ? na : #089981
  , style = plot.style_linebr)

//Bear
plot_bear_top = plot(bear_top, 'Bearish OB Top'
  , bear_top != bear_top[1] ? na : #f23645
  , style = plot.style_linebr)

plot_bear_btm = plot(bear_btm, 'Bearish OB Bottom'
  , bear_top != bear_top[1] ? na : color.new(#f23645, 100)
  , style = plot.style_linebr)

plot(avg, 'Average'
  , #ff5d00
  , style = plot.style_linebr)

//Fills
fill(plot_bull_top, plot_bull_btm, title = 'Bullish OB Area'
  , color = bull_btm != bull_btm[1] ? na : color.new(#089981, 80))

fill(plot_bear_top, plot_bear_btm, title = 'Bearish OB Area'
  , color = bear_top != bear_top[1] ? na : color.new(#f23645, 80))

//Dynamic Sweeps
plotcandle(bull_btm, bull_btm, low, low
  , color = color(na)
  , wickcolor = color(na)
  , bordercolor = low < bull_btm and close > bull_btm ? bullSweepCss : color(na)
  , display = showBullSweep ? display.all - display.status_line : display.none
  , editable = false)

plotcandle(bear_top, bear_top, high, high
  , color = color(na)
  , wickcolor = color(na)
  , bordercolor = high > bear_top and close < bear_top ? bearSweepCss : color(na)
  , display = showBearSweep ? display.all - display.status_line : display.none
  , editable = false)

//-----------------------------------------------------------------------------}