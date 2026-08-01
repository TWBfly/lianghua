// This source code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © MWRIGHT, INC

// v1.1
// - Added a Timeframe Extender that turns each candle into a candle that represents a longer timeframe.
//   For example, in the 5 minute timeframe, a Timeframe Extender value of 3 uses a candle that represents
//   a candle for the previous 5 x 3 minutes - 15 minutes. In this case, we're using the wicks for 15 
//   minute candles for EVERY candle. This provides a way to account for wicking that might otherwise not
//   be captured in the current timeframe.
// - Fixed a bug with the smoothing of Half and Phi bands
// - Added color coding to the baseline to indicate uptrends, downtrends, and consolidation using 3 EMAs.
//   If the EMAs are in order (Fast, Mid, Slow), then an uptrend color is used. If the EMAs are in reverse
//   order (Slow, Mid, Fast), then a downtrend color is used. Otherwise, a neutral color is used, which
//   identifies consolidation, or a ranging pattern.
//   This was added because it seemed that the wicking of a baseline during a trend seems to often be a 
//   good indicator of a trend continuation.
// 
// v1.1
// - Revised image for indicator description

//@version=5
indicator(title="ATR Bands (Keltner Channel), Wick and SRSI Signals [MW] v1.1", shorttitle="ATR Wicks SRSI [MW] v1.1", overlay=true, max_labels_count = 500)

// ==================
// Inputs

// Channel Settings
grp_channelSettings = "═════════  Channel Settings  ═════════"
i_ema = input.int(21, title="Baseline EMA Period", group=grp_channelSettings)
i_atr = input.int(21, title="ATR Period", group=grp_channelSettings)
i_multiplier = input.float(2.618, title="Multiplier", step=0.1, group=grp_channelSettings)
i_smoothing = input.int(3, title="Band Smoothing", step=1, group=grp_channelSettings)

// Additional Channels
grp_additional = "════════  Additional Channels  ════════"
i_halfOffset = input.bool(true, title="Half of Multiplier Offset", group=grp_additional)
i_qtrOffset = input.bool(false, title="Quarter of Multiplier Offset", group=grp_additional)
i_phiOffset = input.bool(false, title="Phi (Φ) Offset", group=grp_additional)

// Wick Settings for Candle Filters
grp_wickSettings = "════  Wick Settings for Candle Filters  ════"
i_useCandleBody         = input.bool(false, title="Use Candle Body (Rather than full candle size)", group=grp_wickSettings)
i_wickRatio = input.float(0.4, title="Wick Ratio for Bands", maxval=1, minval=0, step=0.01, group=grp_wickSettings)
i_wickRatioMid  = input.float(0.4, title="Wick Ratio for Baseline", minval=0, step=0.1, group=grp_wickSettings)

// Timeframe Multiplier for Wicks
grp_tfextender = "════  Timeframe Multiplier for Wicks  ════"
i_tfExtender                     = input.int(2, title="Timeframe Extender for Wick Calculations", minval=1, group=grp_tfextender)
i_useWickExtenderSignals         = input.bool(false, title="Use Wick Timeframe Extender", group=grp_tfextender)
i_useOnlyWickExtenderSignals     = input.bool(false, title="Use Wick Timeframe Extender Signals ONLY!", group=grp_tfextender)
i_showWickExtenderCandles        = input.bool(false, title="Show Wick Timeframe Extender Candles", group=grp_tfextender)

// Visual Preferences - Signals
grp_signals = "═════  Visual Preferences - Signals  ═════"
i_showLabels = input.bool(true, title="Show Signals", group=grp_signals)
i_showBaselineSignal = input.bool(true, title="Show Baseline Signals", group=grp_signals)
i_showHalfOffsetSignal = input.bool(false, title="Show Signals from 1/2 Band Offset", group=grp_signals)
i_showPhiOffsetSignal = input.bool(false, title="Show Signals From Phi Band Offset", group=grp_signals)

// Visual Preferences - Bands and Baseline
grp_bandsAndBaseline = "════  Visual Pref. - Bands and Baseline  ════"
i_showBands = input.bool(true, title="Show ATR (Keltner) Bands", group=grp_bandsAndBaseline)
i_fill = input.bool(true, title="Fill Bands", group=grp_bandsAndBaseline)
i_showThickBaseline = input.bool(true, title="Show Thick Baseline", group=grp_bandsAndBaseline)

// SRSI Settings
grp_srsi = "═══════  Stochastic RSI Settings  ═══════"
i_useSRSIFilter = input.bool(true, title="Use Stochastic RSI Filtering", group=grp_srsi)
smoothK     = input.int(3, "K", minval=1, group=grp_srsi)
lengthRSI   = input.int(14, "RSI Length", minval=1, group=grp_srsi)
lengthStoch = input.int(8, "Stochastic Length", minval=1, group=grp_srsi)

// Baseline Consolidation
grp_consolidation = "═══════  Baseline Consolidation  ═══════"
i_rangingEMA1 = input.int(4, title="Fast EMA", minval=1 , group=grp_consolidation)
i_rangingEMA2 = input.int(14, title="Middle EMA", minval=1 , group=grp_consolidation)
i_rangingEMA3 = input.int(21, title="Slow EMA", minval=1 , group=grp_consolidation)


// ==================
// Colors

defaultColor = color.new(#999999,0)
brightRed = color.new(#ff33ff,0) 
brightGreen = color.new(#33ff33,0) 
darkRed = color.new(#660066,0) 
darkGreen = color.new(#006600,0) 

green = color.new(#33cc33,0)
red = color.new(#cc3333,0)
green_half = color.new(#339933,0)
red_half = color.new(#993333,0)
green_phi = color.new(#336633,0)
red_phi = color.new(#663333,0)

var color baselineColor = na


// ==================
// Calculations

// Calculate EMA and ATR

phi = 1.618
ema0 = ta.ema(close, i_ema)
ema = ta.ema(ema0,3)
emaPhiSquared = ta.ema(ema0, math.round(i_ema * phi))
emaPhi = ta.ema(emaPhiSquared, 3)
atr = ta.atr(i_atr)

rangingEMA1 = ta.ema(close,i_rangingEMA1)
rangingEMA2 = ta.ema(close,i_rangingEMA2)
rangingEMA3 = ta.ema(close,i_rangingEMA3)

// Calculate Stochastic RSI values on the primary timeline
_rsi1 = ta.rsi(close, lengthRSI)
_k1 = ta.sma(ta.stoch(_rsi1, _rsi1, _rsi1, lengthStoch), smoothK)

// Calculate Keltner Channel
upperBand0 = ema + atr * i_multiplier
upperBand = ta.sma(upperBand0,i_smoothing)
lowerBand0 = ema - atr * i_multiplier
lowerBand = ta.sma(lowerBand0,i_smoothing)

upperHalfBand0 = ema + atr * i_multiplier / 2
upperHalfBand = ta.sma(upperHalfBand0,i_smoothing)
lowerHalfBand0 = ema - atr * i_multiplier / 2
lowerHalfBand = ta.sma(lowerHalfBand0,i_smoothing)

uppePhiBand0 = ema + atr * i_multiplier * phi-1
upperPhiBand = ta.sma(uppePhiBand0,i_smoothing)
lowerPhiBand0 = ema - atr * i_multiplier * phi-1
lowerPhiBand = ta.sma(lowerPhiBand0,i_smoothing)

// Calculate wicks using Multiplier
tfExtender = i_tfExtender
high_tfExt = ta.highest(high,tfExtender)
open_tfExt = open[tfExtender - 1]
close_tfExt = close
low_tfExt = ta.lowest(low,tfExtender)
tfExtColor = close_tfExt >= open_tfExt ? color.lime : color.red
plotcandle(open=i_showWickExtenderCandles ? open_tfExt : na, high=high_tfExt, low=low_tfExt, close=close_tfExt, title="Timeframe Extended Candles", color=tfExtColor, wickcolor=tfExtColor)


// Calculate Signal for Default Wicks
srsiFilterBear = _k1 > 80
srsiFilterBull = _k1 < 20
var bool closeBelowWickAbove = false
var bool closeAboveWickBelow = false
var bool closeBelowWickAbove_half = false
var bool closeAboveWickBelow_half = false
var bool closeBelowWickAbove_phi = false
var bool closeAboveWickBelow_phi = false
var bool closeBelowWickAbove_baseline = false
var bool closeAboveWickBelow_baseline = false
if i_useSRSIFilter
    closeBelowWickAbove := close < upperBand and high > upperBand and srsiFilterBear
    closeAboveWickBelow := close > lowerBand and low < lowerBand and srsiFilterBull
    closeBelowWickAbove_half := close < upperHalfBand and high > upperHalfBand and srsiFilterBear
    closeAboveWickBelow_half := close > lowerHalfBand and low < lowerHalfBand and srsiFilterBull
    closeBelowWickAbove_phi := close < upperPhiBand and high > upperPhiBand and srsiFilterBear
    closeAboveWickBelow_phi := close > lowerPhiBand and low < lowerPhiBand and srsiFilterBull
    closeBelowWickAbove_baseline := close < ema and high > ema and srsiFilterBear
    closeAboveWickBelow_baseline := close > ema and low < ema and srsiFilterBull
else
    closeBelowWickAbove := close < upperBand and high > upperBand
    closeAboveWickBelow := close > lowerBand and low < lowerBand
    closeBelowWickAbove_half := close < upperHalfBand and high > upperHalfBand
    closeAboveWickBelow_half := close > lowerHalfBand and low < lowerHalfBand
    closeBelowWickAbove_phi := close < upperPhiBand and high > upperPhiBand
    closeAboveWickBelow_phi := close > lowerPhiBand and low < lowerPhiBand
    closeBelowWickAbove_baseline := close < ema and high > ema
    closeAboveWickBelow_baseline := close > ema and low < ema


bodySize = math.abs(open-close)
candleSize = high-low

size = i_useCandleBody ? bodySize : candleSize

upperWickSize = high - math.max(open,close)
upperWickRatio = upperWickSize/size
lowerWickSize = math.min(open,close) - low
lowerWickRatio = lowerWickSize/size

bigUpperWick = upperWickRatio > i_wickRatio ? true : false
bigLowerWick = lowerWickRatio > i_wickRatio ? true : false
bigUpperWickMid = upperWickRatio > i_wickRatioMid ? true : false
bigLowerWickMid = lowerWickRatio > i_wickRatioMid ? true : false

wickedAboveBasis = bigUpperWickMid and closeBelowWickAbove_baseline and ta.falling(ema,14)
wickedBelowBasis = bigLowerWickMid and closeAboveWickBelow_baseline and ta.rising(ema,3)

consolidation = (rangingEMA1 < rangingEMA2 and rangingEMA1 > rangingEMA3) or (rangingEMA1 > rangingEMA2 and rangingEMA1 < rangingEMA3)
bullishBaseline = rangingEMA1 > rangingEMA2 and rangingEMA2 > rangingEMA3
bearishBaseline = rangingEMA1 < rangingEMA2 and rangingEMA2 < rangingEMA3
baselineColor := bullishBaseline ? green : color.new(#cccccc,0)
baselineColor := bearishBaseline ? red : baselineColor

// Calculate Signal for Timeframe Extended Wicks
var bool closeBelowWickAbove_tfExt = false
var bool closeAboveWickBelow_tfExt = false
var bool closeBelowWickAbove_half_tfExt = false
var bool closeAboveWickBelow_half_tfExt = false
var bool closeBelowWickAbove_phi_tfExt = false
var bool closeAboveWickBelow_phi_tfExt = false
var bool closeBelowWickAbove_baseline_tfExt = false
var bool closeAboveWickBelow_baseline_tfExt = false
if i_useSRSIFilter
    closeBelowWickAbove_tfExt := close_tfExt < upperBand and high_tfExt > upperBand and srsiFilterBear
    closeAboveWickBelow_tfExt := close_tfExt > lowerBand and low_tfExt < lowerBand and srsiFilterBull
    closeBelowWickAbove_half_tfExt := close_tfExt < upperHalfBand and high_tfExt > upperHalfBand and srsiFilterBear
    closeAboveWickBelow_half_tfExt := close_tfExt > lowerHalfBand and low_tfExt < lowerHalfBand and srsiFilterBull
    closeBelowWickAbove_phi_tfExt := close_tfExt < upperPhiBand and high_tfExt > upperPhiBand and srsiFilterBear
    closeAboveWickBelow_phi_tfExt := close_tfExt > lowerPhiBand and low_tfExt < lowerPhiBand and srsiFilterBull
    closeBelowWickAbove_baseline_tfExt := close_tfExt < ema and high_tfExt > ema and srsiFilterBear
    closeAboveWickBelow_baseline_tfExt := close_tfExt > ema and low_tfExt < ema and srsiFilterBull
else
    closeBelowWickAbove_tfExt := close_tfExt < upperBand and high_tfExt > upperBand
    closeAboveWickBelow_tfExt := close_tfExt > lowerBand and low_tfExt < lowerBand
    closeBelowWickAbove_half_tfExt := close_tfExt < upperHalfBand and high_tfExt > upperHalfBand
    closeAboveWickBelow_half_tfExt := close_tfExt > lowerHalfBand and low_tfExt < lowerHalfBand
    closeBelowWickAbove_phi_tfExt := close_tfExt < upperPhiBand and high_tfExt > upperPhiBand
    closeAboveWickBelow_phi_tfExt := close_tfExt > lowerPhiBand and low_tfExt < lowerPhiBand
    closeBelowWickAbove_baseline_tfExt := close_tfExt < ema and high_tfExt > ema
    closeAboveWickBelow_baseline_tfExt := close_tfExt > ema and low_tfExt < ema


bodySize_tfExt = math.abs(open_tfExt-close_tfExt)
candleSize_tfExt = high_tfExt-low_tfExt

size_tfExt = i_useCandleBody ? bodySize_tfExt : candleSize_tfExt

upperWickSize_tfExt = high_tfExt - math.max(open_tfExt,close_tfExt)
upperWickRatio_tfExt = upperWickSize_tfExt/size_tfExt
lowerWickSize_tfExt = math.min(open_tfExt,close_tfExt) - low_tfExt
lowerWickRatio_tfExt = lowerWickSize_tfExt/size_tfExt

bigUpperWick_tfExt = upperWickRatio_tfExt > i_wickRatio ? true : false
bigLowerWick_tfExt = lowerWickRatio_tfExt > i_wickRatio ? true : false
bigUpperWickMid_tfExt = upperWickRatio_tfExt > i_wickRatioMid ? true : false
bigLowerWickMid_tfExt = lowerWickRatio_tfExt > i_wickRatioMid ? true : false

wickedAboveBasis_tfExt = bigUpperWickMid_tfExt and closeBelowWickAbove_baseline_tfExt and ta.falling(ema,14)
wickedBelowBasis_tfExt = bigLowerWickMid_tfExt and closeAboveWickBelow_baseline_tfExt and ta.rising(ema,14)


// ==================
// DRAWRINGS


// ======================
// Keltner Bands - ATR Multiplier Signals for Default Wicks
if closeBelowWickAbove and bigUpperWick
    label.new(i_showLabels and not i_useOnlyWickExtenderSignals ? bar_index : na, high, text="S", style=label.style_label_down, color=red, textcolor=color.white, yloc=yloc.abovebar)
plotshape(closeBelowWickAbove and bigUpperWick and not i_useOnlyWickExtenderSignals, title="Trend Weakness - Upper Wick", location=location.abovebar, color=red, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow and bigLowerWick
    label.new(i_showLabels and not i_useOnlyWickExtenderSignals ? bar_index : na, low, "B", style=label.style_label_up, color=green, textcolor=color.white, yloc=yloc.belowbar)
plotshape(closeAboveWickBelow and bigLowerWick and not i_useOnlyWickExtenderSignals, title="Trend Weakness - Lower Wick", location=location.belowbar, color=green, style=shape.triangleup, size=size.tiny)


// Kelter Bands - Half Multiplier Signals
if closeBelowWickAbove_half and bigUpperWick
    label.new(i_showLabels and i_showHalfOffsetSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, high, text="S1", style=label.style_label_down, color=red_half, textcolor=color.white, yloc=yloc.abovebar, size=size.small)
plotshape(closeBelowWickAbove_half and i_showHalfOffsetSignal and bigUpperWick, title="Trend Weakness - Upper Wick - Half Offset", location=location.abovebar, color=red_half, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow_half and bigLowerWick
    label.new(i_showLabels and i_showHalfOffsetSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, low, "B1", style=label.style_label_up, color=green_half, textcolor=color.white, yloc=yloc.belowbar, size=size.small)
plotshape(closeAboveWickBelow_half and i_showHalfOffsetSignal and bigLowerWick and not i_useOnlyWickExtenderSignals, title="Trend Weakness - Lower Wick - Half Offset", location=location.belowbar, color=green_half, style=shape.triangleup, size=size.tiny)


// Keltner Bands - Phi Multiplier Signals
if closeBelowWickAbove_phi and bigUpperWick
    label.new(i_showLabels and i_showPhiOffsetSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, high, text="S2", style=label.style_label_down, color=red_phi, textcolor=color.white, yloc=yloc.abovebar, size=size.small)
plotshape(closeBelowWickAbove_phi and i_showPhiOffsetSignal and bigUpperWick and not i_useOnlyWickExtenderSignals, title="Trend Weakness - Upper Wick - Half Offset", location=location.abovebar, color=red_phi, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow_phi and bigLowerWick
    label.new(i_showLabels and i_showPhiOffsetSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, low, "B2", style=label.style_label_up, color=green_phi, textcolor=color.white, yloc=yloc.belowbar, size=size.small)
plotshape(closeAboveWickBelow_phi and i_showPhiOffsetSignal and bigLowerWick and not i_useOnlyWickExtenderSignals, title="Trend Weakness - Lower Wick - Half Offset", location=location.belowbar, color=green_phi, style=shape.triangleup, size=size.tiny)

// Baseline Signals
if wickedAboveBasis
    label.new(i_showLabels and i_showBaselineSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, high, "S3", style=label.style_label_down, color=color.new(#663333,0), textcolor=color.white, yloc=yloc.abovebar, size=size.small)
if wickedBelowBasis
    label.new(i_showLabels and i_showBaselineSignal and not i_useOnlyWickExtenderSignals ? bar_index : na, low, "B3", style=label.style_label_up, color=color.new(#336633,0), textcolor=color.white, yloc=yloc.belowbar, size=size.small)

// ======================
// Keltner Bands - ATR Multiplier Signals for Timeframe Extended Wicks
if closeBelowWickAbove_tfExt and bigUpperWick_tfExt
    label.new(i_showLabels and i_useWickExtenderSignals ? bar_index : na, high, text="S", style=label.style_label_down, color=red, textcolor=color.white, yloc=yloc.abovebar)
plotshape(closeBelowWickAbove_tfExt and bigUpperWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Upper Wick", location=location.abovebar, color=red, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow_tfExt and bigLowerWick_tfExt
    label.new(i_showLabels and i_useWickExtenderSignals ? bar_index : na, low, "B", style=label.style_label_up, color=green, textcolor=color.white, yloc=yloc.belowbar)
plotshape(closeAboveWickBelow_tfExt and bigLowerWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Lower Wick", location=location.belowbar, color=green, style=shape.triangleup, size=size.tiny)


// Kelter Bands - Half Multiplier Signals
if closeBelowWickAbove_half_tfExt and bigUpperWick_tfExt
    label.new(i_showLabels and i_showHalfOffsetSignal and i_useWickExtenderSignals ? bar_index : na, high, text="S1", style=label.style_label_down, color=red_half, textcolor=color.white, yloc=yloc.abovebar, size=size.small)
plotshape(closeBelowWickAbove_half_tfExt and i_showHalfOffsetSignal and bigUpperWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Upper Wick - Half Offset", location=location.abovebar, color=red_half, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow_half_tfExt and bigLowerWick_tfExt
    label.new(i_showLabels and i_showHalfOffsetSignal and i_useWickExtenderSignals ? bar_index : na, low, "B1", style=label.style_label_up, color=green_half, textcolor=color.white, yloc=yloc.belowbar, size=size.small)
plotshape(closeAboveWickBelow_half_tfExt and i_showHalfOffsetSignal and bigLowerWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Lower Wick - Half Offset", location=location.belowbar, color=green_half, style=shape.triangleup, size=size.tiny)


// Keltner Bands - Phi Multiplier Signals
if closeBelowWickAbove_phi_tfExt and bigUpperWick_tfExt
    label.new(i_showLabels and i_showPhiOffsetSignal and i_useWickExtenderSignals ? bar_index : na, high, text="S2", style=label.style_label_down, color=red_phi, textcolor=color.white, yloc=yloc.abovebar, size=size.small)
plotshape(closeBelowWickAbove_phi_tfExt and i_showPhiOffsetSignal and bigUpperWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Upper Wick - Half Offset", location=location.abovebar, color=red_phi, style=shape.triangledown, size=size.tiny)


if closeAboveWickBelow_phi_tfExt and bigLowerWick_tfExt
    label.new(i_showLabels and i_showPhiOffsetSignal and i_useWickExtenderSignals ? bar_index : na, low, "B2", style=label.style_label_up, color=green_phi, textcolor=color.white, yloc=yloc.belowbar, size=size.small)
plotshape(closeAboveWickBelow_phi_tfExt and i_showPhiOffsetSignal and bigLowerWick_tfExt and i_useWickExtenderSignals, title="Trend Weakness - Lower Wick - Half Offset", location=location.belowbar, color=green_phi, style=shape.triangleup, size=size.tiny)

// Baseline Signals
if wickedAboveBasis_tfExt
    label.new(i_showLabels and i_showBaselineSignal and i_useWickExtenderSignals ? bar_index : na, high, "S3", style=label.style_label_down, color=color.new(#663333,0), textcolor=color.white, yloc=yloc.abovebar, size=size.small)
if wickedBelowBasis_tfExt
    label.new(i_showLabels and i_showBaselineSignal and i_useWickExtenderSignals ? bar_index : na, low, "B3", style=label.style_label_up, color=color.new(#336633,0), textcolor=color.white, yloc=yloc.belowbar, size=size.small)


plot(ema, color=baselineColor, linewidth=3, title="Baseline")
plot(i_showThickBaseline ? ema + .2*atr : na, color=baselineColor, linewidth=1, title="Baseline Upper")
plot(i_showThickBaseline ? ema - .2*atr : na, color=baselineColor, linewidth=1, title="Baseline Lower")
uBand = plot(i_showBands ? upperBand : na, color=color.new(color.silver, 40), title="Upper Band")
lBand = plot(i_showBands ? lowerBand : na, color=color.new(color.silver, 40), title="Lower Band")

// Additional bands
uHalfBand = plot(i_halfOffset and i_showBands ? ema + atr * i_multiplier / 2 : na, color=color.new(color.silver, 60), title="Upper Half Band")
lHalfBand = plot(i_halfOffset and i_showBands ? ema - atr * i_multiplier / 2 : na, color=color.new(color.silver, 60), title="Lower Half Band")
uQtrBand = plot(i_qtrOffset and i_showBands ? ema + atr * i_multiplier / 4 : na, color=color.new(color.silver, 80), title="Upper Quarter Band")
lQtrBand = plot(i_qtrOffset and i_showBands ? ema - atr * i_multiplier / 4 : na, color=color.new(color.silver, 80), title="Lower Quarter Band")
uPhiBand = plot(i_phiOffset and i_showBands ? ema + atr * i_multiplier * 0.618 : na, color=color.new(color.orange, 60))
lPhiBand = plot(i_phiOffset and i_showBands ? ema - atr * i_multiplier * 0.618 : na, color=color.new(color.orange, 60))
// uPhiBand = plot(i_phiOffset and i_showBands ? upperPhiBand : na, color=color.new(color.orange, 60), title="Upper Phi Band")
// lPhiBand = plot(i_phiOffset and i_showBands ? lowerPhiBand : na, color=color.new(color.orange, 60), title="Lower Phi Band")

// Fill bands
fillColor = i_fill and i_showBands ? color.new(color.blue, 90) : na
fill(uBand, lBand, color=fillColor)
fill(uHalfBand, lHalfBand, color=fillColor)
fill(uQtrBand, lQtrBand, color=fillColor)
fill(uPhiBand, lPhiBand, color=fillColor)
