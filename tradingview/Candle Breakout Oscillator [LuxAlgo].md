// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Candle Breakout Oscillator [LuxAlgo]','LuxAlgo - Candle Breakout Oscillator')
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                   = #089981
RED                     = #F23645

bullColor               = color.new(GREEN,50)
bearColor               = color.new(RED,50)
sidewaysColor           = color.new(color.silver,50)

NONE                    = 'None'
VOLUME                  = 'Volume'
PRICE                   = 'Price'
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

DATA_GROUP              = 'DATA'
THRESHOLDS_GROUP        = 'THRESHOLDS'

windowInput             = input.int(    100,    'Window')

smoothingInput          = input.string( RMA,    'Smoothing Method', group = DATA_GROUP,         options=[NONE,RMA,SMA,TMA,EMA,DEMA,TEMA,HMA,WMA,SWMA,VWMA])
smoothingLengthInput    = input.int(    2,      'Smoothing Length', group = DATA_GROUP,         step = 1,   minval = 1, maxval = 100)
weightTypeInput         = input.string( NONE,   'Weighting Method', group = DATA_GROUP,         options=[NONE,VOLUME,PRICE])

topThresholdInput       = input.int(    80,     'Top',              group = THRESHOLDS_GROUP,   minval = 50,maxval = 100)
bottomThresholdInput    = input.int(    20,     'Bottom',           group = THRESHOLDS_GROUP,   minval = 0, maxval = 50)

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
var array<float> bulls          = array.new<float>()
var array<float> bears          = array.new<float>()
var array<float> sideways       = array.new<float>()
var array<float> volumes        = array.new<float>()
var array<float> bullWeights    = array.new<float>()
var array<float> bearWeights    = array.new<float>()
var array<float> sidewayWeights = array.new<float>()

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
parseWeight(float weight) => weightTypeInput != NONE ? (weightTypeInput == VOLUME ? volume : weight) : 1

addData(array<float> a_rray, float value, int size, float weight) =>
    a_rray.push(value * parseWeight(weight))
    if a_rray.size() > size
        a_rray.shift()

addWeight(array<float> a_rray, float value, int size) =>
    a_rray.push(value)
    if a_rray.size() > size
        a_rray.shift()

normalize(array<float> a_rray, int window, array<float> weights) =>
    value = weightTypeInput != NONE ? a_rray.sum() / (weightTypeInput == VOLUME ? volumes.sum() : weights.sum()) : a_rray.sum()
    100 * (value - ta.lowest(value, window)) / (ta.highest(value, window) - ta.lowest(value, window))

smooth(float data) =>
    switch smoothingInput
        RMA     => ta.rma(data,smoothingLengthInput)
        SMA     => ta.sma(data,smoothingLengthInput)
        TMA     => ta.sma(ta.sma(data,smoothingLengthInput),smoothingLengthInput)
        EMA     => ta.ema(data,smoothingLengthInput)
        DEMA    => 2 * ta.ema(data,smoothingLengthInput) - ta.ema(ta.ema(data,smoothingLengthInput),smoothingLengthInput)
        TEMA    => 3 * ta.ema(data,smoothingLengthInput) - 3 * ta.ema(ta.ema(data,smoothingLengthInput),smoothingLengthInput) + ta.ema(ta.ema(ta.ema(data,smoothingLengthInput),smoothingLengthInput),smoothingLengthInput)
        HMA     => ta.hma(data,smoothingLengthInput)
        WMA     => ta.wma(data,smoothingLengthInput)
        SWMA    => ta.swma(data)
        VWMA    => ta.vwma(data,smoothingLengthInput)
        => data
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
bull            = close > high[1]
bear            = close < low[1]
sideway         = not bull and not bear
bullWeight      = math.abs(close - high[1])
bearWeight      = math.abs(close - low[1])
sidewayWeight   = 1

addData(bulls, bull ? +1 : -1, windowInput,bullWeight)
addData(bears, bear ? +1 : -1, windowInput,bearWeight)
addData(sideways, sideway ? +1 : -1, windowInput,sidewayWeight)
addWeight(volumes,volume,windowInput)
addWeight(bullWeights,bullWeight,windowInput)
addWeight(bearWeights,bearWeight,windowInput)
addWeight(sidewayWeights,sidewayWeight,windowInput)

bullsNormalized     = smooth(normalize(bulls,windowInput,bullWeights))
bearsNormalized     = smooth(normalize(bears,windowInput,bearWeights))
sidewaysNormalized  = smooth(normalize(sideways,windowInput,sidewayWeights))

bullPlot            = plot(bullsNormalized,'Bullish', bullColor)
bearPlot            = plot(bearsNormalized,'Bearish', bearColor)
sidewaysPlot        = plot(sidewaysNormalized,'Sideways',sidewaysColor)
topPlot             = plot(topThresholdInput,'Top',color(na))
bottomPlot          = plot(bottomThresholdInput,'Bottom',color(na))

bullishCross        = bullsNormalized > bearsNormalized and bullsNormalized[1] <= bearsNormalized[1]
bearishCross        = bearsNormalized > bullsNormalized and bearsNormalized[1] <= bullsNormalized[1]

plotshape(bullsNormalized,'Bullish Cross',shape.circle,location.absolute,bullishCross ? color.new(bullColor,0) : color(na), size = size.tiny)
plotshape(bearsNormalized,'Bearish Cross',shape.circle,location.absolute,bearishCross ? color.new(bearColor,0) : color(na), size = size.tiny)

fill(bullPlot,topPlot, bullsNormalized > topThresholdInput ? bullColor : color(na),'Bullish Top Fill')
fill(bullPlot,bottomPlot ,bullsNormalized < bottomThresholdInput ? bullColor : color(na),'Bullish Bottom Fill')
fill(bearPlot, topPlot, bearsNormalized > topThresholdInput ? bearColor : color(na),'Bearish Top Fill')
fill(bearPlot, bottomPlot, bearsNormalized < bottomThresholdInput ? bearColor : color(na),'Bearish Bottom Fill')
fill(sidewaysPlot, bottomPlot, sidewaysNormalized < bottomThresholdInput ? sidewaysColor : color(na),'Sideways Bottom Fill')

hline(topThresholdInput,'Top Threshold')
hline(bottomThresholdInput,'Bottom Threshold')
//---------------------------------------------------------------------------------------------------------------------}