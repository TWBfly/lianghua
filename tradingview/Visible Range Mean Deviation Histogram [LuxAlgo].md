// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Visible Range Mean Deviation Histogram [LuxAlgo]", "VRMDH [LuxAlgo]"
  , overlay = true
  , max_boxes_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
rows = input.int(10, "Bins Per Side"
  , minval = 1)

mult = input.float(2, "Deviation Multiplier"
  , minval = 0)

//Style
rel   = input(true, "Relative"
  , inline = 'inline0'
  , group  = 'Style')

width = input.float(30
  , minval = 0
  , maxval = 100
  , inline = 'inline0'
  , group  = 'Style')
  
up_css = input.color(#0cb51a, "Bin Colors"
  , inline = 'inline1'
  , group  = 'Style')

dn_css = input.color(#ff1100, ""
  , inline = 'inline1'
  , group  = 'Style')

poc = input(true, "Show POCs"
  , group  = 'Style')

//-----------------------------------------------------------------------------}
//Calculations
//-----------------------------------------------------------------------------{
var csum1 = 0.
var csum2 = 0.
var idx   = 0

n = bar_index

left = chart.left_visible_bar_time
right = chart.right_visible_bar_time

if time >= left and time <= right
    csum1 += close
    csum2 += close * close

    idx += 1

//Display Histogram
if time == right
    //Calculate mean/standard deviation
    mean1 = csum1 / idx
    mean2 = csum2 / idx
    
    dev = math.sqrt(mean2 - mean1 * mean1) * mult / rows
    
    //Highlight upper/lower extremities
    line.new(left, mean1 + dev*rows, right, mean1 + dev*rows
      , color = up_css
      , style = line.style_dashed
      , xloc  = xloc.bar_time)
      
    line.new(left, mean1 - dev*rows, right, mean1 - dev*rows
      , color = dn_css
      , style = line.style_dashed
      , xloc  = xloc.bar_time)
    
    //Count prices values within bins
    upper_bins_count = array.new_int(0)
    lower_bins_count = array.new_int(0)
    
    upper_levels = array.new_float(0)
    lower_levels = array.new_float(0)
    
    sum_dev    = dev
    upper_prev = mean1
    lower_prev = mean1
    
    for i = 0 to rows-1
        sum_up = 0
        sum_dn = 0
        
        upper = mean1 + sum_dev
        lower = mean1 - sum_dev
        
        array.push(upper_levels, upper)
        array.push(lower_levels, lower)
        
        for j = 0 to idx-1
            sum_up := high[j] >= upper_prev and low[j] < upper ? sum_up + 1 
              : sum_up
            
            sum_dn := low[j] <= lower_prev and high[j] > lower ? sum_dn + 1 
              : sum_dn
        
        array.push(upper_bins_count, sum_up)
        array.push(lower_bins_count, sum_dn)
        
        sum_dev    += dev
        upper_prev += dev
        lower_prev -= dev
    
    //Display bins
    incr_mult  = 0.
    upper_prev := mean1
    lower_prev := mean1
    
    max_up = array.max(upper_bins_count)
    max_dn = array.max(lower_bins_count)
    max = math.max(max_up, max_dn)
    
    for i = 0 to rows-1
        upper_right = 0
        lower_right = 0
        
        get_up_bin = array.get(upper_bins_count, i)
        get_dn_bin = array.get(lower_bins_count, i)
        
        upper = array.get(upper_levels, i)
        lower = array.get(lower_levels, i)
        
        incr_mult += mult / rows
        
        if rel
            upper_right := math.round(get_up_bin / max * width / 100 * (idx - 1))
            lower_right := math.round(get_dn_bin / max * width / 100 * (idx - 1))
        else
            upper_right := get_up_bin
            lower_right := get_dn_bin
        
        //Upper side bins
        box.new(n - idx + 1, upper, n - idx + 1 + upper_right, upper_prev
          , border_color = up_css
          , bgcolor      = color.new(up_css, 90)
          , text         = '+' + str.tostring(incr_mult, '#.##')
          , text_color   = up_css
          , text_halign  = text.align_left)
          
        if get_up_bin == max_up and poc
            avg = math.avg(upper, upper_prev)
            
            line.new(n - idx + 1 + upper_right, avg, n, avg
              , color = up_css
              , style = line.style_dotted)
        
        //Lower side bins
        box.new(n - idx + 1, lower_prev, n - idx + 1 + lower_right, lower
          , border_color = dn_css
          , bgcolor      = color.new(dn_css, 90)
          , text         = '-' + str.tostring(incr_mult, '#.##')
          , text_color   = dn_css
          , text_halign  = text.align_left)
          
        if get_dn_bin == max_dn and poc
            avg = math.avg(lower, lower_prev)
            
            line.new(n - idx + 1 + lower_right, avg, n, avg
              , color = dn_css
              , style = line.style_dotted)
        
        upper_prev := upper
        lower_prev := lower

//-----------------------------------------------------------------------------}