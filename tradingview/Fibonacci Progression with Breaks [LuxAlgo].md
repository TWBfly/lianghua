// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Fibonacci Progression With Breaks [LuxAlgo]",overlay=1,max_labels_count=500,max_lines_count=500)
method = input.string('Atr',options=['Atr','Manual'],inline='inline1')
size   = input(1.,'',inline='inline1')
max    = input(3,'Sequence Length')
//----
var fib = array.from(1,1)
var dist = 0.,var avg = 0.,var fib_n = 1,var os = 0

src = close
n = bar_index

if barstate.isfirst
    for i = 1 to max
        array.push(fib,array.get(fib,i-1) + array.get(fib,i))
//----
if method == 'Atr'
    dist := ta.atr(200)*size*array.get(fib,fib_n)
else
    dist := size*array.get(fib,fib_n)

fib_n := math.abs(src-avg) > dist ? fib_n+1 : fib_n
avg := nz(fib_n > max+1 ? src : avg[1],src)
fib_n := fib_n > max+1 ? 1 : fib_n

buy = avg > avg[1]
sell = avg < avg[1]
os := buy ? 1 : sell ? 0 : os

tp = avg != avg[1] ? na : os == 1 ? avg + dist : avg - dist
sl = avg != avg[1] ? na : os == 0 ? avg + dist : avg - dist
//----
css = os == 1 ? #0cb51a : #ff1100
plot0 = plot(src,color=na)
plot1 = plot(avg,color=na)
fill(plot0,plot1,color.new(css,80))
//----
plotshape(buy ? low : na,"Buy Label",shape.labelup,location.absolute,#0cb51a,0,text="B",textcolor=color.white,size=size.tiny)
plotshape(sell ? high : na,"Sell Label",shape.labeldown,location.absolute,#ff1100,0,text="S",textcolor=color.white,size=size.tiny)

plot(tp,'Target',#0cb51a,1,plot.style_linebr)
plot(sl,'Stop',#ff1100,1,plot.style_linebr)

if fib_n > fib_n[1] and os == 1 and src > avg
    label.new(n,src,str.tostring(array.get(fib,fib_n-1)) + ' ✅',yloc=yloc.abovebar
      ,color=na,style=label.style_label_down,textcolor=color.gray,size=size.small)
else if fib_n > fib_n[1] and os == 1 and src < avg
    label.new(n,src,str.tostring(array.get(fib,fib_n-1)) + ' ❌',yloc=yloc.belowbar
      ,color=na,style=label.style_label_up,textcolor=color.gray,size=size.small)

if fib_n > fib_n[1] and os == 0 and src < avg
    label.new(n,src,str.tostring(array.get(fib,fib_n-1)) + ' ✅',yloc=yloc.belowbar
      ,color=na,style=label.style_label_up,textcolor=color.gray,size=size.small)
else if fib_n > fib_n[1] and os == 0 and src > avg
    label.new(n,src,str.tostring(array.get(fib,fib_n-1)) + ' ❌',yloc=yloc.abovebar
      ,color=na,style=label.style_label_down,textcolor=color.gray,size=size.small)
