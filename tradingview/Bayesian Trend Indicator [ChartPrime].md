// This Pine Script™ code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © ChartPrime

//@version=5
indicator('Bayesian Trend Indicator [ChartPrime]', shorttitle = "Bayesian Trend [ChartPrime]", overlay=true, max_labels_count = 100)

// ---------------------------------------------------------------------------------------------------------------------}
// 𝙐𝙎𝙀𝙍 𝙄𝙉𝙋𝙐𝙏𝙎

// ---------------------------------------------------------------------------------------------------------------------{
float source    = input(hlc3, title='Source', group = "Settings")
int length      = input.int(60, title="MA's Length", group = "Settings")

int gap_length  = input.int(20, "Gap Length Between Fast And Slow MA's", 
                             tooltip = "Determines the difference in lengths between the slow and fast moving averages. 
                             A higher gap length will increase the difference, potentially identifying stronger trend signals"
                             )
int gap         = input.int(10, "Gap Signals", minval = 10, 
                             tooltip = "Defines the gap used for the smoothed gradient signal function. 
                             This parameter affects the sensitivity of the trend signals by setting the number of bars used in the signal calculations."
                             )

color colorUp = #0fac16
color colorDn = #c51212


// ---------------------------------------------------------------------------------------------------------------------}
// 𝙄𝙉𝘿𝙄𝘾𝘼𝙏𝙊𝙍 𝘾𝘼𝙇𝘾𝙐𝙇𝘼𝙏𝙄𝙊𝙉𝙎
// ---------------------------------------------------------------------------------------------------------------------{
// Calculate moving averages
ema_  = ta.ema(source, length)
sma_  = ta.sma(source, length)
dema_ = ta.ema(2 * ta.ema(source, length) - ta.ema(ta.ema(source, length), length), length)
vwma_ = ta.vwma(source, length)

// Calculate faster moving averages with lower length
ema_fast  = ta.ema(source, length-gap_length)
sma_fast  = ta.sma(source, length-gap_length)
dema_fast = ta.ema(2 * ema_fast - ta.ema(ema_fast, length-gap_length), length-gap_length)
vwma_fast = ta.vwma(source, length-gap_length)

// Smoothed Gradient Signal Function 
sig(float src, gap)=>
    ta.ema(
     source >= src[gap]   ? 1   : 
     source >= src[gap-1] ? 0.9 :
     source >= src[gap-2] ? 0.8 :
     source >= src[gap-3] ? 0.7 :
     source >= src[gap-4] ? 0.6 :
     source >= src[gap-5] ? 0.5 :
     source >= src[gap-6] ? 0.4 :
     source >= src[gap-7] ? 0.3 :
     source >= src[gap-8] ? 0.2 :
     source >= src[gap-9] ? 0.1 :
      0, 4
      )

// Calculate trend for each faster moving average
ema_trend_fast  = sig(ema_fast, gap)
sma_trend_fast  = sig(sma_fast, gap)
dema_trend_fast = sig(dema_fast, gap)
vwma_trend_fast = sig(vwma_fast, gap)

// Calculate trend for each moving average
ema_trend       = sig(ema_, gap)
sma_trend       = sig(sma_, gap)
dema_trend      = sig(dema_, gap)
vwma_trend      = sig(vwma_, gap)

// Define prior probabilities using moving averages
prior_up   = (ema_trend + sma_trend + dema_trend + vwma_trend) / 4
prior_down = 1 - prior_up

// Define likelihoods using faster moving averages
likelihood_up   = (ema_trend_fast + sma_trend_fast + dema_trend_fast + vwma_trend_fast) / 4
likelihood_down = 1 - likelihood_up

// Calculate posterior probabilities using 𝘽𝙖𝙮𝙚𝙨❜ 𝙩𝙝𝙚𝙤𝙧𝙚𝙢
posterior_up =                  prior_up * likelihood_up 
                                         / 
               (prior_up * likelihood_up + prior_down * likelihood_down)
                 
if na(posterior_up)
    posterior_up := 0

// ---------------------------------------------------------------------------------------------------------------------}
// 𝙑𝙄𝙎𝙐𝘼𝙇𝙄𝙕𝘼𝙏𝙄𝙊𝙉
// ---------------------------------------------------------------------------------------------------------------------{
// Bar Color Trend
trend_col = posterior_up < 0.48 
 ? color.from_gradient(posterior_up, 0, 0.48, colorDn, color.new(chart.bg_color, 20)) 
 : posterior_up > 0.52 ? color.from_gradient(posterior_up, 0.52, 1, color.new(chart.bg_color, 20), colorUp) 
 : chart.bg_color


plotcandle(open, high, low, close, 
             color       = trend_col, 
             bordercolor = trend_col, 
             wickcolor   = trend_col
             )
barcolor(trend_col)

// Table
var table tbl = table.new(position.top_right, 10, 10)

add_val(col, row, col1, row1, txt, val, val1)=>
    table.cell(tbl, col, row, txt, text_color = chart.fg_color)

    table.cell(tbl, col1, row1, str.tostring(math.round(val, 2)), 
              text_color = color.from_gradient(val, 0, 1, colorDn, colorUp))
    table.cell(tbl, col1+1, row1, str.tostring(math.round(val1, 2)), 
              text_color = color.from_gradient(val1, 0, 1, colorDn, colorUp))

if barstate.islast
    table.cell(tbl, 0, 0, "乃𝙖𝙮𝙚𝙨𝙞𝙖𝙣  𝙏𝙧𝙚𝙣𝙙  𝙄𝙣𝙙𝙞𝙘𝙖𝙩𝙤𝗿", text_color = chart.fg_color, text_size = size.large)
    table.merge_cells(tbl, 0, 0, 3, 0)
    table.cell(tbl, 0, 1, "𝗣𝗿𝗼𝗯𝗮𝗯𝗶𝗹𝗶𝘁𝘆 𝗼𝗳 𝗨𝗽 𝗧𝗿𝗲𝗻𝗱:", text_color = chart.fg_color, text_size = size.normal)
    table.cell(tbl, 1, 1, str.tostring(posterior_up*100, format = format.percent), 
                 text_color = color.from_gradient(posterior_up, 0, 1, colorDn, colorUp), 
                 text_size  = posterior_up>0.5? size.large : size.normal)

    table.merge_cells(tbl, 1, 1, 3, 1)
    table.cell(tbl, 0, 2)

    table.cell(tbl, 0, 3, "Moving Average", text_color = #4a4f5e)
    table.cell(tbl, 1, 3, "Slow",           text_color = #4a4f5e)
    table.cell(tbl, 2, 3, "Fast",           text_color = #4a4f5e)

    add_val(0, 4, 1, 4, "SMA", sma_trend, sma_trend_fast)
    add_val(0, 5, 1, 5, "EMA", ema_trend, ema_trend_fast)
    add_val(0, 6, 1, 6, "DEMA", dema_trend, dema_trend_fast)
    add_val(0, 7, 1, 7, "VWMA", vwma_trend, vwma_trend_fast)

// Probability Labels   FROM 0 TO 1 (0%-100%)
label.new(
     x         = bar_index,
     y         = posterior_up > 0.5 ? high : low,
     text      = str.tostring(math.round(posterior_up,2)), 
     style     = posterior_up > 0.5 ? label.style_label_down : label.style_label_up, 
     textcolor = color.from_gradient(posterior_up, 0, 1, colorDn, colorUp),
     color     = color(na)
     )

// Signals
plotchar(ta.crossover(posterior_up, 0.5), 
         char     = "◆", 
         location = location.belowbar, 
         size     = size.tiny, 
         color    = color.new(colorUp, 5)
         )
plotchar(ta.crossunder(posterior_up, 0.5), 
         char     = "◆", 
         location = location.abovebar,
         size     = size.tiny, 
         color    = color.new(colorDn, 5)
         )

// △▽

// ---------------------------------------------------------------------------------------------------------------------}