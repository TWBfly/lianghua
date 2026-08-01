// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Gaussian Volume Profile [LuxAlgo]", "LuxAlgo - Gaussian VP", overlay = true, max_lines_count = 500)

//---------------------------------------------------------------------------------------------------------------------}
// Constants & Inputs
//---------------------------------------------------------------------------------------------------------------------{
// --- Tooltips ---
string TT_LOOKBACK   = "The number of historical bars used to calculate the volume profile distribution."
string TT_BINS       = "Determines the vertical resolution of the profile. More bins provide more detail but require more computation."
string TT_PEAKS      = "The maximum number of Gaussian components to fit. Useful for identifying multiple volume clusters."
string TT_ITER       = "Controls how many times the optimizer refines the fit. Increase if the fit doesn't look smooth."
string TT_LAMBDA     = "Initial damping for the Levenberg-Marquardt algorithm. Affects the early steps of the optimization process."
string TT_RESOLUTION = "The maximum horizontal length of the projected histogram and fit, measured in bar widths."
string TT_WINDOW     = "Toggles the visual background box covering the historical lookback area."
string TT_DETECT     = "Detects local maxima (nodes) in the final fit and draws horizontal dashed levels at those price points."
string TT_AUTO       = "When enabled, the fit color automatically adapts to your chart's foreground color (e.g., White on Dark theme)."

// --- Profile Settings ---
int windowSizeInput  = input.int(100, "Lookback Window", minval = 20, group = "Profile Settings", tooltip = TT_LOOKBACK)
int numBinsInput     = input.int(50, "Number of Bins", minval = 10, maxval = 100, group = "Profile Settings", tooltip = TT_BINS)

// --- Gaussian Settings ---
int numPeaksInput    = input.int(5, "Max Potential Peaks", minval = 1, maxval = 20, group = "Gaussian Settings", tooltip = TT_PEAKS)
int maxIterInput     = input.int(30, "Max Iterations", minval = 5, maxval = 200, group = "Gaussian Settings", tooltip = TT_ITER)
float lambdaInit     = input.float(0.01, "Initial Lambda", minval = 0.00001, group = "Gaussian Settings", tooltip = TT_LAMBDA)

// --- Visuals ---
int histWidthInput   = input.int(100, "Histogram Resolution", minval = 5, group = "Visuals", tooltip = TT_RESOLUTION)
bool showWindow      = input.bool(true, "Highlight Window Range", group = "Visuals", tooltip = TT_WINDOW, inline = "Window")
color windowColor    = input.color(color.new(#808080, 95), "", group = "Visuals", tooltip = "Background color for the historical lookback area.", inline = "Window")
bool showPeakLines   = input.bool(true, "Highlight Detected Peaks", group = "Visuals", tooltip = TT_DETECT)
color userFitColor   = input.color(color.new(#ff5d00, 0), "Fit Color", group = "Visuals", inline = "Color", tooltip = "Static color for the fit density.")
bool autoFitColor    = input.bool(true, "Auto", group = "Visuals", inline = "Color", tooltip = TT_AUTO)

color FIT_COLOR      = autoFitColor ? chart.fg_color : userFitColor

// Palette for individual Gaussian components
color COMP_1 = #2196F3
color COMP_2 = #4CAF50
color COMP_3 = #FFEB3B
color COMP_4 = #E91E63
color COMP_5 = #9C27B0

//---------------------------------------------------------------------------------------------------------------------}
// Functions
//---------------------------------------------------------------------------------------------------------------------{
// @function Calculates a single Gaussian component at price x
calcComponent(float x, array<float> p, int k) =>
    float a     = p.get(k * 3 + 0)
    float mu    = p.get(k * 3 + 1)
    float sigma = p.get(k * 3 + 2)
    float exponent = -math.pow(x - mu, 2) / (2 * math.pow(math.max(1e-9, sigma), 2))
    a * math.exp(math.max(-100, exponent))

// @function Calculates the sum of Gaussians at price x
calcSum(float x, array<float> p, int K) =>
    float sum = 0.0
    for k = 0 to K - 1
        sum += calcComponent(x, p, k)
    sum

//---------------------------------------------------------------------------------------------------------------------}
// Main Logic
//---------------------------------------------------------------------------------------------------------------------{
var polyline sumLine     = na
var polylinesArray       = array.new<polyline>()
var histogramArray       = array.new<line>()
var peakLinesArray       = array.new<line>()
var peakLabelsArray      = array.new<label>()
var box windowBox        = na

// Historical Price Range
float maxPriceWindow = ta.highest(high, windowSizeInput)
float minPriceWindow = ta.lowest(low, windowSizeInput)

if barstate.islast
    int N = windowSizeInput
    int B = numBinsInput
    int K = numPeaksInput
    
    // 1. Compute Volume Profile
    float binSize  = (maxPriceWindow - minPriceWindow) / B
    array<float> binVolumes = array.new<float>(B, 0.0)
    array<float> binCenters = array.new<float>(B, 0.0)
    
    for i = 0 to B - 1
        binCenters.set(i, minPriceWindow + (i + 0.5) * binSize)
        
    for i = 0 to N - 1
        float p_high = high[i]
        float p_low  = low[i]
        float vol    = nz(volume[i])
        for j = 0 to B - 1
            float bc = binCenters.get(j)
            if bc >= p_low and bc <= p_high
                binVolumes.set(j, binVolumes.get(j) + (vol / math.max(1, math.ceil((p_high - p_low) / binSize))))

    float maxBinVol = binVolumes.max()

    // 2. Initial Guesses for LM
    array<float> p = array.new<float>(K * 3)
    float segSize = float(B) / K
    for k = 0 to K - 1
        int startIdx = int(k * segSize)
        int endIdx   = int(math.min(B - 1, (k + 1) * segSize - 1))
        float maxY = 0.0
        int maxX   = startIdx
        for i = startIdx to endIdx
            float val = binVolumes.get(i)
            if val > maxY
                maxY := val
                maxX := i
        p.set(k * 3 + 0, math.max(1.0, maxY))
        p.set(k * 3 + 1, binCenters.get(maxX))
        p.set(k * 3 + 2, (maxPriceWindow - minPriceWindow) / (K * 2.0))
    
    float lambda = lambdaInit
    
    // 3. LM Fitting Loop
    for iter = 1 to maxIterInput
        matrix<float> J = matrix.new<float>(B, K * 3)
        array<float> r  = array.new<float>(B)
        float currentError = 0.0
        for i = 0 to B - 1
            float x = binCenters.get(i)
            float y = binVolumes.get(i)
            float f = calcSum(x, p, K)
            float resVal = y - f
            r.set(i, resVal)
            currentError += math.pow(resVal, 2)
            for k = 0 to K - 1
                float ak     = p.get(k * 3 + 0)
                float muk    = p.get(k * 3 + 1)
                float sigmak = math.max(1e-9, p.get(k * 3 + 2))
                float fk     = calcComponent(x, p, k)
                J.set(i, k * 3 + 0, fk / math.max(1e-6, ak))
                J.set(i, k * 3 + 1, fk * (x - muk) / math.pow(sigmak, 2))
                J.set(i, k * 3 + 2, fk * math.pow(x - muk, 2) / math.pow(sigmak, 3))
            
        matrix<float> JT = J.transpose()
        matrix<float> H  = JT.mult(J)
        array<float> g   = JT.mult(r)
        for i = 0 to (K * 3) - 1
            H.set(i, i, H.get(i, i) * (1.0 + lambda))
        array<float> deltaP = H.pinv().mult(g)
        
        if not na(deltaP)
            array<float> pTrial = p.copy()
            for j = 0 to (K * 3) - 1
                pTrial.set(j, pTrial.get(j) + deltaP.get(j))
                if j % 3 == 0 or j % 3 == 2
                    pTrial.set(j, math.max(1e-6, pTrial.get(j)))
            
            float trialError = 0.0
            for i = 0 to B - 1
                trialError += math.pow(binVolumes.get(i) - calcSum(binCenters.get(i), pTrial, K), 2)
            if trialError < currentError
                p := pTrial
                lambda /= 10.0
                if (currentError - trialError) / currentError < 1e-5
                    break
            else
                lambda *= 10.0

    // 4. Visualization Cleanup
    if not na(sumLine)
        sumLine.delete()
    if not na(windowBox)
        windowBox.delete()
    for item in polylinesArray
        item.delete()
    for item in histogramArray
        item.delete()
    for item in peakLinesArray
        item.delete()
    for item in peakLabelsArray
        item.delete()
        
    polylinesArray.clear()
    histogramArray.clear()
    peakLinesArray.clear()
    peakLabelsArray.clear()

    // 4a. Window Highlight
    if showWindow
        windowBox := box.new(bar_index - windowSizeInput + 1, maxPriceWindow, bar_index, minPriceWindow, bgcolor = windowColor, border_color = na)

    // 4b. Draw Lateral Histogram
    for i = 0 to B - 1
        float vol = binVolumes.get(i)
        float price = binCenters.get(i)
        int x_end = bar_index + 1 + int((vol / maxBinVol) * histWidthInput)
        histogramArray.push(line.new(bar_index + 1, price, x_end, price, color = color.new(FIT_COLOR, 85), width = 2))

    // 4c. Compute Discrete Fit and Detect Peaks via Derivative Sign Change
    array<float> fitValues = array.new<float>(B)
    for i = 0 to B - 1
        fitValues.set(i, calcSum(binCenters.get(i), p, K))
        
    for i = 1 to B - 2
        // Check for local maximum (Peak)
        if fitValues.get(i) > fitValues.get(i - 1) and fitValues.get(i) > fitValues.get(i + 1)
            float peakPrice = binCenters.get(i)
            float peakSum   = fitValues.get(i)
            
            // Associate with dominant individual component
            int dominantK = 0
            float maxCompVal = -1.0
            for k = 0 to K - 1
                float compVal = calcComponent(peakPrice, p, k)
                if compVal > maxCompVal
                    maxCompVal := compVal
                    dominantK := k
            
            color peakColor = switch dominantK % 5
                0 => COMP_1
                1 => COMP_2
                2 => COMP_3
                3 => COMP_4
                => COMP_5
                
            int x_apex = bar_index + 1 + int((peakSum / maxBinVol) * histWidthInput)
            
            if showPeakLines
                peakLinesArray.push(line.new(bar_index - windowSizeInput + 1, peakPrice, x_apex, peakPrice, color = color.new(peakColor, 50), style = line.style_dashed))
                peakLabelsArray.push(label.new(x_apex, peakPrice, str.tostring(math.round_to_mintick(peakPrice)), color = #00000000, textcolor = peakColor, style = label.style_label_left, size = size.small))

    // 4d. Draw Gaussian Components
    for k = 0 to K - 1
        color compColor = switch k % 5
            0 => COMP_1
            1 => COMP_2
            2 => COMP_3
            3 => COMP_4
            => COMP_5
        array<chart.point> compPoints = array.new<chart.point>()
        for i = 0 to B - 1
            float price = binCenters.get(i)
            float compVol = calcComponent(price, p, k)
            int x_coord = bar_index + 1 + int((compVol / maxBinVol) * histWidthInput)
            compPoints.push(chart.point.from_index(x_coord, price))
        polylinesArray.push(polyline.new(compPoints, curved = false, line_color = color.new(compColor, 40), line_width = 1, line_style = line.style_dotted))

    // 4e. Draw Final Gaussian Sum
    array<chart.point> sumPoints = array.new<chart.point>()
    for i = 0 to B - 1
        float price = binCenters.get(i)
        float sumVol = fitValues.get(i)
        int x_coord = bar_index + 1 + int((sumVol / maxBinVol) * histWidthInput)
        sumPoints.push(chart.point.from_index(x_coord, price))
    sumLine := polyline.new(sumPoints, curved = false, line_color = FIT_COLOR, line_width = 3)

//---------------------------------------------------------------------------------------------------------------------}
