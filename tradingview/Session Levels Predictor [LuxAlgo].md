// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Session Levels Predictor [LuxAlgo]", shorttitle="LuxAlgo - Session Levels Predictor", max_lines_count=500, max_labels_count=500, overlay=true)
//Raise Error
if barstate.isfirst and not timeframe.isintraday
    runtime.error('Only intraday timeframes are supported')
 
//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{
st    = '               '
i_sess = input.session("0800-1000",      'Session'                )
ePer1  = input.bool   (    true  ,         ''       , inline='p1')
perc1  = input.int    (     50    ,   'percentile 1' , inline='p1')
ePer2  = input.bool   (    true   ,         ''       , inline='p2')
perc2  = input.int    (     75    ,   'percentile 2' , inline='p2')
ePer3  = input.bool   (    true   ,         ''       , inline='p3')
perc3  = input.int    (     90    ,   'percentile 3' , inline='p3')
maxS   = input.int    (    500    ,  'Max population'             )

//Style
colD   = input.color  (#089981  ,       'Upper'     , inline='c ', group = 'Style')
colU   = input.color  (#f23645  ,       'Lower'     , inline='c ', group = 'Style')
size   = input.string (size.small ,   'Label Size'        
       ,   options =  [size.tiny  , size.small, size.normal]       , group = 'Style')
extMid = input.bool   (  false    ,   'Extend Middle Line'         , group = 'Style')       

//-----------------------------------------------------------------------------}      
//UDT's
//-----------------------------------------------------------------------------{
type bin 
    float sessO
    float sessH
    float sessL 
    float multH
    float multL

type sess     
    float sessO
    float predH1
    float predL1
    float predH2
    float predL2    
    float predH3
    float predL3

    array<float> aH
    array<float> aL

    array<line> ln_midLin

    array<line> ln_predH1
    array<line> ln_predL1

    array<line> ln_predH2
    array<line> ln_predL2

    array<line> ln_predH3
    array<line> ln_predL3

    bool hitH1
    bool hitL1
    bool hitH2
    bool hitL2    
    bool hitH3
    bool hitL3

    array<int> aCounter

    array<int> aCntH1
    array<int> aCntL1
    array<int> aCntH2
    array<int> aCntL2
    array<int> aCntH3
    array<int> aCntL3

//-----------------------------------------------------------------------------}      
//Variables
//-----------------------------------------------------------------------------{
n = bar_index

var sess oSess     = sess.new(
                     na, na, na, na, na, na, na
                     , array.new<float>(1, na)
                     , array.new<float>(1, na)                     
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , array.new<line >(1, na)
                     , na, na, na, na, na, na
                     , array.new< int >(1, na)
                     , array.new< int >(1, na)
                     , array.new< int >(1, na)
                     , array.new< int >(1, na)
                     , array.new< int >(1, na)
                     , array.new< int >(1, na)                    
                     , array.new< int >(1, na)
                     )

var array<bin>aBin = array.new<bin>(1, bin.new()) 

//-----------------------------------------------------------------------------}      
//Methods
//-----------------------------------------------------------------------------{
method p(array<float>a, int perc) => a.percentile_nearest_rank(perc) 

method hitH(sess s, int n, bool b) =>
    bool hit = na, array<line>lin = na, array<int>cnt = na 
    if b
        switch n 
            1 => hit := s.hitH1, lin := s.ln_predH1, cnt := s.aCntH1
            2 => hit := s.hitH2, lin := s.ln_predH2, cnt := s.aCntH2
            3 => hit := s.hitH3, lin := s.ln_predH3, cnt := s.aCntH3
        if not hit 
            if high > lin.first().get_y2() 
                cnt.set(0, 1), hit := true

method hitL(sess s, int n, bool b) =>
    bool hit = na, array<line>lin = na, array<int>cnt = na 
    if b
        switch n 
            1 => hit := s.hitL1, lin := s.ln_predL1, cnt := s.aCntL1
            2 => hit := s.hitL2, lin := s.ln_predL2, cnt := s.aCntL2
            3 => hit := s.hitL3, lin := s.ln_predL3, cnt := s.aCntL3
        if not hit 
            if low < lin.first().get_y2() 
                cnt.set(0, 1), hit := true

method clean(array<float>a) =>
    if a.size() > maxS 
        a.pop() 

method cleanLines(array<line>a) =>
    if a.size() > 70 
        a.pop().delete()

method lb(float f, int d, int c, color col) => 
     label.new(n, f
     , text  = str.format("{0}%", math.round(c / oSess.aCounter.sum() * 100, 1))
     , size  = size
     , style = d == -1 
     ? label.style_label_up  
     : label.style_label_down
     , color=color.new(na, na)
     , textcolor=col)

//-----------------------------------------------------------------------------}      
//Execution
//-----------------------------------------------------------------------------{
t = not na(time(timeframe.period, i_sess)) 

switch 
    t =>                                                                                                                // session
        if not t[1]                                                                                                     // first bar of session
            oSess.sessO := open

            oSess.hitH1 := false, oSess.hitH2 := false, oSess.hitH3 := false
            oSess.hitL1 := false, oSess.hitL2 := false, oSess.hitL3 := false
            
            if extMid
                oSess.ln_midLin.unshift(line.new(n, oSess.sessO, n, oSess.sessO, style=line.style_dotted))

            if ePer1
                oSess.predH1 := oSess.sessO + oSess.aH.p(perc1), oSess.predL1 := oSess.sessO - oSess.aL.p(perc1)
                oSess.ln_predH1.unshift(line.new(n, oSess.predH1, n, oSess.predH1, color=colU))
                oSess.ln_predL1.unshift(line.new(n, oSess.predL1, n, oSess.predL1, color=colD))
                oSess.predH1.lb( 1, oSess.aCntH1.sum(), colU) 
                oSess.predL1.lb(-1, oSess.aCntL1.sum(), colD) 
                oSess.aCntH1.unshift(0), oSess.aCntH1.clean()
                oSess.aCntL1.unshift(0), oSess.aCntL1.clean()

            if ePer2
                oSess.predH2 := oSess.sessO + oSess.aH.p(perc2), oSess.predL2 := oSess.sessO - oSess.aL.p(perc2)
                oSess.ln_predH2.unshift(line.new(n, oSess.predH2, n, oSess.predH2, color=colU))
                oSess.ln_predL2.unshift(line.new(n, oSess.predL2, n, oSess.predL2, color=colD))
                oSess.predH2.lb( 1, oSess.aCntH2.sum(), colU)
                oSess.predL2.lb(-1, oSess.aCntL2.sum(), colD) 
                oSess.aCntH2.unshift(0), oSess.aCntH2.clean()
                oSess.aCntL2.unshift(0), oSess.aCntL2.clean()

            if ePer3
                oSess.predH3 := oSess.sessO + oSess.aH.p(perc3), oSess.predL3 := oSess.sessO - oSess.aL.p(perc3)
                oSess.ln_predH3.unshift(line.new(n, oSess.predH3, n, oSess.predH3, color=colU))
                oSess.ln_predL3.unshift(line.new(n, oSess.predL3, n, oSess.predL3, color=colD))
                oSess.predH3.lb( 1, oSess.aCntH3.sum(), colU) 
                oSess.predL3.lb(-1, oSess.aCntL3.sum(), colD) 
                oSess.aCntH3.unshift(0), oSess.aCntH3.clean()
                oSess.aCntL3.unshift(0), oSess.aCntL3.clean()

            aBin.unshift(bin.new(open, high, low))

            oSess.aCounter.unshift(1), oSess.aCounter.clean()

        else 
            get        = aBin.get(0)
            get.sessH := math.max(high, get.sessH)
            get.sessL := math.min(low , get.sessL)
            get.multH := (get.sessH - get.sessO)
            get.multL := (get.sessO - get.sessL)

    =>                                                                                                                  // not in session
        if t[1]                                                                                                         // if previous bar was in session
            oSess.aH.unshift(aBin.first().multH), oSess.aH.clean()      
            oSess.aL.unshift(aBin.first().multL), oSess.aL.clean()                   

            oSess.sessO := na

            if ePer1
                oSess.ln_predH1.unshift(line.new(n -1, oSess.predH1, n, oSess.predH1, color=colU, style=line.style_dotted))
                oSess.ln_predL1.unshift(line.new(n -1, oSess.predL1, n, oSess.predL1, color=colD, style=line.style_dotted))
            if ePer2
                oSess.ln_predH2.unshift(line.new(n -1, oSess.predH2, n, oSess.predH2, color=colU, style=line.style_dashed))
                oSess.ln_predL2.unshift(line.new(n -1, oSess.predL2, n, oSess.predL2, color=colD, style=line.style_dashed))
            if ePer3
                oSess.ln_predH3.unshift(line.new(n -1, oSess.predH3, n, oSess.predH3, color=colU, style=line.style_solid ))
                oSess.ln_predL3.unshift(line.new(n -1, oSess.predL3, n, oSess.predL3, color=colD, style=line.style_solid ))


oSess.ln_midLin.cleanLines()
oSess.ln_predH1.cleanLines(), oSess.ln_predL1.cleanLines()
oSess.ln_predH2.cleanLines(), oSess.ln_predL2.cleanLines()
oSess.ln_predH3.cleanLines(), oSess.ln_predL3.cleanLines()

oSess.ln_midLin.first().set_x2(n), oSess.ln_midLin.first().set_x2(n)
oSess.ln_predH1.first().set_x2(n), oSess.ln_predL1.first().set_x2(n)
oSess.ln_predH2.first().set_x2(n), oSess.ln_predL2.first().set_x2(n)
oSess.ln_predH3.first().set_x2(n), oSess.ln_predL3.first().set_x2(n)

oSess.hitH(1, ePer1), oSess.hitL(1, ePer1)
oSess.hitH(2, ePer2), oSess.hitL(2, ePer2)
oSess.hitH(3, ePer3), oSess.hitL(3, ePer3) 

//-----------------------------------------------------------------------------}      
//Plot - bgcolor - barcolor
//-----------------------------------------------------------------------------{
plot(oSess.sessO         , style = plot.style_linebr  , title='Session Open'    )

barcolor(t and not t[1] ? color.new(   na     , na) : na)
bgcolor (t              ? color.new(color.blue, 90) : na)

//-----------------------------------------------------------------------------}      
//Table
//-----------------------------------------------------------------------------{
var table tb = table.new(position = position.top_right, columns = 2, rows = 4, bgcolor = chart.bg_color, border_width = 1)

if barstate.islast
    tb.cell(column = 0, row = 0, text_color= chart.fg_color, text = 'Counted Sessions', text_halign = text.align_left)
    tb.cell(column = 1, row = 0, text_color= chart.fg_color, text = str.tostring(oSess.aCounter.sum()))

    row_idx = 1

    if ePer1
        tb.cell(column = 0, row = row_idx, text_color= chart.fg_color, text = 'P1 Hit Rate', text_halign = text.align_left)
        tb.cell(column = 1, row = row_idx, text_color= chart.fg_color
          , text = str.tostring((oSess.aCntH1.sum() + oSess.aCntL1.sum()) / 2 / oSess.aCounter.sum() * 100, format.percent))
        row_idx += 1

    if ePer2
        tb.cell(column = 0, row = row_idx, text_color= chart.fg_color, text = 'P2 Hit Rate', text_halign = text.align_left)
        tb.cell(column = 1, row = row_idx, text_color= chart.fg_color
          , text = str.tostring((oSess.aCntH2.sum() + oSess.aCntL2.sum()) / 2 / oSess.aCounter.sum() * 100, format.percent))
        row_idx += 1

    if ePer3
        tb.cell(column = 0, row = row_idx, text_color= chart.fg_color, text = 'P3 Hit Rate', text_halign = text.align_left)
        tb.cell(column = 1, row = row_idx, text_color= chart.fg_color
          , text = str.tostring((oSess.aCntH3.sum() + oSess.aCntL3.sum()) / 2 / oSess.aCounter.sum() * 100, format.percent))
        row_idx += 1

//-----------------------------------------------------------------------------}