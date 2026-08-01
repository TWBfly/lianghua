// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Swing Structure Scanner [LuxAlgo]", "LuxAlgo - Swing Structure Scanner", overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
//User Inputs
//---------------------------------------------------------------------------------------------------------------------{

len = input.int(5, title = "Swing Length", group = "Swing Points")

lb = input.int(3, title = "Swing Display Lookback", group = "Swing Points", maxval = 49, tooltip = "The number of Symbols will determine the Max LB Allowed, before getting an error.\n\n 1 Symbol => 49 Max\n2 Symbols => 34 Max\n3 Symbols => 28 Max\n4 Symbols => 24 Max\n5 Symbols => 21 Max\n6 Symbols => 19 Max")
//Max LB Sizes
//1 - 49
//2 - 34
//3 - 28
//4 - 24
//5 - 21
//6 - 19

//Symbols
s1Tog = true
tf1 = input.timeframe("", title = ">>>  Symbol 1", inline = "s1", group = "Symbols")
sym1 = input.symbol("CME_MINI:ES1!", title = "", inline = "s1", group = "Symbols")

s2Tog = input.bool(true, title = "Symbol 2", inline = "s2", group = "Symbols")
tf2 = input.timeframe("", title = "", inline = "s2", group = "Symbols")
sym2 = input.symbol("CME_MINI:RTY1!", title = "", inline = "s2", group = "Symbols")

s3Tog = input.bool(true, title = "Symbol 3", inline = "s3", group = "Symbols")
tf3 = input.timeframe("", title = "", inline = "s3", group = "Symbols")
sym3 = input.symbol("CME_MINI:NQ1!", title = "", inline = "s3", group = "Symbols")

s4Tog = input.bool(true, title = "Symbol 4", inline = "s4", group = "Symbols")
tf4 = input.timeframe("", title = "", inline = "s4", group = "Symbols")
sym4 = input.symbol("COINBASE:BTCUSD", title = "", inline = "s4", group = "Symbols")

s5Tog = input.bool(true, title = "Symbol 5", inline = "s5", group = "Symbols")
tf5 = input.timeframe("", title = "", inline = "s5", group = "Symbols")
sym5 = input.symbol("COINBASE:ETHUSD", title = "", inline = "s5", group = "Symbols")

s6Tog = input.bool(true, title = "Symbol 6", inline = "s6", group = "Symbols")
tf6 = input.timeframe("", title = "", inline = "s6", group = "Symbols")
sym6 = input.symbol("NYMEX:CL1!", title = "", inline = "s6", group = "Symbols")

sym_disp_num = (s1Tog?1:0) + (s2Tog?1:0) + (s3Tog?1:0) + (s4Tog?1:0) + (s5Tog?1:0) + (s6Tog?1:0)

//Dashboard Style
vert_display = input.bool(true, title = "Vertical Display", group = "Dashboard Style")

scale_factor = 1 + input.float(0.0, title = "Scaling Factor", step = 0.01, minval = -1, group = "Dashboard Style")

dashLocInput  = input.string("Bottom Right" , "Location"  , options = ["Bottom Right", "Bottom Center","Bottom Left","Middle Right","Middle Center", "Middle Left", "Top Right", "Top Center", "Top Left"], group = "Dashboard Style")
dash_loc = str.lower(str.replace(dashLocInput," ","_"))

txt_size = str.lower(input.string("Small", title = "Text Size", options = ["Tiny","Small","Normal","Large","Huge","Auto"], group = "Dashboard Style"))

table_bg_color = input.color(#1e222d, title = "Background Color", group = "Dashboard Style")

thCol = input.color(#089981, title = "H/L Colors          ", group = "Dashboard Style", inline = "1")
tlCol = input.color(#f23645, title = "", group = "Dashboard Style", inline = "1")

table_empty_cell_color = input.color(#373a46, title = "Empty Cell Color", group = "Dashboard Style")

txtColor = input.color(color.white, title = "Text Color", group = "Dashboard Style")

//---------------------------------------------------------------------------------------------------------------------}
//UDTs
//---------------------------------------------------------------------------------------------------------------------{

type pb
    float price
    int bar


//---------------------------------------------------------------------------------------------------------------------}
//Global Functions
//---------------------------------------------------------------------------------------------------------------------{

get_sym(_lookup) =>
    switch
        _lookup == 1  => sym1 == "" ? syminfo.ticker : array.get(str.split(sym1,":"),1)
        _lookup == 2  => sym2 == "" ? syminfo.ticker :  array.get(str.split(sym2,":"),1)
        _lookup == 3  => sym3 == "" ? syminfo.ticker :  array.get(str.split(sym3,":"),1)
        _lookup == 4  => sym4 == "" ? syminfo.ticker :  array.get(str.split(sym4,":"),1)
        _lookup == 5  => sym5 == "" ? syminfo.ticker :  array.get(str.split(sym5,":"),1)
        _lookup == 6  => sym6 == "" ? syminfo.ticker :  array.get(str.split(sym6,":"),1)

tf_switch(_lookup) =>
    switch
        _lookup == 1  => tf1 == "" ? timeframe.period : tf1
        _lookup == 2  => tf2 == "" ? timeframe.period : tf2
        _lookup == 3  => tf3 == "" ? timeframe.period : tf3
        _lookup == 4  => tf4 == "" ? timeframe.period : tf4
        _lookup == 5  => tf5 == "" ? timeframe.period : tf5
        _lookup == 6  => tf6 == "" ? timeframe.period : tf6

get_formatted_tf(_tf) =>
    period = str.tonumber(_tf)
    unit = switch
        na(period) => _tf
        (period % 60 == 0) => str.tostring(period/60) + "h" 
        => str.tostring(period) + "m"
    unit

//Structure
get_data(_len) =>
    var int dir = 0

    float top = na
    float bot = na
    int topbar = na
    int botbar = na

    upper = ta.highest(_len)
    lower = ta.lowest(_len)

    if dir >= 0 and high[_len] > upper
        dir := -1 
        top := high[_len]
        topbar := bar_index[_len]
    if dir <= 0 and low[_len] < lower
        dir := 1
        bot := low[_len]
        botbar := bar_index[_len]

    top_conf = not na(top)
    bot_conf = not na(bot)
    atr = ta.atr(14)*0.2
    [top_conf,bot_conf,top,bot,topbar,botbar,atr]

get_pivmap(_tog, _sym,_top_conf,_bot_conf,_top,_bot,_hibar,_lobar) =>
    var int last_piv = 0

    var hi3_track = array.new<pb>(na)
    var lo3_track = array.new<pb>(na)
    
    var pb t = pb.new(na,na)
    var pb b = pb.new(na,na)
    


    if _bot_conf and not _bot_conf[1]
        b := pb.new(_bot,_lobar)
        lo3_track.push(b)
        last_piv := -1 

    if _top_conf and not _top_conf[1]
        t := pb.new(_top,_hibar)
        hi3_track.push(t)
        last_piv := 1

    for i = 0 to lb
        if hi3_track.size() > lb
            hi3_track.shift()
        if lo3_track.size() > lb
            lo3_track.shift()

    piv3_track = array.new_float(na)
    piv_map = map.new<int,float>()

    if hi3_track.size() == lb and lo3_track.size() == lb
        for i = 0 to (lb-1)
            hp = hi3_track.get(i).price
            lp = lo3_track.get(i).price
            if last_piv == 1
                piv3_track.push(lp)
                piv3_track.push(hp)
            if last_piv == -1
                piv3_track.push(hp)
                piv3_track.push(lp)

    for [i,piv] in piv3_track
        piv_map.put(i,piv)

    [(_tog?last_piv:na),(_tog?piv_map:map.new<int,float>())]

is_odd(_val) => _val/2 - math.floor(_val/2) > 0 ? true : false

//---------------------------------------------------------------------------------------------------------------------}
//Table Setup
//---------------------------------------------------------------------------------------------------------------------{

tab_rows = vert_display? ((lb*2)*sym_disp_num)+sym_disp_num : (lb*2)+1
tab_cols = vert_display? (lb*2)+3 : 3 + ((lb*2)*sym_disp_num) + (sym_disp_num - 1)

var t1 = table.new(dash_loc, tab_cols , tab_rows , border_color = table_bg_color, border_width = 1, frame_color = table_bg_color, frame_width = 2)

if barstate.isfirst
    if vert_display
        t1.merge_cells(0,0,(lb*2)+2,0)
        t1.merge_cells(0,1,0,lb*2)
        t1.merge_cells(1,1,1,lb)
        t1.merge_cells(1,lb+1,1,(lb*2))
        t1.merge_cells(2,1,2,(lb*2))
        t1.cell(0,0, bgcolor = table_bg_color, height = 0.0000001)
        t1.cell(0,1, text = get_sym(1) + " [" + get_formatted_tf(tf_switch(1)) + "]", text_color = txtColor, bgcolor = table_bg_color, text_size = txt_size, width = 2, height = (lb*2)*scale_factor)

        t1.cell(1,1, bgcolor = thCol, width = 0.1*scale_factor, height = lb*scale_factor)
        t1.cell(1,lb+1, bgcolor = tlCol, width = 0.1*scale_factor, height = lb*scale_factor)

        t1.cell(2,1, bgcolor = table_bg_color, width = 0.00001*scale_factor, height = (lb*2)*scale_factor)
 
        if sym_disp_num > 1
            for i = 1 to sym_disp_num-1
                row = ((lb*2)*i)+i
                t1.merge_cells(0,row+1,0,row+(lb*2))
                t1.merge_cells(1,row,(lb*2)+2,row)
                t1.merge_cells(1,row+1,1,row+lb)
                t1.merge_cells(1,row+lb+1,1,row+lb*2)
                t1.merge_cells(2,row+1,2,row+(lb*2))
                t1.cell(1,row+1, bgcolor = thCol, width = 0.1*scale_factor, height = lb*scale_factor)
                t1.cell(1,row+lb+1, bgcolor = tlCol, width = 0.1*scale_factor, height = lb*scale_factor)
                t1.cell(2,row+1, bgcolor = table_bg_color, width = 0.1*scale_factor, height = (lb*2)*scale_factor)
                t1.cell(0,row, bgcolor = table_bg_color, height = 0.1*scale_factor)
                t1.cell(1,row, bgcolor = table_bg_color, height = 0.1*scale_factor, width = (lb*scale_factor) + (0.1*scale_factor)+(0.00001 *scale_factor))
                t1.cell(0,row+1, text = get_sym(i+1) + " [" + get_formatted_tf(tf_switch(i+1)) + "]", text_color = txtColor, bgcolor = table_bg_color, text_size = txt_size)
    else
        t1.merge_cells(3,0,3+(lb*2)-1,0)
        t1.merge_cells(0,1,0,lb)

        t1.merge_cells(0,lb+1,0,(lb*2))
        t1.merge_cells(1,1,1,lb)
        t1.merge_cells(1,lb+1,1,(lb*2))
        t1.merge_cells(2,0,2,(lb*2))

        t1.cell(0,1, text = "Highs", bgcolor = table_bg_color, text_color = txtColor, height = 3*scale_factor, text_size = txt_size)
        t1.cell(0,lb+1, text = "Lows", bgcolor = table_bg_color, text_color = txtColor, height = 3*scale_factor, text_size = txt_size)
        
        t1.cell(1,1, bgcolor = thCol, width = 0.1*scale_factor, height = 3*scale_factor)
        t1.cell(1,lb+1, bgcolor = tlCol, width = 0.1*scale_factor, height = 3*scale_factor)
        t1.cell(1,0, bgcolor = table_bg_color, width = 0.1*scale_factor, height = 3*scale_factor)
        t1.cell(2,0, bgcolor = table_bg_color, width = 0.00001*scale_factor, height = 6*scale_factor)
        
        t1.cell(0,0, bgcolor = table_bg_color, height = 1*scale_factor)
        t1.cell(3,0, text = get_sym(1) + " [" + get_formatted_tf(tf_switch(1)) + "]", text_color = txtColor, bgcolor = table_bg_color,width = lb*scale_factor, text_size = txt_size)

        if sym_disp_num > 1
            for i = 1 to sym_disp_num-1
                col = 3+((lb*2)*i)+i-1
                t1.merge_cells(col+1,0,col+(lb*2),0)
                t1.merge_cells(col,0,col,(lb*2))
                t1.cell(col,0, bgcolor = table_bg_color, width = 0.1*scale_factor)
                t1.cell(col+1,0, text = get_sym(i+1) + " [" + get_formatted_tf(tf_switch(i+1)) + "]", text_color = txtColor, bgcolor = table_bg_color,width = lb*scale_factor, text_size = txt_size)

//---------------------------------------------------------------------------------------------------------------------}
//Table Specific Display Functions
//---------------------------------------------------------------------------------------------------------------------{
//Setting Blank Grid
set_cells(start_column, start_row) =>
    for i = start_column to ((start_column+(lb*2))-1)
        for e = start_row to ((start_row + (lb*2))-1)
            t1.cell(i,e, bgcolor = table_empty_cell_color, width = 0.5*scale_factor, height = 1*scale_factor)   
            t1.cell_set_tooltip(i,e,"")

send_to_table(start_column, start_row, last_piv, piv_map, _atr)  =>
    sorted_map = map.new<int,int>()
    for [k,v] in piv_map
        vz = piv_map.values()
        int down_count = 0
        int up_count = 0
        for val in vz
            switch
                val < (v-_atr) => down_count += 1
                val > (v+_atr) => up_count += 1
        sorted_map.put(k,last_piv == 1 ? up_count : ((lb*2)-1)-down_count)

    for [c,r] in sorted_map
        oc = last_piv == -1 ? tlCol : thCol
        ec = last_piv == 1 ? tlCol : thCol
        col = is_odd(c)?oc:ec
        t1.cell_set_bgcolor(c+start_column,r+1+start_row,col)
        t1.cell_set_tooltip(c+start_column,r+1+start_row,str.tostring(piv_map.get(c)))

//---------------------------------------------------------------------------------------------------------------------}
//Requesting Data
//---------------------------------------------------------------------------------------------------------------------{

[s1_top_conf,s1_bot_conf,s1_top,s1_bot,s1_hibar,s1_lobar,s1_atr] = request.security(ticker.inherit(syminfo.tickerid,sym1),tf1, get_data(len))
[s2_top_conf,s2_bot_conf,s2_top,s2_bot,s2_hibar,s2_lobar,s2_atr] = request.security(ticker.inherit(syminfo.tickerid,sym2),tf2, get_data(len))
[s3_top_conf,s3_bot_conf,s3_top,s3_bot,s3_hibar,s3_lobar,s3_atr] = request.security(ticker.inherit(syminfo.tickerid,sym3),tf3, get_data(len))
[s4_top_conf,s4_bot_conf,s4_top,s4_bot,s4_hibar,s4_lobar,s4_atr] = request.security(ticker.inherit(syminfo.tickerid,sym4),tf4, get_data(len))
[s5_top_conf,s5_bot_conf,s5_top,s5_bot,s5_hibar,s5_lobar,s5_atr] = request.security(ticker.inherit(syminfo.tickerid,sym5),tf5, get_data(len))
[s6_top_conf,s6_bot_conf,s6_top,s6_bot,s6_hibar,s6_lobar,s6_atr] = request.security(ticker.inherit(syminfo.tickerid,sym6),tf6, get_data(len))

[s1_last_piv,s1_piv_map] = get_pivmap(s1Tog, sym1, s1_top_conf,s1_bot_conf,s1_top,s1_bot,s1_hibar,s1_lobar)
[s2_last_piv,s2_piv_map] = get_pivmap(s2Tog, sym2, s2_top_conf,s2_bot_conf,s2_top,s2_bot,s2_hibar,s2_lobar)
[s3_last_piv,s3_piv_map] = get_pivmap(s3Tog, sym3, s3_top_conf,s3_bot_conf,s3_top,s3_bot,s3_hibar,s3_lobar)
[s4_last_piv,s4_piv_map] = get_pivmap(s4Tog, sym4, s4_top_conf,s4_bot_conf,s4_top,s4_bot,s4_hibar,s4_lobar)
[s5_last_piv,s5_piv_map] = get_pivmap(s5Tog, sym5, s5_top_conf,s5_bot_conf,s5_top,s5_bot,s5_hibar,s5_lobar)
[s6_last_piv,s6_piv_map] = get_pivmap(s6Tog, sym6, s6_top_conf,s6_bot_conf,s6_top,s6_bot,s6_hibar,s6_lobar)


//---------------------------------------------------------------------------------------------------------------------}
//Updating Table
//---------------------------------------------------------------------------------------------------------------------{

if barstate.islast
    if vert_display
        if s1Tog
            set_cells(3,1)
            send_to_table(3,0,s1_last_piv,s1_piv_map,s1_atr)
        if s2Tog
            set_cells(3, (lb*2) + 1+1)
            send_to_table(3, (lb*2) + 1,s2_last_piv,s2_piv_map,s2_atr)
        if s3Tog
            set_cells(3, (lb*2)*2 + 2+1)
            send_to_table(3, (lb*2)*2 + 2,s3_last_piv,s3_piv_map,s3_atr)
        if s4Tog
            set_cells(3, (lb*2)*3 + 3+1)
            send_to_table(3, (lb*2)*3 + 3,s4_last_piv,s4_piv_map,s4_atr)
        if s5Tog
            set_cells(3, (lb*2)*4 + 4+1)
            send_to_table(3, (lb*2)*4 + 4,s5_last_piv,s5_piv_map,s5_atr)
        if s6Tog
            set_cells(3, (lb*2)*5 + 5+1) 
            send_to_table(3, (lb*2)*5 + 5,s6_last_piv,s6_piv_map,s6_atr)
    else
        if s1Tog
            set_cells(3,1)
            send_to_table(3,0,s1_last_piv,s1_piv_map,s1_atr)
        if s2Tog
            set_cells(3 + (lb*2) + 1,1)
            send_to_table(3 + (lb*2) + 1,0,s2_last_piv,s2_piv_map,s2_atr)
        if s3Tog
            set_cells(3 + (lb*2)*2 + 2,1)
            send_to_table(3 + (lb*2)*2 + 2,0,s3_last_piv,s3_piv_map,s3_atr)
        if s4Tog
            set_cells(3 + (lb*2)*3 + 3,1)
            send_to_table(3 + (lb*2)*3 + 3,0,s4_last_piv,s4_piv_map,s4_atr)
        if s5Tog
            set_cells(3 + (lb*2)*4 + 4,1)
            send_to_table(3 + (lb*2)*4 + 4,0,s5_last_piv,s5_piv_map,s5_atr)
        if s6Tog
            set_cells(3 + (lb*2)*5 + 5,1) 
            send_to_table(3 + (lb*2)*5 + 5,0,s6_last_piv,s6_piv_map,s6_atr)

//---------------------------------------------------------------------------------------------------------------------}