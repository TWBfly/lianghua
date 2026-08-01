// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Historical Liquidity Proximity Heatmap [LuxAlgo]", "LuxAlgo - HLPH", overlay = true, calc_bars_count = 2000)
//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
const int MAX_P = 10 

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
int leftLen      = input.int(20, "Pivot Left Length", group = "Pivots")
int rightLen     = input.int(20, "Pivot Right Length", group = "Pivots")
int bufferSize   = input.int(200, "Historical Buffer Size", minval = 10, group = "Pivots")
int numPoints    = input.int(10, "Number of Points (P)", minval = 1, maxval = MAX_P, group = "Display")
int transInput   = input.int(30, "Dot Transparency", minval = 0, maxval = 100, group = "Display")
string themeName = input.string("Viridis", "Color Theme", options = ["Viridis", "Inferno", "Magma", "Plasma", "Cividis", "Turbo"], group = "Style")

//---------------------------------------------------------------------------------------------------------------------}
// State Variables
//---------------------------------------------------------------------------------------------------------------------{
var array<float> h_price_storage = array.new_float(0)
var array<float> h_vol_storage   = array.new_float(0)
var array<float> l_price_storage = array.new_float(0)
var array<float> l_vol_storage   = array.new_float(0)

var float max_vol_found = 0.0
var float min_vol_found = 1.0e10
var bool has_points     = false

var array<color> palette = array.from(
     #440154, #482878, #3e4989, #31688e, #26828e, #1f9e89, #35b779, #6ece58, #b5de2b, #fde725, // Viridis
     #000004, #1b0c41, #4a0c6b, #781c6d, #a52c60, #cf4446, #ed6925, #fb9b06, #f7d13d, #fcffa4, // Inferno
     #000004, #180f3d, #440f76, #721f81, #9e2f7f, #cd4071, #f1605d, #fd9668, #feca8d, #fcfdbf, // Magma
     #0d0887, #46039f, #7201a8, #9c179e, #bd3786, #d8576b, #ed7953, #fb9f3a, #fdca26, #f0f921, // Plasma
     #00224e, #123570, #3b496c, #575d6d, #707173, #8a8678, #a59c74, #c3b369, #e1cc55, #fee838, // Cividis
     #30123b, #4661d6, #37a8fa, #1ae4b6, #71fe5f, #c8ef34, #faba39, #f56918, #ca2a04, #7a0403  // Turbo
     )

int offset = themeName == "Viridis" ? 0 : themeName == "Inferno" ? 10 : themeName == "Magma" ? 20 : themeName == "Plasma" ? 30 : themeName == "Cividis" ? 40 : 50

var array<float> h_res_p = array.new_float(MAX_P, na)
var array<color> h_res_c = array.new_color(MAX_P, color.new(color.gray, 100))
var array<float> l_res_p = array.new_float(MAX_P, na)
var array<color> l_res_c = array.new_color(MAX_P, color.new(color.gray, 100))

// Sorting Buffer
var array<float> tmp_p = array.new_float(0)
var array<float> tmp_v = array.new_float(0)
var array<float> tmp_d = array.new_float(0)

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
get_color(float vol, float mn, float mx, array<color> pal, int off, int trans) =>
    float n = (mx == mn) ? 0.5 : (vol - mn) / math.max(1.0e-10, mx - mn)
    n := math.max(0.0, math.min(1.0, n))
    float pos = n * 9.0
    int i1 = off + int(math.floor(pos))
    int i2 = off + int(math.ceil(pos))
    i1 := math.max(0, math.min(59, i1))
    i2 := math.max(0, math.min(59, i2))
    color c1 = array.get(pal, i1)
    color c2 = array.get(pal, i2)
    float w = pos - math.floor(pos)
    color res = color.rgb(
         int(color.r(c1) + (color.r(c2) - color.r(c1)) * w),
         int(color.g(c1) + (color.g(c2) - color.g(c1)) * w),
         int(color.b(c1) + (color.b(c2) - color.b(c1)) * w),
         trans)
    res

//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
array.fill(h_res_p, na)
array.fill(h_res_c, color.new(color.gray, 100))
array.fill(l_res_p, na)
array.fill(l_res_c, color.new(color.gray, 100))

float vwap_h = na
float vwap_l = na

// Pivot Detection
float ph_found = ta.pivothigh(high, leftLen, rightLen)
float pl_found = ta.pivotlow(low, leftLen, rightLen)

if not na(ph_found)
    float v = volume[rightLen]
    array.push(h_price_storage, ph_found)
    array.push(h_vol_storage, v)
    if array.size(h_price_storage) > bufferSize
        array.shift(h_price_storage)
        array.shift(h_vol_storage)
    max_vol_found := has_points ? math.max(max_vol_found, v) : v
    min_vol_found := has_points ? math.min(min_vol_found, v) : v
    has_points := true

if not na(pl_found)
    float v = volume[rightLen]
    array.push(l_price_storage, pl_found)
    array.push(l_vol_storage, v)
    if array.size(l_price_storage) > bufferSize
        array.shift(l_price_storage)
        array.shift(l_vol_storage)
    max_vol_found := has_points ? math.max(max_vol_found, v) : v
    min_vol_found := has_points ? math.min(min_vol_found, v) : v
    has_points := true

// Highs Sorting
array.clear(tmp_p), array.clear(tmp_v), array.clear(tmp_d)
if array.size(h_price_storage) > 0
    for i = 0 to array.size(h_price_storage) - 1
        float p = array.get(h_price_storage, i)
        if p > high
            array.push(tmp_p, p)
            array.push(tmp_v, array.get(h_vol_storage, i))
            array.push(tmp_d, p - high)
    
    if array.size(tmp_p) > 1
        for i = 0 to array.size(tmp_p) - 2
            for j = i + 1 to array.size(tmp_p) - 1
                if array.get(tmp_d, i) > array.get(tmp_d, j)
                    float t_p = array.get(tmp_p, i), array.set(tmp_p, i, array.get(tmp_p, j)), array.set(tmp_p, j, t_p)
                    float t_v = array.get(tmp_v, i), array.set(tmp_v, i, array.get(tmp_v, j)), array.set(tmp_v, j, t_v)
                    float t_d = array.get(tmp_d, i), array.set(tmp_d, i, array.get(tmp_d, j)), array.set(tmp_d, j, t_d)
    
    int limitH = math.min(array.size(tmp_p), numPoints)
    if limitH > 0
        float sumPV = 0.0
        float sumV  = 0.0
        for i = 0 to limitH - 1
            float pVal = array.get(tmp_p, i)
            float vVal = array.get(tmp_v, i)
            array.set(h_res_p, i, pVal)
            array.set(h_res_c, i, get_color(vVal, min_vol_found, max_vol_found, palette, offset, transInput))
            sumPV += pVal * vVal
            sumV  += vVal
        vwap_h := sumV > 0 ? sumPV / sumV : na

// Lows Sorting
array.clear(tmp_p), array.clear(tmp_v), array.clear(tmp_d)
if array.size(l_price_storage) > 0
    for i = 0 to array.size(l_price_storage) - 1
        float p = array.get(l_price_storage, i)
        if p < low
            array.push(tmp_p, p)
            array.push(tmp_v, array.get(l_vol_storage, i))
            array.push(tmp_d, low - p)
    
    if array.size(tmp_p) > 1
        for i = 0 to array.size(tmp_p) - 2
            for j = i + 1 to array.size(tmp_p) - 1
                if array.get(tmp_d, i) > array.get(tmp_d, j)
                    float t_p = array.get(tmp_p, i), array.set(tmp_p, i, array.get(tmp_p, j)), array.set(tmp_p, j, t_p)
                    float t_v = array.get(tmp_v, i), array.set(tmp_v, i, array.get(tmp_v, j)), array.set(tmp_v, j, t_v)
                    float t_d = array.get(tmp_d, i), array.set(tmp_d, i, array.get(tmp_d, j)), array.set(tmp_d, j, t_d)
    
    int limitL = math.min(array.size(tmp_p), numPoints)
    if limitL > 0
        float sumPV = 0.0
        float sumV  = 0.0
        for i = 0 to limitL - 1
            float pVal = array.get(tmp_p, i)
            float vVal = array.get(tmp_v, i)
            array.set(l_res_p, i, pVal)
            array.set(l_res_c, i, get_color(vVal, min_vol_found, max_vol_found, palette, offset, transInput))
            sumPV += pVal * vVal
            sumV  += vVal
        vwap_l := sumV > 0 ? sumPV / sumV : na

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
plot(array.get(h_res_p, 0), "H1", array.get(h_res_c, 0), 1, plot.style_circles)
plot(array.get(h_res_p, 1), "H2", array.get(h_res_c, 1), 1, plot.style_circles)
plot(array.get(h_res_p, 2), "H3", array.get(h_res_c, 2), 1, plot.style_circles)
plot(array.get(h_res_p, 3), "H4", array.get(h_res_c, 3), 1, plot.style_circles)
plot(array.get(h_res_p, 4), "H5", array.get(h_res_c, 4), 1, plot.style_circles)
plot(array.get(h_res_p, 5), "H6", array.get(h_res_c, 5), 1, plot.style_circles)
plot(array.get(h_res_p, 6), "H7", array.get(h_res_c, 6), 1, plot.style_circles)
plot(array.get(h_res_p, 7), "H8", array.get(h_res_c, 7), 1, plot.style_circles)
plot(array.get(h_res_p, 8), "H9", array.get(h_res_c, 8), 1, plot.style_circles)
plot(array.get(h_res_p, 9), "H10", array.get(h_res_c, 9), 1, plot.style_circles)

plot(array.get(l_res_p, 0), "L1", array.get(l_res_c, 0), 1, plot.style_circles)
plot(array.get(l_res_p, 1), "L2", array.get(l_res_c, 1), 1, plot.style_circles)
plot(array.get(l_res_p, 2), "L3", array.get(l_res_c, 2), 1, plot.style_circles)
plot(array.get(l_res_p, 3), "L4", array.get(l_res_c, 3), 1, plot.style_circles)
plot(array.get(l_res_p, 4), "L5", array.get(l_res_c, 4), 1, plot.style_circles)
plot(array.get(l_res_p, 5), "L6", array.get(l_res_c, 5), 1, plot.style_circles)
plot(array.get(l_res_p, 6), "L7", array.get(l_res_c, 6), 1, plot.style_circles)
plot(array.get(l_res_p, 7), "L8", array.get(l_res_c, 7), 1, plot.style_circles)
plot(array.get(l_res_p, 8), "L9", array.get(l_res_c, 8), 1, plot.style_circles)
plot(array.get(l_res_p, 9), "L10", array.get(l_res_c, 9), 1, plot.style_circles)

plot(vwap_h, "VWAP Highs", #f23645, 1, plot.style_linebr, linestyle = plot.linestyle_dotted)
plot(vwap_l, "VWAP Lows", #089981, 1, plot.style_linebr, linestyle = plot.linestyle_dotted)

//---------------------------------------------------------------------------------------------------------------------}
