// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=6
indicator("EQH/EQL Liquidity Zones [LuxAlgo]", overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
const string G1 = "Liquidity Detection"
const string G2 = "Visuals"
const color BULL_COLOR = #089981
const color BEAR_COLOR = #f23645

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
int leftLenInput    = input.int(10, "Pivot Left Length", minval = 1, group = G1, tooltip = "Number of bars to the left required for a pivot.")
int rightLenInput   = input.int(2, "Pivot Right Length", minval = 1, group = G1, tooltip = "Number of bars to the right required for a pivot.")
float thresholdPct  = input.float(0.03, "Equality Threshold (%)", minval = 0, step = 0.01, group = G1, tooltip = "Maximum percentage difference to consider two highs/lows 'equal'.")
int maxZones        = input.int(60, "Max Active Zones", minval = 1, maxval = 100, group = G1, tooltip = "Maximum number of active (unswept) liquidity lines to track. Increase for 1m charts.")

color bullColor     = input.color(BULL_COLOR, "Bullish Zone Color", group = G2)
color bearColor     = input.color(BEAR_COLOR, "Bearish Zone Color", group = G2)
int zoneTransp      = input.int(85, "Zone Transparency", minval = 0, maxval = 100, group = G2)
bool showMidline    = input.bool(false, "Show Midline", group = G2)
color midlineColor  = input.color(#787b86, "Midline Color", group = G2)
bool showVolume     = input.bool(true, "Show Volume", group = G2)
bool deleteOnSweep  = input.bool(false, "Delete on Sweep", group = G2)

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type LiquidityZone
    box   id
    line  midline
    label lbl
    label b1     
    label b2     
    label v1     
    label v2     
    float sweepLevel
    float totalVol 
    int   createdIdx 
    bool  isHigh
    bool  isSwept

type PivotPoint
    float price
    int   idx
    float vol

//---------------------------------------------------------------------------------------------------------------------}
// Storage
//---------------------------------------------------------------------------------------------------------------------{
var activeZones     = array.new<LiquidityZone>()
var historicalHighs = array.new<PivotPoint>()
var historicalLows  = array.new<PivotPoint>()

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
f_formatVol(float v) =>
    string res = ""
    if v >= 1000000
        res := str.format("{0,number,#.#}M", v / 1000000)
    else if v >= 1000
        res := str.format("{0,number,#.#}K", v / 1000)
    else
        res := str.tostring(v, "#")
    res

method update(LiquidityZone zone, bool deleteOnSweep) =>
    bool shouldRemove = false
    if not zone.isSwept
        // Extend to current bar
        box.set_right(zone.id, bar_index)
        if not na(zone.midline)
            line.set_x2(zone.midline, bar_index)
        label.set_x(zone.lbl, bar_index)
        
        // Sweep check starts the bar AFTER confirmation to handle 1m volatility
        if bar_index > zone.createdIdx
            bool sweepOccurred = zone.isHigh ? high > zone.sweepLevel : low < zone.sweepLevel
            
            if sweepOccurred
                zone.isSwept := true
                shouldRemove := true
                if deleteOnSweep
                    box.delete(zone.id)
                    line.delete(zone.midline)
                    label.delete(zone.lbl)
                    label.delete(zone.b1)
                    label.delete(zone.b2)
                    label.delete(zone.v1)
                    label.delete(zone.v2)
                else
                    box.set_bgcolor(zone.id, color.new(chart.fg_color, 95))
                    box.set_border_color(zone.id, color.new(chart.fg_color, 80))
                    if not na(zone.midline)
                        line.set_color(zone.midline, color.new(chart.fg_color, 80))
                    
                    label.set_textcolor(zone.lbl, color.new(chart.fg_color, 75))
                    string volStr = showVolume ? str.format(" ({0})", f_formatVol(zone.totalVol)) : ""
                    label.set_text(zone.lbl, "Swept " + (zone.isHigh ? "EQH" : "EQL") + volStr)
                    
                    label.set_color(zone.b1, color.new(chart.fg_color, 85))
                    label.set_color(zone.b2, color.new(chart.fg_color, 85))
                    label.set_text(zone.v1, "")
                    label.set_text(zone.v2, "")
    
    shouldRemove

f_consolidateLabels(array<LiquidityZone> zones) =>
    int sz = zones.size()
    if sz > 0
        for i = 0 to sz - 1
            LiquidityZone z = zones.get(i)
            if not z.isSwept
                label.set_text(z.lbl, "")
        
        array<int> processed = array.new<int>()
        for i = 0 to sz - 1
            if processed.includes(i) or zones.get(i).isSwept
                continue
            
            LiquidityZone base = zones.get(i)
            processed.push(i)
            float clusterVol = base.totalVol
            int clusterCount = 1
            
            if i < sz - 1
                for j = i + 1 to sz - 1
                    if processed.includes(j)
                        continue
                    
                    LiquidityZone comp = zones.get(j)
                    if comp.isSwept
                        continue
                        
                    if base.isHigh == comp.isHigh and math.abs(base.sweepLevel - comp.sweepLevel) / base.sweepLevel * 100 <= thresholdPct * 3
                        clusterVol += comp.totalVol
                        clusterCount += 1
                        processed.push(j)
            
            string typeStr  = base.isHigh ? "EQH" : "EQL"
            string countStr = clusterCount > 1 ? str.format("{0}x ", clusterCount) : ""
            string volStr   = showVolume ? str.format(" ({0})", f_formatVol(clusterVol)) : ""
            label.set_text(base.lbl, countStr + typeStr + volStr)

//---------------------------------------------------------------------------------------------------------------------}
// Core Logic
//---------------------------------------------------------------------------------------------------------------------{
float pH = ta.pivothigh(leftLenInput, rightLenInput)
float pL = ta.pivotlow(leftLenInput, rightLenInput)

// Handle Highs (EQH)
if not na(pH)
    int currentPivotIdx = bar_index - rightLenInput
    float currentVol = volume[rightLenInput]
    
    if historicalHighs.size() > 0
        for i = 0 to historicalHighs.size() - 1
            PivotPoint prev = historicalHighs.get(i)
            float diff = math.abs(pH - prev.price) / prev.price * 100
            
            if diff <= thresholdPct
                float top    = math.max(pH, prev.price)
                float bottom = math.min(pH, prev.price)
                float mid    = (top + bottom) / 2
                float totalVol = prev.vol + currentVol
                
                box b = box.new(prev.idx, top, bar_index, bottom, border_color = bearColor, bgcolor = color.new(bearColor, zoneTransp))
                line ml = showMidline ? line.new(prev.idx, mid, bar_index, mid, color = midlineColor, style = line.style_dashed) : na
                
                label lb = label.new(bar_index, mid, "", color = #00000000, textcolor = bearColor, style = label.style_label_left, size = size.small)
                label b1 = label.new(prev.idx, prev.price, "", color = bearColor, style = label.style_circle, size = size.small)
                label b2 = label.new(currentPivotIdx, pH, "", color = bearColor, style = label.style_circle, size = size.small)
                label v1 = showVolume ? label.new(prev.idx, prev.price, f_formatVol(prev.vol), color = #00000000, textcolor = bearColor, style = label.style_label_down, size = size.small) : na
                label v2 = showVolume ? label.new(currentPivotIdx, pH, f_formatVol(currentVol), color = #00000000, textcolor = bearColor, style = label.style_label_down, size = size.small) : na
                
                activeZones.push(LiquidityZone.new(b, ml, lb, b1, b2, v1, v2, top, totalVol, bar_index, true, false))
                break 
    
    historicalHighs.unshift(PivotPoint.new(pH, currentPivotIdx, currentVol))
    if historicalHighs.size() > 50
        historicalHighs.pop()

// Handle Lows (EQL)
if not na(pL)
    int currentPivotIdx = bar_index - rightLenInput
    float currentVol = volume[rightLenInput]
    
    if historicalLows.size() > 0
        for i = 0 to historicalLows.size() - 1
            PivotPoint prev = historicalLows.get(i)
            float diff = math.abs(pL - prev.price) / prev.price * 100
            
            if diff <= thresholdPct
                float top    = math.max(pL, prev.price)
                float bottom = math.min(pL, prev.price)
                float mid    = (top + bottom) / 2
                float totalVol = prev.vol + currentVol
                
                box b = box.new(prev.idx, top, bar_index, bottom, border_color = bullColor, bgcolor = color.new(bullColor, zoneTransp))
                line ml = showMidline ? line.new(prev.idx, mid, bar_index, mid, color = midlineColor, style = line.style_dashed) : na
                
                label lb = label.new(bar_index, mid, "", color = #00000000, textcolor = bullColor, style = label.style_label_left, size = size.small)
                label b1 = label.new(prev.idx, prev.price, "", color = bullColor, style = label.style_circle, size = size.small)
                label b2 = label.new(currentPivotIdx, pL, "", color = bullColor, style = label.style_circle, size = size.small)
                label v1 = showVolume ? label.new(prev.idx, prev.price, f_formatVol(prev.vol), color = #00000000, textcolor = bullColor, style = label.style_label_up, size = size.small) : na
                label v2 = showVolume ? label.new(currentPivotIdx, pL, f_formatVol(currentVol), color = #00000000, textcolor = bullColor, style = label.style_label_up, size = size.small) : na
                
                activeZones.push(LiquidityZone.new(b, ml, lb, b1, b2, v1, v2, bottom, totalVol, bar_index, false, false))
                break
    
    historicalLows.unshift(PivotPoint.new(pL, currentPivotIdx, currentVol))
    if historicalLows.size() > 50
        historicalLows.pop()

//---------------------------------------------------------------------------------------------------------------------}
// Manage Active Zones
//---------------------------------------------------------------------------------------------------------------------{
if activeZones.size() > 0
    // 1. Process active updates and identify swept zones
    for i = activeZones.size() - 1 to 0
        LiquidityZone zone = activeZones.get(i)
        bool swept = zone.update(deleteOnSweep)
        if swept
            activeZones.remove(i)
    
    // 2. Enforce limit by removing OLDEST zones only if still over capacity
    while activeZones.size() > maxZones
        activeZones.remove(0)
    
    // 3. Consolidate labels for remaining live zones
    if activeZones.size() > 0
        f_consolidateLabels(activeZones)

//---------------------------------------------------------------------------------------------------------------------}