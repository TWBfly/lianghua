// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=4
study("Percentile Nearest Rank Using Arrays [LuxAlgo]",overlay=true)
length = input(15)
p      = input(50,"Percentage",minval=0,maxval=100)
src    = input(close)
//----
win = array.new_float(0)
for i = 0 to length-1
    array.push(win,src[i])
array.sort(win)
//----
index = round(p/100*length) - 1
pnr = array.remove(win,index)
//----
plot(pnr,"Plot",#ff1100,2)