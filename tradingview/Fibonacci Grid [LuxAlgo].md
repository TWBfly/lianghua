// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator('Fibonacci Grid [LuxAlgo]', 'LuxAlgo - Fibonacci Grid', overlay = true, max_bars_back = 2000, max_lines_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
N = input.int(4, 'Resolution', maxval=10)
fib = input(true, 'Use Fibonacci Ratios')
src = input(close)

//Style
upCss = input.color(#2157f3, 'Lines Colors', group = 'Style', inline='lcol')
midCss = input.color(#ff5d00, '', group = 'Style', inline='lcol')
dnCss = input.color(#ff1100, '', group = 'Style', inline='lcol')

showArea = input.bool(true, 'Evaluation Area',group='Style', inline='area')
uptrendCss = input.color(color.new(#2157f3, 80), '',group='Style', inline='area')
dntrendCss = input.color(color.new(#ff1100, 80), '',group='Style', inline='area')

ext = input(true, 'Extend Diagonal Lines')

x1 = input.time(0, confirm = true)
x2 = input.time(0, confirm = true)

//-----------------------------------------------------------------------------}
//Function
//-----------------------------------------------------------------------------{
Line(l, x1, y1, x2, y2, css, extend) =>
    line.set_xy1(l, x1, y1)
    line.set_xy2(l, x2, y2)
    line.set_color(l, css)
    line.set_extend(l, extend)
    l

//-----------------------------------------------------------------------------}
//Calculations
//-----------------------------------------------------------------------------{
var ratios = array.from(0.236, 0.382, 0.5, 0.618, 0.786, 1.)
var float max = na
var float min = na
var X1 = 0
var X2 = 0

n = bar_index

if time == x1
    max := src
    min := src
    X1 := n
else if time <= x2
    max := math.max(src, max)
    min := math.min(src, min)
    X2 := n

//-----------------------------------------------------------------------------}
//Display lines
//-----------------------------------------------------------------------------{
if time == x2
    length = X2 - X1
    css = src > math.avg(max, min) ? uptrendCss : dntrendCss

    if showArea
        box.new(x1, max, x2, min, na, xloc = xloc.bar_time, bgcolor = color.new(css, 80))
    
    k = 0.
    size = fib ? array.size(ratios) : N
    
    //Loops trough ratios
    for i = 0 to size - 1
        if fib
            k := array.get(ratios, i)
        else
            k += 1 / N
            
        upcol = color.from_gradient(i, 0, size-1, midCss, upCss)
        dncol = color.from_gradient(i, 0, size-1, midCss, dnCss)

        //Set upward lines
        line.new(X2 - int(k * length), min, X2, k * max + (1 - k) * min
          , color = color.from_gradient(i, 0, size-1, upCss, midCss)
          , extend = ext ? extend.right : extend.none)
        
        line.new(X1 + int(k * length), max, X1, k * min + (1 - k) * max
          , color = color.from_gradient(i, 0, size-1, upCss, midCss)
          , extend = ext ? extend.left : extend.none)
        
        //Set downward lines
        line.new(X2 - int(k * length), max, X2, k * min + (1 - k) * max
          , color = color.from_gradient(i, 0, size-1, dnCss, midCss)
          , extend = ext ? extend.right : extend.none)
        
        line.new(X1 + int(k * length), min, X1, k * max + (1 - k) * min
          , color = color.from_gradient(i, 0, size-1, dnCss, midCss)
          , extend = ext ? extend.left : extend.none)

//-----------------------------------------------------------------------------}