// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// Â© LuxAlgo

//@version=5
indicator("SAR Oscillator [LuxAlgo]")
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
acc = input.float(0.01, 'Acceleration'
  , minval = 0
  , maxval = 1
  , step   = .01)

inc = input.float(0.02, 'Increment'
  , minval = 0
  , maxval = 1
  , step   = .01)

lim = input.float(0.20, 'Maximum'
  , minval = 0
  , maxval = 1
  , step   = .1)

//Style
np_css    = input.color(#2157f3, 'Normalized Price'
  , group = 'Colors')

sp_css    = input.color(#ffe400, 'Normalized SAR'
  , group = 'Colors')

fill_css_0 = input.color(color.new(#FF0000, 0), 'Fill Gradient'
  , inline = 'inline0'
  , group = 'Colors')

fill_css_1 = input.color(color.new(#FFFF00, 80), ''
  , inline = 'inline0'
  , group = 'Colors')

fill_css_2 = input.color(color.new(#39FF14, 0), ''
  , inline = 'inline0'
  , group = 'Colors')

//-----------------------------------------------------------------------------}
//Calculation
//-----------------------------------------------------------------------------{
var max = 0.
var min = 0.

sar = ta.sar(acc, inc, lim)
cross = ta.cross(close, sar)

max := cross ? math.max(high, sar) : math.max(high, max)
min := cross ? math.min(low, sar) : math.min(low, min)

posc = ((close - sar) / (max - min) * 100)*-1
sosc = (((sar - min) / (max - min) - .5) * -200)*-1

//-----------------------------------------------------------------------------}
//Plot
//-----------------------------------------------------------------------------{
gradient_0 = color.from_gradient(sosc, -100, 0, fill_css_0, fill_css_1)
gradient_1 = color.from_gradient(sosc, 0, 100, gradient_0, fill_css_2)

plot_0 = plot(posc, 'Normalized Price'
  , color = np_css)

plot_1 = plot(sosc, 'Normalized SAR'
  , color = sp_css)
  
plot(cross ? sosc : na, 'SAR Dots'
  , color = sosc == -100 ? fill_css_2 : fill_css_0
  , style = plot.style_circles
  , linewidth = 4)

fill(plot_0, plot_1, gradient_1)

hline(50)
hline(-50)