// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("The Strat [LuxAlgo]"
  , overlay = true
  , max_lines_count = 500
  , max_labels_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
asNum    = input(true, 'Show Numbers On Chart')
asCandle = input(true, 'Color Candles')

//Search
customCombo  = input.string('', 'Combo', group = 'Custom Combo Search', inline = 'highlight')
highlightCss = input(#2157f3, ''     , group = 'Custom Combo Search', inline = 'highlight')

//Pivot Machine Gun
showPmgLbl = input(false, 'Show Labels'                    , group = 'Pivot Machine Gun')
minSeq     = input.int(3, 'Min Sequence Length', minval = 1, group = 'Pivot Machine Gun')
minBreak   = input.int(3, 'Min Breaks', minval = 1         , group = 'Pivot Machine Gun')

showPmgLvl = input(true, 'Show Levels'   , group = 'Pivot Machine Gun', inline = 'pmg_lvl')
bullPmg    = input(#0cb51a, ''         , group = 'Pivot Machine Gun', inline = 'pmg_lvl') 
bearPmg    = input(#ff1100, ''         , group = 'Pivot Machine Gun', inline = 'pmg_lvl')

//Pivot Combos
showPivotCombos = input(true, 'Display Pivot Combos', group = 'Pivot Combos')
length          = input(14, 'Pivot Lookback'        , group = 'Pivot Combos')

rightBars = input.int(1, 'Right Bars Scan', minval = 0, group = 'Pivot Combos')
leftBars  = input.int(1, 'Left Bars Scan', minval = 0 , group = 'Pivot Combos')

//Dashboard
showDash  = input(false, 'Show Dashboard', group = 'Dashboard')
showNum   = input(true, 'Number Counter' , group = 'Dashboard')

showPivot      = input(true, 'Pivot Combos'       , inline = 'dashpivot', group = 'Dashboard')
pivotAsPercent = input(true, '%'                  , inline = 'dashpivot', group = 'Dashboard')
showTop        = input(3, 'Pivot Combos Rows'                           , group = 'Dashboard')

showMTF = input(true, 'Show MTF', group = 'Dashboard')

dashLoc  = input.string('Top Right', 'Location', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = 'Dashboard')
textSize = input.string('Small', 'Size'        , options = ['Tiny', 'Small', 'Normal']                 , group = 'Dashboard')

//------------------------------------------------------------------------------
//Functions
//-----------------------------------------------------------------------------{
n = bar_index

numbers()=>
    ins = high < high[1] and low > low[1] ? 1 : 0

    dir = high > high[1] and low > low[1] and low < high[1] ? 2  
      : high < high[1] and low < low[1] and high > low[1] ? -2
      : 0

    out = high > high[1] and low < low[1] ? 3 : 0

    [ins, dir, out]

pmg(bull, show_lines, css)=>
    var csum = 0

    condition = bull ? high < high[1] : low > low[1] 
    value = bull ? high : low

    csum := condition ? csum + 1 : 0

    breaks = 0 
    if csum < csum[1] and csum[1] + 1 >= minSeq
        for i = 1 to csum[1] + 1
            if (bull ? high[i] > high : low > low[i])
                break 
            else
                breaks += 1
        
        if show_lines
            if breaks >= minBreak
                for i = 1 to breaks
                    line.new(n[i], value[i], n, value[i]
                      , color = css)
    
    breaks

pivot_combo(condition, ins, dir, key, value, css, style)=>
    if condition
        txt = '|'
        
        for i = leftBars to -rightBars
            txt += ins[length+i] ? '1|' 
              : dir[length+i] == 2 ? '2|' 
              : dir[length+i] == -2 ? '-2|' 
              : '3|'
              
        if showPivotCombos
            label.new(n - length, condition, txt, color = #00000000
              , style = style
              , textcolor = css
              , size = size.small)

        if array.includes(key, txt)
            idx = array.indexof(key, txt)
            array.set(value, idx, array.get(value, idx) + 1)
        else
            array.push(key, txt)
            array.push(value, 1)

rank_pivot_combo(combo_num, combo_type, tb, col, css, table_size)=>
    //Pivot Low
    sorted_idx = array.sort_indices(combo_num, order.descending)
    len = math.min(showTop-1, array.size(sorted_idx) - 1)

    for i = 0 to len
        tb.cell(col, 2 + i
          , array.get(combo_type, array.get(sorted_idx, i))
          , text_color = css
          , text_size = table_size)
        
        num = array.get(combo_num, array.get(sorted_idx, i)) 
        den = pivotAsPercent ? array.sum(combo_num) / 100 : 1
        
        tb.cell(col + 1, 2 + i
          , str.tostring(num / den, '#.##')
          , text_color = css
          , text_size = table_size)
    
    len

//-----------------------------------------------------------------------------}
//Strat numbering
//-----------------------------------------------------------------------------{
[ins, dir, out] = numbers()

//Count
ins_count   = ta.cum(ins)
dirup_count = ta.cum(math.max(dir / 2, 0))
dirdn_count = ta.cum(math.max(-dir / 2, 0))
out_count   = ta.cum(out / 3)
total_count = (ins_count + dirup_count + dirdn_count + out_count) / 100

//MTF
[ins1, dir1, out1]    = request.security(syminfo.tickerid, '1', numbers())
[ins15, dir15, out15] = request.security(syminfo.tickerid, '15', numbers())
[ins60, dir60, out60] = request.security(syminfo.tickerid, '60', numbers())
[insD, dirD, outD]    = request.security(syminfo.tickerid, 'D', numbers())
[insW, dirW, outW]    = request.security(syminfo.tickerid, 'W', numbers())

//-----------------------------------------------------------------------------}
//Pivot machine gun
//-----------------------------------------------------------------------------{
bull_pmg = 0
bear_pmg = 0

if showPmgLvl or showPmgLbl
    bull_pmg := pmg(1, showPmgLvl, bullPmg) //Bullish pmg
    bear_pmg := pmg(0, showPmgLvl, bearPmg) //Bearish pmg

//-----------------------------------------------------------------------------}
//Custom combo search
//-----------------------------------------------------------------------------{
custom_combo = false

if customCombo != ''
    str_src = str.replace_all(customCombo, '-', '')
    len = str.length(str_src)

    txt = ''
    max = high
    min = low
    for i = 0 to len-1
        num = ins[i] ? '1' 
          : dir[i] == 2 ? '2' 
          : dir[i] == -2 ? '-2' 
          : '3'
        
        txt := num + txt
        
        max := math.max(high[i], max)
        min := math.min(low[i], min)

    if txt == customCombo
        box.new(n-len+1, max, n, min
          , border_color = highlightCss
          , bgcolor = na)

        custom_combo := true

//-----------------------------------------------------------------------------}
//Label pivots
//-----------------------------------------------------------------------------{
var ph_combo_type = array.new_string(0)
var ph_combo_num  = array.new_int(0)

var pl_combo_type = array.new_string(0)
var pl_combo_num  = array.new_int(0)

ph = ta.pivothigh(length, length)
pl = ta.pivotlow(length, length)

//Pivot high combo
pivot_combo(ph
  , ins
  , dir
  , ph_combo_type
  , ph_combo_num
  , color.red
  , label.style_label_down)

//Pivot low combo
pivot_combo(pl
  , ins
  , dir
  , pl_combo_type
  , pl_combo_num
  , color.teal
  , label.style_label_up)

//-----------------------------------------------------------------------------}
//Dashboard
//-----------------------------------------------------------------------------{
var table_position = dashLoc == 'Bottom Left' ? position.bottom_left 
  : dashLoc == 'Top Right' ? position.top_right 
  : position.bottom_right

var table_size = textSize == 'Tiny' ? size.tiny 
  : textSize == 'Small' ? size.small 
  : size.normal

var tb = table.new(table_position, 9, math.max(showTop + 3, 6)
  , bgcolor = #1e222d
  , border_color = #373a46
  , border_width = 1
  , frame_color = #373a46
  , frame_width = 1)

if barstate.isfirst and showDash
    if showPivot
        tb.cell(0, 0, 'Pivots Combo', text_color = color.white, text_size = table_size)
        tb.merge_cells(0, 0, 3, 0)
        
        tb.cell(0, 1, 'Combo', text_color = color.teal, text_size = table_size)
        tb.cell(1, 1, pivotAsPercent ? '%' : 'Count', text_color = color.teal, text_size = table_size)
        tb.cell(2, 1, 'Combo', text_color = color.red , text_size = table_size)
        tb.cell(3, 1, pivotAsPercent ? '%' : 'Count', text_color = color.red , text_size = table_size)

        //Merge Cells
        tb.merge_cells(0, showTop+2, 1, showTop+2)
        tb.merge_cells(2, showTop+2, 3, showTop+2)
    
    if showNum
        tb.cell(4, 0, 'Numbers Counter', text_color = color.white, text_size = table_size)
        tb.merge_cells(4, 0, 7, 0)

        tb.cell(5, 1, 'Count', text_color = color.white, text_size = table_size)
        tb.merge_cells(5, 1, 6, 1)

        tb.cell(7, 1, '%', text_color = color.white, text_size = table_size)

        //Merge Cells
        tb.merge_cells(5, 2, 6, 2)
        tb.merge_cells(5, 3, 6, 3)
        tb.merge_cells(5, 4, 6, 4)
        tb.merge_cells(5, 5, 6, 5)

    if showMTF
        tb.cell(8, 0, 'MTF', text_color = color.white, text_size = table_size)

var max_len = 0
if barstate.islast and showDash
    if showPivot
        //Pivot Low
        rank_pivot_combo(pl_combo_num, pl_combo_type, tb, 0, color.teal, table_size)
        
        //Pivot High
        rank_pivot_combo(ph_combo_num, ph_combo_type, tb, 2, color.red, table_size)
        
        //Pivot cells
        tb.cell(0, showTop+2, 'Pivot Low', text_color = color.teal, text_size = table_size)
        tb.cell(2, showTop+2, 'Pivot High', text_color = color.red, text_size = table_size)
    
    if showNum
        tb.cell(4, 2, '1', text_color = color.white, text_size = table_size)
        tb.cell(5, 2, str.tostring(ins_count), text_color = color.white, text_size = table_size)
        tb.cell(7, 2, str.tostring(ins_count / total_count, '#.##'), text_color = color.white, text_size = table_size)

        tb.cell(4, 3, '2', text_color = color.white, text_size = table_size)
        tb.cell(5, 3, str.tostring(dirup_count), text_color = color.white, text_size = table_size)
        tb.cell(7, 3, str.tostring(dirup_count / total_count, '#.##'), text_color = color.white, text_size = table_size)
        
        tb.cell(4, 4, '-2', text_color = color.white, text_size = table_size)
        tb.cell(5, 4, str.tostring(dirdn_count), text_color = color.white, text_size = table_size)
        tb.cell(7, 4, str.tostring(dirdn_count / total_count, '#.##'), text_color = color.white, text_size = table_size)
        
        tb.cell(4, 5, '3', text_color = color.white, text_size = table_size)
        tb.cell(5, 5, str.tostring(out_count), text_color = color.white, text_size = table_size)
        tb.cell(7, 5, str.tostring(out_count / total_count, '#.##'), text_color = color.white, text_size = table_size)

    if showMTF
        tb.cell(8, 1, str.format('1m ({0})', ins1 + dir1 + out1)     , text_color = color.white, text_size = table_size, text_halign = text.align_right)
        tb.cell(8, 2, str.format('15m ({0})', ins15 + dir15 + out15) , text_color = color.white, text_size = table_size, text_halign = text.align_right)
        tb.cell(8, 3, str.format('1h ({0})', ins60 + dir60 + out60)  , text_color = color.white, text_size = table_size, text_halign = text.align_right)
        tb.cell(8, 4, str.format('D ({0})', insD + dirD + outD)      , text_color = color.white, text_size = table_size, text_halign = text.align_right)
        tb.cell(8, 5, str.format('W ({0})', insW + dirW + outW)      , text_color = color.white, text_size = table_size, text_halign = text.align_right)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
//Plot as candles
barcolor(dir == 2 ? color.teal : dir == -2 ? color.red : na)

plotcandle(high, high, low, low
  , bordercolor = asCandle and out and close > open ? color.teal : asCandle and out and close < open ? color.red : na
  , color = na
  , wickcolor = na
  , display = display.all - display.status_line)

plotcandle(open, high, low, close
  , wickcolor = asCandle and ins and close > open ? color.teal : asCandle and ins and close < open ? color.red : na
  , color = na
  , bordercolor = na
  , display = display.all - display.status_line)

//Plot as numbers
plotchar(ins and close > open and asNum, 'Bullish Inside', '1', location.belowbar, color.teal)
plotchar(ins and close < open and asNum, 'Bearish Inside', '1', location.abovebar, color.red)

plotchar(dir == 2 and asNum, 'Directional Upward', '2', location.belowbar, color.teal)
plotchar(dir == -2 and asNum, 'Directional Downward', '2', location.abovebar, color.red)

plotchar(out and close > open and asNum, 'Bullish Outside', '3', location.belowbar, color.teal)
plotchar(out and close < open and asNum, 'Bearish Outside', '3', location.abovebar, color.red)

//Plot pmg
plotchar(bull_pmg >= minBreak and showPmgLbl, 'Bull PMG', '🔫', location.abovebar)
plotchar(bear_pmg >= minBreak and showPmgLbl, 'Bear PMG', '🔫', location.belowbar)

//-----------------------------------------------------------------------------}
//Alerts
//-----------------------------------------------------------------------------{
//Numbers
alertcondition(ins      , '1 Inside Bar'      , 'Inside bar detected')
alertcondition(dir == 2 , '2 Directional Bar' , 'Upside directional bar detected')
alertcondition(dir == -2, '-2 Directional Bar', 'Downside directional bar detected')
alertcondition(out      , '3 Directional Bar' , 'Outside bar detected')

//Detected Combo
alertcondition(custom_combo, 'Detected Combo' , 'Custom combo detected')

//PMG's
alertcondition(bull_pmg, 'Bullish PMG' , 'Bullish PMG detected')
alertcondition(bear_pmg, 'Bearish PMG' , 'Bearish PMG detected')

//-----------------------------------------------------------------------------}