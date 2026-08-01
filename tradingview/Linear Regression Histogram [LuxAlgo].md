// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Linear Regression Histogram [LuxAlgo]",overlay=true,max_lines_count=500,max_bars_back=500)
length = input.int(100,maxval=500)
bins   = input.int(10,'Bins Number')
mult   = input.float(2.)
src    = input(close)

show_hist = input(true,'Show Histogram',group='Style')
dn_col    = input.color(#ff1100,'Channel Color',group='Style',inline='channel')
up_col    = input.color(#2157f3,'',group='Style',inline='channel')
hist_col  = input.color(#ff5d00,'Histogram Bins Color',group='Style')
//----
var l_reg = array.new_line(0)
var l_hist = array.new_line(0)

lset(l,x1,y1,x2,y2,col)=>
    line.set_xy1(l,x1,y1)
    line.set_xy2(l,x2,y2)
    line.set_color(l,col)

if barstate.isfirst
    for i = 1 to bins
        array.push(l_reg,line.new(na,na,na,na))
        array.push(l_hist,line.new(na,na,na,na))
//----
n = bar_index
v = ta.variance(src,length)
r = ta.correlation(src,n,length) 

alpha = r*(math.sqrt(v)/ta.stdev(n,length))
beta = ta.sma(src,length) - alpha*ta.sma(n,length)

mad = math.sqrt(v - v*math.pow(r,2))*mult
//----
if barstate.islast
    a = alpha*(n-length+1) + beta - mad
    b = alpha*n + beta - mad
    
    for i = 0 to bins-2
        k = i/(bins-1)
        wmad = k*mad*2
        
        css = color.from_gradient(k,0,1,dn_col,up_col)
        lset(array.get(l_reg,i),n-length+1,a+wmad,n,b+wmad,css)
        
        if show_hist
            sum = 0.
            for j = 0 to length-1
                K = (i+1)/(bins-1)
                upper = alpha*(n-j) + beta - mad + (K*mad*2)
                lower = alpha*(n-j) + beta - mad + wmad
                sum := src[j] > lower and src[j] < upper ? sum + 1 : sum
                
            lset(array.get(l_hist,i),n,b+wmad,n+int(sum),b+wmad,hist_col)
    
    lset(array.get(l_reg,bins-1),n-length+1,a+mad*2,n,b+mad*2,up_col)
