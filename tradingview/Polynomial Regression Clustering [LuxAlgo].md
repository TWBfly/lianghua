// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Polynomial Regression Clustering [LuxAlgo]", "LuxAlgo - Polynomial Regression Clustering", overlay = true, max_labels_count = 500, max_lines_count = 500, max_polylines_count = 100)

//---------------------------------------------------------------------------------------------------------------------}
// Types
//---------------------------------------------------------------------------------------------------------------------{
type KMeansResult
    float[] centroids
    int[]   assignments

type ClusterPoints
    float[] x
    float[] y

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
// Sizes
TINY               = 'Tiny'
SMALL              = 'Small'
NORMAL             = 'Normal'
LARGE              = 'Large'

// Groups
G_KMEANS           = "K-Means"
G_REG              = "Regression"
G_STYLE            = "Visual Style"

// Tooltips
T_K                = "The number of price levels to identify."
T_LOOKBACK         = "Number of recent bars to include in the clustering calculation."
T_ITER             = "Maximum number of refinement steps for the algorithm."
T_DEGREE           = "Degree of the polynomial fit for each cluster."
T_EXTRAP           = "Extends the regression line from its cluster range to the current bar."
T_FUTURE           = "Number of bars to project the current cluster's fit into the future."

T_SIZE             = "Adjust the size of the cluster dots."

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
kInput             = input.int(4, "Number of Clusters (K)", minval = 2, maxval = 20, group = G_KMEANS, tooltip = T_K)
lookbackInput      = input.int(250, "Lookback Period", minval = 10, group = G_KMEANS, tooltip = T_LOOKBACK)
maxIterationsInput = input.int(50, "Max Iterations", minval = 1, group = G_KMEANS, tooltip = T_ITER)

polyDegreeInput      = input.int(2, "Polynomial Degree", minval = 1, maxval = 5, group = G_REG, tooltip = T_DEGREE)
extendToCurrentInput = input.bool(true, "Extend All Fits to Current Bar", group = G_REG, tooltip = T_EXTRAP)
projectFutureInput   = input.int(0, "Project Current Cluster into Future", minval = 0, group = G_REG, tooltip = T_FUTURE)

showLinesInput       = input.bool(true, "Show Regression Lines", group = G_STYLE)
showDotsInput        = input.bool(true, "Show Cluster Dots", group = G_STYLE)
dotSizeInput         = input.string(SMALL, "Dot Size", options = [TINY, SMALL, NORMAL, LARGE], group = G_STYLE, tooltip = T_SIZE)

// Color Inputs
col1                 = input.color(#f23645, "Cluster 1 Color", inline = "C1", group = G_STYLE)
col2                 = input.color(#00bcd4, "Cluster 2 Color", inline = "C1", group = G_STYLE)
col3                 = input.color(#089981, "Cluster 3 Color", inline = "C2", group = G_STYLE)
col4                 = input.color(#ff9800, "Cluster 4 Color", inline = "C2", group = G_STYLE)
col5                 = input.color(#9c27b0, "Cluster 5 Color", inline = "C3", group = G_STYLE)
col6                 = input.color(#ffeb3b, "Cluster 6 Color", inline = "C3", group = G_STYLE)
col7                 = input.color(#009688, "Cluster 7 Color", inline = "C4", group = G_STYLE)
col8                 = input.color(#880d1e, "Cluster 8 Color", inline = "C4", group = G_STYLE)
col9                 = input.color(#8bc34a, "Cluster 9 Color", inline = "C5", group = G_STYLE)
col10                = input.color(#e91e63, "Cluster 10 Color", inline = "C5", group = G_STYLE)

//---------------------------------------------------------------------------------------------------------------------}
var color[] palette = array.from(col1, col2, col3, col4, col5, col6, col7, col8, col9, col10)

var parsedSize = switch dotSizeInput
    TINY   => size.tiny
    SMALL  => size.small
    NORMAL => size.normal
    LARGE  => size.large
    => size.small

//---------------------------------------------------------------------------------------------------------------------}
// User Defined Functions
//---------------------------------------------------------------------------------------------------------------------{
// K-Means Method
method calculateKMeans(float[] data, int k, int iterations) =>
    int n = data.size()
    float[] centroids = array.new<float>(k)
    int[] assignments = array.new<int>(n, 0)
    
    // 1. Initialize centroids (spread across data range)
    float minVal = data.min()
    float maxVal = data.max()
    float step = (maxVal - minVal) / (k + 1)
    for i = 0 to k - 1
        centroids.set(i, minVal + step * (i + 1))
    
    // 2. Main Iterative Loop
    for iter = 1 to iterations
        bool changed = false
        
        for i = 0 to n - 1
            float val = data.get(i)
            float minDist = 1.0e10
            int bestCluster = 0
            
            for j = 0 to k - 1
                float dist = math.abs(val - centroids.get(j))
                if dist < minDist
                    minDist := dist
                    bestCluster := j
            
            if assignments.get(i) != bestCluster
                assignments.set(i, bestCluster)
                changed := true
        
        float[] newCentroidSums = array.new<float>(k, 0.0)
        int[] counts = array.new<int>(k, 0)
        
        for i = 0 to n - 1
            int cluster = assignments.get(i)
            newCentroidSums.set(cluster, newCentroidSums.get(cluster) + data.get(i))
            counts.set(cluster, counts.get(cluster) + 1)
        
        for j = 0 to k - 1
            if counts.get(j) > 0
                centroids.set(j, newCentroidSums.get(j) / counts.get(j))
        
        if not changed
            break
            
    KMeansResult.new(centroids, assignments)

// Regression Logic
// Solve beta = (X'X)^-1 X'Y
// We normalize X to [0, 1] range to prevent numerical instability with high degrees
getPolyCoefficients(float[] xData, float[] yData, int degree, float xMax) =>
    int n = xData.size()
    if n <= degree
        matrix.new<float>(0, 0)
    else
        matrix<float> X = matrix.new<float>(n, degree + 1)
        matrix<float> Y = matrix.new<float>(n, 1)
        
        for i = 0 to n - 1
            // Normalize x to [0, 1]
            float xNormalized = xData.get(i) / xMax
            matrix.set(Y, i, 0, yData.get(i))
            for j = 0 to degree
                matrix.set(X, i, j, math.pow(xNormalized, j))
        
        matrix<float> XT = matrix.transpose(X)
        matrix<float> XTX = matrix.mult(XT, X)
        matrix<float> XTXInv = matrix.pinv(XTX)
        
        if na(XTXInv)
            matrix.new<float>(0, 0)
        else
            matrix.mult(matrix.mult(XTXInv, XT), Y)


predictPoly(matrix<float> coefficients, float x, float xMax) =>
    float result = 0.0
    int rows = matrix.rows(coefficients)
    if rows > 0
        float xNormalized = x / xMax
        for i = 0 to rows - 1
            result += matrix.get(coefficients, i, 0) * math.pow(xNormalized, i)
    result

//---------------------------------------------------------------------------------------------------------------------}
// Core Calculations
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast
    // 1. Collect price data
    float[] priceData = array.new<float>()
    for i = 0 to lookbackInput - 1
        priceData.push(hl2[i])
    
    KMeansResult results = priceData.calculateKMeans(kInput, maxIterationsInput)
    float[] sortedCentroids = results.centroids.copy()
    sortedCentroids.sort() 
    
    int currentClusterIdx = results.assignments.get(0)

    
    // 3. Visualization cleanup
    var dotLabels = array.new<label>()
    var polylines = array.new<polyline>()
    
    while dotLabels.size() > 0
        label.delete(dotLabels.shift())
    while polylines.size() > 0
        polyline.delete(polylines.shift())

    // 4. Group Data for Regression
    array<ClusterPoints> clusters = array.new<ClusterPoints>(kInput)
    for k = 0 to kInput - 1
        clusters.set(k, ClusterPoints.new(array.new<float>(), array.new<float>()))

    for i = 0 to lookbackInput - 1
        int clusterIdx = results.assignments.get(i)
        float center = results.centroids.get(clusterIdx)
        
        int rank = 0
        for j = 0 to sortedCentroids.size() - 1
            if sortedCentroids.get(j) == center
                rank := j
                break
        
        color clusterColor = palette.get(rank % palette.size())
        float xVal = float(lookbackInput - 1 - i)
        
        clusters.get(clusterIdx).x.push(xVal)
        clusters.get(clusterIdx).y.push(hl2[i])

        // 5. Visuals - Cluster Dots
        if showDotsInput
            dotLabels.push(label.new(
                 x          = bar_index - i, 
                 y          = hl2[i], 
                 text       = "●", 
                 style      = label.style_label_center, 
                 color      = #00000000, 
                 textcolor  = clusterColor, 
                 size       = parsedSize
                 ))

    // 6. Visuals - Polynomial Regression Lines
    if showLinesInput
        for k = 0 to kInput - 1
            float[] xVals = clusters.get(k).x
            float[] yVals = clusters.get(k).y
            
            // We only fit if we have enough points for the degree
            if xVals.size() > polyDegreeInput + 1
                // Use lookbackInput as the normalization factor
                matrix<float> coeffs = getPolyCoefficients(xVals, yVals, polyDegreeInput, float(lookbackInput))
                
                if matrix.rows(coeffs) > 0
                    chart.point[] linePoints = array.new<chart.point>()
                    float minX = xVals.min()
                    float maxX = xVals.max()
                    
                    float center = results.centroids.get(k)
                    int rank = 0
                    for j = 0 to sortedCentroids.size() - 1
                        if sortedCentroids.get(j) == center
                            rank := j
                            break
                    color clusterColor = palette.get(rank % palette.size())

                    // We iterate through the desired range.
                    int startX       = int(math.floor(minX))
                    int fitEndX      = int(math.ceil(maxX))
                    int extrapSolidX = extendToCurrentInput ? lookbackInput - 1 : fitEndX
                    int finalX       = (k == currentClusterIdx) ? math.max(extrapSolidX, lookbackInput - 1 + projectFutureInput) : extrapSolidX

                    // Draw the fitting + extension range (Solid)
                    for xValInt = startX to extrapSolidX
                        float currY = predictPoly(coeffs, float(xValInt), float(lookbackInput))
                        int targetBar = bar_index - (lookbackInput - 1 - xValInt)
                        linePoints.push(chart.point.from_index(targetBar, currY))
                    
                    polylines.push(polyline.new(linePoints, curved = false, line_color = clusterColor, line_width = 1))

                    // Draw the future projection range (Dashed)
                    if finalX > extrapSolidX
                        chart.point[] extrapPoints = array.new<chart.point>()
                        for xValInt = extrapSolidX to finalX
                            float currY = predictPoly(coeffs, float(xValInt), float(lookbackInput))
                            int targetBar = bar_index - (lookbackInput - 1 - xValInt)
                            extrapPoints.push(chart.point.from_index(targetBar, currY))
                        
                        polylines.push(polyline.new(extrapPoints, curved = false, line_color = clusterColor, line_width = 1, line_style = line.style_dashed))

//---------------------------------------------------------------------------------------------------------------------}
