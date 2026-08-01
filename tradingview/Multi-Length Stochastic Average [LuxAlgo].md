// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=4
study("Multi-Length Stochastic Average [LuxAlgo]")
length      = input(14)
source      = input(close)
presmooth   = input(10,'Pre-Smoothing'
  ,inline='presmooth')
premethod   = input('SMA','',options=['None','SMA','TMA','LSMA']
  ,inline='presmooth')
postsmooth  = input(10,'Post-Smoothing'
  ,inline='postsmooth')
postmethod  = input('SMA','',options=['None','SMA','TMA','LSMA']
  ,inline='postsmooth')
//----
ma(x,k,order) => 
    if order == 'SMA'
        sma(x,k)
    else if order == 'TMA'
        sma(sma(x,k),k)
    else if order == 'LSMA'
        linreg(x,k,0)
    else
        x
//----
src = ma(source,presmooth,premethod)
var weight = array.new_float(0)
prices = array.new_float(0)
//----
avg = 0.
for i = 0 to length-1
    array.push(prices,src[i])
for i = 4 to length
    slice = array.slice(prices,0,i)
    avg += (src-array.min(slice))/(array.max(slice)-array.min(slice))
norm = avg/(length-3)*100
sta = ma(norm,postsmooth,postmethod)
//----
css =  sta > sta[1] ? #39FF11 : sta < sta[1] ? #FF3131 : na
plot = plot(sta,"Plot",fixnan(css),2)
up = plot(80,"Plot",color.gray)
dn = plot(20,"Plot",color.gray)
//----
fill(plot,up,sta > 80 ? #FF3131 : na,50)
fill(plot,dn,sta < 20 ? #39FF11 : na,50)
//----
plot(crossunder(sta,80) ? 80 : crossover(sta,20) ? 20 : na,'Circles',css,3,plot.style_circles)