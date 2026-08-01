// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator("AI Channels (Clustering) [LuxAlgo]", "LuxAlgo - AI Channels", overlay = true)
//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
length = input(30, 'Window Size')
K = input.int(5, 'Clusters', minval = 3, maxval = 10)
denoise = input(true, 'Denoise Channels')
asTs = input(false, 'As trailing Stop')

//Optimization
maxIter = input.int(500, 'Maximum Iteration Steps', minval = 0, group = 'Optimization')
maxData = input.int(5000, 'Historical Bars Calculation', minval = 0, group = 'Optimization')

//Style
upperCss = input(#00897B, 'Upper Zone', group = 'Style')
avgCss = input(#ff5d00, 'Average', group = 'Style')
lowerCss = input(#FF5252, 'Lower Zone', group = 'Style')

//-----------------------------------------------------------------------------}
//UDT's
//-----------------------------------------------------------------------------{
type vector
    array<float> out

//-----------------------------------------------------------------------------}
//K-means clustering
//-----------------------------------------------------------------------------{
data = array.new<float>(0)

//Populate data arrays
if last_bar_index - bar_index <= maxData
    for i = 0 to length-1
        data.push(close[i])

//Intitalize centroids using percentiles
centroids = array.new<float>(0)
for i = 1 to K
    per = int(i/(K+1)*100)
    centroids.push(data.percentile_linear_interpolation(per))

//Intialize clusters
var array<vector> clusters = na

if last_bar_index - bar_index <= maxData
    for _ = 0 to maxIter
        clusters := array.new<vector>(0)

        for i = 0 to K-1
            clusters.push(vector.new(array.new<float>(0)))
    
        //Assign value to cluster
        i = 0
        for value in data
            dist = array.new<float>(0)
            for centroid in centroids
                dist.push(math.abs(value - centroid))

            idx = dist.indexof(dist.min())
            
            if idx != -1
                clusters.get(idx).out.push(value)
            
            i += 1

        //Update centroids
        new_centroids = array.new<float>(0)
        for cluster_ in clusters
            new_centroids.push(cluster_.out.avg())

        //Test if centroid changed
        if new_centroids.get(0) == centroids.get(0) and new_centroids.get(1) == centroids.get(1) and new_centroids.get(2) == centroids.get(2)
            break

        centroids := new_centroids

//-----------------------------------------------------------------------------}
//Get channels
//-----------------------------------------------------------------------------{
var float upper = close
var float avg   = close
var float lower = close
var float upper_dev = na
var float lower_dev = na

var float out_upper = na
var float out_avg   = na
var float out_lower = na
var os = 0
 
if not na(clusters)
    //Get centroids 
    upper := nz(centroids.get(K-1), upper)
    avg := nz(centroids.get(int(math.avg(0, K-1))), avg)
    lower := nz(centroids.get(0), lower)
    os := close > upper ? 1 : close < lower ? 0 : os

    upper_dev := clusters.get(K-1).out.stdev()
    lower_dev := clusters.get(0).out.stdev()

if denoise
    out_upper := nz(os ? math.max(upper, out_upper) : math.min(upper, out_upper), upper)
    out_avg := nz(os ? math.max(avg, out_avg) : math.min(avg, out_avg), avg)
    out_lower := nz(os ? math.max(lower, out_lower) : math.min(lower, out_lower), lower)
else
    out_upper := upper
    out_avg := avg
    out_lower := lower

upper_min = out_upper - upper_dev
lower_max = out_lower + lower_dev

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
var bullCss = asTs ? lowerCss : upperCss 
var bearCss = asTs ? upperCss : lowerCss 

plot_upper = plot(asTs ? (os ? na : out_upper) : out_upper, 'Upper', bullCss
  , style = plot.style_linebr)

plot(math.avg(out_upper, out_lower), 'Average', avgCss)

plot_lower = plot(asTs ? (os ? out_lower : na) : out_lower, 'Lower', bearCss
  , style = plot.style_linebr)

//Cluster dispersion areas
plot_upper_min = plot(upper_min, color = na, editable = false)
plot_lower_max = plot(lower_max, color = na, editable = false)

fill(plot_upper, plot_upper_min, out_upper, upper_min, bullCss, color.new(bullCss, 90))
fill(plot_lower_max, plot_lower, lower_max, out_lower, color.new(bearCss, 90), bearCss)

//-----------------------------------------------------------------------------}