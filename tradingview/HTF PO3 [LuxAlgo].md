// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("HTF PO3 [LuxAlgo]", "LuxAlgo - HTF PO3", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Inputs
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR    = #089981
color BEAR_COLOR    = #f23645
color NEUTRAL_COLOR = #787b86

string HTF_GROUP      = "Higher Timeframe Settings"
string htfInput       = input.timeframe("60", "HTF Timeframe", group = HTF_GROUP)
int candleCountInput  = input.int(1, "Candles to Show", minval = 1, maxval = 10, group = HTF_GROUP)
int offsetInput       = input.int(15, "Right Offset (Bars)", minval = 5, group = HTF_GROUP)

string STYLE_GROUP    = "Visual Style"
color bullColorInput  = input.color(BULL_COLOR, "Bullish Color", inline = "colors", group = STYLE_GROUP)
color bearColorInput  = input.color(BEAR_COLOR, "Bearish Color", inline = "colors", group = STYLE_GROUP)
int transparency      = input.int(0, "Live Body Transparency", minval = 0, maxval = 100, group = STYLE_GROUP)
bool showLabelsInput  = input.bool(true, "Show Price Labels", group = STYLE_GROUP)
bool showDeltaInput   = input.bool(true, "Show Running Delta", group = STYLE_GROUP)

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
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
var htfHistory = array.new<HTFData>()
bool htfNew = ta.change(time(htfInput)) != 0

// Tracking for current forming HTF candle
var float curO = na, var float curH = na, var float curL = na
var int   curOIdx = na, var int   curHIdx = na, var int   curLIdx = na
var float curDelta = 0.0
var int   curStartTime = na

if htfNew
    // Save finished candle to history
    if not na(curO)
        htfHistory.unshift(HTFData.new(curO, curH, curL, close[1], curOIdx, curHIdx, curLIdx, curDelta, curStartTime))
        if htfHistory.size() > 10
            htfHistory.pop()
    
    // Initialize new candle
    curO := open
    curH := high
    curL := low
    curOIdx := bar_index
    curHIdx := bar_index
    curLIdx := bar_index
    curDelta := (close > open ? volume : close < open ? -volume : 0)
    curStartTime := time
else
    if high > curH or na(curH)
        curH := high
        curHIdx := bar_index
    if low < curL or na(curL)
        curL := low
        curLIdx := bar_index
    curDelta += (close > open ? volume : close < open ? -volume : 0)

// Formatting Delta
formatDelta(float val) =>
    string sign = val > 0 ? "+" : ""
    float absVal = math.abs(val)
    absVal >= 1000000 ? sign + str.format("{0,number,#.#}M", val / 1000000) : absVal >= 1000 ? sign + str.format("{0,number,#.#}K", val / 1000) : sign + str.tostring(val)

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
var uiElements = array.new<HTFCandleUI>()

if barstate.islast
    // Cleanup previous UI elements
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

    int candleWidth = 6
    int candleGap   = 10

    // Render candles chronologically: [Oldest] ... [Prev] [Live]
    for p = 0 to candleCountInput - 1
        bool isLive = (p == candleCountInput - 1)
        HTFData data = na
        
        if isLive
            data := HTFData.new(curO, curH, curL, close, curOIdx, curHIdx, curLIdx, curDelta, curStartTime)
        else
            int histIdx = (candleCountInput - 2) - p
            if htfHistory.size() > histIdx
                data := htfHistory.get(histIdx)
        
        if not na(data)
            // Coordinates for the projection
            int startIdx = last_bar_index + offsetInput + (p * (candleWidth + candleGap))
            int endIdx   = startIdx + candleWidth
            int midIdx   = (startIdx + endIdx) / 2
            int labelIdx = endIdx + 1
            
            color baseColor = data.c >= data.o ? bullColorInput : bearColorInput
            color wickColor = isLive ? baseColor : color.new(baseColor, 70)
            int bodyTrans   = isLive ? transparency : 85
            
            // 1. HTF Candle (Drawn using absolute prices and index grid)
            line wLine = line.new(midIdx, data.h, midIdx, data.l, color = wickColor, width = 2)
            box  bBox  = box.new(startIdx, math.max(data.o, data.c), endIdx, math.min(data.o, data.c), border_color = wickColor, bgcolor = color.new(baseColor, bodyTrans))

            // 2. Mapping & Labels (ONLY for the LIVE candle)
            line oM = na, line hM = na, line lM = na, line cM = na
            label oL = na, label hL = na, label lL = na, label cL = na

            if isLive
                // Direct connectors from LTF bar origin to HTF projection
                oM := line.new(data.oIdx, data.o, startIdx, data.o, color = NEUTRAL_COLOR, style = line.style_dashed)
                hM := line.new(data.hIdx, data.h, midIdx, data.h, color = bullColorInput, style = line.style_dashed)
                lM := line.new(data.lIdx, data.l, midIdx, data.l, color = bearColorInput, style = line.style_dashed)
                cM := line.new(bar_index, data.c, endIdx, data.c, color = baseColor, style = line.style_dashed)

                if showLabelsInput
                    oL := label.new(labelIdx, data.o, "Open: " + str.tostring(data.o, format.mintick), color = #00000000, textcolor = NEUTRAL_COLOR, style = label.style_label_left, size = size.small)
                    hL := label.new(labelIdx, data.h, "High: " + str.tostring(data.h, format.mintick), color = #00000000, textcolor = bullColorInput, style = label.style_label_left, size = size.small)
                    lL := label.new(labelIdx, data.l, "Low: " + str.tostring(data.l, format.mintick), color = #00000000, textcolor = bearColorInput, style = label.style_label_left, size = size.small)
                    cL := label.new(labelIdx, data.c, "Close: " + str.tostring(data.c, format.mintick), color = #00000000, textcolor = baseColor, style = label.style_label_left, size = size.small)

            // 3. Timeframe Header
            int totalMins = timeframe.in_seconds(htfInput) / 60
            string tfStr = totalMins >= 1440 ? str.tostring(totalMins/1440) + "D" : totalMins >= 60 ? str.tostring(totalMins/60) + "H" : str.tostring(totalMins) + "m"
            string headText = tfStr
            if not isLive
                headText += "\n" + str.format_time(data.startTime, "HH:mm", syminfo.timezone)
            color tfColor = isLive ? NEUTRAL_COLOR : color.new(NEUTRAL_COLOR, 60)
            label tL = label.new(midIdx, data.h, headText, color = #00000000, textcolor = tfColor, style = label.style_label_down, size = size.normal)

            // 4. Delta (Centered below Low)
            label dL = na
            if showDeltaInput
                color dCol = data.delta >= 0 ? bullColorInput : bearColorInput
                color fDCol = isLive ? dCol : color.new(dCol, 60)
                dL := label.new(midIdx, data.l, "Delta: " + formatDelta(data.delta), color = #00000000, textcolor = fDCol, style = label.style_label_up, size = size.normal)

            uiElements.push(HTFCandleUI.new(bBox, wLine, oM, hM, lM, cM, oL, hL, lL, cL, dL, tL))

//---------------------------------------------------------------------------------------------------------------------}
// End of Script
//---------------------------------------------------------------------------------------------------------------------{