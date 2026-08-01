// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("3D Opportunity Cone [LuxAlgo]", "LuxAlgo - 3D Opportunity Cone", overlay = true, max_lines_count = 500, max_labels_count = 500, scale = scale.none)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Inputs
//---------------------------------------------------------------------------------------------------------------------{
color BUY_COLOR  = #089981
color RISK_COLOR = #f23645
color GRID_COLOR = color.new(chart.fg_color, 75)

string G1 = "Cone Settings"
int   lookbackInput   = input.int(20, "Evaluation Lookback", minval = 5, group = G1)
float coneSizeInput   = input.float(5.0, "Cone Scale", minval = 0.1, step = 0.1, group = G1)
int   xOffsetInput    = input.int(35, "X Offset (Bars)", group = G1)
float tiltInput       = input.float(0.4, "3D Tilt", minval = 0.1, maxval = 1.0, group = G1)

string G2 = "Trail & Colors"
color pointColorInput = input.color(color.yellow, "Highlight Color", group = G2)
color fillConeInput   = input.color(#ffffff12, "Cone Fill Color", group = G2) // #ffffff12 is roughly color.new(white, 93)
int   trailLengthInput = input.int(100, "Trail Length", minval = 1, maxval = 100, group = G2)

float PI = math.pi

//---------------------------------------------------------------------------------------------------------------------}
// Functions & Methods
//---------------------------------------------------------------------------------------------------------------------{

// @function Projects 3D coordinates to 2D chart space
project(float x, float y, float z, float centerX, float centerY, float scale, float tilt) =>
    float p_x = centerX + x * scale
    float p_y = centerY + (y + z * tilt) * (scale * (syminfo.mintick * 6000))
    [p_x, p_y]

// @function Normalizes a series over a lookback period
normalize(float val, int len) =>
    float min = ta.lowest(val, len)
    float max = ta.highest(val, len)
    (val - min) / math.max(max - min, syminfo.mintick)

//---------------------------------------------------------------------------------------------------------------------}
// Drawing Management
//---------------------------------------------------------------------------------------------------------------------{
var array<line>     linesArray     = array.new<line>()
var array<label>    labelsArray    = array.new<label>()
var array<polyline> polylinesArray = array.new<polyline>()

cleanDrawings() =>
    if linesArray.size() > 0
        for i = 0 to linesArray.size() - 1
            linesArray.get(i).delete()
        linesArray.clear()
    if labelsArray.size() > 0
        for i = 0 to labelsArray.size() - 1
            labelsArray.get(i).delete()
        labelsArray.clear()
    if polylinesArray.size() > 0
        for i = 0 to polylinesArray.size() - 1
            polylinesArray.get(i).delete()
        polylinesArray.clear()

//---------------------------------------------------------------------------------------------------------------------}
// Market Logic
//---------------------------------------------------------------------------------------------------------------------{

// 1. Value Factor (Height)
float valueFactor = 1.0 - (ta.stoch(close, high, low, lookbackInput) / 100)

// 2. Risk Factor (Radius)
float atr      = ta.atr(lookbackInput)
float riskNorm = normalize(atr, lookbackInput * 5)

// 3. Conviction Factor (Angle)
float volm     = volume
float volmNorm = normalize(volm, lookbackInput * 5)
float angle    = volmNorm * 2 * PI

// Anchor for the visualization
float anchorY  = ta.sma(close, lookbackInput)

//---------------------------------------------------------------------------------------------------------------------}
// Visualization Logic
//---------------------------------------------------------------------------------------------------------------------{

if barstate.islast
    cleanDrawings()
    
    float anchorX = bar_index + xOffsetInput
    float scale   = coneSizeInput * 15
    
    // --- Draw Opportunity Cone ---
    int ringCount = 5
    for i = 0 to ringCount
        float h = i / ringCount
        float r = 1.0 - h
        array<chart.point> ringPoints = array.new<chart.point>()
        for j = 0 to 16
            float theta = (j / 16) * 2 * PI
            [p_x, p_y] = project(r * math.cos(theta), h * 2.5, r * math.sin(theta), anchorX, anchorY, scale, tiltInput)
            array.push(ringPoints, chart.point.from_index(math.round(p_x), p_y))
        
        polylinesArray.push(polyline.new(ringPoints, closed = true, line_color = i == ringCount ? BUY_COLOR : GRID_COLOR, line_width = i == ringCount ? 2 : 1, fill_color = fillConeInput))

    // Vertical Ribs
    for i = 0 to 7
        float theta = (i / 8) * 2 * PI
        [base_x, base_y] = project(math.cos(theta), 0, math.sin(theta), anchorX, anchorY, scale, tiltInput)
        [apex_x, apex_y] = project(0, 2.5, 0, anchorX, anchorY, scale, tiltInput)
        linesArray.push(line.new(math.round(base_x), base_y, math.round(apex_x), apex_y, color = GRID_COLOR, style = line.style_dotted))

    // --- Draw Trail (Historical Opportunity) ---
    for i = trailLengthInput - 1 to 0
        float hValue = valueFactor[i]
        float hRisk  = riskNorm[i]
        float hAngle = angle[i]
        
        float ptY = hValue * 2.5
        float ptR = hRisk * (1.0 - hValue)
        float ptX = ptR * math.cos(hAngle)
        float ptZ = ptR * math.sin(hAngle)
        
        [dot_x, dot_y] = project(ptX, ptY, ptZ, anchorX, anchorY, scale, tiltInput)
        
        color basePointColor = color.from_gradient(hValue, 0, 1, RISK_COLOR, BUY_COLOR)
        int alpha = math.round((i / trailLengthInput) * 100)
        color hColor = color.new(basePointColor, alpha)
        
        labelsArray.push(label.new(math.round(dot_x), dot_y, "●", color = #00000000, textcolor = hColor, style = label.style_label_center, size = i == 0 ? size.normal : size.tiny))
        
        if i == 0
            // Highlight current bar
            labelsArray.push(label.new(math.round(dot_x), dot_y, "●", color = #00000000, textcolor = color.new(pointColorInput, 30), style = label.style_label_center, size = size.normal))
            
            [sh_x, sh_y] = project(ptX, 0, ptZ, anchorX, anchorY, scale, tiltInput)
            linesArray.push(line.new(math.round(dot_x), dot_y, math.round(sh_x), sh_y, color = color.new(pointColorInput, 60), style = line.style_dashed))
            
            [ax_x, ax_y] = project(0, ptY, 0, anchorX, anchorY, scale, tiltInput)
            linesArray.push(line.new(math.round(dot_x), dot_y, math.round(ax_x), ax_y, color = color.new(pointColorInput, 80)))

    // --- Annotations ---
    [lab_apex_x, lab_apex_y] = project(0, 2.7, 0, anchorX, anchorY, scale, tiltInput)
    labelsArray.push(label.new(math.round(lab_apex_x), lab_apex_y, "BUY ZONE\n(Oversold + Low Risk)", textcolor = BUY_COLOR, style = label.style_none, size = size.small))

    [lab_base_x, lab_base_y] = project(1.2, 0, 0, anchorX, anchorY, scale, tiltInput)
    labelsArray.push(label.new(math.round(lab_base_x), lab_base_y, "RISK ZONE\n(Overbought/Volatility)", textcolor = RISK_COLOR, style = label.style_label_left, color = #00000000, size = size.small))

//---------------------------------------------------------------------------------------------------------------------}
