// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator('Half Cup [LuxAlgo]', shorttitle='LuxAlgo - Half Cup', max_labels_count = 500, max_polylines_count = 100, max_bars_back = 5000, overlay=true)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
m1 = 'Maximum % candles ', m2= ' the Half Cup', m3='Diagonal Shift of upper/lower part\nof the Half Cup'
left          = input.int  (20, 'Swing Length'       ,                                               minval=3              )
iBots         = input.int  (15, 'Max % Breaks Bottom',  group ='Validation' , tooltip=m1+'below'+m2, minval=0, maxval=100        )   / 100
iTops         = input.int  (15, 'Max % Breaks Tops'  ,  group ='Validation' , tooltip=m1+'above'+m2, minval=0, maxval=100              )   / 100
broadness     = input.int  (30,     '% Broadness'    ,  group ='Positioning', tooltip=m3           , minval=1, maxval=100                    )  / 100
verticalShift = input.int  (-10,   'Vertical Shift'  ,  group ='Positioning', tooltip='Moves the Half Cup up/down'                                 )  / 100 //% of height
lineLength    = input.int  (30  ,  'Channel Length'  ,  group ='Positioning'                       , minval=0                                            )
bull          = input.bool (true       ,  'Bull '    ,  group ='Style'      , inline='bull'                                                                    )
cBull         = input.color(#089981  ,    ''       ,  group ='Style'      , inline='bull', tooltip='1) Color Bullish Channel + Bullish Dots\n2) Bullish Colorfill')
cBullFill     = input.color(#08998120,    ''       ,  group ='Style'      , inline='bull'                                                                          )
bear          = input.bool (true       ,  'Bear'     ,  group ='Style'      , inline='bear'                                                                           )
cBear         = input.color(#f23645  ,    ''       ,  group ='Style'      , inline='bear', tooltip='1) Color Bearish Channel + Bearish Dots\n2) Bearish Colorfill' )
cBearFill     = input.color(#f2364520,    ''       ,  group ='Style'      , inline='bear'                                                                        )

//---------------------------------------------------------------------------------------------------------------------}
//LuxAlgo Defined Type
//---------------------------------------------------------------------------------------------------------------------{
type tester 
    array<chart.point>cpB
    array<chart.point>cpT
    int position = 0

//---------------------------------------------------------------------------------------------------------------------}
//Constants and general variables
//---------------------------------------------------------------------------------------------------------------------{
n   = bar_index
INV = color(na)
pi  = math.pi 
pi2 = pi / 2 

//---------------------------------------------------------------------------------------------------------------------}
//Variables
//---------------------------------------------------------------------------------------------------------------------{
var int lastPolyPhBix = 0
var polyline bull_poly = na, var polyline bull_polyTestB = na, var polyline bull_polyTestT = na
var array<label> bull_labsT = array.new<label>(), var array<label> bull_labsB = array.new<label>()
var tester bull_tester = tester.new(array.new<chart.point>(), array.new<chart.point>(), 0)

var int lastPolyPlBix = 0
var polyline bear_poly = na, var polyline bear_polyTestB = na, var polyline bear_polyTestT = na
var array<label> bear_labsT = array.new<label>(), var array<label> bear_labsB = array.new<label>()
var tester bear_tester = tester.new(array.new<chart.point>(), array.new<chart.point>(), 0)

//---------------------------------------------------------------------------------------------------------------------}
//Execution
//---------------------------------------------------------------------------------------------------------------------{
ph       = ta.pivothigh(left, 1)
vwPh_bix = ta.valuewhen(not na(ph), n-1, 0)
vwPh_prc = ta.valuewhen(not na(ph), ph , 0)

pl       = ta.pivotlow (left, 1)
vwPl_bix = ta.valuewhen(not na(pl), n-1, 0)
vwPl_prc = ta.valuewhen(not na(pl), pl , 0)

//Bullish
if bull and not na(pl) and pl < vwPh_prc
    //width & height of 'Half Cup'
    width  = n-1 - vwPh_bix //#bars
    height = vwPh_prc - pl //#price

    //Vertical Shift of pattern
    vwPh_prc += height * verticalShift

    //Shifts the pattern Top part diagonally
    partX = math.round(width * broadness)
    partY = height * broadness

    bottoms = array.new<chart.point>()
    tops    = array.new<chart.point>()
    testT   = array.new<chart.point>() 
    testB   = array.new<chart.point>() 

    testB_  = array.new<chart.point>() 

    countBots = 0, countTops = 0 

    maxBreaksBot = width * iBots
    maxBreaksTop = width * iTops

    xLast = n, yLast = 0., x_ = -1

    for i = 0 to width 
        //Make Quarter Circle (3rd quadrant)
        y =       vwPh_prc - ((height * math.sin(pi - (pi2 / width*i))))
        x = math.floor(n-1 + ((width  * math.cos(pi - (pi2 / width*i)))))

        x2 = x + partX
        y2 = y + partY
            
        if xLast > n -2
            diffX = x2 - xLast            
            diffY = y2 - yLast
            if diffX >= 1 
                for j = 1 to diffX
                    testT     .push(chart.point.from_index(xLast + j        , yLast + (diffY / diffX * j)       ))  
                    //Bottom Line before pl    
                    if xLast + j - partX < n 
                        testB_.push(chart.point.from_index(xLast + j - partX, yLast + (diffY / diffX * j) -partY))    
                    tops   .unshift(chart.point.from_index(xLast + j        , yLast + (diffY / diffX * j)       ))
            else 
                if x2 > n -1
                    testT.push(chart.point.from_index(x2, y2))           
                tops  .unshift(chart.point.from_index(x2, y2))
        else
            if x != x_
                bottoms  .push(chart.point.from_index(x , y )) 
                tops  .unshift(chart.point.from_index(x2, y2))
            x_ := x

        xLast := x2
        yLast := y2

        if close[n-x] < y 
            countBots += 1 

        if n-x2 >= 0
            if close[n-x2 ] > y2 
                countTops += 1 

        if countBots > maxBreaksBot or countTops > maxBreaksTop
            break 

    //Connection with polyTestB polyline
    testB_.push(chart.point.from_index(xLast+1-partX, yLast-partY)) 

    if countBots <= maxBreaksBot and countTops <= maxBreaksTop 

        if lastPolyPhBix == vwPh_bix
            bull_poly.delete(), bull_polyTestB.delete(), bull_polyTestT.delete()

            while bull_labsT.size() > 0
                lab = bull_labsT.pop()
                lab.set_textcolor(color.new(cBull, 65))

            while bull_labsB.size() > 0
                lab = bull_labsB.pop()
                lab.set_textcolor(color.new(cBear, 65))

        lastPolyPhBix := vwPh_bix 
        
        for i = 1 to lineLength 
            testT.push(chart.point.from_index(xLast+i, yLast))
            testB.push(chart.point.from_index(xLast+i-partX, yLast-partY))

        for i = lineLength to lineLength+partX 
            testB.push(chart.point.from_index(xLast+i-partX, yLast-partY))

        bull_tester.cpT := testT        
        bull_tester.cpB := testB
        bull_tester.position := 0

        //Connection 'Half Cup Bottom' & polyTestB polyline
        if bottoms.size() > 0
            testB_.unshift(chart.point.from_index(bottoms.last().index, bottoms.last().price)) 

        //Merge points array's
        bottoms.concat(testB_), bottoms.concat(tops)

        bull_poly       := polyline.new(bottoms, closed=true, line_color=INV, fill_color=cBullFill)
        bull_polyTestB  := polyline.new(testB , line_color=cBull)
        bull_polyTestT  := polyline.new(testT , line_color=cBull)
        
//Bearish
if bear and not na(ph) and ph > vwPl_prc

    //width & height of 'Half Cup'
    width  = n-1 - vwPl_bix //#bars
    height = ph  - vwPl_prc //#price

    //Vertical Shift of pattern
    vwPl_prc += height * verticalShift

    //Shifts the pattern Top part diagonally
    partX = math.round(width * broadness)
    partY = height * broadness

    bottoms = array.new<chart.point>()
    tops    = array.new<chart.point>()
    testT   = array.new<chart.point>() 
    testB   = array.new<chart.point>() 

    testT_  = array.new<chart.point>() 

    countBots = 0, countTops = 0 

    maxBreaksBot = width * iBots
    maxBreaksTop = width * iTops

    xLast = n, yLast = 0., x_ = -1

    for i = 0 to width 
        //Make Quarter Circle (2rd quadrant)
        y =       vwPl_prc - ((height * math.sin(pi + (pi2 / width*i)))) 
        x = math.floor(n-1 + ((width  * math.cos(pi + (pi2 / width*i)))))

        x2 = x + partX
        y2 = y - partY

        if xLast > n -2
            diffX = x2 - xLast            
            diffY = y2 - yLast
            if diffX >= 1 
                for j = 1 to diffX
                    testB     .push(chart.point.from_index(xLast + j        , yLast - (diffY / diffX * j)       ))  
                    //Bottom Line before pl    
                    if xLast + j - partX < n 
                        testT_.push(chart.point.from_index(xLast + j - partX, yLast - (diffY / diffX * j) +partY))    
                    bottoms.unshift(chart.point.from_index(xLast + j        , yLast - (diffY / diffX * j)       ))
            else 
                if x2 > n -1
                    testB .push(chart.point.from_index(x2, y2))           
                bottoms.unshift(chart.point.from_index(x2, y2))
        else
            if x != x_
                tops      .push(chart.point.from_index(x , y )) 
                bottoms.unshift(chart.point.from_index(x2, y2))
            x_ := x

        xLast := x2
        yLast := y2

        if close[n-x] > y 
            countBots += 1 

        if n-x2 >= 0
            if close[n-x2 ] < y2 
                countTops += 1 

        if countBots > maxBreaksBot or countTops > maxBreaksTop
            break 

    //Connection with polyTestB polyline
    testT_.push(chart.point.from_index(xLast+1-partX, yLast+partY)) 

    if countBots <= maxBreaksBot and countTops <= maxBreaksTop 

        if lastPolyPlBix == vwPl_bix
            bear_poly.delete(), bear_polyTestB.delete(), bear_polyTestT.delete()

            while bear_labsT.size() > 0
                lab = bear_labsT.pop()
                lab.set_textcolor(color.new(cBull, 65))

            while bear_labsB.size() > 0
                lab = bear_labsB.pop()
                lab.set_textcolor(color.new(cBear, 65))

        lastPolyPlBix := vwPl_bix 

        for i = 1 to lineLength 
            testB.push(chart.point.from_index(xLast+i, yLast))
            testT.push(chart.point.from_index(xLast+i-partX, yLast+partY))

        for i = lineLength to lineLength+partX 
            testT.push(chart.point.from_index(xLast+i-partX, yLast+partY))

        bear_tester.cpT := testT        
        bear_tester.cpB := testB
        bear_tester.position := 0

        //Connection 'Half Cup Bottom' & polyTestB polyline
        if tops.size() > 0
            testT_.unshift(chart.point.from_index(tops.last().index, tops.last().price)) 

        //Merge points array's
        tops.concat(testT_)
        tops.concat(bottoms)

        bear_poly       := polyline.new(tops, closed=true, line_color=INV, fill_color=cBearFill)
        bear_polyTestB  := polyline.new(testB, line_color=cBear)
        bear_polyTestT  := polyline.new(testT, line_color=cBear)

if bull_tester.cpT.size() > 0 
    for i = bull_tester.cpT.size() -1 to 0 
        tes = bull_tester.cpT.get(i)
        if tes.index == n 
            switch 
                bull_tester.position < 1 =>
                    if close > tes.price
                        bull_labsT.push(
                         label.new(n, high, style=label.style_label_down, color=INV, text='●', textcolor=cBull))
                        bull_tester.position := 1
                bull_tester.position == 1 =>     
                    if close < tes.price
                        bull_tester.position := 0
            bull_tester.cpT.remove(i)
            break

if bull_tester.cpB.size() > 0 
    for i = bull_tester.cpB.size() -1 to 0 
        tes = bull_tester.cpB.get(i)
        if tes.index == n 
            switch 
                bull_tester.position > -1 =>
                    if close < tes.price
                        bull_labsB.push(
                         label.new(n, low, style=label.style_label_up, color=INV, text='●', textcolor=cBear))
                        bull_tester.position := -1
                bull_tester.position == -1 =>     
                    if close > tes.price
                        bull_tester.position := 0
            bull_tester.cpB.remove(i)
            break

if bear_tester.cpT.size() > 0 
    for i = bear_tester.cpT.size() -1 to 0 
        tes = bear_tester.cpT.get(i)
        if tes.index == n 
            switch 
                bear_tester.position < 1 =>
                    if close > tes.price
                        bear_labsT.push(
                         label.new(n, high, style=label.style_label_down, color=INV, text='●', textcolor=cBull))
                        bear_tester.position := 1
                bear_tester.position == 1 =>     
                    if close < tes.price
                        bear_tester.position := 0
            bear_tester.cpT.remove(i)
            break

if bear_tester.cpB.size() > 0 
    for i = bear_tester.cpB.size() -1 to 0 
        tes = bear_tester.cpB.get(i)
        if tes.index == n 
            switch 
                bear_tester.position > -1 =>
                    if close < tes.price
                        bear_labsB.push(
                         label.new(n, low, style=label.style_label_up, color=INV, text='●', textcolor=cBear))
                        bear_tester.position := -1
                bear_tester.position == -1 =>     
                    if close > tes.price
                        bear_tester.position := 0
            bear_tester.cpB.remove(i)
            break

//---------------------------------------------------------------------------------------------------------------------}