// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=5

indicator('Multi-Chart Widget [LuxAlgo]', 'LuxAlgo - Multi-Chart Widget', true, max_lines_count = 500, scale = scale.none)

//---------------------------------------------------------------------------------------------------------------------
// Settings 
//---------------------------------------------------------------------------------------------------------------------{

disp  = display.all - display.status_line

genericGR = 'Mini Chart(s) Generic Settings'
separator = input.bool(true, 'Mini Charts Separator', group = genericGR)
numberOfBars = input.int(41, '  Number Of Bars', minval = 1, maxval = 73, group = genericGR, display = disp, tooltip = 'A maximum of 73 bars can be configured for each mini chart.')
hOffset = input.int(17, '  Horizontal Offset', minval = 10, maxval = 360, group = genericGR, display = disp, tooltip = 'Option range 10-360')

tfTT   = 'This option is utilized to calculate mini charts for higher timeframes. If a timeframe lower than the chart\'s timeframe is selected, calculations will be based on the chart\'s timeframe.'
htf1GR = 'Top Mini Chart Settings'
htf1SH = input.bool(true, 'Mini Chart Top', group = htf1GR)
htf1SY = input.symbol('' , '  Symbol', group = htf1GR, display = disp)
htf1TF = input.string('Chart', '  Timeframe', options = ['Chart', '5 Minutes', '15 Minutes', '1 Hour', '4 Hours', '1 Day', '1 Week', '1 Month'], group = htf1GR, display = disp, tooltip = tfTT)
htf1CT = input.string('Candles', '  Chart Type', options = ['Candles', 'Volume candles', 'Line', 'Area', 'Columns', 'High-low', 'Heikin Ashi'], group = htf1GR, display = disp)
htf1SZ = input.int(1, '  Chart Size', minval = 1, maxval = 5, group = htf1GR, display = disp)
htf1TI = input.string('Supertrend', '  Technical Indicator', options = ['Supertrend', 'Bollinger Bands', 'Moving Average', 'None'], group = htf1GR, display = disp)

htf2GR = 'Middle Mini Chart Settings'
htf2SH = input.bool(true, 'Mini Chart Middle', group = htf2GR)
htf2SY = input.symbol('' , '  Symbol', group = htf2GR, display = disp)
htf2TF = input.string('Chart', '  Timeframe', options = ['Chart', '5 Minutes', '15 Minutes', '1 Hour', '4 Hours', '1 Day', '1 Week', '1 Month'], group = htf2GR, display = disp, tooltip = tfTT)
htf2CT = input.string('Volume candles', '  Chart Type', options = ['Candles', 'Volume candles', 'Line', 'Area', 'Columns', 'High-low', 'Heikin Ashi'], group = htf2GR, display = disp)
htf2SZ = input.int(1, '  Chart Size', minval = 1, maxval = 5, group = htf2GR, display = disp)
htf2TI = input.string('Bollinger Bands', '  Technical Indicator', options = ['Supertrend', 'Bollinger Bands', 'Moving Average', 'None'], group = htf2GR, display = disp)

htf3GR = 'Bottom Mini Chart Settings'
htf3SH = input.bool(true, 'Mini Chart Bottom', group = htf3GR)
htf3SY = input.symbol('' , '  Symbol', group = htf3GR, display = disp)
htf3TF = input.string('Chart', '  Timeframe', options = ['Chart', '5 Minutes', '15 Minutes', '1 Hour', '4 Hours', '1 Day', '1 Week', '1 Month'], group = htf3GR, display = disp, tooltip = tfTT)
htf3CT = input.string('Area', '  Chart Type', options = ['Candles', 'Volume candles', 'Line', 'Area', 'Columns', 'High-low', 'Heikin Ashi'], group = htf3GR, display = disp)
htf3SZ = input.int(1, '  Chart Size', minval = 1, maxval = 5, group = htf3GR, display = disp)
htf3TI = input.string('Moving Average', '  Technical Indicator', options = ['Supertrend', 'Bollinger Bands', 'Moving Average', 'None'], group = htf3GR, display = disp)

stGR     = 'Supertrend Settings'
stLength = input.int(10, '  ATR Length', minval=1, group = stGR, display = disp)
stFactor = input.float(3, '  Factor', minval = 0.1, step = 0.1, group = stGR, display = disp)
stColor  = input.color(color.blue, '  Color', group = stGR)

maGR     = 'Moving Average Settings'
maTT     = 'Display various moving averages for chart/high timeframe mini charts.'
maType   = input.string("SMA", "  Type", options = ["SMA", "EMA", "HMA", "RMA", "WMA", "VWMA"], group = maGR, display = disp)
maSource = input.source(close, "  Source", group = maGR, display = disp)
maLength = input.int(5, "  Length", minval = 1, group = maGR, display = disp)
maColor  = input.color(color.orange, '  Color', group = maGR)

bbGR     = 'Bollinger Bands Settings'
bbType   = input.string("SMA", "  Basis Type", options = ["SMA", "EMA", "HMA", "RMA", "WMA", "VWMA"], group = bbGR, display = disp)
bbSource = input.source(close, "  Source", group = bbGR, display = disp)
bbLength = input.int(20, "  Length", minval = 1, group = bbGR, display = disp)
bbMult   = input.float(2.0, "  StdDev", minval=0.01, maxval=50, group = bbGR, display = disp)
bbbColor = input.color(color.new(color.orange, 50), '  Color Basis', group = bbGR)
bbuColor = input.color(color.blue, '  Color Upper Band', group = bbGR)
bblColor = input.color(color.blue, '  Color Lower Band', group = bbGR)

panleGR   = 'Mini Chart(s) Panel Settings'
panelSH   = input.bool(true, 'Mini Chart(s) Panel', group = panleGR)

dstSH     = input.bool(true, 'Dual Supertrend', group = panleGR)
st1Period = input.int(10, '  ST 1 : ATR Length', minval=1, group = panleGR, display = disp)
st1factor = input.float(2, '  ST 1 : Factor', minval = 0.1, step = 0.1, group = panleGR, display = disp)

st2Period = input.int(10, '  ST 2 : ATR Length', minval = 1, group = panleGR, display = disp)
st2factor = input.float(3, '  ST 2 : Factor', minval = 0.1, step = 0.1, group = panleGR, display = disp)

rsiSH     = input.bool(true, 'Relative Strength Index', group = panleGR)
rsiSource = input.source(close, '  Source', group = panleGR, display = disp)
rsiLength = input.int(14, '  Length', minval = 1, group = panleGR, display = disp)

vixSH     = input.bool(true, 'Volatility', group = panleGR)
vixLength = input.int(20, '  Length', minval = 1, group = panleGR, display = disp)

r2SH      = input.bool(true, 'R-Squared', group = panleGR)
r2Length  = input.int(20, '  Length', minval = 1, group = panleGR, display = disp)

//---------------------------------------------------------------------------------------------------------------------}
// User Defined Types
//---------------------------------------------------------------------------------------------------------------------{

type htfCharts
    line        []  bars
    chart.point []  tiUpperPoints
    chart.point []  tiBasisPoints
    chart.point []  tiLowerPoints
    chart.point []  chartPoints
    chart.point []  areaPoints
    polyline    []  stLineHide
    polyline        tiUpperLine
    polyline        tiBasisLine
    polyline        tiLowerLine
    polyline        chartLine
    polyline        areaLine
    label           panel
    label       []  supertrend

//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{

//---------------------------------------------------------------------------------------------------------------------}
// Functions / Methods
//---------------------------------------------------------------------------------------------------------------------{

timeframe(userTimeframe) =>
    float chartTFinM = timeframe.in_seconds() / 60

    switch 
        userTimeframe == "5 Minutes"  and chartTFinM <= 5    => '5'
        userTimeframe == "15 Minutes" and chartTFinM <= 15   => '15'
        userTimeframe == "1 Hour"     and chartTFinM <= 60   => '60'
        userTimeframe == "4 Hours"    and chartTFinM <= 240  => '240'
        userTimeframe == "1 Day"      and timeframe.isintraday => 'D'
        userTimeframe == "1 Week"     and (timeframe.isdaily or timeframe.isintraday) => 'W'
        userTimeframe == "1 Month"    and (timeframe.isweekly or timeframe.isdaily or timeframe.isintraday) => 'M'
        => timeframe.period

timeframeText(userTimeframe) =>
    tf = timeframe(userTimeframe)

    if not str.contains(tf, "D") and not str.contains(tf, "W") and not str.contains(tf, "M") and not str.contains(tf, "S")
        numTF = str.tonumber(tf)
        if numTF < 60
            tf + 'm'
        else
            str.tostring(numTF / 60) + 'H'
    else
        tf

syminfo(symbol) =>
    symbol != '' ? str.substring(ticker.standard(symbol), str.pos(ticker.standard(symbol), ":") + 1) : syminfo.ticker

checkExchange(chartTickerid, htf1SH, htf1SY, htf2SH, htf2SY, htf3SH, htf3SY) =>
    exchange = str.substring(chartTickerid, 0, str.pos(chartTickerid, ":")) 
    (htf1SH ? str.contains((htf1SY != '' ? htf1SY : syminfo.tickerid), exchange) : true) and (htf2SH ? str.contains((htf2SY != '' ? htf2SY : syminfo.tickerid), exchange) : true) and (htf3SH ? str.contains((htf3SY != '' ? htf3SY : syminfo.tickerid), exchange) : true)

movingAverage(source, length, maType) => 
    switch maType
        "SMA"  => ta.sma (source, length)
        "EMA"  => ta.ema (source, length)
        "HMA"  => ta.hma (source, length)
        "RMA"  => ta.rma (source, length)
        "WMA"  => ta.wma (source, length)
        "VWMA" => ta.vwma(source, length)

bollingerBands(source, length, multiplier, maType) =>
    [movingAverage(source, length, maType), multiplier * ta.stdev(source, length)]

supertrend(factor, atrPeriod) =>
    [supertrend, direction] = ta.supertrend(factor, atrPeriod)

supertrend(st1factor, st1Period, st2factor, st2Period) =>
    [_, direction1] = ta.supertrend(st1factor, st1Period)
    [_, direction2] = ta.supertrend(st2factor, st2Period)

    switch
        direction1 < 0 and direction2 < 0 => '\nDual Supertrend: ▲ Bullish'
        direction1 > 0 and direction2 > 0 => '\nDual Supertrend: ▼ Bearish'
        => '\nDual Supertrend: Trendless or Transitioning'

rsi(source, length) =>     
    rsi = ta.rsi(source, length)

    switch
        rsi > 70 => '\nRelative Strength: ▲ Overbought'
        rsi > 60 => '\nRelative Strength: ▲ Bullish'
        rsi > 40 => '\nRelative Strength: Neutral'
        rsi > 30 => '\nRelative Strength: ▼ Bearish'
        => '\nRelative Strength: ▼ Oversold'

volatility(length) =>
    str.tostring(math.abs(ta.ema(close - close[1], length) / ta.ema(math.abs(close - close[1]), length)), '\nVolatility: %#.##')

r2(length) =>
    str.tostring(math.pow(ta.correlation(close, bar_index, length), 2), '\nR²: %#.##')

volumeCandle(vol) =>
    volMa = ta.sma(vol, 9)
    vol > volMa * 4.669 ? 7 : vol > volMa * 2.618 ? 6 : vol > volMa * 1.618 ? 5 : vol > volMa ? 4 : vol > volMa * 0.618 ? 3 : 2

collectData(collect, technicalIndicator, tiMaxLength) =>

    var openArray = array.new_float()
    var highArray = array.new_float()
    var lowArray = array.new_float()
    var closeArray = array.new_float()
    var volumeWeightArray = array.new_int()

    var tiBasisArray = array.new_float()
    var tiComponentArray = array.new_float()
    var tiHighArray = array.new_float()
    var tiLowArray = array.new_float()

    if collect
        openArray.unshift(open)
        highArray.unshift(high)
        lowArray.unshift(low)
        closeArray.unshift(close)
        volumeWeightArray.unshift(volumeCandle(volume))

        [tiSource, tiComponent] = switch technicalIndicator
            'Supertrend' => supertrend(stFactor, stLength)
            'Bollinger Bands' => bollingerBands(bbSource, bbLength, bbMult, bbType)
            'Moving Average' => [movingAverage(maSource, maLength, maType), 1]
            => [close, close]

        if technicalIndicator == 'Bollinger Bands'
            tiHighArray.unshift(tiSource + tiComponent)
            tiLowArray.unshift(tiSource - tiComponent)
        else
            tiHighArray.unshift(tiSource)
            tiLowArray.unshift(tiSource)

        tiBasisArray.unshift(tiSource)
        tiComponentArray.unshift(tiComponent)

        rsiValue = rsi(rsiSource, rsiLength)
        dualStValue = supertrend(st1factor, st1Period, st2factor, st2Period)
        vixValue = volatility(vixLength)
        r2Value  = r2(r2Length)

        if closeArray.size() > numberOfBars + tiMaxLength//         if closeArray.size() > 2 * numberOfBars
            openArray.pop(), highArray.pop(), lowArray.pop(), closeArray.pop(), volumeWeightArray.pop()
            tiBasisArray.pop(), tiComponentArray.pop(), tiHighArray.pop(), tiLowArray.pop()

            [openArray, highArray, lowArray, closeArray, volumeWeightArray, 
             math.min(array.slice(lowArray , 0, numberOfBars + 1).min(), array.slice(tiLowArray , 0, numberOfBars + 1).min()), 
             math.max(array.slice(highArray, 0, numberOfBars + 1).max(), array.slice(tiHighArray, 0, numberOfBars + 1).max()), 
             tiBasisArray, tiComponentArray, rsiValue, dualStValue, vixValue, r2Value]
        else
            [openArray, highArray, lowArray, closeArray, volumeWeightArray, 
             math.min(array.slice(lowArray , 0, closeArray.size()).min(), array.slice(tiLowArray , 0, closeArray.size()).min()), 
             math.max(array.slice(highArray, 0, closeArray.size()).max(), array.slice(tiHighArray, 0, closeArray.size()).max()), 
             tiBasisArray, tiComponentArray, rsiValue, dualStValue, vixValue, r2Value]
            //[array.new<float>(na), array.new<float>(na), array.new<float>(na), array.new<float>(na), array.new<int>(na), 0., 0., array.new<float>(na), array.new<float>(na), '', '', '', str.tostring(closeArray.size())]

processData(htfSH, htfTF, htfSY, tiMaxLength, chart, openArray, highArray, lowArray, closeArray, volumeWeightArray, htfLST, htfHST, tiBasisArray, tiComponentArray, technicalIndicator, rsiSH, rsiValue, dstSH, dualStValue, vixSH, vixValue, r2SH, r2Value, offset, size) => 

    if htfSH
        var htfCharts htfChart = 
             htfCharts.new(
                 array.new<line>(na), 
                 array.new<chart.point>(na), 
                 array.new<chart.point>(na), 
                 array.new<chart.point>(na), 
                 array.new<chart.point>(na), 
                 array.new<chart.point>(na), 
                 array.new<polyline>(na), 
                 polyline.new(na), 
                 polyline.new(na), 
                 polyline.new(na), 
                 polyline.new(na), 
                 polyline.new(na), 
                 label(na), 
                 array.new<label>(na)
             )

        if closeArray.size() > 0 //numberOfBars - 1

            if htfChart.bars.size() > 0
                for i = 0 to htfChart.bars.size() - 1
                    line.delete(htfChart.bars.shift())

            if chart == 'Line' or chart == 'Area'
                htfChart.chartPoints.clear()
                htfChart.chartLine.delete()

            if chart == 'Area'
                htfChart.areaPoints.clear()
                htfChart.areaLine.delete()

            if htfChart.stLineHide.size() > 0
                for i = 0 to htfChart.stLineHide.size() - 1
                    polyline.delete(htfChart.stLineHide.shift())

            if technicalIndicator != 'None'
                htfChart.tiUpperPoints.clear()
                htfChart.tiUpperLine.delete()

                htfChart.tiBasisPoints.clear()
                htfChart.tiBasisLine.delete()

                htfChart.tiLowerPoints.clear()
                htfChart.tiLowerLine.delete()

            if htfChart.supertrend.size() > 0
                for i = 0 to htfChart.supertrend.size() - 1
                    label.delete(htfChart.supertrend.shift())

            for index = tiMaxLength to closeArray.size() - 1 // for index = numberOfBars to closeArray.size() - 1

                arrayIndex = closeArray.size() - index - 1 //arrayIndex = numberOfBars - index - 1
                barIndex = hOffset + bar_index + index - tiMaxLength // barIndex = hOffset + bar_index + index - numberOfBars
                barColor = chart == 'High-low' ? color.blue : openArray.get(arrayIndex) > closeArray.get(arrayIndex) ? color.red : color.teal
                barBody  = chart == 'Volume candles' ? volumeWeightArray.get(arrayIndex) : 3

                if chart != 'Line' and chart != 'Area'
                    if chart != 'High-low'
                        htfChart.bars.push(line.new(
                             barIndex, chart != 'Columns' ? size * (openArray.get(arrayIndex)  - htfLST) / (htfHST - htfLST) + offset : offset, 
                             barIndex, size * (closeArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset,
                             xloc.bar_index, extend.none, barColor, line.style_solid, barBody))

                    if chart != 'Columns'
                        htfChart.bars.push(line.new(
                             barIndex, size * (highArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset, 
                             barIndex, size * (lowArray.get(arrayIndex)  - htfLST) / (htfHST - htfLST) + offset, 
                             xloc.bar_index, extend.none, barColor, line.style_solid, chart == 'High-low' ? 3 : 1))
                else
                    htfChart.chartPoints.push(chart.point.from_index(barIndex, size * (closeArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset))

                if technicalIndicator != 'None' and tiBasisArray.get(arrayIndex) > 0
                    if technicalIndicator == 'Supertrend'
                        htfChart.tiBasisPoints.push(chart.point.from_index(barIndex, size * (tiBasisArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset))
                    else if technicalIndicator == 'Bollinger Bands'
                        htfChart.tiUpperPoints.push(chart.point.from_index(barIndex, size * ((tiBasisArray.get(arrayIndex) + tiComponentArray.get(arrayIndex)) - htfLST) / (htfHST - htfLST) + offset))
                        htfChart.tiBasisPoints.push(chart.point.from_index(barIndex, size * (tiBasisArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset))
                        htfChart.tiLowerPoints.push(chart.point.from_index(barIndex, size * ((tiBasisArray.get(arrayIndex) - tiComponentArray.get(arrayIndex)) - htfLST) / (htfHST - htfLST) + offset))
                    else
                        htfChart.tiBasisPoints.push(chart.point.from_index(barIndex, size * (tiBasisArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset))

            if chart == 'Line' or chart == 'Area'
                htfChart.chartLine := polyline.new(htfChart.chartPoints, false, false, xloc.bar_index, color.blue, color(na), line.style_solid, 2)

                if chart == 'Area'
                    htfChart.areaPoints := htfChart.chartPoints.copy()
                    htfChart.areaPoints.push(chart.point.from_index(hOffset + bar_index + numberOfBars - 1, offset))
                    htfChart.areaPoints.push(chart.point.from_index(hOffset + bar_index, offset))
                    htfChart.areaLine := polyline.new(htfChart.areaPoints, false, true, xloc.bar_index, color(na), color.new(color.blue, 93), line.style_solid, 1)

            if technicalIndicator != 'None'

                if technicalIndicator == 'Supertrend'
                    htfChart.tiBasisLine := polyline.new(htfChart.tiBasisPoints, false, false, xloc.bar_index, stColor, color(na), line.style_solid, 1)

                    for index = tiMaxLength to closeArray.size() - 1
                        arrayIndex = closeArray.size() - index - 1
                        barIndex = hOffset + bar_index + index - tiMaxLength

                        if arrayIndex < closeArray.size() - 1
                            if tiComponentArray.get(arrayIndex) != tiComponentArray.get(arrayIndex + 1)

                                htfChart.stLineHide.push(polyline.new(
                                 array.from(
                                     chart.point.from_index(barIndex - 1, size * (tiBasisArray.get(arrayIndex + 1) - htfLST) / (htfHST - htfLST) + offset),
                                     chart.point.from_index(barIndex, size * (tiBasisArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset)),
                                     false, false, xloc.bar_index, chart.bg_color, color(na), line.style_solid, 2)
                                 )

                                htfChart.supertrend.push(label.new(barIndex, size * (tiBasisArray.get(arrayIndex) - htfLST) / (htfHST - htfLST) + offset, '', color = stColor, style = label.style_circle, size = size.auto))

                else if technicalIndicator == 'Bollinger Bands'
                    htfChart.tiUpperLine := polyline.new(htfChart.tiUpperPoints, false, false, xloc.bar_index, bbuColor, color(na), line.style_solid, 1)
                    htfChart.tiBasisLine := polyline.new(htfChart.tiBasisPoints, false, false, xloc.bar_index, bbbColor, color(na), line.style_solid, 1)
                    htfChart.tiLowerLine := polyline.new(htfChart.tiLowerPoints, false, false, xloc.bar_index, bblColor, color(na), line.style_solid, 1)
                else
                    htfChart.tiBasisLine := polyline.new(htfChart.tiBasisPoints, false, false, xloc.bar_index, maColor, color(na), line.style_solid, 1)

            if panelSH
                panelText = syminfo(htfSY) + ' (' + str.tostring(closeArray.first()) + ') · ' + timeframeText(htfTF) + ' · (' + chart + ')\n' + (dstSH ? dualStValue : '') + (rsiSH ? rsiValue : '') + (vixSH ? vixValue : '') + (r2SH ? r2Value : '')
                htfChart.panel.delete(), htfChart.panel := label.new(hOffset + bar_index + numberOfBars + 5, size * (math.avg(htfHST, htfLST) - htfLST) / (htfHST - htfLST) + offset, panelText, color = color(na), style = label.style_label_left, textcolor = chart.fg_color, textalign = text.align_left)
        else
            panelText = syminfo(htfSY) + '\nThere isn\'t enough data available (' + r2Value + ' bars) for the selected timeframe ' + timeframeText(htfTF)
            htfChart.panel.delete(), htfChart.panel := label.new(hOffset + bar_index + numberOfBars, offset + 0.5, panelText, color = color(na), style = label.style_label_down, textcolor = chart.fg_color, textalign = text.align_left)

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{

tiMaxLength = math.max(stLength, maLength, bbLength)

htf1SY := htf1CT == 'Heikin Ashi' ? htf1SY != '' ? ticker.heikinashi(htf1SY) : ticker.heikinashi(syminfo.tickerid) : htf1SY != '' ? ticker.standard(htf1SY) : ticker.standard(syminfo.tickerid) 
[openArray1, highArray1, lowArray1, closeArray1, volumeWeightArray1, htfLST1, htfHST1, tiBasisArray1, tiComponentArray1, rsiValue1, dualStValue1, vixValue1, r2Value1] = 
 request.security(htf1SY, timeframe(htf1TF), collectData(htf1SH, htf1TI, tiMaxLength), calc_bars_count = numberOfBars + tiMaxLength + 1) // 2 * numberOfBars + 1

htf2SY := htf2CT == 'Heikin Ashi' ? htf2SY != '' ? ticker.heikinashi(htf2SY) : ticker.heikinashi(syminfo.tickerid) : htf1SY != '' ? ticker.standard(htf2SY) : ticker.standard(syminfo.tickerid) 
[openArray2, highArray2, lowArray2, closeArray2, volumeWeightArray2, htfLST2, htfHST2, tiBasisArray2, tiComponentArray2, rsiValue2, dualStValue2, vixValue2, r2Value2] = 
 request.security(htf2SY, timeframe(htf2TF), collectData(htf2SH, htf2TI, tiMaxLength), calc_bars_count = numberOfBars + tiMaxLength + 1) // 2 * numberOfBars + 1

htf3SY := htf3CT == 'Heikin Ashi' ? htf3SY != '' ? ticker.heikinashi(htf3SY) : ticker.heikinashi(syminfo.tickerid) : htf1SY != '' ? ticker.standard(htf3SY) : ticker.standard(syminfo.tickerid) 
[openArray3, highArray3, lowArray3, closeArray3, volumeWeightArray3, htfLST3, htfHST3, tiBasisArray3, tiComponentArray3, rsiValue3, dualStValue3, vixValue3, r2Value3] = 
 request.security(htf3SY, timeframe(htf3TF), collectData(htf3SH, htf3TI, tiMaxLength), calc_bars_count = numberOfBars + tiMaxLength + 1) // 2 * numberOfBars + 1

//log.info("yaz_kizim {0} {1} {2}", str.contains(htf1SY, str.substring(syminfo.tickerid, 0, str.pos(syminfo.tickerid, ":"))), str.substring(syminfo.tickerid, 0, str.pos(syminfo.tickerid, ":")), checkExchange(syminfo.tickerid, htf1SH, htf1SY, htf2SH, htf2SY, htf3SH, htf3SY))

var label lbWarning = na

if barstate.islast and last_bar_index > numberOfBars + tiMaxLength - 1
    lbWarning.delete()

    if  barstate.isrealtime or checkExchange(syminfo.tickerid, htf1SH, htf1SY, htf2SH, htf2SY, htf3SH, htf3SY) // session.ismarket or 

        processData(htf1SH, htf1TF, htf1SY, tiMaxLength, htf1CT, openArray1, highArray1, lowArray1, closeArray1, volumeWeightArray1, htfLST1, htfHST1, tiBasisArray1, tiComponentArray1, htf1TI, rsiSH, rsiValue1, dstSH, dualStValue1, vixSH, vixValue1, r2SH, r2Value1, 1.1 + (htf3SH ? 1.1 + htf3SZ - 1 : 1.1) + (htf2SH ? 1.1 + htf2SZ - 1 : 0), htf1SZ)
        processData(htf2SH, htf2TF, htf2SY, tiMaxLength, htf2CT, openArray2, highArray2, lowArray2, closeArray2, volumeWeightArray2, htfLST2, htfHST2, tiBasisArray2, tiComponentArray2, htf2TI, rsiSH, rsiValue2, dstSH, dualStValue2, vixSH, vixValue2, r2SH, r2Value2, 1.1 + (htf3SH ? 1.1 + htf3SZ - 1 : 1.1), htf2SZ)
        processData(htf3SH, htf3TF, htf3SY, tiMaxLength, htf3CT, openArray3, highArray3, lowArray3, closeArray3, volumeWeightArray3, htfLST3, htfHST3, tiBasisArray3, tiComponentArray3, htf3TI, rsiSH, rsiValue3, dstSH, dualStValue3, vixSH, vixValue3, r2SH, r2Value3, 1.1, htf3SZ)

        var line lnVertical = na, var line lnHorizontal1 = na, var line lnHorizontal2 = na
        if separator and (htf1SH or htf2SH or htf3SH)
            lnVertical.delete(), lnVertical := line.new(bar_index + hOffset - 5, 2.2, bar_index + hOffset - 5, 2.2, extend = extend.both, color = color.new(chart.fg_color, 41), width = 1)
        
            spCount = (htf1SH ? 1 : 0) + (htf2SH ? 1 : 0) + (htf3SH ? 1 : 0)

            if spCount > 1
                yValue = 1.15 + (htf3SH ? htf3SZ : htf2SH ? htf2SZ + 1.1 : 1)
                lnHorizontal1.delete(), lnHorizontal1 := line.new(bar_index + hOffset - 5, yValue, bar_index + hOffset, yValue, extend = extend.right, color = color.new(chart.fg_color, 41), width = 1)
            if spCount > 2
                yValue = 2.25 + (htf3SH ? htf3SZ : 1) + (htf2SH ? htf2SZ - 1 : 0)
                lnHorizontal2.delete(), lnHorizontal2 := line.new(bar_index + hOffset - 5, yValue, bar_index + hOffset, yValue, extend = extend.right, color = color.new(chart.fg_color, 41), width = 1)
    else
        txt = 'The Multi-Chart Snapshot [LuxAlgo] tool supports the display of mini charts featuring various types of instruments alongside the primary chart instrument.\n' +
               'However, this functionality is subject to a limitation: the selected primary chart instrument must have an ACTIVE market status.\n\n' +
               'The market for the ' + syminfo.type + ' ' + syminfo.description + '(' + syminfo.ticker + ') on the ' + syminfo.prefix(syminfo.tickerid) + ' exchange is currently CLOSED or no new data available.\n\n' +
               'Options:\n -Selecting an active primary chart instrument, or\n' +
               ' -Ensuring that the mini chart instruments belong to the same exchange and have the same type as the primary chart instrument (' + syminfo.ticker + ').\n\n' +
               'If the above conditions are met, please wait a few seconds for the data to be loaded during the initial execution.'
        lbWarning.delete(), lbWarning := label.new(bar_index + hOffset - 5, 1.1, txt, color = color(na), style = label.style_label_left, textcolor = chart.fg_color, textalign = text.align_left)
else
    txt = 'There isn\'t enough data available;\nEnsure that the number of chart bars is at least more than ' + str.tostring(numberOfBars + tiMaxLength) + '\nReducing the number of bars set for the mini charts may help.'
    lbWarning.delete(), lbWarning := label.new(bar_index + hOffset - 5, 1.1, txt, color = color(na), style = label.style_label_left, textcolor = chart.fg_color, textalign = text.align_left)

//---------------------------------------------------------------------------------------------------------------------}