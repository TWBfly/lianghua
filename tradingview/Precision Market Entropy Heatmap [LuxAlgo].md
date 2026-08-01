// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Precision Market Entropy Heatmap [LuxAlgo]", "LuxAlgo - Precision Market Entropy Heatmap", overlay = true, max_boxes_count = 500, max_lines_count = 500, max_polylines_count = 100)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
int MAX_BOXES      = 500

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string GRP_CORE    = 'Heatmap Settings'
string anchorInput = input.timeframe("D", "Anchor Interval", group = GRP_CORE, tooltip = "Each block represents the profile of one anchor period (e.g., Daily).")
string precInput   = input.timeframe("1", "Intrabar Precision", group = GRP_CORE, tooltip = "Lower timeframe used to calculate the heatmap. Lower values (e.g., '1') provide much higher precision but require more data.")
int rowsInput      = input.int(50, "Number of Rows", minval = 10, maxval = 100, group = GRP_CORE, tooltip = "Price resolution of the heatmap.")

string GRP_STYLE   = 'Style Settings'
color lowColInput  = input.color(color.new(#000033, 0), "Heatmap Intensity", group = GRP_STYLE, inline = 'intensity')
color midColInput  = input.color(color.new(#00ff88, 0), "", group = GRP_STYLE, inline = 'intensity')
color highColInput = input.color(color.new(#ffff00, 0), "", group = GRP_STYLE, inline = 'intensity')
int transInput     = input.int(70, "Heatmap Transparency", minval = 0, maxval = 100, group = GRP_STYLE)

color bullPocInput = input.color(#089981, "POC Extension (Bull/Bear)", group = GRP_STYLE, inline = 'extCol')
color bearPocInput = input.color(#f23645, "", group = GRP_STYLE, inline = 'extCol')

bool showDevInput  = input.bool(true, "Show Developing POC", group = GRP_STYLE, inline = 'devPoc')
color devPocColInput = input.color(#ffffff, "", group = GRP_STYLE, inline = 'devPoc')
bool devPocAutoInput = input.bool(true, "Auto", group = GRP_STYLE, inline = 'devPoc', tooltip = "When enabled, the developing POC uses the theme's foreground color.")

string GRP_DISP    = "Display Settings"
int sessionsInput  = input.int(10, "Max Sessions to Show", minval = 1, maxval = 50, group = GRP_DISP)
bool extendInput   = input.bool(true, "Extend POCs to Current Bar", group = GRP_DISP)
//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type BarData
    float h
    float l
    float v

type ProfileRow
    float volume   = 0.0
    float priceMin = 0.0
    float priceMax = 0.0
    box   boxId    = na

type ProfileBlock
    int   startBar
    line  pocLine  = na
    polyline devPoc = na
    array<chart.point> points
    array<ProfileRow> rows
//---------------------------------------------------------------------------------------------------------------------}
// Variables
//---------------------------------------------------------------------------------------------------------------------{
var array<ProfileBlock> blocks = array.new<ProfileBlock>()
var ProfileBlock activeBlock   = na
var int lastStart              = bar_index
var sessionLtfData             = array.new<BarData>()

// Colors
color lowColor  = color.new(lowColInput, transInput)
color midColor  = color.new(midColInput, transInput)
color highColor = color.new(highColInput, transInput)
color devPocCol = devPocAutoInput ? chart.fg_color : devPocColInput

// Intrabar Data
[ltfH, ltfL, ltfV] = request.security_lower_tf(syminfo.tickerid, precInput, [high, low, volume])
//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
bool isNewSession = ta.change(time(anchorInput)) != 0

// On New Session: Handle transition
if isNewSession or barstate.isfirst
    if not na(activeBlock)
        blocks.push(activeBlock)
        
        while blocks.size() > sessionsInput or blocks.size() * rowsInput > MAX_BOXES
            ProfileBlock old = blocks.shift()
            if not na(old)
                if not na(old.devPoc)
                    old.devPoc.delete()
                if not na(old.pocLine)
                    old.pocLine.delete()
                if not na(old.rows)
                    for row in old.rows
                        row.boxId.delete()
    
    lastStart := bar_index
    sessionLtfData.clear()
    
    activeBlock := ProfileBlock.new(
         startBar = bar_index, 
         pocLine  = line.new(na, na, na, na, style = line.style_dashed),
         devPoc   = na,
         points   = array.new<chart.point>(0),
         rows     = array.new<ProfileRow>(0)
         )
    
    for i = 0 to rowsInput - 1
        activeBlock.rows.push(ProfileRow.new(0.0, 0.0, 0.0, na))

// Accumulate intrabar data
if not na(ltfH) and ltfH.size() > 0
    for i = 0 to ltfH.size() - 1
        sessionLtfData.push(BarData.new(ltfH.get(i), ltfL.get(i), ltfV.get(i)))

// Active Session Updates
if not na(activeBlock) and activeBlock.rows.size() > 0 and sessionLtfData.size() > 0
    float sHigh = na
    float sLow  = na
    for i = 0 to sessionLtfData.size() - 1
        BarData d = sessionLtfData.get(i)
        if not na(d.h) and not na(d.l)
            sHigh := na(sHigh) ? d.h : math.max(sHigh, d.h)
            sLow  := na(sLow) ? d.l : math.min(sLow, d.l)
    
    if not na(sHigh) and not na(sLow) and sHigh > sLow
        float rowSize = (sHigh - sLow) / rowsInput
        
        array<float> rowVolumes = array.new_float(rowsInput, 0.0)
        float maxVol = 0.0
        int peakIdx  = 0
        
        for i = 0 to sessionLtfData.size() - 1
            BarData d = sessionLtfData.get(i)
            if na(d.h) or na(d.l) or na(d.v)
                continue
            int idxH = int(math.min(rowsInput - 1, math.max(0, math.floor((d.h - sLow) / rowSize))))
            int idxL = int(math.min(rowsInput - 1, math.max(0, math.floor((d.l - sLow) / rowSize))))
            int span = idxH - idxL + 1
            for j = idxL to idxH
                float vol = rowVolumes.get(j) + (d.v / span)
                rowVolumes.set(j, vol)
                if vol > maxVol
                    maxVol := vol
                    peakIdx := j
        
        float pocPrice = (sLow + peakIdx * rowSize) + (rowSize / 2)

        // Developing POC
        activeBlock.points.push(chart.point.from_index(bar_index, pocPrice))
        if not na(activeBlock.devPoc)
            activeBlock.devPoc.delete()
        if showDevInput
            activeBlock.devPoc := polyline.new(activeBlock.points, curved = false, line_color = devPocCol, line_width = 2)
        
        // Active POC Line
        activeBlock.pocLine.set_xy1(lastStart, pocPrice)
        activeBlock.pocLine.set_xy2(bar_index, pocPrice)
        activeBlock.pocLine.set_color(pocPrice < close ? bullPocInput : bearPocInput)

        // Boxes
        for i = 0 to rowsInput - 1
            ProfileRow row = activeBlock.rows.get(i)
            row.volume := rowVolumes.get(i)
            row.priceMin := sLow + i * rowSize
            row.priceMax := row.priceMin + rowSize
            float intensity = maxVol > 0 ? row.volume / maxVol : 0
            
            color rowCol = intensity > 0.5 
                 ? color.from_gradient(intensity, 0.5, 1.0, midColor, highColor)
                 : color.from_gradient(intensity, 0.0, 0.5, lowColor, midColor)
            
            if na(row.boxId)
                row.boxId := box.new(lastStart, row.priceMax, bar_index, row.priceMin, border_color = color.new(rowCol, 90), bgcolor = rowCol)
            else
                row.boxId.set_lefttop(lastStart, row.priceMax)
                row.boxId.set_rightbottom(bar_index, row.priceMin)
                row.boxId.set_bgcolor(rowCol)
                row.boxId.set_border_color(color.new(rowCol, 90))

// Historical Updates
if blocks.size() > 0
    for i = 0 to blocks.size() - 1
        ProfileBlock b = blocks.get(i)
        if not na(b.pocLine)
            float pPrice = b.pocLine.get_y1()
            b.pocLine.set_color(pPrice < close ? bullPocInput : bearPocInput)
            if extendInput
                b.pocLine.set_x2(bar_index)
            else
                int endBar = (i < blocks.size() - 1) ? blocks.get(i+1).startBar : bar_index
                b.pocLine.set_x2(endBar)

//---------------------------------------------------------------------------------------------------------------------}
