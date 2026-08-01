// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Omni-Flow Consensus [LuxAlgo]", "LuxAlgo - Omni-Flow", overlay = false, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
group_calc              = "Core Logic"
flowLenInput            = input.int(24, "Flow Sensitivity", minval = 5, group = group_calc)
spectralLenInput        = input.int(10, "Spectral Smoothing", minval = 1, group = group_calc)
boostInput              = input.float(1.5, "Signal Boost", minval = 1.0, maxval = 5.0, step = 0.1, group = group_calc)

group_signals           = "Signal Filtering"
smoothSignalsInput      = input.bool(true, "Smooth Signals (Reduce Noise)", group = group_signals)
strictnessInput         = input.int(3, "Signal Strictness", minval = 1, maxval = 10, group = group_signals)
thresholdInput          = input.float(15.0, "Momentum Threshold", minval = 0.0, maxval = 50.0, group = group_signals)

group_visual            = "Aesthetics"
colorCandlesInput       = input.bool(true, "Gradient Candle Coloring", group = group_visual)
glowIntensityInput      = input.int(60, "Glow Intensity", minval = 0, maxval = 100, group = group_visual)
showDashboardInput      = input.bool(true, "Display Flow Dashboard", group = group_visual)
dashPosInput            = input.string(TOP_RIGHT, "Position", options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT], group = group_visual)
dashSizeInput           = input.string(SMALL, "Size", options = [TINY, SMALL, NORMAL], group = group_visual)

group_color             = "Color Settings"
bullColorInput          = input.color(#089981, "Bullish", inline = "bull", group = group_color)
bullGlowInput           = input.color(#00ffd5, "Glow", inline = "bull", group = group_color)
bearColorInput          = input.color(#f23645, "Bearish", inline = "bear", group = group_color)
bearGlowInput           = input.color(#ff0055, "Glow", inline = "bear", group = group_color)
neutralColorInput       = input.color(#434651, "Neutral", inline = "neutral", group = group_color)
neutralGlowInput        = input.color(#787b86, "Glow", inline = "neutral", group = group_color)

group_dash_color        = "Dashboard Colors"
dashBgColorInput        = input.color(#161616, "Background", group = group_dash_color)
dashBorderColorInput    = input.color(#2E2E2E, "Borders", group = group_dash_color)
dashHeaderColorInput    = input.color(#808080, "Headers", group = group_dash_color)
dashDataColorInput      = input.color(#DBDBDB, "Data", group = group_dash_color)

// Map inputs to constants for cleaner logic
BULL_GLOW               = bullGlowInput
BULL_CORE               = bullColorInput
BEAR_GLOW               = bearGlowInput
BEAR_CORE               = bearColorInput
NEUTRAL_CORE            = neutralColorInput
NEUTRAL_GLOW            = neutralGlowInput
DATA                    = dashDataColorInput
HEADERS                 = dashHeaderColorInput
BACKGROUND              = dashBgColorInput
BORDERS                 = dashBorderColorInput

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
asf(float src, int len) =>
    float alpha = 2.0 / (len + 1)
    float diff  = ta.atr(len)
    float adaptive_alpha = math.min(1.0, alpha * (math.abs(src - src[1]) / (diff + syminfo.mintick)))
    float out = 0.0
    out := na(out[1]) ? src : out[1] + adaptive_alpha * (src - out[1])
    out

cell(table t, int c, int r, string txt, color clr = #FFFFFF, string halign = text.align_right) => 
    t.cell(c, r, txt, text_color = clr, text_size = dashSizeInput == TINY ? size.tiny : dashSizeInput == SMALL ? size.small : size.normal, text_halign = halign)

divider(table t, int row, int lastCol) =>    
    t.merge_cells(0, row, lastCol, row)
    t.cell(0, row, "━━━━━━━━━━━━━━━━━━━━━━", text_color = BORDERS, text_size = size.tiny, text_halign = text.align_center)

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
smart_vol    = not na(volume) and volume > 0 ? volume : ta.tr
vol_pressure = (close - open) / (math.max(high - low, syminfo.mintick)) * smart_vol
fpi_raw      = ta.sma(vol_pressure, flowLenInput)

fpi_highest = ta.highest(fpi_raw, flowLenInput * 2)
fpi_lowest  = ta.lowest(fpi_raw, flowLenInput * 2)
fpi_range   = math.max(fpi_highest - fpi_lowest, syminfo.mintick)
fpi_norm    = ((fpi_raw - fpi_lowest) / fpi_range * 200) - 100

boosted_flow = math.sign(fpi_norm) * math.pow(math.abs(fpi_norm) / 100, 1 / boostInput) * 100

flow_main    = asf(boosted_flow, spectralLenInput)
flow_signal  = ta.ema(flow_main, 5)

is_bullish   = flow_main > 0
is_trending  = math.abs(flow_main) > 50

raw_cross_up = ta.crossover(flow_main, flow_signal)
raw_cross_dn = ta.crossunder(flow_main, flow_signal)
bull_confirm = ta.barssince(raw_cross_up) < strictnessInput and flow_main > flow_signal
bear_confirm = ta.barssince(raw_cross_dn) < strictnessInput and flow_main < flow_signal

is_impulse_bull = smoothSignalsInput ? ta.crossover(ta.barssince(not bull_confirm), strictnessInput - 1) and flow_main > thresholdInput : raw_cross_up and is_bullish
is_impulse_bear = smoothSignalsInput ? ta.crossover(ta.barssince(not bear_confirm), strictnessInput - 1) and flow_main < -thresholdInput : raw_cross_dn and not is_bullish

regime_str = not is_trending ? "ACCUMULATION" : is_bullish ? "BULLISH FLOW" : "BEARISH FLOW"

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
core_clr = not is_trending ? NEUTRAL_CORE : is_bullish ? BULL_CORE : BEAR_CORE
glow_clr = not is_trending ? NEUTRAL_GLOW : is_bullish ? BULL_GLOW : BEAR_GLOW

// Zero Zone
z_u = plot(10, "Zero Zone U", color.new(chart.fg_color, 100))
z_d = plot(-10, "Zero Zone D", color.new(chart.fg_color, 100))
fill(z_u, z_d, color.new(NEUTRAL_GLOW, 92), "Zero Center Highlight")
plot(0, "Zero Axis", color.new(chart.fg_color, 50), 2, plot.style_line)

// Main Flow Lines
p_main = plot(flow_main, "Omni-Flow Main", core_clr, 4)
p_sig  = plot(flow_signal, "Signal Line", color.new(core_clr, 60), 1)

// Glow Bands
u2 = plot(90, "OB Outer", color.new(glow_clr, 95))
u1 = plot(70, "OB Inner", color.new(glow_clr, 95))
d1 = plot(-70, "OS Inner", color.new(glow_clr, 95))
d2 = plot(-90, "OS Outer", color.new(glow_clr, 95))

upper_glow = color.new(glow_clr, math.max(100 - int(math.abs(math.max(0, flow_main))), 70))
lower_glow = color.new(glow_clr, math.max(100 - int(math.abs(math.min(0, flow_main))), 70))

fill(u2, u1, 90, 70, color.new(upper_glow, 100), upper_glow, "Upper Glow Layer")
fill(d1, d2, -70, -90, lower_glow, color.new(lower_glow, 100), "Lower Glow Layer")
fill(p_main, p_sig, is_bullish ? color.new(BULL_GLOW, glowIntensityInput) : color.new(BEAR_GLOW, glowIntensityInput), "Momentum Fill")

// Impulse Visuals (Diamonds)
plotchar(is_impulse_bull ? flow_main : na, "Bull Impulse", "◊", location.absolute, BULL_GLOW, size = size.small)
plotchar(is_impulse_bear ? flow_main : na, "Bear Impulse", "◊", location.absolute, BEAR_GLOW, size = size.small)

//---------------------------------------------------------------------------------------------------------------------}
// Price Chart Rendering: Gradient Candles
//---------------------------------------------------------------------------------------------------------------------{
candle_color = is_bullish ? 
     color.from_gradient(flow_main, 0, 100, NEUTRAL_CORE, BULL_CORE) : 
     color.from_gradient(flow_main, -100, 0, BEAR_CORE, NEUTRAL_CORE)

barcolor(colorCandlesInput ? candle_color : na, title = "Flow Gradient Candles")

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedPos  = dashPosInput == TOP_RIGHT ? position.top_right : dashPosInput == BOTTOM_RIGHT ? position.bottom_right : position.bottom_left
var table dash = table.new(parsedPos, 2, 7, bgcolor = BACKGROUND, frame_color = BORDERS, frame_width = 1)

if showDashboardInput and barstate.islast
    table.merge_cells(dash, 0, 0, 1, 0)
    cell(dash, 0, 0, "OMNI-FLOW CONSENSUS", DATA, text.align_center)
    divider(dash, 1, 1)
    cell(dash, 0, 2, "Regime", HEADERS, text.align_left)
    cell(dash, 1, 2, regime_str, is_trending ? (is_bullish ? BULL_GLOW : BEAR_GLOW) : NEUTRAL_GLOW)
    cell(dash, 0, 3, "Flow Intensity", HEADERS, text.align_left)
    cell(dash, 1, 3, str.format("{0,number,#}%", math.abs(flow_main)), DATA)
    divider(dash, 4, 1)
    cell(dash, 0, 5, "Status", HEADERS, text.align_left)
    cell(dash, 1, 5, is_impulse_bull ? "BULL INJECT" : is_impulse_bear ? "BEAR INJECT" : "NEUTRAL", is_impulse_bull ? BULL_GLOW : is_impulse_bear ? BEAR_GLOW : DATA)

//---------------------------------------------------------------------------------------------------------------------}
// Alerts
//---------------------------------------------------------------------------------------------------------------------{
alertcondition(is_impulse_bull, "Bullish Injection", "Confirmed Bullish Flow Injection.")
alertcondition(is_impulse_bear, "Bearish Injection", "Confirmed Bearish Flow Injection.")

//---------------------------------------------------------------------------------------------------------------------}