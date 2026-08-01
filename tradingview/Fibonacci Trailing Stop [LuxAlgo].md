// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Fibonacci Trailing Stop [LuxAlgo]", "LuxAlgo - Fibonacci Trailing Stop", max_lines_count=500, max_labels_count=500, overlay=true)

//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
L = input.int   (       20    ,              'L'           ,             group=        'swings'         ,  minval=                           1                            ) 
R = input.int   (       1     ,              'R'           ,             group=        'swings'         ,  minval=                           1                            ) 
lb= input.bool  (     false   , '            Swings labels',             group=        'swings'                                                                           )
F = input.float (    -0.382   ,        'Level       '      , inline='_', group='Fibonacci Trailing Stop', options=  [-0.5, -0.382, -0.236 ,  0, 0.236, 0.382, 0.5, 0.618] )
i = input.bool  (     false   ,               ''           , inline='_', group='Fibonacci Trailing Stop'                                                                  ) 
f = input.float (     1.618   ,               ''           , inline='_', group='Fibonacci Trailing Stop',   step =                        0.001                           )
c = input.string(    'close'  ,           'Trigger'        ,             group='Fibonacci Trailing Stop', options=                ['close', 'wick']                       )                                                 
cU= input.color (  #089981  ,      '                  '  , inline='c', group='Fibonacci Trailing Stop'                                                                  )
cD= input.color (  #f23645  ,               ''           , inline='c', group='Fibonacci Trailing Stop'                                                                  )
sF= input.bool  (     true    , '         Latest Fibonacci',             group=       'Fibonacci'                                                                         )
F0= input.color (#08998164  ,          '           '     , inline='f', group=       'Fibonacci'                                                                         )
Fm= input.color (#1e42b070  ,               ''           , inline='f', group=       'Fibonacci'                                                                         )
F1= input.color (#f2364564  ,               ''           , inline='f', group=       'Fibonacci'                                                                         )
fl= input.bool  (    true     ,  '              Shadows'                                                                                                                  )

Ls= math.max(1, math.ceil(L / 2))
Rs= math.max(1, math.ceil(R / 2))

n = bar_index 

iF=i ? f : F 

//-----------------------------------------------------------------------------}
//User Defined Types
//-----------------------------------------------------------------------------{
type piv 
    int   b 
    float p
    int   d 
    label l

type fib 
    linefill lf_0
    linefill lfMd
    linefill lf_1
    line     ln_0_5 
    line     diagon

//-----------------------------------------------------------------------------}
//Variables
//-----------------------------------------------------------------------------{
var int     dir      = 0
var float   st       = close
var float   max      = high
var float   min      = low
var float   dif      = na
var float other_side = na

var piv[] pivs = array.new<piv>() 

var fib fib  = fib.new(
   lf_0 = linefill.new( 
       line       .new(na, na, na, na, color=sF ? F0 : color.new(color.blue, 100))
     , line       .new(na, na, na, na, color=sF ? F0 : color.new(color.blue, 100))
     , color      .new(F0            ,       fl ? 100:                          85)
     ),
   lfMd = linefill.new( 
       line       .new(na, na, na, na, color=sF ? Fm : color.new(color.blue, 100))
     , line       .new(na, na, na, na, color=sF ? Fm : color.new(color.blue, 100))
     , color      .new(Fm            ,       fl ? 100:                          85)
     ),
   lf_1 = linefill.new( 
       line       .new(na, na, na, na, color=sF ? F1 : color.new(color.blue, 100))
     , line       .new(na, na, na, na, color=sF ? F1 : color.new(color.blue, 100))
     , color      .new(F1            ,       fl ? 100:                          85)
     ),     
   ln_0_5  =  line.new(na, na, na, na, color=sF ? color.blue   : color.new(color.blue, 100)),
   diagon  =  line.new(na, na, na, na, color=sF ? color.silver : color.new(color.blue, 100) 
           ,                           style=       line.style_dashed                         ))

var line_0 =  line.new(na, na, na, na)
var line_1 =  line.new(na, na, na, na)

//-----------------------------------------------------------------------------}
//Function
//-----------------------------------------------------------------------------{
flab(i, x, y) => label.new(x, y, style=i == 1 ? label.style_label_down : label.style_label_up, color=color.gray)

//-----------------------------------------------------------------------------}
//Execution
//-----------------------------------------------------------------------------{
ph = ta.pivothigh(L , R )
pl = ta.pivotlow (L , R )

ph_= ta.pivothigh(Ls, Rs) // used for fill ~ ST
pl_= ta.pivotlow (Ls, Rs) // used for fill ~ ST

if ph
    if pivs.size() > 0 
        get = pivs.first() 
        if get.d > 0 and ph > get.p
            get.b :=  n  -R
            get.p := high[R]
            get.l.set_xy(n -R, high[R])
        if get.d < 0 and ph > get.p
            pivs.unshift(piv.new(n -R, high[R] , 1, lb ? flab( 1, n -R, high[R]) : na))
    else 
        pivs    .unshift(piv.new(n -R, high[R] , 1, lb ? flab( 1, n -R, high[R]) : na))
    
if pl
    if pivs.size() > 0 
        get = pivs.first() 
        if get.d < 0 and pl < get.p
            get.b :=  n  -R
            get.p := low [R]                   
            get.l.set_xy(n -R, low [R])
        if get.d > 0 and pl < get.p
            pivs.unshift(piv.new(n -R, low [R] ,-1, lb ? flab(-1, n -R, low [R]) : na))            
    else
        pivs    .unshift(piv.new(n -R, low [R] ,-1, lb ? flab(-1, n -R, low [R]) : na))

if pivs.size() >= 2
    max := math.max(pivs.first().p, pivs.get(1).p)
    min := math.min(pivs.first().p, pivs.get(1).p)
    if pivs.size() == 2
        st         := math.avg(max, min)
        other_side := math.avg(max, min)
    dif := max - min 
    max += dif * iF 
    min -= dif * iF 

    _0i       =                    pivs.first( ).b, _0p = pivs.first( ).p
    _1i       =                    pivs.get  (1).b, _1p = pivs.get  (1).p 
    d         =                           _0p < _1p ? -dif : dif 

    l0_1      =        fib.   lf_0.get_line1(), l0_2      =            fib.   lf_0.get_line2()
    lMd1      =        fib.   lfMd.get_line1(), lMd2      =            fib.   lfMd.get_line2()
    l1_1      =        fib.   lf_1.get_line1(), l1_2      =            fib.   lf_1.get_line2()

    if (ph or pl) and (sF or fl)
        l0_1      .set_xy1(_0i, _0p              ), l0_1      .set_xy2( n + 3 , _0p              )
        l0_2      .set_xy1(_0i, _0p - (d * 0.236)), l0_2      .set_xy2( n + 3 , _0p - (d * 0.236))
        lMd1      .set_xy1(_0i, _0p - (d * 0.382)), lMd1      .set_xy2( n + 3 , _0p - (d * 0.382))
        lMd2      .set_xy1(_0i, _0p - (d * 0.618)), lMd2      .set_xy2( n + 3 , _0p - (d * 0.618))
        l1_1      .set_xy1(_0i, _0p - (d * 0.786)), l1_1      .set_xy2( n + 3 , _0p - (d * 0.786))
        l1_2      .set_xy1(_0i, _1p              ), l1_2      .set_xy2( n + 3 , _1p              )
        fib.ln_0_5.set_xy1(_0i, _0p - (d * 0.5  )), fib.ln_0_5.set_xy2( n + 3 , _0p - (d * 0.5  ))
        fib.diagon.set_xy1(_0i, _0p              ), fib.diagon.set_xy2(_1i    , _1p              )
    else 
        l0_1      .set_x2 ( n + 3 )
        l0_2      .set_x2 ( n + 3 )
        lMd1      .set_x2 ( n + 3 )
        lMd2      .set_x2 ( n + 3 )
        l1_1      .set_x2 ( n + 3 )
        l1_2      .set_x2 ( n + 3 )
        fib.ln_0_5.set_x2 ( n + 3 )

price = c == 'close' ? close : dir < 1 ? high : low 

if dir <  1
    if price > st 
        st := min 
        dir :=  1
    else 
        st := math.min(st, max)

if dir > -1
    if price < st 
        st := max 
        dir := -1        
    else 
        st := math.max(st, min)

col = dir < 1 ? cD : cU

other_side := switch 
    dir <  1 and ph_ => math.min(other_side, ph_, st) 
    dir <  1         => math.min(other_side     , st) 
    dir > -1 and pl_ => math.max(other_side, pl_, st)    
    dir > -1         => math.max(other_side     , st)
    =>                           other_side

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot0    = fib.lf_0.get_line1().get_y2() 
plot_236 = fib.lf_0.get_line2().get_y2() 
plot_382 = fib.lfMd.get_line1().get_y2() 
plot_500 = fib.ln_0_5          .get_y2()
plot_618 = fib.lfMd.get_line2().get_y2() 
plot_786 = fib.lf_1.get_line1().get_y2() 
plot1    = fib.lf_1.get_line2().get_y2() 

ch = ta.change(plot0) or ta.change(plot1) // when lines change
p1 = plot(not ch ? plot0    : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)
p2 = plot(not ch ? plot_236 : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)
p3 = plot(not ch ? plot_382 : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)
p4 = plot(not ch ? plot_618 : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)
p5 = plot(not ch ? plot_786 : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)
p6 = plot(not ch ? plot1    : na, color=color.new(color.blue, 100), style=plot.style_circles, display=display.none)

fill(p1, p2, ch or not fl ? na : math.avg(plot0, plot_236), plot_236,     color.new(chart.bg_color, 100), F0)
fill(p3, p4, ch or not fl ? na : plot_382                 , plot_500, Fm, color.new(chart.bg_color, 100)    )
fill(p3, p4, ch or not fl ? na : plot_500                 , plot_618,     color.new(chart.bg_color, 100), Fm)
fill(p5, p6, ch or not fl ? na : math.avg(plot1, plot_786), plot_786,     color.new(chart.bg_color, 100), F1)

s = plot(     st             , 'Fib Trailing Stop', color=          col            , display=display.pane + display.data_window)
o = plot(fl ? na : other_side,    'other side'    , color=color.new(col       , 75), display=display.pane + display.data_window)
fill    ( o ,  s , color=color.new(col, 90))

//-----------------------------------------------------------------------------}
//Alerts
//-----------------------------------------------------------------------------{
alertcondition(ta.change(dir) and dir ==  1,    'Uptrend'  ,    'Uptrend'  )
alertcondition(ta.change(dir) and dir == -1,   'Downtrend' ,   'Downtrend' )
alertcondition(ta.change(dir)              , 'Trend change', 'Trend change')

//-----------------------------------------------------------------------------}