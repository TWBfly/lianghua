// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Machine Learning Trendlines Cluster [LuxAlgo]", "LuxAlgo - ML Trendlines Cluster", overlay = true, max_lines_count = 500)
//---------------------------------------------------------------------------------------------------------------------}
//CONSTANTS & STRINGS & INPUTS
//---------------------------------------------------------------------------------------------------------------------{
GREEN                       = #089981
RED                         = #F23645

SOLID                       = 'Solid'
DASHED                      = 'Dashed'
DOTTED                      = 'Dotted'

ABOVE                       = 'Above Threshold'
BELOW                       = 'Below Threshold'

length                      = input(        500,    'Window Size')
K                           = input.int(    4,      'Clusters',                 minval = 3)
maxIter                     = input.int(    1000,   'Maximum Iteration Steps',  group = 'Optimization', minval = 0)
thresholdMultiplierInput    = input.float(  0.25,   'Threshold Multiplier',     group = 'Slope Filter', minval = 0, step = 0.05)
filterSlopesInput           = input.bool(   false,  'Filter Slopes',            group = 'Slope Filter', inline = 'filter')
thresholdSideInput          = input.string( ABOVE,  '',                         group = 'Slope Filter', options = [ABOVE, BELOW], inline = 'filter')
bullCss                     = input(        GREEN,  'Upper Zone',               group = 'Style')
bearCss                     = input(        RED,    'Lower Zone',               group = 'Style')
styleInput                  = input.string( SOLID,  'Lines',                    group = 'Style',        options = [SOLID,DASHED,DOTTED])
sizeInput                   = input.int(    1,      'Size',                     group = 'Style')

//---------------------------------------------------------------------------------------------------------------------}
//DATA STRUCTURES & VARIABLES
//---------------------------------------------------------------------------------------------------------------------{
type vector
    array<float> out

type vectorint
    array<int> out

var lineStyle = switch styleInput
    SOLID   => line.style_solid
    DASHED  => line.style_dashed
    DOTTED  => line.style_dotted

var data_y              = array.new<float>(0)
var data_x              = array.new<int>(0)

var n                   = bar_index
var volatility          = ta.cum(high - low) / (bar_index+1)
var slopeThreshold      = thresholdMultiplierInput * volatility

//---------------------------------------------------------------------------------------------------------------------}
//USER-DEFINED FUNCTIONS
//---------------------------------------------------------------------------------------------------------------------{
gatherData() =>
    data_y.unshift(close)
    data_x.unshift(n)

    if data_y.size() > length
        data_y.pop()
        data_x.pop()

displayTrendlines() =>
    for eachLine in line.all
        eachLine.delete()

    array<vector> clusters_y    = na
    array<vectorint> clusters_x = na
    centroids                   = array.new<float>(0)

    //Intitalize centroids using quartiles
    for i = 1 to K
        per = int(i/(K+1)*100)
        centroids.push(data_y.percentile_linear_interpolation(per))

    //Start Kmeans
    for _ = 0 to maxIter
        clusters_y := array.new<vector>(0)
        clusters_x := array.new<vectorint>(0)

        for i = 1 to K
            clusters_y.push(vector.new(array.new_float()))
            clusters_x.push(vectorint.new(array.new_int()))
        
        //Assign value to cluster
        i = 0
        for value in data_y
            dist = array.new<float>(0)
            for centroid in centroids
                dist.push(math.abs(value - centroid))

            idx = dist.indexof(dist.min())
            clusters_y.get(idx).out.push(value)
            clusters_x.get(idx).out.push(data_x.get(i))
            i += 1

        //Update centroids
        new_centroids = array.new<float>(0)
        for cluster_ in clusters_y
            new_centroids.push(cluster_.out.avg())

        //Test if centroid changed
        if new_centroids.get(0) == centroids.get(0) and new_centroids.get(1) == centroids.get(1) and new_centroids.get(2) == centroids.get(2)
            break

        centroids := new_centroids
    
    //Display lines
    for i = 0 to K-1
        get_y       = clusters_y.get(i).out
        get_x       = clusters_x.get(i).out
        a           = get_y.covariance(get_x) / get_x.variance()
        b           = get_y.avg() - a * get_x.avg()

        css         = color.from_gradient(i, 0, K-1, bearCss, bullCss)

        x1          = get_x.last()
        y1          = a * get_x.last() + b
        x2          = n
        y2          = a * n + b

        rawSlope    = (y2 - y1) / (x2 - x1)    
        ratio       = 180/math.pi
        slope       = ratio * math.atan(rawSlope)        
        
        if not filterSlopesInput or (filterSlopesInput and ((thresholdSideInput == ABOVE and math.abs(slope) < slopeThreshold) or (thresholdSideInput == BELOW and math.abs(slope) > slopeThreshold)))
            line.new(x1, y1, x2, y2, color = css,style = lineStyle,width = sizeInput)                        

//---------------------------------------------------------------------------------------------------------------------}
//MUTABLE VARIABLES & EXECUTION
//---------------------------------------------------------------------------------------------------------------------{
n               := bar_index
volatility      := ta.cum(high - low) / (bar_index+1)
slopeThreshold  := thresholdMultiplierInput * volatility

gatherData()

if barstate.islast
    displayTrendlines()

//---------------------------------------------------------------------------------------------------------------------}