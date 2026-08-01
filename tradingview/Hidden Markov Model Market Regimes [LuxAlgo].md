// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Hidden Markov Model Market Regimes [LuxAlgo]", "LuxAlgo - HMM Regimes", overlay = false, max_bars_back = 1000)

//---------------------------------------------------------------------------------------------------------------------}
// Constants
//---------------------------------------------------------------------------------------------------------------------{
color TREND_COLOR       = #3179f5
color RANGE_COLOR       = #9598a1

DATA                    = #DBDBDB
HEADERS                 = #808080
BACKGROUND              = #161616
BORDERS                 = #2E2E2E

TOP_RIGHT               = 'Top Right'
BOTTOM_RIGHT            = 'Bottom Right'
BOTTOM_LEFT             = 'Bottom Left'

TINY                    = 'Tiny'
SMALL                   = 'Small'
NORMAL                  = 'Normal'
LARGE                   = 'Large'
HUGE                    = 'Huge'

//---------------------------------------------------------------------------------------------------------------------}
// Inputs
//---------------------------------------------------------------------------------------------------------------------{
string HMM_GROUP        = 'HMM Settings'
int lookbackInput       = input.int(50, 'Lookback Period', minval = 10, group = HMM_GROUP, tooltip = 'Lookback for calculating volatility and mean returns.')
float learningRateInput = input.float(0.5, 'Learning Rate', minval = 0.01, maxval = 1.0, step = 0.05, group = HMM_GROUP, tooltip = 'Adjusts how quickly the model adapts to new data.')

string DASHBOARD_GROUP  = 'Dashboard'
bool dashboardInput     = input.bool(true, 'Enable Dashboard', group = DASHBOARD_GROUP)
string dashboardPosInput= input.string(TOP_RIGHT, 'Position', group = DASHBOARD_GROUP, options = [TOP_RIGHT, BOTTOM_RIGHT, BOTTOM_LEFT])
string dashboardSizeInput= input.string(SMALL, 'Size', group = DASHBOARD_GROUP, options = [TINY, SMALL, NORMAL, LARGE, HUGE])

//---------------------------------------------------------------------------------------------------------------------}
// Logic
//---------------------------------------------------------------------------------------------------------------------{
// Observation data: Log Returns and Volatility
float logReturn        = math.log(close / nz(close[1], close))
float meanReturn       = ta.sma(logReturn, lookbackInput)
float volatility       = ta.stdev(logReturn, lookbackInput)

// Normalized Observations for emission likelihood
float normReturn       = (logReturn - meanReturn) / (volatility + 1e-9)
float normVol          = volatility / (ta.sma(volatility, lookbackInput) + 1e-9)

// State Emission Likelihoods (Gaussian Heuristics)
// 1. Ranging State (Local Stationary): Low volatility, returns mean-reverting (normReturn near 0)
float emissionRanging   = math.exp(-math.pow(normVol - 0.7, 2) / 0.5) * math.exp(-math.pow(normReturn, 2) / 0.5)

// 2. Trending State (Local Non-Stationary): Higher volatility, returns directional (abs(normReturn) > 0)
float emissionTrending  = math.exp(-math.pow(normVol - 1.3, 2) / 0.8) * math.exp(-math.pow(math.abs(normReturn) - 1.0, 2) / 1.5)

// Initial Transition Matrix (Persistence-heavy)
var float pTrendTrend = 0.95, var float pTrendRange = 0.05
var float pRangeTrend = 0.05, var float pRangeRange = 0.95

// State Probabilities (Initialization)
var float probTrend = 0.5
var float probRange = 0.5

// Forward Algorithm (Update step)
if not na(normVol)
    // Prediction step (Priors)
    float priorTrend = probTrend * pTrendTrend + probRange * pRangeTrend
    float priorRange = probTrend * pTrendRange + probRange * pRangeRange
    
    // Update step (Likelihood * Prior)
    float unnormTrend = emissionTrending * priorTrend
    float unnormRange = emissionRanging * priorRange
    
    // Normalization to get posterior probabilities
    float sumProbs = unnormTrend + unnormRange
    if sumProbs > 0
        float targetTrend = unnormTrend / sumProbs
        float targetRange = unnormRange / sumProbs
        
        // Apply Learning Rate for smoothing the transition
        probTrend := (1.0 - learningRateInput) * probTrend + learningRateInput * targetTrend
        probRange := (1.0 - learningRateInput) * probRange + learningRateInput * targetRange
        
    // Ensure sum remains 1.0
    float currentSum = probTrend + probRange
    probTrend /= currentSum
    probRange /= currentSum

//---------------------------------------------------------------------------------------------------------------------}
// Plots
//---------------------------------------------------------------------------------------------------------------------{
// Measurements as percentages
float trendPercent = probTrend * 100
float rangePercent = probRange * 100

plotTrend = plot(trendPercent, "Trending Regime %", color = TREND_COLOR, linewidth = 1)
plotRange = plot(rangePercent, "Ranging Regime %",  color = RANGE_COLOR, linewidth = 1)

// Horizontal Reference Lines
hline(50, "Neutral", color = color.new(HEADERS, 50), linestyle = hline.style_dashed)
hline(80, "High Confidence", color = color.new(HEADERS, 80), linestyle = hline.style_dotted)

// Gradient fills for each regime
fill(plotTrend, plot(0, display = display.none), trendPercent, 0, color.new(TREND_COLOR, 50), color.new(TREND_COLOR, 100), "Trend Fill")
fill(plotRange, plot(0, display = display.none), rangePercent, 0, color.new(RANGE_COLOR, 50), color.new(RANGE_COLOR, 100), "Range Fill")

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{
var parsedDashboardPosition = switch dashboardPosInput
    TOP_RIGHT       => position.top_right
    BOTTOM_RIGHT    => position.bottom_right
    BOTTOM_LEFT     => position.bottom_left

var parsedDashboardSize     = switch dashboardSizeInput
    TINY            => size.tiny
    SMALL           => size.small
    NORMAL          => size.normal
    LARGE           => size.large
    HUGE            => size.huge

cell(table t, int col, int row, string txt, color c = #FFFFFF, string align = text.align_right, color bg = na, float h = 0) => 
    t.cell(col, row, txt, text_color = c, text_size = parsedDashboardSize, text_halign = align, bgcolor = bg, height = h)

divider(table t, int row, int lastCol) =>    
    t.merge_cells(0, row, lastCol, row)
    cell(t, 0, row, '━━━━━━━━━━━━━━', align = text.align_center, h = 0.5, c = BORDERS)

if dashboardInput and barstate.islast
    var table t = table.new(parsedDashboardPosition, 2, 7, bgcolor = BACKGROUND, border_width = 0, frame_color = BORDERS, frame_width = 1)
    
    t.merge_cells(0, 0, 1, 0)
    cell(t, 0, 0, 'HMM REGIMES', c = DATA, align = text.align_center)
    
    divider(t, 1, 1)
    
    cell(t, 0, 2, 'Trending', c = HEADERS, align = text.align_left)
    cell(t, 1, 2, str.tostring(trendPercent, "0.0") + "%", c = TREND_COLOR)
    
    cell(t, 0, 3, 'Ranging', c = HEADERS, align = text.align_left)
    cell(t, 1, 3, str.tostring(rangePercent, "0.0") + "%", c = RANGE_COLOR)
    
    divider(t, 4, 1)
    string currentRegime = probTrend > probRange ? "Trending" : "Ranging"
    color regimeColor    = probTrend > probRange ? TREND_COLOR : RANGE_COLOR
    float confidence     = math.max(probTrend, probRange)
        
    cell(t, 0, 5, 'Current State', c = HEADERS, align = text.align_left)
    cell(t, 1, 5, currentRegime, c = regimeColor)
    
    cell(t, 0, 6, 'Confidence', c = HEADERS, align = text.align_left)
    cell(t, 1, 6, str.tostring(confidence * 100, "0.0") + "%", c = DATA)

//---------------------------------------------------------------------------------------------------------------------}
