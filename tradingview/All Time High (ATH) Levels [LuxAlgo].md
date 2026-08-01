// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/ MPL-2.0
// © LuxAlgo

//@version=6
indicator("All Time High (ATH) Levels [LuxAlgo]", "LuxAlgo - All Time High (ATH) Levels", overlay = true, max_lines_count = 500, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
showLast = input.int(50, 'Show Last ATH', minval = 1)
duration = input(3, 'ATH Minimum Duration')
distMult = input.float(3., 'Minimum Distance Between ATH', step = .25)

//Interval Filter
showClassification = input(true, 'Show SR%', group = 'SR% Classification')
minSr = input.float(0, 'Minimum %', minval = 0, maxval = 100, group = 'SR% Classification')

//Style
bullCss = input(#089981, 'Support Color', group = 'Style')
bearCss = input(#f23645, 'Resistance Color', group = 'Style')

trailCss1 = input(#0a0032, 'Trailing Gradient', inline = 'trail', group = 'Style')
trailCss2 = input(#ff5d00, '', inline = 'trail', group = 'Style')
trailCss3 = input(#2962ff, '', inline = 'trail', group = 'Style')

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{
n = bar_index

set_elements(x1, lvl, txt, css)=>
    line.new(x1, lvl, time, lvl, xloc.bar_time, color = css)
    line.new(n, lvl, n+100, lvl, color = css)

    if showClassification
        label.new(n+100, lvl, txt, color = color(na), style = label.style_label_left, textcolor = css, size = size.tiny)

//---------------------------------------------------------------------------------------------------------------------}
//Variables
//---------------------------------------------------------------------------------------------------------------------{
var aths = array.new<float>(0)
var aths_x1 = array.new<int>(0)
var price_dist = array.new<float>(0)
var total_price_dist = array.new<float>(0)

var x1 = 0
var time_x1 = 0
var max = high

max := math.max(high, max)
atr = nz(ta.atr(200), ta.cum(high - low) / (n+1)) * distMult

if max > max[1]
    x1 := n
    time_x1 := time

//Test for ATH recency
if n - x1 == duration
    aths.unshift(max)
    aths_x1.unshift(time_x1)

    //Relative Dist Calculation
    price_dist.unshift(0)
    total_price_dist.unshift(0)

//Set ATH's
for [index, element] in aths
    price_dist.set(index, price_dist.get(index) + math.max(close - element, 0))
    total_price_dist.set(index, total_price_dist.get(index) + math.abs(close - element))

//---------------------------------------------------------------------------------------------------------------------}
//Display ATH's
//---------------------------------------------------------------------------------------------------------------------{
//Delete existing graphical elements
for element in line.all
    element.delete()
for element in label.all
    element.delete()

if barstate.islast and aths.size() > 0
    //Recent ATH
    lvl = aths.get(0)

    //Set display elements
    set_elements(aths_x1.get(0), lvl, '[R] 100%', bearCss)
    
    //Display Historical ATH's
    if aths.size() > 1
        for i = 1 to math.min(showLast-1, aths.size()-1)
            dist = lvl - aths.get(i)

            //Display level if distance between currently evaluated level and previous level is greater than threshold
            if dist >= atr
                norm_dist = (1 - price_dist.get(i) / total_price_dist.get(i)) * 100
                sr = norm_dist < 50 ? '[S] ' : '[R] '
                css = color.from_gradient(norm_dist, 0, 100, bullCss, bearCss)
                
                norm_dist := math.abs(norm_dist - 50) * 2

                //Display level if percentage is higher than user set threshold
                if norm_dist >= minSr

                    //Set display elements
                    set_elements(aths_x1.get(i), aths.get(i), sr + str.tostring(norm_dist, format.percent), css)

                    lvl := aths.get(i)

//---------------------------------------------------------------------------------------------------------------------}
//Plots
//---------------------------------------------------------------------------------------------------------------------{
bg_css1 = color.from_gradient(n, 0, last_bar_index/2, trailCss1, trailCss2)
bg_css2 = color.from_gradient(n, last_bar_index/2, last_bar_index, bg_css1, trailCss3)

plot_price = plot(close, display = display.none, editable = false)
plot_max = plot(max, color = bg_css2)

fill(plot_price, plot_max, color = color.new(bg_css2, 90))

//---------------------------------------------------------------------------------------------------------------------}