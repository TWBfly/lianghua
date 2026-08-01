// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator('Session Gap Fill [LuxAlgo]','LuxAlgo - Session Gap Fill', overlay = true, max_boxes_count = 500, max_labels_count = 500, max_lines_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                       = #089981
RED                         = #F23645

GREEN_80                    = color.new(GREEN,80)
RED_80                      = color.new(RED,80)
RED_50                      = color.new(RED,50)
SILVER_50                   = color.new(color.silver,50)
SILVER_80                   = color.new(color.silver,80)

NOOVERLAPPING               = 'No Overlapping Wicks'
OVERLAPPING                 = 'Overlapping'
ALL                         = 'All'

TOP_RIGHT                   = 'Top Right'
BOTTOM_RIGHT                = 'Bottom Right'
BOTTOM_LEFT                 = 'Bottom Left'

TINY                        = 'Tiny'
SMALL                       = 'Small'
NORMAL                      = 'Normal'
LARGE                       = 'Large'
HUGE                        = 'Huge'

DASHBOARD_GROUP             = 'Dashboard'
STYLE_GROUP                 = 'Style'

EM_SPACE                    = ' '
FOUR_PER_EM_SPACE           = ' '
HAIR_SPACE                  = ' '

filledBullishGapTooltip     = EM_SPACE+HAIR_SPACE+HAIR_SPACE
filledBearishGapTooltip     = FOUR_PER_EM_SPACE+FOUR_PER_EM_SPACE+FOUR_PER_EM_SPACE+HAIR_SPACE
unfilledGapTooltip          = EM_SPACE+EM_SPACE+EM_SPACE+FOUR_PER_EM_SPACE+HAIR_SPACE+HAIR_SPACE
levelTooltip                = EM_SPACE+FOUR_PER_EM_SPACE+HAIR_SPACE+HAIR_SPACE+HAIR_SPACE

gapTypeInput                = input.string( ALL,        'Gap Type',             options = [ALL,OVERLAPPING,NOOVERLAPPING])

dashboardInput              = input.bool(   true,       'Dashboard',            group=DASHBOARD_GROUP)
dashboardPositionInput      = input.string( TOP_RIGHT,  'Position',             group=DASHBOARD_GROUP, options = [TOP_RIGHT,BOTTOM_RIGHT,BOTTOM_LEFT])
dashboardSizeInput          = input.string( NORMAL,     'Size',                 group=DASHBOARD_GROUP, options = [TINY,SMALL,NORMAL,LARGE,HUGE])

filledBullishGapInput       = input.bool(   true,       'Filled Bullish Gap',   group = STYLE_GROUP, inline = 'style1')
filledBullishGapColorInput  = input.color(  GREEN_80,   filledBullishGapTooltip,group = STYLE_GROUP, inline = 'style1')
filledBearishGapInput       = input.bool(   true,       'Filled Bearish Gap',   group = STYLE_GROUP, inline = 'style2')
filledBearishGapColorInput  = input.color(  RED_80,     filledBearishGapTooltip,group = STYLE_GROUP, inline = 'style2')
unfilledGapInput            = input.bool(   true,       'Unfilled Gap',         group = STYLE_GROUP, inline = 'style3')
unfilledGapColorInput       = input.color(  SILVER_80,  unfilledGapTooltip,     group = STYLE_GROUP, inline = 'style3')
divergingInput              = input.bool(   true,       'Max Deviation Level',  group = STYLE_GROUP, inline = 'style4')
divergingColorInput         = input.color(  RED_50,     '',                     group = STYLE_GROUP, inline = 'style4')
levelInput                  = input.bool(   true,       'Open Price Level',     group = STYLE_GROUP, inline = 'style5')
levelColorInput             = input.color(  SILVER_50,  levelTooltip,           group = STYLE_GROUP, inline = 'style5')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type gap
    int startBar
    int fillBar
    int startTime
    int endTime    
    string gapType
    float openPrice
    float top
    float bottom
    float lastClose    
    box gapArea    
    line extremePrice
    label tag    
    bool filled = false
    bool valid  = false

var array<gap> gaps                         = array.new<gap>()
var array<int> filledBullishGaps            = array.new<int>()
var array<int> filledBearishGaps            = array.new<int>()
var array<int> filledBullishReversedGaps    = array.new<int>()
var array<int> filledBearishReversedGaps    = array.new<int>()
var array<int> filledBullishBars            = array.new<int>()
var array<int> filledBearishBars            = array.new<int>()

bool gapStart                               = session.isfirstbar_regular

var parsedDashboardPosition = switch dashboardPositionInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
gapType() =>    
    bullishGap              = open  > close[1]
    bearishGap              = open  < close[1]
    bullishOverlapping      = low   < high[1]
    bullishNonOverlapping   = low   > high[1]
    bearishOverlapping      = high  > low[1]
    bearishNonOverlapping   = high  < low[1]

    overlappingGap          = (bullishGap and bullishOverlapping) or (bearishGap and bearishOverlapping)
    noOverlappingGap        = (bullishGap and bullishNonOverlapping) or (bearishGap and bearishNonOverlapping)
    
    switch
        overlappingGap      => OVERLAPPING
        noOverlappingGap    => NOOVERLAPPING        
        => ''

validateGap(gap currentGap) => 
    bool isValid        = currentGap.gapType != '' and (gapTypeInput == ALL or currentGap.gapType == gapTypeInput)
    currentGap.valid    := isValid

checkGapType() => 
    bool passedCheck = true
    if gaps.last().gapType == '' or (gapTypeInput != ALL and gaps.last().gapType != gapTypeInput)
        gaps.pop()
        passedCheck := false
    passedCheck

gatherStatistics() =>
    if gaps.size() > 0 and checkGapType()
        if gaps.last().openPrice > gaps.last().lastClose
            filledBullishGaps.push(gaps.last().filled ? 1 : 0)
            if gaps.last().filled
                filledBullishReversedGaps.push(close[1] > gaps.last().openPrice ? 1 : 0)
                filledBullishBars.push(gaps.last().fillBar - gaps.last().startBar)
        else
            filledBearishGaps.push(gaps.last().filled ? 1 : 0)
            if gaps.last().filled
                filledBearishReversedGaps.push(close[1] < gaps.last().openPrice ? 1 : 0)
                filledBearishBars.push(gaps.last().fillBar - gaps.last().startBar)

gatherData() =>
    if gapStart        
        gatherStatistics()        
        gaps.push(gap.new(bar_index,bar_index,time,time,gapType(),open,high,low,close[1],na,na,na))        
        validateGap(gaps.last())
                    
    if gaps.size() > 0
        gap currentGap          = gaps.last()
        currentGap.endTime      := time        
        currentGap.top          := math.max(currentGap.top,high)
        currentGap.bottom       := math.min(currentGap.bottom,low)

        if not currentGap.filled
            bool filledGap      = (currentGap.openPrice > currentGap.lastClose and currentGap.bottom <= currentGap.lastClose) or (currentGap.openPrice < currentGap.lastClose and currentGap.top >= currentGap.lastClose)
            currentGap.filled   := filledGap
            currentGap.fillBar  := bar_index            
            
drawGap(gap currentGap) =>        
    bool isGapDisplayable = currentGap.filled ? (currentGap.openPrice > currentGap.lastClose ? filledBullishGapInput : filledBearishGapInput) : unfilledGapInput

    if isGapDisplayable
        if currentGap.filled        
            float tagPrice  = currentGap.openPrice > currentGap.lastClose ? currentGap.top : currentGap.bottom        
            int tagTime     = currentGap.startTime + math.round(0.5*(currentGap.endTime - currentGap.startTime))
            string tagStyle = currentGap.openPrice > currentGap.lastClose ? label.style_label_down : label.style_label_up        

            currentGap.tag.delete()
            currentGap.tag := label.new(chart.point.new(tagTime,na,tagPrice),'Filled',xloc.bar_time,yloc.price,color(na),tagStyle,currentGap.openPrice > currentGap.lastClose ? color.new(filledBullishGapColorInput,0) : color.new(filledBearishGapColorInput,0),10)

        currentGap.gapArea.delete()    
        currentGap.gapArea := box.new(chart.point.new(currentGap.startTime,na,math.max(currentGap.openPrice,currentGap.lastClose)),chart.point.new(currentGap.endTime,na,math.min(currentGap.openPrice,currentGap.lastClose)),border_color = color(na),bgcolor = currentGap.filled ? (currentGap.openPrice > currentGap.lastClose ? filledBullishGapColorInput : filledBearishGapColorInput) : unfilledGapColorInput, xloc = xloc.bar_time)

        if divergingInput
            currentGap.extremePrice.delete()
            float extremePrice = currentGap.openPrice > currentGap.lastClose ? currentGap.top : currentGap.bottom

            if extremePrice != currentGap.openPrice
                currentGap.extremePrice := line.new(chart.point.new(currentGap.startTime,na,extremePrice),chart.point.new(currentGap.endTime,na,extremePrice),xloc.bar_time, color = divergingColorInput)
    
drawGaps() =>
    for eachGap in gaps.slice(0,gaps.size() - 1)
        drawGap(eachGap)
    
drawLastGap() =>
    gap lastGap = gaps.last()
    if lastGap.valid
        drawGap(lastGap)

cell(table t_able, int column, int row, string data, color = color.white, align = text.align_right) => t_able.cell(column,row,data,text_color = color, text_size = parsedDashboardSize, text_halign = align)

drawDashboard() =>
    var table t_able = table.new(parsedDashboardPosition,3,5
     , bgcolor      = #1e222d
     , border_color = #373a46
     , border_width = 1
     , frame_color  = #373a46
     , frame_width  = 1)

    cell(t_able,1,0,'Bullish',      align = text.align_left)
    cell(t_able,2,0,'Bearish',      align = text.align_left)

    cell(t_able,0,1,'Gaps',         align = text.align_center)
    cell(t_able,0,2,'Filled',       align = text.align_center)  
    cell(t_able,0,3,'Reversed',     align = text.align_center)
    cell(t_able,0,4,'Bars Avg.',    align = text.align_center)
    
    cell(t_able,1,1,str.format('{0, number, 0.00%}',filledBullishGaps.size() / (gaps.size() - 1)))
    cell(t_able,1,2,str.format('{0, number, 0.00%}',filledBullishGaps.sum() / filledBullishGaps.size()))
    cell(t_able,1,3,str.format('{0, number, 0.00%}',filledBullishReversedGaps.sum() / filledBullishReversedGaps.size()))
    cell(t_able,1,4,str.format('{0, number, 0.00}',filledBullishBars.avg()))

    cell(t_able,2,1,str.format('{0, number, 0.00%}',filledBearishGaps.size() / (gaps.size() - 1)))            
    cell(t_able,2,2,str.format('{0, number, 0.00%}',filledBearishGaps.sum() / filledBearishGaps.size()))
    cell(t_able,2,3,str.format('{0, number, 0.00%}',filledBearishReversedGaps.sum() / filledBearishReversedGaps.size()))
    cell(t_able,2,4,str.format('{0, number, 0.00}',filledBearishBars.avg()))
    
//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
gatherData()

if barstate.islastconfirmedhistory        
    drawGaps()

    if dashboardInput
        drawDashboard()
    
if barstate.islast
    drawLastGap()

gap currentGap          = gaps.size() > 0 ? gaps.last() : na
bool isGapDisplayable   = currentGap.filled ? (currentGap.openPrice > currentGap.lastClose ? filledBullishGapInput : filledBearishGapInput) : unfilledGapInput
float currentGapOpen    = not na(currentGap) and currentGap.valid ? currentGap.openPrice : na
float openPrice         = levelInput and isGapDisplayable ? (gapStart ? na : currentGapOpen) : na

plot(openPrice,'Open Price Level',levelColorInput,style = plot.style_linebr)

//---------------------------------------------------------------------------------------------------------------------}