// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Candlestick Channels [LuxAlgo]", overlay = true, max_labels_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
length = input.int(14, 'Trend Length'
  , minval = 0)

alpha = input.float(50, 'Convergence'
  , minval = 0
  , maxval = 100)

smooth = input.int(7, 'Smooth'
  , minval = 1)

//Patterns
enable_hammer = input(true, 'Hammer'
  , group = 'patterns')

enable_ihammer = input(true, 'Inverted Hammer'
  , group = 'patterns')

enable_shooting = input(true, 'Shooting Star'
  , group = 'patterns')

enable_hanging = input(true, 'Hanging Man'
  , group = 'patterns')

enable_bulleng = input(false, 'Bullish Engulfing'
  , group = 'patterns')

enable_beareng = input(false, 'Bearish Engulfing'
  , group = 'patterns')

enable_wm = input(true, 'White Marubozu'
  , group = 'patterns')

enable_bm = input(true, 'Black Marubozu'
  , group = 'patterns')
  
//Style
bull_css = input(#0cb51a, 'Bullish Color'
  , group = 'Style')

avg_css = input(#ff5d00, 'Average Color'
  , group = 'Style')

bear_css = input(#ff1100, 'Bearish Color'
  , group = 'Style')

fade = input.int(200, 'Fading Period'
  , minval = 1)

//-----------------------------------------------------------------------------}
//Variables/Functions
//-----------------------------------------------------------------------------{
n = bar_index
o = open,h = high,l = low,c = close

atr = ta.atr(20) / 2 
st = ta.stoch(c, c, c, length)
downtrend = st < 50
uptrend = st > 50

d = math.abs(c - o)

//Label
lbl(y, txt, direction, tlt)=>
    label.new(n, y, txt
          , size = size.tiny
          , style = direction == 1 ? label.style_label_up : label.style_label_down
          , color = direction == 1 ? bull_css : bear_css
          , textcolor = color.white
          , tooltip = tlt)

//-----------------------------------------------------------------------------}
//Tooltips
//-----------------------------------------------------------------------------{
var hammer_tlt = "The hammer candlestick pattern is formed of a short body with a long lower wick, and is found at the bottom of a downward trend."
  + "\n" + "\nA hammer shows that although there were selling pressures during the day, ultimately a strong buying pressure drove the price back up." 

var ihammer_tlt = "The inverted hammer is a similar pattern than the hammer pattern. The only difference being that the upper wick is long, while the lower wick is short."
  + "\n" + "\nIt indicates a buying pressure, followed by a selling pressure that was not strong enough to drive the market price down. The inverse hammer suggests that buyers will soon have control of the market."

var bulleng_tlt = "The bullish engulfing pattern is formed of two candlesticks. The first candle is a short red body that is completely engulfed by a larger green candle"
  + "\n" + "\nThough the second day opens lower than the first, the bullish market pushes the price up, culminating in an obvious win for buyers"

var wm_tlt = "The white marubozu is a single candles formation formed after a downtrend and indicating a bullish reversal."
  + "\n" + "\nThis candlestick has a long bullish body with no upper or lower shadows, reflecting a strong buying pressure."
  
var shooting_tlt = "The shooting star is the same shape as the inverted hammer, but is formed in an uptrend: it has a small lower body, and a long upper wick."
  + "\n" + "\nUsually, the market will gap slightly higher on opening and rally to an intra-day high before closing at a price just above the open – like a star falling to the ground."

var hanging_tlt = "The hanging man is the bearish equivalent of a hammer; it has the same shape but forms at the end of an uptrend."
  + "\n" + "\nIt indicates that there was a significant sell-off during the day, but that buyers were able to push the price up again. The large sell-off is often seen as an indication that the bulls are losing control of the market."

var beareng_tlt = "A bearish engulfing pattern occurs at the end of an uptrend. The first candle has a small green body that is engulfed by a subsequent long red candle."
  + "\n" + "\nIt signifies a peak or slowdown of price movement, and is a sign of an impending market downturn. The lower the second candle goes, the more significant the trend is likely to be."

var bm_tlt = "The black marubozu is a single candles formation formed after an uptrend and indicating a bearish reversal."
  + "\n" + "\nThis candlestick has a long bearish body with no upper or lower shadows, reflecting a strong selling pressure."

//-----------------------------------------------------------------------------}
//Pattern Rules
//-----------------------------------------------------------------------------{
hammer = downtrend and math.min(o, c) - l > 2 * d and h - math.max(c, o) < d / 4
ihammer = downtrend and h - math.max(o, c) > 2 * d and math.min(c, o) - l < d / 4

shooting = uptrend and h - math.max(o, c) > 2 * d and math.min(c, o) - l < d / 4
hanging = uptrend and math.min(o, c) - l > 2 * d and h - math.max(c, o) < d / 4

bulleng = downtrend and c > o and c[1] < o[1] and c > o[1] and d > atr
beareng = uptrend and c < o and c[1] > o[1] and c < o[1] and d > atr

wm = c > o and h - math.max(o, c) + math.min(o, c) - l < d / 10 and d > atr and downtrend[1]
bm = c < o and h - math.max(o, c) + math.min(o, c) - l < d / 10 and d > atr and uptrend[1]

//-----------------------------------------------------------------------------}
//Channel
//-----------------------------------------------------------------------------{
var max = h
var min = l

//Bullish Patterns
if hammer and enable_hammer
    max += alpha / 100 * (c - max)
    lbl(low, 'H', 1, hammer_tlt)
    
if ihammer and enable_ihammer
    max += alpha / 100 * (c - max)
    lbl(low, 'IH', 1, ihammer_tlt)

if bulleng and enable_bulleng
    max += alpha / 100 * (c - max)
    lbl(low, 'BE', 1, bulleng_tlt)

if wm and enable_wm
    max += alpha / 100 * (c - max)
    lbl(low, 'WM', 1, wm_tlt)

//Bearish Patterns
if shooting and enable_shooting
    min += alpha / 100 * (c - min)
    lbl(high, 'SS', 0, shooting_tlt)

if hanging and enable_hanging
    min += alpha / 100 * (c - min)
    lbl(high, 'HM', 0, hanging_tlt)

if beareng and enable_beareng
    min += alpha / 100 * (c - min)
    lbl(high, 'BE', 0, beareng_tlt)

if bm and enable_bm
    min += alpha / 100 * (c - min)
    lbl(high, 'BM', 0, bm_tlt)

max := math.max(c, max)
min := math.min(c, min)

smooth_max = ta.ema(max, smooth)
smooth_min = ta.ema(min, smooth)
avg = math.avg(smooth_max, smooth_min)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
var os = 0
os := c > smooth_max ? 1 : c < smooth_min ? 0 : os

var fade_max = 0
fade_max := os == 0 ? fade_max + 1 : 0

var fade_min = 0
fade_min := os == 1 ? fade_min + 1 : 0

plot_0 = plot(smooth_max, 'Upper', bull_css)

plot_1 = plot(avg, 'Average', avg_css)

plot_2 = plot(smooth_min, 'Lower', bear_css)

css1 = color.from_gradient(fade_max, 0, fade, color.new(bull_css, 80), color.new(bull_css, 100))
fill(plot_0, plot_1, css1)

css2 = color.from_gradient(fade_min, 0, fade, color.new(bear_css, 80), color.new(bear_css, 100))
fill(plot_1, plot_2, css2)

//-----------------------------------------------------------------------------}