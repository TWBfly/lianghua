// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Temporal Volume Profile 3D [LuxAlgo]", "LuxAlgo - Temporal VP 3D", overlay = false, max_polylines_count = 100, max_lines_count = 500, max_labels_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Groups & Inputs
//---------------------------------------------------------------------------------------------------------------------{
const string GRP_TERRAIN = "Volume Profile & Matrix"
const string GRP_CAMERA  = "Camera Projection"
const string GRP_STYLE   = "Style & Colors"

// Terrain Settings
int lookback    = input.int(250, "Lookback Bars", group = GRP_TERRAIN, minval = 50, maxval = 500, tooltip = "Total bars of historical volume to analyze.")
int priceBins   = input.int(45, "Price Bins (Width)", group = GRP_TERRAIN, minval = 10, maxval = 70, tooltip = "Number of horizontal price levels (X-axis).")
int timeSteps   = input.int(25, "Time Slices (Depth)", group = GRP_TERRAIN, minval = 5, maxval = 30, tooltip = "Number of time segments to divide the volume into (Y-axis).")
int smoothLen   = input.int(2,  "Terrain Smoothing", group = GRP_TERRAIN, minval = 0, maxval = 4, tooltip = "Blends adjacent volume nodes for a smoother landscape.")

// Camera Settings
float yawDeg   = input.float(35, "Yaw (°)", group = GRP_CAMERA, minval = -89, maxval = 89, tooltip = "Rotates the landscape left or right.")
float pitchDeg = input.float(40, "Pitch (°)", group = GRP_CAMERA, minval = 0, maxval = 89, tooltip = "Tilts the landscape up or down.")
float scaleX   = input.float(3.0, "Scale X (Width)", group = GRP_CAMERA, step = 0.1)
float scaleY   = input.float(3.0, "Scale Y (Depth)", group = GRP_CAMERA, step = 0.1)
float scaleZ   = input.float(2.0, "Scale Z (Height)", group = GRP_CAMERA, step = 0.1)
int   offsetX  = input.int(0, "Offset X (Bars Left/Right)", group = GRP_CAMERA, tooltip = "Moves the entire landscape horizontally.")
float offsetY  = input.float(0, "Offset Y (Price Up/Down)", group = GRP_CAMERA, tooltip = "Moves the entire landscape vertically.")

// Style
bool  showRidgeLines  = input.bool(true, "Show Ridge Lines", group = GRP_STYLE)
bool  showMountainFills = input.bool(true, "Show Mountain Fills", group = GRP_STYLE)
color mountainBg      = input.color(#131722, "Mountain Fill (Chart BG)", group = GRP_STYLE, tooltip = "Set this to match your chart background for a clean 3D overlap effect.")
bool  showPoc         = input.bool(true, "Show POC Ridge Line", group = GRP_STYLE, tooltip = "Highlights the Point of Control (Highest Volume Node) across all time slices.")
bool  showPriceMarker = input.bool(true, "Show Current Price Tracking", group = GRP_STYLE, tooltip = "Highlights the price level of the current close.")
bool  showPeakWarning = input.bool(true, "Show Peak Proximity Warning", group = GRP_STYLE, tooltip = "Changes the color of the price tracker when current price is inside a major volume mountain (High Volume Node).")
int   peakWarnThresh  = input.int(75, "Peak Warning Threshold (%)", group = GRP_STYLE, minval = 1, maxval = 100, tooltip = "Volume percentage required to trigger the proximity warning.")
color warnColor       = input.color(color.new(#FF1744, 0), "Warning Color", group = GRP_STYLE)
color neutralPlane    = input.color(color.new(color.white, 85), "Neutral Plane Color", group = GRP_STYLE)
color pocColor        = input.color(color.new(#FFD600, 0), "POC Line Color", group = GRP_STYLE)

//---------------------------------------------------------------------------------------------------------------------}
// Types & Math Base
//---------------------------------------------------------------------------------------------------------------------{
type Camera
    int anchorX
    float anchorY
    float cYaw
    float sYaw
    float sPit
    float cPit
    float sx
    float sy
    float sz

method project(Camera this, float x, float y, float z) =>
    float xr = x * this.cYaw - y * this.sYaw
    float yr = x * this.sYaw + y * this.cYaw
    float sxp = xr * this.sx
    float syp = yr * this.sPit * this.sy - z * this.cPit * this.sz
    chart.point.from_index(this.anchorX + int(sxp), this.anchorY - syp)

var array<color> depthPalette = array.from(#F9C80E, #F86624, #EA3546, #662E9B, #43BCCD)

f_colorAt(float t) =>
    float u = math.max(0, math.min(1, t))
    float s = u * (depthPalette.size() - 1)
    int i1 = int(math.floor(s))
    int i2 = int(math.ceil(s))
    color.from_gradient(s - i1, 0, 1, depthPalette.get(i1), depthPalette.get(i2))

//---------------------------------------------------------------------------------------------------------------------}
// Data Collection
//---------------------------------------------------------------------------------------------------------------------{
var float[] hArr = array.new_float()
var float[] lArr = array.new_float()
var float[] vArr = array.new_float()

array.unshift(hArr, high)
array.unshift(lArr, low)
array.unshift(vArr, volume)

if array.size(hArr) > 500
    array.pop(hArr)
    array.pop(lArr)
    array.pop(vArr)

//---------------------------------------------------------------------------------------------------------------------}
// 3D Rendering Engine (On Last Bar)
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast
    for p in polyline.all
        p.delete()
    for ln in line.all
        ln.delete()
    for lb in label.all
        lb.delete()
        
    int actualLookback = math.min(lookback, array.size(hArr))
    float maxP = array.max(array.slice(hArr, 0, actualLookback))
    float minP = array.min(array.slice(lArr, 0, actualLookback))
    float binSize = (maxP - minP) / priceBins
    
    // Matrix to store Volume at Price
    // Rows = Time Slices (Y-axis), Cols = Price Bins (X-axis)
    var matrix<float> terrainMap = matrix.new<float>(timeSteps, priceBins, 0.0)
    
    // Distribute Volume
    if binSize > 0
        for t = 0 to actualLookback - 1
            int stepIdx = math.floor(t / (actualLookback / timeSteps))
            int y = timeSteps - 1 - stepIdx // y=0 is oldest (back), y=timeSteps-1 is newest (front)
            y := math.max(0, math.min(timeSteps - 1, y))
            
            float h = array.get(hArr, t)
            float l = array.get(lArr, t)
            float v = array.get(vArr, t)
            
            if h == l
                int bin = math.max(0, math.min(priceBins - 1, int((h - minP) / binSize)))
                terrainMap.set(y, bin, terrainMap.get(y, bin) + v)
            else
                int startBin = math.max(0, int((l - minP) / binSize))
                int endBin = math.min(priceBins - 1, int((h - minP) / binSize))
                int binCount = endBin - startBin + 1
                float vPerBin = v / binCount
                for b = startBin to endBin
                    terrainMap.set(y, b, terrainMap.get(y, b) + vPerBin)
                    
    // Normalize volume to a 0-100 Z-scale
    float maxVol = 0.0
    for y = 0 to timeSteps - 1
        for x = 0 to priceBins - 1
            maxVol := math.max(maxVol, terrainMap.get(y, x))
            
    if maxVol > 0
        for y = 0 to timeSteps - 1
            for x = 0 to priceBins - 1
                terrainMap.set(y, x, (terrainMap.get(y, x) / maxVol) * 100.0)
                
    // Apply Terrain Smoothing
    if smoothLen > 0
        matrix<float> smoothMap = matrix.new<float>(timeSteps, priceBins, 0.0)
        for y = 0 to timeSteps - 1
            for x = 0 to priceBins - 1
                float sum = 0.0
                int count = 0
                for dy = -smoothLen to smoothLen
                    for dx = -smoothLen to smoothLen
                        int ny = y + dy
                        int nx = x + dx
                        if ny >= 0 and ny < timeSteps and nx >= 0 and nx < priceBins
                            sum += terrainMap.get(ny, nx)
                            count += 1
                smoothMap.set(y, x, sum / count)
        terrainMap := smoothMap

    // Camera Setup
    Camera cam = Camera.new(
         anchorX = bar_index - int(priceBins * scaleX * 0.55) + offsetX, 
         anchorY = 50.0 - offsetY, 
         cYaw    = math.cos(yawDeg * math.pi / 180),
         sYaw    = math.sin(yawDeg * math.pi / 180), 
         sPit    = math.sin(pitchDeg * math.pi / 180), 
         cPit    = math.cos(pitchDeg * math.pi / 180), 
         sx      = scaleX, 
         sy      = scaleY, 
         sz      = scaleZ
     )
     
    // 1. Draw Base Plane (Z=0)
    array<chart.point> plane = array.new<chart.point>()
    plane.push(cam.project(0, 0, 0))
    plane.push(cam.project(priceBins - 1, 0, 0))
    plane.push(cam.project(priceBins - 1, timeSteps - 1, 0))
    plane.push(cam.project(0, timeSteps - 1, 0))
    polyline.new(plane, closed = true, fill_color = neutralPlane, line_color = color.new(color.gray, 60))

    // 2. Precalculate Depth Points (POC & Price Tracking)
    array<chart.point> pocPts = array.new<chart.point>()
    array<chart.point> pricePts = array.new<chart.point>()
    
    int currentBin = 0
    if binSize > 0
        currentBin := math.max(0, math.min(priceBins - 1, int((close - minP) / binSize)))

    float frontZ = terrainMap.get(timeSteps - 1, currentBin)
    bool isNearPeak = showPeakWarning and frontZ >= peakWarnThresh
    color trackerColor = isNearPeak ? warnColor : color.new(color.white, 30)
    color trackerBaseColor = isNearPeak ? warnColor : color.new(color.white, 20)
    color labelColor = isNearPeak ? warnColor : color.white

    for y = 0 to timeSteps - 1
        float maxV = -1.0
        int pocX = 0
        for x = 0 to priceBins - 1
            float v = terrainMap.get(y, x)
            if v > maxV
                maxV := v
                pocX := x
        pocPts.push(cam.project(pocX, y, maxV + 1.0))
        
        if binSize > 0
            pricePts.push(cam.project(currentBin, y, terrainMap.get(y, currentBin) + 0.5))

    // 3. Build Ridge Plot (Back to Front Painter's Algorithm)
    array<chart.point> profileBuf = array.new<chart.point>()
    array<chart.point> lineBuf = array.new<chart.point>()
    
    for y = 0 to timeSteps - 1
        profileBuf.clear()
        lineBuf.clear()
        
        // Build surface curve
        for x = 0 to priceBins - 1
            float z = terrainMap.get(y, x)
            chart.point pt = cam.project(x, y, z)
            profileBuf.push(pt)
            lineBuf.push(pt)
            
        // Close profile polygon to the floor for occlusion
        profileBuf.push(cam.project(priceBins - 1, y, 0))
        profileBuf.push(cam.project(0, y, 0))
        
        color c = f_colorAt(y / math.max(1, timeSteps - 1))
        
        // Draw connecting depth segments BEFORE drawing the mountain slice, 
        // so the mountain naturally occludes lines that go behind it!
        if y > 0
            if showPoc
                line.new(pocPts.get(y - 1), pocPts.get(y), color = pocColor, width = 2)
            if showPriceMarker and binSize > 0
                line.new(pricePts.get(y - 1), pricePts.get(y), color = trackerColor, width = 1, style = line.style_dashed)
        
        // Draw the Mountain Profile Slice
        if showMountainFills
            polyline.new(profileBuf, closed = true, fill_color = mountainBg, line_color = #00000000)
            
        if showRidgeLines
            polyline.new(lineBuf, closed = false, line_color = c, line_width = 2)

    // 4. Draw Front Marker for Current Price
    if showPriceMarker and binSize > 0
        chart.point markerPos = pricePts.get(timeSteps - 1)
        chart.point markerBase = cam.project(currentBin, timeSteps - 1, 0)
        line.new(markerBase, markerPos, color = trackerBaseColor, width = 1, style = line.style_dashed)
        label.new(markerPos.index, markerPos.price, "❖ " + str.tostring(close, format.mintick), color = #00000000, textcolor = labelColor, style = label.style_label_left, size = size.normal)

//---------------------------------------------------------------------------------------------------------------------}