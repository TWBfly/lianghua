// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=5

indicator("VWAP Periodic Close [LuxAlgo]", 'LuxAlgo - VWAP Periodic Close', true)

//---------------------------------------------------------------------------------------------------------------------
// Settings 
//---------------------------------------------------------------------------------------------------------------------{

display  = display.all - display.status_line

optionTT = 'VWAP Close Level toggles the display of the level where the VWAP closes at the end of the specified period\n\nVWAP Origin toggles the display of the VWAP line for that period\n\nHistorical Closes option defines how many levels will be plotted for that period'

group_dVWAP = 'Daily - Volume Weighted Average Price (VWAP)'

isdVWAPc    = input.bool(true, 'VWAP Close Level', inline = 'dVWAP', group = group_dVWAP, tooltip = optionTT)
isdVWAP     = input.bool(true, 'VWAP Origin', inline = 'dVWAP', group = group_dVWAP)
dVWAPSource = input.source(hlc3, 'VWAP Source', inline = 'dVWAP2', group = group_dVWAP, display = display)
dHistorical = input.int(1, "Historical Closes", minval = 0, group = group_dVWAP, display = display)
dOffset     = input.int(17, "Line/Label Offset", minval = 0, maxval = 500, group = group_dVWAP, display = display)

group_wVWAP = 'Weekly - Volume Weighted Average Price (VWAP)'

iswVWAPc    = input.bool(true, 'VWAP Close Level', inline = 'dVWAP', group = group_wVWAP, tooltip = optionTT)
iswVWAP     = input.bool(true, 'VWAP Origin', inline = 'dVWAP', group = group_wVWAP)
wVWAPSource = input.source(hlc3, 'VWAP Source', inline = 'dVWAP2', group = group_wVWAP, display = display)
wHistorical = input.int(3, "Historical Closes", minval = 0, group = group_wVWAP, display = display)
wOffset     = input.int(17, "Line/Label Offset", minval = 0, maxval = 500, group = group_wVWAP, display = display)

group_mVWAP = 'Monthly - Volume Weighted Average Price (VWAP)'

ismVWAPc    = input.bool(true, 'VWAP Close Level', inline = 'dVWAP', group = group_mVWAP, tooltip = optionTT)
ismVWAP     = input.bool(true, 'VWAP Origin', inline = 'dVWAP', group = group_mVWAP)
mVWAPSource = input.source(hlc3, 'VWAP Source', inline = 'dVWAP2', group = group_mVWAP, display = display)
mHistorical = input.int(2, "Historical Closes", minval = 0, group = group_mVWAP, display = display)
mOffset     = input.int(17, "Line/Label Offset", minval = 0, maxval = 500, group = group_mVWAP, display = display)

group_qVWAP = 'Quarterly - Volume Weighted Average Price (VWAP)'

isqVWAPc    = input.bool(false, 'VWAP Close Level', inline = 'dVWAP', group = group_qVWAP, tooltip = optionTT)
isqVWAP     = input.bool(false, 'VWAP Origin', inline = 'dVWAP', group = group_qVWAP)
qVWAPSource = input.source(hlc3, 'VWAP Source', inline = 'dVWAP2', group = group_qVWAP, display = display)
qHistorical = input.int(1, "Historical Closes", minval = 0, group = group_qVWAP, display = display)
qOffset     = input.int(17, "Line/Label Offset", minval = 0, maxval = 500, group = group_qVWAP, display = display)

group_yVWAP = 'Yearly - Volume Weighted Average Price (VWAP)'

isyVWAPc    = input.bool(false, 'VWAP Close Level', inline = 'dVWAP', group = group_yVWAP, tooltip = optionTT)
isyVWAP     = input.bool(false, 'VWAP Origin', inline = 'dVWAP', group = group_yVWAP)
yVWAPSource = input.source(hlc3, 'VWAP Source', inline = 'dVWAP2', group = group_yVWAP, display = display)
yHistorical = input.int(1, "Historical Closes", minval = 0, group = group_yVWAP, display = display)
yOffset     = input.int(17, "Line/Label Offset", minval = 0, maxval = 500, group = group_yVWAP, display = display)

group_Theme = 'Themes'
theme = input.string("Custom", 'Themes', options = ["Day", "Night", "Custom"], group = group_Theme, display = display)

dVWAPColor  = input.color(#e91e63, 'D', inline = 'dVWAP2', group = group_Theme)
wVWAPColor  = input.color(#2962ff, 'W', inline = 'dVWAP2', group = group_Theme)
mVWAPColor  = input.color(#00bcd4, 'M', inline = 'dVWAP2', group = group_Theme)
qVWAPColor  = input.color(#089981, 'Q', inline = 'dVWAP2', group = group_Theme)
yVWAPColor  = input.color(#ff9800, 'Y', inline = 'dVWAP2', group = group_Theme)

//---------------------------------------------------------------------------------------------------------------------}
// User Defined Types
//---------------------------------------------------------------------------------------------------------------------{

type VWAP
    chart.point []  points
    polyline    []  lines

//---------------------------------------------------------------------------------------------------------------------}
// Functions / Methods
//---------------------------------------------------------------------------------------------------------------------{

monthh(m) =>
    switch m 
        1 => 'Jan'
        2 => 'Feb'
        3 => 'Mar'
        4 => 'Apr'
        5 => 'May'
        6 => 'Jun'
        7 => 'Jul'
        8 => 'Aug'
        9 => 'Sep'
        10 => 'Oct'
        11 => 'Nov'
        12 => 'Dec'

date(t) =>
    D = dayofmonth(t)
    monthh(month(t)) + '-' + (D < 10 ? '0' + str.tostring(D) : str.tostring(D)) + '-' + str.tostring(year(t)) + ' · '

renderVWAPCloses(source, period, historical, txt, color, offset, origin) => 
    isVoly = ta.cum(volume) > 0
    anchor = timeframe.change(period)
    vwap   = ta.vwap(source, anchor)

    if isVoly

        var vwapLinesArray = array.new_line()
        var vwapLabelsArray = array.new_label()
        var vwapDateArray = array.new_string()

        var VWAP vwapArray = VWAP.new(array.new<chart.point>(na), array.new<polyline>(na))
        var int firstTime = time 
        if anchor 
            vwapLinesArray.push(line.new(bar_index[1], vwap[1], bar_index[1] + offset, vwap[1], color = color, width = 2))
            vwapLabelsArray.push(label.new(bar_index[1] + offset, vwap[1], date(time) + txt + '(1) · ' + str.tostring(vwap[1], format.mintick), color = color.new(color, 73), textcolor = color, style = label.style_label_left, tooltip = str.tostring(vwap[1], format.mintick)))
            vwapDateArray.push(date(firstTime))
            firstTime := time

            if origin
                vwapArray.lines.push(polyline.new(vwapArray.points, false, false, line_color = color))
                vwapArray.points.clear()
                vwapArray.points.push(chart.point.from_index(bar_index, vwap))

            if vwapArray.lines.size() > historical
                vwapArray.lines.shift().delete()

            if vwapLinesArray.size() > historical
                vwapLinesArray.shift().delete()

            if vwapLabelsArray.size() > historical
                vwapLabelsArray.shift().delete()

            if vwapDateArray.size() > historical
                vwapDateArray.shift()

            for [index, value] in vwapLabelsArray
                value.set_text(vwapDateArray.get(index) + txt + '(' + str.tostring(vwapLabelsArray.size() - index) + ')' + ' · ' + str.tostring(value.get_y(), format.mintick))
            
        else if vwapLinesArray.size() > 0 and vwapLabelsArray.size() > 0
            if origin
                vwapArray.points.push(chart.point.from_index(bar_index, vwap))

            for currentElement in vwapLinesArray
                currentElement.set_x2(bar_index + offset)

            for currentElement in vwapLabelsArray
                currentElement.set_x(bar_index + offset)
    else
        var table note = table.new(position.bottom_right, 1, 1)
        if barstate.islast
            table.cell(note, 0, 0, 'No volume is provided by the data vendor.      \n\n', text_size = size.normal, text_color = chart.fg_color)

switch theme
    'Day' => dVWAPColor := #cf476f, wVWAPColor := #ffd166, mVWAPColor := #06d6a0, qVWAPColor := #118ab2, yVWAPColor := #073b4c
    'Night' => dVWAPColor := #f48fb1, wVWAPColor := #90bff9, mVWAPColor := #80deea, qVWAPColor := #70ccbd, yVWAPColor := #ffcc80

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{

bgcolor(theme == 'Day' ? #ffffff : theme == 'Night' ? #000000 : na)
bgcolor(theme == 'Day' ? #ffffff : theme == 'Night' ? #000000 : na, 1001)


if isdVWAPc and timeframe.isintraday
    renderVWAPCloses(dVWAPSource, 'D'  , dHistorical, 'DAILY', dVWAPColor, dOffset, isdVWAP) 

if iswVWAPc and (timeframe.isdaily or timeframe.isintraday)
    renderVWAPCloses(wVWAPSource, 'W'  , wHistorical, 'WEEKLY', wVWAPColor, wOffset, iswVWAP) 

if ismVWAPc and (timeframe.isweekly or timeframe.isdaily or timeframe.isintraday)
    renderVWAPCloses(mVWAPSource, 'M'  , mHistorical, 'MONTHLY', mVWAPColor, mOffset, ismVWAP) 

if isqVWAPc and (timeframe.ismonthly or timeframe.isweekly or timeframe.isdaily or timeframe.isintraday)
    renderVWAPCloses(qVWAPSource, '3M' , qHistorical, 'QUARTERLY', qVWAPColor, qOffset, isqVWAP) 

if isyVWAPc and (timeframe.ismonthly or timeframe.isweekly or timeframe.isdaily or timeframe.isintraday)
    renderVWAPCloses(yVWAPSource, '12M', yHistorical, 'YEARLY', yVWAPColor, yOffset, isyVWAP) 

//---------------------------------------------------------------------------------------------------------------------}