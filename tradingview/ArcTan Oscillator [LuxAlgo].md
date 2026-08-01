// This source code is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=4
study("ArcTan Oscillator","ATO [LuxAlgo]")
length = input(21)
pg     = input(0,"Pre-Gain [-10,10]",minval=-10,maxval=10)
src    = input(close,"Source")
//----
grad(os) => os < 10 ? #ff1100 : max(os,10) < 20 ? #d12033 :
  max(os,20) < 30 ? #bd2649 : max(os,30) < 40 ? #a72d61 :
  max(os,40) < 50 ? #913479 : max(os,50) < 60 ? #743d99 :
  max(os,60) < 70 ? #5945b6 : max(os,70) < 80 ? #494ac7 :
  max(os,80) < 90 ? #3750db : #2157f3 
//----
ma = sma(src,length)
z = (ma - sma(ma,length))/stdev(ma,length)
os = atan(z*(pg <= 0 ? exp(pg) : pg*2))
cor = correlation(src,os,length) 
//----
plot(os,"Reversal Potential",color = grad((.5*cor+.5)*100)
  ,style=plot.style_area,transp=30)
plot(os,"Osc",#0a0032,2)