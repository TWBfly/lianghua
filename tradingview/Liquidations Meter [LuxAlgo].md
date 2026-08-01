// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=5

indicator('Liquidations Meter [LuxAlgo]', 'LuxAlgo - Liquidations Meter', true)

//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{

clGR  = 'Liquidation Price Calculator'

lmTT  = 'Presents liquidations on the price chart by measuring the highest leverage value of longs and shorts that have been potentially liquidated on the last chart bar.\n\n' +
         'Liquidations meter allows traders to\n -gauge the momentum of the bar,\n -identify the strength of the bulls and bears, and\n -identify probable reversal/exhaustion points\n\n' +
         'Here with liquidations, we refer to the process of forcibly closing a trader\'s position in the market'
lmSH  = input.bool(true, 'Liquidations Meter', group = 'Liquidations Meter', tooltip = lmTT)
refPS = input.string("open", "Base Price", options = ["open", "close", "oc2", "hl2", "ooc3", "occ3", "hlc3", "ohlc4", "hlcc4"], group = 'Liquidations Meter')

clTT  = 'The liquidation price calculator is useful for leverage trading traders who want to know how much risk they can take for each trade.\n\n' +
         'This tool uses a formula to calculate the liquidation price based on the entry price + leverage ratio.\n\n' +
         'Other factors such as leveraged fees, position size, and other interest payments have been excluded since they are variables that don’t directly affect the level of liquidation of a leveraged position.\n\n' +
         'This calculator also assumes that traders are using an isolated margin for one single position and does not take into consideration the additional margin they might have in their account.'
clSH  = input.bool(true, 'Liquidation Price Calculator', group = clGR, tooltip = clTT)
epTT  = 'Defines the entry price.\nIf the entry price is set to 0, then the selected \'Base Price\' value is assumed as entry price\n\n' +
         'Tip: Before entering a trade, setting base price to \'close\' and entry price to remain at 0 will allow the traders to easily evaluate the risk and reward situation of any given setup'
clEP  = input.float(0., 'Entry Price', group = clGR, tooltip = epTT)
lrTT  = 'Leverage allows traders to borrow funds in order to enter a position larger than their own funds permit\n\n' +
         'the higher the leverage ratio the higher the risk.\n\nIt is important to be aware that when the leverage ratio is increased, the liquidation price moves closer to the entry price, meaning a higher risk trader\'s position will have'
clLR  = input.float(10., 'Leverage', minval = 0, group = clGR, tooltip = lrTT)

lpSH  = input.bool(true, 'Show Calculated Liquidation Prices on the Chart', group = clGR)

dbTT  = 'The bar statistics option enables measuring and presenting trading activity, volatility, and probable liquidations for the last chart bar'
dbSH  = input.bool(true, 'Show Bar Statistics', group = 'Dashboard', tooltip = dbTT)

lcLS  = input.string('Small', 'Liquidations Meter Text Size', options = ['Tiny', 'Small', 'Normal'], group = 'Others')
lcOF  = input.int(3, 'Liquidations Meter Offset', minval = 0, group = 'Others')
clPS  = input.string('Bottom', 'Dashboard/Calculator Placement', options=['Top', 'Middle', 'Bottom'], group = 'Others') 
lcDS  = input.string('Small', 'Dashboard/Calculator Text Size', options = ['Tiny', 'Small', 'Normal'], group = 'Others')

//-----------------------------------------------------------------------------}
// User Defined Types
//-----------------------------------------------------------------------------{

// @type        bar properties with their values 
//
// @field o     (float) open price of the bar
// @field h     (float) high price of the bar
// @field l     (float) low price of the bar
// @field i     (int)   index of the bar

type bar
    float o = open
    float h = high
    float l = low
    float c = close
    float v = volume
    int   i = bar_index

//-----------------------------------------------------------------------------}
// Variables 
//-----------------------------------------------------------------------------{

bar b = bar.new()

var label lbL = na, label.delete(lbL[1])
var label lbS = na, label.delete(lbS[1])
var line lnL = na, line.delete(lnL[1])
var line lnS = na, line.delete(lnS[1])

var aLQ = array.new_box()
var aCL = array.new_box()

vST = ''

//-----------------------------------------------------------------------------}
// Functions/methods
//-----------------------------------------------------------------------------{

// @function        converts simple text to formated text  
//                     
// @param  _s       [string] simple string 
//
// @returns         enumarated text size value 

f_gSZ(_s) =>
    switch _s
        'Tiny'  => size.tiny 
        'Small' => size.small 
        => size.normal

// @function        compares the source value with the reference value  
//                     
// @param  _s       [float] source 
// @param  _r       [float] reference  
// @param  _m       [float] multiplier 
//
// @returns         [string] result of the comparison 

f_gST(_s, _r, _m) =>
    if _s
        isS = _s >= 4.669 * _r * _m
        isH = _s >= 1.618 * _r * _m
        isL = _s <= 0.618 * _r * _m

        isS ? 'Very High' : isH ? 'High' : isL ? 'Low' : 'Average'

// @function        converts simple text to source  
//                     
// @param  _s       [string] simple string
//
// @returns         [float] source series 

f_gSRC(_s) =>
    switch _s
        "open"  => open
        "close" => close
        "oc2"   => math.avg(open, close)
        "hl2"   => hl2
        "ooc3"  => math.avg(open, open , close)
        "occ3"  => math.avg(open, close, close)
        "hlc3"  => hlc3
        "ohlc4" => ohlc4
        "hlcc4" => hlcc4

//-----------------------------------------------------------------------------}
// Calculations
//-----------------------------------------------------------------------------{
nzV  = nz(b.v)

vDB  = f_gST(nzV, ta.sma(nzV, 13), 1.1)
vST += '\n\nLast Bar Statistics:\n Trading activity : ' + vDB

aDB  = f_gST(b.h - b.l, ta.atr(13), 0.9)
vST += '\n Volatility : ' + aDB

LQ   = nzV / (b.o / (b.o - b.l)) + nzV / (math.avg(b.o, b.c) / (b.h - math.avg(b.o, b.c)))
lDB  = f_gST(LQ, ta.sma(LQ, 89), 1.9)
vST += '\n Liquidations : ' + lDB

lSZ  = f_gSZ(lcLS)
refP = f_gSRC(refPS)

if lmSH and barstate.islast

    if aLQ.size() > 0
        for i = 1 to aLQ.size()
            box.delete(aLQ.shift())
    
    off = lpSH ? 7 : 0
    
    if (refP - b.l) > 0
        aLQ.push(box.new(b.i + lcOF + off, refP, b.i + lcOF + off + 2, refP * (1 - 1. / 100), border_color = color(na), bgcolor = color.new(color.teal, 89), text = '100x', text_color = chart.fg_color, text_valign = text.align_bottom))
    if (b.h - refP) > 0
        aLQ.push(box.new(b.i + lcOF + off, refP, b.i + lcOF + off + 2, refP * (1 + 1. / 100), border_color = color(na), bgcolor = color.new(color.red,  89), text = '100x', text_color = chart.fg_color, text_valign = text.align_top))

    lev   = array.from(100, 50, 25, 10,  5,  3,  2, 1)
    trans = array.from( 89, 76, 63, 50, 37, 24, 11, 1)

    for i = 1 to 7
        if (refP - b.l) > 0 and refP / (refP - b.l) < lev.get(i - 1)
            aLQ.push(box.new(b.i + lcOF + off, refP * (1 - 1. / lev.get(i - 1)), b.i + lcOF + off + 2, refP * (1 - 1. / lev.get(i)), border_color = color(na), 
             bgcolor = color.new(color.teal, trans.get(i)), text = str.tostring(lev.get(i)) + 'x', text_color = chart.fg_color, text_valign = text.align_bottom))
    
        if (b.h - refP) > 0 and refP / (b.h - refP) < lev.get(i - 1)
            aLQ.push(box.new(b.i + lcOF + off, refP * (1 + 1. / lev.get(i - 1)), b.i + lcOF + off + 2, refP * (1 + 1. / lev.get(i)), border_color = color(na), 
             bgcolor = color.new(color.red, trans.get(i)), text = str.tostring(lev.get(i)) + 'x', text_color = chart.fg_color, text_valign = text.align_top))

    if refP / (refP - b.l) <= 100 and (refP - b.l) > 0
        lbL :=  label.new(b.i + lcOF + off + 1, b.l, '◄ ' + str.tostring(refP / (refP - b.l), '#.#') + 'x Longs Liquidated' ,
                     color = color(na), textcolor = chart.fg_color, size = lSZ, style = label.style_label_left, 
                     tooltip = 'The highest leverage of\n probable liquidated longs : ' + str.tostring(refP / (refP - b.l), '#.##') + 'x\nEstimantion based on\n reference price : '  + str.tostring(refP, format.mintick) + vST)
        lnL := line.new(b.i + lcOF + off, b.l, b.i + lcOF + off + 2, b.l, color = chart.fg_color, style = line.style_dotted)

    if refP / (b.h - refP) <= 100 and (b.h - refP) > 0
        lbS := label.new(b.i + lcOF + off + 1, b.h, '◄ ' + str.tostring(refP / (b.h - refP), '#.#') + 'x Shorts Liquidated', 
                     color = color(na), textcolor = chart.fg_color, size = lSZ, style = label.style_label_left, 
                     tooltip = 'The highest leverage of\n probable liquidated shorts : ' + str.tostring(refP / (b.h - refP), '#.##') + 'x\nEstimantion based on\n reference price : ' + str.tostring(refP, format.mintick) + vST)
        lnS := line.new(b.i + lcOF + off, b.h, b.i + lcOF + off + 2, b.h, color = chart.fg_color, style = line.style_dotted)

tPOS = switch clPS
    'Top'     => position.top_right
    'Middle'  => position.middle_right
    'Bottom'  => position.bottom_right

tSZ = f_gSZ(lcDS)

refP := clEP == 0 ? refP : clEP

var table calc = table.new(tPOS, 3, 18, bgcolor = #1e222d, border_color = #515359, border_width = 1, frame_color = #373a46, frame_width = 1)

if barstate.islast 
    if dbSH    
        table.cell(calc, 0, 0, "BAR STATISTICS\n", text_color = color.white, text_size = tSZ, bgcolor = #2962FF)
        table.merge_cells(calc, 0, 0, 2, 0)

        table.cell(calc, 0, 2, "Volatility", text_color = color.white, text_size = tSZ, text_halign = text.align_left)
        table.merge_cells(calc, 0, 2, 1, 2)
        table.cell(calc, 2, 2, aDB, text_color = color.white, text_size = tSZ)

        if nzV > 0
            table.cell(calc, 0, 1, "Activity", text_color = color.white, text_size = tSZ, text_halign = text.align_left)
            table.merge_cells(calc, 0, 1, 1, 1)
            table.cell(calc, 2, 1, vDB, text_color = color.white, text_size = tSZ)

            table.cell(calc, 0, 3, "Liquidations", text_color = color.white, text_size = tSZ, text_halign = text.align_left)
            table.merge_cells(calc, 0, 3, 1, 3)
            table.cell(calc, 2, 3, lDB + ' !', text_color = color.white, text_size = tSZ, 
             tooltip = 'The highest leverage of\n probable liquidated shorts : ' + (refP / (b.h - refP) > 100 ? '>100' : str.tostring(refP / (b.h - refP), '#.##')) + 
                   'x\n probable liquidated longs  : ' + (refP / (refP - b.l) > 100 ? '>100' : str.tostring(refP / (refP - b.l), '#.##')) + 
                   'x\n\nEstimantion based on\n reference price : '  + str.tostring(refP, format.mintick))

    if clSH
        table.cell(calc, 0, 4, "CALCULATOR\n", text_color = color.white, text_size = tSZ, bgcolor = #2962FF)
        table.merge_cells(calc, 0, 4, 2, 4)

        table.cell(calc, 0, 5, "Entry Price ", text_color = color.white, text_size = tSZ)
        table.merge_cells(calc, 0, 5, 1, 5)
        table.cell(calc, 2, 5, "Leverage", text_color = color.white, text_size = tSZ)

        table.cell(calc, 0, 6, str.tostring(refP, format.mintick), text_color = color.white, text_size = tSZ)
        table.merge_cells(calc, 0, 6, 1, 6)
        table.cell(calc, 2, 6, str.tostring(clLR), text_color = color.white, text_size = tSZ)

        tip = 'Liquidation price is the distance from trader\'s entry price to the price where trader\'s leveraged position gets liquidated due to a loss.\n\n' +
              'If a trader wants to enter a $1.000 trade with ' + str.tostring(clLR) + 'x leverage, then $' + str.tostring(1000/clLR, '#.##') + 
              ' is the initial margin (the amount of money coming from the traders pocket) and the remaining $' + str.tostring(1000 - 1000/clLR, '#.##') + ' are borrowed funds\n\n' +
              'When a trader\'s account falls below the required margin level, exchanges or brokerage platforms cannot allow a trader to lose borrowed funds and therefore the trader\'s positions will be forcibly closed as soon as position losses reach the initial margin.\n\n' +
              'The liquidation prices presented below are approximate values of both long and short liquidation prices. It is important to note that the exchanges will taken into consideration the trader\'s open positions when calculating the liquidation price. Unrealized PNL and maintenance margin of the trader\'s open position will affect the calculation of liquidation price'

        table.cell(calc, 0, 14, 'Liquidation Prices !', text_color = color.white, text_size = tSZ, tooltip = tip)
        table.merge_cells(calc, 0, 14, 2, 14)
        
        table.cell(calc, 0, 15, "█", text_color = color.teal, text_size = tSZ)
        table.cell(calc, 1, 15, "Longs", text_color = color.white, text_size = tSZ, text_halign = text.align_left)
        table.cell(calc, 2, 15, '≅ ' + str.tostring(refP * (1 - 1. / clLR), format.mintick) + ' (↓%' + str.tostring(100. / clLR, '#.##') + ')', 
         text_color = color.white, text_size = tSZ)
        
        table.cell(calc, 0, 16, "█", text_color = color.red, text_size = tSZ)
        table.cell(calc, 1, 16, "Shorts", text_color = color.white, text_size = tSZ, text_halign = text.align_left)
        table.cell(calc, 2, 16, '≅ ' + str.tostring(refP * (1 + 1. / clLR), format.mintick) + ' (↑%' + str.tostring(100. / clLR, '#.##') + ')', 
         text_color = color.white, text_size = tSZ)

    if lpSH
        if aCL.size() > 0
            for i = 1 to aCL.size()
                box.delete(aCL.shift())

        lLP = refP * (1 - 1. / clLR)
        sLP = refP * (1 + 1. / clLR)

        aCL.push(box.new(b.i, lLP, b.i + lcOF + 6, lLP, border_color = color.teal,
             text = 'Long Liquidation Price Level\n'  + (b.l < lLP ? 'trade liquidated' : '%' + str.tostring((math.abs(lLP / b.c - 1) * 100), '#.##') + ' (' + str.tostring(b.c - lLP, format.mintick) + ') to liquidation'), 
             text_size = size.small, text_halign = text.align_right, text_valign = text.align_top, text_color = color.teal))

        aCL.push(box.new(b.i + 2, refP, b.i + lcOF + 4, refP, border_color = color.gray))
    
        aCL.push(box.new(b.i, sLP, b.i + lcOF + 6, sLP, border_color = color.red,
             text = 'Short Liquidation Price Level\n' + (b.h > sLP ? 'trade liquidated' : '%' + str.tostring((math.abs(sLP / b.c - 1) * 100), '#.##') + ' (' + str.tostring(sLP - b.c, format.mintick) + ') to liquidation'), 
             text_size = size.small, text_halign = text.align_right, text_valign = text.align_bottom, text_color = color.red))

//-----------------------------------------------------------------------------}