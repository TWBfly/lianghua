// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Wave Consolidation [LuxAlgo]", "LuxAlgo - Wave Consolidation", overlay = true, max_lines_count = 500, max_boxes_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//Inputs
//---------------------------------------------------------------------------------------------------------------------{
sTog = input.bool(true, title = "Display Structure", group = "Structure")
len = input.int(5, minval = 1, title = "Structure Length", group = "Structure", tooltip = "Structure (Zig-Zags) uses a length to 'confirm' absolute tops and bottoms.\nFor this reason, the tops and bottom are identified at this offset length of bars.\n\nHigher values will result in larger structure with a larger gap between absolute tops and bottoms and identification point.")
vp = input.bool(false, title = "Volume Based Calculations", group = "Zones", tooltip = "Uses volume profiles to determine the areas of high activity, this will produce volume based zones.\nBy default this indicator uses market profiles to determine zones based on price action.\n\nNote: This calculation is more intensive so you may experience occasional errors requiring a reload of the indicator.")
count = input.int(3, minval = 1, title = "Display Count", group = "Zones", tooltip = "Max Number of Zones (Bullish & Bearish) possible to be displayed at one time.")
multi = input.float(0, minval = 0, maxval = 4, step = 0.25,  title = "Multiplier", group = "Zones", tooltip = "The multiplier to use for the value cut-off for determining zone boundaries.\nThese are Standard Deviations above the average, higher values will produce smaller zones, due to the higher threshold.")

bullColor = input.color(color.new(#089981,50), title = "Bull Zone Color  ", group = "Style") 
bearColor = input.color(color.new(#f23645,50), title = "Bear Zone Color", group = "Style")
midTog = input.bool(true, title = "Display Average Lines", group = "Style")

invis = color.new(chart.bg_color,100)

//---------------------------------------------------------------------------------------------------------------------}
//UDTs
//---------------------------------------------------------------------------------------------------------------------{
type bar_data
    float h
    float l
    float v
    int bi

type zones
    float top
    box bx
    line ln
    int dir
    int mod

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{
fz(_val) => _val > 0 ? _val : 1

round_to(_round,_to) =>
    math.round(_round/_to)*_to

//---------------------------------------------------------------------------------------------------------------------}
//Chart Data
//---------------------------------------------------------------------------------------------------------------------{
var chart_data = array.new<bar_data>(na)

chart_data.push(bar_data.new(math.round_to_mintick(high),math.round_to_mintick(low), volume, bar_index))

//---------------------------------------------------------------------------------------------------------------------}
//Structure
//---------------------------------------------------------------------------------------------------------------------{
var legs = array.new_line(na)

var int dir = 0

float top = na
float btm = na

var float t_val = na
var float b_val = na
var float last_t_val = na
var float last_b_val = na
var int last_t_bar = na
var int last_b_bar = na
var int t_bar = na
var int b_bar = na

upper = ta.highest(len)
lower = ta.lowest(len)

if dir == 1 and high[len] > upper
    dir := 0 
    top := high[len]

if dir == 0 and low[len] < lower
    dir := 1
    btm := low[len]

t = not na(top)
b = not na(btm)

if t
    last_t_val := t_val
    last_t_bar := t_bar
    t_bar := bar_index-len
    t_val := top
    if sTog
        legs.push(line.new(b_bar, b_val, t_bar, t_val, color = chart.fg_color))

if b
    last_b_val := b_val
    last_b_bar := b_bar
    b_bar := bar_index-len
    b_val := btm
    if sTog
        legs.push(line.new(t_bar, t_val, b_bar, b_val, color = chart.fg_color))


//---------------------------------------------------------------------------------------------------------------------}
//Managing Array Sizes Based on Swing Structure
//---------------------------------------------------------------------------------------------------------------------{

//Chart Data
for i = chart_data.size()-1 to 0
    bar = chart_data.get(i).bi
    if bar < math.min(last_b_bar,last_t_bar)
        chart_data.remove(i)

//Structure Legs
if legs.size() > 200
    legs.shift().delete()

//---------------------------------------------------------------------------------------------------------------------}
//Zone Calculations
//---------------------------------------------------------------------------------------------------------------------{
//Overview: 
//Every time 1 cycle is complete we want to calculate a profile, find the POC and search for a zone containing POC.
//Then manage the zones for overlap and mitigation.

//Zone Data
var c_zones = array.new<zones>(na)

//Profile data
data_map = map.new<float,float>()

//Triggers for Profile Calcs
bull_trigger = t and (t_val >= last_b_val) and (t_val > last_t_val)
bear_trigger = b and (b_val <= last_t_val) and (b_val < last_b_val)

//Identifying Tick Size for Profile Calcs
float max = na
float min = na
for data in chart_data
    if data.h > max or na(max)
        max := data.h
    if data.l < min or na(min)
        min := data.l
 
tick_size = math.max(syminfo.mintick,(max-min)/1000)

//Generating Profiles when Triggered
if bull_trigger
    for i = 0 to chart_data.size() - 1
        hi = round_to(chart_data.get(i).h,tick_size)
        lo = round_to(chart_data.get(i).l,tick_size)
        candle_index = ((hi-lo)/tick_size)
        tick_vol = vp?math.round((chart_data.get(i).v/(candle_index+1)),3):1
        bar = chart_data.get(i).bi
        if bar < last_b_bar or bar > t_bar
            continue
        for e = 0 to candle_index
            val = round_to(lo+(e*tick_size),tick_size)
            data_map.put(val, math.round(nz(data_map.get(val)),3)+tick_vol)

if bear_trigger
    for i = 0 to chart_data.size() - 1
        hi = round_to(chart_data.get(i).h,tick_size)
        lo = round_to(chart_data.get(i).l,tick_size)
        candle_index = ((hi-lo)/tick_size)
        tick_vol = vp?math.round((chart_data.get(i).v/(candle_index+1)),3):1
        bar = chart_data.get(i).bi
        if bar < last_t_bar or bar > b_bar
            continue
        for e = 0 to candle_index
            val = round_to(lo+(e*tick_size),tick_size)
            data_map.put(val, math.round(nz(data_map.get(val)),3)+tick_vol)
   
//Getting High Volume Zone
if bear_trigger or bull_trigger
    keys = map.keys(data_map)    
    values = map.values(data_map)
    array.sort(keys, order.ascending)

    float poc = 0
    float poc_vol = 0
    prof_avg = array.avg(keys)

    for [key, value] in data_map
        if (value > poc_vol) or (value == poc_vol and math.abs(key-prof_avg)<math.abs(poc-prof_avg))
            poc := key
            poc_vol := value

    avg_vol = values.avg() + values.stdev()*multi
    up_count = poc
    down_count = poc

    for i = 0 to array.size(keys)
        upper_vol = nz(data_map.get(round_to(up_count+tick_size,tick_size)))
        if upper_vol >= avg_vol               
            up_count := round_to(up_count+(tick_size*2),tick_size) 
        else
            break

    for i = 0 to array.size(keys)
        lower_vol = nz(data_map.get(round_to(down_count-tick_size,tick_size)))
        if lower_vol >= avg_vol               
            down_count := round_to(down_count-tick_size,tick_size) 
        else
            break
 
    zone_top = math.round_to_mintick(up_count)
    zone_bot = math.round_to_mintick(down_count)

//Pushing Zones to Zone Array for Management
    if bull_trigger
        c_zones.push(zones.new(zone_top,box.new(last_b_bar,na,t_bar,zone_bot, border_color = bullColor, bgcolor = bullColor),line.new(last_b_bar,na,t_bar,na, style = line.style_dashed, color = (midTog?color.new(bullColor,0):invis)),1,0))
    if bear_trigger
        c_zones.push(zones.new(zone_top,box.new(last_t_bar,na,b_bar,zone_bot, border_color = bearColor, bgcolor = bearColor),line.new(last_t_bar,na,b_bar,na, style = line.style_dashed, color = (midTog?color.new(bearColor,0):invis)),-1,0))

//Zone Management (Trigger Based)
    if c_zones.size() > 0 

        zn = c_zones.last()
        zn_top = zn.top
        zn_bot = zn.bx.get_bottom()
        zn_left = zn.bx.get_left()

        for i = c_zones.size()-1 to 0 
        
            if i == c_zones.size()-1
                continue

            z = c_zones.get(i)
            z_top = z.top
            z_bot = z.bx.get_bottom()
            z_left = z.bx.get_left()
            z_dir = z.dir

            if (close > z_top and z_dir == -1)
              or (close < z_bot and z_dir == 1)
              or (z.mod == -2)
                z.mod := -1

            if z.mod != -1 and (i >= c_zones.size()-3) and 
              ( ((z_top <= zn_top) and (z_bot >= zn_bot)) 
              or ((z_top >= zn_bot) and (z_bot <= zn_bot)) 
              or ((z_bot <= zn_top) and (z_top >= zn_top)) )

                zn.bx.set_top(math.max(zn_top,z_top))
                zn.bx.set_bottom(math.min(zn_bot,z_bot))
                zn.bx.set_left(math.min(zn_left,z_left))
                zn.ln.set_x1(math.min(zn_left,z_left))
                z.mod := -1

            if z.mod <= -1
                z.bx.delete()
                z.ln.delete()
                c_zones.remove(i)

//Non-Trigger Based Zone Management
for z in c_zones
    z_top = z.top
    z_bot = z.bx.get_bottom()
    z_dir = z.dir
    z_lvl = z_dir == -1 ? z_top : z_dir == 1 ? z_bot : math.avg(z_top,z_bot)
    if (close > z_top and z_dir == -1)
      or (close < z_bot and z_dir == 1)
        z.top := z_lvl
        z.bx.set_top(z_lvl)
        z.bx.set_bottom(z_lvl)
        z.bx.set_border_style(line.style_dotted)
        z.mod := -2

//---------------------------------------------------------------------------------------------------------------------}
//Display
//---------------------------------------------------------------------------------------------------------------------{
if c_zones.size() > 0
    bull_count = 0
    bear_count = 0 
    for i = c_zones.size()-1 to 0
        z = c_zones.get(i)
        z.bx.set_top(na)
        z.ln.set_y1(na)
        z.ln.set_y2(na)
        avg = math.avg(z.top,z.bx.get_bottom())
        if z.mod == -2    
            z.bx.set_top(z.top)
            z.bx.set_right(bar_index)
            z.ln.set_x2(bar_index)
        if (bull_count == count) and (bear_count == count)
            continue
        if (bull_count < count) and (z.dir == 1) and (z.mod != -2)
            z.bx.set_top(z.top)
            z.bx.set_right(bar_index)
            bull_count += 1
            z.ln.set_x2(bar_index)
            z.ln.set_y1(avg)
            z.ln.set_y2(avg)
            
        if (bear_count < count) and (z.dir == -1) and (z.mod != -2)
            z.bx.set_top(z.top)
            z.bx.set_right(bar_index)
            bear_count += 1
            z.ln.set_x2(bar_index)
            z.ln.set_y1(avg)
            z.ln.set_y2(avg)
            
//---------------------------------------------------------------------------------------------------------------------}