// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Island Reversal [LuxAlgo]','LuxAlgo - Island Reversal', overlay = true, max_boxes_count = 500, max_labels_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN               = #089981
RED                 = #F23645

UPTREND             = 1
DOWNTREND           = 0

TREND_GROUP         = 'Trend Filter'
VOLUME_GROUP        = 'Volume Filter'
RANGE_GROUP         = 'Range Filter'
STYLE_GROUP         = 'Style'

EM_SPACE            = ' '
volSpacing          = EM_SPACE+EM_SPACE+EM_SPACE+EM_SPACE

trendInput          = input.bool(   true,   'Trend Filter',                 group = TREND_GROUP)
trendLengthInput    = input.int(    10,     'Trend Length',                 group = TREND_GROUP, minval = 2)

volumeInput         = input.bool(   false,  'Volume Filter',                group = VOLUME_GROUP)

r2FilterInput       = input.bool(   true,  'Horizontality Filter (R2)',    group = RANGE_GROUP, inline = 'r2')
r2ThresholdInput    = input.float(  0.50,   '',                             group = RANGE_GROUP, inline = 'r2', minval = 0, maxval = 1, step = 0.05)
volFilterInput      = input.bool(   true,  'Volatility Filter'+volSpacing, group = RANGE_GROUP, inline = 'volatility')
volMultiplierInput  = input.float(  5.0,    '',                             group = RANGE_GROUP, inline = 'volatility')

bullishColorInput   = input.color(  GREEN,  'Bullish',                      group = STYLE_GROUP)
bearishColorInput   = input.color(  RED,    'Bearish',                      group = STYLE_GROUP)
transparencyInput   = input.int(    80,     'Transparency',                 group = STYLE_GROUP)
showR2              = input(false, 'Show R2 In Label',                      group = STYLE_GROUP)

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type islandReversal    
    int startTime
    int endTime
    float top
    float bottom
    color background
    int volumesIndex
    int trend
    bool startWithBullishGap
    float startLevel
    float endLevel
    bool isActive           = true
    bool isCompleted        = false
    array<float> highs      = na
    array<float> lows       = na
    array<float> volumes    = na
    array<float> rangeData  = na
    string addedTag         = ''

var array<islandReversal> reversals = array.new<islandReversal>()
var array<float> volumes            = array.new<float>()
var int trend                       = UPTREND
float lower                         = ta.lowest(trendLengthInput)
float upper                         = ta.highest(trendLengthInput)
float volatility                    = ta.atr(200) * volMultiplierInput
bool bullishGap                     = low > high[1]
bool bearishGap                     = high < low[1]
bool newGap                         = bullishGap or bearishGap

volumes.push(volume)
trend := upper > upper[1] ? UPTREND : lower < lower[1] ? DOWNTREND : trend

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
rSquared(array<float> data) =>    
    array<int> bars = data.sort_indices()
    bars.sort()
    math.pow(data.covariance(bars) / (bars.stdev() * data.stdev()),2)

validRange(islandReversal currentReversal) =>
    bool r2Filter           = true
    bool volatilityFilter   = true

    if r2FilterInput
        float r2                    = rSquared(currentReversal.rangeData)        
        currentReversal.addedTag    := str.format('{0,number,0.000000}',r2)
        r2Filter                    := r2 <= r2ThresholdInput

    if volFilterInput
        float reversalRange = currentReversal.top - currentReversal.bottom
        volatilityFilter    := reversalRange <= volatility

    r2Filter and volatilityFilter

validVolume(islandReversal currentReversal) =>    
    if volumeInput
        float previousVolumeAverage = volumes.slice(math.max(0,currentReversal.volumesIndex - currentReversal.volumes.size()),currentReversal.volumesIndex).avg()
        float currentVolumeAverage  = currentReversal.volumes.avg()
        currentVolumeAverage > previousVolumeAverage
    else
        true

validTrend(islandReversal currentReversal) => (trendInput and ((currentReversal.trend == UPTREND and currentReversal.startWithBullishGap) or (currentReversal.trend == DOWNTREND and not currentReversal.startWithBullishGap))) or not trendInput
    
checkFilters(islandReversal currentReversal) => validTrend(currentReversal) and validVolume(currentReversal) and validRange(currentReversal)

gatherData() =>    
    if newGap
        float startLevel    = bullishGap ? high[1] : low[1]
        float endLevel      = bullishGap ? low : high
        bool newReversal    = false

        if reversals.size() > 0
            islandReversal currentReversal = reversals.last()

            if currentReversal.isActive
                if (currentReversal.startWithBullishGap and bearishGap) or (not currentReversal.startWithBullishGap and bullishGap)
                    currentReversal.volumes.push(volume)
                    currentReversal.endTime     := time
                    currentReversal.endLevel    := endLevel                    
                    currentReversal.isActive    := false
                    currentReversal.isCompleted := true
                    if not checkFilters(currentReversal)
                        reversals.pop()
                else
                    currentReversal.isCompleted := false
                    currentReversal.isActive    := false                    
                    newReversal                 := true
                    reversals.pop()
            else
                newReversal := true
        else
            newReversal := true

        if newReversal            
            reversals.push(islandReversal.new(time[1],time,high,low,bullishGap ? bearishColorInput : bullishColorInput,volumes.size(),trend,bullishGap,startLevel,startLevel,true,false,array.from(high),array.from(low),array.from(volume[1],volume),array.from(close)))
            if reversals.size() > 500
                reversals.shift()    
            0
    else
        if reversals.size() > 0
            islandReversal currentReversal = reversals.last()

            if currentReversal.isActive                
                currentReversal.highs.push(high)
                currentReversal.lows.push(low)
                currentReversal.volumes.push(volume)
                currentReversal.rangeData.push(close)
                currentReversal.endTime := time
                currentReversal.top     := currentReversal.highs.max()
                currentReversal.bottom  := currentReversal.lows.min()

                if (currentReversal.startWithBullishGap and currentReversal.bottom < currentReversal.startLevel) or (not currentReversal.startWithBullishGap and currentReversal.top > currentReversal.startLevel)
                    currentReversal.isCompleted := false
                    currentReversal.isActive    := false
                    reversals.pop()
        0

drawReversals() =>
    for eachReversal in reversals
        if not eachReversal.isActive or (eachReversal.isActive and checkFilters(eachReversal))
            color areaColor = eachReversal.startWithBullishGap ? color.new(bearishColorInput,transparencyInput) : color.new(bullishColorInput,transparencyInput)
            string tag      = (eachReversal.startWithBullishGap ? 'Top\nIsland Reversal' : 'Bottom\nIsland Reversal') + (showR2 ? '\n' + eachReversal.addedTag : '')            
            box.new(chart.point.new(eachReversal.startTime,na,eachReversal.top),chart.point.new(eachReversal.endTime,na,eachReversal.bottom),color(na),xloc = xloc.bar_time,bgcolor = areaColor)
            label.new(chart.point.new(eachReversal.startTime + math.round(0.5*(eachReversal.endTime - eachReversal.startTime)),na,eachReversal.startWithBullishGap ? eachReversal.top : eachReversal.bottom),tag,xloc.bar_time,yloc.price,color(na),eachReversal.startWithBullishGap ? label.style_label_down : label.style_label_up, color.new(areaColor,0), size.normal)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
gatherData()

if barstate.islastconfirmedhistory
    drawReversals()

//---------------------------------------------------------------------------------------------------------------------}