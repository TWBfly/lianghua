// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("Market Structure Volume Distribution [LuxAlgo]", "LuxAlgo - Market Structure Volume Distribution", overlay = true, max_lines_count = 500, max_boxes_count = 200, max_bars_back = 5000)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
TOTAL_VOLUME    = 'TOTAL VOLUME'
BUY_SELL_VOLUME = 'BUY&SELL VOLUME'
BULLISH         = 'BULLISH'
BEARISH         = 'BEARISH'
GREEN           = #089981
RED             = #F23645

DATA_GROUP      = 'Data Gathering'
PROFILE_GROUP   = 'Profile'
STYLE_GROUP     = 'Style'

executionVisualRangeTooltip = 'Activate this to use all visible bars on the calculations. This disables the use of the next parameter `Execute on the last N bars`. Default false.'
executionLastNBarsTooltip   = 'Use last N bars on the calculations. To use this parameter `Execute on all visible range` must be disabled. Values from 20 to 5000, default 500.'
pivotLengthTooltip          = 'How many bars will be used to confirm a pivot. The bigger this parameter is the fewer breaks of structure will detect. Values from 1, default 2'
profileSizeTooltip          = 'Number of rows in the volume profile. Values from 2 to 100, default 10.'
profileWidthTooltip         = 'Maximum width of the volume profile. Values from 25 to 500, default 200.'
profileModeTooltip          = 'How the volume will be displayed on each row. `TOTAL VOLUME` will aggregate buy & sell volume per row, `BUY&SELL VOLUME` will separate the buy volume from the sell volume on each row. Default BUY&SELL VOLUME'
buyColorTooltip             = 'This is the color for the buy volume on the profile when the `BUY&SELL VOLUME` mode is activated. Default green.'
sellColorTooltip            = 'This is the color for the sell volume on the profile when the `BUY&SELL VOLUME` mode is activated. Default red.'
showGridTooltip             = 'Show dotted inner grid levels. Default true.'

//---------------------------------------------------------------------------------------------------------------------}
//Settings
//---------------------------------------------------------------------------------------------------------------------{
executionVisualRangeInput   = input.bool(   false,          'Execute on all visible range', group=DATA_GROUP,       tooltip = executionVisualRangeTooltip)
executionLastNBarsInput     = input.int(    500,            'Execute on the last N bars',   group=DATA_GROUP,       tooltip = executionLastNBarsTooltip,    minval=20,  maxval=5000)
pivotLengthInput            = input.int(    2,              'Pivot Length',                 group=DATA_GROUP,       tooltip = pivotLengthTooltip,           minval=1)
profileSizeInput            = input.int(    10,             'Profile Rows',                 group=PROFILE_GROUP,    tooltip = profileSizeTooltip,           minval=2,   maxval=100)
profileWidthInput           = input.int(    200,            'Profile Width',                group=PROFILE_GROUP,    tooltip = profileWidthTooltip,          minval=25,  maxval=500, step=25)
profileModeInput            = input.string( BUY_SELL_VOLUME,'Profile Mode',                 group=PROFILE_GROUP,    tooltip = profileModeTooltip,           options=[TOTAL_VOLUME,BUY_SELL_VOLUME])
buyColorInput               = input.color(  GREEN,          'Buy Color',                    group=STYLE_GROUP,      tooltip = buyColorTooltip)
sellColorInput              = input.color(  RED,            'Sell Color',                   group=STYLE_GROUP,      tooltip = sellColorTooltip)
showGridInput               = input.bool(   true,           'Show dotted grid levels',      group=STYLE_GROUP,      tooltip = showGridTooltip)

//---------------------------------------------------------------------------------------------------------------------}
//UDT
//---------------------------------------------------------------------------------------------------------------------{
// @type                Storage UDT for pivot points
// @field barIndex      Bar index of the privot point
// @field priceLevel    Price level of the pivot point
type pivotPoint
    int barIndex
    float priceLevel

// @type                    Storage UDT for breakouts (aka breaks of pivot points)
// @field pivot             Broken pivot point
// @field breakoutVolume    Volume of the breakout bar
// @field bias              Bias can be BULLISH or BEARISH and is used to catalog the volume as buy or sell volume
// @field row               Row in the volume profile where this breakout belongs
type breakout
    pivotPoint pivot
    float breakoutVolume
    string bias
    int row

// @type                Storege UDT for the volume profile
// @field sellVolume    Array for sell volume, each element represents one row of the profile
// @field buyVolume     Array for buy volume, each element represents one row of the profile
// @field totalVolume   Array for total volume, each element represents one row of the profile
type profile
    array<float> sellVolume
    array<float> buyVolume
    array<float> totalVolume

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
// @variable    Pivot point high: only the last pivot high is stored until it breaks or a new pivot high is found
var pivotPoint pivotHigh        = na
// @variable    Pivot point low: only the last pivot low is stored until it breaks or a new pivot low is found
var pivotPoint pivotLow         = na
// @variable    Collection of all breakouts (aka breaks of pivot points)
var array<breakout> breakouts   = array.new<breakout>(na)
// @variable    Volume profile storage: contains 3 arrays for buy, sell and total volume
var profile volumeProfile       = profile.new(na,na,na)
// @variable    Collection of lines representing the grid
var array<line> grid            = array.new<line>(profileSizeInput,na)
// @variable    Top price in the execution window
var float executionTop          = 0
// @variable    Bottom price in the execution window
var float executionBottom       = 0
// @variable    Storage the previous value of executionWindow
var bool lastExecutionWindow    = false
// @variable    Storage the bar_index of the first bar inside the execution window
var int firstExecutionBar       = 0

// @function        Draw a new line from the pivot point to the current bar
// @param point     (pivotPoint) Pivot point containing the starting bar and price level for the line
// @param lineColor (series color) Color for the new line
// @returns         New line ID
drawBreakLine(pivotPoint point,color lineColor) => line.new(point.barIndex,point.priceLevel,bar_index,point.priceLevel,color=lineColor)

// @function        Set for each breakout the correct row parameter (which row of the profile it belongs to)
// @param top       (series float) Top price inside the execution window
// @param bottom    (series float) Bottom price inside the execution window
// @returns         Last row of the last breakout
updateBreakoutRows(float top, float bottom) =>
    rowHeight = math.round_to_mintick((top - bottom) / profileSizeInput)
    for eachBreakout in breakouts        
        eachBreakout.row := math.min(int((top - eachBreakout.pivot.priceLevel)/rowHeight),profileSizeInput-1)

// @function    Recreate the profile 3 volume arrays from the breakouts: buy, sell and total volume
// @returns     void
updateProfileRows() =>    
    volumeProfile.buyVolume     := array.new<float>(profileSizeInput,0)
    volumeProfile.sellVolume    := array.new<float>(profileSizeInput,0)
    volumeProfile.totalVolume   := array.new<float>(profileSizeInput,0)
    
    for eachBreakout in breakouts
        array<float> selectedVolume = na

        if eachBreakout.bias == BULLISH
            selectedVolume := volumeProfile.buyVolume
        else
            selectedVolume := volumeProfile.sellVolume        

        currentVolume = array.get(selectedVolume,eachBreakout.row)
        array.set(selectedVolume,eachBreakout.row,currentVolume + eachBreakout.breakoutVolume)
        array.set(volumeProfile.totalVolume,eachBreakout.row,array.get(volumeProfile.totalVolume,eachBreakout.row)+eachBreakout.breakoutVolume)

// @function    Draw a line from `bar` to `last_bar_index + 10` at the specified level and style
// @param bar   (series int) Starting bar for drawing the line
// @param level (series float) Price level for drawing the line
// @param style (series string) Style of the line
// @returns     void
drawGridLine(int bar, float level,string style) => 
    startPoint  = chart.point.new(na,bar,level)
    endPoint    = chart.point.new(na,last_bar_index + 10,level)
    array.push(grid,line.new(startPoint,endPoint,color=chart.fg_color,style = style))

// @function                        Draw a volume profile box with the specified parameters                      
// @param top                       (float) Top price of the box
// @param bottom                    (float) Bottom price of the box
// @param rowVolume                 (float) Volume data that gives the width of the box and the text inside
// @param backgroundColor           (color) Background color of the box
// @param textHAlign                (string) Text horizontal align inside the box
// @returns                         New box ID
drawProfileSimpleRow(float top, float bottom, int left,float rowVolume,color backgroundColor = color.blue,string textHAlign = text.align_left) =>
    boxWidth    = int((rowVolume * (profileWidthInput - 10))/array.max(volumeProfile.totalVolume))
    topLeft     = chart.point.new(na,left,top)
    bottomRight = chart.point.new(na,left + boxWidth,bottom)            
    box.new(topLeft,bottomRight,border_color = na,text = rowVolume > 0 ? str.tostring(rowVolume,format.volume) : na,bgcolor = backgroundColor,text_color = chart.fg_color, text_size = size.tiny,text_halign = textHAlign)

// @function                        Draw 2 volume profile boxes with the specified parameters
// @param top                       (float) Top price of the box
// @param bottom                    (float) Bottom price of the box
// @param middle                    (int) Middle bar index from where draw the boxes
// @param buyVolume                 (float) Buy volume for the green box
// @param sellVolume                (float) Sell volume for the red box
// @returns                         New box ID
drawProfileDoubleRow(float top, float bottom, int middle, float buyVolume, float sellVolume) =>    
    boxWidth    = int((sellVolume * (profileWidthInput - 10))/array.max(volumeProfile.totalVolume))
    drawProfileSimpleRow(top,bottom,middle-boxWidth,sellVolume,sellColorInput,text.align_right)
    drawProfileSimpleRow(top,bottom,middle,buyVolume,buyColorInput)

// @function        Draw the grid and the volume profile
// @param top       (series float) Top price inside the execution window
// @param bottom    (series float) Bottom price inside the execution window
// @param firstBar  (series int) First bar inside the execution window
// @returns         Last drawn box ID
drawFullProfile(float top, float bottom,int firstBar) =>
    updateBreakoutRows(top,bottom)
    updateProfileRows()

    for eachBox in box.all
        box.delete(eachBox)

    for eachLine in grid
        line.delete(eachLine)

    rowHeight = math.round_to_mintick((top - bottom) / profileSizeInput)
    rowGap = math.max(math.round_to_mintick(rowHeight/10),syminfo.mintick)
    
    leftIndex = last_bar_index + 10
    middleIndex = leftIndex + int((array.max(volumeProfile.sellVolume) * (profileWidthInput - 10))/array.max(volumeProfile.totalVolume))

    // draw top solid grid line            
    drawGridLine(firstBar,top,line.style_solid)                   

    for index = 0 to profileSizeInput - 1
        rowTop = top - index * rowHeight - rowGap
        rowBottom = (index == (profileSizeInput - 1) ? bottom : rowTop - rowHeight + rowGap) + rowGap

        if showGridInput and index > 0
            drawGridLine(firstBar,rowTop+rowGap,line.style_dotted)        

        if profileModeInput == TOTAL_VOLUME
            drawProfileSimpleRow(rowTop,rowBottom,leftIndex,array.get(volumeProfile.totalVolume,index))            
        else
            drawProfileDoubleRow(rowTop,rowBottom,middleIndex,array.get(volumeProfile.buyVolume,index),array.get(volumeProfile.sellVolume,index))            

    // draw bottom grid line            
    drawGridLine(firstBar,bottom,line.style_solid)                   

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
// @variable Storage for possible pivot high on current bar
currentPivotHigh        = ta.pivothigh(pivotLengthInput,pivotLengthInput)
// @variable Storage for possible pivot low on current bar
currentPivotLow         = ta.pivotlow(pivotLengthInput,pivotLengthInput)
// @variable Calculate if current bar is inside execution window
currentExecutionWindow  = executionVisualRangeInput ? time >= chart.left_visible_bar_time : (last_bar_index - bar_index) <= executionLastNBarsInput
// @variable bar_index of possible pivot point
pivotBarIndex           = bar_index[pivotLengthInput]

// check if we are inside execution window
if currentExecutionWindow
    
    // check if this is the first bar inside execution window
    if not lastExecutionWindow    
        executionTop        := high
        executionBottom     := low
        firstExecutionBar   := bar_index    

    lastExecutionWindow := currentExecutionWindow    
   
    // we execute this logic only once per bar 
    if barstate.isconfirmed
        
        // Here we are throwing a custom error with the `runtime.error` built-in function
        // Why this is necessary? To avoid runtime enviroment throwing an error when it tries to create a new line with a x1 parameter (bar_index) bigger than the max buffer of 5000
        // this will happen when `executionVisualRangeInput` is `true` and the user drags the screen several times to show more past bars until the limit is reached and throws our custom error        
        if (last_bar_index - firstExecutionBar) > 5000
            runtime.error('Execution windows bigger than 5000 bars are not allowed. Please use a smaller execution window.')

        // update of top and bottom prices inside execution window
        executionTop    := math.max(high,executionTop)
        executionBottom := math.min(low,executionBottom)

        // if we identify a pivot high, we store it into `pivotHigh` variable
        if not na(currentPivotHigh)
            pivotHigh := pivotPoint.new(pivotBarIndex,currentPivotHigh)

        // if we identify a pivot low, we store it into `pivotLow` variable
        if not na(currentPivotLow)
            pivotLow := pivotPoint.new(pivotBarIndex,currentPivotLow)

        // if we have a pivotHigh and a break of its level, we store the breakout and draw the line
        if not na(pivotHigh) 
            if close > pivotHigh.priceLevel            
                array.push(breakouts,breakout.new(pivotHigh,volume,BULLISH))                
                drawBreakLine(pivotHigh,buyColorInput)        
                pivotHigh := na                

        // if we have a pivotLow and a break of its level, we store the breakout and draw the line
        if not na(pivotLow)
            if close < pivotLow.priceLevel           
                array.push(breakouts,breakout.new(pivotLow,volume,BEARISH))                
                drawBreakLine(pivotLow,sellColorInput)
                pivotLow := na                
                
        // Coding trick: avoid the use of drawings like `line` or `box` on unnecesary bars, just plot them on the last bar to smooth script execution
        if barstate.islastconfirmedhistory or barstate.isrealtime

            // Another custom error, this one is to prevent drawing grid (lines) and profile (boxes) when there is no breaks of structure,
            // this will happen when the user sets a big pivotLengthInput and a small executionLastNBarsInput
            if array.size(breakouts) == 0
                runtime.error('No breaks of structure detected. Please modify `Data Gathering` parameters on the settings window. Ex. smaller `Pivot Length` and/or bigger execution window')

            // we draw both the grid and the volume profile
            drawFullProfile(executionTop,executionBottom,firstExecutionBar)           
            
//---------------------------------------------------------------------------------------------------------------------}