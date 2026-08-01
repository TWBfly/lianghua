// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
 
//@version=5
indicator('Candle Body Support/Resistance [LuxAlgo]', shorttitle='LuxAlgo - Candle Body Support/Resistance', max_lines_count=500, max_labels_count=500, overlay=true)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
showLines =    input.string('Historical', 'Display Mode'                    , options=                  ['Trailing', 'Historical']                )
sup_perc  = 1-(input.float(50, 'Support %'           , minval=0, maxval=100 , tooltip='Percentage of the bullish candle body used for supports'   ) / 100)
res_perc  = 1-(input.float(50, 'Resistance %'        , minval=0, maxval=100 , tooltip='Percentage of the bearish candle body used for resistances') / 100)
lenATR    =    input.int  (20, 'Length ATR'                                 , group='Filter')
threshold =    input.float(2 , 'Volatility Threshold', minval=1, step=0.1   , group='Filter', tooltip= 'Multiplicative factor of the ATR')
maxBars   =    input.int  (500,  'Max Line Length'   , minval=1, maxval=4500, group='Filter')
lBull     =    input.color(#089981  ,    'Bull '   , inline= 'bull'       , group='Style' )
cBull     =    input.color(#089981bb,      ''      , inline= 'bull'       , group='Style' )
bBull     =    input.color(#08998125,      ''      , inline= 'bull'       , group='Style' , tooltip='Color {Line - Dot - Candle}')
lBear     =    input.color(#f23645  ,    'Bear'    , inline= 'bear'       , group='Style' )
cBear     =    input.color(#f23645bb,      ''      , inline= 'bear'       , group='Style' )
bBear     =    input.color(#f2364525,      ''      , inline= 'bear'       , group='Style' , tooltip='Color {Line - Dot - Candle}')
LabelSize = input.string('Small', 'Dot Size', options=['Tiny', 'Small', 'Normal', 'Large'])
LbSize    = LabelSize == 'Tiny' ? 3 :  LabelSize == 'Small' ? 4 :  LabelSize == 'Normal' ? 5 : 6, LabelSize := str.lower(LabelSize)

//---------------------------------------------------------------------------------------------------------------------}
//LuxAlgo Defined Type
//---------------------------------------------------------------------------------------------------------------------{
type sr 
    line ln 
    bool tg = false
    int  bx

//---------------------------------------------------------------------------------------------------------------------}
//Variables
//---------------------------------------------------------------------------------------------------------------------{
var linesBull   = array.new<sr>() 
var linesBear   = array.new<sr>() 

var float pBull = na
var float pBear = na

bool tBull = false
bool tBear = false

bool eBull = false
bool eBear = false

atr = ta.atr(lenATR)
INV = color(na)
n = bar_index 

//---------------------------------------------------------------------------------------------------------------------}
//Execution
//---------------------------------------------------------------------------------------------------------------------{
volCandle = math.abs(close - open) > nz(atr[1]) * threshold

if volCandle 
    switch close > open 
        true => 
            val = close - (close - open) * sup_perc 
            switch 
                showLines == 'Trailing' => pBull := val
                => linesBull.push(sr.new(line.new(n, val, n, val, color=lBull)))
        => 
            val = close + (open - close) * res_perc 
            switch 
                showLines == 'Trailing' => pBear := val 
                => linesBear.push(sr.new(line.new(n, val, n, val, color=lBear)))
else 
    if showLines == 'Trailing'
        if not na(pBull) 
            switch
                close < pBull                                    => eBull := true
                low   < pBull and open > pBull and close > pBull => tBull := true

        if not na(pBear) 
            switch 
                close > pBear                                    => eBear := true
                high  > pBear and open < pBear and close < pBear => tBear := true

if showLines == 'Historical'
    if linesBull.size() > 0 
        for i =  linesBull.size() -1 to 0 
            get = linesBull.get(i), y2 = get.ln.get_y2(), get.ln.set_x2(n)
            if low  < y2 and open > y2 and close > y2 
                label.new(n, y2, style=label.style_label_center, color=INV, text='●', textcolor=cBull, size=LabelSize)
                get.tg := true, get.bx := n

    if linesBear.size() > 0 
        for i =  linesBear.size() -1 to 0 
            get = linesBear.get(i), y2 = get.ln.get_y2(), get.ln.set_x2(n)
            if high > y2 and open < y2 and close < y2 
                label.new(n, y2, style=label.style_label_center, color=INV, text='●', textcolor=cBear, size=LabelSize)
                get.tg := true, get.bx := n

if showLines == 'Trailing'
    if not na(pBull) and close[1] < pBull[1]
        pBull := na

    if not na(pBear) and close[1] > pBear[1]
        pBear := na
else
    if linesBull.size() > 0 
        for i =   linesBull.size() -1 to 0 
            get = linesBull.get(i), get.ln.set_x2(n)
            tooFar = n - get.ln.get_x1() > maxBars
            if close < get.ln.get_y2() or tooFar
                removed = linesBull.remove(i)
                if not get.tg
                    removed.ln.delete() //if not tested, lines are deleted
                else 
                    if tooFar 
                        removed.ln.set_x2(get.bx) //set x2 to last test   

    if linesBear.size() > 0 
        for i =   linesBear.size() -1 to 0 
            get = linesBear.get(i), get.ln.set_x2(n) 
            tooFar = n - get.ln.get_x1() > maxBars
            if close > get.ln.get_y2() or tooFar
                removed = linesBear.remove(i)
                if not get.tg
                    removed.ln.delete()
                else 
                    if tooFar 
                        removed.ln.set_x2(get.bx)
            
//---------------------------------------------------------------------------------------------------------------------}
//Plot
//---------------------------------------------------------------------------------------------------------------------{
plot(pBull, "Bullish Trailing Stop", color=lBull, display=display.all - display.status_line, style=plot.style_linebr)
plot(pBear, "Bearish Trailing Stop", color=lBear, display=display.all - display.status_line, style=plot.style_linebr)

plot(tBull ? pBull : na, "Trailing Support Dot", color=cBull, style=plot.style_circles, display=display.all - display.status_line, linewidth=LbSize)
plot(tBear ? pBear : na, "Trailing Resistance Dot", color=cBear, style=plot.style_circles, display=display.all - display.status_line, linewidth=LbSize)

barcolor(volCandle ? close > open ? bBull : bBear : na)

//---------------------------------------------------------------------------------------------------------------------}