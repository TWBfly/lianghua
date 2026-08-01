// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Squeeze Index [LuxAlgo]", "Squeeze Index [LuxAlgo]")
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
conv   = input(50, 'Convergence Factor')

length = input(20)

src = input(close)

//Style
col_0 = input(#ffeb3b, 'Gradient'
  , inline = 'inline0'
  , group = 'Style')
  
col_1 = input(#ff5d00, ''
  , inline = 'inline0'
  , group = 'Style')
  
col_2 = input(#ff1100, ''
  , inline = 'inline0'
  , group = 'Style')

//-----------------------------------------------------------------------------}
//Squeeze index
//-----------------------------------------------------------------------------{
var max = 0.
var min = 0.

max := nz(math.max(src, max - (max - src) / conv), src)
min := nz(math.min(src, min + (src - min) / conv), src)
diff = math.log(max - min)

psi = -50 * ta.correlation(diff, bar_index, length) + 50

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
css1 = color.from_gradient(psi, 0, 80, col_0, col_1)
css2 = color.from_gradient(psi, 80, 100, css1, col_2)

plot_0 = plot(psi, 'PSI', psi > 80 ? na : css2)
plot(psi, 'Dots', psi > 80 ? css2 : na, style = plot.style_cross)

plot_1 = plot(80, display = display.none, editable = false)

fill(plot_0, plot_1, psi < 80 ? na : color.new(#ff1100, 80))

hline(80)

//-----------------------------------------------------------------------------}