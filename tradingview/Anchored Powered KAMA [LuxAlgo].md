// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Anchored Powered KAMA [LuxAlgo]','LuxAlgo - Anchored Powered KAMA',precision = 2,overlay = true,max_bars_back = 5000)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN               = #089981
RED                 = #F23645

HOURLY              = 'Hourly'
DAILY               = 'Daily'
WEEKLY              = 'Weekly'
MONTHLY             = 'Monthly'
YEARLY              = 'Yearly'

periodInput         = input.string( YEARLY,             'Anchor Period',    options=[HOURLY,DAILY,WEEKLY,MONTHLY,YEARLY], inline = 'period')
autoIPeriodInput    = input.bool(   true,               'Auto',             inline = 'period')
sourceInput         = input.source( close,              'Source')
powerInput          = input.float(  2.0,                'Power Exponent',   step = 0.25,minval=0)
multiplierInput     = input.float(  2.0,                'Bands Multiplier', step = 0.25,minval=2.0)
bullishColorInput   = input.color(  color.new(GREEN,80),'',                 inline = 'colors')
bearishColorInput   = input.color(  color.new(RED,80),  '',                 inline = 'colors')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
string parsedPeriod         = switch
    timeframe.in_seconds() <= timeframe.in_seconds('2')     =>  HOURLY
    timeframe.in_seconds() <= timeframe.in_seconds('15')    =>  DAILY
    timeframe.in_seconds() <= timeframe.in_seconds('60')    =>  WEEKLY
    timeframe.in_seconds() <= timeframe.in_seconds('240')   =>  MONTHLY
    =>  YEARLY

bool isNewPeriod            = switch (autoIPeriodInput ? parsedPeriod : periodInput)
    HOURLY      => ta.change(hour)              != 0
    DAILY       => ta.change(time_tradingday)   != 0
    WEEKLY      => ta.change(weekofyear)        != 0
    MONTHLY     => ta.change(month)             != 0
    YEARLY      => ta.change(year)              != 0

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
anchoredKama(float data) =>
    var int counter         = 0
    var float kama          = 0
    float efficiencyRatio   = 0
    var float welford       = 0

    if isNewPeriod
        counter := 1
        welford := 0
    else
        if counter >= 4999
            runtime.error('The Anchor Period setting is much too large in relation to the current chart timeframe. Please select a larger chart timeframe or a smaller anchor period.')
        counter += 1

    efficiencyRatio     := math.abs(ta.change(data,counter)) / math.sum(math.abs(ta.change(data)),counter)
    smoothingConstant   = math.pow(efficiencyRatio, powerInput)    
    kama                := smoothingConstant * data + (1 - smoothingConstant) * nz(kama,data)    
    welford             += (data - kama[1])*(data - kama)
    deviation           = math.sqrt(welford/counter)
    [kama,deviation]

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
[kama,deviation] = anchoredKama(sourceInput)

plot(isNewPeriod ? na : kama,'APKama',chart.fg_color,linewidth = 1,style = plot.style_linebr)

upperOuterPlot = plot(isNewPeriod ? na : kama + multiplierInput * deviation,'upper',color.new(bullishColorInput,20),linewidth = 1,style = plot.style_linebr)
upperInnerPlot = plot(isNewPeriod ? na : kama + (multiplierInput - 1) * deviation,'upper',bar_index % 2 == 0 ? color(na) : color.new(bullishColorInput,50),linewidth = 1,style = plot.style_linebr)
lowerInnerPlot = plot(isNewPeriod ? na : kama - (multiplierInput - 1) * deviation,'lower',bar_index % 2 == 0 ? color(na) : color.new(bearishColorInput,50),linewidth = 1,style = plot.style_linebr)
lowerOuterPlot = plot(isNewPeriod ? na : kama - multiplierInput * deviation,'lower',color.new(bearishColorInput,20),linewidth = 1,style = plot.style_linebr)

fill(upperOuterPlot,upperInnerPlot,kama + multiplierInput * deviation,kama + (multiplierInput - 1) * deviation,bullishColorInput,color.new(chart.bg_color,100))
fill(lowerInnerPlot,lowerOuterPlot,kama - (multiplierInput - 1) * deviation,kama - multiplierInput * deviation,color.new(chart.bg_color,100),bearishColorInput)

//---------------------------------------------------------------------------------------------------------------------}