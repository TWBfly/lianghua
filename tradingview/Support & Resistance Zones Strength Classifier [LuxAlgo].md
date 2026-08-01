// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Support & Resistance Zones Strength Classifier [LuxAlgo]", "LuxAlgo - S&R Zones", overlay = true, max_boxes_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Inputs
//---------------------------------------------------------------------------------------------------------------------{
color BULL_COLOR = #089981
color BEAR_COLOR = #f23645

// --- Calculation Inputs ---
pivotLenInput       = input.int(10, "Pivot Lookback", minval = 2, group = "Calculation", tooltip = "Number of bars on each side of the pivot.")
zoneMultInput        = input.float(2.0, "Zone Width (dist Multiplier)", minval = 0.1, step = 0.1, group = "Calculation", tooltip = "Determines the vertical thickness of the S&R zones based on dist.")
minTestsInput        = input.int(2, "Minimum Tests to Highlight", minval = 1, group = "Calculation", tooltip = "Only show zones that have been tested at least this many times.")
maxZonesInput        = input.int(10, "Max Active Zones Per Type", minval = 1, maxval = 50, group = "Calculation", tooltip = "Limits the number of support and resistance zones displayed on the chart.")
maxHeightMultInput   = input.float(10.0, "Max Zone Height (dist Multiplier)", minval = 1.0, step = 0.5, group = "Calculation", tooltip = "If a zone becomes wider than this (due to merging), it will be deleted.")

// --- Visual Inputs ---
supportColorInput    = input.color(BULL_COLOR, "Support Color", group = "Visuals")
resistanceColorInput = input.color(BEAR_COLOR, "Resistance Color", group = "Visuals")
showLabelsInput      = input.bool(true, "Show Test Count Labels", group = "Visuals", tooltip = "Display labels showing many times a zone has been tested.")
extendZonesInput     = input.bool(true, "Extend Zones to Right", group = "Visuals", tooltip = "Extend the zone boxes to the current bar.")

//---------------------------------------------------------------------------------------------------------------------}
// Types & Collections
//---------------------------------------------------------------------------------------------------------------------{
type Zone
    float top
    float bottom
    int   testCount
    bool  isSupport
    int   startTime
    box   boxId
    label labelId
    line  lineId
    bool  isBroken
    int   mergeCount

var Zone[] supportZones    = array.new<Zone>()
var Zone[] resistanceZones = array.new<Zone>()


//---------------------------------------------------------------------------------------------------------------------}
// Methods & Functions
//---------------------------------------------------------------------------------------------------------------------{
// Method to check if a zone is broken by price close
// Method to check if a zone is broken by price close
method checkBreak(Zone self, float priceClose) =>
    if not self.isBroken
        if self.isSupport and priceClose < self.bottom
            self.isBroken := true
        else if not self.isSupport and priceClose > self.top
            self.isBroken := true
    self.isBroken

// Method to update visual objects of a zone
method updateVisuals(Zone self, int currentTime, int barDuration, color zoneColor) =>
    if not na(self.boxId)
        box.set_right(self.boxId, currentTime)
        box.set_bgcolor(self.boxId, color.new(zoneColor, self.testCount >= minTestsInput ? 80 : 95))
        box.set_border_color(self.boxId, na)
        
        if showLabelsInput and not na(self.labelId)
            label.set_x(self.labelId, currentTime + barDuration * 2)
            label.set_text(self.labelId, str.tostring(self.testCount))
            label.set_y(self.labelId, (self.top + self.bottom) / 2)
            label.set_textcolor(self.labelId, self.testCount >= minTestsInput ? zoneColor : na)
            label.set_style(self.labelId, label.style_label_left)
            label.set_tooltip(self.labelId, "Merges: " + str.tostring(self.mergeCount))
        
        if not na(self.lineId)
            line.set_x2(self.lineId, currentTime)
            line.set_color(self.lineId, color.new(zoneColor, self.testCount >= minTestsInput ? 50 : 80))

// Function to manage and add zones
manageZones(Zone[] zones, float price, bool isSupport, float width, color zoneColor) =>
    bool found = false
    int currentBarTime = time
    int barDuration = time - time[1]
    
    // Check for existing zones within proximity
    for z in zones
        if price <= z.top and price >= z.bottom
            z.testCount += 1
            found := true
            break
            
    // If no existing zone found, create new one
    if not found
        float top    = isSupport ? price + width / 2 : price + width
        float bottom = isSupport ? price - width : price - width / 2
        int startTime = time[pivotLenInput]
        
        box   b = box.new(startTime, top, time, bottom, 
                         xloc = xloc.bar_time,
                         bgcolor = color.new(zoneColor, 95), 
                         border_color = na)
                         
        label l = showLabelsInput ? label.new(time + barDuration * 2, (top + bottom) / 2, "1", 
                                             xloc = xloc.bar_time,
                                             color = #00000000, 
                                             style = label.style_label_left,
                                             textcolor = 1 >= minTestsInput ? zoneColor : na,
                                             size = size.small) : na
        
        line  li = line.new(startTime, (top + bottom) / 2, time, (top + bottom) / 2, 
                            xloc = xloc.bar_time, 
                            style = line.style_dashed, 
                            color = color.new(zoneColor, 80))
                                             
        array.unshift(zones, Zone.new(top, bottom, 1, isSupport, startTime, b, l, li, false, 0))
        
        // Trim array to keep only maxZonesInput
        if array.size(zones) > maxZonesInput
            Zone old = array.pop(zones)
            box.delete(old.boxId)
            label.delete(old.labelId)
            line.delete(old.lineId)

// Function to merge overlapping zones
mergeZones(Zone[] zones, float maxHeight) =>
    int i = 0
    while i < array.size(zones)
        Zone z1 = array.get(zones, i)
        int j = i + 1
        bool merged = false
        while j < array.size(zones)
            Zone z2 = array.get(zones, j)
            // Check for overlap
            if not (z1.bottom > z2.top or z1.top < z2.bottom)
                // Merge z2 into z1
                z1.top := math.max(z1.top, z2.top)
                z1.bottom := math.min(z1.bottom, z2.bottom)
                z1.testCount += z2.testCount
                z1.mergeCount += z2.mergeCount + 1
                // Anchor to the oldest pivot in the merge
                z1.startTime := math.min(z1.startTime, z2.startTime)
                
                // Update visuals of z1 to reflect new boundaries
                if not na(z1.boxId)
                    box.set_top(z1.boxId, z1.top)
                    box.set_bottom(z1.boxId, z1.bottom)
                    box.set_left(z1.boxId, z1.startTime)
                
                if not na(z1.lineId)
                    line.set_y1(z1.lineId, (z1.top + z1.bottom) / 2)
                    line.set_y2(z1.lineId, (z1.top + z1.bottom) / 2)
                    line.set_x1(z1.lineId, z1.startTime)


                // Delete z2 visuals and remove from collection
                box.delete(z2.boxId)
                label.delete(z2.labelId)
                line.delete(z2.lineId)

                array.remove(zones, j)
                merged := true
            else
                j += 1
        
        // After merging, check if the combined zone is too wide
        if (z1.top - z1.bottom) > maxHeight
            box.delete(z1.boxId)
            label.delete(z1.labelId)
            line.delete(z1.lineId)

            array.remove(zones, i)
            continue // Index shifted, don't increment i
            
        if merged
            continue
        i += 1

//---------------------------------------------------------------------------------------------------------------------}
// Main Logic
//---------------------------------------------------------------------------------------------------------------------{
float dist = ta.cum(math.abs(high-low)) / (bar_index+1)
float zoneWidth = (na(dist) ? close * 0.01 : dist) * zoneMultInput

float ph = ta.pivothigh(pivotLenInput, pivotLenInput)
float pl = ta.pivotlow(pivotLenInput, pivotLenInput)

// Handle Resistance (Pivot Highs)
if not na(ph)
    manageZones(resistanceZones, ph, false, zoneWidth, resistanceColorInput)
    mergeZones(resistanceZones, dist * maxHeightMultInput)

// Handle Support (Pivot Lows)
if not na(pl)
    manageZones(supportZones, pl, true, zoneWidth, supportColorInput)
    mergeZones(supportZones, dist * maxHeightMultInput)

// Check for breaks and update all zones
if array.size(supportZones) > 0
    for i = array.size(supportZones) - 1 to 0
        Zone z = array.get(supportZones, i)
        if z.checkBreak(close)
            box.delete(z.boxId)
            label.delete(z.labelId)
            line.delete(z.lineId)

            array.remove(supportZones, i)
        else if barstate.islast
            z.updateVisuals(time, time - time[1], supportColorInput)

if array.size(resistanceZones) > 0
    for i = array.size(resistanceZones) - 1 to 0
        Zone z = array.get(resistanceZones, i)
        if z.checkBreak(close)
            box.delete(z.boxId)
            label.delete(z.labelId)
            line.delete(z.lineId)

            array.remove(resistanceZones, i)
        else if barstate.islast
            z.updateVisuals(time, time - time[1], resistanceColorInput)

//---------------------------------------------------------------------------------------------------------------------}
