// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Volume Grid Heatmap [LuxAlgo]", "LuxAlgo - Volume Grid Heatmap", overlay = true, max_boxes_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
const string VIRIDIS = "Viridis"
const string INFERNO = "Inferno"
const string MAGMA   = "Magma"
const string PLASMA  = "Plasma"
const string CIVIDIS = "Cividis"
const string TURBO   = "Turbo"

// Heatmap Palettes
var color[] viridisColors = array.from(#440154, #482878, #3e4989, #31688e, #26828e, #1f9e89, #35b779, #6ece58, #b5de2b, #fde725)
var color[] infernoColors = array.from(#000004, #1b0c41, #4a0c6b, #781c6d, #a52c60, #cf4446, #ed6925, #fb9b06, #f7d13d, #fcffa4)
var color[] magmaColors   = array.from(#000004, #180f3d, #440f76, #721f81, #9e2f7f, #cd4071, #f1605d, #fd9668, #feca8d, #fcfdbf)
var color[] plasmaColors  = array.from(#0d0887, #46039f, #7201a8, #9c179e, #bd3786, #d8576b, #ed7953, #fb9f3a, #fdca26, #f0f921)
var color[] cividisColors = array.from(#00224e, #123570, #3b496c, #575d6d, #707173, #8a8678, #a59c74, #c3b369, #e1cc55, #fee838)
var color[] turboColors   = array.from(#30123b, #4661d6, #37a8fa, #1ae4b6, #71fe5f, #c8ef34, #faba39, #f56918, #ca2a04, #7a0403)

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
int lookbackInput  = input.int(1000, "Lookback Bars", minval = 10, group = "Grid Settings")
int rowsInput      = input.int(50, "Rows (Price)", minval = 1, maxval = 50, group = "Grid Settings")
int colsInput      = input.int(50, "Columns (Time)", minval = 1, maxval = 50, group = "Grid Settings")

string themeInput  = input.string(VIRIDIS, "Heatmap Theme", options = [VIRIDIS, INFERNO, MAGMA, PLASMA, CIVIDIS, TURBO], group = "Visuals")
int transparency   = input.int(50, "Transparency", minval = 0, maxval = 100, group = "Visuals")

//---------------------------------------------------------------------------------------------------------------------}
// Calculations
//---------------------------------------------------------------------------------------------------------------------{
var box[] gridBoxes = array.new_box()

// Pre-calculate boundary values in global scope for consistency
float hi = ta.highest(high, lookbackInput)
float lo = ta.lowest(low, lookbackInput)

// Function to get color from theme based on normalized value (0.0 to 1.0)
getColor(float val, string theme) =>
    color[] palette = switch theme
        VIRIDIS => viridisColors
        INFERNO => infernoColors
        MAGMA   => magmaColors
        PLASMA  => plasmaColors
        CIVIDIS => cividisColors
        TURBO   => turboColors
        => viridisColors
    
    int idx = math.max(0, math.min(9, math.floor(val * 10)))
    palette.get(idx)

if barstate.islast
    float priceRange = hi - lo
    
    if priceRange > 0
        // Initialize Volume Matrix
        array<float> volMatrix = array.new_float(rowsInput * colsInput, 0.0)
        
        float rowHeight = priceRange / rowsInput
        float colWidth  = float(lookbackInput) / colsInput
        
        // Accumulate Volume across history
        for i = 0 to lookbackInput - 1
            float v = nz(volume[i])
            if v == 0
                continue
                
            float bHi = high[i]
            float bLo = low[i]
            
            // Determine Column Index
            int colIdx = math.max(0, math.min(colsInput - 1, math.floor((lookbackInput - 1 - i) / colWidth)))
            
            // Distribute Volume across Rows based on price overlap
            for r = 0 to rowsInput - 1
                float rLo = lo + (r * rowHeight)
                float rHi = rLo + rowHeight
                
                float overlap = math.max(0, math.min(bHi, rHi) - math.max(bLo, rLo))
                if overlap > 0
                    float barRange = bHi - bLo
                    float proportion = barRange == 0 ? 1.0 : overlap / barRange
                    int matrixIdx = r * colsInput + colIdx
                    volMatrix.set(matrixIdx, volMatrix.get(matrixIdx) + (v * proportion))

        // Find Max Volume for Normalization
        float maxVol = volMatrix.max()
        
        // Render Grid
        if gridBoxes.size() > 0
            for b in gridBoxes
                b.delete()
            gridBoxes.clear()
            
        int startBar = bar_index - lookbackInput
        
        for c = 0 to colsInput - 1
            int left  = startBar + math.floor(c * colWidth)
            int right = startBar + math.floor((c + 1) * colWidth)
            
            for r = 0 to rowsInput - 1
                float bottom = lo + (r * rowHeight)
                float top    = bottom + rowHeight
                
                float cellVol = volMatrix.get(r * colsInput + c)
                float normVol = maxVol > 0 ? cellVol / maxVol : 0
                
                if cellVol > 0
                    color cellColor = color.new(getColor(normVol, themeInput), transparency)
                    gridBoxes.push(
                         box.new(left, top, right, bottom, 
                                 bgcolor = cellColor, 
                                 border_color = color.new(chart.fg_color, 90),
                                 border_style = line.style_solid)
                         )

//---------------------------------------------------------------------------------------------------------------------}
