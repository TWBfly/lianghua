// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=5

indicator('Chandelier Exit Oscillator [LuxAlgo]', 'LuxAlgo - Chandelier Exit Oscillator')

//---------------------------------------------------------------------------------------------------------------------
// Settings 
//---------------------------------------------------------------------------------------------------------------------{

display     = display.all - display.status_line

generGroup  = 'Chandelier Exit Settings'
tfIndi      = input.timeframe('', "Timeframe", group = generGroup, display = display)
length      = input.int(22, 'ATR Length', minval = 0, group = generGroup, display = display)
multiplier  = input.float(3.0, 'ATR Multiplier', minval = 0, step = .1, group = generGroup, display = display)

osc_Group   = 'Chandelier Exit Oscillator'
osc_Show    = input.string('Regular', 'Chandelier Exit Oscillator', options = ['Regular', 'Normalized'], group = osc_Group, display = display)
bullColor   = input.color(#2962ff, '  Bullish', inline = 'CSS', group = osc_Group)
bearColor   = input.color(#f23645, 'Bearish', inline = 'CSS', group = osc_Group)
osc_lnWidth = input.int(1, 'Width', minval = 1, inline = 'CSS', group = osc_Group, display = display)
norm_Smooth = input.int(3, '  Oscillator Smoothing ', minval = 1, inline = 'dmmy', group = osc_Group, display = display)

ceGroup     = 'Chandelier Exit Overlay'
ceShow      = input.bool(true, 'Chandelier Exit Overlay', group = ceGroup)
ceBullColor = input.color(#089981, '  Bullish', group = ceGroup, inline = 'MS')
ceBearColor = input.color(#f23645, 'Bearish', group = ceGroup, inline = 'MS')
ceLnWidth   = input.int(1, 'Width', minval = 1, inline = 'MS', group = ceGroup, display = display)
barShow     = input.bool(false, 'Trend-based Bar Colors', group = ceGroup)

//---------------------------------------------------------------------------------------------------------------------}
// Functions / Methods
//---------------------------------------------------------------------------------------------------------------------{

normalize(bull, bear, smooth)=>
    var os = 0
    var float max = na
    var float min = na
    os := bull ? 1 : bear ? -1 : os
    
    max := os > os[1] ? close : os < os[1] ? max : math.max(close, max)
    min := os < os[1] ? close : os > os[1] ? min : math.min(close, min)

    ta.sma((close - min) / (max - min), smooth) * 100

chandelierExit(length, multiplier, mode) => 
    atr = ta.atr(length)

    highestHigh = math.avg(ta.highest(close, length), ta.highest(length))
    lowestLow   = math.avg(ta.lowest (close, length), ta.lowest (length))
    chandLong   = highestHigh - atr * multiplier
    chandShort  = lowestLow   + atr * multiplier

    var int dir = 1
    dir := close > chandShort ? 1 : close < chandLong ? -1 : dir
    chandExit = dir > 0 ? chandLong : chandShort

    chandOsc = mode ? normalize(close > math.avg(chandLong, chandShort), close < math.avg(chandLong, chandShort), norm_Smooth) : ta.sma(math.avg(close - chandLong, close - chandShort), norm_Smooth)

    [chandExit, dir, chandOsc]

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{

mode = osc_Show == 'Normalized'

[chandExit, dir, chandExitOsc] = request.security(syminfo.tickerid, tfIndi, chandelierExit(length, multiplier, mode))

tiRankN = plot(chandExitOsc, 'Chandelier Exit Oscillator', chandExitOsc > (mode ? 50 : 0) ? color.new(bullColor, 43) : color.new(bearColor, 43), osc_lnWidth, display = display, editable = false)

midLineN = plot(not mode ? 0 : na, 'Equilibrium Level', color.new(#787b86, 63), display = display, editable = false)
fill(tiRankN, midLineN, (chandExitOsc > 0 ? chandExitOsc : 0), (chandExitOsc > 0 ? 0 : chandExitOsc), (chandExitOsc > 0 ? color.new(bullColor, 17) : color.new(chart.bg_color, 17)), (chandExitOsc > 0 ?  color.new(chart.bg_color, 17): color.new(bearColor, 17)))

plot(mode ? 85 : na, 'Upper Level', color.new(#787b86, 63), display = display, editable = false)
midLine   = plot(mode ? 50 : na, 'Equilibrium Level', color.new(#787b86, 63), display = display, editable = false)
plot(mode ? 15 : na, 'Lower Level', color.new(#787b86, 63), display = display, editable = false)
fill(tiRankN, midLine, (chandExitOsc > 50 ? chandExitOsc : 50), (chandExitOsc > 50 ? 50 : chandExitOsc), (chandExitOsc > 50 ? color.new(bullColor, 17) : color.new(chart.bg_color, 17)), (chandExitOsc > 50 ?  color.new(chart.bg_color, 17): color.new(bearColor, 17)))

plotshape(ceShow ? chandExit : na, 'Signals', shape.circle, location.absolute, dir != dir[1] ?  dir == 1 ? ceBullColor : ceBearColor : na, size = size.auto, display = display, force_overlay = true, editable = false)

bear = plot(ceShow and dir == -1 ? chandExit : na, 'Chandelier Exit Overlay', dir != dir[1] ? na : dir == 1 ? ceBullColor : ceBearColor, ceLnWidth, display = display, editable = false, force_overlay = true)
body = plot(barstate.isfirst ? na : ceShow ? hl2 : na, "Body Middle", display = display.none, editable = false, force_overlay = true)
bull = plot(ceShow and dir ==  1 ? chandExit : na, 'Chandelier Exit Overlay', dir != dir[1] ? na : dir == 1 ? ceBullColor : ceBearColor, ceLnWidth, display = display, editable = false, force_overlay = true)

fill(bear, body, chandExit, hl2, color.new(ceBearColor, 81), color.new(chart.bg_color, 100))
fill(body, bull, hl2, chandExit, color.new(chart.bg_color, 100), color.new(ceBullColor, 81))

barColor = barShow ? dir == 1 ? ceBullColor : ceBearColor : na
plotcandle(barShow ? open : na, barShow ? high : na, barShow ? low : na, barShow ? close : na, color = barColor,  bordercolor = barColor, wickcolor = barColor, display = display, editable = false, force_overlay = true)

//---------------------------------------------------------------------------------------------------------------------}