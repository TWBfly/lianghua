// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Linear Regression Fan [LuxAlgo]", "LuxAlgo - Linear Regression Fan", overlay = true, max_bars_back = 2000, max_lines_count = 500)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
mult    = input(2.)
N       = input.int(4,'Lines Per Side', minval = 0)
initPos = input.float(0.5, 'Initial Fan Position [0, 1]', minval = 0, maxval = 1)
src     = input(close)

//Style
showChannel = input(true, 'Show Channel')
up_col = input(#2157f3, 'Upper Colors', group = 'Style')
mid_col = input(#ff5d00, 'Basis', group = 'Style')
dn_col = input(#ff1100, 'Lower Colors', group = 'Style')

x1 = input.time(0, 'Left Coordinate', confirm = true)
x2 = input.time(0, 'Right Coordinate', confirm = true)

//-----------------------------------------------------------------------------}
//Populate X/Y arrays
//-----------------------------------------------------------------------------{
n = bar_index
var y = array.new<float>(0)
var x = array.new<int>(0)

if time >= x1 and time <= x2
    y.unshift(src)
    x.unshift(n)

//-----------------------------------------------------------------------------}
//Display Fan
//-----------------------------------------------------------------------------{
if time == x2
    //Get linreg coefficients and RMSE
    vx = x.variance()
    vy = y.variance()
    cov = y.covariance(x)
    
    a = cov / vx
    b = y.avg() - a * x.avg()
    dev = math.sqrt(vy - vy * math.pow(cov / (math.sqrt(vy) * math.sqrt(vx)), 2)) * mult

    //Get coordinates
    y1 = a*x.last() + b
    y2 = a*x.first() + b

    //Set linear regression channel
    if showChannel
        line.new(x1, y1 + dev, x2, y2 + dev, xloc.bar_time
          , color = up_col
          , style = line.style_dashed
          , extend = extend.right)

        line.new(x1, y1, x2, y2, xloc.bar_time
          , color = mid_col
          , extend = extend.right)

        line.new(x1, y1 - dev, x2, y2 - dev, xloc.bar_time
          , color = dn_col
          , style = line.style_dashed
          , extend = extend.right)

    //Set linear regression fan
    for i = 1 to N
        init = initPos * (y1 + dev) + (1 - initPos) * (y1 - dev)
        line.new(x1, init, x2, y2 + i/N * dev, xloc.bar_time
          , color = up_col
          , extend = extend.right)

        line.new(x1, init, x2, y2 - i/N * dev, xloc.bar_time
          , color = dn_col
          , extend = extend.right)

//-----------------------------------------------------------------------------}