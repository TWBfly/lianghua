// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("KNN Supertrend Horizon [LuxAlgo]", "LuxAlgo - KNN Supertrend Horizon", overlay = true, max_bars_back = 2001, max_labels_count = 500, format = format.price)

//---------------------------------------------------------------------------------------------------------------------}
// Constants 
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645
string BAR_CHAR  = "▬▬▬▬▬▬▬▬▬▬"

// Table Constants
DATA                    = #DBDBDB
HEADERS                 = #808080
BACKGROUND              = #161616
BORDERS                 = #2E2E2E
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
string GRP_ML    = "Machine Learning Settings"
int neighborsK   = input.int(10, "K-Neighbors", minval = 1, maxval = 50, group = GRP_ML)
int windowSize   = input.int(500, "Search Window", minval = 100, maxval = 2000, group = GRP_ML)

string GRP_STR   = "Supertrend Settings"
int atrLenInput  = input.int(10, "ATR Length", minval = 1, group = GRP_STR)
float factorInput = input.float(3.0, "Factor", minval = 0.01, step = 0.1, group = GRP_STR)

string GRP_FIL    = "Noise Filter Settings"
bool smoothSource = input.bool(true, "Smooth Price Input", group = GRP_FIL)
int smoothLenVal  = input.int(10, "Smoothing Length", minval = 1, group = GRP_FIL)
float mlBuffer    = input.float(5.0, "ML Confidence Buffer (%)", minval = 0.0, maxval = 20.0, step = 0.5, group = GRP_FIL)

string GRP_SIG    = "Rejection Signal Settings"
bool showBubbles  = input.bool(true, "Show 3D Rejection Orbs", group = GRP_SIG)
float rejMult     = input.float(1.5, "Min Wick-to-Body Multiplier", minval = 1.0, maxval = 5.0, step = 0.1, group = GRP_SIG)
int bubbleGap     = input.int(5, "Min Bubble Gap (Bars)", minval = 1, maxval = 20, group = GRP_SIG)

string GRP_VIS   = "Visual Settings"
color bullColInput = input.color(BULL_COLOR, "Uptrend Color", group = GRP_VIS)
color bearColInput = input.color(BEAR_COLOR, "Downtrend Color", group = GRP_VIS)
int smoothLen      = input.int(20, "Liquid Smoothness", minval = 1, group = GRP_VIS)
float vibrancy     = input.float(1.5, "Vibrancy", minval = 1.0, maxval = 3.0, step = 0.1, group = GRP_VIS)
bool colorCandles  = input.bool(true, "Gradient Candle Coloring", group = GRP_VIS)

string GRP_DB          = "Dashboard Settings"
bool showDashboard     = input.bool(true, "Show Dashboard", group = GRP_DB)
string dashboardPos    = input.string(TOP_RIGHT, "Position", options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT], group = GRP_DB)
string dashboardSize   = input.string(SMALL, "Size", options = [TINY, SMALL, NORMAL, LARGE, HUGE], group = GRP_DB)

//---------------------------------------------------------------------------------------------------------------------}
// Variables & Helper Functions
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPos
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize     = switch dashboardSize
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

// Table Helper Functions
cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

// Formatting Helpers
formatDynamicVolume(vol) =>
    vol >= 1000000000 ? str.format("{0,number,#.##}B", vol / 1000000000) :
     vol >= 1000000 ? str.format("{0,number,#.##}M", vol / 1000000) :
     vol >= 1000 ? str.format("{0,number,#.#}K", vol / 1000) :
     str.tostring(vol, "#")

getDynamicSizeValue() =>
    float avgVol = ta.sma(volume, 100)
    float stdVol = ta.stdev(volume, 100)
    float zScore = (volume - avgVol) / nz(stdVol, 1)
    int sz = int(math.max(8, math.min(30, 14 + (zScore * 2))))
    sz

//---------------------------------------------------------------------------------------------------------------------}
// Core ML Engine (KNN)
//---------------------------------------------------------------------------------------------------------------------{
float src = smoothSource ? ta.hma(close, smoothLenVal) : close
float f1 = ta.rsi(src, 14)
float f2 = (ta.atr(14) / src) * 100
[st_val, st_dir] = ta.supertrend(factorInput, atrLenInput)
int targetTrend = st_dir < 0 ? 1 : -1

var float mlProb = 50.0
if bar_index > windowSize
    float bullVotes = 0.0
    float bearVotes = 0.0
    float[] dists = array.new_float(0)
    for i = 1 to windowSize
        float d = math.sqrt(math.pow(f1 - f1[i], 2) + math.pow(f2 - f2[i], 2))
        array.push(dists, d)
    float[] sortedDists = array.copy(dists)
    array.sort(sortedDists)
    float threshold = array.get(sortedDists, math.min(neighborsK - 1, array.size(sortedDists) - 1))
    for i = 0 to array.size(dists) - 1
        if array.get(dists, i) <= threshold
            if targetTrend[i+1] > 0
                bullVotes += 1
            else
                bearVotes += 1
    mlProb := (bullVotes / (bullVotes + bearVotes)) * 100

float smoothedProb = ta.ema(mlProb, smoothLen)
var bool mlBullish = false
if smoothedProb > 50 + mlBuffer
    mlBullish := true
else if smoothedProb < 50 - mlBuffer
    mlBullish := false

float intensity    = mlBullish ? (smoothedProb - 50) * 2 : (50 - smoothedProb) * 2
float glowPower    = math.pow(math.max(0, intensity) / 100, vibrancy) * 100

// Colors
color bullGlow = color.from_gradient(glowPower, 0, 100, color.new(bullColInput, 100), color.new(bullColInput, 75))
color bearGlow = color.from_gradient(glowPower, 0, 100, color.new(bearColInput, 100), color.new(bearColInput, 75))
color candleBull = color.from_gradient(glowPower, 0, 100, color.new(bullColInput, 85), color.new(bullColInput, 20))
color candleBear = color.from_gradient(glowPower, 0, 100, color.new(bearColInput, 85), color.new(bearColInput, 20))

//---------------------------------------------------------------------------------------------------------------------}
// Rejection Detection & Visuals
//---------------------------------------------------------------------------------------------------------------------{
float atrRef    = ta.atr(14)
float bodySize  = math.abs(close - open)
float upperWick = high - math.max(open, close)
float lowerWick = math.min(open, close) - low
var int lastBubbleBar = 0

bool isBearRejection = not mlBullish and high > st_val and close < st_val and upperWick > bodySize * rejMult and (bar_index - lastBubbleBar >= bubbleGap)
bool isBullRejection = mlBullish and low < st_val and close > st_val and lowerWick > bodySize * rejMult and (bar_index - lastBubbleBar >= bubbleGap)

int currentBubbleSize = getDynamicSizeValue()
string bubbleText     = formatDynamicVolume(volume)
float stemOffset      = atrRef * 1.5
float orbLayerGap     = atrRef * 0.05

render3DOrbWithLabel(int barIdx, float yCenter, string txt, int baseSize, color themeColor, float offset, bool isBull) =>
    label.new(barIdx, yCenter - (offset * 1.5), style = label.style_circle, color = color.new(color.black, 80), size = baseSize + 2, yloc = yloc.price)
    label.new(barIdx, yCenter, style = label.style_circle, color = color.new(themeColor, 70), size = baseSize + 1, yloc = yloc.price)
    label.new(barIdx, yCenter, style = label.style_circle, color = color.new(themeColor, 15), size = baseSize, yloc = yloc.price)
    label.new(barIdx, yCenter + (offset * 0.5), style = label.style_circle, color = color.new(color.white, 85), size = int(baseSize * 0.7), yloc = yloc.price)
    label.new(barIdx, yCenter + offset, style = label.style_circle, color = color.new(color.white, 40), size = int(baseSize * 0.2), yloc = yloc.price)
    float labelY = isBull ? yCenter - (offset * 8.0) : yCenter + (offset * 8.0)
    label.new(barIdx, labelY, text = txt, style = isBull ? label.style_label_up : label.style_label_down, color = color.new(color.black, 40), textcolor = color.white, size = size.small, yloc = yloc.price)

if showBubbles and isBullRejection
    line.new(bar_index, low, bar_index, low - stemOffset, color = color.new(bullColInput, 60), style = line.style_dashed)
    render3DOrbWithLabel(bar_index, low - stemOffset, bubbleText, currentBubbleSize, bullColInput, orbLayerGap, true)
    lastBubbleBar := bar_index

if showBubbles and isBearRejection
    line.new(bar_index, high, bar_index, high + stemOffset, color = color.new(bearColInput, 60), style = line.style_dashed)
    render3DOrbWithLabel(bar_index, high + stemOffset, bubbleText, currentBubbleSize, bearColInput, orbLayerGap, false)
    lastBubbleBar := bar_index

plotchar(mlBullish, "Bull Glow", BAR_CHAR, location.bottom, bullGlow, size = size.large)
plotchar(not mlBullish, "Bear Glow", BAR_CHAR, location.top, bearGlow, size = size.large)
plot(st_val, "ML Supertrend", mlBullish ? color.new(bullColInput, 60) : color.new(bearColInput, 60), 2, plot.style_linebr)
barcolor(colorCandles ? (mlBullish ? candleBull : candleBear) : na, title = "Gradient Candles")

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard Display
//---------------------------------------------------------------------------------------------------------------------{
var int barsSinceChange = 0
barsSinceChange := ta.change(mlBullish) ? 0 : barsSinceChange + 1

if showDashboard and barstate.islast
    var table t_able = table.new(parsedDashboardPosition, 2, 9, bgcolor = BACKGROUND, frame_color = BORDERS, frame_width = 1)
    
    t_able.merge_cells(0, 0, 1, 0)
    cell(t_able, 0, 0, "KNN Supertrend Horizon [LuxAlgo]", color = DATA, align = text.align_center)
    divider(t_able, 1, 1)

    cell(t_able, 0, 2, "Trend Direction", HEADERS, text.align_left)
    cell(t_able, 1, 2, mlBullish ? "Bullish" : "Bearish", mlBullish ? BULL_COLOR : BEAR_COLOR)

    cell(t_able, 0, 3, "ML Confidence", HEADERS, text.align_left)
    cell(t_able, 1, 3, str.tostring(smoothedProb, "#.#") + "%", DATA)

    divider(t_able, 4, 1)

    cell(t_able, 0, 5, "Bars In Trend", HEADERS, text.align_left)
    cell(t_able, 1, 5, str.tostring(barsSinceChange), DATA)

    cell(t_able, 0, 6, "ST Distance", HEADERS, text.align_left)
    float distPct = (math.abs(close - st_val) / close) * 100
    cell(t_able, 1, 6, str.tostring(distPct, "#.##") + "%", DATA)

    divider(t_able, 7, 1)

    cell(t_able, 0, 8, "Rel. Volatility", HEADERS, text.align_left)
    cell(t_able, 1, 8, str.tostring(f2, "#.##") + "%", DATA)

//---------------------------------------------------------------------------------------------------------------------}