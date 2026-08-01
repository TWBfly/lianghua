// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Circular Barplot - Oscillators Sentiment [LuxAlgo]",overlay=true,max_lines_count=500,scale=scale.none)
width     = input.int(50,step=10)
spacing   = input.float(4.,minval=1)
thickness = input.int(3)
offset    = input.int(10)
src       = input(close)

gradient  = input(false,inline='gradient')
grad_a    = input(#ff1100,'',inline='gradient')
grad_b    = input(#2157f3,'',inline='gradient')
grad_c    = input(#00bcd4,'',inline='gradient')
//----
rsi_len = input(14,'RSI     ',inline='inline1',group='Oscillators')
rsi_col = input(#ff1100,'',inline='inline1',group='Oscillators')

st_len = input(14,'%K     ',inline='inline1',group='Oscillators')
st_col = input(#ff5d00,'',inline='inline1',group='Oscillators')

r_len = input(14,'ROSC  ',inline='inline2',group='Oscillators')
r_col = input(#0cb51a,'',inline='inline2',group='Oscillators')

wpr_len = input(14,'WPR   ',inline='inline2',group='Oscillators')
wpr_col = input(#2157f3,'',inline='inline2',group='Oscillators')

pr_len = input(14,'%RANK',inline='inline3',group='Oscillators')
pr_col = input(#673ab7,'',inline='inline3',group='Oscillators')

mfi_len = input(14,'MFI    ',inline='inline3',group='Oscillators')
mfi_col = input(#e91e63,'',inline='inline3',group='Oscillators')
//------------------------------------------------------------------------------
n = bar_index+width+offset

lset(l,x1,y1,x2,y2,col,width)=>
    line.set_xy1(l,x1,y1)
    line.set_xy2(l,x2,y2)
    line.set_color(l,col)
    line.set_width(l,width)

var rsi_lines = array.new_line(0)
var st_lines = array.new_line(0)
var r_lines = array.new_line(0)
var wpr_lines = array.new_line(0)
var pr_lines = array.new_line(0)
var mfi_lines = array.new_line(0)

if barstate.isfirst
    for i = 0 to 360 by 10
        array.push(rsi_lines,line.new(na,na,na,na))
        array.push(st_lines,line.new(na,na,na,na))
        array.push(r_lines,line.new(na,na,na,na))
        array.push(wpr_lines,line.new(na,na,na,na))
        array.push(pr_lines,line.new(na,na,na,na))
        array.push(mfi_lines,line.new(na,na,na,na))

l(Line,r,len,col_a,col_b,width_a,width_b)=>
    int prev_x = na
    float prev_y = na
    nl = 0
    for i = 0 to 360 by 10
        x = r*math.sin(math.toradians(i))
        y = r*math.cos(math.toradians(i))
        
        css = gradient ? color.from_gradient(i,180,360,color.from_gradient(i,0,180,grad_a,grad_b),grad_c) : col_a
        
        lset(array.get(Line,nl),prev_x,prev_y,n+math.round(x),y,
          i > len ? col_b : css,
          i > len ? width_b : width_a)
        
        prev_x := n+math.round(x)
        prev_y := y
        
        nl += 1
//------------------------------------------------------------------------------
rsi   = ta.rsi(src,rsi_len)
angle_rsi = math.round(rsi/100*360)

stoch = ta.stoch(src,src,src,st_len)
angle_stoch = math.round(stoch/100*360)

rosc = ta.correlation(src,n,r_len)
angle_rosc  = math.round((.5*rosc+.5)*360)

wpr = ta.wpr(wpr_len)
angle_wpr   = math.round((wpr/100 + 1)*360)

pr = ta.percentrank(src,pr_len)
angle_pr = math.round(pr/100*360)

mfi = ta.mfi(src,mfi_len)
angle_mfi = math.round(mfi/100*360)
//------------------------------------------------------------------------------
var tb = table.new(position.top_right,2,6)
if barstate.islast
    //Circular Plot
    l(rsi_lines,width,angle_rsi,rsi_col,color.gray,thickness,1)
    l(st_lines,width-spacing,angle_stoch,st_col,color.gray,thickness,1)
    l(r_lines,width-spacing*2,angle_rosc,r_col,color.gray,thickness,1)
    l(wpr_lines,width-spacing*3,angle_wpr,wpr_col,color.gray,thickness,1)
    l(pr_lines,width-spacing*4,angle_pr,pr_col,color.gray,thickness,1)
    l(mfi_lines,width-spacing*5,angle_mfi,mfi_col,color.gray,thickness,1)
    
    //Center Labels
    avg = math.avg(angle_rsi,angle_stoch,angle_rosc,angle_wpr,angle_pr,angle_mfi)/3.6
    
    avg_css = gradient ? color.from_gradient(avg,50,100,color.from_gradient(avg,0,50,grad_a,grad_b),grad_c) : color.gray
    
    label.delete(label.new(n,0,str.tostring(avg,'#.##')+'%',color=avg_css,
      style=label.style_label_center,textcolor=color.white,textalign=text.align_center,size=size.normal)[1])
    
    //Table Cells
    table.cell(tb,0,0,'1 - RSI',text_color=color.white,bgcolor=rsi_col,text_halign=text.align_left)
    table.cell(tb,0,1,'2 - %K',text_color=color.white,bgcolor=st_col,text_halign=text.align_left)
    table.cell(tb,0,2,'3 - ROSC',text_color=color.white,bgcolor=r_col,text_halign=text.align_left)
    table.cell(tb,0,3,'4 - WPR',text_color=color.white,bgcolor=wpr_col,text_halign=text.align_left)
    table.cell(tb,0,4,'5 - %RANK',text_color=color.white,bgcolor=pr_col,text_halign=text.align_left)
    table.cell(tb,0,5,'6 - MFI',text_color=color.white,bgcolor=mfi_col,text_halign=text.align_left)
    
    table.cell(tb,1,0,str.tostring(rsi,'#.##'),text_color=color.white,bgcolor=rsi_col)
    table.cell(tb,1,1,str.tostring(stoch,'#.##'),text_color=color.white,bgcolor=st_col)
    table.cell(tb,1,2,str.tostring(rosc,'#.##'),text_color=color.white,bgcolor=r_col)
    table.cell(tb,1,3,str.tostring(wpr,'#.##'),text_color=color.white,bgcolor=wpr_col)
    table.cell(tb,1,4,str.tostring(pr,'#.##'),text_color=color.white,bgcolor=pr_col)
    table.cell(tb,1,5,str.tostring(mfi,'#.##'),text_color=color.white,bgcolor=mfi_col)
