// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Cubic Bézier Curve Extrapolation [LuxAlgo]",overlay=true,max_lines_count=500)
length = input(20,'Extrapolation Length')
src    = input(close,'Source')

width = input(1,group='Style')
up = input.color(#0cb51a,'Colors',group='Style',inline='inline1')
dn = input.color(#ff1100,'',group='Style',inline='inline1')

a = input.time(0,'P1',confirm=true,group='Anchor Points',inline='a')
a_y = input.price(0,'P1 Value',confirm=true,group='Anchor Points',inline='a')

b = input.time(0,'P2',confirm=true,group='Anchor Points',inline='b')
b_y = input.price(0,'P2 Value',confirm=true,group='Anchor Points',inline='b')

c = input.time(0,'P3',confirm=true,group='Anchor Points',inline='c')
c_y = input.price(0,'P3 Value',confirm=true,group='Anchor Points',inline='c')

d = input.time(0,'P4',confirm=true,group='Anchor Points',inline='d')
d_y = input.price(0,'P4 Value',confirm=true,group='Anchor Points',inline='d')
//----
n = bar_index
var a_x = 0
var b_x = 0
var c_x = 0
var d_x = 0
//----
if time == a
    a_x := n
if time == b
    b_x := n
    line.new(a,a_y,b,b_y,xloc=xloc.bar_time,color=color.gray)
if time == c
    c_x := n
    line.new(b,b_y,c,c_y,xloc=xloc.bar_time,color=color.gray)
if time == d
    d_x := n
    line.new(c,c_y,d,d_y,xloc=xloc.bar_time,color=color.gray)
//----
diff = d_x - a_x
var float y1 = na
var float y2 = na
if time == math.max(a,b,c,d)
    for i = 0 to diff+length
        k = i/diff
        y2 := a_y*math.pow(1 - k,3) + 3*b_y*math.pow(1 - k,2)*k + 3*c_y*(1 - k)*math.pow(k,2) + d_y*math.pow(k,3)
        css = y2 > y1 ? up : dn
        line.new(n-diff+i,y2,n-diff+i-1,y1,color=css,style=i > diff ? line.style_dotted : line.style_solid,width=width)
        y1 := y2