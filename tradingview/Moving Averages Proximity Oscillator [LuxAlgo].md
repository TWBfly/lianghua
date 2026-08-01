// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Moving Averages Proximity Oscillator [LuxAlgo]", "MAPO [LuxAlgo]")
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
min = input.int(10, "Minimum Length"
  , minval = 1)

max = input.int(100, "Maximum Length"
  , minval = 1)

smooth = input.int(9
  , minval = 1)

normalized = input(true)

src = input(close)

//-----------------------------------------------------------------------------}
//Calculations
//-----------------------------------------------------------------------------{
csum = ta.cum(src)

len = 0.
per = 0.
max_min = math.abs(src - (csum - csum[min]) / min)

for i = min to max
    ma = (csum - csum[i])/i
    per += src > ma ? 1 : 0 
    
    ae = math.abs(src - ma)
    
    max_min := math.min(ae, max_min)
    len := ae == max_min ? i : len

len := ta.sma(len, smooth)
per := ta.sma(per, smooth)

if normalized
    len := (len - min) / (max - min + 1) * 100
    per := per / (max - min + 1) * 100
else
    per := per + min

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
var lvl = normalized ? 50 : (max + min + 1) / 2
var ob  = normalized ? 80 : 0.8 * max + 0.2 * min
var os  = normalized ? 20 : 0.8 * min + 0.2 * max

plot(per, "Price Above MA's"
  , color = per > lvl ? color.teal : color.red
  , transp = 50
  , style = plot.style_columns
  , histbase = lvl)

plot(len, "Proximity Index"
  , color = #5b9cf6)
  
hline(ob)
hline(os)

//-----------------------------------------------------------------------------}
