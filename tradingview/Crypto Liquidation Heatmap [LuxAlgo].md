// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=5

indicator("Crypto Liquidation Heatmap [LuxAlgo]", "LuxAlgo - Crypto Liquidation Heatmap", true)
//---------------------------------------------------------------------------------------------------------------------
// Settings
//---------------------------------------------------------------------------------------------------------------------{
disp  = display.all - display.status_line

symGR = 'Cryptocurrency Asset List'
tTip  = 'It is highly recommended to select instruments from the same exchange with same currency to maintain proportional integrity among the chosen assets, ' +
         'as different exchanges may have varying trading volumes.\n\nSupported currencies include USD, USDT, USDC, USDP, and USDD. Remember to use the same currency when selecting assets.'

sym01 = input.symbol('BINANCE:BTCUSDT'  , 'Symbol 01', tooltip = tTip, group = symGR, display = disp)
sym02 = input.symbol('BINANCE:ETHUSDT'  , 'Symbol 02', tooltip = tTip, group = symGR, display = disp)
sym03 = input.symbol('BINANCE:BNBUSDT'  , 'Symbol 03', tooltip = tTip, group = symGR, display = disp)
sym04 = input.symbol('BINANCE:SOLUSDT'  , 'Symbol 04', tooltip = tTip, group = symGR, display = disp)
sym05 = input.symbol('BINANCE:XRPUSDT'  , 'Symbol 05', tooltip = tTip, group = symGR, display = disp)
sym06 = input.symbol('BINANCE:ADAUSDT'  , 'Symbol 06', tooltip = tTip, group = symGR, display = disp)
sym07 = input.symbol('BINANCE:DOGEUSDT' , 'Symbol 07', tooltip = tTip, group = symGR, display = disp)
sym08 = input.symbol('BINANCE:AVAXUSDT' , 'Symbol 08', tooltip = tTip, group = symGR, display = disp)
sym09 = input.symbol('BINANCE:SHIBUSDT' , 'Symbol 09', tooltip = tTip, group = symGR, display = disp)
sym10 = input.symbol('BINANCE:DOTUSDT'  , 'Symbol 10', tooltip = tTip, group = symGR, display = disp)
sym11 = input.symbol('BINANCE:POLUSDT'  , 'Symbol 11', tooltip = tTip, group = symGR, display = disp)
sym12 = input.symbol('BINANCE:LINKUSDT' , 'Symbol 12', tooltip = tTip, group = symGR, display = disp)
sym13 = input.symbol('BINANCE:TRXUSDT'  , 'Symbol 13', tooltip = tTip, group = symGR, display = disp)
sym14 = input.symbol('BINANCE:BCHUSDT'  , 'Symbol 14', tooltip = tTip, group = symGR, display = disp)
sym15 = input.symbol('BINANCE:UNIUSDT'  , 'Symbol 15', tooltip = tTip, group = symGR, display = disp)
sym16 = input.symbol('BINANCE:NEARUSDT' , 'Symbol 16', tooltip = tTip, group = symGR, display = disp)
sym17 = input.symbol('BINANCE:LTCUSDT'  , 'Symbol 17', tooltip = tTip, group = symGR, display = disp)
sym18 = input.symbol('BINANCE:ICPUSDT'  , 'Symbol 18', tooltip = tTip, group = symGR, display = disp)
sym19 = input.symbol('BINANCE:FILUSDT'  , 'Symbol 19', tooltip = tTip, group = symGR, display = disp)
sym20 = input.symbol('BINANCE:ATOMUSDT' , 'Symbol 20', tooltip = tTip, group = symGR, display = disp)

scrGR = 'Liquidation Heatmap Settings'
scrPS = input.string('Top Right', 'Position', options=['Top Left', 'Top Center', 'Top Right', 'Middle Left', 'Middle Center', 'Middle Right', 'Bottom Left', 'Bottom Center', 'Bottom Right'], group = scrGR, display = disp)

scrSZ = input.string('Large', 'Size', options=['Large', 'Small'], group = scrGR, display = disp)
scrSz = scrSZ == 'Large'

//---------------------------------------------------------------------------------------------------------------------}
// User Defined Types
//---------------------------------------------------------------------------------------------------------------------{
type liqData
    string  cell
    string  tooltip
    color   color
    string  type

//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{
symbolData = array.new<liqData>()
totalLiquidation = array.new_float()

scrP = switch scrPS
    'Top Left'      => position.top_left
    'Top Center'    => position.top_center
    'Top Right'     => position.top_right
    'Middle Left'   => position.middle_left
    'Middle Center' => position.middle_center
    'Middle Right'  => position.middle_right
    'Bottom Left'   => position.bottom_left
    'Bottom Center' => position.bottom_center
    'Bottom Right'  => position.bottom_right

var table tb = table.new(scrP, 20, 12, border_width = 3)

//---------------------------------------------------------------------------------------------------------------------}
// Functions / Methods
//---------------------------------------------------------------------------------------------------------------------{
collectSymbolData(symbol, elapsedTime) =>
    [long, short, price, symtype] = request.security(symbol, timeframe.period,
          [volume * (open - low ) * math.avg(math.min(open, close), low ) / open,
           volume * (high - open) * math.avg(math.max(open, close), high) / open,
           math.round(close / syminfo.mintick) * syminfo.mintick, syminfo.type],
          ignore_invalid_symbol = true)

    if str.contains(symtype, "crypto")
        syminfo = str.substring(symbol, str.pos(symbol, ":") + 1)
        symbolData.push(liqData.new(
             str.replace(syminfo, str.match(syminfo, "US[\\w]+"),  "", 0) + '\n$' + str.tostring(long + short, format.volume),
             syminfo + ' ' + str.tostring(price) + '\n\nLiquidation  ' + str.tostring(long + short, format.volume) + '\nLong     ' + str.tostring(long, format.volume) + '\nShort    ' + str.tostring(short, format.volume)+ '\n\nDuration    ' + elapsedTime,
             long > short ? color.new(#089981, 13) : color.new(#f23645, 13), symtype))
        totalLiquidation.push(long + short)

// 20-slot treemap placement (unique coords)
setTableCell(idx, value) =>
    if idx == 0
        tb.cell_set_text(0, 0,  symbolData.get(value).cell),  tb.cell_set_tooltip(0, 0,  symbolData.get(value).tooltip),  tb.cell_set_bgcolor(0, 0,  symbolData.get(value).color)
    else if idx == 1
        tb.cell_set_text(0, 8,  symbolData.get(value).cell),  tb.cell_set_tooltip(0, 8,  symbolData.get(value).tooltip),  tb.cell_set_bgcolor(0, 8,  symbolData.get(value).color)
    else if idx == 2
        tb.cell_set_text(6, 0,  symbolData.get(value).cell),  tb.cell_set_tooltip(6, 0,  symbolData.get(value).tooltip),  tb.cell_set_bgcolor(6, 0,  symbolData.get(value).color)
    else if idx == 3
        tb.cell_set_text(6, 4,  symbolData.get(value).cell),  tb.cell_set_tooltip(6, 4,  symbolData.get(value).tooltip),  tb.cell_set_bgcolor(6, 4,  symbolData.get(value).color)
    else if idx == 4
        tb.cell_set_text(6, 9,  symbolData.get(value).cell),  tb.cell_set_tooltip(6, 9,  symbolData.get(value).tooltip),  tb.cell_set_bgcolor(6, 9,  symbolData.get(value).color)
    else if idx == 5
        tb.cell_set_text(10, 0, symbolData.get(value).cell),  tb.cell_set_tooltip(10, 0, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(10, 0, symbolData.get(value).color)
    else if idx == 6
        tb.cell_set_text(10, 3, symbolData.get(value).cell),  tb.cell_set_tooltip(10, 3, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(10, 3, symbolData.get(value).color)
    else if idx == 7
        tb.cell_set_text(10, 6, symbolData.get(value).cell),  tb.cell_set_tooltip(10, 6, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(10, 6, symbolData.get(value).color)
    else if idx == 8
        tb.cell_set_text(10, 9, symbolData.get(value).cell),  tb.cell_set_tooltip(10, 9, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(10, 9, symbolData.get(value).color)
    else if idx == 9
        tb.cell_set_text(15, 0, symbolData.get(value).cell),  tb.cell_set_tooltip(15, 0, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(15, 0, symbolData.get(value).color)
    else if idx == 10
        tb.cell_set_text(18, 0, symbolData.get(value).cell),  tb.cell_set_tooltip(18, 0, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(18, 0, symbolData.get(value).color)
    else if idx == 11
        tb.cell_set_text(14, 3, symbolData.get(value).cell),  tb.cell_set_tooltip(14, 3, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(14, 3, symbolData.get(value).color)
    else if idx == 12
        tb.cell_set_text(17, 3, symbolData.get(value).cell),  tb.cell_set_tooltip(17, 3, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(17, 3, symbolData.get(value).color)
    else if idx == 13
        tb.cell_set_text(14, 6, symbolData.get(value).cell),  tb.cell_set_tooltip(14, 6, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(14, 6, symbolData.get(value).color)
    else if idx == 14
        tb.cell_set_text(14, 8, symbolData.get(value).cell),  tb.cell_set_tooltip(14, 8, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(14, 8, symbolData.get(value).color)
    else if idx == 15
        tb.cell_set_text(14,10, symbolData.get(value).cell),  tb.cell_set_tooltip(14,10, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(14,10, symbolData.get(value).color)
    else if idx == 16
        tb.cell_set_text(18, 6, symbolData.get(value).cell),  tb.cell_set_tooltip(18, 6, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(18, 6, symbolData.get(value).color)
    else if idx == 17
        tb.cell_set_text(18, 7, symbolData.get(value).cell),  tb.cell_set_tooltip(18, 7, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(18, 7, symbolData.get(value).color)
    else if idx == 18
        tb.cell_set_text(18, 8, symbolData.get(value).cell),  tb.cell_set_tooltip(18, 8, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(18, 8, symbolData.get(value).color)
    else if idx == 19
        tb.cell_set_text(18, 9, symbolData.get(value).cell),  tb.cell_set_tooltip(18, 9, symbolData.get(value).tooltip),  tb.cell_set_bgcolor(18, 9, symbolData.get(value).color)

// elapsed time label
measureElapsedTime() =>
    timeDiff = timenow - time
    h = math.floor(timeDiff / 3600000) % 24
    ht = h < 10 ? '0' + str.tostring(h) : str.tostring(h)
    m = math.floor(timeDiff / 60000) % 60
    mt = m < 10 ? '0' + str.tostring(m) : str.tostring(m)
    s = math.floor(timeDiff / 1000) % 60
    st = s < 10 ? '0' + str.tostring(s) : str.tostring(s)
    if timeframe.isweekly or timeframe.ismonthly
        D = dayofmonth(int(timeDiff))
        str.tostring(D) + 'D-' + ht + ':' + mt  + ':' + st
    else
        ht + ':' + mt  + ':' + st

//---------------------------------------------------------------------------------------------------------------------}
// Layout (no overlaps)
//---------------------------------------------------------------------------------------------------------------------{
if barstate.isfirst
    table.cell(tb, 0, 0, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.huge : size.normal)
    table.merge_cells(tb, 0, 0, 5, 7)

    table.cell(tb, 0, 8, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.huge : size.normal)
    table.merge_cells(tb, 0, 8, 5, 11)

    table.cell(tb, 6, 0, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.large : size.small)
    table.merge_cells(tb, 6, 0, 9, 3)

    table.cell(tb, 6, 4, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.large : size.small)
    table.merge_cells(tb, 6, 4, 9, 8)

    table.cell(tb, 6, 9, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.large : size.small)
    table.merge_cells(tb, 6, 9, 9, 11)

    table.cell(tb, 10, 0, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 10, 0, 14, 2)

    table.cell(tb, 10, 3, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 10, 3, 13, 5)

    table.cell(tb, 10, 6, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 10, 6, 13, 8)

    table.cell(tb, 10, 9, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 10, 9, 13, 11)

    table.cell(tb, 15, 0, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 15, 0, 17, 2)

    table.cell(tb, 18, 0, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.normal : size.tiny)
    table.merge_cells(tb, 18, 0, 19, 2)

    table.cell(tb, 14, 3, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.small : size.tiny)
    table.merge_cells(tb, 14, 3, 16, 5)

    table.cell(tb, 17, 3, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.small : size.tiny)
    table.merge_cells(tb, 17, 3, 19, 5)

    table.cell(tb, 14, 6, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.small : size.tiny)
    table.merge_cells(tb, 14, 6, 17, 7)

    table.cell(tb, 14, 8, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.small : size.tiny)
    table.merge_cells(tb, 14, 8, 17, 9)

    table.cell(tb, 14, 10, '', text_color = color.white, text_halign = text.align_left, text_size = scrSz ? size.small : size.tiny)
    table.merge_cells(tb, 14, 10, 17, 11)

    // bottom-right tiny singles (4 distinct boxes)
    table.cell(tb, 18, 6, '', text_color = color.white, text_halign = text.align_left, text_size = size.tiny)
    table.merge_cells(tb, 18, 6, 19, 6)

    table.cell(tb, 18, 7, '', text_color = color.white, text_halign = text.align_left, text_size = size.tiny)
    table.merge_cells(tb, 18, 7, 19, 7)

    table.cell(tb, 18, 8, '', text_color = color.white, text_halign = text.align_left, text_size = size.tiny)
    table.merge_cells(tb, 18, 8, 19, 8)

    table.cell(tb, 18, 9, '', text_color = color.white, text_halign = text.align_left, text_size = size.tiny)
    table.merge_cells(tb, 18, 9, 19, 11)

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
elapsedTime = measureElapsedTime()

if barstate.islast
    collectSymbolData(sym01, elapsedTime)
    collectSymbolData(sym02, elapsedTime)
    collectSymbolData(sym03, elapsedTime)
    collectSymbolData(sym04, elapsedTime)
    collectSymbolData(sym05, elapsedTime)
    collectSymbolData(sym06, elapsedTime)
    collectSymbolData(sym07, elapsedTime)
    collectSymbolData(sym08, elapsedTime)
    collectSymbolData(sym09, elapsedTime)
    collectSymbolData(sym10, elapsedTime)
    collectSymbolData(sym11, elapsedTime)
    collectSymbolData(sym12, elapsedTime)
    collectSymbolData(sym13, elapsedTime)
    collectSymbolData(sym14, elapsedTime)
    collectSymbolData(sym15, elapsedTime)
    collectSymbolData(sym16, elapsedTime)
    collectSymbolData(sym17, elapsedTime)
    collectSymbolData(sym18, elapsedTime)
    collectSymbolData(sym19, elapsedTime)
    collectSymbolData(sym20, elapsedTime)

    sortedIndices = totalLiquidation.sort_indices(order.descending)

    for [index, value] in sortedIndices
        if index < 20 and str.contains(symbolData.get(value).type, "crypto")
            setTableCell(index, value)

//---------------------------------------------------------------------------------------------------------------------}
