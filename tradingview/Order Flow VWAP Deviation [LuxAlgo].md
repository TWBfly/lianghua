// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Order Flow VWAP Deviation [LuxAlgo]", "LuxAlgo - Order Flow VWAP Deviation", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Groups
//---------------------------------------------------------------------------------------------------------------------{
string G_VWAP = "VWAP Settings"
string G_STOP = "Stop Zones (Pivots)"
string G_VP   = "Volume Profile & Stop Zones"
string G_IFVG = "Inversion Fair Value Gaps (IFVGs)"

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
vwapAnchor     = input.string("Session", "VWAP Anchor", options = ["Session", "Week", "Month", "Year"], group = G_VWAP)
stdDevMult     = input.float(2.0, "Std. Dev Multiplier", minval = 0.5, step = 0.1, group = G_VWAP)

pivotLookback  = input.int(50, "Pivot Lookback (Stop Zones)", minval = 10, group = G_STOP)
maxActiveLines = input.int(10, "Max Active Lines", minval = 1, maxval = 50, group = G_STOP)

// VP Inputs
vpRows         = input.int(50, "Profile Rows", minval = 10, maxval = 100, group = G_VP)
vpWidth        = input.int(30, "Profile Max Width (Bars)", minval = 5, group = G_VP)
vpOffset       = input.int(10, "Profile Right Offset", minval = 0, group = G_VP)
sessionAnchor  = input.string("1800-1801", "Anchor Time Range (HHMM-HHMM)", group = G_VP)
sessionTz      = input.string("GMT-4", "Timezone", options = ["GMT-5", "GMT-4", "UTC"], group = G_VP)
stopThreshold  = input.float(1.5, "Stop Zone Volume Multiplier", minval = 1.0, step = 0.1, group = G_VP)

// IFVG Inputs
showIFVG       = input.bool(false, "Show IFVGs", group = G_IFVG)
ifvgVolFilter  = input.float(1.2, "IFVG Volatility Filter", minval = 0.5, step = 0.1, group = G_IFVG)
ifvgHistory    = input.int(5, "Max Active IFVGs", minval = 1, maxval = 20, group = G_IFVG)

//---------------------------------------------------------------------------------------------------------------------}
// VWAP Calculation
//---------------------------------------------------------------------------------------------------------------------{
isNewVwapPeriod = switch vwapAnchor
    "Session" => timeframe.change("D")
    "Week"    => timeframe.change("W")
    "Month"   => timeframe.change("M")
    "Year"    => timeframe.change("12M")
    => false

[vValue, vUpper, vLower] = ta.vwap(hlc3, isNewVwapPeriod, stdDevMult)

//---------------------------------------------------------------------------------------------------------------------}
// Significant Pivot Logic (Stop Lines)
//---------------------------------------------------------------------------------------------------------------------{
ph = ta.pivothigh(high, pivotLookback, pivotLookback)
pl = ta.pivotlow(low, pivotLookback, pivotLookback)

var line[] upperLines = array.new_line()
var line[] lowerLines = array.new_line()

if not na(ph)
    newLine = line.new(bar_index - pivotLookback, ph, bar_index, ph, color = color.new(#f23645, 60), style = line.style_dashed)
    array.unshift(upperLines, newLine)
    if array.size(upperLines) > maxActiveLines
        line.delete(array.pop(upperLines))

if not na(pl)
    newLine = line.new(bar_index - pivotLookback, pl, bar_index, pl, color = color.new(#089981, 60), style = line.style_dashed)
    array.unshift(lowerLines, newLine)
    if array.size(lowerLines) > maxActiveLines
        line.delete(array.pop(lowerLines))

// Line Update & Stop Trigger Detection
avgVol20 = ta.sma(volume, 20)
var bool stopTriggeredUpper = false
var bool stopTriggeredLower = false
stopTriggeredUpper := false
stopTriggeredLower := false

if array.size(upperLines) > 0
    for i = array.size(upperLines) - 1 to 0
        l = array.get(upperLines, i)
        if high >= line.get_y1(l)
            if volume > avgVol20 * 1.2
                stopTriggeredUpper := true
            line.set_x2(l, bar_index)
            array.remove(upperLines, i)
        else
            line.set_x2(l, bar_index)

if array.size(lowerLines) > 0
    for i = array.size(lowerLines) - 1 to 0
        l = array.get(lowerLines, i)
        if low <= line.get_y1(l)
            if volume > avgVol20 * 1.2
                stopTriggeredLower := true
            line.set_x2(l, bar_index)
            array.remove(lowerLines, i)
        else
            line.set_x2(l, bar_index)

//---------------------------------------------------------------------------------------------------------------------}
// IFVG Logic
//---------------------------------------------------------------------------------------------------------------------{
avgBody = ta.sma(math.abs(close - open), 50)
volatilityValid = math.abs(close[1] - open[1]) > avgBody * ifvgVolFilter

bearFVG = volatilityValid and high < low[2]
bullFVG = volatilityValid and low > high[2]

var float[] activeBearFvgTop = array.new_float()
var float[] activeBearFvgBtm = array.new_float()
var int[]   activeBearFvgBar = array.new_int()

var float[] activeBullFvgTop = array.new_float()
var float[] activeBullFvgBtm = array.new_float()
var int[]   activeBullFvgBar = array.new_int()

if showIFVG
    if bearFVG
        array.unshift(activeBearFvgTop, low[2])
        array.unshift(activeBearFvgBtm, high)
        array.unshift(activeBearFvgBar, bar_index[1])
    if bullFVG
        array.unshift(activeBullFvgTop, low)
        array.unshift(activeBullFvgBtm, high[2])
        array.unshift(activeBullFvgBar, bar_index[1])

var box[]  ifvgBoxes  = array.new_box()
var label[] ifvgLabels = array.new_label()
var bool[]  ifvgIsBull = array.new_bool()

if showIFVG
    // Bearish FVGs for Bullish Inversion
    if array.size(activeBearFvgTop) > 0
        for i = array.size(activeBearFvgTop) - 1 to 0
            top = array.get(activeBearFvgTop, i)
            btm = array.get(activeBearFvgBtm, i)
            if close > top
                startBar = array.get(activeBearFvgBar, i)
                newBox   = box.new(startBar, top, bar_index + 10, btm, bgcolor = color.new(#089981, 85), border_color = color.new(#089981, 60))
                newLabel = label.new(bar_index, (top + btm) / 2, "IFVG", color = #00000000, textcolor = #089981, style = label.style_label_center, size = size.small)
                array.unshift(ifvgBoxes, newBox)
                array.unshift(ifvgLabels, newLabel)
                array.unshift(ifvgIsBull, true)
                array.remove(activeBearFvgTop, i)
                array.remove(activeBearFvgBtm, i)
                array.remove(activeBearFvgBar, i)
                if array.size(ifvgBoxes) > ifvgHistory
                    box.delete(array.pop(ifvgBoxes))
                    label.delete(array.pop(ifvgLabels))
                    array.pop(ifvgIsBull)

    // Bullish FVGs for Bearish Inversion
    if array.size(activeBullFvgTop) > 0
        for i = array.size(activeBullFvgTop) - 1 to 0
            top = array.get(activeBullFvgTop, i)
            btm = array.get(activeBullFvgBtm, i)
            if close < btm
                startBar = array.get(activeBullFvgBar, i)
                newBox   = box.new(startBar, top, bar_index + 10, btm, bgcolor = color.new(#f23645, 85), border_color = color.new(#f23645, 60))
                newLabel = label.new(bar_index, (top + btm) / 2, "IFVG", color = #00000000, textcolor = #f23645, style = label.style_label_center, size = size.small)
                array.unshift(ifvgBoxes, newBox)
                array.unshift(ifvgLabels, newLabel)
                array.unshift(ifvgIsBull, false)
                array.remove(activeBullFvgTop, i)
                array.remove(activeBullFvgBtm, i)
                array.remove(activeBullFvgBar, i)
                if array.size(ifvgBoxes) > ifvgHistory
                    box.delete(array.pop(ifvgBoxes))
                    label.delete(array.pop(ifvgLabels))
                    array.pop(ifvgIsBull)

// Mitigation Logic
if array.size(ifvgBoxes) > 0
    for i = array.size(ifvgBoxes) - 1 to 0
        b      = array.get(ifvgBoxes, i)
        l      = array.get(ifvgLabels, i)
        isBull = array.get(ifvgIsBull, i)
        top    = box.get_top(b)
        btm    = box.get_bottom(b)
        
        mitigated = isBull ? close < btm : close > top
        
        if mitigated
            box.delete(b)
            label.delete(l)
            array.remove(ifvgBoxes, i)
            array.remove(ifvgLabels, i)
            array.remove(ifvgIsBull, i)
        else
            if bar_index < box.get_right(b)
                box.set_right(b, bar_index + 5)

//---------------------------------------------------------------------------------------------------------------------}
// Forward Volume Collection
//---------------------------------------------------------------------------------------------------------------------{
t = time(timeframe.period, sessionAnchor, sessionTz)
isAnchorBar = not na(t) and na(t[1])
var float[] sessionPrices = array.new_float()
var float[] sessionVolumes = array.new_float()
var float[] sessionBuyVols = array.new_float()
var float[] sessionSellVols = array.new_float()

if isAnchorBar
    array.clear(sessionPrices)
    array.clear(sessionVolumes)
    array.clear(sessionBuyVols)
    array.clear(sessionSellVols)

// Proxy for Buyer/Seller Volume
float range_val = math.max(high - low, syminfo.mintick)
float bVol = volume * (close - low) / range_val
float sVol = volume * (high - close) / range_val

array.push(sessionPrices, close)
array.push(sessionVolumes, volume)
array.push(sessionBuyVols, bVol)
array.push(sessionSellVols, sVol)

bgcolor(isAnchorBar ? color.new(color.yellow, 80) : na)

//---------------------------------------------------------------------------------------------------------------------}
// Profile Visualization
//---------------------------------------------------------------------------------------------------------------------{
var box[]   profileBoxes  = array.new_box()
var label[] profileLabels = array.new_label()

if barstate.islast and array.size(sessionPrices) > 0
    float sHigh = array.get(sessionPrices, 0)
    float sLow  = array.get(sessionPrices, 0)
    for p in sessionPrices
        sHigh := math.max(sHigh, p)
        sLow  := math.min(sLow, p)
    
    float[] binVols = array.new_float(vpRows, 0.0)
    float[] binBuyVols = array.new_float(vpRows, 0.0)
    float[] binSellVols = array.new_float(vpRows, 0.0)
    float bSize = (sHigh - sLow) / vpRows
    
    if bSize > 0
        for i = 0 to array.size(sessionPrices) - 1
            float p = array.get(sessionPrices, i)
            float v = array.get(sessionVolumes, i)
            float bv = array.get(sessionBuyVols, i)
            float sv = array.get(sessionSellVols, i)
            int bIdx = math.min(vpRows - 1, math.max(0, math.floor((p - sLow) / bSize)))
            array.set(binVols, bIdx, array.get(binVols, bIdx) + v)
            array.set(binBuyVols, bIdx, array.get(binBuyVols, bIdx) + bv)
            array.set(binSellVols, bIdx, array.get(binSellVols, bIdx) + sv)
        
        if array.size(profileBoxes) > 0
            for i = 0 to array.size(profileBoxes) - 1
                box.delete(array.get(profileBoxes, i))
            array.clear(profileBoxes)
        if array.size(profileLabels) > 0
            for i = 0 to array.size(profileLabels) - 1
                label.delete(array.get(profileLabels, i))
            array.clear(profileLabels)
        
        maxV   = 0.0
        totalV = 0.0
        pIdx   = 0
        for i = 0 to vpRows - 1
            v = array.get(binVols, i)
            totalV += v
            if v > maxV
                maxV := v
                pIdx := i
        
        avgV = totalV / vpRows
        for i = 0 to vpRows - 1
            v = array.get(binVols, i)
            if v > 0
                nW = (v / maxV) * vpWidth
                isStop = v > avgV * stopThreshold
                binColor = i == pIdx ? color.new(#FFEB3B, 10) : isStop ? color.new(#ff9800, 30) : color.new(#5b9cf6, 60)
                
                t_box = sLow + (i + 1) * bSize
                b_box = sLow + i * bSize
                l_box = bar_index + vpOffset
                r_box = l_box + math.round(nW)
                array.push(profileBoxes, box.new(l_box, t_box, r_box, b_box, border_color = color.new(chart.bg_color, 100), bgcolor = binColor))
                
                if isStop or i == pIdx
                    diffMult = v / avgV
                    bv = array.get(binBuyVols, i)
                    sv = array.get(binSellVols, i)
                    
                    y_center = (t_box + b_box) / 2
                    multColor = i == pIdx ? #FFEB3B : #ff9800
                    
                    // Multiplier + Dominant Side combined in one label with multiple colors is not possible for standard labels.
                    // Instead, we position the "B" or "S" label to the right of the multiplier label.
                    
                    // 1. Draw Multiplier Label
                    multTxt = str.format("{0,number,#.#}x", diffMult)
                    multLabel = label.new(r_box, y_center, multTxt, xloc.bar_index, yloc.price, color.new(chart.bg_color, 100), label.style_label_left, multColor, size.tiny)
                    array.push(profileLabels, multLabel)
                    
                    // 2. Position the Side Label (B/S) after the 'x'
                    // We can estimate the spacing based on the multiplier string length.
                    sideTxt = bv > sv ? "B" : "S"
                    sideColor = bv > sv ? #089981 : #f23645
                    
                    // Using a small offset for the second label
                    sideLabel = label.new(r_box + 3, y_center, sideTxt, xloc.bar_index, yloc.price, color.new(chart.bg_color, 100), label.style_label_left, sideColor, size.tiny)
                    array.push(profileLabels, sideLabel)

//---------------------------------------------------------------------------------------------------------------------}
// Plots
//---------------------------------------------------------------------------------------------------------------------{
plot(vValue, "VWAP", color.new(chart.fg_color, 50))
pUp = plot(vUpper, "Upper Band", color.new(#f23645, 0))
pLo = plot(vLower, "Lower Band", color.new(#089981, 0))
fill(pUp, plot(vValue), vUpper, vValue, color.new(#f23645, 90), color.new(#f23645, 100))
fill(pLo, plot(vValue), vLower, vValue, color.new(#089981, 90), color.new(#089981, 100))

plotshape(stopTriggeredUpper, "Stops Triggered High", shape.circle, location.abovebar, color.new(#f23645, 50), size = size.tiny)
plotshape(stopTriggeredLower, "Stops Triggered Low", shape.circle, location.belowbar, color.new(#089981, 50), size = size.tiny)

//---------------------------------------------------------------------------------------------------------------------}
