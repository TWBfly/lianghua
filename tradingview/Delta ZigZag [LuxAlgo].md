// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator(    'Delta ZigZag [LuxAlgo]'
 , shorttitle='LuxAlgo - Delta ZigZag'
 , max_labels_count=500
 , max_lines_count=500
 , overlay=true
 )

//------------------------------------------------------------------------------
// Settings
//-----------------------------------------------------------------------------{
tick      = input.string   ('LTF',  'Data from: ', options=['Ticks','LTF'])
res       = input.timeframe('1' ), W = 'high/low', C='close'
iSrc      = input.string   ( W   ,     'option'  , options=[W, C])

showZZ    = input(true, title='Show ZigZag'                 , group="ZigZag"                                                                                                            )
left      = input.int(3, minval=1                           , group="ZigZag"                                                                                                            )
right     = input.int(0, minval=0                           , group="ZigZag"                                                                                                            )
upcol     = input(#089981, title='Up Color'               , group="ZigZag"                                                                                                            )
dncol     = input(#F23645, title='Down Color'             , group="ZigZag"                                                                                                            )

shZZbl_tV = input(true, title='Show % Bullish Volume'       , group="ZigZag Delta"               , tooltip='ZigZag must be enabled'                                                     )
shZZdV_tV = input(true, title='Show'                        , group="ZigZag Delta", inline='avg' , tooltip='Set AVG'                                                                    )
opt       = input.string('Normalised Volume Delta',   ''    , group='ZigZag Delta', inline='avg'
          , options=['Average Volume Delta/bar', 'Average Volume/bar', 'Normalised Volume Delta'], tooltip='sum of chosen data divided by N° bars of ZZ line'                           )
cZZUp     = input.color(#42BDA8, 'Up     '    , inline='u', group='ZigZag Delta'                                                                                                      )
cZZUp_    = input.color(#f77c807f, 'Up -     ', inline='u', group='ZigZag Delta', tooltip='Up\n-> bullish ZigZag and + ZigZag Delta\n\nUp -\n-> bullish ZigZag and - ZigZag Delta'    )
cZZDn     = input.color(#F77C80, 'Down'       , inline='d', group='ZigZag Delta'                                                                                                      )
cZZDn_    = input.color(#42bda87f, 'Down +'   , inline='d', group='ZigZag Delta', tooltip='Down\n-> bearish ZigZag and - ZigZag Delta\n\nDown +\n-> bearish ZigZag and + ZigZag Delta')

showD     = input.bool(false, 'Show Details'                , group='Bar data'                                                                                                          )
iSplitV_B = input.bool(false, 'Split Volume per bar'        , group='Bar data'    , tooltip='up & down volume per bar'                                                                  ) // split in uV , dV (no nV)
iV_B      = input.bool(false, 'Volume (Bar)'                , group='Bar data'    , tooltip='up + down volume per bar (neutral volume not included)'                                    ) //          uV + dV (no nV)
iDV_B     = input.bool(true , 'Δ Volume (Bar)'              , group='Bar data'    , tooltip='up - down volume per bar'                                                                  ) //          uV - dV

//-----------------------------------------------------------------------------}      
//Basics
//-----------------------------------------------------------------------------{
INV       = color.new( na ,  na )
avg       = math.avg(close, open)
n         = bar_index
bull      = close >  open
bear      = close <  open
neut      = close == open
tAVG      = opt == 'Average Volume Delta/bar' ? 'x̄ (ΔV)' : opt == 'Average Volume/bar' ? 'x̄ (V)' : 'x̄ (ΔV/V)' 

hi        = switch iSrc 
    W => high 
    C => close 

lo        = switch iSrc 
    W => low 
    C => close 

isTick = tick == 'Ticks'
isLTF  = tick == 'LTF'

//-----------------------------------------------------------------------------}      
//UDT
//-----------------------------------------------------------------------------{
type zz 
    float p 
    int   b 

//-----------------------------------------------------------------------------}      
//Variables
//-----------------------------------------------------------------------------{
var  MAX_A_SIZE    = 10
var string  txt    = ''
var  int    dir    = 0
var line  zzlineA  = line.new(na, na, na, na)
var line  zzlineZ  = line.new(na, na, na, na)
var label mid = label.new(na, na, style=label.style_label_center
     , color=color.new(color.black, 25), size=size.small)
var array<zz> zigzag = array.new<zz>(3, zz.new(na, na))
var array<float>aZig = array.new<float>(3, na) 
var array<float>aZag = array.new<float>(3, na) 
varip bool ticksAvailable = false
varip float volBl = na
varip float volBr = na
varip float  vl   = na
varip float  cl   = na
varip float  dfP  = na
varip float  dfV  = na
color colT = na 

float ph = ta.pivothigh(hi, left, right)
float pl = ta.pivotlow (lo, left, right)

//-----------------------------------------------------------------------------}      
//Methods
//-----------------------------------------------------------------------------{
method n(float piv) => bool out = not na(piv)

method add_to_zigzag(zz z) =>
    zigzag.unshift(z)
    if zigzag.size() > MAX_A_SIZE
        zigzag.pop()

method update_zigzag(zz z) =>
    zz1 = zigzag.first()
    if  (dir ==  1 and z.p >= zz1.p)
     or (dir == -1 and z.p <= zz1.p)
        zz1.p := z.p
        zz1.b := z.b

method clean(array <line> aL) =>
    while aL.size() > 500
        aL.shift().delete()

method clean(array <label> aL) =>
    while aL.size() > 500
        aL.shift().delete()

method v(float val) => str.tostring(val, format.volume) 

//-----------------------------------------------------------------------------}      
//Execution
//-----------------------------------------------------------------------------{
//Ticks
if isTick 
    if barstate.isnew 
        cl    := open  , dfP := 0 // "open" 
        vl    := volume, dfV := 0 // "volume" at first tick
        volBl := 0 ,   volBr := 0
    else
        dfP  := close  - cl
        dfV  := volume - vl

        switch 
            dfP > 0 => volBl += dfV
            dfP < 0 => volBr += dfV

        cl    :=  close
        vl    := volume
  
//LTF
res:=timeframe.from_seconds(
      math.min(
       timeframe.in_seconds(timeframe.period)
     , timeframe.in_seconds(      res       )
              )
                           )

[bV, sV, nV, tV] = request.security_lower_tf(
  syminfo.tickerid,  res  , 
 [
   bull ? volume : 0
 , bear ? volume : 0
 , neut ? volume : 0
 , volume
 ]                                          )

vSize   = tV.size()
ltf_Vup = bV.sum () 
ltf_Vdn = sV.sum () 
ltf_Vtt = tV.sum () 

//Start tick/LTF
if not ticksAvailable and volBl > 0 //Start Tick data
    ticksAvailable := true 
isAllowed = isTick ? ticksAvailable : tV.size() > 0
if isAllowed and not isAllowed[1]
    line.new(n, close, n, close + syminfo.mintick, color=color.silver, style=line.style_dotted, extend=extend.both)

//Dir
dir := ph.n() and na(pl)  ? 1 : pl.n() and na(ph) ? -1 : dir 
bool ch_dir = ta.change(dir) != 0

//ZigZag
if ch_dir
    zz.new(dir == 1 ? hi[right] : lo[right], n -right).add_to_zigzag()
else
    zz.new(dir == 1 ? hi[right] : lo[right], n -right).update_zigzag()

float  val = zigzag.first().p
int  point = zigzag.first().b
float val1 = zigzag.get (1).p
int point1 = zigzag.get (1).b
float val2 = zigzag.get (2).p
int point2 = zigzag.get (2).b

bool ch_b0 = ta.change(point ) != 0 
bool ch_b1 = ta.change(point1) != 0

if showZZ 

    if ch_b0

        width = point - point1
        float sumBlVol  = 0         
        float sumBrVol  = 0 
        float sumVolume = 0
        float slope = 0
        float  p2   = 0

        for i = n - point to n - point1 -1
            sumBlVol  += isTick ? volBl[i] : ltf_Vup[i]            
            sumBrVol  += isTick ? volBr[i] : ltf_Vdn[i]
            sumVolume += isTick ? volBl[i] + volBr[i] : ltf_Vup[i] + ltf_Vdn[i]

        ratioBl  = sumBlVol / sumVolume 
        colRatio = ratioBl > 0.5 ? val > val1 ? cZZUp : cZZDn_ : val < val1 ? cZZDn : cZZUp_

        b2 = math.round(point1 + ratioBl * width)
        if val > val1 
            slope := (val - val1) / width
            p2    := val1 + slope * (b2 - point1)
        else 
            slope := (val1 - val) / width
            p2    := val1 - slope * (b2 - point1)

        //If only change of last point
        if not ch_b1 
            if isAllowed
                zzlineA.set_xy2(b2, p2)
                zzlineZ.set_xy1(b2, p2)
                zzlineZ.set_xy2(point, val)
                if shZZbl_tV
                    mid.set_xy(b2, p2)
                    mid.set_textcolor(colRatio)
                    mid.set_text(str.format("{0, number, percent}", ratioBl))
            else 
                zzlineA.set_xy2(point, val)
        else
            b1 = point1, p1 = val1
            b3 = point , p3 = val 
            if isAllowed
                zzlineA := line.new(x1=b1, y1=p1, x2=b2, y2=p2, color=upcol, width=2)
                zzlineZ := line.new(x1=b2, y1=p2, x2=b3, y2=p3, color=dncol, width=2)
                if shZZbl_tV
                    if b2 == mid.get_x() and p2 == mid.get_y() 
                        p2 += switch 
                            p3 < p1 => syminfo.mintick * 50
                            =>      -  syminfo.mintick * 50 
                    mid := label.new(b2, p2, style=label.style_label_center, color=color.new(color.black, 25)
                         , text=str.format("{0, number, percent}", ratioBl)
                         , textcolor=colRatio, size=size.small
                         )
            else 
                zzlineA := line.new(x1=b1, y1=p1, x2=b3, y2=p3, color=color.new(dir==1?upcol:dncol, 50), width=2)
        
//Tick/LTF
if ch_dir and isAllowed and shZZdV_tV

    _t   = 0.
    _sumVolume = 0.
    _sum_Delta = 0.
    j    = 
           point1 
         - point2 

    for i = n - point1 to n - point2 -1
        vBl = isTick ? volBl[i] : ltf_Vup[i]
        vBr = isTick ? volBr[i] : ltf_Vdn[i]

        _sumVolume += vBl + vBr
        _sum_Delta += vBl - vBr

    _t := switch opt
        'Average Volume/bar'       => _sumVolume / j
        'Average Volume Delta/bar' => _sum_Delta / j
        =>                            _sum_Delta / 
                                      _sumVolume

    txt    := opt == 'Normalised Volume Delta' ? str.format("{0, number, percent}", _t) 
           :   str.format("{0}", str.tostring(math.round(_t, 2), format.volume)) 
              
    dist = n - point1
    if dir == -1        
        colT := _sum_Delta < 0 ? cZZUp_ : cZZUp
        if txt != 'NaN'
            label.new(point1, high[n - point1]
             , color=color.new(na, na), textcolor=colT, text=txt, tooltip=tAVG)

        aZig.unshift(_t), aZig.pop() 

    else
        colT := _sum_Delta > 0 ? cZZDn_ : cZZDn 
        if txt != 'NaN'
            label.new(point1, low[n - point1], style=label.style_label_up
             , color=color.new(na, na), textcolor=colT, text=txt, tooltip=tAVG)
         
        aZag.unshift(_t), aZag.pop() 

//Intrabar Delta
delta   = isTick ? (volBl - volBr) : ltf_Vup - ltf_Vdn
sumV    = isTick ? (volBl + volBr) : ltf_Vup + ltf_Vdn // volume without neutral volume
norm    = delta / sumV
colIB   = norm > 0 ? bull ? cZZUp : cZZDn_ : bear ? cZZDn : cZZUp_ 

//Show details
if showD and isAllowed and (isTick ? ticksAvailable : true)
    label.new(n, dir > 0 ? low : high, style=dir > 0 ? label.style_label_up : label.style_label_down
     ,                color=color.new(na, na)
     ,     textcolor= colIB, text=str.format(          "{0}{1}{2}{3}"
         , iSplitV_B ? str.format("upV: {0}\n" , (isTick ? volBl : ltf_Vup).v()) : ''
         , iSplitV_B ? str.format("dnV: {0}\n" , (isTick ? volBr : ltf_Vdn).v()) : ''
         , iV_B      ? str.format("V: {0}\n"   , (sumV                    ).v()) : ''   
         , iDV_B     ? str.format("ΔV: {0}\n"  , (delta                   ).v()) : ''  
         ), size=size.small)

//-----------------------------------------------------------------------------}      
//cleanse
//-----------------------------------------------------------------------------{
line.all.clean() 
label.all.clean() 

//-----------------------------------------------------------------------------}      
//Plot
//-----------------------------------------------------------------------------{
plot(dir         ,        'dir'                             , display=display.data_window)
plot(delta       ,       'delta'                            , display=display.data_window)
plot(volBl       ,   'Tick Volume Up'  , color=color.lime , display=display.data_window)
plot(volBr       ,   'Tick Volume Dn'  , color=color.red  , display=display.data_window)

//-----------------------------------------------------------------------------} 