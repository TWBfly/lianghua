// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/ MPL-2.0
// © LuxAlgo

//@version=6
indicator("Session Volume Moving Average [LuxAlgo]", "LuxAlgo - Session Volume Moving Average", overlay=true, max_boxes_count=500, max_lines_count=500, max_labels_count=500, calc_bars_count = 2000)

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string maGroup      = "Moving Average Settings"
int    lengthInput  = input.int(50, "Length", minval=1, group=maGroup)
string maTypeInput  = input.string("SMA", "Type", options=["SMA", "EMA", "RMA", "WMA", "HMA", "VWMA"], group=maGroup)
float  srcInput     = input.source(close, "Source", group=maGroup)

string sessGroup    = "Session Settings"
int    maxSessInput = input.int(3, "Past Sessions to Show", minval=1, maxval=50, group=sessGroup, tooltip="Limits the number of past sessions drawn. Increase this to see more past history. Note: Subject to Pine Script's 500 max box limit.")
bool   useSess1     = input.bool(true,  "Session 1 (New York)", inline="s1", group=sessGroup)
string sess1Time    = input.session("0930-1600", "", inline="s1", group=sessGroup)
bool   useSess2     = input.bool(false, "Session 2 (London)  ", inline="s2", group=sessGroup)
string sess2Time    = input.session("0300-1130", "", inline="s2", group=sessGroup)
bool   useSess3     = input.bool(false, "Session 3 (Tokyo)   ", inline="s3", group=sessGroup)
string sess3Time    = input.session("1800-0300", "", inline="s3", group=sessGroup)
bool   useSess4     = input.bool(false, "Session 4 (Sydney)  ", inline="s4", group=sessGroup)
string sess4Time    = input.session("1700-0200", "", inline="s4", group=sessGroup)
string sessionTz    = input.string("America/New_York", "Timezone", group=sessGroup)

string volGroup     = "Volume Bar Settings"
float  volMult      = input.float(1.5, "Height Multiplier", minval=0.1, step=0.1, group=volGroup, tooltip="Adjusts the maximum height of the volume bars relative to price volatility.")
int    lookback     = input.int(100, "Normalization Lookback", minval=10, group=volGroup)
int    consecBars   = input.int(4, "Consecutive Trend Bars", minval=2, group=volGroup, tooltip="Highlights areas with this many consecutive bars of increasing or decreasing volume.")
float  sigVolMult   = input.float(2.0, "Significant Vol Multiplier", minval=0.0, step=0.1, group=volGroup, tooltip="Only highlights streaks where volume exceeds this multiplier times the average volume. Set to 0 to show all.")
string volDirection = input.string("Auto", "Bar Direction", options=["Auto", "Upwards", "Downwards"], group=volGroup)
float  barWidth     = input.float(0.8, "Bar Width %", minval=0.1, maxval=1.0, step=0.1, group=volGroup, tooltip="Adjusts the width of the volume blocks relative to the candle width.")

string styleGroup   = "Style"
color  colorUp      = input.color(#089981, "Bullish Volume", group=styleGroup)
color  colorDown    = input.color(#f23645, "Bearish Volume", group=styleGroup)
color  borderCol    = input.color(#131722, "Border Color", group=styleGroup)
color  maColor      = input.color(#5b9cf6, "Moving Average", group=styleGroup)
bool   colorCandles = input.bool(false, "Color Candles By Delta", group=styleGroup)

string gradGroup    = "Session Gradient Bar"
bool   showGradBar  = input.bool(true, "Show Session Delta Bar", group=gradGroup)
float  gradHeight   = input.float(2.0, "Bar Height Multiplier", minval=0.1, step=0.1, group=gradGroup)
color  gradMidCol   = input.color(color.gray, "Neutral Color", group=gradGroup)

string vpGroup      = "Volume Profile"
bool   showVP       = input.bool(true, "Show Volume Profile", group=vpGroup)
int    vpBins       = input.int(24, "Number of Bins", minval=5, maxval=100, group=vpGroup)
int    vpWidth      = input.int(20, "VP Width %", minval=5, maxval=100, group=vpGroup)
color  vpColor      = input.color(color.new(#5b9cf6, 70), "VP Color", group=vpGroup)

//---------------------------------------------------------------------------------------------------------------------}
// Types & Methods
//---------------------------------------------------------------------------------------------------------------------{
type SessionVisuals
    box[]   boxes
    label[] labels
    line[]  lines

method track(box b, SessionVisuals sv) =>
    if not na(sv) and not na(b)
        array.push(sv.boxes, b)
    b

method track(label l, SessionVisuals sv) =>
    if not na(sv) and not na(l)
        array.push(sv.labels, l)
    l

method track(line ln, SessionVisuals sv) =>
    if not na(sv) and not na(ln)
        array.push(sv.lines, ln)
    ln

type SessProfile
    float[] prices
    float[] vols
    box[]   boxes
    float   maxP
    float   minP

method reset(SessProfile vp) =>
    array.clear(vp.prices)
    array.clear(vp.vols)
    vp.boxes := array.new_box()
    vp.maxP := na
    vp.minP := na

method addData(SessProfile vp, float p, float v, float h, float l) =>
    array.push(vp.prices, p)
    array.push(vp.vols, v)
    if na(vp.maxP)
        vp.maxP := h
        vp.minP := l
    else
        vp.maxP := math.max(vp.maxP, h)
        vp.minP := math.min(vp.minP, l)

method drawProfile(SessProfile vp, int rTime, int lTime, color vColor, int numBins, int vpWidthPct, SessionVisuals sv) =>
    if array.size(vp.prices) > 0 and vp.maxP != vp.minP
        float binSize = (vp.maxP - vp.minP) / numBins
        float[] binVols = array.new_float(numBins, 0)
        
        float maxBinVol = 0
        for i = 0 to array.size(vp.prices) - 1
            float p = array.get(vp.prices, i)
            float v = array.get(vp.vols, i)
            int binIdx = math.floor((p - vp.minP) / binSize)
            if binIdx >= numBins
                binIdx := numBins - 1
            if binIdx < 0
                binIdx := 0
            float curV = array.get(binVols, binIdx) + v
            array.set(binVols, binIdx, curV)
            maxBinVol := math.max(maxBinVol, curV)
            
        if array.size(vp.boxes) == 0
            for i = 0 to numBins - 1
                box newBox = box.new(na, na, na, na, xloc=xloc.bar_time, border_width=0).track(sv)
                array.push(vp.boxes, newBox)
                
        int sessWidth = rTime - lTime
        int maxVpWidth = math.round(sessWidth * (vpWidthPct / 100.0))
        
        for i = 0 to numBins - 1
            box b = array.get(vp.boxes, i)
            float bVol = array.get(binVols, i)
            float bTop = vp.minP + (i + 1) * binSize
            float bBot = vp.minP + i * binSize
            
            int bLeft = maxBinVol > 0 ? rTime - math.round((bVol / maxBinVol) * maxVpWidth) : rTime
            
            box.set_lefttop(b, bLeft, bTop)
            box.set_rightbottom(b, rTime, bBot)
            box.set_bgcolor(b, vColor)

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
get_ma(float source, int length, string type) =>
    float _sma  = ta.sma(source, length)
    float _ema  = ta.ema(source, length)
    float _rma  = ta.rma(source, length)
    float _wma  = ta.wma(source, length)
    float _hma  = ta.hma(source, length)
    float _vwma = ta.vwma(source, length)
    switch type
        "SMA"  => _sma
        "EMA"  => _ema
        "RMA"  => _rma
        "WMA"  => _wma
        "HMA"  => _hma
        "VWMA" => _vwma
        => _sma

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
float ma = get_ma(srcInput, lengthInput, maTypeInput)

// Session filtering logic
bool  inSess1   = useSess1 and not na(time(timeframe.period, sess1Time, sessionTz))
bool  inSess2   = useSess2 and not na(time(timeframe.period, sess2Time, sessionTz))
bool  inSess3   = useSess3 and not na(time(timeframe.period, sess3Time, sessionTz))
bool  inSess4   = useSess4 and not na(time(timeframe.period, sess4Time, sessionTz))
bool  anySess   = useSess1 or useSess2 or useSess3 or useSess4
bool  inSession = inSess1 or inSess2 or inSess3 or inSess4
bool  plotCond  = anySess ? inSession : true
float vol       = plotCond ? volume : 0

// Scale volume using a rolling max and ATR to match chart proportions
float priceScale = ta.atr(lookback)
// Use 95th percentile to prevent single extreme volume spikes from squashing the rest
float maxVol     = ta.percentile_linear_interpolation(vol, lookback, 95)
float normVol    = maxVol > 0 ? math.min(vol / maxVol, 1.2) : 0
float volHeight  = normVol * priceScale * volMult

bool  isUpwards  = volDirection == "Auto" ? close < ma : volDirection == "Upwards"
float y1 = ma
float y2 = isUpwards ? ma + volHeight : ma - volHeight

bool  isBull   = close > open

// Session Delta (Bull vs Bear Volume %)
var float sessCumBull = 0
var float sessCumTotal = 0
bool newSession = (inSess1 and not inSess1[1]) or (inSess2 and not inSess2[1]) or (inSess3 and not inSess3[1]) or (inSess4 and not inSess4[1])

bool newDay = ta.change(time("D")) != 0
bool newSessTrigger = anySess ? newSession : newDay

var SessionVisuals[] pastSessions = array.new<SessionVisuals>()

if barstate.isfirst
    array.push(pastSessions, SessionVisuals.new(array.new_box(), array.new_label(), array.new_line()))

if newSessTrigger
    array.push(pastSessions, SessionVisuals.new(array.new_box(), array.new_label(), array.new_line()))
    if array.size(pastSessions) > maxSessInput
        SessionVisuals old = array.shift(pastSessions)
        for b in old.boxes
            box.delete(b)
        for l in old.labels
            label.delete(l)
        for ln in old.lines
            line.delete(ln)

SessionVisuals currentVisuals = array.size(pastSessions) > 0 ? array.last(pastSessions) : na


if newSession
    sessCumBull  := isBull ? vol : 0
    sessCumTotal := vol
else if inSession
    sessCumBull  += isBull ? vol : 0
    sessCumTotal += vol

float deltaPercent = sessCumTotal > 0 ? (sessCumBull / sessCumTotal) * 100 : 50
color heatColor = deltaPercent < 50 ? color.from_gradient(deltaPercent, 35, 50, colorDown, gradMidCol) : color.from_gradient(deltaPercent, 50, 65, gradMidCol, colorUp)

// Calculate opacity gradient: higher volume = more opaque, lower volume = more transparent
float transp   = 100 - (normVol * 100)

float avgVol = ta.sma(volume, 50)
bool isSigStreak = sigVolMult == 0 or (volume > avgVol * sigVolMult)

// Volume Color Mode Logic
color regularVolColor = isBull ? colorUp : colorDown
color baseVolColor    = regularVolColor
color volColor        = color.new(baseVolColor, transp)
color bColor          = color.new(borderCol, transp)

// Box width calculation based on time
float changeTime = ta.change(time)
float medTimeDiff = ta.median(changeTime, 10)
int timeDiff = na(medTimeDiff) ? int(nz(changeTime, 0)) : int(medTimeDiff)
int halfWidth = math.round((timeDiff / 2) * barWidth)
int leftTime = time - halfWidth
int rightTime = time + halfWidth

// Volume streak logic
var int volStreak = 0
if plotCond
    if newSessTrigger
        volStreak := 0
    else if vol > nz(vol[1])
        volStreak := volStreak > 0 ? volStreak + 1 : 2
    else if vol < nz(vol[1])
        volStreak := volStreak < 0 ? volStreak - 1 : -2
    else
        volStreak := 0
else
    volStreak := 0

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
var SessProfile vp1 = SessProfile.new(array.new_float(), array.new_float(), array.new_box(), na, na)
var SessProfile vp2 = SessProfile.new(array.new_float(), array.new_float(), array.new_box(), na, na)
var SessProfile vp3 = SessProfile.new(array.new_float(), array.new_float(), array.new_box(), na, na)
var SessProfile vp4 = SessProfile.new(array.new_float(), array.new_float(), array.new_box(), na, na)

var box b1 = na, var box b1_g = na, var float t1 = na, var float bot1 = na, var int lT1 = na, var label lbl1 = na
var box b2 = na, var box b2_g = na, var float t2 = na, var float bot2 = na, var int lT2 = na, var label lbl2 = na
var box b3 = na, var box b3_g = na, var float t3 = na, var float bot3 = na, var int lT3 = na, var label lbl3 = na
var box b4 = na, var box b4_g = na, var float t4 = na, var float bot4 = na, var int lT4 = na, var label lbl4 = na

float pad = priceScale * 2.5
float maxSessVal = math.max(high, math.max(y1, y2)) + pad
float minSessVal = math.min(low,  math.min(y1, y2)) - pad

if inSess1 and not (inSess1[1] == true)
    t1   := maxSessVal
    bot1 := minSessVal
    lT1  := leftTime
    vp1.reset()
    vp1.addData(close, vol, high, low)
    float lblY1 = showGradBar ? t1 + (priceScale * (1.0 + gradHeight)) : t1
    b1_g := box.new(lT1, t1, rightTime, bot1, xloc=xloc.bar_time, border_color=color.new(borderCol, 85), border_style=line.style_solid, border_width=4, bgcolor=color.new(borderCol, 95)).track(currentVisuals)
    b1   := box.new(lT1, t1, rightTime, bot1, xloc=xloc.bar_time, border_color=color.new(borderCol, 30), border_style=line.style_dashed, border_width=1, bgcolor=na).track(currentVisuals)
    lbl1 := label.new(int(math.avg(lT1, rightTime)), lblY1, text="New York", xloc=xloc.bar_time, color=color.new(color.black, 100), textcolor=color.new(chart.fg_color, 30), style=label.style_label_down, size=size.small).track(currentVisuals)
else if inSess1
    t1   := math.max(t1, maxSessVal)
    bot1 := math.min(bot1, minSessVal)
    vp1.addData(close, vol, high, low)
    if not na(b1)
        float lblY1 = showGradBar ? t1 + (priceScale * (1.0 + gradHeight)) : t1
        box.set_right(b1_g, rightTime)
        box.set_top(b1_g, t1)
        box.set_bottom(b1_g, bot1)
        box.set_right(b1, rightTime)
        box.set_top(b1, t1)
        box.set_bottom(b1, bot1)
        label.set_xy(lbl1, int(math.avg(lT1, rightTime)), lblY1)

if showVP and inSess1
    vp1.drawProfile(rightTime, lT1, vpColor, vpBins, vpWidth, currentVisuals)

if inSess2 and not (inSess2[1] == true)
    t2   := maxSessVal
    bot2 := minSessVal
    lT2  := leftTime
    vp2.reset()
    vp2.addData(close, vol, high, low)
    float lblY2 = showGradBar ? t2 + (priceScale * (1.0 + gradHeight)) : t2
    b2_g := box.new(lT2, t2, rightTime, bot2, xloc=xloc.bar_time, border_color=color.new(borderCol, 85), border_style=line.style_solid, border_width=4, bgcolor=color.new(borderCol, 95)).track(currentVisuals)
    b2   := box.new(lT2, t2, rightTime, bot2, xloc=xloc.bar_time, border_color=color.new(borderCol, 30), border_style=line.style_dashed, border_width=1, bgcolor=na).track(currentVisuals)
    lbl2 := label.new(int(math.avg(lT2, rightTime)), lblY2, text="London", xloc=xloc.bar_time, color=color.new(color.black, 100), textcolor=color.new(chart.fg_color, 30), style=label.style_label_down, size=size.small).track(currentVisuals)
else if inSess2
    t2   := math.max(t2, maxSessVal)
    bot2 := math.min(bot2, minSessVal)
    vp2.addData(close, vol, high, low)
    if not na(b2)
        float lblY2 = showGradBar ? t2 + (priceScale * (1.0 + gradHeight)) : t2
        box.set_right(b2_g, rightTime)
        box.set_top(b2_g, t2)
        box.set_bottom(b2_g, bot2)
        box.set_right(b2, rightTime)
        box.set_top(b2, t2)
        box.set_bottom(b2, bot2)
        label.set_xy(lbl2, int(math.avg(lT2, rightTime)), lblY2)

if showVP and inSess2
    vp2.drawProfile(rightTime, lT2, vpColor, vpBins, vpWidth, currentVisuals)

if inSess3 and not (inSess3[1] == true)
    t3   := maxSessVal
    bot3 := minSessVal
    lT3  := leftTime
    vp3.reset()
    vp3.addData(close, vol, high, low)
    float lblY3 = showGradBar ? t3 + (priceScale * (1.0 + gradHeight)) : t3
    b3_g := box.new(lT3, t3, rightTime, bot3, xloc=xloc.bar_time, border_color=color.new(borderCol, 85), border_style=line.style_solid, border_width=4, bgcolor=color.new(borderCol, 95)).track(currentVisuals)
    b3   := box.new(lT3, t3, rightTime, bot3, xloc=xloc.bar_time, border_color=color.new(borderCol, 30), border_style=line.style_dashed, border_width=1, bgcolor=na).track(currentVisuals)
    lbl3 := label.new(int(math.avg(lT3, rightTime)), lblY3, text="Tokyo", xloc=xloc.bar_time, color=color.new(color.black, 100), textcolor=color.new(chart.fg_color, 30), style=label.style_label_down, size=size.small).track(currentVisuals)
else if inSess3
    t3   := math.max(t3, maxSessVal)
    bot3 := math.min(bot3, minSessVal)
    vp3.addData(close, vol, high, low)
    if not na(b3)
        float lblY3 = showGradBar ? t3 + (priceScale * (1.0 + gradHeight)) : t3
        box.set_right(b3_g, rightTime)
        box.set_top(b3_g, t3)
        box.set_bottom(b3_g, bot3)
        box.set_right(b3, rightTime)
        box.set_top(b3, t3)
        box.set_bottom(b3, bot3)
        label.set_xy(lbl3, int(math.avg(lT3, rightTime)), lblY3)

if showVP and inSess3
    vp3.drawProfile(rightTime, lT3, vpColor, vpBins, vpWidth, currentVisuals)

if inSess4 and not (inSess4[1] == true)
    t4   := maxSessVal
    bot4 := minSessVal
    lT4  := leftTime
    vp4.reset()
    vp4.addData(close, vol, high, low)
    float lblY4 = showGradBar ? t4 + (priceScale * (1.0 + gradHeight)) : t4
    b4_g := box.new(lT4, t4, rightTime, bot4, xloc=xloc.bar_time, border_color=color.new(borderCol, 85), border_style=line.style_solid, border_width=4, bgcolor=color.new(borderCol, 95)).track(currentVisuals)
    b4   := box.new(lT4, t4, rightTime, bot4, xloc=xloc.bar_time, border_color=color.new(borderCol, 30), border_style=line.style_dashed, border_width=1, bgcolor=na).track(currentVisuals)
    lbl4 := label.new(int(math.avg(lT4, rightTime)), lblY4, text="Sydney", xloc=xloc.bar_time, color=color.new(color.black, 100), textcolor=color.new(chart.fg_color, 30), style=label.style_label_down, size=size.small).track(currentVisuals)
else if inSess4
    t4   := math.max(t4, maxSessVal)
    bot4 := math.min(bot4, minSessVal)
    vp4.addData(close, vol, high, low)
    if not na(b4)
        float lblY4 = showGradBar ? t4 + (priceScale * (1.0 + gradHeight)) : t4
        box.set_right(b4_g, rightTime)
        box.set_top(b4_g, t4)
        box.set_bottom(b4_g, bot4)
        box.set_right(b4, rightTime)
        box.set_top(b4, t4)
        box.set_bottom(b4, bot4)
        label.set_xy(lbl4, int(math.avg(lT4, rightTime)), lblY4)

if showVP and inSess4
    vp4.drawProfile(rightTime, lT4, vpColor, vpBins, vpWidth, currentVisuals)


plot(ma, "Moving Average", color=plotCond ? heatColor : maColor, linewidth=1)

if not na(ma) and not na(volHeight) and plotCond
    box.new(leftTime, y1, rightTime, y2, xloc=xloc.bar_time, border_color=bColor, border_width=1, bgcolor=volColor).track(currentVisuals)

var box streakBox = na
var label streakLabel = na

if plotCond
    if math.abs(volStreak) >= consecBars
        if na(streakBox) and isSigStreak
            int startIdx = math.abs(volStreak) - 1
            float maxTop = math.max(y1[startIdx], y2[startIdx])
            float minBot = math.min(y1[startIdx], y2[startIdx])
            for i = 0 to startIdx
                maxTop := math.max(maxTop, math.max(y1[i], y2[i]))
                minBot := math.min(minBot, math.min(y1[i], y2[i]))
            streakBox := box.new(leftTime[startIdx], maxTop, rightTime, minBot, xloc=xloc.bar_time, border_color=color.new(chart.fg_color, 20), border_style=line.style_dashed, border_width=2, bgcolor=na).track(currentVisuals)
            
            string txt = (volStreak > 0 ? "Inc: " : "Dec: ") + str.tostring(math.abs(volStreak))
            streakLabel := label.new(int(math.avg(leftTime[startIdx], rightTime)), maxTop, txt, xloc=xloc.bar_time, color=color(na), textcolor=chart.fg_color, style=label.style_label_down, size=size.small).track(currentVisuals)
        else if not na(streakBox)
            float currentTop = box.get_top(streakBox)
            float currentBot = box.get_bottom(streakBox)
            float newTop = math.max(currentTop, math.max(y1, y2))
            
            box.set_right(streakBox, rightTime)
            box.set_top(streakBox, newTop)
            box.set_bottom(streakBox, math.min(currentBot, math.min(y1, y2)))
            
            string txt = (volStreak > 0 ? "Inc: " : "Dec: ") + str.tostring(math.abs(volStreak))
            int avgT = int(math.avg(box.get_left(streakBox), rightTime))
            label.set_xy(streakLabel, avgT, newTop)
            label.set_text(streakLabel, txt)
    else
        streakBox := na
        streakLabel := na


//---------------------------------------------------------------------------------------------------------------------}
// Gradient Bar on Chart
//---------------------------------------------------------------------------------------------------------------------{
var box[] currentGradBoxes = na
var label currentGradLabel = na

if showGradBar
    if newSession
        currentGradBoxes := array.new_box()
        for i = 0 to 49
            box gBox = box.new(na, na, na, na, xloc=xloc.bar_time, border_width=0).track(currentVisuals)
            array.push(currentGradBoxes, gBox)
        currentGradLabel := label.new(na, na, "", xloc=xloc.bar_time, style=label.style_label_down, textcolor=color.white, color=color(na), size=size.small).track(currentVisuals)

    if inSession and not na(currentGradBoxes)
        int sLeft = na
        float sTop = na
        if inSess1
            sLeft := lT1
            sTop := t1
        else if inSess2
            sLeft := lT2
            sTop := t2
        else if inSess3
            sLeft := lT3
            sTop := t3
        else if inSess4
            sLeft := lT4
            sTop := t4

        if not na(sLeft) and not na(sTop)
            float barBottom = sTop + (priceScale * 0.5)
            float barTop    = sTop + (priceScale * 0.5) + (priceScale * gradHeight)
            float timeSpan  = rightTime - sLeft
            
            int pointerVal = math.round(deltaPercent / 2)
            pointerVal := math.max(0, math.min(50, pointerVal))
            int pointerTime = sLeft + math.round((timeSpan / 50) * pointerVal)

            for i = 0 to 49
                color c = i < 25 ? color.from_gradient(i, 0, 25, colorDown, gradMidCol) : color.from_gradient(i, 25, 49, gradMidCol, colorUp)
                
                int bLeft  = sLeft + math.round((timeSpan / 50) * i)
                int bRight = sLeft + math.round((timeSpan / 50) * (i + 1))
                
                box bx = array.get(currentGradBoxes, i)
                box.set_lefttop(bx, bLeft, barTop)
                box.set_rightbottom(bx, bRight, barBottom)
                box.set_bgcolor(bx, c)
                
            label.set_xy(currentGradLabel, pointerTime, barTop)
            label.set_color(currentGradLabel, heatColor)

barcolor(colorCandles and plotCond ? heatColor : na)

//---------------------------------------------------------------------------------------------------------------------}