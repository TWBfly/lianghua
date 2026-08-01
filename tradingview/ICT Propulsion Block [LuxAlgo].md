// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=5

indicator("ICT Propulsion Block [LuxAlgo]", "LuxAlgo - ICT Propulsion Block", overlay = true,  max_lines_count = 500, max_boxes_count = 500, max_labels_count = 500, max_bars_back = 1234)

//---------------------------------------------------------------------------------------------------------------------
// Settings 
//---------------------------------------------------------------------------------------------------------------------{

display = display.all - display.status_line

obGroup = 'Order & Propulsion Blocks'
obLength = input.int(3, 'Swing Detection Length', minval = 1, group = obGroup, display = display)

obMitigationPrice = input.string('Closing Price', 'Mitigation Price', options = ['Closing Price', 'Wick'], group = obGroup, display = display)
obCloseMitigationPrice = obMitigationPrice == 'Closing Price'

pbPropulsionBlock = input.bool(true, 'Highlight Propulsion Block Signals', group = obGroup)
obUnassociatedTTip = 'An unassociated order block in the context of propulsion blocks refers to an order block that is not linked or connected to any propulsion block.'
obUnassociated = input.bool(true, 'Remove Unassociated Order Blocks', group = obGroup, tooltip = obUnassociatedTTip)

obRemoveMitigatedTTip = 'The Remove Mitigated Blocks option will remove the visualization of;\n -Mitigated Order Blocks,\n -Mitigated Propulsion Blocks and their associated Order Blocks.'
obRemoveMitigated = input.bool(false, 'Remove Mitigated Blocks', group = obGroup, tooltip = obRemoveMitigatedTTip)

obMostRecent = input.bool(false, 'Most Recent Blocks', inline = 'NR', group = obGroup)
obMostRecentValue = input.int(30, '', minval = 1, inline = 'NR', group = obGroup, display = display)

//Style
obStyleGroup = 'Order & Propulsion Blocks Style'

obShowBullish = input.bool(true, 'Bullish ', inline = 'bullish', group = obStyleGroup)
obBullishColor = input(color.new(#2157f3, 4), 'OB', inline = 'bullish', group = obStyleGroup)
pbBullishColor = input(color.new(#089981, 4), 'PB', inline = 'bullish', group = obStyleGroup)

obShowBearish = input.bool(true, 'Bearish', inline = 'bearish', group = obStyleGroup)
obBearishColor = input(color.new(#ff5d00, 4), 'OB', inline = 'bearish', group = obStyleGroup)
pbBearishColor = input(color.new(#ff1100, 4), 'PB', inline = 'bearish', group = obStyleGroup)

obBlockLabels = input.bool(true, 'Block Labels', inline = 'SZ', group = obStyleGroup)
obLabelSize = input.string('Small', '', options = ['Tiny', 'Small', 'Normal'], inline = 'SZ', group = obStyleGroup, display = display)

//---------------------------------------------------------------------------------------------------------------------}
// User Defined Types
//---------------------------------------------------------------------------------------------------------------------{

// @type        bar properties with their values 
//
// @field o     (float) open price of the bar
// @field h     (float) high price of the bar
// @field l     (float) low price of the bar
// @field c     (float) close price of the bar
// @field i     (int) index of the bar

type BAR
    float   open = open
    float   high = high
    float   low = low
    float   close = close
    int     index = bar_index

type OrderBlock
    int     startIndex = bar_index
    int     endIndex = na
    int     confirmedIndex = na

    float   open  = na
    float   high  = na
    float   low   = na
    float   close = na

    line    meanThresholdLine
    label   propulsionLabel
    box     orderblockLevelBox

    bool    isPropulsion

    bool    isProcessed = false
    bool    isActive    = true
    bool    isMitigated = false

type SWING
    float   value = na
    int     index = na
    bool    cross = false

//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{

BAR bar = BAR.new()

//---------------------------------------------------------------------------------------------------------------------}
// Functions / Methods
//---------------------------------------------------------------------------------------------------------------------{

method obRender(OrderBlock this, left, right, obOpen, obHigh, obLow, obClose, color, isPropulsion, isBullish) =>

    this.orderblockLevelBox.set_lefttop(left, isBullish ? obHigh : obLow)
    this.orderblockLevelBox.set_rightbottom(right, isBullish ? obHigh : obLow)
    this.orderblockLevelBox.set_bgcolor(color)
    this.orderblockLevelBox.set_border_color(color)

    if obBlockLabels
        this.orderblockLevelBox.set_text((isPropulsion ? 'PB' : 'OB')) // (isBullish? '▲' : '▼') + 
        this.orderblockLevelBox.set_text_color(color.new(color, 4))

    if isPropulsion
        this.meanThresholdLine.set_xy1(left , math.avg(obOpen, obClose))
        this.meanThresholdLine.set_xy2(right, math.avg(obOpen, obClose))
        this.meanThresholdLine.set_color(color.new(color, 4))

        if pbPropulsionBlock
            this.propulsionLabel.set_xy(left, isBullish ? obLow : obHigh)
            this.propulsionLabel.set_textcolor(color.new(color, 4))

method obSetRight(OrderBlock this, right) =>
    this.orderblockLevelBox.set_right(right), this.meanThresholdLine.set_x2(right), this.endIndex := right

method obDelete(OrderBlock this) =>
    this.orderblockLevelBox.delete(), this.meanThresholdLine.delete(), this.propulsionLabel.delete()

swings(length)=>
    var os = 0
    var SWING swingHigh = SWING.new(na, na)
    var SWING swingLow = SWING.new(na, na)

    upper = ta.highest(length)
    lower = ta.lowest (length)

    os := high[length] > upper ? 0 : low[length] < lower ? 1 : os

    if os == 0 and os[1] != 0 
        swingHigh := SWING.new(high[length], bar_index[length])
    
    if os == 1 and os[1] != 1
        swingLow := SWING.new(low[length], bar_index[length])

    [swingHigh, swingLow]
    
breaches(obBullArray, obBearArray) =>
    breachLow = bar.low
    breachHigh = bar.high
    breachIndex = bar.index

    var SWING bullishBreachHigh = SWING.new(na, na)
    var SWING bearishBreachLow = SWING.new(na, na)

    if obBullArray.size() > 0
        currentOrderBlock = obBullArray.get(0)
        if bar.low <= currentOrderBlock.high and bar.low > currentOrderBlock.low and bar.index > currentOrderBlock.confirmedIndex and not currentOrderBlock.isMitigated and currentOrderBlock.isActive and not currentOrderBlock.isPropulsion and bar.open > currentOrderBlock.high
            breachLow := math.min(bar.low, breachLow[1])
            breachHigh := breachLow == bar.low ? bar.high : breachHigh[1]
            breachIndex := breachLow == bar.low ? bar.index : breachIndex[1]
            bullishBreachHigh := SWING.new(breachHigh, breachIndex)
            //log.info("yaz_kizim {0} {1}", bar.low, bar.index)

    if obBearArray.size() > 0
        currentOrderBlock = obBearArray.get(0)
        if bar.high >= currentOrderBlock.low and bar.high < currentOrderBlock.high and bar.index > currentOrderBlock.confirmedIndex and not currentOrderBlock.isMitigated and currentOrderBlock.isActive and not currentOrderBlock.isPropulsion and bar.open < currentOrderBlock.low  
            breachHigh := math.max(bar.high, breachHigh[1])
            breachLow := breachHigh == bar.high ? bar.low : breachLow[1]
            breachIndex := breachHigh == bar.high ? bar.index : breachIndex[1]
            bearishBreachLow := SWING.new(breachLow, breachIndex)

    [bullishBreachHigh, bearishBreachLow]

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{

var bearishOrderBlockArray = array.new<OrderBlock>(0)
var bullishOrderBlockArray = array.new<OrderBlock>(0)

[swingHigh, swingLow] = swings(obLength)
[bullishBreachHigh, bearishBreachLow] = breaches(bullishOrderBlockArray, bearishOrderBlockArray)

obTextSize =   obLabelSize == 'Tiny'  ? size.tiny 
             : obLabelSize == 'Small' ? size.small 
             : size.normal

if obShowBullish
    if bar.close > swingHigh.value and not swingHigh.cross
        swingHigh.cross := true

        obBar = BAR.new(bar.open[1], bar.high[1], bar.low[1], bar.close[1], bar.index[1])

        for index = 1 to (bar.index - swingHigh.index) - 1
            if bar.open[index] > bar.close[index]
                if  bar.low[index]  <= obBar.low
                    obBar := BAR.new(bar.open[index], bar.high[index], bar.low[index], bar.close[index], bar.index[index])
            
        if bullishOrderBlockArray.size() > 0
            recentOrderBlock = bullishOrderBlockArray.get(0)

            if recentOrderBlock.isMitigated and recentOrderBlock.isPropulsion
                previousOrderBlock = bullishOrderBlockArray.get(1)
                if not previousOrderBlock.isPropulsion
                    previousOrderBlock.isMitigated := true

            if recentOrderBlock.isMitigated or (not recentOrderBlock.isMitigated and obBar.high > recentOrderBlock.high and obBar.index > recentOrderBlock.startIndex) //and recentOrderBlock.low != obBar.low and recentOrderBlock.high != obBar.high
                bullishOrderBlockArray.unshift(OrderBlock.new(obBar.index, bar.index, bar.index, obBar.open, obBar.high, obBar.low, obBar.close,
                     line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                     label.new(na, na, '▲', style = label.style_label_up, color = color(na), size = size.small, textcolor = color(na)),
                     box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_top), false)) 

                recentOrderBlock := bullishOrderBlockArray.get(0)
                previousOrderBlock = bullishOrderBlockArray.get(1)

                previousOrderBlock.isActive := false

                if obBar.index <= previousOrderBlock.endIndex and recentOrderBlock.low <= previousOrderBlock.high and recentOrderBlock.high > previousOrderBlock.high
                    recentOrderBlock.isPropulsion := true

                else if not previousOrderBlock.isPropulsion and obUnassociated
                    previousOrderBlock.obDelete()

        else
            bullishOrderBlockArray.unshift(OrderBlock.new(obBar.index, bar.index, bar.index, obBar.open, obBar.high, obBar.low, obBar.close,
                 line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                 label.new(na, na, '▲', style = label.style_label_up, color = color(na), size = size.small, textcolor = color(na)),
                 box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_top), false)) 
                
    if bullishOrderBlockArray.size() > 0

        recentOrderBlock = bullishOrderBlockArray.get(0)

        if bar.close > bullishBreachHigh.value and not bullishBreachHigh.cross and not recentOrderBlock.isMitigated and bullishBreachHigh.index > recentOrderBlock.confirmedIndex
            bullishBreachHigh.cross := true

            recentOrderBlock.isActive := false
            recentOrderBlock.obSetRight(bar.index)

            bullishOrderBlockArray.unshift(OrderBlock.new(bar.index[bar.index - bullishBreachHigh.index], bar.index, bar.index, bar.open[bar.index - bullishBreachHigh.index], bullishBreachHigh.value, bar.low[bar.index - bullishBreachHigh.index], bar.close[bar.index - bullishBreachHigh.index],
                 line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                 label.new(na, na, '▲', style = label.style_label_up, color = color(na), size = size.small, textcolor = color(na)),
                 box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_top), true)) 
                
        for arayIndex = bullishOrderBlockArray.size() - 1 to 0
            currentOrderBlock = bullishOrderBlockArray.get(arayIndex)

            if obRemoveMitigated and currentOrderBlock.isMitigated
                currentOrderBlock.obDelete()

            if not currentOrderBlock.isProcessed 
                currentOrderBlock.obRender(currentOrderBlock.startIndex, bar.index, currentOrderBlock.open, currentOrderBlock.high, currentOrderBlock.low, currentOrderBlock.close, currentOrderBlock.isPropulsion ? pbBullishColor : obBullishColor, currentOrderBlock.isPropulsion, true)
                currentOrderBlock.isProcessed := true

            if currentOrderBlock.isActive and not currentOrderBlock.isMitigated

                if (obCloseMitigationPrice ? bar.close : bar.low) < currentOrderBlock.low
                    currentOrderBlock.isMitigated := true

                currentOrderBlock.obSetRight(bar.index)

    if obMostRecent
        if bullishOrderBlockArray.size() > obMostRecentValue
            currentOrderBlock = bullishOrderBlockArray.pop()
            currentOrderBlock.obDelete()
    else
        if bullishOrderBlockArray.size() > 125
            currentOrderBlock = bullishOrderBlockArray.pop()
            currentOrderBlock.obDelete()

if obShowBearish
    if bar.close < swingLow.value and not swingLow.cross
        swingLow.cross := true

        obBar = BAR.new(bar.open[1], bar.high[1], bar.low[1], bar.close[1], bar.index[1])

        for index = 1 to (bar.index - swingLow.index) - 1
            if bar.open[index] < bar.close[index]
                if  bar.high[index]  >= obBar.high
                    obBar := BAR.new(bar.open[index], bar.high[index], bar.low[index], bar.close[index], bar.index[index])

        if bearishOrderBlockArray.size() > 0
            recentOrderBlock = bearishOrderBlockArray.get(0)

            if recentOrderBlock.isMitigated and recentOrderBlock.isPropulsion
                previousOrderBlock = bearishOrderBlockArray.get(1)
                if not previousOrderBlock.isPropulsion
                    previousOrderBlock.isMitigated := true

            if recentOrderBlock.isMitigated or (not recentOrderBlock.isMitigated and obBar.low < recentOrderBlock.low and obBar.index > recentOrderBlock.startIndex)
                bearishOrderBlockArray.unshift(OrderBlock.new(obBar.index, bar.index, bar.index, obBar.open, obBar.high, obBar.low, obBar.close, 
                     line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                     label.new(na, na, '▼', style = label.style_label_down, color = color(na), size = size.small, textcolor = color(na)),
                     box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_bottom), false)) 

                recentOrderBlock := bearishOrderBlockArray.get(0)
                previousOrderBlock = bearishOrderBlockArray.get(1)

                previousOrderBlock.isActive := false

                if obBar.index <= previousOrderBlock.endIndex and recentOrderBlock.high >= previousOrderBlock.low and recentOrderBlock.low < previousOrderBlock.low
                    recentOrderBlock.isPropulsion := true

                else if not previousOrderBlock.isPropulsion and obUnassociated
                    previousOrderBlock.obDelete()

        else
            bearishOrderBlockArray.unshift(OrderBlock.new(obBar.index, bar.index, bar.index, obBar.open, obBar.high, obBar.low, obBar.close, 
                 line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                 label.new(na, na, '▼', style = label.style_label_down, color = color(na), size = size.small, textcolor = color(na)),
                 box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_bottom), false)) 

    if bearishOrderBlockArray.size() > 0

        recentOrderBlock = bearishOrderBlockArray.get(0)

        if bar.close < bearishBreachLow.value and not bearishBreachLow.cross and not recentOrderBlock.isMitigated and bearishBreachLow.index > recentOrderBlock.confirmedIndex
            bearishBreachLow.cross := true
            
            recentOrderBlock.isActive := false
            recentOrderBlock.obSetRight(bar.index)

            bearishOrderBlockArray.unshift(OrderBlock.new(bar.index[bar.index - bearishBreachLow.index], bar.index, bar.index, bar.open[bar.index - bearishBreachLow.index], bar.high[bar.index - bearishBreachLow.index], bearishBreachLow.value, bar.close[bar.index - bearishBreachLow.index],
                 line.new(na, na, na, na, color = color(na), style = line.style_dotted),
                 label.new(na, na, '▼', style = label.style_label_down, color = color(na), size = size.small, textcolor = color(na)),
                 box.new(na, na, na, na, color(na), text_size = obTextSize, text_halign = text.align_right, text_valign = text.align_bottom), true)) 

        for arayIndex = bearishOrderBlockArray.size() - 1 to 0
            currentOrderBlock = bearishOrderBlockArray.get(arayIndex)

            if obRemoveMitigated and currentOrderBlock.isMitigated
                currentOrderBlock.obDelete()

            if not currentOrderBlock.isProcessed 
                currentOrderBlock.obRender(currentOrderBlock.startIndex, bar.index, currentOrderBlock.open, currentOrderBlock.high, currentOrderBlock.low, currentOrderBlock.close, currentOrderBlock.isPropulsion ? pbBearishColor : obBearishColor, currentOrderBlock.isPropulsion, false)
                currentOrderBlock.isProcessed := true

            if currentOrderBlock.isActive and not currentOrderBlock.isMitigated

                if (obCloseMitigationPrice ? bar.close : bar.high) > currentOrderBlock.high
                    currentOrderBlock.isMitigated := true

                currentOrderBlock.obSetRight(bar.index)

    if obMostRecent
        if bearishOrderBlockArray.size() > obMostRecentValue
            currentOrderBlock = bearishOrderBlockArray.pop()
            currentOrderBlock.obDelete()
    else
        if bearishOrderBlockArray.size() > 125
            currentOrderBlock = bearishOrderBlockArray.pop()
            currentOrderBlock.obDelete()

//---------------------------------------------------------------------------------------------------------------------}