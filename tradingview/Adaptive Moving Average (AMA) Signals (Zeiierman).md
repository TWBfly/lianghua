// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/

// ~~ © Zeiierman {
//@version=6
indicator('Adaptive Moving Average (AMA) Signals (Zeiierman)', shorttitle = 'AMA Signals (Zeiierman)', overlay = true, behind_chart = false)
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~ Settings {
// ~~ Tooltips
t1 = "Defines the lookback period for calculating the Efficiency Ratio (ER), which measures the market's efficiency. A higher value smoothens the ER curve but may delay detection of market trends."
t2 = "Sets the length of the fast Exponential Moving Average (EMA) used in calculating the Adaptive Moving Average (AMA). Decreasing this value makes the AMA more sensitive to recent price changes, potentially increasing trading signals."
t3 = "Sets the length of the slow EMA used in calculating the AMA. Increasing this length makes the AMA less sensitive to recent price movements, potentially reduce noise but also delay signal generation."
t4 = "Signal gamma influences the sensitivity of the filter applied to the AMA, which impacts the generation of signals. \n\nA negative value targets trend signals (detected only within trends). \n\nA positive value seeks reversal signals (detected against the trend). \n\nA lower negative value means signals are less sensitive and filter out more trend signals. \n\nConversely, a higher positive value means signals are less sensitive and filter out more reversal signals."
t5 = "Determines the responsiveness of the structure for AMA candles. A higher value may result in smoother but less responsive candles, potentially leading to delayed recognition of price movements."
t6 = "Shows or hides the cloud fill between the AMA line and a smoothed price reference."
t7 = "Bullish cloud color used when the AMA trend is positive."
t8 = "Bearish cloud color used when the AMA trend is negative."
t9 = "Base transparency of the cloud. Lower values make the cloud stronger and more visible."
t10 = "Length of the smoothing used for the hidden cloud reference. Higher values create a softer and steadier cloud."
t11 = "Extra smoothing applied to the AMA line before the cloud is built. Higher values create a cleaner cloud but add lag."
t12 = "Controls how many layered fill bands are used to simulate a richer gradient-like cloud."
t13 = "Controls how far back the script measures AMA direction. Lower values make candle coloring react faster, while higher values make it smoother and more trend-focused."
t14 = "Minimum weighted score required before AMA candles switch bullish or bearish color. Higher values create stricter, cleaner trend coloring. Lower values allow faster but noisier color changes."
t15 = "Bullish candle color used when the AMA candle trend logic is positive."
t16 = "Bearish candle color used when the AMA candle trend logic is negative."
t17 = "When enabled, signal markers are only displayed if they agree with the current AMA candle-color trend. Buy signals require bullish candle trend, and sell signals require bearish candle trend."

n = input(15, title = 'Period for ER calculation', group = 'AMA', inline = '', tooltip = t1)
fastLength = input(5, title = 'Fast EMA Length', group = 'AMA', inline = '', tooltip = t2)
slowLength = input(50, title = 'Slow EMA Length', group = 'AMA', inline = '', tooltip = t3)
gamma = input.float(0.15, step = 0.1, title = 'Signal Gamma', group = 'Trend & Reversal Signals', inline = '', tooltip = t4)
dncol = input.color(color.lime, title = '', group = 'Trend & Reversal Signals', inline = 'col')
upcol = input.color(color.red, title = '', group = 'Trend & Reversal Signals', inline = 'col')
signalWithCandleTrend = input.bool(true, 'Signals Follow Candle Trend', group = 'Trend & Reversal Signals', tooltip = t17)

Candle = input.bool(false, 'AMA Candles', inline = 'Candles', group = 'AMA Candles', tooltip = '')
slopeLen = input.int(3, 'AMA Slope Length', minval = 1, group = 'AMA Candles', tooltip = t13)
scoreThreshold = input.float(0.60, 'Trend Score Threshold', minval = 0.0, maxval = 1.0, step = 0.05, group = 'AMA Candles', tooltip = t14)
length = 50
candleBull = input.color(color.lime, 'Bull Candle', inline = 'candlecol', group = 'AMA Candles', tooltip = t15)
candleBear = input.color(color.red, 'Bear Candle', inline = 'candlecol', group = 'AMA Candles', tooltip = t16)

// ~~ Cloud Fill Settings
showCloud       = input.bool(true, "Show Cloud Fill", group="Cloud Fill", tooltip=t6)
cloudBull       = input.color(color.lime, "Bull Cloud", inline="cloudcol", group="Cloud Fill", tooltip=t7)
cloudBear       = input.color(color.red, "Bear Cloud", inline="cloudcol", group="Cloud Fill", tooltip=t8)
cloudTransp     = input.int(78, "Cloud Transparency", minval=0, maxval=95, group="Cloud Fill", tooltip=t9)
cloudRefLen     = input.int(10, "Cloud Reference Length", minval=1, group="Cloud Fill", tooltip=t10)
cloudLineSmooth = input.int(2, "Cloud Line Smoothing", minval=1, group="Cloud Fill", tooltip=t11)
cloudLayers     = input.int(3, "Cloud Richness", minval=1, maxval=3, group="Cloud Fill", tooltip=t12)
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~  AMA calculation {
// ~~  Calculate the Efficiency Ratio (ER)
change = math.abs(close - close[n])
volatility = math.sum(math.abs(close - close[1]), n)
ER = volatility != 0 ? change / volatility : 0.0

// ~~  Calculate the smoothing constants for the fastest and slowest EMA
fastest = 2.0 / (fastLength + 1.0)
slowest = 2.0 / (slowLength + 1.0)

// ~~  Calculate the Scaled Smoothing Coefficient (SC)
sc = math.pow(ER * (fastest - slowest) + slowest, 2)

// ~~ Calculate the AMA
var float ama = na
ama := na(ama[1]) ? close : ama[1] + sc * (close - ama[1])

// ~~  Apply the filter to the AMA 
sigma = ta.stdev(ama, n)
filter = gamma * sigma
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~ Condition Function {
conditionloop(cond_) =>
    bool conditionMet = true
    for i = 1 to 20 by 1
        if cond_[i]
            conditionMet := false
    conditionMet
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~  AMA CandleFunction {
AMACandles(high_, low_, close_, src_, factor_, candle_, length_) =>
    float initial = 0.0
    float Don_High = ta.highest(high_, length_)
    float Don_Low = ta.lowest(low_, length_)
    float range_ = Don_High - Don_Low
    float Norm = range_ != 0 ? (close_ - Don_Low) / range_ : 0.0
    initial := candle_ ? Norm * close + (1 - Norm) * nz(initial[1], close) : Norm * close + (1 - Norm * 2) * nz(initial[1], close)
    float Factor = candle_ ? (1 - Norm) * nz(initial[1], src_) : (factor_ ? 1 - Norm * 2 : 1 - Norm / 2) * nz(initial[1], src_)
    float output = Norm * src_ + Factor
    output

Up = ta.highest(high + sigma, 5)
Dn = ta.lowest(low - sigma, 5)

// ~~ Return Trend Candles
O = Candle ? ta.ema(AMACandles(Up, Dn, close, open, true, false, length), 2) : na
H = Candle ? ta.ema(AMACandles(Up, Dn, close, high, false, false, length), 2) : na
L = Candle ? ta.ema(AMACandles(Up, Dn, close, low, false, false, length), 2) : na
C = Candle ? ta.ema(AMACandles(Up, Dn, close, close, true, false, length), 2) : na

// ~~ Return Color Sign
pricewick(h_, a) =>
    bool cond = h_ > a
    cond

cond_open  = pricewick(H, open)
cond_high  = pricewick(H, high)
cond_low   = pricewick(H, low)
cond_close = pricewick(H, close)

baseBull = cond_open or cond_high or cond_low or cond_close
baseBear = not baseBull

amaSlope = ama - ama[slopeLen]

// Slope strength normalized by sigma so it adapts to market conditions
safSigma = math.max(sigma, 0.000001)
slopeNorm = math.min(math.abs(amaSlope) / safSigma, 1.0)

// Trend strength from price distance to AMA, also normalized
distNorm = math.min(math.abs(close - ama) / safSigma, 1.0)

// Optional efficiency boost using ER already present in your script
erNorm = math.min(math.max(ER, 0.0), 1.0)

// Stronger trend score: slope gets the most weight, then strength, then structure
slopeWeight = 0.55
strengthWeight = 0.30
structureWeight = 0.15

bullScore = (amaSlope > 0 ? slopeNorm * slopeWeight : 0.0) +
         (close > ama ? ((distNorm * 0.6 + erNorm * 0.4) * strengthWeight) : 0.0) +
         (baseBull ? structureWeight : 0.0)

bearScore = (amaSlope < 0 ? slopeNorm * slopeWeight : 0.0) +
         (close < ama ? ((distNorm * 0.6 + erNorm * 0.4) * strengthWeight) : 0.0) +
         (baseBear ? structureWeight : 0.0)

var color sign = na
sign := bullScore >= scoreThreshold and bullScore > bearScore ? candleBull :
     bearScore >= scoreThreshold and bearScore > bullScore ? candleBear :
     nz(sign[1], color.gray)

candleTrendBull = sign == candleBull
candleTrendBear = sign == candleBear
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~  Trading rules {
longCondition = ta.crossover(ama, ama[1] - filter)
shortCondition = ta.crossunder(ama, ama[1] + filter)
longFilterOk   = conditionloop(longCondition)
shortFilterOk  = conditionloop(shortCondition)
SignalUp       = longCondition and longFilterOk
SignalDn       = shortCondition and shortFilterOk

displaySignalUp = SignalUp and (not signalWithCandleTrend or candleTrendBull)
displaySignalDn = SignalDn and (not signalWithCandleTrend or candleTrendBear)
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~ Plot AMA Average & Signals {
pos    = ama > ama[1] and close > ama
neg    = ama < ama[1] and close < ama
color_ = pos ? color.lime : neg ? color.red : na

plot(ama, color=color_, title="AMA", linewidth=2)

placebuy  = low - ta.atr(14) * 0.6
placesell = high + ta.atr(14) * 0.6

plotshape(displaySignalUp ? placebuy : na, title="Buy Signal", location=location.absolute, color=dncol, style=shape.triangleup, size=size.tiny)
plotshape(displaySignalDn ? placesell : na, title="Sell Signal", location=location.absolute, color=upcol, style=shape.triangledown, size=size.tiny)
plotshape(displaySignalUp ? placebuy : na, title="UI - Buy Signal", location=location.absolute, color=color.new(dncol, 50), style=shape.triangleup, size=size.small)
plotshape(displaySignalDn ? placesell : na, title="UI - Sell Signal", location=location.absolute, color=color.new(upcol, 50), style=shape.triangledown, size=size.small)
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~ Enhanced AMA Cloud {
cloudLine = ta.sma(ama, cloudLineSmooth)
cloudRef  = ta.ema(hlc3, cloudRefLen)

cloudA = not na(cloudLine) and not na(cloudRef) ? cloudLine + (cloudRef - cloudLine) * 0.25 : na
cloudB = not na(cloudLine) and not na(cloudRef) ? cloudLine + (cloudRef - cloudLine) * 0.50 : na
cloudC = not na(cloudLine) and not na(cloudRef) ? cloudLine + (cloudRef - cloudLine) * 0.75 : na

cloudBaseColor = pos ? cloudBull : neg ? cloudBear : na

pCloudLine = plot(showCloud ? cloudLine : na, title="Cloud AMA Line", color=color.new(chart.fg_color, 100), display=display.none)
pCloudA    = plot(showCloud and cloudLayers >= 1 ? cloudA : na, title="Cloud Layer A", color=color.new(chart.fg_color, 100), display=display.none)
pCloudB    = plot(showCloud and cloudLayers >= 2 ? cloudB : na, title="Cloud Layer B", color=color.new(chart.fg_color, 100), display=display.none)
pCloudC    = plot(showCloud and cloudLayers >= 3 ? cloudC : na, title="Cloud Layer C", color=color.new(chart.fg_color, 100), display=display.none)
pCloudRef  = plot(showCloud ? cloudRef : na, title="Cloud Reference", color=color.new(chart.fg_color, 100), display=display.none)

fill(pCloudLine, pCloudA, color=showCloud and cloudLayers >= 1 ? color.new(cloudBaseColor, math.max(0, cloudTransp - 18)) : na, title="Cloud Fill 1")
fill(pCloudA, pCloudB, color=showCloud and cloudLayers >= 2 ? color.new(cloudBaseColor, math.max(0, cloudTransp - 6)) : na, title="Cloud Fill 2")
fill(pCloudB, pCloudC, color=showCloud and cloudLayers >= 3 ? color.new(cloudBaseColor, math.min(95, cloudTransp + 6)) : na, title="Cloud Fill 3")
fill(pCloudC, pCloudRef, color=showCloud and cloudLayers >= 3 ? color.new(cloudBaseColor, math.min(95, cloudTransp + 18)) : na, title="Cloud Fill 4")
fill(pCloudB, pCloudRef, color=showCloud and cloudLayers == 2 ? color.new(cloudBaseColor, math.min(95, cloudTransp + 10)) : na, title="Cloud Fill 2 Layer")
fill(pCloudA, pCloudRef, color=showCloud and cloudLayers == 1 ? color.new(cloudBaseColor, math.min(95, cloudTransp + 14)) : na, title="Cloud Fill 1 Layer")
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~  Plot AMA Candles {
plotcandle(open, high, low, close, color = Candle ? sign : na, bordercolor = Candle ? sign : na, wickcolor = Candle ? sign : na, title = 'AMA Candles')
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}

// ~~  Alerts {
alertcondition(displaySignalUp, title = 'Buy', message = 'Buy')
alertcondition(displaySignalDn, title = 'Sell', message = 'Sell')
alertcondition(pos and not pos[1], title = 'Positive Trend', message = 'Positive Trend')
alertcondition(neg and not neg[1], title = 'Negative Trend', message = 'Negative Trend')
//~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~}