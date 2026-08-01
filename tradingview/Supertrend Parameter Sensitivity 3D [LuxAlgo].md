// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Supertrend Parameter Sensitivity 3D [LuxAlgo]", "LuxAlgo - ST 3D Surface", overlay=false, max_lines_count=500)
//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
grp_main = "Main Indicator"
auto_apply = input.bool(false, "Auto Apply Stable Parameters", group=grp_main, tooltip="When enabled, dynamically updates parameters bar-by-bar to use the most stable matrix combination.")
main_len = input.int(10, "ATR Length", group=grp_main)
main_mult = input.float(3.0, "Multiplier", group=grp_main)

grp_st = "Sensitivity Ranges"
len_start = input.int(5, "Length Start", group=grp_st, tooltip="Starting ATR Length for optimization matrix")
len_step  = input.int(1, "Length Step", group=grp_st, tooltip="Increment of ATR Length per step (10 steps total)")
mult_start= input.float(1.0, "Multiplier Start", group=grp_st, tooltip="Starting Multiplier for optimization matrix")
mult_step = input.float(0.1, "Multiplier Step", group=grp_st, tooltip="Increment of Multiplier per step (10 steps total)")

grp_opt = "Optimization"
metric_input = input.string("Win Rate", "Metric", options=["Win Rate", "Net Profit", "Profit Factor", "Total Trades", "Average Trade", "Reward/Risk Ratio", "Gross Profit", "Total Wins", "Win/Loss Ratio"], group=grp_opt)

grp_vis = "3D Surface Style"
color_high = input.color(#089981, "High Value Color", group=grp_vis)
color_low  = input.color(#f23645, "Low Value Color", group=grp_vis)
color_wire = input.color(color.new(color.gray, 50), "Wireframe Color", group=grp_vis)
color_stable = input.color(#2196F3, "Stable Area Color", group=grp_vis)
x_step_in  = input.int(2, "X Spacing (Bars)", group=grp_vis, tooltip="Width of the surface grid cells")
y_step_in  = input.float(2.0, "Y Spacing %", group=grp_vis, tooltip="Depth of the surface grid cells") / 100
z_scale_in = input.float(20.0, "Z Height %", group=grp_vis, tooltip="Max height of the surface peaks") / 100

DASHBOARD_GROUP         = 'Dashboard'
dashboardInput          = input.bool(true, 'Enable Dashboard', group = DASHBOARD_GROUP)
dashboardPositionInput  = input.string('Top Right', 'Position', group = DASHBOARD_GROUP, options = ['Top Right', 'Top Center', 'Top Left', 'Middle Right', 'Middle Center', 'Middle Left', 'Bottom Right', 'Bottom Center', 'Bottom Left'])
dashboardSizeInput      = input.string('Small', 'Size', group = DASHBOARD_GROUP, options = ['Auto', 'Nano', 'Micro', 'Tiny', 'Small', 'Normal', 'Large', 'Huge'])

var parsedDashboardPosition = switch dashboardPositionInput
    'Top Right'       => position.top_right
    'Top Center'      => position.top_center
    'Top Left'        => position.top_left
    'Middle Right'    => position.middle_right
    'Middle Center'   => position.middle_center
    'Middle Left'     => position.middle_left
    'Bottom Right'    => position.bottom_right
    'Bottom Center'   => position.bottom_center
    'Bottom Left'     => position.bottom_left

var int parsedDashboardSize = switch dashboardSizeInput
    'Auto'            => 0
    'Nano'            => 5
    'Micro'           => 6
    'Tiny'            => 8
    'Small'           => 10
    'Normal'          => 14
    'Large'           => 20
    'Huge'            => 36

DATA                    = #DBDBDB
HEADERS                 = #808080
BACKGROUND              = #161616
BORDERS                 = #2E2E2E

//---------------------------------------------------------------------------------------------------------------------}
// Sensitivity Matrix Types & State
//---------------------------------------------------------------------------------------------------------------------{
type ST_State
    float prev_up = na
    float prev_dn = na
    int   trend   = 1
    int   trades  = 0
    int   wins    = 0
    float gross_profit = 0.0
    float gross_loss   = 0.0
    float entry_price  = na
    int   position     = 0

method get_metric(ST_State state, string metric) =>
    float val = 0.0
    if metric == "Net Profit"
        val := state.gross_profit - state.gross_loss
    else if metric == "Win Rate"
        val := state.trades > 0 ? (state.wins / state.trades * 100) : 0.0
    else if metric == "Profit Factor"
        val := state.gross_loss > 0 ? (state.gross_profit / state.gross_loss) : (state.gross_profit > 0 ? 10.0 : 0.0)
    else if metric == "Total Trades"
        val := state.trades
    else if metric == "Average Trade"
        val := state.trades > 0 ? (state.gross_profit - state.gross_loss) / state.trades : 0.0
    else if metric == "Reward/Risk Ratio"
        float avg_win = state.wins > 0 ? state.gross_profit / state.wins : 0.0
        float losses = state.trades - state.wins
        float avg_loss = losses > 0 ? state.gross_loss / losses : 0.0
        val := avg_loss > 0 ? avg_win / avg_loss : (avg_win > 0 ? 10.0 : 0.0)
    else if metric == "Gross Profit"
        val := state.gross_profit
    else if metric == "Total Wins"
        val := state.wins
    else if metric == "Win/Loss Ratio"
        float losses = state.trades - state.wins
        val := losses > 0 ? state.wins / losses : (state.wins > 0 ? 10.0 : 0.0)
    val

var st_states = array.new<ST_State>(100)
if bar_index == 0
    for i = 0 to 99
        st_states.set(i, ST_State.new())

//---------------------------------------------------------------------------------------------------------------------}
// Precomputing Native ATRs for Exact Calculation
//---------------------------------------------------------------------------------------------------------------------{
float true_range = ta.tr(true)
float atr0 = ta.rma(true_range, len_start + 0 * len_step)
float atr1 = ta.rma(true_range, len_start + 1 * len_step)
float atr2 = ta.rma(true_range, len_start + 2 * len_step)
float atr3 = ta.rma(true_range, len_start + 3 * len_step)
float atr4 = ta.rma(true_range, len_start + 4 * len_step)
float atr5 = ta.rma(true_range, len_start + 5 * len_step)
float atr6 = ta.rma(true_range, len_start + 6 * len_step)
float atr7 = ta.rma(true_range, len_start + 7 * len_step)
float atr8 = ta.rma(true_range, len_start + 8 * len_step)
float atr9 = ta.rma(true_range, len_start + 9 * len_step)

float[] atrs = array.from(atr0, atr1, atr2, atr3, atr4, atr5, atr6, atr7, atr8, atr9)

//---------------------------------------------------------------------------------------------------------------------}
// Evaluating 100 Combinations Bar-By-Bar
//---------------------------------------------------------------------------------------------------------------------{
float avg_hl = math.avg(high, low)

for i = 0 to 9
    float atr = atrs.get(i)
    for j = 0 to 9
        int idx = i * 10 + j
        float mult = mult_start + j * mult_step
        ST_State state = st_states.get(idx)
        
        float basic_lower = avg_hl - mult * atr
        float basic_upper = avg_hl + mult * atr
        
        float prev_lower = na(state.prev_up) ? basic_lower : state.prev_up
        float prev_upper = na(state.prev_dn) ? basic_upper : state.prev_dn
        
        float lower = close[1] > prev_lower ? math.max(basic_lower, prev_lower) : basic_lower
        float upper = close[1] < prev_upper ? math.min(basic_upper, prev_upper) : basic_upper
        
        int trend = state.trend
        if trend == -1 and close > prev_upper
            trend := 1
        else if trend == 1 and close < prev_lower
            trend := -1
            
        // Trade recording
        if trend != state.trend
            if state.position != 0
                float pnl = (close - state.entry_price) / state.entry_price * state.position * 100
                if pnl > 0
                    state.wins += 1
                    state.gross_profit += pnl
                else
                    state.gross_loss += math.abs(pnl)
                state.trades += 1
                
            state.position := trend
            state.entry_price := close
            
        state.prev_up := lower
        state.prev_dn := upper
        state.trend := trend

//---------------------------------------------------------------------------------------------------------------------}
// Main Supertrend Plot
//---------------------------------------------------------------------------------------------------------------------{
[supertrend, direction] = ta.supertrend(main_mult, main_len)
float upTrend = direction < 0 ? supertrend : na
float downTrend = direction > 0 ? supertrend : na

if auto_apply
    matrix<float> z_matrix_rt = matrix.new<float>(10, 10, 0.0)
    for i = 0 to 9
        for j = 0 to 9
            int idx = i * 10 + j
            z_matrix_rt.set(i, j, st_states.get(idx).get_metric(metric_input))
            
    int rt_stable_i = 1
    int rt_stable_j = 1
    float rt_max_stable_score = na
    for i = 1 to 8
        for j = 1 to 8
            float sum_score = 0.0
            for di = -1 to 1
                for dj = -1 to 1
                    sum_score += z_matrix_rt.get(i + di, j + dj)
            float avg_score = sum_score / 9
            
            float dev_sum = 0.0
            for di = -1 to 1
                for dj = -1 to 1
                    float diff = z_matrix_rt.get(i + di, j + dj) - avg_score
                    dev_sum += diff * diff
            float std_dev = math.sqrt(dev_sum / 9)
            
            float combined_score = avg_score - std_dev * 1.5
            if na(rt_max_stable_score) or combined_score > rt_max_stable_score
                rt_max_stable_score := combined_score
                rt_stable_i := i
                rt_stable_j := j
                
    int best_idx = rt_stable_i * 10 + rt_stable_j
    ST_State best_state = st_states.get(best_idx)
    upTrend := best_state.trend == 1 ? best_state.prev_up : na
    downTrend := best_state.trend == -1 ? best_state.prev_dn : na

plot(upTrend, "Up Trend", color=color.new(#089981, 0), style=plot.style_linebr, force_overlay=true)
plot(downTrend, "Down Trend", color=color.new(#f23645, 0), style=plot.style_linebr, force_overlay=true)

// Pre-calculate projection base values to avoid local scope warnings
float chart_lowest = 0.0
float chart_highest = 100.0

//---------------------------------------------------------------------------------------------------------------------}
// 3D Surface Rendering
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast
    matrix<float> z_matrix = matrix.new<float>(10, 10, 0.0)
    float min_z = na
    float max_z = na
    
    int best_i = 0
    int best_j = 0
    float best_val = na
    
    int worst_i = 0
    int worst_j = 0
    float worst_val = na
    
    // Calculate metrics
    for i = 0 to 9
        for j = 0 to 9
            int idx = i * 10 + j
            ST_State state = st_states.get(idx)
            
            float val = 0.0
            if metric_input == "Net Profit"
                val := state.gross_profit - state.gross_loss
            else if metric_input == "Win Rate"
                val := state.trades > 0 ? (state.wins / state.trades * 100) : 0.0
            else if metric_input == "Profit Factor"
                val := state.gross_loss > 0 ? (state.gross_profit / state.gross_loss) : (state.gross_profit > 0 ? 10.0 : 0.0)
            else if metric_input == "Total Trades"
                val := state.trades
            else if metric_input == "Average Trade"
                val := state.trades > 0 ? (state.gross_profit - state.gross_loss) / state.trades : 0.0
            else if metric_input == "Reward/Risk Ratio"
                float avg_win = state.wins > 0 ? state.gross_profit / state.wins : 0.0
                float losses = state.trades - state.wins
                float avg_loss = losses > 0 ? state.gross_loss / losses : 0.0
                val := avg_loss > 0 ? avg_win / avg_loss : (avg_win > 0 ? 10.0 : 0.0)
            else if metric_input == "Gross Profit"
                val := state.gross_profit
            else if metric_input == "Total Wins"
                val := state.wins
            else if metric_input == "Win/Loss Ratio"
                float losses = state.trades - state.wins
                val := losses > 0 ? state.wins / losses : (state.wins > 0 ? 10.0 : 0.0)
                
            z_matrix.set(i, j, val)
            
            min_z := na(min_z) ? val : math.min(min_z, val)
            max_z := na(max_z) ? val : math.max(max_z, val)
            
            if na(best_val) or val >= best_val
                best_val := val
                best_i := i
                best_j := j
                
            if na(worst_val) or val <= worst_val
                worst_val := val
                worst_i := i
                worst_j := j
                
    // Find most stable area (highest average and lowest variance in a full 3x3 window)
    int stable_i = 1
    int stable_j = 1
    float max_stable_score = na
    for i = 1 to 8
        for j = 1 to 8
            float sum_score = 0.0
            for di = -1 to 1
                for dj = -1 to 1
                    sum_score += z_matrix.get(i + di, j + dj)
            float avg_score = sum_score / 9
            
            float dev_sum = 0.0
            for di = -1 to 1
                for dj = -1 to 1
                    float diff = z_matrix.get(i + di, j + dj) - avg_score
                    dev_sum += diff * diff
            float std_dev = math.sqrt(dev_sum / 9)
            
            float combined_score = avg_score - std_dev * 1.5
            if na(max_stable_score) or combined_score > max_stable_score
                max_stable_score := combined_score
                stable_i := i
                stable_j := j
                
    // Normalize matrix to 0-1 range for Z axis
    float range_z = max_z - min_z
    if range_z == 0
        range_z := 1
        
    matrix<float> norm_z = matrix.new<float>(10, 10, 0.0)
    for i = 0 to 9
        for j = 0 to 9
            norm_z.set(i, j, (z_matrix.get(i, j) - min_z) / range_z)
            
    // 3D Projection configuration
    int bar_offset = 5
    float base_price = chart_lowest
    float price_range = chart_highest - base_price
    if price_range == 0
        price_range := close * 0.01
        
    float y_step = price_range * y_step_in
    float z_scale = price_range * z_scale_in
    
    // Store projection coordinates
    matrix<int> cx_mat = matrix.new<int>(10, 10, 0)
    matrix<float> cy_mat = matrix.new<float>(10, 10, 0.0)
    
    for i = 0 to 9
        for j = 0 to 9
            // Isometric X: right for i, left for j. Offset to avoid drawing into the future.
            int cx = bar_index - bar_offset - 9 * x_step_in + (i - j) * x_step_in
            // Isometric Y: up for both i and j. Plus Z value.
            float cy = base_price + (i + j) * y_step + norm_z.get(i, j) * z_scale
            cx_mat.set(i, j, cx)
            cy_mat.set(i, j, cy)
            
    // --- 3D Bounding Box & Axes ---
    int x_left = bar_index - bar_offset - 9 * x_step_in + (0 - 9) * x_step_in
    float y_left = base_price + (0 + 9) * y_step
    
    int x_right = bar_index - bar_offset - 9 * x_step_in + (9 - 0) * x_step_in
    float y_right = base_price + (9 + 0) * y_step
    
    int x_back = bar_index - bar_offset - 9 * x_step_in + (9 - 9) * x_step_in
    float y_back = base_price + (9 + 9) * y_step
    
    color axis_col = color.new(color.gray, 60)
    
    // Draw back walls
    line.new(x_left, y_left, x_back, y_back, color=axis_col)
    line.new(x_right, y_right, x_back, y_back, color=axis_col)
    line.new(x_left, y_left + z_scale, x_back, y_back + z_scale, color=axis_col)
    line.new(x_right, y_right + z_scale, x_back, y_back + z_scale, color=axis_col)
    line.new(x_left, y_left, x_left, y_left + z_scale, color=axis_col)
    line.new(x_right, y_right, x_right, y_right + z_scale, color=axis_col)
    line.new(x_back, y_back, x_back, y_back + z_scale, color=axis_col)
    
    // Grid lines on back walls
    for k = 1 to 4
        float zl = k * z_scale / 5
        line.new(x_left, y_left + zl, x_back, y_back + zl, color=color.new(axis_col, 30), style=line.style_dotted)
        line.new(x_right, y_right + zl, x_back, y_back + zl, color=color.new(axis_col, 30), style=line.style_dotted)
        
    // Scale Labels on Z-Axis (Left Back Wall Edge)
    label.new(x_left, y_left + z_scale, str.tostring(max_z, "#.##"), style=label.style_label_right, color=color(na), textcolor=chart.fg_color, size=size.tiny)
    label.new(x_left, y_left + z_scale/2, str.tostring(min_z + (max_z - min_z)/2, "#.##"), style=label.style_label_right, color=color(na), textcolor=chart.fg_color, size=size.tiny)
    label.new(x_left, y_left, str.tostring(min_z, "#.##"), style=label.style_label_right, color=color(na), textcolor=chart.fg_color, size=size.tiny)
    
    // Axis Titles
    label.new(x_left, y_left, "Length (Y)\nLen: " + str.tostring(len_start), style=label.style_label_right, color=color(na), textcolor=chart.fg_color, size=size.tiny)
    label.new(x_right, y_right, "Multiplier (X)\nMult: " + str.tostring(mult_start), style=label.style_label_left, color=color(na), textcolor=chart.fg_color, size=size.tiny)
            
    // Draw cells back-to-front (Painter's algorithm)
    for j = 8 to 0
        for i = 8 to 0
            int x1 = cx_mat.get(i, j)
            float y1 = cy_mat.get(i, j)
            
            int x2 = cx_mat.get(i+1, j)
            float y2 = cy_mat.get(i+1, j)
            
            int x3 = cx_mat.get(i, j+1)
            float y3 = cy_mat.get(i, j+1)
            
            int x4 = cx_mat.get(i+1, j+1)
            float y4 = cy_mat.get(i+1, j+1)
            
            line l1 = line.new(x1, y1, x2, y2, color=color_wire)
            line l2 = line.new(x3, y3, x4, y4, color=color_wire)
            
            line.new(x1, y1, x3, y3, color=color_wire)
            line.new(x2, y2, x4, y4, color=color_wire)
            
            float avg_z = (norm_z.get(i, j) + norm_z.get(i+1, j) + norm_z.get(i, j+1) + norm_z.get(i+1, j+1)) / 4
            color cell_color = color.from_gradient(avg_z, 0, 1, color.new(color_low, 30), color.new(color_high, 30))
            
            bool is_best_cell = (i == best_i or i + 1 == best_i) and (j == best_j or j + 1 == best_j)
            bool is_stable_cell = (i == stable_i or i + 1 == stable_i) and (j == stable_j or j + 1 == stable_j)
            if is_best_cell
                cell_color := color.new(#FFD700, 20)
            else if is_stable_cell
                cell_color := color.new(color_stable, 20)
            
            linefill.new(l1, l2, cell_color)
            
    // Legend / Info Label
    int center_x = cx_mat.get(5, 5)
    float top_y = y_back + z_scale + price_range * 0.05
    
    // Highlight Best Point
    int best_cx = cx_mat.get(best_i, best_j)
    float best_cy = cy_mat.get(best_i, best_j)
    string best_lbl = "↓\nVal: " + str.tostring(best_val, "#.##") + "\nLen: " + str.tostring(len_start + best_i * len_step) + " | Mult: " + str.tostring(mult_start + best_j * mult_step)
    label.new(best_cx, best_cy, best_lbl, color=color(na), style=label.style_label_down, textcolor=chart.fg_color, size=size.small)

    // Highlight Stable Point
    if stable_i != best_i or stable_j != best_j
        int stable_cx = cx_mat.get(stable_i, stable_j)
        float stable_cy = cy_mat.get(stable_i, stable_j)
        float stable_val = z_matrix.get(stable_i, stable_j)
        string stable_lbl = "↓\nStable: " + str.tostring(stable_val, "#.##") + "\nLen: " + str.tostring(len_start + stable_i * len_step) + " | Mult: " + str.tostring(mult_start + stable_j * mult_step)
        label.new(stable_cx, stable_cy, stable_lbl, color=color(na), style=label.style_label_down, textcolor=chart.fg_color, size=size.small)

    string lbl_text = "Z-Axis Metric: " + metric_input + "\nRange: " + str.tostring(min_z, "#.##") + " to " + str.tostring(max_z, "#.##")
    label.new(x_left, y_back + z_scale + price_range * 0.05, lbl_text, color=color(na), style=label.style_label_down, textcolor=chart.fg_color, size=size.small)

    // Dashboard Rendering
    if dashboardInput
        var table t_able = table.new(parsedDashboardPosition, 11, 13, bgcolor = BACKGROUND, border_width = 1, frame_color = BORDERS, frame_width = 1, force_overlay = true)
        
        int NUM_BINS = 25
        float[] bins = array.new_float(NUM_BINS, 0)
        float sum_val = 0.0
        for i = 0 to 9
            for j = 0 to 9
                float v = z_matrix.get(i, j)
                sum_val += v
                int bin_idx = math.floor((v - min_z) / range_z * (NUM_BINS - 0.01))
                bin_idx := math.max(0, math.min(NUM_BINS - 1, bin_idx))
                bins.set(bin_idx, bins.get(bin_idx) + 1)
                
        float avg_val = sum_val / 100
        float max_bin = array.max(bins)
        
        int avg_bin_idx = math.floor((avg_val - min_z) / range_z * (NUM_BINS - 0.01))
        avg_bin_idx := math.max(0, math.min(NUM_BINS - 1, avg_bin_idx))
        
        string[] blocks = array.from(" ", "▂", "▃", "▄", "▅", "▆", "▇", "█")
        string dist_str1 = ""
        string dist_str2 = ""
        for i = 0 to NUM_BINS - 1
            float b = bins.get(i)
            int block_idx = max_bin > 0 ? math.round((b / max_bin) * 7) : 0
            if i == avg_bin_idx
                dist_str1 += "┃"
                dist_str2 += "▲"
            else
                dist_str1 += blocks.get(block_idx)
                dist_str2 += " "
                
        string dist_text = "Value Distribution (Avg: " + str.tostring(avg_val, "#.##") + ")\n" + dist_str1 + "\n" + dist_str2
        
        t_able.merge_cells(0, 0, 10, 0)
        t_able.cell(0, 0, dist_text, text_color = color.white, text_size = parsedDashboardSize, text_halign = text.align_center, text_font_family = font.family_monospace)
        
        t_able.merge_cells(0, 1, 10, 1)
        t_able.cell(0, 1, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", text_color = BORDERS, text_size = parsedDashboardSize, text_halign = text.align_center)
        
        t_able.cell(0, 2, "Len \\ Mult", text_color = HEADERS, text_size = parsedDashboardSize, text_halign = text.align_center)
        for j = 0 to 9
            t_able.cell(j + 1, 2, str.tostring(mult_start + j * mult_step, "#.#"), text_color = HEADERS, text_size = parsedDashboardSize, text_halign = text.align_center)
            
        for i = 0 to 9
            t_able.cell(0, i + 3, str.tostring(len_start + i * len_step), text_color = HEADERS, text_size = parsedDashboardSize, text_halign = text.align_center)
            for j = 0 to 9
                float val = z_matrix.get(i, j)
                float norm_val = norm_z.get(i, j)
                color cell_bg = color.from_gradient(norm_val, 0, 1, color_low, color_high)
                
                int state_idx = i * 10 + j
                ST_State state = st_states.get(state_idx)
                
                string cell_text = str.tostring(val, "#.##")
                string cell_tooltip = "Val: " + str.tostring(val, "#.##") + "\nLen: " + str.tostring(len_start + i * len_step) + "\nMult: " + str.tostring(mult_start + j * mult_step) + "\nTrades: " + str.tostring(state.trades)
                
                if i == best_i and j == best_j
                    cell_text := "★\n" + cell_text
                    cell_tooltip := "⭐ Best Value\n" + cell_tooltip
                else if i == worst_i and j == worst_j
                    cell_text := "✖\n" + cell_text
                    cell_tooltip := "📉 Worst Value\n" + cell_tooltip
                else if i == stable_i and j == stable_j
                    cell_text := "♦\n" + cell_text
                    cell_tooltip := "♦ Most Stable Area\n" + cell_tooltip
                    
                color text_col = color.white
                if i == stable_i and j == stable_j and (stable_i != best_i or stable_j != best_j)
                    text_col := color_stable
                    
                t_able.cell(j + 1, i + 3, cell_text, text_color = text_col, text_size = parsedDashboardSize, text_halign = text.align_center, bgcolor = cell_bg, tooltip = cell_tooltip)

//---------------------------------------------------------------------------------------------------------------------}
