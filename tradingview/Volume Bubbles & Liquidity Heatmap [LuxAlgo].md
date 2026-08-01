// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Volume Bubbles & Liquidity Heatmap [LuxAlgo]','LuxAlgo - Volume Bubbles & Liquidity Heatmap', overlay = true, max_polylines_count = 100, max_labels_count = 100, max_lines_count = 101, max_boxes_count = 500, max_bars_back = 5000)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN               = #089981
RED                 = #F23645

BUYSELL             = 'Buy & Sell Volume'
DELTA               = 'Delta Volume'
TOTAL               = 'Total Volume'

TOP                 = 'Top'
BOTTOM              = 'Bottom'
MIDDLE              = 'Middle'

BUBBLES_GROUP       = 'BUBBLES'
LABELS_GROUP        = 'LABELS'
SEPARATOR_GROUP     = 'SEPARATORS'
HISTOGRAM_GROUP     = 'LIQUIDITY HEATMAP'
STYLE_GROUP         = 'STYLE'

bubblesModeTooltip  = 'Select from the following options: total volume, buy and sell volume, or the delta between buy and sell volume.'
bubbleTFTooltip     = 'Select the timeframe for which the bubbles will be displayed.'
bubbleSizeTooltip   = 'Select the size of the bubbles as a percentage.'
priceRatioTooltip   = 'Select the shape of the bubbles. The larger the number, the more vertical the bubbles will be stretched.'

lookbackPeriodInput = input.int(    2000,       'Execute on last X bars',   minval = 100, maxval = 5000)

bubblesInput        = input.bool(   true,       'Display Bubbles',  group = BUBBLES_GROUP)
bubblesModeInput    = input.string( BUYSELL,    'Bubble Mode',      group = BUBBLES_GROUP,  tooltip = bubblesModeTooltip,   options = [TOTAL,BUYSELL,DELTA])
bubbleTimeframeInput= input.timeframe('1D',     'Bubble Timeframe', group = BUBBLES_GROUP,  tooltip = bubbleTFTooltip)
bubbleSizeInput     = input.int(    100,        'Bubble Size %',    group = BUBBLES_GROUP,  tooltip = bubbleSizeTooltip,    minval = 10,    maxval = 100) * 0.01
priceRatioInput     = input.float(  0.5,        'Bubble Shape',     group = BUBBLES_GROUP,  tooltip = priceRatioTooltip,    minval = 0,     step = 0.1)

labelInput          = input.bool(   true,       'Display Labels',   group = LABELS_GROUP,   inline = 'labels')
labelSizeInput      = input.int(    14,         '',                 group = LABELS_GROUP,   inline = 'labels')
labelLocationInput  = input.string( BOTTOM,     '',                 group = LABELS_GROUP,   inline = 'labels', options = [TOP,MIDDLE,BOTTOM])

separatorInput      = input.bool(   true,                           'Display Separators',   group = SEPARATOR_GROUP, inline = 'separators')
separatorColorInput = input.color(  color.new(color.silver,50),   '',                     group = SEPARATOR_GROUP, inline = 'separators')

histogramInput      = input.bool(   true,                           'Display Heatmap',      group = HISTOGRAM_GROUP)
histogramSizeInput  = input.int(    25,                             'Heatmap Rows',         group = HISTOGRAM_GROUP, minval = 2, maxval = 500)
histogramCellInput  = input.int(    20,                             'Cell Minimum Size',    group = HISTOGRAM_GROUP, minval = 2)
histogramColor1Input= input.color(  color.new(RED,90),              '',                     group = HISTOGRAM_GROUP, inline = 'histogram')
histogramColor2Input= input.color(  color.new(color.yellow,90),   '',                     group = HISTOGRAM_GROUP, inline = 'histogram')
histogramColor3Input= input.color(  color.new(color.blue,90),     '',                     group = HISTOGRAM_GROUP, inline = 'histogram')

buyColorInput       = input.color(  color.new(GREEN,50),            '',                     group = STYLE_GROUP,    inline = 'colors')
sellColorInput      = input.color(  color.new(RED,50),              '',                     group = STYLE_GROUP,    inline = 'colors')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type data
    float buyVolume
    float sellVolume
    float highPrice
    float lowPrice
    int barIndex
    bool newBubble

type bubble
    array<float> buyVolume
    array<float> sellVolume
    array<float> highs
    array<float> lows
    array<int> bars

type histogramBox
    int firstBar
    int lastBar
    float liquidity
    string extend

type histogramLevel
    float top
    float bottom
    array<histogramBox> boxes

type histogramData
    int barIndex
    float barVolume
    float barPrice

type fullHistogram
    float top
    float bottom
    float rowSize
    float maxVolume
    array<histogramLevel> levels
    array<histogramData> bars

var fullHistogram histogram = fullHistogram.new(0,0,0,0,array.new<histogramLevel>(),array.new<histogramData>())
var array<data> bars        = array.new<data>()
var array<bubble> bubbles   = array.new<bubble>()   
var array<float> volumes    = array.new<float>()
var array<float> ranges     = array.new<float>()
var array<float> deltas     = array.new<float>()

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
fetchData() =>
    float barTop        = high - math.max(open,close)
    float barBottom     = math.min(open,close) - low
    float barRange      = high - low
    bool bullBar        = close - open > 0
    
    float buyRange      = bullBar ? barRange : barTop + barBottom
    float sellRange     = bullBar ? barTop + barBottom : barRange
    float totalRange    = barRange + barTop + barBottom

    float buyRatio      = buyRange / totalRange
    float sellRatio     = sellRange / totalRange

    float buyVolume     = math.round(buyRatio * volume)
    float sellVolume    = math.round(sellRatio * volume)

    bool newBubble      = timeframe.change(bubbleTimeframeInput)
    
    if bars.size() >= lookbackPeriodInput
        bars.shift()
        histogram.bars.shift()

    bars.push(data.new(buyVolume,sellVolume,high,low,bar_index,newBubble))    
    histogram.bars.push(histogramData.new(bar_index,volume,math.round_to_mintick(hlc3)))

    if histogram.top == 0
        histogram.top       := high
        histogram.bottom    := low
    else
        histogram.top       := math.max(histogram.top,high)
        histogram.bottom    := math.min(histogram.bottom,low)
    
fetchBubbles() =>
    bubbles.clear()
    volumes.clear()
    ranges.clear()
    deltas.clear()
    for [index, eachBar] in bars        
        if eachBar.newBubble
            bubbles.push(bubble.new(array.new<float>(),array.new<float>(),array.new<float>(),array.new<float>(),array.new<int>()))
            volumes.push(0)
            ranges.push(0)
            deltas.push(0)

        if bubbles.size() != 0
            bubble currentBubble = bubbles.last()        
            currentBubble.highs.push(eachBar.highPrice)
            currentBubble.lows.push(eachBar.lowPrice)
            currentBubble.bars.push(eachBar.barIndex)
            currentBubble.buyVolume.push(eachBar.buyVolume)
            currentBubble.sellVolume.push(eachBar.sellVolume)

            volumes.set(-1, bubbles.last().buyVolume.sum() + bubbles.last().sellVolume.sum())
            ranges.set( -1, bubbles.last().highs.max() - bubbles.last().lows.min())
            deltas.set( -1, bubbles.last().buyVolume.sum() - bubbles.last().sellVolume.sum())

coordinates(int anchorBar, float anchorPrice, float angle, float radiusBar, float radiusPrice) =>
    x = math.min(math.round(anchorBar + radiusBar * math.cos(math.toradians(angle))),last_bar_index + 500)
    y = anchorPrice + radiusPrice * math.sin(math.toradians(angle))
    [x,y]

drawLabel(string switchData, float bubbleVolume, color bubbleColor,int anchorBar, float anchorPrice, float angle, float radiusBar, float radiusPrice) =>
    [labelPoint, labelStyle] = switch switchData
        TOP =>
            [x, y] = coordinates(anchorBar, anchorPrice, angle, radiusBar, radiusPrice)
            [chart.point.new(na,x,y),label.style_label_down]
        MIDDLE => 
            [x, y] = coordinates(anchorBar, anchorPrice, angle, radiusBar, radiusPrice)
            [chart.point.new(na,x,y),label.style_none]
        BOTTOM =>
            [x, y] = coordinates(anchorBar, anchorPrice, angle, radiusBar, radiusPrice)
            [chart.point.new(na,x,y),label.style_label_up]

    label.new(labelPoint,str.tostring(bubbleVolume,format.volume), textcolor = color.new(bubbleColor,0), color = color(na), style = labelStyle, size = labelSizeInput)

drawFullBubble(bubble eachBubble, bool deltaBubble) =>
    array<chart.point> bubblePoints = array.new<chart.point>()
    int anchorBar                   = eachBubble.bars.median()
    float anchorPrice               = math.round_to_mintick(0.5 * (eachBubble.highs.max() + eachBubble.lows.min()))
    
    float bubbleVolume              = math.abs(eachBubble.buyVolume.sum() + (deltaBubble ? -1 : 1 ) * eachBubble.sellVolume.sum())
    float bubbleRatio               = (bubbleVolume / (deltaBubble ? deltas.max() : volumes.max())) * bubbleSizeInput
    float radiusBar                 = math.floor(0.5 * eachBubble.bars.size()) * bubbleRatio
    float range2barRatio            = ranges.max() / eachBubble.bars.size()
    float radiusPrice               = radiusBar * range2barRatio * priceRatioInput        

    for deltaIndex = 0 to 360
        [x, y] = coordinates(anchorBar, anchorPrice, deltaIndex, radiusBar, radiusPrice)            
        bubblePoints.push(chart.point.new(na,x,y))
    
    float bubbleDelta   = eachBubble.buyVolume.sum() - eachBubble.sellVolume.sum()                
    bubbleColor         = bubbleDelta > 0 ? buyColorInput : sellColorInput   

    if labelInput
        int labelAngle = labelLocationInput == TOP ? 90 : labelLocationInput == BOTTOM ? 270 : 0
        drawLabel(labelLocationInput, bubbleVolume, bubbleColor, anchorBar, anchorPrice, labelAngle, labelLocationInput != MIDDLE ? radiusBar : 0, labelLocationInput != MIDDLE ? radiusPrice : 0)

    if separatorInput
        line.new(chart.point.new(na,eachBubble.bars.last(),eachBubble.highs.max()),chart.point.new(na,eachBubble.bars.last(),eachBubble.lows.min()),color = separatorColorInput, style = line.style_dashed)

    polyline.new(bubblePoints, false, true, line_color = color.new(bubbleColor,0), fill_color = bubbleColor)  

drawSplitBubble(bubble eachBubble) =>
    array<chart.point> buyVolumePoints  = array.new<chart.point>()
    array<chart.point> sellVolumePoints = array.new<chart.point>()

    int anchorBar                       = eachBubble.bars.median()        
    float anchorPrice                   = math.round_to_mintick(0.5 * (eachBubble.highs.max() + eachBubble.lows.min()))
    float bubbleVolume                  = eachBubble.buyVolume.sum() + eachBubble.sellVolume.sum()        
    float bubbleRatio                   = (bubbleVolume / volumes.max()) * bubbleSizeInput
    float radiusBar                     = math.floor(0.5 * eachBubble.bars.size()) * bubbleRatio
    float range2barRatio                = ranges.max() / eachBubble.bars.size()
    float radiusPrice                   = radiusBar * range2barRatio * priceRatioInput
    float volumeRatio                   = bubbleVolume / 360
    float normalizedBuyVolume           = eachBubble.buyVolume.sum() / volumeRatio
    float normalizedSellVolume          = eachBubble.sellVolume.sum() / volumeRatio

    buyVolumePoints.push(chart.point.new(na,anchorBar,anchorPrice))
    for buyIndex = 0 to normalizedBuyVolume            
        [x, y] = coordinates(anchorBar, anchorPrice, buyIndex, radiusBar, radiusPrice)            
        buyVolumePoints.push(chart.point.new(na,x,y))
    buyVolumePoints.push(chart.point.new(na,anchorBar,anchorPrice))

    sellVolumePoints.push(chart.point.new(na,anchorBar,anchorPrice))
    for sellIndex = normalizedBuyVolume to normalizedBuyVolume + normalizedSellVolume
        [x, y] = coordinates(anchorBar, anchorPrice, sellIndex, radiusBar, radiusPrice)            
        sellVolumePoints.push(chart.point.new(na,x,y))
    sellVolumePoints.push(chart.point.new(na,anchorBar,anchorPrice))

    if labelInput
        string buyLabelLocation     = labelLocationInput == MIDDLE ? MIDDLE : TOP
        string sellLabelLocation    = labelLocationInput == MIDDLE ? MIDDLE : BOTTOM 
        float labelRadius           = labelLocationInput == MIDDLE ? 0.5*radiusPrice : radiusPrice

        drawLabel(buyLabelLocation,eachBubble.buyVolume.sum(),color.new(buyColorInput,0),anchorBar, anchorPrice, 90, radiusBar, labelRadius)           
        drawLabel(sellLabelLocation,eachBubble.sellVolume.sum(),color.new(sellColorInput,0),anchorBar, anchorPrice, 270, radiusBar, labelRadius)    

    if separatorInput
        line.new(chart.point.new(na,eachBubble.bars.last(),eachBubble.highs.max()),chart.point.new(na,eachBubble.bars.last(),eachBubble.lows.min()),color = separatorColorInput, style = line.style_dashed)

    polyline.new(buyVolumePoints, false, true, line_color = color.new(buyColorInput,0), fill_color = buyColorInput)
    polyline.new(sellVolumePoints,false, true, line_color = color.new(sellColorInput,0),fill_color = sellColorInput)

drawBubbles() =>
    for eachPolyline in polyline.all
        eachPolyline.delete()
    for eachLabel in label.all
        eachLabel.delete()
    for eachLine in line.all
        eachLine.delete()
    for eachBubble in bubbles
        switch bubblesModeInput
            TOTAL   => drawFullBubble(eachBubble,false)
            BUYSELL => drawSplitBubble(eachBubble)
            DELTA   => drawFullBubble(eachBubble,true)

drawHistogram() =>
    for eachBox in box.all
        eachBox.delete()
    
    histogram.rowSize := math.round_to_mintick((histogram.top - histogram.bottom)/histogramSizeInput)        
    histogram.levels.clear()
    for index = 0 to histogramSizeInput - 1
        float bottom    = histogram.bottom + index * histogram.rowSize
        float top       = bottom + histogram.rowSize    
        histogram.levels.push(histogramLevel.new(top,bottom,array.new<histogramBox>()))

    int lastLevel = 0
    for [index,eachBar] in histogram.bars        
        int level                       = math.floor((eachBar.barPrice - histogram.bottom) / histogram.rowSize)    
        level                           := math.min(level,histogram.levels.size() - 1)
        histogramLevel h_istogramLevel  = histogram.levels.get(level)
        array<histogramBox> boxes       = h_istogramLevel.boxes

        if boxes.size() == 0
            boxes.push(histogramBox.new(eachBar.barIndex,eachBar.barIndex,eachBar.barVolume,extend.right))      
        else
            histogramBox b_ox   = boxes.last()
            b_ox.lastBar        := eachBar.barIndex

            if level == lastLevel                                
                b_ox.liquidity += eachBar.barVolume                                
            else
                bool boxIsBigEnough = b_ox.lastBar - b_ox.firstBar >= histogramCellInput                
                if boxIsBigEnough
                    b_ox.extend := extend.none                                                
                    boxes.push(histogramBox.new(eachBar.barIndex,eachBar.barIndex,eachBar.barVolume,extend.right))
                else
                    b_ox.liquidity += eachBar.barVolume
            histogram.maxVolume := math.max(histogram.maxVolume,b_ox.liquidity)
        lastLevel := level

    for [index,eachLevel] in histogram.levels
        for eachBox in eachLevel.boxes
            float liquidityRatio    = eachBox.liquidity / histogram.maxVolume
            color backgroundColor   = color.from_gradient(liquidityRatio,liquidityRatio <= 0.5 ? 0.0 : 0.5,liquidityRatio <= 0.5 ? 0.5 : 1.0,liquidityRatio <= 0.5 ? histogramColor3Input : histogramColor2Input,liquidityRatio <= 0.5 ? histogramColor2Input : histogramColor1Input)
            box.new(chart.point.new(na,eachBox.firstBar,eachLevel.top),chart.point.new(na,eachBox.lastBar,eachLevel.bottom),extend = eachBox.extend, border_color = color(na),bgcolor = backgroundColor)                       

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
executionWindow = bar_index >= last_bar_index - lookbackPeriodInput

if executionWindow
    fetchData()

    if barstate.islastconfirmedhistory or (barstate.isrealtime and barstate.isconfirmed)    
        if histogramInput
            drawHistogram()

        if bubblesInput
            fetchBubbles()
            drawBubbles()
        
//---------------------------------------------------------------------------------------------------------------------}