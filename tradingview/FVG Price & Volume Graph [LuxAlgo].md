// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("FVG Price & Volume Graph [LuxAlgo]", "LuxAlgo - FVG Price & Volume Graph", overlay = true, max_boxes_count = 500, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
length = input(100, 'Display Amount')
levelsFromFvg = input.int(3, 'Highest Volume Averages', minval = 1) 

useMitigation = input(true, 'Consider Mitigation')
filterOutside = input(true, 'Filter FVGs Outside Visible Range')

tf = input.timeframe('1', 'Intrabar Data TF')

//Style 
bullCss = input(#089981, 'Bullish FVG', inline = 'bullcss', group = 'Style')
bullBorder = input(color.new(#089981, 100), 'Border', inline = 'bullcss',  group = 'Style')

bearCss = input(#f23645, 'Bearish FVG', inline = 'bearcss',  group = 'Style')
bearBorder = input(color.new(#f23645, 100), 'Border', inline = 'bearcss',  group = 'Style')

bullVolumeLevels = input(color.new(#089981, 25), 'Bullish Highest Volume Levels', group = 'Style')
bearVolumeLevels = input(color.new(#f23645, 25), 'Bearish Highest Volume Levels', group = 'Style')

showRegression = input(true, 'Regression Line', inline = 'reg', group = 'Style')
regCss = input(color.new(color.gray, 50), '', inline = 'reg', group = 'Style')

gradient = input.string('None', 'Gradient', options = ['None', 'Volume', 'Range'], group = 'Style')
minTransp = input(80, 'Minimum Gradient Transparency', group = 'Style')

showAxes = input(true, 'Show Axes', group = 'Style')
showLabels = input(true, 'Show X Axis Labels', inline = 'x_labels', group = 'Style')
labelFrequency = input.int(10, '', minval = 2, inline = 'x_labels', group = 'Style')

res = input.int(500, 'Graph Resolution', minval = 10, maxval = 500, group = 'Style') - 3 //Correct for box + offset

//---------------------------------------------------------------------------------------------------------------------}
//UDT
//---------------------------------------------------------------------------------------------------------------------{
type fvg
    float top
    float btm
    float vol
    bool  isbullish

//---------------------------------------------------------------------------------------------------------------------}
//Populate arrays
//---------------------------------------------------------------------------------------------------------------------{
var fvg_array = array.new<fvg>(0)
var prev_prices  = array.new<float>(0)
var prev_volumes = array.new<float>(0)

[ltf_data_price, ltf_data_volume] = request.security_lower_tf(syminfo.tickerid, tf, [close, volume])

//FVG condition
bullish_fvg = low > high[2] and close[1] > high[2]
bearish_fvg = high < low[2] and close[1] < low[2]

if bullish_fvg or bearish_fvg
    //FVG extremities
    top    = bullish_fvg ? low : low[2]
    bottom = bullish_fvg ? high[2] : high

    //Calculate volume associated to FVG
    vol = 0.
    if prev_prices.size() > 0
        for [index, price] in prev_prices
            //Test if price is traded within fvg
            if price > bottom and price < top
                vol += prev_volumes.get(index)

        fvg_array.unshift(fvg.new(top, bottom, vol, bullish_fvg))

//Keep previous intrabar data
prev_prices := ltf_data_price
prev_volumes := ltf_data_volume

//Test mitigation
size = fvg_array.size()

if useMitigation and size > 0
    for i = size-1 to 0
        get_fvg = fvg_array.get(i)

        if (get_fvg.isbullish ? close < get_fvg.btm : close > get_fvg.top)
            fvg_array.remove(i)

//Get visible chart minimum price
var float max_price = na
var float min_price = na

if time == chart.left_visible_bar_time
    max_price := high
    min_price := low

else if time > chart.left_visible_bar_time and time <= chart.right_visible_bar_time
    max_price := math.max(high, max_price)
    min_price := math.min(low, min_price)

//---------------------------------------------------------------------------------------------------------------------}
//Display Graph
//---------------------------------------------------------------------------------------------------------------------{
n = bar_index + 2

var x_labels = array.new<label>(0)
var levels = array.new<line>(0)

var x_axis = line.new(na, na, na, na, color = chart.fg_color)
var y_axis = line.new(na, na, na, na, color = chart.fg_color, extend = extend.both)
var linreg = line.new(na, na, na, na, style = line.style_dashed, color = regCss)

//Push lines/labels objects
if barstate.isfirst
    for i = 0 to levelsFromFvg-1
        levels.push(line.new(na, na, na, na, extend = extend.left, style = line.style_dotted))

    if showLabels
        for i = 0 to labelFrequency
            x_labels.push(label.new(na, na, style = label.style_label_up, color = color(na), textcolor = chart.fg_color, size = size.tiny))

//Delete previous boxes
for bx in box.all
    bx.delete()

//Display graphical elements
level_idx = 0
if barstate.islast
    fvg_display = array.new<fvg>(0)
    range_slice = array.new<float>(0)
    vol_slice   = array.new<float>(0)

    //Preliminary collection of FVGs
    max_size = 0
    for i = 0 to math.min(length, size)-1
        display = true
        get_fvg = fvg_array.get(i)

        //Test if FVG is outside the chart visible range
        if filterOutside
            display := get_fvg.top < max_price and get_fvg.btm > min_price
        
        if display
            fvg_display.push(get_fvg)
            vol_slice.push(get_fvg.vol)

            if gradient == 'Range'
                range_slice.push(get_fvg.top - get_fvg.btm)
        
        max_size += 1

    //Raise error for empty array
    if max_size == 0
        runtime.error('No FVGs in the chart visible range')

    //Sort fvg volume
    vol_slice.sort(order.descending)

    max_vol = vol_slice.first()
    min_vol = vol_slice.last()
    vol_range = max_vol - min_vol

    //Get threshold for highest volume fvg's
    limit = vol_slice.get(levelsFromFvg)

    //Arrays holding input data for linreg
    y = array.new<float>(0)
    x = array.new<int>(0)

    //Get maximum and minimum fvg ranges values
    max_range = gradient == 'Range' ? range_slice.max() : na
    min_range = gradient == 'Range' ? range_slice.min() : na

    //Display FVG's
    for i = 0 to max_size-1
        display = true
        get_fvg = fvg_array.get(i)

        if filterOutside
            display := get_fvg.top < max_price and get_fvg.btm > min_price
        
        if display
            x1 = n + int((get_fvg.vol - min_vol) / vol_range * res)

            //Set colors
            css = get_fvg.isbullish ? bullCss : bearCss
            
            if gradient != 'None'
                value = gradient == 'Range' ? get_fvg.top - get_fvg.btm : get_fvg.vol
                max   = gradient == 'Range' ? max_range : max_vol 
                min   = gradient == 'Range' ? min_range : min_vol 

                css := color.from_gradient(value, min, max, color.new(css, minTransp), css)
    
            //Set FVG
            box.new(x1 - 1, get_fvg.top, x1 + 1, get_fvg.btm, get_fvg.isbullish ? bullBorder : bearBorder, bgcolor = css)

            //Display highest volume fvg's levels        
            avg = math.avg(get_fvg.top, get_fvg.btm)

            if get_fvg.vol > limit
                get_level = levels.get(level_idx)

                get_level.set_xy1(n, avg)
                get_level.set_xy2(x1, avg)
                get_level.set_color(get_fvg.isbullish ? bullVolumeLevels : bearVolumeLevels)

                level_idx += 1

            //Populate data for linear regression
            y.push(avg), x.push(x1)

    //Labels
    if showLabels
        incr = min_vol
        for lbl in x_labels
            x1 = n + int((incr - min_vol) / vol_range * res)

            lbl.set_xy(x1, min_price)
            lbl.set_text(str.tostring(incr, format.volume))

            incr += vol_range / labelFrequency
    
    //Axis
    if showAxes
        x_axis.set_xy1(n-1, min_price), x_axis.set_xy2(n+res, min_price)
        y_axis.set_xy1(n-1, min_price), y_axis.set_xy2(n-1, high)

    if showRegression
        //Regression line
        a = y.covariance(x) / x.variance()
        b = y.avg() - a * x.avg()

        linreg.set_xy1(x.min(), a * x.min() + b)
        linreg.set_xy2(x.max(), a * x.max() + b)

//---------------------------------------------------------------------------------------------------------------------}