// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("HTF Candle Projections [LuxAlgo]", "LuxAlgo - HTF Candle Projections", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_bars_back = 5000)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string htfInput         = input.timeframe("D", "HTF Timeframe")
int    widthInput       = input.int(6, "Candle Width (Bars)", minval = 1)
int    gapInput         = input.int(2, "Gap Between Candles", minval = 0)
int    countInput       = input.int(4, "Number of HTF Candles", minval = 1, maxval = 50)
bool   showSentiment    = input.bool(true, "Show Internal Sentiment Bars")

group_colors            = "Colors"
color  bullColorInput   = input.color(color.new(BULL_COLOR, 80), "HTF Bull Body",   inline = "1", group = group_colors)
color  bearColorInput   = input.color(color.new(BEAR_COLOR, 80), "HTF Bear Body",   inline = "1", group = group_colors)
color  bullSentInput    = input.color(color.new(BULL_COLOR, 20), "Sentiment Bull",  inline = "2", group = group_colors)
color  bearSentInput    = input.color(color.new(BEAR_COLOR, 20), "Sentiment Bear",  inline = "2", group = group_colors)
color  wickColorInput   = input.color(color.new(color.gray, 50), "Wick Color",      inline = "3", group = group_colors)
color  connColorInput   = input.color(color.new(color.gray, 50), "Connection Line", inline = "3", group = group_colors)
color  absConnColorInput = input.color(color.gray, "Absolute High/Low Connection", group = group_colors)

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type HTFData
    float o
    float h
    float l
    float c
    int   highTime
    int   lowTime
    int   bullCount
    int   bearCount
    int   totalBars

//---------------------------------------------------------------------------------------------------------------------}
// Core Calculations
//---------------------------------------------------------------------------------------------------------------------{
var HTFData[] htfHistory = array.new<HTFData>(0)

// Detect HTF boundary
bool isNewHtf = ta.change(time(htfInput)) != 0

// Track current HTF metrics
var float currentO         = open
var float currentH         = high
var float currentL         = low
var int   currentHighTime  = time
var int   currentLowTime   = time
var int   currentBull      = 0
var int   currentBear      = 0
var int   currentTotal     = 0

// Update trackers on every bar
if isNewHtf
    // Save completed candle to history if valid
    if not na(currentO) and currentTotal > 0
        htfHistory.push(HTFData.new(currentO, currentH, currentL, close[1], currentHighTime, currentLowTime, currentBull, currentBear, currentTotal))
        
        // Preserve memory by strictly limiting historical data
        while htfHistory.size() > math.max(0, countInput - 1)
            htfHistory.shift()

    // Reset for new HTF candle
    currentO        := open
    currentH        := high
    currentL        := low
    currentHighTime := time
    currentLowTime  := time
    currentBull     := close > open ? 1 : 0
    currentBear     := close < open ? 1 : 0
    currentTotal    := 1
else
    // Accumulate HTF data
    currentH := math.max(currentH, high)
    currentL := math.min(currentL, low)
    
    if high == currentH
        currentHighTime := time
    if low == currentL
        currentLowTime  := time
    
    currentBull  := currentBull + (close > open ? 1 : 0)
    currentBear  := currentBear + (close < open ? 1 : 0)
    currentTotal := currentTotal + 1

//---------------------------------------------------------------------------------------------------------------------}
// Drawing Setup
//---------------------------------------------------------------------------------------------------------------------{
var box[]  bodies      = array.new_box(0)
var box[]  bullBars    = array.new_box(0)
var box[]  bearBars    = array.new_box(0)
var line[] upperWicks  = array.new_line(0)
var line[] lowerWicks  = array.new_line(0)
var line[] highConns   = array.new_line(0)
var line[] lowConns    = array.new_line(0)

if barstate.isfirst
    for i = 0 to countInput - 1
        bodies.push(box.new(na, na, na, na, border_color = na, xloc = xloc.bar_time))
        bullBars.push(box.new(na, na, na, na, border_color = na, xloc = xloc.bar_time))
        bearBars.push(box.new(na, na, na, na, border_color = na, xloc = xloc.bar_time))
        upperWicks.push(line.new(na, na, na, na, xloc = xloc.bar_time))
        lowerWicks.push(line.new(na, na, na, na, xloc = xloc.bar_time))
        highConns.push(line.new(na, na, na, na, xloc = xloc.bar_time))
        lowConns.push(line.new(na, na, na, na, xloc = xloc.bar_time))

//---------------------------------------------------------------------------------------------------------------------}
// Render
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast
    // Prepare data to draw
    HTFData[] drawData = array.new<HTFData>(0)
    
    // Add historical candles
    int histSize = htfHistory.size()
    if histSize > 0
        int start = math.max(0, histSize - (countInput - 1))
        for i = start to histSize - 1
            drawData.push(htfHistory.get(i))
            
    // Add current live candle
    drawData.push(HTFData.new(currentO, currentH, currentL, close, currentHighTime, currentLowTime, currentBull, currentBear, currentTotal))
    
    // Calculate bar duration for time-based projection
    int barDuration = int(math.max(time - time[1], 0))
    
    // Find absolute highest high and lowest low
    float absMaxH = -1.0
    float absMinL = 10e10
    
    for i = 0 to drawData.size() - 1
        HTFData d = drawData.get(i)
        absMaxH := math.max(absMaxH, d.h)
        absMinL := math.min(absMinL, d.l)

    // Draw loop
    for i = 0 to drawData.size() - 1
        HTFData d = drawData.get(i)
        
        // Calculate Time positions
        int leftTime  = time + (2 * barDuration) + (i * (widthInput + gapInput) * barDuration)
        int rightTime = leftTime + (widthInput * barDuration)
        int midTime   = int(math.round((leftTime + rightTime) / 2.0))
        
        float bodyTop    = math.max(d.o, d.c)
        float bodyBottom = math.min(d.o, d.c)
        float bodyHeight = bodyTop - bodyBottom
        color bColor     = d.c >= d.o ? bullColorInput : bearColorInput
        
        // HTF Body
        box b = bodies.get(i)
        b.set_lefttop(leftTime, bodyTop)
        b.set_rightbottom(rightTime, bodyBottom)
        b.set_bgcolor(bColor)
        b.set_border_color(bColor)
        
        // Sentiment Bars (Composition)
        box bullB = bullBars.get(i)
        box bearB = bearBars.get(i)
        
        if showSentiment
            float bullPerc = d.totalBars > 0 ? d.bullCount / float(d.totalBars) : 0
            float bearPerc = d.totalBars > 0 ? d.bearCount / float(d.totalBars) : 0
            
            bullB.set_lefttop(leftTime, bodyBottom + (bodyHeight * bullPerc))
            bullB.set_rightbottom(leftTime + math.round(widthInput / 2) * barDuration, bodyBottom)
            bullB.set_bgcolor(bullSentInput)
            bullB.set_border_color(na)
            
            bearB.set_lefttop(leftTime + math.round(widthInput / 2) * barDuration, bodyBottom + (bodyHeight * bearPerc))
            bearB.set_rightbottom(rightTime, bodyBottom)
            bearB.set_bgcolor(bearSentInput)
            bearB.set_border_color(na)
        else
            bullB.set_lefttop(na, na)
            bearB.set_lefttop(na, na)
        
        // Wicks
        line uw = upperWicks.get(i)
        uw.set_xy1(midTime, d.h)
        uw.set_xy2(midTime, bodyTop)
        uw.set_color(wickColorInput)
        
        line lw = lowerWicks.get(i)
        lw.set_xy1(midTime, d.l)
        lw.set_xy2(midTime, bodyBottom)
        lw.set_color(wickColorInput)
        
        // Connection Lines
        bool isAbsMax = d.h == absMaxH
        bool isAbsMin = d.l == absMinL
        
        line hConn = highConns.get(i)
        hConn.set_xy1(d.highTime, d.h)
        hConn.set_xy2(midTime, d.h)
        hConn.set_color(isAbsMax ? absConnColorInput : connColorInput)
        hConn.set_style(isAbsMax ? line.style_solid : line.style_dotted)
        
        line lConn = lowConns.get(i)
        lConn.set_xy1(d.lowTime, d.l)
        lConn.set_xy2(midTime, d.l)
        lConn.set_color(isAbsMin ? absConnColorInput : connColorInput)
        lConn.set_style(isAbsMin ? line.style_solid : line.style_dotted)

//---------------------------------------------------------------------------------------------------------------------}
