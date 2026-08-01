// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("kNN Market Architecture [LuxAlgo]", "LuxAlgo - kNN Market Architecture", overlay = true, max_labels_count = 500, max_lines_count = 500, max_boxes_count = 500, max_bars_back = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Inputs
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR      = #089981 // Green (Resistance High)
color BEAR_COLOR      = #f23645 // Red (Support Low)
color NEUTRAL_COLOR   = #787b86

sensitivityInput  = input.int(5, "Structure Sensitivity", minval = 1, maxval = 10, group = "Dynamic Engine")
autoSensitivity   = input.bool(true, "Auto-Adjust Sensitivity", group = "Dynamic Engine")

knnKInput         = input.int(5, "k-Nearest Neighbors", minval = 1, maxval = 20, group = "kNN Classifier")
minConfidence     = input.float(0.4, "Confidence Threshold", minval = 0.0, maxval = 1.0, step = 0.1, group = "kNN Classifier")

showST            = input.bool(true, "Short-Term Lines (ST)", group = "Visual Hierarchy")
showMT            = input.bool(true, "Medium-Term Lines (MT)", group = "Visual Hierarchy")
showLT            = input.bool(true, "Long-Term Lines (LT)", group = "Visual Hierarchy")
colorCandlesInput = input.bool(true, "Color Candles by Bias", group = "Visual Hierarchy")
biasSourceInput   = input.string("Auto", "Bias Source", options = ["Auto", "LT", "MT", "ST", "None"], group = "Visual Hierarchy")
infoLabelSize     = input.string("Small", "Info Label Size", options = ["Tiny", "Small", "Normal", "Large"], group = "Visual Hierarchy")
showDeltaTankInput = input.bool(true, "Show Delta Tank", group = "Visual Hierarchy")

stLabelsInput     = input.bool(true, "Show ST Icons", inline = "ST", group = "Visual Hierarchy")
stLabelInput      = input.string("•", "Icon", inline = "ST", group = "Visual Hierarchy")
stSizeInput       = input.string("Tiny", "Size", options = ["Tiny", "Small", "Normal", "Large"], inline = "ST", group = "Visual Hierarchy")
stBOSInput        = input.string("Tiny", "ST BOS Size", options = ["None", "Tiny", "Small", "Normal", "Large"], group = "Visual Hierarchy")

mtLabelsInput     = input.bool(false, "Show MT Icons", inline = "MT", group = "Visual Hierarchy")
mtLabelInput      = input.string("•", "Icon", inline = "MT", group = "Visual Hierarchy")
mtSizeInput       = input.string("Small", "Size", options = ["Tiny", "Small", "Normal", "Large"], inline = "MT", group = "Visual Hierarchy")
mtBOSInput        = input.string("None", "MT BOS Size", options = ["None", "Tiny", "Small", "Normal", "Large"], group = "Visual Hierarchy")

ltLabelsInput     = input.bool(true, "Show LT Icons", inline = "LT", group = "Visual Hierarchy")
ltLabelInput      = input.string("●", "Icon", inline = "LT", group = "Visual Hierarchy")
ltSizeInput       = input.string("Normal", "Size", options = ["Tiny", "Small", "Normal", "Large"], inline = "LT", group = "Visual Hierarchy")
ltBOSInput        = input.string("Normal", "LT BOS Size", options = ["None", "Tiny", "Small", "Normal", "Large"], group = "Visual Hierarchy")

offsetMultiplier  = input.float(0.8, "Label Offset Multiplier", minval = 0.0, maxval = 5.0, step = 0.1, group = "Visual Hierarchy")

showVP            = input.bool(true, "Show Volume Profile", group = "Volume Profile")
vpRows            = input.int(30, "Profile Rows", minval = 10, maxval = 100, group = "Volume Profile")
vpWidth           = input.int(50, "Profile Width (%)", minval = 10, maxval = 100, group = "Volume Profile")
vpOffset          = input.int(50, "Profile Offset", minval = 0, maxval = 500, group = "Volume Profile")

//---------------------------------------------------------------------------------------------------------------------}
// Types & Methods
//---------------------------------------------------------------------------------------------------------------------{
type StructurePoint
    float price
    int   index
    string term 
    float feat1 
    float feat2 
    float score 

type LineMetadata
    int   startBar
    float startPrice
    label infoLabel
    float cumVol = 0.0
    float cumDelta = 0.0

method getDistance(StructurePoint p1, StructurePoint p2) =>
    math.abs(p1.feat1 - p2.feat1) + math.abs(p1.feat2 - p2.feat2)

//---------------------------------------------------------------------------------------------------------------------}
// Dynamic Detection Engine
//---------------------------------------------------------------------------------------------------------------------{
float atr = ta.atr(200)
float avgAtr = ta.sma(atr, 200)
float volRatio = atr / nz(avgAtr, atr)
float smoothedRatio = ta.ema(volRatio, 50) 

float dynamicMultiplier = autoSensitivity ? math.pow(nz(smoothedRatio, 1.0), 1.5) : 1.0
int baseLen = math.max(3, math.round((11 - sensitivityInput) * dynamicMultiplier))

f_detect_pivots(len) =>
    ph = ta.pivothigh(high, len, len)
    pl = ta.pivotlow(low, len, len)
    [ph, pl]

f_knn_score(StructurePoint current, array<StructurePoint> history, int k) =>
    float score = 0.0
    if history.size() > k
        array<float> distances = array.new_float(0)
        for p in history
            distances.push(current.getDistance(p))
        array<int> ranks = array.new_int(0)
        for i = 0 to history.size() - 1
            ranks.push(i)
        for i = 0 to k - 1
            for j = i + 1 to history.size() - 1
                if distances.get(ranks.get(j)) < distances.get(ranks.get(i))
                    temp = ranks.get(i)
                    ranks.set(i, ranks.get(j))
                    ranks.set(j, temp)
        float sumScore = 0.0
        for i = 0 to k - 1
            sumScore += history.get(ranks.get(i)).score
        score := sumScore / k
    else
        score := 0.5 
    score

//---------------------------------------------------------------------------------------------------------------------}
// Core Execution
//---------------------------------------------------------------------------------------------------------------------{
var stHistoryHigh = array.new<StructurePoint>(0), var stHistoryLow  = array.new<StructurePoint>(0)
var mtHistoryHigh = array.new<StructurePoint>(0), var mtHistoryLow  = array.new<StructurePoint>(0)
var ltHistoryHigh = array.new<StructurePoint>(0), var ltHistoryLow  = array.new<StructurePoint>(0)

var float lastSTHigh = na, var float lastSTLow = na
var float lastMTHigh = na, var float lastMTLow = na
var float lastLTHigh = na, var float lastLTLow = na

var line activeSTHigh = na, var line activeSTLow = na
var line activeMTHigh = na, var line activeMTLow = na
var line activeLTHigh = na, var line activeLTLow = na

// Generic Metadata for the "Active Term"
var LineMetadata activeMetaHigh = na
var LineMetadata activeMetaLow  = na

float relVol = volume / ta.sma(volume, 100)
atr14 = ta.atr(14)
float relATR = atr14 / ta.sma(atr14, 100)

// Define Active Term Hierarchy
string activeTerm = biasSourceInput == "None" ? "" : (biasSourceInput != "Auto" ? biasSourceInput : (showLT ? "LT" : showMT ? "MT" : showST ? "ST" : ""))

f_parse_size(s) =>
    switch s
        "Tiny"   => size.tiny
        "Small"  => size.small
        "Normal" => size.normal
        "Large"  => size.large
        => size.small

parsedLabelSize = switch infoLabelSize
    "Tiny"   => size.tiny
    "Small"  => size.small
    "Normal" => size.normal
    "Large"  => size.large

f_process_term(float ph, float pl, int len, string term, array<StructurePoint> hHigh, array<StructurePoint> hLow, line activeH, line activeL, bool showLines, bool showLabels) =>
    line outH = activeH
    line outL = activeL
    bool phTriggered = false
    bool plTriggered = false
    
    float visualOffset = atr14 * offsetMultiplier
    
    currentSize = term == "LT" ? f_parse_size(ltSizeInput) : term == "MT" ? f_parse_size(mtSizeInput) : f_parse_size(stSizeInput)
    currentText = term == "LT" ? ltLabelInput : term == "MT" ? mtLabelInput : stLabelInput
    string lStyle = term == "LT" ? line.style_solid : term == "MT" ? line.style_dashed : line.style_dotted

    if not na(ph)
        current = StructurePoint.new(ph, bar_index[len], term, relATR[len], relVol[len], 1.0)
        bool isValid = f_knn_score(current, hHigh, knnKInput) >= minConfidence
        if isValid
            if showLabels
                y = ph + visualOffset
                label.new(bar_index[len], y, currentText, style = label.style_none, textcolor = BULL_COLOR, size = currentSize)
            
            if showLines
                if not na(outH) 
                    outH.delete()
                outH := line.new(bar_index[len], ph, bar_index, ph, color = BULL_COLOR, style = lStyle)
                phTriggered := true

        hHigh.push(current)
        if hHigh.size() > 100 
            hHigh.shift()

    if not na(pl)
        current = StructurePoint.new(pl, bar_index[len], term, relATR[len], relVol[len], 1.0)
        bool isValid = f_knn_score(current, hLow, knnKInput) >= minConfidence
        if isValid
            if showLabels
                y = pl - visualOffset
                label.new(bar_index[len], y, currentText, style = label.style_none, textcolor = BEAR_COLOR, size = currentSize)
            
            if showLines
                if not na(outL) 
                    outL.delete()
                outL := line.new(bar_index[len], pl, bar_index, pl, color = BEAR_COLOR, style = lStyle)
                plTriggered := true

        hLow.push(current)
        if hLow.size() > 100 
            hLow.shift()
    [outH, outL, phTriggered, plTriggered]

// Process Terms
[stPH, stPL] = f_detect_pivots(baseLen)
[newSTH, newSTL, stHT, stLT] = f_process_term(stPH, stPL, baseLen, "ST", stHistoryHigh, stHistoryLow, activeSTHigh, activeSTLow, showST, stLabelsInput)
activeSTHigh := newSTH, activeSTLow := newSTL
if stHT and activeTerm == "ST" and showDeltaTankInput
    if not na(activeMetaHigh)
        label.delete(activeMetaHigh.infoLabel)
    activeMetaHigh := LineMetadata.new(bar_index[baseLen], stPH, label.new(bar_index, stPH, "", style = label.style_label_left, color = color.new(BULL_COLOR, 30), textcolor = color.white, size = parsedLabelSize))
if stLT and activeTerm == "ST" and showDeltaTankInput
    if not na(activeMetaLow)
        label.delete(activeMetaLow.infoLabel)
    activeMetaLow := LineMetadata.new(bar_index[baseLen], stPL, label.new(bar_index, stPL, "", style = label.style_label_left, color = color.new(BEAR_COLOR, 30), textcolor = color.white, size = parsedLabelSize))

if not na(stPH)
    lastSTHigh := stPH
if not na(stPL)
    lastSTLow := stPL

mtLen = baseLen * 3
[mtPH, mtPL] = f_detect_pivots(mtLen)
[newMTH, newMTL, mtHT, mtLT] = f_process_term(mtPH, mtPL, mtLen, "MT", mtHistoryHigh, mtHistoryLow, activeMTHigh, activeMTLow, showMT, mtLabelsInput)
activeMTHigh := newMTH, activeMTLow := newMTL
if mtHT and activeTerm == "MT" and showDeltaTankInput
    if not na(activeMetaHigh)
        label.delete(activeMetaHigh.infoLabel)
    activeMetaHigh := LineMetadata.new(bar_index[mtLen], mtPH, label.new(bar_index, mtPH, "", style = label.style_label_left, color = color.new(BULL_COLOR, 30), textcolor = color.white, size = parsedLabelSize))
if mtLT and activeTerm == "MT" and showDeltaTankInput
    if not na(activeMetaLow)
        label.delete(activeMetaLow.infoLabel)
    activeMetaLow := LineMetadata.new(bar_index[mtLen], mtPL, label.new(bar_index, mtPL, "", style = label.style_label_left, color = color.new(BEAR_COLOR, 30), textcolor = color.white, size = parsedLabelSize))

if not na(mtPH)
    lastMTHigh := mtPH
if not na(mtPL)
    lastMTLow := mtPL

ltLen = mtLen * 3
[ltPH, ltPL] = f_detect_pivots(ltLen)
[newLTH, newLTL, ltHT, ltLT] = f_process_term(ltPH, ltPL, ltLen, "LT", ltHistoryHigh, ltHistoryLow, activeLTHigh, activeLTLow, showLT, ltLabelsInput)
activeLTHigh := newLTH, activeLTLow := newLTL
if ltHT and activeTerm == "LT" and showDeltaTankInput
    if not na(activeMetaHigh)
        label.delete(activeMetaHigh.infoLabel)
    activeMetaHigh := LineMetadata.new(bar_index[ltLen], ltPH, label.new(bar_index, ltPH, "", style = label.style_label_left, color = color.new(BULL_COLOR, 30), textcolor = color.white, size = parsedLabelSize))
if ltLT and activeTerm == "LT" and showDeltaTankInput
    if not na(activeMetaLow)
        label.delete(activeMetaLow.infoLabel)
    activeMetaLow := LineMetadata.new(bar_index[ltLen], ltPL, label.new(bar_index, ltPL, "", style = label.style_label_left, color = color.new(BEAR_COLOR, 30), textcolor = color.white, size = parsedLabelSize))

if not na(ltPH)
    lastLTHigh := ltPH
if not na(ltPL)
    lastLTLow := ltPL

// Metadata Accumulator Update
f_update_metadata(LineMetadata m) =>
    if not na(m) and not na(m.infoLabel)
        m.cumVol += volume
        m.cumDelta += (close > open ? volume : -volume)
        
        float fillRatio = math.max(0, math.min(1, math.abs(m.cumDelta) / math.max(1, m.cumVol)))
        int fillBlocks = math.round(fillRatio * 10)
        
        string barStr = ""
        for i = 1 to 10
            barStr += i <= fillBlocks ? "█" : "░"
            
        string icon = m.cumDelta >= 0 ? "▲" : "▼"
        color deltaColor = m.cumDelta >= 0 ? BULL_COLOR : BEAR_COLOR
        
        txt = " [ DELTA TANK ] \n" +
              "       " + icon + "       \n" +
              " " + barStr + " \n" +
              "       " + str.tostring(fillRatio * 100, "#") + "%       "
        
        m.infoLabel.set_text(txt)
        m.infoLabel.set_color(color.new(deltaColor, 30))
        m.infoLabel.set_textcolor(color.white)
        m.infoLabel.set_x(bar_index)

if not na(activeMetaHigh) 
    f_update_metadata(activeMetaHigh)
if not na(activeMetaLow) 
    f_update_metadata(activeMetaLow)

// Termination Logic
f_terminate_line(line l, color lineCol, string term, LineMetadata meta = na, string bosSize = "Small") =>
    line out = l
    if not na(l)
        isHigh = lineCol == BULL_COLOR
        broken = isHigh ? close > l.get_y1() : close < l.get_y1()
        if broken
            l.set_x2(bar_index)
            midX = math.round(math.avg(l.get_x1(), bar_index))
            bosCol = isHigh ? BULL_COLOR : BEAR_COLOR
            lblStyle = isHigh ? label.style_label_down : label.style_label_up
            if bosSize != "None"
                label.new(midX, l.get_y1(), term + " BOS", style = lblStyle, color = #00000000, textcolor = bosCol, size = f_parse_size(bosSize))
            if not na(meta) 
                label.delete(meta.infoLabel)
            out := na
        else
            l.set_x2(bar_index)
    out

activeSTHigh := f_terminate_line(activeSTHigh, BULL_COLOR, "ST", activeTerm == "ST" ? activeMetaHigh : na, stBOSInput)
activeSTLow  := f_terminate_line(activeSTLow, BEAR_COLOR, "ST", activeTerm == "ST" ? activeMetaLow : na, stBOSInput)
activeMTHigh := f_terminate_line(activeMTHigh, BULL_COLOR, "MT", activeTerm == "MT" ? activeMetaHigh : na, mtBOSInput)
activeMTLow  := f_terminate_line(activeMTLow, BEAR_COLOR, "MT", activeTerm == "MT" ? activeMetaLow : na, mtBOSInput)
activeLTHigh := f_terminate_line(activeLTHigh, BULL_COLOR, "LT", activeTerm == "LT" ? activeMetaHigh : na, ltBOSInput)
activeLTLow  := f_terminate_line(activeLTLow, BEAR_COLOR, "LT", activeTerm == "LT" ? activeMetaLow : na, ltBOSInput)

//---------------------------------------------------------------------------------------------------------------------}
// Hierarchy Logic for Coloring and Bias
//---------------------------------------------------------------------------------------------------------------------{
selectedHigh = activeTerm == "LT" ? lastLTHigh : activeTerm == "MT" ? lastMTHigh : activeTerm == "ST" ? lastSTHigh : na
selectedLow  = activeTerm == "LT" ? lastLTLow  : activeTerm == "MT" ? lastMTLow  : activeTerm == "ST" ? lastSTLow  : na

color candleColor = na
if not na(selectedHigh) and not na(selectedLow)
    float factor = (close - selectedLow) / math.max(1e-6, selectedHigh - selectedLow)
    candleColor := factor > 0.5 ? color.from_gradient(factor, 0.5, 1.0, NEUTRAL_COLOR, BULL_COLOR) : color.from_gradient(factor, 0.0, 0.5, BEAR_COLOR, NEUTRAL_COLOR)
    if close > selectedHigh
        candleColor := BULL_COLOR
    if close < selectedLow
        candleColor := BEAR_COLOR

barcolor(colorCandlesInput ? candleColor : na)

//---------------------------------------------------------------------------------------------------------------------}
// Volume Profile Logic (3D Visualization)
//---------------------------------------------------------------------------------------------------------------------{
if showVP and barstate.islast and not na(selectedHigh) and not na(selectedLow)
    int firstBar = math.max(0, bar_index - 499)
    if not na(activeMetaHigh) and not na(activeMetaLow)
        firstBar := math.max(firstBar, math.min(activeMetaHigh.startBar, activeMetaLow.startBar))
    
    int lookback = bar_index - firstBar
    float priceRange = selectedHigh - selectedLow
    float binStep = priceRange / vpRows
    
    var array<float> binVolumes = array.new_float(vpRows, 0.0)
    array.fill(binVolumes, 0.0)
    
    for i = 0 to lookback
        float p = close[i]
        float v = volume[i]
        if p >= selectedLow and p <= selectedHigh
            int binIdx = math.min(vpRows - 1, math.floor((p - selectedLow) / binStep))
            array.set(binVolumes, binIdx, array.get(binVolumes, binIdx) + v)
            
    float maxVol = array.max(binVolumes)
    int pocIdx = array.indexof(binVolumes, maxVol)
    
    var boxes = array.new<box>(0)
    for b in boxes
        box.delete(b)
    array.clear(boxes)
    
    for i = 0 to vpRows - 1
        float vol = array.get(binVolumes, i)
        if vol > 0
            float binBottom = selectedLow + (i * binStep)
            float binTop = binBottom + binStep
            
            int binWidth = math.round((vol / maxVol) * vpWidth)
            color baseColor = i == pocIdx ? NEUTRAL_COLOR : i > pocIdx ? BULL_COLOR : BEAR_COLOR
            
            int rightEdge = bar_index + vpOffset
            int leftEdge = rightEdge - binWidth
            
            // 3D Visual Elements: Body, Top Edge Highlight, and Leading Edge Shadow
            // Main Body
            boxes.push(box.new(leftEdge, binTop, rightEdge, binBottom, 
                         bgcolor = color.new(baseColor, 75), border_color = na))
            
            // Top Edge (Highlight) - create a thin box at the top of the bin
            float highlightHeight = binStep * 0.15
            boxes.push(box.new(leftEdge, binTop, rightEdge, binTop - highlightHeight, 
                         bgcolor = color.new(baseColor, 40), border_color = na))
            
            // Leading Edge (Front Face Shadow/Highlight) - create a thin vertical box
            boxes.push(box.new(leftEdge, binTop, leftEdge + 1, binBottom, 
                         bgcolor = color.new(baseColor, 20), border_color = na))

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
DATA = #DBDBDB, HEADERS = #808080, BACKGROUND = #161616, BORDERS = #2E2E2E
if input.bool(true, 'Dashboard', group = 'Dashboard') and barstate.islast
    var t = table.new(position.top_right, 3, 5, bgcolor = BACKGROUND, frame_color = BORDERS, frame_width = 1)
    t.merge_cells(0,0,2,0)
    t.cell(0,0, 'Multi-Term kNN [LuxAlgo]', text_color = DATA, text_size = size.small)
    t.cell(0,2, 'Active Term', text_color = HEADERS, text_halign = text.align_left, text_size = size.small)
    t.cell(1,2, activeTerm == "" ? "None" : activeTerm, text_color = DATA, text_size = size.small)
    t.cell(0,4, 'Bias', text_color = HEADERS, text_halign = text.align_left, text_size = size.small)
    
    biasStr = close > selectedHigh ? 'Bullish' : close < selectedLow ? 'Bearish' : 'Neutral'
    t.cell(1,4, biasStr, text_color = biasStr == 'Bullish' ? BULL_COLOR : biasStr == 'Bearish' ? BEAR_COLOR : NEUTRAL_COLOR, text_size = size.small)

//---------------------------------------------------------------------------------------------------------------------}
