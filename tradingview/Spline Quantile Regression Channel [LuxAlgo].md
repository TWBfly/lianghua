// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo
//@version=6
indicator("Spline Quantile Regression Channel [LuxAlgo]", "LuxAlgo - Spline Quantile Channel", overlay = true, max_polylines_count = 10)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{
int   nInput          = input.int(100, "Lookback Period", minval = 10, group = "Spline Configuration", tooltip = "The number of historical bars used to fit the spline regression.")
int   knotsInput      = input.int(3, "Internal Knots", minval = 1, maxval = 15, group = "Spline Configuration", tooltip = "Number of internal knots. More knots allow the spline to adapt to more complex price structures, while fewer knots yield a smoother curve.")
int   itersInput      = input.int(100, "IRLS Iterations", minval = 1, maxval = 200, group = "Optimization", tooltip = "Iterations for the IRLS solver. Higher values improve quantile accuracy but increase computational load.")
int   extInput        = input.int(20, "Forecast Length", minval = 0, maxval = 100, group = "Optimization", tooltip = "The number of bars to project the spline into the future.")

float upperQInput     = input.float(0.95, "Upper Quantile", minval = 0.01, maxval = 0.99, step = 0.05, group = "Quantile Levels", tooltip = "The specific quantile for the upper band.")
float midQInput       = input.float(0.5, "Median Quantile", minval = 0.01, maxval = 0.99, step = 0.05, group = "Quantile Levels", tooltip = "The specific quantile for the median band.")
float lowerQInput     = input.float(0.05, "Lower Quantile", minval = 0.01, maxval = 0.99, step = 0.05, group = "Quantile Levels", tooltip = "The specific quantile for the lower band.")

color upperColor      = input.color(#f23645, "Upper Color", group = "Visuals", tooltip = "Color of the upper band.")
color midColor        = input.color(#ff9800, "Median Color", group = "Visuals", tooltip = "Color of the median band.")
color lowerColor      = input.color(#089981, "Lower Color", group = "Visuals", tooltip = "Color of the lower band.")
int   widthInput      = input.int(2, "Line Width", minval = 1, group = "Visuals", tooltip = "Width of the channel lines.")

//---------------------------------------------------------------------------------------------------------------------}
// Matrix & Spline Functions
//---------------------------------------------------------------------------------------------------------------------{
// Returns the design matrix X for a cubic spline basis
// Basis: 1, x, x^2, x^3, (x - knot_j)^3+
get_design_matrix(int n, int k_count, int extrapolation = 0) =>
    int total_rows = n + extrapolation
    int cols = 4 + k_count
    matrix<float> X = matrix.new<float>(total_rows, cols)
    
    // Calculate knot positions (equally spaced within [0, 1])
    array<float> knots = array.new<float>(0)
    for i = 1 to k_count
        knots.push(float(i) / (k_count + 1))
        
    for i = 0 to total_rows - 1
        // Scale x so that history is [0, 1] and future is > 1
        float x = float(i) / math.max(1, n - 1)
        X.set(i, 0, 1.0)
        X.set(i, 1, x)
        X.set(i, 2, math.pow(x, 2))
        X.set(i, 3, math.pow(x, 3))
        
        for j = 0 to k_count - 1
            float knot = knots.get(j)
            X.set(i, 4 + j, math.pow(math.max(0, x - knot), 3))
    X

// IRLS loop for Quantile Regression
solve_quantile_regression(matrix<float> X_train, array<float> y, float tau, int iters) =>
    int n = X_train.rows()
    int p = X_train.columns()
    
    // Initial guess: Ridge OLS
    matrix<float> Xt = X_train.transpose()
    matrix<float> XtX = matrix.mult(Xt, X_train)
    for i = 0 to p - 1
        XtX.set(i, i, XtX.get(i, i) + 1e-4)
    
    matrix<float> XtX_inv = XtX.inv()
    array<float> beta = na
    
    if not na(XtX_inv)
        beta := matrix.mult(matrix.mult(XtX_inv, Xt), y)
    else
        beta := array.new<float>(p, 0.0), beta.set(0, y.avg())
        
    // IRLS Iterations
    for iter = 1 to iters
        array<float> y_pred = X_train.mult(beta)
        matrix<float> XtWX = matrix.new<float>(p, p, 0.0)
        array<float> XtWy = array.new<float>(p, 0.0)
        
        for i = 0 to n - 1
            float res = y.get(i) - y_pred.get(i)
            float w = (res > 0 ? tau : (1.0 - tau)) / math.max(math.abs(res), 1e-6)
            
            for j = 0 to p - 1
                float x_ij = X_train.get(i, j)
                float xw = x_ij * w
                XtWy.set(j, XtWy.get(j) + xw * y.get(i))
                for k = 0 to p - 1
                    XtWX.set(j, k, XtWX.get(j, k) + xw * X_train.get(i, k))
        
        for j = 0 to p - 1
            XtWX.set(j, j, XtWX.get(j, j) + 1e-4)
            
        matrix<float> XtWX_inv = XtWX.inv()
        if not na(XtWX_inv)
            beta := XtWX_inv.mult(XtWy)
        else
            break
            
    beta

//---------------------------------------------------------------------------------------------------------------------}
// Drawing Logic
//---------------------------------------------------------------------------------------------------------------------{
var polyline upHist = na, var polyline upExt = na
var polyline midHist = na, var polyline midExt = na
var polyline loHist = na, var polyline loExt = na

render_quantile(matrix<float> X_all, array<float> beta, int n, float mu, float sigma, color c, int width, polyline hist, polyline ext) =>
    array<float> fitted_std = X_all.mult(beta)
    array<chart.point> hist_pts = array.new<chart.point>()
    array<chart.point> ext_pts  = array.new<chart.point>()
    
    for i = 0 to X_all.rows() - 1
        float val = fitted_std.get(i) * sigma + mu
        chart.point pt = chart.point.from_index(bar_index - (n - 1 - i), val)
        if i < n
            hist_pts.push(pt)
        if i >= n - 1 // Include last historical point to bridge the gap
            ext_pts.push(pt)
            
    polyline.delete(hist)
    polyline.delete(ext)
    
    new_hist = polyline.new(hist_pts, line_color = c, line_width = width)
    new_ext  = polyline.new(ext_pts, line_color = c, line_width = width, line_style = line.style_dashed)
    [new_hist, new_ext]

//---------------------------------------------------------------------------------------------------------------------}
// Main Execution
//---------------------------------------------------------------------------------------------------------------------{
if barstate.islast and bar_index >= nInput
    // 1. Data Preparation
    array<float> y_raw = array.new<float>(nInput)
    for i = 0 to nInput - 1
        y_raw.set(nInput - 1 - i, close[i])
    
    float mu_y = y_raw.avg()
    float stdev_y = math.max(y_raw.stdev(), 1e-6)
    array<float> y_std = array.new<float>(nInput)
    for i = 0 to nInput - 1
        y_std.set(i, (y_raw.get(i) - mu_y) / stdev_y)
        
    // 2. Basis Computation
    matrix<float> X_all = get_design_matrix(nInput, knotsInput, extInput)
    matrix<float> X_train = X_all.submatrix(0, nInput, 0, X_all.columns())
    
    // 3. Solve & Render
    array<float> b_up  = solve_quantile_regression(X_train, y_std, upperQInput, itersInput)
    array<float> b_mid = solve_quantile_regression(X_train, y_std, midQInput, itersInput)
    array<float> b_lo  = solve_quantile_regression(X_train, y_std, lowerQInput, itersInput)
    
    // Explicitly update polylines on the last bar
    [h_up, e_up]   = render_quantile(X_all, b_up, nInput, mu_y, stdev_y, upperColor, widthInput, upHist, upExt)
    upHist := h_up, upExt := e_up
    
    [h_mid, e_mid] = render_quantile(X_all, b_mid, nInput, mu_y, stdev_y, midColor, widthInput, midHist, midExt)
    midHist := h_mid, midExt := e_mid
    
    [h_lo, e_lo]   = render_quantile(X_all, b_lo, nInput, mu_y, stdev_y, lowerColor, widthInput, loHist, loExt)
    loHist := h_lo, loExt := e_lo

//---------------------------------------------------------------------------------------------------------------------}
