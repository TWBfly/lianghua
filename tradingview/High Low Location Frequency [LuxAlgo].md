// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator('High/Low Location Frequency [LuxAlgo]', 'LuxAlgo - High/Low Location Frequency', overlay = true, max_labels_count = 500, max_lines_count = 500, max_bars_back = 5000)

//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
DAILY                           = 'Hour of Day'
WEEKLY                          = 'Day of Week'
MONTHLY                         = 'Day of Month'
YEARLY                          = 'Month of Year'

GREEN                           = #089981
RED                             = #F23645
SILVER                          = #B2B5BE
GRAY50                          = color.new(color.gray,50)
SILVER80                        = color.new(SILVER,80)

EM_SPACE                        = ' '
EN_SPACE                        = ' '
EN_SPACE3                       = EM_SPACE+EN_SPACE

AUTO                            = 'Auto'
TINY                            = 'Tiny'
SMALL                           = 'Small'
NORMAL                          = 'Normal'
LARGE                           = 'Large'
HUGE                            = 'Huge'

TOP                             = 'Top'
MIDDLE                          = 'Middle'
BOTTOM                          = 'Bottom'

RIGHT                           = 'Right'
CENTER                          = 'Center'
LEFT                            = 'Left'

FILTERS_GROUP                   = 'ADVANCED FILTERS'
DASHBOARD_GROUP                 = 'DASHBOARD'
STYLE_GROUP                     = 'STYLE'

periodTooltip                   = 'Select the period to display. Users can choose between ´Hour of Day´, ´Day of Week´, ´Day of Month´ and ´Month of Year´.'
executionWindowTooltip          = 'Select how many bars (hours, days, or months) will be used to gather data from'
hoursFilterTooltip              = 'Filter which hours of the day exclude from the data. Accepts a list of hours from 0 to 23, separated by commas or spaces. You cannot mix commas or spaces as separators. Choose one.'
daysofweekFilterTooltip         = 'Filter which days of the week to exclude from the data. Accept a list of days from 1 to 5 for tickers not trading on weekends, or from 1 to 7 for tickers trading all week. Choose between commas or spaces as separators, but not both.'
daysofmonthFilterTooltip        = 'Filter which days of the month you want to exclude from the data. Just enter a list of days from 1 to 31. You can choose between commas or spaces as a separator, but you can not mix them on the same filter.'
monthsFilterTooltip             = 'Filter months to exclude from data. Accepts months from 1 to 12. Choose one separator: comma or space.'
yearsFilterTooltip              = 'Filter years to exclude from data. Accepts years from 1000 to 2999. Choose one separator: comma or space.'
tableHorizontalPositionTooltip  = 'Select both the vertical and horizontal parameters for the desired location of the dashboard.'
tableSizeTooltip                = 'Select size for dashboard.'
highProbabilityTopColorTooltip  = 'Enable/disable `High Probability Top` vertical and choose color'
highProbabilityBottomColorTooltip = 'Enable/disable `High Probability Bottom` vertical line and choose color'
topLabelSizeTooltip             = 'Enable/disable period top labels, choose color and size.'
bottomLabelSizeTooltip          = 'Enable/disable period bottom labels, choose color and size.'
highlightPeriodColorTooltip     = 'Enable/disable vertical highlight at start of period.'

highProbabilityTopText          = 'High Probability Top Line'+EN_SPACE3

periodInput                     = input.string( DAILY,  'Period',                       tooltip = periodTooltip,            options = [DAILY,WEEKLY,MONTHLY,YEARLY])
executionWindowInput            = input.int(    5000,   'Execution Window',             tooltip = executionWindowTooltip,   maxval = 5000, minval = 10) - 2

hoursFilterInput                = input.string( '',     'Hours of day',                 group=FILTERS_GROUP,        tooltip = hoursFilterTooltip)
daysofweekFilterInput           = input.string( '',     'Days of week',                 group=FILTERS_GROUP,        tooltip = daysofweekFilterTooltip)
daysofmonthFilterInput          = input.string( '',     'Days of month',                group=FILTERS_GROUP,        tooltip = daysofmonthFilterTooltip)
monthsFilterInput               = input.string( '',     'Months',                       group=FILTERS_GROUP,        tooltip = monthsFilterTooltip)
yearsFilterInput                = input.string( '',     'Years',                        group=FILTERS_GROUP,        tooltip = yearsFilterTooltip)

tableVerticalPositionInput      = input.string( TOP,    'Dashboard Location',           group = DASHBOARD_GROUP,    tooltip = '',                               inline = 'location',    options = [TOP,MIDDLE,BOTTOM])
tableHorizontalPositionInput    = input.string( RIGHT,  '',                             group = DASHBOARD_GROUP,    tooltip = tableHorizontalPositionTooltip,   inline = 'location',    options = [RIGHT,CENTER,LEFT])
tableSizeInput                  = input.string( SMALL,  'Dashboard Size',               group = DASHBOARD_GROUP,    tooltip = tableSizeTooltip,                 options = [AUTO,TINY,SMALL,NORMAL,LARGE,HUGE])

highProbabilityTopInput         = input.bool(   true,   highProbabilityTopText,         group = STYLE_GROUP,        tooltip = '',                               inline = 'topLine')
highProbabilityTopColorInput    = input.color(  RED,    '',                             group = STYLE_GROUP,        tooltip = highProbabilityTopColorTooltip,   inline = 'topLine')
highProbabilityBottomInput      = input.bool(   true,   'High Probability Bottom Line', group = STYLE_GROUP,        tooltip = '',                               inline = 'bottomLine')
highProbabilityBottomColorInput = input.color(  GREEN,  '',                             group = STYLE_GROUP,        tooltip = highProbabilityBottomColorTooltip,inline = 'bottomLine')
topLabelInput                   = input.bool(   true,   'Top Label'+EN_SPACE3,          group = STYLE_GROUP,        tooltip = '',                               inline = 'topLabel')
topLabelColorInput              = input.color(  RED,    '',                             group = STYLE_GROUP,        tooltip = '',                               inline = 'topLabel')
topLabelSizeInput               = input.string( SMALL,  '',                             group = STYLE_GROUP,        tooltip = topLabelSizeTooltip,              inline = 'topLabel',    options = [AUTO,TINY,SMALL,NORMAL,LARGE,HUGE])
bottomLabelInput                = input.bool(   true,   'Bottom Label',                 group = STYLE_GROUP,        tooltip = '',                               inline = 'bottomLabel')
bottomLabelColorInput           = input.color(  GREEN,  '',                             group = STYLE_GROUP,        tooltip = '',                               inline = 'bottomLabel')
bottomLabelSizeInput            = input.string( SMALL,  '',                             group = STYLE_GROUP,        tooltip = bottomLabelSizeTooltip,           inline = 'bottomLabel', options = [AUTO,TINY,SMALL,NORMAL,LARGE,HUGE])
highlightPeriodInput            = input.bool(   true,   'Highlight Period Changes',     group = STYLE_GROUP,        tooltip = '',                               inline = 'highlight')
highlightPeriodColorInput       = input.color(  GRAY50, '',                             group = STYLE_GROUP,        tooltip = highlightPeriodColorTooltip,      inline = 'highlight')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
// @variable                        regex to match a list of hours separated by spaces
var string hoursRegexSpace          = '^(2[0-3]|1[0-9]|[0-9])?(\\s[0-9]|\\s1[0-9]|\\s2[0-3])*$'
// @variable                        regex to match a list of hours separated by commas
var string hoursRegexComma          = '^(2[0-3]|1[0-9]|[0-9])?(,[0-9]|,1[0-9]|,2[0-3])*$'
// @variable                        regex to match a list of days of week separated by spaces
var string daysofweekRegexSpace     = '^[1-7]?(\\s[1-7])*$'
// @variable                        regex to match a list of days of week separated by commas
var string daysofweekRegexComma     = '^[1-7]?(,[1-7])*$'
// @variable                        regex to match a list of days of month separated by spaces
var string daysofmonthRegexSpace    = '^(3[0-1]|2[0-9]|1[0-9]|[1-9])?(\\s[1-9]|\\s1[0-9]|\\s2[0-9]|\\s3[0-1])*$'
// @variable                        regex to match a list of days of month separated by commas
var string daysofmonthRegexComma    = '^(3[0-1]|2[0-9]|1[0-9]|[1-9])?(,[1-9]|,1[0-9]|,2[0-9]|,3[0-1])*$'
// @variable                        regex to match a list of months separated by spaces
var string monthsRegexSpace         = '^(1[0-2]|[1-9])?(\\s[1-9]|\\s1[0-2]|)*$'
// @variable                        regex to match a list of months separated by commas
var string monthsRegexComma         = '^(1[0-2]|[1-9])?(,[1-9]|,1[0-2]|)*$'
// @variable                        regex to match a list of years separated by spaces
var string yearsRegexSpace          = '^([1-2][0-9][0-9][0-9])?(\\s[1-2][0-9][0-9][0-9])*$'
// @variable                        regex to match a list of years separated by commas
var string yearsRegexComma          = '^([1-2][0-9][0-9][0-9])?(,[1-2][0-9][0-9][0-9])*$'

// @function            helper function to get an array<string> from input string parsed with regex
// @param filterInput   (string) user input
// @param regexSpace    (string) regex for spaces list
// @param regexComma    (string) regex for commas list
// @returns             array<string> ID
getFilter(string filterInput,string regexSpace, string regexComma) =>
    string spaceFilter      = str.match(filterInput, regexSpace)
    string commaFilter      = str.match(filterInput, regexComma)
    array<string> output    = array.new<string>()

    if not na(spaceFilter)
        if str.length(spaceFilter) > 0
            output := str.split(spaceFilter, ' ')
    else if not na(commaFilter)
        if str.length(commaFilter) > 0
            output := str.split(commaFilter, ',')

    output

// @variable                        array representing hours to filter
var array<string> hoursFilter       = getFilter(hoursFilterInput,       hoursRegexSpace,        hoursRegexComma)
// @variable                        array representing days of week to filter
var array<string> daysofweekFilter  = getFilter(daysofweekFilterInput,  daysofweekRegexSpace,   daysofweekRegexComma)
// @variable                        array representing days of month to filter
var array<string> daysofmonthFilter = getFilter(daysofmonthFilterInput, daysofmonthRegexSpace,  daysofmonthRegexComma)
// @variable                        array representing months to filter
var array<string> monthsFilter      = getFilter(monthsFilterInput,      monthsRegexSpace,       monthsRegexComma)
// @variable                        array representing years to filter
var array<string> yearsFilter       = getFilter(yearsFilterInput,       yearsRegexSpace,        yearsRegexComma)

// @variable            dashboard position on the chart
var tablePosition       = switch tableVerticalPositionInput + tableHorizontalPositionInput
    TOP     + RIGHT     => position.top_right
    TOP     + CENTER    => position.top_center
    TOP     + LEFT      => position.top_left
    MIDDLE  + RIGHT     => position.middle_right
    MIDDLE  + CENTER    => position.middle_center
    MIDDLE  + LEFT      => position.middle_left
    BOTTOM  + RIGHT     => position.bottom_right
    BOTTOM  + CENTER    => position.bottom_center
    BOTTOM  + LEFT      => position.bottom_left

// @variable            dashboard size
var tableSize           = switch tableSizeInput
    AUTO                => size.auto
    TINY                => size.tiny
    SMALL               => size.small
    NORMAL              => size.normal
    LARGE               => size.large
    HUGE                => size.huge

// @variable            top labels size
var topLabelSize        = switch topLabelSizeInput
    AUTO                => size.auto
    TINY                => size.tiny
    SMALL               => size.small
    NORMAL              => size.normal
    LARGE               => size.large
    HUGE                => size.huge
    
// @variable            bottom labels size
var bottomLabelSize     = switch bottomLabelSizeInput
    AUTO                => size.auto
    TINY                => size.tiny
    SMALL               => size.small
    NORMAL              => size.normal
    LARGE               => size.large
    HUGE                => size.huge
    
// @type                UDT to store top and bottom period extremes (labels)
// @field top           top price
// @field bottom        bottom price
// @field topTime       top bar time   
// @field bottomTime    bottom bar time
type trailingExtremes
    float   top
    float   bottom
    int     topTime
    int     bottomTime

// @variable                                array to store trailingExtremes UDTs
var trailingExtremes trailing               = trailingExtremes.new()

// @variable                                day of week
parsedDayofweek                             = dayofweek(time_tradingday)
// @variable                                week of year
parsedWeekofyear                            = syminfo.type == 'crypto' ? weekofyear : weekofyear(time_close)
// @variable                                day of month
parsedDayofmonth                            = syminfo.type == 'crypto' ? dayofmonth : dayofmonth(time_close)
// @variable                                month
parsedMonth                                 = syminfo.type == 'crypto' ? month      : month(time_close)
// @variable                                year
parsedYear                                  = syminfo.type == 'crypto' ? year       : year(time_close)

// @variable                                period for top/bottom extremes (labels)
extremeLabelsPeriod                         = switch periodInput
    DAILY                                   => parsedDayofweek
    WEEKLY                                  => parsedWeekofyear
    MONTHLY                                 => parsedMonth
    YEARLY                                  => parsedYear

// @variable                                several dashboard variables (table)
[columns,rows,dataRows,columnTag,headerTag] = switch periodInput
    DAILY                                   => [7,  16, 2, 'HOUR',  'DAYS']
    WEEKLY                                  => [3,  11, 1, 'DAY',   'WEEKS']
    MONTHLY                                 => [11, 16, 3, 'DAY',   'MONTHS']
    YEARLY                                  => [3,  16, 1, 'MONTH', 'YEARS']

// @variable                                true if current bar must be highlighted (change background)
var bool highlightBackground                = false

if highlightPeriodInput
    highlightBackground                     := switch periodInput
        DAILY                               => ta.change(parsedDayofweek)
        WEEKLY                              => ta.change(parsedWeekofyear)
        MONTHLY                             => ta.change(parsedMonth)
        YEARLY                              => ta.change(parsedYear)

// @variable                                helper array for months with 30 days
var array<int> monthsWith30Days             = array.from(4,6,9,11)

// @function            helper function to identify a leap year
// @param y_ear         (int) year to check
// @returns             bool
isLeapYear(int y_ear) => (y_ear % 4 == 0 and y_ear % 100 != 0) or y_ear % 400 == 0

// @variable            fix for february: 30 days + leapYearFebFix
leapYearFebFix          = isLeapYear(parsedYear) ? -1 : -2
// @variable            fix for days in month from a base month of 30 days
monthFix                = parsedMonth == 2 ? (isLeapYear(parsedYear) ? -1 : -2) : monthsWith30Days.includes(parsedMonth) ? 0 : 1

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
// @function                true if values are not included in any filter
// @param customPeriod      (int) current period from security context
// @param p_arsedDayofweek  (int) day of week
// @param p_arsedDayofmonth (int) day of month
// @param p_arsedMonth      (int) month
// @param p_arsedYear       (int) year
// @returns                 bool
allFiltersPass(int customPeriod, int p_arsedDayofweek, int p_arsedDayofmonth,int p_arsedMonth,int p_arsedYear) =>
    varip bool output   = true
    output              := true
    
    if periodInput == DAILY
        parsedHour1 = customPeriod
        if hoursFilter.includes(str.tostring(parsedHour1))
            output := false            

    if periodInput != YEARLY
        parsedDayofweek1    = periodInput == WEEKLY     ? customPeriod : p_arsedDayofweek
        parsedDayofmonth1   = periodInput == MONTHLY    ? customPeriod : p_arsedDayofmonth       
        if daysofweekFilter.includes(str.tostring(parsedDayofweek1))
            output := false

        if daysofmonthFilter.includes(str.tostring(parsedDayofmonth1))
            output := false            

    parsedMonth1    = periodInput == MONTHLY ? customPeriod : p_arsedMonth
    parsedYear1     = p_arsedYear

    if monthsFilter.includes(str.tostring(parsedMonth1))
        output := false

    if yearsFilter.includes(str.tostring(parsedYear1))
        output := false        

    output

// @function                    inner function to fetch data from security context, it iterates thru bars with a reverse loop in a single execution
// @param firstBar              (int) first index for loop
// @param period                (int) period to check
// @param executionCondition    (int) reset condition 
// @param startKey              (int) start key for tops/bottoms arrays
// @param endKey                (int) end key for tops/bottoms arrays
// @returns                     tuple
dataLoop(int firstBar = 4998, int period = hour, int executionCondition = time_tradingday, int startKey = 0, int endKey = 23) =>
    varip int initialTime       = time    
    varip bool executed         = false
    varip map<int,int> tops     = map.new<int,int>()
    varip map<int,int> bottoms  = map.new<int,int>()
    var int voidInt             = na
    var map<int,int> voidMap    = na

    if barstate.isfirst        
        for index = startKey to endKey
            tops.put(   index, 0)
            bottoms.put(index, 0)

    if barstate.islast and not executed        
        executed            := true
        var parsedFirstBar  = math.min(firstBar,last_bar_index)
        initialTime         := time[parsedFirstBar]
        var h_igh           = high[parsedFirstBar]
        var l_ow            = low[parsedFirstBar]
        var periodTop       = period[parsedFirstBar]
        var periodBottom    = period[parsedFirstBar]

        for index = parsedFirstBar to 0
            if executionCondition[index] != executionCondition[index + 1]
                if allFiltersPass(periodTop, parsedDayofweek[index], parsedDayofmonth[index], parsedMonth[index], parsedYear[index])
                    tops.put(periodTop, tops.get(periodTop) + 1)
                    
                if allFiltersPass(periodBottom, parsedDayofweek[index], parsedDayofmonth[index], parsedMonth[index], parsedYear[index])
                    bottoms.put(periodBottom, bottoms.get(periodBottom) + 1)
                    
                h_igh           := high[index]
                l_ow            := low[index]
                periodTop       := period[index]
                periodBottom    := period[index]
            else
                if high[index]  > h_igh
                    h_igh       := high[index]
                    periodTop   := period[index]
                if low[index]   < l_ow
                    l_ow        := low[index]
                    periodBottom := period[index]                                     

    if barstate.islast
        [initialTime, tops, bottoms]
    else
        [voidInt, voidMap, voidMap]

// @function            wrapper for security call with params for security inner function
// @param timeFrame     (string) timeframe for security context
// @param period        (int) period to check
// @param condition     (int) reset condition 
// @param startKey      (int) start key for tops/bottoms arrays
// @param endKey        (int) end key for tops/bottoms arrays
// @returns             tuple
securityWrapper(string timeFrame, int period, int condition, int startKey = 0, int endKey = 23) => request.security(syminfo.tickerid, timeFrame, dataLoop(executionWindowInput, period, condition, startKey, endKey))

// @function            helper function to get a string representing all active filters
// @returns             string
filtersTag() =>
    string output = ''

    if hoursFilter.size()       > 0
        output := 'H '
    if daysofweekFilter.size()  > 0
        output := output + 'DW '
    if daysofmonthFilter.size() > 0
        output := output + 'DM '
    if monthsFilter.size()      > 0
        output := output + 'M '
    if yearsFilter.size()       > 0
        output := output + 'Y'

    output

// @function            draw a new cell
// @param t_able        (table) The cell is in this table
// @param column        (int) column
// @param row           (int) row
// @param cellText      (string) text to display
// @param background    (color) background color
// @returns             void
drawCell(table t_able, int column, int row, string cellText, color background = na) => t_able.cell(column, row, cellText, text_color = chart.fg_color, text_halign = text.align_center, bgcolor = background, text_size = tableSize)// , text_font_family = font.family_monospace)

// @function            draw table header
// @param t_able        (table) Header cells are in this table
// @param occurrences   (int) number of periods
// @param initialTime   (int) initial time from when the data is retrieved
// @returns             type
drawHeader(table t_able,int occurrences, int initialTime) =>
    t_able.merge_cells(0, 0, columns - 1, 0)
    t_able.merge_cells(0, 1, columns - 1, 1)
    t_able.merge_cells(0, 2, columns - 1, 2)

    drawCell(t_able, 0, 0, 'HIGH/LOW LOCATION FREQUENCY')        
    string headerInfo = str.tostring(occurrences)+' '+headerTag+' since '+str.format_time(initialTime, "dd MMM yyyy")
    string filtersTag = filtersTag()
    if str.length(filtersTag) > 0
        headerInfo := headerInfo + '\nFilters: '+filtersTag
    drawCell(t_able, 0, 1, headerInfo)
    drawCell(t_able, 0, 2, '-')
    t_able.cell(0, 2 , '-', text_color = SILVER, bgcolor = SILVER, text_size = size.tiny)
   
    drawCell(t_able, 0, 3, columnTag,   SILVER80)
    drawCell(t_able, 1, 3, 'HIGH %',    SILVER80)
    drawCell(t_able, 2, 3, 'LOW %',     SILVER80)

    if dataRows > 1
        drawCell(t_able, 3, 3, '',          SILVER80)
        drawCell(t_able, 4, 3, columnTag,   SILVER80)
        drawCell(t_able, 5, 3, 'HIGH %',    SILVER80)
        drawCell(t_able, 6, 3, 'LOW %',     SILVER80)

        if dataRows > 2
            drawCell(t_able, 7, 3, '',          SILVER80)
            drawCell(t_able, 8, 3, columnTag,   SILVER80)
            drawCell(t_able, 9, 3, 'HIGH %',    SILVER80)
            drawCell(t_able, 10,3, 'LOW %',     SILVER80)

// @function            helper function to fix the position of data cells on a double column
// @param key           (int) key to display  
// @returns             tuple
doubleColumn(int key) => 
    if key > 11
        [4, -12]
    else
        [0, 0]

// @function            helper function to fix the position of data cells on a triple column
// @param key           (int) key to display  
// @returns             tuple
tripleColumn(int key) => 
    if key > 22
        [8, -22]
    else if key > 11
        [4, -11]
    else
        [0, 0]

// @function            helper function to get day of week as string from an int
// @param d_ayofweek    (int) day of week
// @returns             string
dayofweekString(int d_ayofweek) =>
    if syminfo.type == 'crypto'
        switch d_ayofweek
            1   => 'SUN'
            2   => 'MON'
            3   => 'TUE'
            4   => 'WED'
            5   => 'THU'
            6   => 'FRI'
            7   => 'SAT'
    else
        switch d_ayofweek
            1   => 'MON'
            2   => 'TUE'
            3   => 'WED'
            4   => 'THU'
            5   => 'FRI'

// @function            helper function to get month as string from an int
// @param m_onth        (int) month
// @returns             string
monthString(int m_onth) =>    
    switch m_onth
        1   => 'JAN'
        2   => 'FEB'
        3   => 'MAR'
        4   => 'APR'
        5   => 'MAY'
        6   => 'JUN'
        7   => 'JUL'
        8   => 'AUG'
        9   => 'SEP'
        10  => 'OCT'
        11  => 'NOV'
        12  => 'DEC'        

// @function            draw dashboard (table)
// @param initialTime   (int) initial time from when the data is retrieved
// @param tops          (map) data to display (tops)
// @param bottoms       (map) data to display (bottoms)
// @returns             void
drawTable(int initialTime, map<int,int> tops, map<int,int>  bottoms) =>    
    var table t_able    = table.new(tablePosition, columns, rows, chart.bg_color, SILVER, 2)    
    totalTops           = tops.values().sum()
    totalBottoms        = bottoms.values().sum()

    drawHeader(t_able, totalTops, initialTime)

    for [index,eachKey] in tops.keys()
        probabilityTop      = (tops.get(eachKey) / totalTops)
        probabilityBottom   = (bottoms.get(eachKey) / totalBottoms)       
        [columnFix,rowFix]  = switch dataRows
            1 => [0, 0]
            2 => doubleColumn(eachKey)
            3 => tripleColumn(eachKey)

        string rowTag = periodInput == WEEKLY ? dayofweekString(eachKey) : periodInput == YEARLY ? monthString(eachKey) : str.tostring(eachKey)
        drawCell(t_able, 0 + columnFix, index + 4 + rowFix, rowTag,SILVER80)
        drawCell(t_able, 1 + columnFix, index + 4 + rowFix, probabilityTop      > 0 ? str.format('{0,number,0.00%}', probabilityTop)    : '')
        drawCell(t_able, 2 + columnFix, index + 4 + rowFix, probabilityBottom   > 0 ? str.format('{0,number,0.00%}', probabilityBottom) : '')
        
// @function            update horizontal line time coordinates
// @param l_ine         (line) line to update
// @param t_ime         (time) bar time
// @returns             void
drawHorizontalLine(line l_ine, int t_ime) =>
    l_ine.set_first_point(  chart.point.new(t_ime, na, close))
    l_ine.set_second_point( chart.point.new(t_ime, na, close + syminfo.mintick))

// @function            calculate and update line time coordinate
// @param l_ine         (line) line to update
// @param m_ap          (map) data for calculations
// @returns             void
drawLine(line l_ine, map<int,int> m_ap) =>
    millisecondsHour        = 1000 * 60 * 60
    millisecondsDay         = millisecondsHour * 24
    highProbabilityPeriod   = m_ap.keys().get(m_ap.values().indexof(m_ap.values().max()))    

    switch periodInput
        DAILY =>
            if timeframe.in_seconds() <= timeframe.in_seconds('60')            
                delta       = highProbabilityPeriod - hour                
                t_ime       = delta == 0 ? 0 : ((delta > 0 ? 0 : millisecondsDay) + millisecondsHour * delta)                
                parsedTime  = timestamp(parsedYear, parsedMonth, parsedDayofmonth, hour, 0, 0) + t_ime
                drawHorizontalLine(l_ine, parsedTime)
                
        WEEKLY => 
            if timeframe.in_seconds() <= timeframe.in_seconds('D')
                delta       = highProbabilityPeriod - parsedDayofweek                
                t_ime       = delta == 0 ? 0 : ((delta > 0 ? 0 : millisecondsDay * 7) + millisecondsDay * delta)
                parsedTime  = time_tradingday + t_ime
                drawHorizontalLine(l_ine, parsedTime)
                
        MONTHLY =>
            if timeframe.in_seconds() <= timeframe.in_seconds('D')                
                nextParsedMonth = highProbabilityPeriod >= parsedDayofmonth ? parsedMonth : parsedMonth == 12 ? 1 : parsedMonth + 1
                nextParsedYear = highProbabilityPeriod >= parsedDayofmonth ? parsedYear : parsedMonth == 12 ? parsedYear + 1 : parsedYear
                goodParsedTime      = timestamp(nextParsedYear, nextParsedMonth, highProbabilityPeriod, hour(time_tradingday), minute(time_tradingday), 0)                
                drawHorizontalLine(l_ine, goodParsedTime)
                
        YEARLY =>
            if timeframe.in_seconds() <= timeframe.in_seconds('M')                                
                nextYearFix    = highProbabilityPeriod >= parsedMonth ? 0 : 1
                goodParsedTime      = timestamp(parsedYear + nextYearFix, highProbabilityPeriod, 1, hour(time_tradingday), minute(time_tradingday), 0)                
                drawHorizontalLine(l_ine, goodParsedTime)
                                
// @function            draw two horizontal lines to mark the next high probability period (for top and bottom)
// @param tops          (map) data to calculations (tops)
// @param bottoms       (map) data to calculations (bottoms)
// @returns             void
drawLines(map<int,int> tops, map<int,int>  bottoms) =>
    var line topLine    = line.new(na, na, na, na, xloc = xloc.bar_time, extend = extend.both, width = 4, color = highProbabilityTopColorInput)
    var line bottomLine = line.new(na, na, na, na, xloc = xloc.bar_time, extend = extend.both, width = 4, color = highProbabilityBottomColorInput)

    if highProbabilityTopInput
        log.info('\nTOP')
        drawLine(topLine,   tops)
    if highProbabilityBottomInput
        log.info('\nBOTTOM')
        drawLine(bottomLine,bottoms)

// @function            helper function to update a label
// @param l_abel        (label) label to update
// @param labelPrice    (float) price
// @param labelTime     (int) bar time
// @returns             type
updateLabel(label l_abel,float labelPrice, int labelTime) =>
    l_abel.set_point(chart.point.new(labelTime, na, labelPrice))
    l_abel.set_text(str.format('{0}\n{1}',math.round_to_mintick(labelPrice), str.format_time(labelTime, "yyyy-MM-dd HH:mm", syminfo.timezone)))    

// @function            helper function to create a new label
// @param labelColor    (color) text color
// @param labelStyle    (string) label style
// @param labelSize     (string) text size
// @returns             label ID
newLabel(color labelColor, string labelStyle, string labelSize) => label.new(na, na, xloc = xloc.bar_time, color = color(na), textcolor = labelColor, style = labelStyle, size = labelSize)

// @function            draw labels at each period top and bottom
// @param period        (int) period to use
// @returns             void
drawExtremsLabels(int period) =>
    var topLabel    = newLabel(topLabelColorInput,      label.style_label_down, topLabelSize)
    var bottomLabel = newLabel(bottomLabelColorInput,   label.style_label_up,   bottomLabelSize)

    if ta.change(period)
        topLabel    := newLabel(topLabelColorInput,     label.style_label_down, topLabelSize)
        bottomLabel := newLabel(bottomLabelColorInput,  label.style_label_up,   bottomLabelSize)

        trailing.top        := high
        trailing.bottom     := low
        trailing.topTime    := time
        trailing.bottomTime := time
    else
        if high > trailing.top
            trailing.top        := high
            trailing.topTime    := time
        if low < trailing.bottom
            trailing.bottom     := low
            trailing.bottomTime := time

    if topLabelInput
        updateLabel(topLabel,   trailing.top,   trailing.topTime)
    
    if bottomLabelInput
        updateLabel(bottomLabel,trailing.bottom,trailing.bottomTime)

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast
    // we fetch the data
    [initialTime,tops,bottoms] = switch periodInput
        DAILY   => securityWrapper('60',hour,                       time_tradingday)        
        WEEKLY  => securityWrapper('D', dayofweek(time_tradingday), parsedWeekofyear,   1, syminfo.type == 'crypto' ? 7 : 5)
        MONTHLY => securityWrapper('D', parsedDayofmonth,           parsedMonth,        1, 31) 
        YEARLY  => securityWrapper('M', parsedMonth,                parsedYear,         1, 12)
    
    if not na(tops)
        // we draw dashboard
        drawTable(initialTime, tops, bottoms)
        // we draw high probability horizontal lines        
        drawLines(tops, bottoms)

if topLabelInput or bottomLabelInput
    // we draw labels at each period top and bottom
    drawExtremsLabels(extremeLabelsPeriod)

// we highlight each new period
bgcolor(highlightBackground ? highlightPeriodColorInput : na)

//---------------------------------------------------------------------------------------------------------------------}