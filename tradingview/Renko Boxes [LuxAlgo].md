// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Renko Boxes [LuxAlgo]", "LuxAlgo - Renko Boxes", overlay = true)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
atrLengthInput = input.int(200, "ATR Length", minval = 1, group = "Renko Settings")
atrMultInput   = input.float(1.0, "ATR Multiplier", minval = 0.1, step = 0.1, group = "Renko Settings")

bullColorInput = input.color(#089981, "Bullish Color", group = "Visuals")
bearColorInput = input.color(#f23645, "Bearish Color", group = "Visuals")
fillTransp     = input.int(90, "Transparency", minval = 0, maxval = 100, group = "Visuals")

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
float atr = ta.atr(atrLengthInput)
float brickSize = atr * atrMultInput

var float renkoUpper = na
var float renkoLower = na
var int   direction  = 0 // 1: Up, -1: Down

// Initialize on the first available bar after ATR is calculated
if bar_index > atrLengthInput
    if na(renkoUpper)
        renkoUpper := close
        renkoLower := close - brickSize
        direction  := 1
    else
        // Calculate potential new levels
        float upThreshold   = renkoUpper + brickSize
        float downThreshold = renkoLower - brickSize

        if direction == 1
            // Trend continues up
            if close > upThreshold
                int numBricks = math.floor((close - renkoUpper) / brickSize)
                renkoLower := renkoUpper + (numBricks - 1) * brickSize
                renkoUpper := renkoUpper + numBricks * brickSize
            // Trend reverses down
            else if close < downThreshold
                int numBricks = math.floor((renkoLower - close) / brickSize)
                renkoUpper := renkoLower - (numBricks - 1) * brickSize
                renkoLower := renkoLower - numBricks * brickSize
                direction  := -1
        else
            // Trend continues down
            if close < downThreshold
                int numBricks = math.floor((renkoLower - close) / brickSize)
                renkoUpper := renkoLower - (numBricks - 1) * brickSize
                renkoLower := renkoLower - numBricks * brickSize
            // Trend reverses up
            else if close > upThreshold
                int numBricks = math.floor((close - renkoUpper) / brickSize)
                renkoLower := renkoUpper + (numBricks - 1) * brickSize
                renkoUpper := renkoUpper + numBricks * brickSize
                direction  := 1

//---------------------------------------------------------------------------------------------------------------------}
// Visuals
//---------------------------------------------------------------------------------------------------------------------{
bool isChanged = renkoUpper != renkoUpper[1] or renkoLower != renkoLower[1]
bool isReversed = ta.change(direction) != 0
float renkoAvg = (renkoUpper + renkoLower) / 2.0

color plotColor = direction == 1 ? bullColorInput : bearColorInput
color finalColor = isChanged ? na : plotColor

// Renko Average Line (Continuous & Dashed)
plot(renkoAvg, "Renko Average", color = plotColor, style = plot.style_line, linestyle = plot.linestyle_dotted, linewidth = 1)

// Reversal Dots
plot(isReversed ? renkoAvg : na, "Reversal Dots", color = plotColor, style = plot.style_circles, linewidth = 2)

// Renko Boxes (with cuts)
p1 = plot(renkoUpper, "Renko Upper", color = finalColor, style = plot.style_linebr)
p2 = plot(renkoLower, "Renko Lower", color = finalColor, style = plot.style_linebr)

// Fill the area between upper and lower levels (with cuts)
fill(p1, p2, isChanged ? na : color.new(plotColor, fillTransp), "Renko Box Fill")

//---------------------------------------------------------------------------------------------------------------------}
