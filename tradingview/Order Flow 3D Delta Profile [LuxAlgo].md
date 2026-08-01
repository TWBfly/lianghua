// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=6
indicator("Order Flow 3D Delta Profile [LuxAlgo]", "LuxAlgo - 3D Delta Profile", overlay = true, max_polylines_count = 100, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{

t1 = "Number of bars to include in the profile."
t2 = "Percentage of total volume considered as the Value Area (default 70%)."
t3 = "Controls the 3D depth perspective. Positive Y tilts UP, Negative Y tilts DOWN. Positive X tilts RIGHT, Negative X tilts LEFT."

prd         = input.int(200, "Length", minval = 1, maxval = 2500, tooltip = t1, group = "General")
buckets     = input.int(35, "Buckets", minval = 5, maxval = 100, group = "General")
vaPercent   = input.float(70.0, "Value Area %", minval = 1, maxval = 100, tooltip = t2, group = "General")

align       = input.string("Center", "Profile Alignment", options=["Left", "Center", "Right"], group = "Profile Setup")
placement   = input.string("Right of Price", "Profile Placement", options=["On Candles", "Right of Price"], group = "Profile Setup")
mult        = input.float(0.5, "Profile Width Scale", step = 0.1, minval = 0.1, maxval = 1.0, group = "Profile Setup")

depthX      = input.float(0.08, "Extrusion Depth X", step = 0.02, minval = -1.0, maxval = 1.0, tooltip = t3, group = "3D Options")
depthY      = input.float(0.5, "Extrusion Depth Y", step = 0.1, minval = -2.0, maxval = 2.0, group = "3D Options")
showBox     = input.bool(true, "Show Bounding Box", tooltip="Draws a 3D dashed wireframe around the candle range", group = "3D Options")

showHighVol = input.bool(true, "Highlight High Volume Candles", tooltip="Draws glowing connections to individual candles with abnormally high volume.", group = "Visuals")
volMult     = input.float(2.5, "Anomaly Threshold (x Avg)", step = 0.5, minval = 1.0, group = "Visuals")

pocCol      = input.color(#FFD700, "POC Color", group = "Style")
bullCol     = input.color(#089981, "Bull (Positive Delta)", group = "Style")
bearCol     = input.color(#f23645, "Bear (Negative Delta)", group = "Style")
lineCol     = input.color(color.new(color.black, 40), "Border Color", group = "Style")

//---------------------------------------------------------------------------------------------------------------------}
// User-Defined Types
//---------------------------------------------------------------------------------------------------------------------{

type Vals
    int start  = na
    float top = na
    float bot = na

type Arrays
    array<float> v
    array<float> c
    array<float> o
    array<float> m
    array<int>   i
    array<float> h
    array<float> l

type Block3D
    array<chart.point> front
    array<chart.point> side
    array<chart.point> top
    color f_col
    color s_col
    color t_col
    color l_col

//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{

hi = ta.highest(high, prd)
lo = ta.lowest(low, prd)

var v = Vals.new(bar_index)
var a = Arrays.new(array.new<float>(), array.new<float>(), array.new<float>(), array.new<float>(), array.new<int>(), array.new<float>(), array.new<float>())

//---------------------------------------------------------------------------------------------------------------------}
// Functions & Methods
//---------------------------------------------------------------------------------------------------------------------{

method CandlestickData(Arrays arr) =>
    arr.v.push(volume)
    arr.c.push(close)
    arr.o.push(open)
    arr.m.push(hl2)
    arr.i.push(bar_index)
    arr.h.push(high)
    arr.l.push(low)

method CandlestickDataClean(Arrays arr) =>
    arr.v.shift()
    arr.c.shift()
    arr.o.shift()
    arr.m.shift()
    arr.i.shift()
    arr.h.shift()
    arr.l.shift()

method Darken(color c, float amount) =>
    r = color.r(c)
    g = color.g(c)
    b = color.b(c)
    t = color.t(c)
    color.rgb(r * (1 - amount), g * (1 - amount), b * (1 - amount), t)

method Lighten(color c, float amount) =>
    r = color.r(c)
    g = color.g(c)
    b = color.b(c)
    t = color.t(c)
    color.rgb(r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount, t)

GenerateBlock3D(int x1, int x2, float y1, float y2, int dx, float dy) =>
    front = array.new<chart.point>()
    side = array.new<chart.point>()
    top = array.new<chart.point>()
    
    // Front face
    front.push(chart.point.from_index(x1, y1))
    front.push(chart.point.from_index(x1, y2))
    front.push(chart.point.from_index(x2, y2))
    front.push(chart.point.from_index(x2, y1))
    
    // Side face
    if dx > 0
        // Right side
        side.push(chart.point.from_index(x2, y1))
        side.push(chart.point.from_index(x2, y2))
        side.push(chart.point.from_index(x2+dx, y2+dy))
        side.push(chart.point.from_index(x2+dx, y1+dy))
    else if dx < 0
        // Left side
        side.push(chart.point.from_index(x1, y1))
        side.push(chart.point.from_index(x1, y2))
        side.push(chart.point.from_index(x1+dx, y2+dy))
        side.push(chart.point.from_index(x1+dx, y1+dy))
        
    // Top/Bottom face
    if dy > 0
        // Top face
        top.push(chart.point.from_index(x1, y2))
        top.push(chart.point.from_index(x2, y2))
        top.push(chart.point.from_index(x2+dx, y2+dy))
        top.push(chart.point.from_index(x1+dx, y2+dy))
    else if dy < 0
        // Bottom face
        top.push(chart.point.from_index(x1, y1))
        top.push(chart.point.from_index(x2, y1))
        top.push(chart.point.from_index(x2+dx, y1+dy))
        top.push(chart.point.from_index(x1+dx, y1+dy))
        
    Block3D.new(front, side, top)

//---------------------------------------------------------------------------------------------------------------------}
// Main Logic
//---------------------------------------------------------------------------------------------------------------------{

if barstate.isfirst
    v.start := bar_index

v.top := hi
v.bot := lo
if bar_index > prd
    v.start += 1
a.CandlestickData()
if a.v.size() > prd
    a.CandlestickDataClean()

if barstate.islast
    for e in polyline.all
        e.delete()
    for e in line.all
        e.delete()
        
    step = (v.top - v.bot) / buckets
    priceLevels = array.new<float>()
    for i = 0 to buckets
        priceLevels.push(v.bot + i * step)
        
    array<float> bu_bins = array.new<float>(buckets, 0.0)
    array<float> be_bins = array.new<float>(buckets, 0.0)
    
    for [idx, vo] in a.v
        float m_val = a.m.get(idx)
        for j = 0 to buckets - 1
            if m_val >= priceLevels.get(j) and m_val < priceLevels.get(j+1)
                if a.c.get(idx) > a.o.get(idx)
                    bu_bins.set(j, bu_bins.get(j) + vo)
                else if a.c.get(idx) < a.o.get(idx)
                    be_bins.set(j, be_bins.get(j) + vo)
                break
                
    float max_total_vol = 0
    float total_vol_sum = 0
    int poc_idx = 0
    
    for i = 0 to buckets - 1
        float vol = bu_bins.get(i) + be_bins.get(i)
        total_vol_sum += vol
        if vol > max_total_vol
            max_total_vol := vol
            poc_idx := i
            
    array<bool> in_va = array.new<bool>(buckets, false)
    if total_vol_sum > 0
        in_va.set(poc_idx, true)
        float va_vol = max_total_vol
        float target_va_vol = total_vol_sum * (vaPercent / 100)
        
        int upper_idx = poc_idx
        int lower_idx = poc_idx
        
        while va_vol < target_va_vol
            float upper_vol = (upper_idx + 1 < buckets) ? (bu_bins.get(upper_idx + 1) + be_bins.get(upper_idx + 1)) : -1.0
            float lower_vol = (lower_idx - 1 >= 0) ? (bu_bins.get(lower_idx - 1) + be_bins.get(lower_idx - 1)) : -1.0
            
            if upper_vol == -1 and lower_vol == -1
                break
                
            if upper_vol >= lower_vol
                upper_idx += 1
                va_vol += upper_vol
                in_va.set(upper_idx, true)
            else
                lower_idx -= 1
                va_vol += lower_vol
                in_va.set(lower_idx, true)

    int length = bar_index - v.start
    int s_idx = placement == "Right of Price" ? bar_index + 5 : v.start
    int b_idx = s_idx + length
    int anchor_x = s_idx + math.floor((b_idx - s_idx) / 2)
    float profile_width_bars = length * mult
    
    float max_extrusion_y = step * depthY
    int max_extrusion_x = math.floor(profile_width_bars * depthX)
    
    array<Block3D> blocks = array.new<Block3D>()
    
    for i = 0 to buckets - 1
        float bu_vol = bu_bins.get(i)
        float be_vol = be_bins.get(i)
        float total_v = bu_vol + be_vol
        float delta_v = bu_vol - be_vol
        
        if total_v == 0
            continue
            
        int w = na
        if align == "Center"
            w := math.max(1, math.floor((total_v / max_total_vol) * (profile_width_bars / 2)))
        else
            w := math.max(1, math.floor((total_v / max_total_vol) * profile_width_bars))
            
        int x1 = na
        int x2 = na
        if align == "Center"
            if delta_v >= 0
                x1 := anchor_x
                x2 := anchor_x + w
            else
                x1 := anchor_x - w
                x2 := anchor_x
        else if align == "Left"
            x1 := s_idx
            x2 := s_idx + w
        else // Right
            x1 := b_idx - w
            x2 := b_idx
        
        bool is_poc = (i == poc_idx)
        bool is_va = in_va.get(i)
        
        color base_col_raw = delta_v >= 0 ? bullCol : bearCol
        color base_col = color.new(base_col_raw, 0)
        color poc_opaque = color.new(pocCol, 0)
        
        color f_col = is_poc ? poc_opaque : is_va ? base_col : Darken(base_col, 0.6)
        
        color s_col = Darken(f_col, 0.3)
        color t_col = Lighten(f_col, 0.2)
        color l_col = is_poc ? poc_opaque : is_va ? color.new(lineCol, 0) : color.new(lineCol, 80)
        
        float y1 = priceLevels.get(i)
        float y2 = priceLevels.get(i+1)
        
        Block3D blk = GenerateBlock3D(x1, x2, y1, y2, max_extrusion_x, max_extrusion_y)
        blk.f_col := f_col
        blk.s_col := s_col
        blk.t_col := t_col
        blk.l_col := l_col
        
        blocks.push(blk)
        
    // Rendering Pass
    if blocks.size() > 0
        if max_extrusion_y >= 0
            // Bottom to Top drawing order
            // 1. Draw ALL Tops
            for i = 0 to blocks.size() - 1
                Block3D blk = blocks.get(i)
                if blk.top.size() > 0
                    polyline.new(blk.top, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.t_col)
            // 2. Draw ALL Sides
            for i = 0 to blocks.size() - 1
                Block3D blk = blocks.get(i)
                if blk.side.size() > 0
                    polyline.new(blk.side, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.s_col)
            // 3. Draw ALL Fronts
            for i = 0 to blocks.size() - 1
                Block3D blk = blocks.get(i)
                if blk.front.size() > 0
                    polyline.new(blk.front, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.f_col)
        else
            // Top to Bottom drawing order
            // 1. Draw ALL Tops
            for i = blocks.size() - 1 to 0
                Block3D blk = blocks.get(i)
                if blk.top.size() > 0
                    polyline.new(blk.top, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.t_col)
            // 2. Draw ALL Sides
            for i = blocks.size() - 1 to 0
                Block3D blk = blocks.get(i)
                if blk.side.size() > 0
                    polyline.new(blk.side, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.s_col)
            // 3. Draw ALL Fronts
            for i = blocks.size() - 1 to 0
                Block3D blk = blocks.get(i)
                if blk.front.size() > 0
                    polyline.new(blk.front, closed=true, curved=false, line_color=blk.l_col, fill_color=blk.f_col)

    // High Volume Candlestick Highlights
    if showHighVol
        float sum_vol = 0
        for v_amt in a.v
            sum_vol += v_amt
        float avg_vol = sum_vol / math.max(1, a.v.size())
        float thresh = avg_vol * volMult
        
        for [idx, v_amt] in a.v
            if v_amt > thresh
                int b_idx_c = a.i.get(idx)
                float h_val = a.h.get(idx)
                float l_val = a.l.get(idx)
                float c_val = a.c.get(idx)
                float o_val = a.o.get(idx)
                float m_val = a.m.get(idx)
                
                int end_idx = s_idx
                if idx + 1 < a.v.size()
                    for k = idx + 1 to a.v.size() - 1
                        if a.h.get(k) >= m_val and a.l.get(k) <= m_val
                            end_idx := a.i.get(k)
                            break
                
                color c_col = c_val > o_val ? bullCol : bearCol
                color c_solid = color.new(c_col, 0)
                
                // Glow around the candle
                line.new(b_idx_c, h_val, b_idx_c, l_val, color=color.new(c_col, 90), width=20)
                line.new(b_idx_c, h_val, b_idx_c, l_val, color=color.new(c_col, 80), width=12)
                line.new(b_idx_c, h_val, b_idx_c, l_val, color=color.new(c_col, 60), width=6)
                line.new(b_idx_c, h_val, b_idx_c, l_val, color=color.new(c_col, 30), width=3)
                line.new(b_idx_c, h_val, b_idx_c, l_val, color=c_solid, width=1)
                
                // 3D Laser Beam connecting to profile
                float r_y1 = m_val - step * 0.05
                float r_y2 = m_val + step * 0.05
                
                color r_f = color.new(c_col, 40)
                color r_t = Lighten(r_f, 0.4)
                
                if max_extrusion_y >= 0
                    array<chart.point> t_ribbon = array.new<chart.point>()
                    t_ribbon.push(chart.point.from_index(b_idx_c, r_y2))
                    t_ribbon.push(chart.point.from_index(end_idx, r_y2))
                    t_ribbon.push(chart.point.from_index(end_idx + max_extrusion_x, r_y2 + max_extrusion_y))
                    t_ribbon.push(chart.point.from_index(b_idx_c + max_extrusion_x, r_y2 + max_extrusion_y))
                    polyline.new(t_ribbon, closed=true, curved=false, line_color=c_solid, fill_color=r_t)
                else
                    array<chart.point> b_ribbon = array.new<chart.point>()
                    b_ribbon.push(chart.point.from_index(b_idx_c, r_y1))
                    b_ribbon.push(chart.point.from_index(end_idx, r_y1))
                    b_ribbon.push(chart.point.from_index(end_idx + max_extrusion_x, r_y1 + max_extrusion_y))
                    b_ribbon.push(chart.point.from_index(b_idx_c + max_extrusion_x, r_y1 + max_extrusion_y))
                    polyline.new(b_ribbon, closed=true, curved=false, line_color=c_solid, fill_color=r_t)
                    
                array<chart.point> f_ribbon = array.new<chart.point>()
                f_ribbon.push(chart.point.from_index(b_idx_c, r_y1))
                f_ribbon.push(chart.point.from_index(b_idx_c, r_y2))
                f_ribbon.push(chart.point.from_index(end_idx, r_y2))
                f_ribbon.push(chart.point.from_index(end_idx, r_y1))
                polyline.new(f_ribbon, closed=true, curved=false, line_color=c_solid, fill_color=r_f)

    if showBox
        color box_line_col = color.new(lineCol, 50)
        color glass_fill   = color.new(lineCol, 95)
        
        // Back Wall Glass Effect
        array<chart.point> back_face = array.new<chart.point>()
        back_face.push(chart.point.from_index(v.start + max_extrusion_x, v.bot + max_extrusion_y))
        back_face.push(chart.point.from_index(v.start + max_extrusion_x, v.top + max_extrusion_y))
        back_face.push(chart.point.from_index(bar_index + max_extrusion_x, v.top + max_extrusion_y))
        back_face.push(chart.point.from_index(bar_index + max_extrusion_x, v.bot + max_extrusion_y))
        polyline.new(back_face, closed=true, curved=false, line_color=na, fill_color=glass_fill)
        
        // Floor Glass Effect
        array<chart.point> bot_face = array.new<chart.point>()
        bot_face.push(chart.point.from_index(v.start, v.bot))
        bot_face.push(chart.point.from_index(bar_index, v.bot))
        bot_face.push(chart.point.from_index(bar_index + max_extrusion_x, v.bot + max_extrusion_y))
        bot_face.push(chart.point.from_index(v.start + max_extrusion_x, v.bot + max_extrusion_y))
        polyline.new(bot_face, closed=true, curved=false, line_color=na, fill_color=glass_fill)

        array<chart.point> box_pts = array.new<chart.point>()
        box_pts.push(chart.point.from_index(v.start, v.bot))
        box_pts.push(chart.point.from_index(v.start, v.top))
        box_pts.push(chart.point.from_index(bar_index, v.top))
        box_pts.push(chart.point.from_index(bar_index, v.bot))
        box_pts.push(chart.point.from_index(v.start, v.bot))
        
        box_pts.push(chart.point.from_index(v.start + max_extrusion_x, v.bot + max_extrusion_y))
        box_pts.push(chart.point.from_index(v.start + max_extrusion_x, v.top + max_extrusion_y))
        box_pts.push(chart.point.from_index(v.start, v.top))
        box_pts.push(chart.point.from_index(v.start + max_extrusion_x, v.top + max_extrusion_y))
        
        box_pts.push(chart.point.from_index(bar_index + max_extrusion_x, v.top + max_extrusion_y))
        box_pts.push(chart.point.from_index(bar_index, v.top))
        box_pts.push(chart.point.from_index(bar_index + max_extrusion_x, v.top + max_extrusion_y))
        
        box_pts.push(chart.point.from_index(bar_index + max_extrusion_x, v.bot + max_extrusion_y))
        box_pts.push(chart.point.from_index(bar_index, v.bot))
        box_pts.push(chart.point.from_index(bar_index + max_extrusion_x, v.bot + max_extrusion_y))
        
        box_pts.push(chart.point.from_index(v.start + max_extrusion_x, v.bot + max_extrusion_y))
        
        polyline.new(box_pts, closed=false, curved=false, line_color=box_line_col, line_style=line.style_solid, line_width=2)

//---------------------------------------------------------------------------------------------------------------------}
