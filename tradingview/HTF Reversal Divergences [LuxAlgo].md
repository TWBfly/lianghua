// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("HTF Reversal Divergences [LuxAlgo]", "LuxAlgo - HTF Reversal Divergences", overlay = false, max_labels_count = 500, max_boxes_count = 500, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
const color BULL_COLOR    = #089981
const color BEAR_COLOR    = #f23645
const color NEUTRAL_COLOR = #787b86

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
// HTF Pattern Inputs
htfInput            = input.timeframe("15", "High Timeframe",           group = "HTF Reversal Patterns", tooltip = "The timeframe to check for reversal patterns.")
showEngulfingInput  = input.bool(true,      "Show Engulfing Patterns",  group = "HTF Reversal Patterns")
showPinBarsInput    = input.bool(true,      "Show Pin Bars",            group = "HTF Reversal Patterns", tooltip = "Includes Hammer and Shooting Star patterns.")
bullPatternColInput = input.color(BULL_COLOR, "Bullish Pattern Color",  group = "HTF Reversal Patterns", inline = "Colors")
bearPatternColInput = input.color(BEAR_COLOR, "Bearish Pattern Color",  group = "HTF Reversal Patterns", inline = "Colors")

// RSI Divergence Inputs
showDivInput        = input.bool(true,      "Show RSI Divergences",     group = "RSI Divergence")
rsiLenInput         = input.int(14,         "RSI Length",               group = "RSI Divergence", minval = 1)
lbRInput            = input.int(5,          "Pivot Right Lookback",     group = "RSI Divergence")
lbLInput            = input.int(5,          "Pivot Left Lookback",      group = "RSI Divergence")
bullDivColInput     = input.color(BULL_COLOR, "Bullish Div Color",      group = "RSI Divergence", inline = "Div Colors")
bearDivColInput     = input.color(BEAR_COLOR, "Bearish Div Color",      group = "RSI Divergence", inline = "Div Colors")

// Advanced: HTF PO3 Inputs
showPo3Input        = input.bool(false,     "Show HTF PO3",             group = "Advanced: HTF PO3", tooltip = "Displays projected HTF candles to the right of price on the main chart.")
candleCountInput    = input.int(1,          "Candles to Show",          group = "Advanced: HTF PO3", minval = 1, maxval = 10)
po3OffsetInput      = input.int(15,         "Right Offset (Bars)",      group = "Advanced: HTF PO3", minval = 5)
showPo3LabelsInput  = input.bool(true,      "Show PO3 Price Labels",    group = "Advanced: HTF PO3")
showPo3DeltaInput   = input.bool(true,      "Show PO3 Running Delta",   group = "Advanced: HTF PO3")

// Alert Inputs
alertBullDivInput   = input.bool(true,      "Bullish Divergence",       group = "Alerts")
alertBearDivInput   = input.bool(true,      "Bearish Divergence",       group = "Alerts")
alertBullEngInput   = input.bool(true,      "Bullish Engulfing",        group = "Alerts")
alertBearEngInput   = input.bool(true,      "Bearish Engulfing",        group = "Alerts")
alertHammerInput    = input.bool(true,      "Hammer",                   group = "Alerts")
alertStarInput      = input.bool(true,      "Shooting Star",            group = "Alerts")

//---------------------------------------------------------------------------------------------------------------------}
// Types & Methods
//---------------------------------------------------------------------------------------------------------------------{
type HTFData
    float o
    float h
    float l
    float c
    int   oIdx
    int   hIdx
    int   lIdx
    float delta
    int   startTime

type HTFCandleUI
    box   body
    line  wick
    line  oM
    line  hM
    line  lM
    line  cM
    label oL
    label hL
    label lL
    label cL
    label dL
    label tL

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
formatDelta(float val) =>
    string sign = val > 0 ? "+" : ""
    float absVal = math.abs(val)
    absVal >= 1000000 ? sign + str.format("{0,number,#.#}M", val / 1000000) : absVal >= 1000 ? sign + str.format("{0,number,#.#}K", val / 1000) : sign + str.tostring(val)

drawHtfPattern(string name, float h, float l, float o, float c, int tStart, int tEnd, color col, bool isBullish) =>
    string timeStr  = str.format_time(tStart, "HH:mm", syminfo.timezone)
    string labelTxt = name + "\n" + timeStr
    int midTime     = math.round((tStart + tEnd) / 2)
    int timeInset   = math.round((tEnd - tStart) * 0.1)

    box.new(tStart, h, tEnd, l, xloc = xloc.bar_time, bgcolor = color.new(col, 90), border_color = color.new(col, 50), border_width = 1, force_overlay = true)
    box.new(tStart + timeInset, math.max(o, c), tEnd - timeInset, math.min(o, c), xloc = xloc.bar_time, bgcolor = color.new(col, 60), border_color = color.new(col, 20), border_width = 1, force_overlay = true)
    line.new(midTime, h, midTime, l, xloc = xloc.bar_time, color = color.new(col, 20), width = 1, force_overlay = true)
    label.new(midTime, isBullish ? l : h, labelTxt, xloc = xloc.bar_time, yloc = yloc.price, color = #00000000, textcolor = col, style = isBullish ? label.style_label_up : label.style_label_down, size = size.small, force_overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
// Core Calculations
//---------------------------------------------------------------------------------------------------------------------{
bool htfNewBar = nz(ta.change(time(htfInput))) != 0

// Fetch HTF Data: [1] is the bar that just finished
[hOpen, hHigh, hLow, hClose, hPrevOpen, hPrevClose, hTimeStart, hTimeEnd] = request.security(syminfo.tickerid, htfInput, [open[1], high[1], low[1], close[1], open[2], close[2], time[1], time_close[1]])

// PO3 Tracking logic
var htfHistory = array.new<HTFData>()
var float curO = na, var float curH = na, var float curL = na
var int   curOIdx = na, var int   curHIdx = na, var int   curLIdx = na
var float curDelta = 0.0
var int   curStartTime = na

if showPo3Input
    if htfNewBar
        if not na(curO)
            htfHistory.unshift(HTFData.new(curO, curH, curL, close[1], curOIdx, curHIdx, curLIdx, curDelta, curStartTime))
            if htfHistory.size() > 10
                htfHistory.pop()
        curO := open, curH := high, curL := low, curOIdx := bar_index, curHIdx := bar_index, curLIdx := bar_index, curDelta := (close > open ? volume : close < open ? -volume : 0), curStartTime := time
    else
        if high > curH or na(curH)
            curH := high, curHIdx := bar_index
        if low < curL or na(curL)
            curL := low, curLIdx := bar_index
        curDelta += (close > open ? volume : close < open ? -volume : 0)

// HTF Pattern Logic
bool isBullEngulfing = showEngulfingInput and hClose > hOpen and hPrevClose < hPrevOpen and hClose >= hPrevOpen and hOpen <= hPrevClose
bool isBearEngulfing = showEngulfingInput and hClose < hOpen and hPrevClose > hPrevOpen and hClose <= hPrevOpen and hOpen >= hPrevClose
bool isHammer        = showPinBarsInput and (math.min(hOpen, hClose) - hLow) > (hHigh - hLow) * 0.6 and math.abs(hClose - hOpen) < (hHigh - hLow) * 0.3
bool isShootingStar  = showPinBarsInput and (hHigh - math.max(hOpen, hClose)) > (hHigh - hLow) * 0.6 and math.abs(hClose - hOpen) < (hHigh - hLow) * 0.3

bool isBullPattern = isBullEngulfing or isHammer
bool isBearPattern = isBearEngulfing or isShootingStar

// RSI Calculations
float rsiValue = ta.rsi(close, rsiLenInput)
color rsiColor = rsiValue > 50 ? bullDivColInput : bearDivColInput

// RSI Divergence Logic
float phRsi = ta.pivothigh(rsiValue, lbLInput, lbRInput), float plRsi = ta.pivotlow(rsiValue, lbLInput, lbRInput)
bool bullDivConfirmed = false, bearDivConfirmed = false

var float plPriceMem = na, var float plRsiMem = na, var int plIndexMem = na
if not na(plRsi)
    if not na(plPriceMem) and rsiValue[lbRInput] > plRsiMem and low[lbRInput] < plPriceMem
        bullDivConfirmed := true
        if showDivInput
            line.new(plIndexMem, plPriceMem, bar_index - lbRInput, low[lbRInput], color = bullDivColInput, width = 2, force_overlay = true)
            label.new(bar_index - lbRInput, low[lbRInput], "Bull Div", yloc = yloc.belowbar, textcolor = bullDivColInput, color = #00000000, size = size.small, style = label.style_label_up, force_overlay = true)
            line.new(plIndexMem, plRsiMem, bar_index - lbRInput, rsiValue[lbRInput], color = bullDivColInput, width = 2)
    plPriceMem := low[lbRInput], plRsiMem := rsiValue[lbRInput], plIndexMem := bar_index - lbRInput

var float phPriceMem = na, var float phRsiMem = na, var int phIndexMem = na
if not na(phRsi)
    if not na(phPriceMem) and rsiValue[lbRInput] < phRsiMem and high[lbRInput] > phPriceMem
        bearDivConfirmed := true
        if showDivInput
            line.new(phIndexMem, phPriceMem, bar_index - lbRInput, high[lbRInput], color = bearDivColInput, width = 2, force_overlay = true)
            label.new(bar_index - lbRInput, high[lbRInput], "Bear Div", yloc = yloc.abovebar, textcolor = bearDivColInput, color = #00000000, size = size.small, style = label.style_label_down, force_overlay = true)
            line.new(phIndexMem, phRsiMem, bar_index - lbRInput, rsiValue[lbRInput], color = bearDivColInput, width = 2)
    phPriceMem := high[lbRInput], phRsiMem := rsiValue[lbRInput], phIndexMem := bar_index - lbRInput

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
// RSI Plots
rsiPlot = plot(rsiValue, "RSI", color = rsiColor, linewidth = 2)
midPlot = plot(50,       "Mid Line", color = color.new(chart.fg_color, 80), style = plot.style_linebr)
fill(midPlot, rsiPlot, 50, rsiValue, rsiValue > 50 ? color.new(bullDivColInput, 100) : color.new(bearDivColInput, 50), rsiValue > 50 ? color.new(bullDivColInput, 50) : color.new(bearDivColInput, 100))
hline(70, "OB", color = color.new(bearDivColInput, 50), linestyle = hline.style_dashed)
hline(30, "OS", color = color.new(bullDivColInput, 50), linestyle = hline.style_dashed)

// HTF Reversal Pattern Drawings
if htfNewBar and not na(hTimeStart)
    if isBullPattern
        drawHtfPattern(isBullEngulfing ? "Bull Engulfing" : "Hammer", hHigh, hLow, hOpen, hClose, hTimeStart, hTimeEnd, bullPatternColInput, true)
    if isBearPattern
        drawHtfPattern(isBearEngulfing ? "Bear Engulfing" : "Shooting Star", hHigh, hLow, hOpen, hClose, hTimeStart, hTimeEnd, bearPatternColInput, false)

// PO3 UI Logic
var uiElements = array.new<HTFCandleUI>()
if barstate.islast and showPo3Input
    if uiElements.size() > 0
        for i = 0 to uiElements.size() - 1
            HTFCandleUI ui = uiElements.get(i)
            ui.body.delete()
            ui.wick.delete()
            if not na(ui.oM)
                ui.oM.delete()
            if not na(ui.hM)
                ui.hM.delete()
            if not na(ui.lM)
                ui.lM.delete()
            if not na(ui.cM)
                ui.cM.delete()
            if not na(ui.oL)
                ui.oL.delete()
            if not na(ui.hL)
                ui.hL.delete()
            if not na(ui.lL)
                ui.lL.delete()
            if not na(ui.cL)
                ui.cL.delete()
            if not na(ui.dL)
                ui.dL.delete()
            if not na(ui.tL)
                ui.tL.delete()
    uiElements.clear()

    int candleWidth = 6, int candleGap = 10
    for p = 0 to candleCountInput - 1
        bool isLive = (p == candleCountInput - 1)
        HTFData data = isLive ? HTFData.new(curO, curH, curL, close, curOIdx, curHIdx, curLIdx, curDelta, curStartTime) : (htfHistory.size() > (candleCountInput - 2) - p ? htfHistory.get((candleCountInput - 2) - p) : na)
        
        if not na(data)
            int startIdx = last_bar_index + po3OffsetInput + (p * (candleWidth + candleGap)), int endIdx = startIdx + candleWidth, int midIdx = (startIdx + endIdx) / 2
            color baseColor = data.c >= data.o ? bullPatternColInput : bearPatternColInput
            color wickColor = isLive ? baseColor : color.new(baseColor, 70)
            line wLine = line.new(midIdx, data.h, midIdx, data.l, color = wickColor, width = 2, force_overlay = true)
            box  bBox  = box.new(startIdx, math.max(data.o, data.c), endIdx, math.min(data.o, data.c), border_color = wickColor, bgcolor = color.new(baseColor, isLive ? 20 : 85), force_overlay = true)
            line oM = na, line hM = na, line lM = na, line cM = na, label oL = na, label hL = na, label lL = na, label cL = na, label dL = na
            if isLive
                oM := line.new(data.oIdx, data.o, startIdx, data.o, color = NEUTRAL_COLOR, style = line.style_dashed, force_overlay = true)
                hM := line.new(data.hIdx, data.h, midIdx, data.h, color = bullPatternColInput, style = line.style_dashed, force_overlay = true)
                lM := line.new(data.lIdx, data.l, midIdx, data.l, color = bearPatternColInput, style = line.style_dashed, force_overlay = true)
                cM := line.new(bar_index, data.c, endIdx, data.c, color = baseColor, style = line.style_dashed, force_overlay = true)
                if showPo3LabelsInput
                    oL := label.new(endIdx + 1, data.o, "Open: " + str.tostring(data.o, format.mintick), color = #00000000, textcolor = NEUTRAL_COLOR, style = label.style_label_left, size = size.small, force_overlay = true)
                    hL := label.new(endIdx + 1, data.h, "High: " + str.tostring(data.h, format.mintick), color = #00000000, textcolor = bullPatternColInput, style = label.style_label_left, size = size.small, force_overlay = true)
                    lL := label.new(endIdx + 1, data.l, "Low: " + str.tostring(data.l, format.mintick), color = #00000000, textcolor = bearPatternColInput, style = label.style_label_left, size = size.small, force_overlay = true)
                    cL := label.new(endIdx + 1, data.c, "Close: " + str.tostring(data.c, format.mintick), color = #00000000, textcolor = baseColor, style = label.style_label_left, size = size.small, force_overlay = true)
            int totalMins = timeframe.in_seconds(htfInput) / 60
            string tfStr = totalMins >= 1440 ? str.tostring(totalMins/1440) + "D" : totalMins >= 60 ? str.tostring(totalMins/60) + "H" : str.tostring(totalMins) + "m"
            label tL = label.new(midIdx, data.h, tfStr + (not isLive ? "\n" + str.format_time(data.startTime, "HH:mm", syminfo.timezone) : ""), color = #00000000, textcolor = isLive ? NEUTRAL_COLOR : color.new(NEUTRAL_COLOR, 60), style = label.style_label_down, size = size.normal, force_overlay = true)
            if showPo3DeltaInput
                dL := label.new(midIdx, data.l, "Delta: " + formatDelta(data.delta), color = #00000000, textcolor = isLive ? (data.delta >= 0 ? bullPatternColInput : bearPatternColInput) : color.new(NEUTRAL_COLOR, 60), style = label.style_label_up, size = size.normal, force_overlay = true)
            uiElements.push(HTFCandleUI.new(bBox, wLine, oM, hM, lM, cM, oL, hL, lL, cL, dL, tL))

//---------------------------------------------------------------------------------------------------------------------}
// Alerts
//---------------------------------------------------------------------------------------------------------------------{
if (alertBullDivInput and bullDivConfirmed)
    alert("Bullish RSI Divergence on " + syminfo.ticker, alert.freq_once_per_bar_close)
if (alertBearDivInput and bearDivConfirmed)
    alert("Bearish RSI Divergence on " + syminfo.ticker, alert.freq_once_per_bar_close)
if (alertBullEngInput and htfNewBar and isBullEngulfing)
    alert("HTF Bullish Engulfing on " + syminfo.ticker, alert.freq_once_per_bar_close)
if (alertBearEngInput and htfNewBar and isBearEngulfing)
    alert("HTF Bearish Engulfing on " + syminfo.ticker, alert.freq_once_per_bar_close)
if (alertHammerInput and htfNewBar and isHammer)
    alert("HTF Hammer on " + syminfo.ticker, alert.freq_once_per_bar_close)
if (alertStarInput and htfNewBar and isShootingStar)
    alert("HTF Shooting Star on " + syminfo.ticker, alert.freq_once_per_bar_close)

//---------------------------------------------------------------------------------------------------------------------}
