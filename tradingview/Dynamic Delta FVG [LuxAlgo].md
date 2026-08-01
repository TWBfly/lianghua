// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Dynamic Delta FVG [LuxAlgo]", "LuxAlgo - DDFVG", overlay = true, max_boxes_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR      = #089981
color BEAR_COLOR      = #f23645

string MIT_TOUCH      = "Touch"
string MIT_FULL       = "Full Fill"

string GRP_FILTER     = "Detection Filters"
string GRP_DELTA      = "Volume Delta Analysis"
string GRP_STYLE      = "Visuals"
string GRP_DASH       = "Dashboard"

// Dashboard Constants
color DATA            = #DBDBDB
color HEADERS         = #808080
color BACKGROUND      = #161616
color BORDERS         = #2E2E2E

string TOP_RIGHT      = 'Top Right'
string BOTTOM_RIGHT   = 'Bottom Right'
string BOTTOM_LEFT    = 'Bottom Left'

string TINY           = 'Tiny'
string SMALL          = 'Small'
string NORMAL         = 'Normal'
string LARGE          = 'Large'
string HUGE           = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type Imbalance
    box   buyBoxId
    box   sellBoxId
    label labelId
    float top
    float bottom
    bool  isBull
    bool  isMitigated
    float buyPct
    float sellPct

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
float volMultInput       = input.float(0.0, "Min Volume Threshold", minval = 0, step = 0.1, group = GRP_FILTER, tooltip = "Filter for institutional volume spikes. 0 = Disabled.")
float atrMultInput       = input.float(0.2, "Min ATR Magnitude", minval = 0, step = 0.1, group = GRP_FILTER, tooltip = "Reduced default to 0.1 for better sensitivity on NQ/XAUUSD.")
string mitModeInput      = input.string(MIT_TOUCH, "Mitigation Mode", options = [MIT_TOUCH, MIT_FULL], group = GRP_FILTER)
bool   filterOverlapInput = input.bool(true, "Filter Overlapping", group = GRP_FILTER, tooltip = "Ensures only the most recent imbalance in a price zone is active.")

string deltaTfInput      = input.timeframe("1S", "Delta Timeframe", group = GRP_DELTA, tooltip = "Set to 1S for maximum granularity. Required TradingView Paid Plan for second data.")

int   maxGapsInput       = input.int(20, "Max Active Gaps", minval = 1, maxval = 100, group = GRP_STYLE)
color buyColorInput      = input.color(color.new(BULL_COLOR, 60), "Buyer Color", group = GRP_STYLE)
color sellColorInput     = input.color(color.new(BEAR_COLOR, 60), "Seller Color", group = GRP_STYLE)
bool  showMitigatedInput = input.bool(false, "Show Mitigated Gaps", group = GRP_STYLE)

bool   showDashInput     = input.bool(true, "Show Dashboard", group = GRP_DASH)
string dashPosInput      = input.string(TOP_RIGHT, "Position", options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT], group = GRP_DASH)
string dashSizeInput     = input.string(SMALL, "Size", options = [TINY, SMALL, NORMAL, LARGE, HUGE], group = GRP_DASH)

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
get_delta_details() =>
    float buyVol  = 0.0
    float sellVol = 0.0
    
    // Request lower TF data
    [vArr, cArr, oArr] = request.security_lower_tf(syminfo.tickerid, deltaTfInput, [volume, close, open], ignore_invalid_timeframe = true)
    
    // Check if we have volume data from lower TF
    if not na(vArr) and array.size(vArr) > 0
        for i = 0 to array.size(vArr) - 1
            float v = array.get(vArr, i)
            float c = array.get(cArr, i)
            float o = array.get(oArr, i)
            if c > o
                buyVol += v
            else if c < o
                sellVol += v
            else
                buyVol  += v / 2
                sellVol += v / 2
    else
        // Fallback to candle direction if no lower TF data or volume is 0
        if close > open
            buyVol := 100.0
        else if close < open
            sellVol := 100.0
        else
            buyVol := 50.0
            sellVol := 50.0
                
    float total   = buyVol + sellVol
    float buyPct  = total > 0 ? (buyVol / total) * 100 : 50.0
    float sellPct = total > 0 ? (sellVol / total) * 100 : 50.0
    [buyPct, sellPct]

// Table Helpers
var parsedDashboardPosition = switch dashPosInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize     = switch dashSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

cell(table t_able, int column, int row, string data, color = #FFFFFF, align = text.align_right, color background = na, float height = 0) => 
    t_able.cell(column, row, data, text_color = color, text_size = parsedDashboardSize, text_halign = align, bgcolor = background, height = height)

divider(table t_able, int row, int lastColumn) =>    
    string rowDivider = '━━━━━━━━━━━━━━━━'
    t_able.merge_cells(0, row, lastColumn, row)
    cell(t_able, 0, row, rowDivider, align = text.align_center, height = 0.5, color = BORDERS)

//---------------------------------------------------------------------------------------------------------------------}
// Core Logic
//---------------------------------------------------------------------------------------------------------------------{
var activeGaps = array.new<Imbalance>(0)

// Use nz and fallback for ATR to ensure it works on early bars
float atr         = nz(ta.atr(14), ta.tr) 
float volAvg      = nz(ta.sma(volume, 20), volume)
[buyPct, sellPct] = get_delta_details()

// Detection
// We only run on bar confirmation to ensure FVG stability and Delta accuracy
if barstate.isconfirmed
    bool isBullFVG      = low > high[2]
    bool isBearFVG      = high < low[2]
    
    // Filters with high compatibility for NQ/XAUUSD
    bool volFilter      = nz(volume[1]) >= volAvg[1] * volMultInput
    bool sizeFilterBull = (low - high[2]) >= atr * atrMultInput
    bool sizeFilterBear = (low[2] - high) >= atr * atrMultInput

    if (isBullFVG or isBearFVG) and volFilter
        if (isBullFVG and sizeFilterBull) or (isBearFVG and sizeFilterBear)
            float top         = isBullFVG ? low : low[2]
            float bottom      = isBullFVG ? high[2] : high
            float mid         = (top + bottom) / 2
            float rangeHeight = top - bottom
            
            // FVG formed on the previous bar (index 1)
            float bPct = nz(buyPct[1], 50.0)
            float sPct = nz(sellPct[1], 50.0)
            
            float splitLevel  = bottom + (rangeHeight * (sPct / 100))
            string deltaText  = "B:" + str.tostring(bPct, "#") + "% S:" + str.tostring(sPct, "#") + "%"
            
            // Overlap Handling
            if filterOverlapInput and activeGaps.size() > 0
                for i = activeGaps.size() - 1 to 0
                    Imbalance gap = activeGaps.get(i)
                    if not gap.isMitigated
                        if math.max(bottom, gap.bottom) < math.min(top, gap.top)
                            gap.buyBoxId.delete()
                            gap.sellBoxId.delete()
                            gap.labelId.delete()
                            activeGaps.remove(i)

            // Create Visuals
            box bBox = box.new(bar_index[2], top, bar_index, splitLevel, bgcolor = buyColorInput, border_width = 0)
            box sBox = box.new(bar_index[2], splitLevel, bar_index, bottom, bgcolor = sellColorInput, border_width = 0)

            color tagColor = bPct > sPct ? color.new(BULL_COLOR, 20) : color.new(BEAR_COLOR, 20)
            label lbl = label.new(bar_index, mid, deltaText, 
                 color       = tagColor, 
                 textcolor   = color.white, 
                 style       = label.style_label_left, 
                 size        = size.small)
                 
            activeGaps.push(Imbalance.new(bBox, sBox, lbl, top, bottom, isBullFVG, false, bPct, sPct))
            
            if activeGaps.size() > maxGapsInput
                Imbalance old = activeGaps.shift()
                old.buyBoxId.delete()
                old.sellBoxId.delete()
                old.labelId.delete()

// Mitigation & Maintenance
int   openBull      = 0
int   openBear      = 0
float sumAllBuyPct  = 0.0
float sumAllSellPct = 0.0
int   totalActive   = 0

if activeGaps.size() > 0
    for i = activeGaps.size() - 1 to 0
        Imbalance gap = activeGaps.get(i)
        
        if not gap.isMitigated
            bool mitigated = false
            if gap.isBull
                mitigated := mitModeInput == MIT_TOUCH ? low < gap.top : low < gap.bottom
            else
                mitigated := mitModeInput == MIT_TOUCH ? high > gap.bottom : high > gap.top
            
            if mitigated
                gap.isMitigated := true
                if not showMitigatedInput
                    gap.buyBoxId.delete()
                    gap.sellBoxId.delete()
                    gap.labelId.delete()
                    activeGaps.remove(i)
                else
                    gap.buyBoxId.set_bgcolor(color.new(chart.fg_color, 90))
                    gap.sellBoxId.set_bgcolor(color.new(chart.fg_color, 95))
                    gap.labelId.delete()
            else
                gap.buyBoxId.set_right(bar_index)
                gap.sellBoxId.set_right(bar_index)
                gap.labelId.set_x(bar_index)
                gap.labelId.set_y((gap.top + gap.bottom) / 2)
                
                totalActive   += 1
                sumAllBuyPct  += gap.buyPct
                sumAllSellPct += gap.sellPct
                
                if gap.isBull
                    openBull += 1
                else
                    openBear += 1

float avgBuyAll      = totalActive > 0 ? sumAllBuyPct / totalActive : 50.0
float avgSellAll     = totalActive > 0 ? sumAllSellPct / totalActive : 50.0
float netMarketDelta = avgBuyAll - avgSellAll

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var table dash = table.new(parsedDashboardPosition, 2, 9, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)

if showDashInput and barstate.islast
    cell(dash, 0, 0, 'Active Imbalances', color = DATA, align = text.align_center)
    dash.merge_cells(0, 0, 1, 0)
    
    divider(dash, 1, 1)
    
    cell(dash, 0, 2, "Bullish Imbalances", color = HEADERS, align = text.align_left)
    cell(dash, 1, 2, str.tostring(openBull), color = BULL_COLOR)
    
    cell(dash, 0, 3, "Bearish Imbalances", color = HEADERS, align = text.align_left)
    cell(dash, 1, 3, str.tostring(openBear), color = BEAR_COLOR)

    divider(dash, 4, 1)

    cell(dash, 0, 5, "Buyer Strength", color = HEADERS, align = text.align_left)
    cell(dash, 1, 5, str.tostring(avgBuyAll, "#.#") + "%", color = BULL_COLOR)

    cell(dash, 0, 6, "Seller Strength", color = HEADERS, align = text.align_left)
    cell(dash, 1, 6, str.tostring(avgSellAll, "#.#") + "%", color = BEAR_COLOR)

    divider(dash, 7, 1)

    string sentiment = netMarketDelta > 5 ? "Aggressive Buying" : netMarketDelta < -5 ? "Aggressive Selling" : "Neutral / Balanced"
    color sentColor  = netMarketDelta > 5 ? BULL_COLOR : netMarketDelta < -5 ? BEAR_COLOR : HEADERS
    
    cell(dash, 0, 8, "Net Sentiment", color = HEADERS, align = text.align_left)
    cell(dash, 1, 8, sentiment, color = sentColor)

//---------------------------------------------------------------------------------------------------------------------}