// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Rally Base Drop SND Pivots [LuxAlgo]", "LuxAlgo - RBD SND Pivots", overlay = true, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
//Inputs
//---------------------------------------------------------------------------------------------------------------------{

len = input.int(3, title = "Length")

rallyCol = input.color(color.new(#089981,50), title = "Rally Color")
dropCol = input.color(color.new(#f23645,50),title = "Drop Color")

hideLen = input.int(0, title = "Historical Lookback",minval  = 0,  tooltip = "Hide Levels farther than this number of bars back.\n\nNote: 0 = Show All")

//---------------------------------------------------------------------------------------------------------------------}
//UDTs
//---------------------------------------------------------------------------------------------------------------------{

type pb
    float price
    int bar

//---------------------------------------------------------------------------------------------------------------------}
//Basic Variables
//---------------------------------------------------------------------------------------------------------------------{

gc = close > open
rc = close < open

rally = gc and gc[1]
drop = rc and rc[1]
base = not rally and not drop

//---------------------------------------------------------------------------------------------------------------------}
//Functions
//---------------------------------------------------------------------------------------------------------------------{

check_rb_piv(_len) =>
    var pb piv_hi = pb.new(na,na)
    var pb piv_lo = pb.new(na,na)
    hst = ta.highest(math.max(close,open),_len)
    lst = ta.lowest(math.min(close,open),_len)
    for i = 0 to len - 1
        if not gc[i] or not rc[len+i]
            piv_lo := pb.new(na,na)
            break
        if i == len-1 and close > open[len+i] and close[len] < close[len+i]
            piv_lo := pb.new(low[i],bar_index[i])
            box.new(bar_index[len+i],hst[len],bar_index[len],lst[len], bgcolor = dropCol, border_color = dropCol)
            box.new(bar_index[i],hst,bar_index,lst, bgcolor = rallyCol, border_color = rallyCol)
    for i = 0 to len - 1
        if not rc[i] or not gc[len+i]
            piv_hi := pb.new(na,na)
            break
        if i == len-1 and close < open[len+i] and close[len] > close[len+i]
            piv_hi := pb.new(high[i],bar_index[i])
            box.new(bar_index[len+i],hst[len],bar_index[len],lst[len], bgcolor = rallyCol, border_color = rallyCol)
            box.new(bar_index[i],hst,bar_index,lst, bgcolor = dropCol, border_color = dropCol)
    
    [piv_hi,piv_lo] 

//---------------------------------------------------------------------------------------------------------------------}
//Processes
//---------------------------------------------------------------------------------------------------------------------{

[ph,pl] = check_rb_piv(len)

var his = array.new_line(na)
var los = array.new_line(na)

if not na(ph.price)
    his.push(line.new(ph.bar,ph.price,bar_index,ph.price, color = dropCol))
if not na(pl.price)
    los.push(line.new(pl.bar,pl.price,bar_index,pl.price, color = rallyCol))

for [i,ln] in los
    if close[1] < ln.get_y1()
        los.remove(i)
        continue
    ln.set_x2(bar_index)
for [i,ln] in his
    if close[1] > ln.get_y1()
        his.remove(i)
        continue
    ln.set_x2(bar_index)

if hideLen > 0
    for bx in box.all
        if bx.get_right() < bar_index-(hideLen+(len*2))
            bx.delete()
    for ln in line.all
        if ln.get_x1() < bar_index-(hideLen+(len*2))
            ln.delete()

//---------------------------------------------------------------------------------------------------------------------}