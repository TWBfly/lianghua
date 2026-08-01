// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=6
indicator("Liquidity Delta Profiler [LuxAlgo]", "LuxAlgo - Liquidity Delta Profiler", overlay = true, max_boxes_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color DATA              = #DBDBDB
color HEADERS           = #808080
color BACKGROUND        = #161616
color BORDERS           = #2E2E2E

string TOP_RIGHT        = 'Top Right'
string BOTTOM_RIGHT     = 'Bottom Right'
string BOTTOM_LEFT      = 'Bottom Left'

string TINY             = 'Tiny'
string SMALL            = 'Small'
string NORMAL           = 'Normal'
string LARGE            = 'Large'
string HUGE             = 'Huge'

string DASHBOARD_GROUP  = 'Dashboard'

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
length = input.int(15, "Pivot Length", minval = 2, tooltip = "Lookback and lookforward length for detecting major swing highs/lows.")
maxZones = input.int(10, "Max Zones per Type", minval = 1, maxval = 40, tooltip = "Maximum number of active/historical buy and sell zones to keep on the chart.")
showSwept = input.bool(true, "Show Swept Zones", tooltip = "Keep zones visible (with dashed outlines and reduced opacity) after price sweeps them.")
filterOverlaps = input.bool(true, "Filter Overlapping Zones", tooltip = "When enabled, prevents creating new zones that overlap with existing active zones. Only the most significant (highest for BSL, lowest for SSL) level is kept.")

showDecay = input.bool(true, "Show Zone Decay", tooltip = "Displays the remaining 'health' of active zones based on the volume traded inside them. Health drops from 100% to 0%.")
zoneCapacity = input.float(5.0, "Zone Volume Capacity", minval = 1.0, tooltip = "Multiplier for average volume to determine how much volume a zone can absorb before reaching 0% health.")

enableReversals = input.bool(true, "Enable Reversal Detection", group = "Reversals", tooltip = "Detects unusual volume delta patterns during liquidity sweeps to signal potential reversals. Plots a bubble with signal type (ABS, EXH, DIV, REJ) and hover tooltip.")

dashboardInput          = input.bool(   true,       'Show Dashboard',    group = DASHBOARD_GROUP, tooltip = 'Enable or disable the dashboard.')
dashboardPositionInput  = input.string( TOP_RIGHT,  'Position',          group = DASHBOARD_GROUP, tooltip = 'Select the dashboard location.', options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
dashboardSizeInput      = input.string( TINY,       'Size',              group = DASHBOARD_GROUP, tooltip = 'Select the dashboard size.', options = [TINY, SMALL, NORMAL, LARGE, HUGE])
dashboardWindowInput    = input.int(    10,         'Eval Window (Bars)', group = DASHBOARD_GROUP, minval = 1, tooltip = 'Maximum number of bars to wait for the reversal to occur.')
dashboardHoldInput      = input.int(    3,          'Hold Time (Bars)',   group = DASHBOARD_GROUP, minval = 1, tooltip = 'Number of consecutive bars price must stay in profit (opposite direction) to be considered a win.')
dashboardHighlightInput = input.bool(   false,      'Highlight Eval Bars',group = DASHBOARD_GROUP, tooltip = 'Highlights bars actively evaluated. Yellow = Evaluating, Aqua = Holding in profit.')

bslColor = input.color(color.new(#f23645, 0), "BSL Outline Color", group = "Style", tooltip = "Color for Buy-Side Liquidity zones (above price).")
sslColor = input.color(color.new(#089981, 0), "SSL Outline Color", group = "Style", tooltip = "Color for Sell-Side Liquidity zones (below price).")

buyDeltaColor = input.color(color.new(#089981, 0), "Buy Delta Fill", group = "Style", tooltip = "Fill color when buy volume dominates a zone quadrant.")
sellDeltaColor = input.color(color.new(#f23645, 0), "Sell Delta Fill", group = "Style", tooltip = "Fill color when sell volume dominates a zone quadrant.")

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type Zone
    float top
    float bottom
    int left
    int right
    bool swept
    bool signaled
    box[] quads
    float[] deltas
    box outline
    float volumeTraded
    float capacity
    bool wasHit
    label decayLabel

type Trade
    string type
    int dir
    float entry
    int entryBar
    bool active
    bool won
    int consecBars

//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{
var Zone[] bslZones = array.new<Zone>()
var Zone[] sslZones = array.new<Zone>()

var activeTrades = array.new<Trade>()

var int absTotal = 0
var int absWins = 0
var int exhTotal = 0
var int exhWins = 0
var int divTotal = 0
var int divWins = 0
var int rejTotal = 0
var int rejWins = 0

var string parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left
    => position.top_right

var string parsedDashboardSize     = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge
    => size.normal

var table t_able = table.new(parsedDashboardPosition, 4, 11, bgcolor = dashboardInput ? BACKGROUND : na, border_width = 0, frame_color = dashboardInput ? BORDERS : na, frame_width = 1, force_overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
// Methods / Functions
//---------------------------------------------------------------------------------------------------------------------{
cell(table t_able, int col, int r, string data, color txtColor = color.white, string align = text.align_right, color background = na, float h = 0) => 
    t_able.cell(col, r, data, text_color = txtColor, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = h)

divider(table t_able, int r, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, r, lastColumn, r)
    cell(t_able, 0, r, rowDivider, txtColor = BORDERS, align = text.align_center, h = 0.5)

method evaluateReversals(Zone z, bool isBsl, float barH, float barL, float barC, float barO, float barDelta, float barVol) =>
    if enableReversals and not z.signaled
        float totalD = 0.0
        float absTotalD = 0.0
        for d in z.deltas
            totalD += d
            absTotalD += math.abs(d)
            
        if absTotalD > 0
            int outerIdx = isBsl ? 3 : 0
            float outerD = z.deltas.get(outerIdx)
            
            bool isSweeping = isBsl ? barH > z.top : barL < z.bottom
            bool closesInside = isBsl ? (barC <= z.top and barC >= z.bottom) : (barC >= z.bottom and barC <= z.top)
            float midPoint = (z.top + z.bottom) / 2
            bool closesRejecting = isBsl ? barC < midPoint : barC > midPoint
            
            string signalType = ""
            string tooltipTxt = ""
            float significance = 0.0
            color sigColor = isBsl ? color.red : color.green // Reversing from Resistance is Bearish (Red), from Support is Bullish (Green)
            
            // 1. Absorption at the Extreme (Trap)
            if isSweeping and ((isBsl and outerD < 0) or (not isBsl and outerD > 0))
                float ratio = math.abs(outerD) / (absTotalD + 0.0001)
                if ratio > 0.2
                    signalType := "ABS"
                    tooltipTxt := "Absorption at Extreme\n" + (isBsl ? "Sellers" : "Buyers") + " aggressively absorbed the sweep.\nOuter Quadrant Delta: " + str.tostring(outerD, format.volume)
                    significance := ratio * 2
                    
            // 2. Exhaustion (Dry Sweep)
            if signalType == "" and isSweeping
                float ratio = math.abs(outerD) / (absTotalD + 0.0001)
                if ratio < 0.1
                    signalType := "EXH"
                    tooltipTxt := "Exhaustion (Dry Sweep)\nMinimal volume at the extreme edge.\nOuter Quadrant Delta: " + str.tostring(outerD, format.volume)
                    significance := 1.0 - (ratio * 5)
                    
            // 3. Delta Divergence (FOMO)
            if signalType == "" and closesInside
                float ratio = math.abs(outerD) / (absTotalD + 0.0001)
                if ratio > 0.6 and ((isBsl and outerD > 0) or (not isBsl and outerD < 0))
                    signalType := "DIV"
                    tooltipTxt := "Delta Divergence (FOMO)\nHigh volume trapped at the extreme, but price failed to breakout.\nOuter Quadrant Delta: " + str.tostring(outerD, format.volume)
                    significance := ratio
                    
            // 4. Snapback (Climax + Rejection)
            if signalType == "" and isSweeping and closesRejecting
                float barRatio = math.abs(barDelta) / (barVol + 0.0001)
                if ((isBsl and barDelta < 0) or (not isBsl and barDelta > 0)) and barRatio > 0.2
                    signalType := "REJ"
                    tooltipTxt := "Snapback Rejection\nSweep followed by immediate strong rejection.\nBar Delta: " + str.tostring(barDelta, format.volume)
                    significance := barRatio * 2
        
            // Plot Signal
            if signalType != ""
                z.signaled := true
                alert("Reversal Signal (" + signalType + ") detected at " + str.tostring(barC), alert.freq_once_per_bar)
                
                significance := math.min(math.max(significance, 0.0), 1.0)
                string sSize = size.tiny
                int trans = 50
                
                if significance > 0.7
                    sSize := size.normal
                    trans := 10
                else if significance > 0.4
                    sSize := size.small
                    trans := 30
                    
                color finalColor = color.new(sigColor, trans)
                float yLoc = isBsl ? barH : barL
                string labelStyle = isBsl ? label.style_label_down : label.style_label_up
                
                label.new(bar_index, yLoc, text=signalType, color=finalColor, style=labelStyle, textcolor=color.white, size=sSize, tooltip=tooltipTxt)
                
                // Track Trade Performance
                float entry = barC
                activeTrades.push(Trade.new(signalType, isBsl ? -1 : 1, entry, bar_index, true, false, 0))

method updateVisuals(Zone z, bool isBsl, bool showS, color buyC, color sellC, color bslC, color sslC) =>
    float maxD = 0.0
    for d in z.deltas
        maxD := math.max(maxD, math.abs(d))
    
    for i = 0 to 3
        float d = z.deltas.get(i)
        color c = na
        string txt = ""
        color tColor = na
        if maxD > 0 and math.abs(d) > 0.001
            color baseC = d > 0 ? buyC : sellC
            int trans = z.swept ? 90 : 100 - int((math.abs(d) / maxD) * 60)
            c := color.rgb(color.r(baseC), color.g(baseC), color.b(baseC), trans)
            txt := (d > 0 ? "+" : d < 0 ? "-" : "") + str.tostring(math.abs(d), format.volume)
            tColor := color.new(baseC, z.swept ? 50 : 0)
        else
            color baseC = isBsl ? bslC : sslC
            int defaultTrans = 60 + (isBsl ? (3 - i) : i) * 10
            c := color.rgb(color.r(baseC), color.g(baseC), color.b(baseC), z.swept ? 90 : defaultTrans)
            txt := "0"
            tColor := color.new(baseC, z.swept ? 80 : 50)
        
        box q = z.quads.get(i)
        q.set_bgcolor(not showS and z.swept ? na : c)
        q.set_text(not showS and z.swept ? "" : txt)
        q.set_text_color(not showS and z.swept ? na : tColor)
        
        if z.swept
            q.set_border_color(not showS ? na : color.new(isBsl ? bslC : sslC, 80))
            q.set_border_style(line.style_dashed)
        else
            q.set_border_color(color.new(isBsl ? bslC : sslC, 60))
            q.set_border_style(line.style_solid)
            
    if z.swept
        if showS
            z.outline.set_border_style(line.style_dashed)
            z.outline.set_border_color(color.new(isBsl ? bslC : sslC, 80))
        else
            z.outline.set_border_color(na)

barOverlap(float barH, float barL, float qTop, float qBot) =>
    float overlapTop = math.min(barH, qTop)
    float overlapBot = math.max(barL, qBot)
    overlapTop > overlapBot ? (overlapTop - overlapBot) : 0.0

//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
float atr = ta.atr(14)
float ph = ta.pivothigh(high, length, length)
float pl = ta.pivotlow(low, length, length)
float avgVol = nz(ta.sma(volume, length))
if avgVol == 0
    avgVol := 1
float currentZoneCap = avgVol * zoneCapacity

if not na(ph) and bar_index >= length
    int pivotIdx = bar_index - length
    float pHigh = high[length]
    float pBot = math.max(close[length], open[length])
    if pHigh - pBot < atr[length] * 0.1
        pBot := pHigh - atr[length] * 0.1
        
    bool skip = false
    if filterOverlaps and bslZones.size() > 0
        for i = bslZones.size() - 1 to 0
            if i < bslZones.size()
                Zone ex = bslZones.get(i)
                if not ex.swept
                    bool overlaps = math.max(pBot, ex.bottom) <= math.min(pHigh, ex.top)
                    if overlaps
                        if pHigh > ex.top
                            for b in ex.quads
                                b.delete()
                            ex.outline.delete()
                            ex.decayLabel.delete()
                            bslZones.remove(i)
                        else
                            skip := true
                            break
                            
    if not skip
        box[] quads = array.new<box>(4)
        float[] deltas = array.new<float>(4, 0.0)
        float step = (pHigh - pBot) / 4
        for i = 0 to 3
            float qBot = pBot + i * step
            float qTop = pBot + (i + 1) * step
            color baseC = bslColor
            int trans = 60 + (3 - i) * 10
            color c = color.rgb(color.r(baseC), color.g(baseC), color.b(baseC), trans)
            
            float gap = step * 0.05
            float bTop = qTop - gap
            float bBot = qBot + gap
            if i == 0
                bBot := qBot
            if i == 3
                bTop := qTop
                
            quads.set(i, box.new(pivotIdx, bTop, pivotIdx, bBot, border_color = color.new(baseC, 60), bgcolor = c, text = "0", text_color = color.new(baseC, 50), text_halign = text.align_right, text_size = size.auto))
        
        box outline = box.new(pivotIdx, pHigh, pivotIdx, pBot, border_color = color.new(bslColor, 80), bgcolor = na)
        label dLabel = label.new(bar_index, pBot + (pHigh - pBot)/2, text = "100%", style = label.style_label_left, color = color.new(bslColor, 80), textcolor = color.white, size = size.small)
        if not showDecay
            dLabel.set_x(na)
            
        Zone z = Zone.new(pHigh, pBot, pivotIdx, pivotIdx, false, false, quads, deltas, outline, 0.0, currentZoneCap, false, dLabel)
        bslZones.unshift(z)
        if bslZones.size() > maxZones
            Zone removed = bslZones.pop()
            for b in removed.quads
                b.delete()
            removed.outline.delete()
            removed.decayLabel.delete()

if not na(pl) and bar_index >= length
    int pivotIdx = bar_index - length
    float pLow = low[length]
    float pTop = math.min(close[length], open[length])
    if pTop - pLow < atr[length] * 0.1
        pTop := pLow + atr[length] * 0.1
        
    bool skip = false
    if filterOverlaps and sslZones.size() > 0
        for i = sslZones.size() - 1 to 0
            if i < sslZones.size()
                Zone ex = sslZones.get(i)
                if not ex.swept
                    bool overlaps = math.max(pLow, ex.bottom) <= math.min(pTop, ex.top)
                    if overlaps
                        if pLow < ex.bottom
                            for b in ex.quads
                                b.delete()
                            ex.outline.delete()
                            ex.decayLabel.delete()
                            sslZones.remove(i)
                        else
                            skip := true
                            break
                            
    if not skip
        box[] quads = array.new<box>(4)
        float[] deltas = array.new<float>(4, 0.0)
        float step = (pTop - pLow) / 4
        for i = 0 to 3
            float qBot = pLow + i * step
            float qTop = pLow + (i + 1) * step
            color baseC = sslColor
            int trans = 60 + i * 10
            color c = color.rgb(color.r(baseC), color.g(baseC), color.b(baseC), trans)
            
            float gap = step * 0.05
            float bTop = qTop - gap
            float bBot = qBot + gap
            if i == 0
                bBot := qBot
            if i == 3
                bTop := qTop
                
            quads.set(i, box.new(pivotIdx, bTop, pivotIdx, bBot, border_color = color.new(baseC, 60), bgcolor = c, text = "0", text_color = color.new(baseC, 50), text_halign = text.align_right, text_size = size.auto))
        
        box outline = box.new(pivotIdx, pTop, pivotIdx, pLow, border_color = color.new(sslColor, 80), bgcolor = na)
        label dLabel = label.new(bar_index, pLow + (pTop - pLow)/2, text = "100%", style = label.style_label_left, color = color.new(sslColor, 80), textcolor = color.white, size = size.small)
        if not showDecay
            dLabel.set_x(na)
            
        Zone z = Zone.new(pTop, pLow, pivotIdx, pivotIdx, false, false, quads, deltas, outline, 0.0, currentZoneCap, false, dLabel)
        sslZones.unshift(z)
        if sslZones.size() > maxZones
            Zone removed = sslZones.pop()
            for b in removed.quads
                b.delete()
            removed.outline.delete()
            removed.decayLabel.delete()

float vol = nz(volume)
float totalRange = high - low
float barDelta = totalRange == 0 ? 0 : vol * (close - open) / totalRange

if bslZones.size() > 0
    for i = bslZones.size() - 1 to 0
        if i < bslZones.size()
            Zone z = bslZones.get(i)
            if not z.swept
                z.right := bar_index
                z.outline.set_right(bar_index)
                for b in z.quads
                    b.set_right(bar_index)
                
                bool hit = false
                float step = (z.top - z.bottom) / 4
                for j = 0 to 3
                    float qBot = z.bottom + j * step
                    float qTop = z.bottom + (j + 1) * step
                    float overlap = barOverlap(high, low, qTop, qBot)
                    if overlap > 0
                        hit := true
                        float overlapRatio = totalRange == 0 ? 0 : overlap / totalRange
                        float qDelta = barDelta * overlapRatio
                        z.deltas.set(j, z.deltas.get(j) + qDelta)
                        z.volumeTraded += vol * overlapRatio
                
                if hit and not z.wasHit
                    alert("Price testing Resistance BSL Zone at " + str.tostring(z.top), alert.freq_once_per_bar)
                    
                if high > z.top
                    z.swept := true
                    alert("Resistance BSL Zone Swept at " + str.tostring(z.top), alert.freq_once_per_bar)
                
                if not z.swept
                    if showDecay
                        int health = int(math.max(0, 100 - (z.volumeTraded / z.capacity * 100)))
                        z.decayLabel.set_x(bar_index + 1)
                        z.decayLabel.set_text(str.tostring(health) + "%")
                    else
                        z.decayLabel.set_x(na)
                else
                    z.decayLabel.delete()
                    
                z.wasHit := hit
                
                if hit or z.swept
                    z.evaluateReversals(true, high, low, close, open, barDelta, vol)
                    z.updateVisuals(true, showSwept, buyDeltaColor, sellDeltaColor, bslColor, sslColor)

if sslZones.size() > 0
    for i = sslZones.size() - 1 to 0
        if i < sslZones.size()
            Zone z = sslZones.get(i)
            if not z.swept
                z.right := bar_index
                z.outline.set_right(bar_index)
                for b in z.quads
                    b.set_right(bar_index)
                
                bool hit = false
                float step = (z.top - z.bottom) / 4
                for j = 0 to 3
                    float qBot = z.bottom + j * step
                    float qTop = z.bottom + (j + 1) * step
                    float overlap = barOverlap(high, low, qTop, qBot)
                    if overlap > 0
                        hit := true
                        float overlapRatio = totalRange == 0 ? 0 : overlap / totalRange
                        float qDelta = barDelta * overlapRatio
                        z.deltas.set(j, z.deltas.get(j) + qDelta)
                        z.volumeTraded += vol * overlapRatio
                
                if hit and not z.wasHit
                    alert("Price testing Support SSL Zone at " + str.tostring(z.bottom), alert.freq_once_per_bar)
                    
                if low < z.bottom
                    z.swept := true
                    alert("Support SSL Zone Swept at " + str.tostring(z.bottom), alert.freq_once_per_bar)
                
                if not z.swept
                    if showDecay
                        int health = int(math.max(0, 100 - (z.volumeTraded / z.capacity * 100)))
                        z.decayLabel.set_x(bar_index + 1)
                        z.decayLabel.set_text(str.tostring(health) + "%")
                    else
                        z.decayLabel.set_x(na)
                else
                    z.decayLabel.delete()
                    
                z.wasHit := hit
                
                if hit or z.swept
                    z.evaluateReversals(false, high, low, close, open, barDelta, vol)
                    z.updateVisuals(false, showSwept, buyDeltaColor, sellDeltaColor, bslColor, sslColor)

// Process Active Trades
color barHighlight = na
if activeTrades.size() > 0
    for i = activeTrades.size() - 1 to 0
        if i < activeTrades.size()
            Trade t = activeTrades.get(i)
            if t.active
                if bar_index > t.entryBar // Wait until the next bar to start evaluating
                    bool inProfit = (t.dir == 1 and close > t.entry) or (t.dir == -1 and close < t.entry)
                    
                    if inProfit
                        t.consecBars += 1
                        if na(barHighlight) or barHighlight == color.yellow
                            barHighlight := color.aqua
                    else
                        t.consecBars := 0
                        if na(barHighlight)
                            barHighlight := color.yellow
                        
                    if t.consecBars >= dashboardHoldInput
                        t.active := false
                        t.won := true
                    else if bar_index - t.entryBar >= dashboardWindowInput
                        t.active := false // Time ran out
                    
                    if not t.active
                        if t.type == "ABS"
                            absTotal += 1
                            if t.won
                                absWins += 1
                        else if t.type == "EXH"
                            exhTotal += 1
                            if t.won
                                exhWins += 1
                        else if t.type == "DIV"
                            divTotal += 1
                            if t.won
                                divWins += 1
                        else if t.type == "REJ"
                            rejTotal += 1
                            if t.won
                                rejWins += 1
                        activeTrades.remove(i)

barcolor(dashboardHighlightInput ? barHighlight : na)

if barstate.islast
    if dashboardInput
        t_able.merge_cells(0, 0, 3, 0)
        cell(t_able, 0, 0, 'Reversal Performance (Time-Based)', txtColor = DATA, align = text.align_center)
        
        divider(t_able, 1, 3)
        
        cell(t_able, 0, 2, 'Signal', txtColor = HEADERS, align = text.align_left)
        cell(t_able, 1, 2, 'Total',  txtColor = HEADERS, align = text.align_right)
        cell(t_able, 2, 2, 'Wins',   txtColor = HEADERS, align = text.align_right)
        cell(t_able, 3, 2, 'Win %',  txtColor = HEADERS, align = text.align_right)
        
        divider(t_able, 3, 3)
        
        float absRate = absTotal > 0 ? (absWins / absTotal) * 100 : 0
        cell(t_able, 0, 4, 'ABS', txtColor = DATA, align = text.align_left)
        cell(t_able, 1, 4, str.tostring(absTotal), txtColor = DATA, align = text.align_right)
        cell(t_able, 2, 4, str.tostring(absWins), txtColor = DATA, align = text.align_right)
        cell(t_able, 3, 4, str.tostring(absRate, '#.##') + '%', txtColor = absTotal > 0 ? (absRate >= 50 ? color.green : color.red) : DATA, align = text.align_right)
        
        divider(t_able, 5, 3)
        
        float exhRate = exhTotal > 0 ? (exhWins / exhTotal) * 100 : 0
        cell(t_able, 0, 6, 'EXH', txtColor = DATA, align = text.align_left)
        cell(t_able, 1, 6, str.tostring(exhTotal), txtColor = DATA, align = text.align_right)
        cell(t_able, 2, 6, str.tostring(exhWins), txtColor = DATA, align = text.align_right)
        cell(t_able, 3, 6, str.tostring(exhRate, '#.##') + '%', txtColor = exhTotal > 0 ? (exhRate >= 50 ? color.green : color.red) : DATA, align = text.align_right)
        
        divider(t_able, 7, 3)
        
        float divRate = divTotal > 0 ? (divWins / divTotal) * 100 : 0
        cell(t_able, 0, 8, 'DIV', txtColor = DATA, align = text.align_left)
        cell(t_able, 1, 8, str.tostring(divTotal), txtColor = DATA, align = text.align_right)
        cell(t_able, 2, 8, str.tostring(divWins), txtColor = DATA, align = text.align_right)
        cell(t_able, 3, 8, str.tostring(divRate, '#.##') + '%', txtColor = divTotal > 0 ? (divRate >= 50 ? color.green : color.red) : DATA, align = text.align_right)
        
        divider(t_able, 9, 3)
        
        float rejRate = rejTotal > 0 ? (rejWins / rejTotal) * 100 : 0
        cell(t_able, 0, 10, 'REJ', txtColor = DATA, align = text.align_left)
        cell(t_able, 1, 10, str.tostring(rejTotal), txtColor = DATA, align = text.align_right)
        cell(t_able, 2, 10, str.tostring(rejWins), txtColor = DATA, align = text.align_right)
        cell(t_able, 3, 10, str.tostring(rejRate, '#.##') + '%', txtColor = rejTotal > 0 ? (rejRate >= 50 ? color.green : color.red) : DATA, align = text.align_right)
    else
        t_able.clear(0, 0, 3, 10)

//---------------------------------------------------------------------------------------------------------------------}