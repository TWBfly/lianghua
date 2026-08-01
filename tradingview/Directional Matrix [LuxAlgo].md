// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=4
study("Directional Matrix [LuxAlgo]",overlay=true,max_bars_back=2000)
max    = input(120,'Maximum Length',minval=2)
min    = input(10 ,'Minimum Length',minval=2)
value  = input(10 ,'Step',minval=1) 
src    = input(close)

r_dist = input(false,'Normalized Change Mode' 
  ,group='Style Settings')
  
dash_loc = input("Top Right","Dashboard Location"
  ,options=["Top Right","Bottom Right","Top Left","Bottom Left"]
  ,group='Style Settings')

text_size = input('Small',"Dashboard Size"
  ,options=["Tiny","Small","Normal","Large"]
  ,group='Style Settings')
  
cell_up = input(#2157f3,'Bullish Cell Color'
  ,group='Style Settings')

cell_dn = input(#ff1100,'Bearish Cell Color'
  ,group='Style Settings')

txt_col = input(color.gray,'Text/Frame Color'
  ,group='Style Settings')
  
  
  
cell_transp = input(50,'Cell Transparency'
  ,minval=0
  ,maxval=100
  ,group='Style Settings')
//----
var color sma_bgcolor = na
var color tma_bgcolor = na
var color wma_bgcolor = na
var color reg_bgcolor = na
var string sma_txt = na
var string tma_txt = na
var string wma_txt = na
var string reg_txt = na
//----
csum_a = cum(src)
csum_b = cum(csum_a)
//----
sma_array = array.new_float(0)
tma_array = array.new_float(0)
wma_array = array.new_float(0)
reg_array = array.new_float(0)

var table_position = dash_loc == 'Top Left' ? position.top_left :
  dash_loc == 'Bottom Left' ? position.bottom_left :
  dash_loc == 'Top Right' ? position.top_right : position.bottom_right
  
var table_text_size = text_size == 'Tiny' ? size.tiny :
  text_size == 'Small' ? size.small :
  text_size == 'Normal' ? size.normal : size.large

var main_table = table.new(table_position,5,abs(max-min)+2,
  frame_color=txt_col,
  frame_width=1,
  border_color=txt_col,
  border_width=1)
  
if barstate.isfirst and max > min
    table.cell(main_table,1,0,'SMA',text_color=txt_col,text_size=table_text_size)
    table.cell(main_table,2,0,'TMA',text_color=txt_col,text_size=table_text_size)
    table.cell(main_table,3,0,'WMA',text_color=txt_col,text_size=table_text_size)
    table.cell(main_table,4,0,'REG',text_color=txt_col,text_size=table_text_size)
    for i = 0 to (max-min) by value
        length = min + i
        table.cell(main_table,0,i+1,tostring(length),text_color=txt_col,text_size=table_text_size)
else
    table.cell(main_table,0,0,'"Maximum Length" setting \n must be higher than "Minimum Length" setting',text_color=txt_col,text_size=table_text_size)
//----
if barstate.islast and max > min
    inc = 0
    per = 0.
    for i = 0 to (max-min) by value
        length = min + i
        sum_a = csum_a[1] - csum_a[length+1]
        sum_b = csum_b[1] - csum_b[length+1]
        tma = (csum_a - csum_a[length])/length - (csum_a - csum_a[length*2])/(length*2)
        wma = (length*csum_a - sum_b)/(length*(length+1)/2)
        array.push(sma_array,src-src[length])
        array.push(tma_array,tma)
        array.push(wma_array,src - sum_a/length)
        array.push(reg_array,wma - (csum_a - csum_a[length])/length)
        //----
    for i = 0 to (max-min) by value
        sma_get = array.get(sma_array,inc)
        tma_get = array.get(tma_array,inc)
        wma_get = array.get(wma_array,inc)
        reg_get = array.get(reg_array,inc)
        if r_dist
            sma_norm = (sma_get-array.min(sma_array))/array.range(sma_array)
            tma_norm = (tma_get-array.min(tma_array))/array.range(tma_array)
            wma_norm = (wma_get-array.min(wma_array))/array.range(wma_array)
            reg_norm = (reg_get-array.min(reg_array))/array.range(reg_array)
            sma_bgcolor := color.from_gradient(sma_norm,0,1,cell_dn,cell_up)
            tma_bgcolor := color.from_gradient(tma_norm,0,1,cell_dn,cell_up)
            wma_bgcolor := color.from_gradient(wma_norm,0,1,cell_dn,cell_up)
            reg_bgcolor := color.from_gradient(reg_norm,0,1,cell_dn,cell_up)
            sma_txt := tostring(sma_norm,'#.##')
            tma_txt := tostring(tma_norm,'#.##')
            wma_txt := tostring(wma_norm,'#.##')
            reg_txt := tostring(reg_norm,'#.##')
        else 
            sma_bgcolor := sma_get > 0 ? cell_up : cell_dn
            tma_bgcolor := tma_get > 0 ? cell_up : cell_dn
            wma_bgcolor := wma_get > 0 ? cell_up : cell_dn
            reg_bgcolor := reg_get > 0 ? cell_up : cell_dn
            sma_txt := ''
            tma_txt := ''
            wma_txt := ''
            reg_txt := ''
        per += sign(sma_get)+sign(tma_get)+sign(wma_get)+sign(reg_get)
        table.cell(main_table,1,i+1,sma_txt,text_color=txt_col,text_size=table_text_size,bgcolor=color.new(sma_bgcolor,cell_transp))
        table.cell(main_table,2,i+1,tma_txt,text_color=txt_col,text_size=table_text_size,bgcolor=color.new(tma_bgcolor,cell_transp))
        table.cell(main_table,3,i+1,wma_txt,text_color=txt_col,text_size=table_text_size,bgcolor=color.new(wma_bgcolor,cell_transp))
        table.cell(main_table,4,i+1,reg_txt,text_color=txt_col,text_size=table_text_size,bgcolor=color.new(reg_bgcolor,cell_transp))
        inc += 1
    table.cell(main_table,0,0,str.format('{0,number,percent}',.5*(per/(inc*4))+.5),text_color=txt_col,text_size=table_text_size,
      bgcolor=color.from_gradient(.5*(per/(inc*4))+.5,0,1,color.new(cell_dn,cell_transp),color.new(cell_up,cell_transp)))