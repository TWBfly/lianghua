// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Trendlines Oscillator [LuxAlgo]','LuxAlgo - Trendlines Oscillator', max_lines_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645

BEAR                    = 0
BULL                    = 1

NONE                    = 'None'
RMA                     = 'RMA'
SMA                     = 'SMA'
TMA                     = 'TMA'
EMA                     = 'EMA'
DEMA                    = 'DEMA'
TEMA                    = 'TEMA'
HMA                     = 'HMA'
WMA                     = 'WMA'
SWMA                    = 'SWMA'
VWMA                    = 'VWMA'

SMOOTH_GROUP            = 'Smoothing'

EM_SPACE                = ' ' 
dataSpacing             = EM_SPACE + EM_SPACE + EM_SPACE

lengthInput             = input.int(    5,      'Length')
memoryInput             = input.int(    10,     'Memory')
sourceInput             = input.source( close,  'Source')

dataSmoothingInput      = input.string( NONE,   'Data Smoothing'+dataSpacing,   inline = 'data',    group = SMOOTH_GROUP,   options = [NONE,RMA,SMA,TMA,EMA,DEMA,TEMA,HMA,WMA,SWMA,VWMA])
dataSmoothingLengthInput= input.int(    10,     '',                             inline = 'data',    group = SMOOTH_GROUP,   minval = 2)

smoothingActiveInput    = input.bool(   true,   'Signal Smoothing',             inline = 'signal',  group = SMOOTH_GROUP)
smoothingInput          = input.string( TMA,    '',                             inline = 'signal',  group = SMOOTH_GROUP,   options = [RMA,SMA,TMA,EMA,DEMA,TEMA,HMA,WMA,SWMA,VWMA])
smoothingLengthInput    = input.int(    10,     '',                             inline = 'signal',  group = SMOOTH_GROUP,   minval = 2 )

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type l
    float intercept 
    float slope

var array<l> res    = array.new<l>(0)
var array<l> sup    = array.new<l>(0)
var int phx1        = 0
var int plx1        = 0
var int lastSignal  = BEAR

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
method get_point(l id, x)=>
    id.slope * x + id.intercept

smooth(float data, string smoothing, int length) =>
    switch smoothing
        RMA     => ta.rma(data,length)
        SMA     => ta.sma(data,length)
        TMA     => ta.sma(ta.sma(data,length),length)
        EMA     => ta.ema(data,length)
        DEMA    => 2 * ta.ema(data,length) - ta.ema(ta.ema(data,length),length)
        TEMA    => 3 * ta.ema(data,length) - 3 * ta.ema(ta.ema(data,length),length) + ta.ema(ta.ema(ta.ema(data,length),length),length)
        HMA     => ta.hma(data,length)
        WMA     => ta.wma(data,length)
        SWMA    => ta.swma(data)
        VWMA    => ta.vwma(data,length)
        => data

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
n       = bar_index
ph      = fixnan(ta.pivothigh(lengthInput, lengthInput))
pl      = fixnan(ta.pivotlow(lengthInput, lengthInput))
sup_sum = 0.
sup_den = 0.
res_sum = 0.
res_den = 0.

if ph < ph[1]
    slope = (ph - ph[1])/(n-lengthInput - phx1)
    res.unshift(l.new(ph[1] - slope * phx1, slope))

if pl > pl[1]
    slope = (pl - pl[1])/(n-lengthInput - plx1)
    sup.unshift(l.new(pl[1] - slope * plx1, slope))

if ph != ph[1]
    phx1 := n-lengthInput
if pl != pl[1]
    plx1 := n-lengthInput

if res.size() > memoryInput
    res.pop()

if sup.size() > memoryInput
    sup.pop()

for element in sup
    point = element.get_point(n)
    if sourceInput > point
        sup_sum += sourceInput - point
    
    sup_den += math.abs(sourceInput - point)

for element in res
    point = element.get_point(n)
    if sourceInput < point
        res_sum += point - sourceInput

    res_den += math.abs(point - sourceInput)

float supportLine       = sup_sum / sup_den * 100
float resistanceLine    = res_sum / res_den * 100
float smoothSupport     = smooth(supportLine,dataSmoothingInput,dataSmoothingLengthInput)
float smoothResistance  = smooth(resistanceLine,dataSmoothingInput,dataSmoothingLengthInput)
float signal            = math.abs(smoothSupport - smoothResistance)
float signalLine        = smoothingActiveInput ? smooth(signal,smoothingInput,smoothingLengthInput) : na

plot(signalLine,'signal,',chart.fg_color)
supportPlot     = plot(smoothSupport,'support', color = GREEN)
resistancePlot  = plot(smoothResistance,'resistance',color = RED)
basePlot        = plot(0,'', display = display.none, editable = false)

bullSignal      = smoothSupport > signalLine and smoothSupport[1] < signalLine[1]
bearSignal      = smoothResistance > signalLine and smoothResistance[1] < signalLine[1]

lastSignal      := bullSignal and lastSignal == BEAR ? BULL : bearSignal and lastSignal == BULL ? BEAR : lastSignal
firstBull       = smoothingActiveInput and ta.change(lastSignal) > 0
firstBear       = smoothingActiveInput and ta.change(lastSignal) < 0

plot(firstBull ? smoothSupport : na, 'Bullish Cross', linewidth = 3, style = plot.style_circles, color = color.new(GREEN,0))
plot(firstBear ? smoothResistance : na, 'Bearish Cross', linewidth = 3, style = plot.style_circles, color = color.new(RED,0))

fill(basePlot,supportPlot,100,0,color.new(GREEN,40),color.new(GREEN,100))
fill(basePlot,resistancePlot,100,0,color.new(RED,40),color.new(RED,100))

hline(80)
hline(50)
hline(20)

//---------------------------------------------------------------------------------------------------------------------}