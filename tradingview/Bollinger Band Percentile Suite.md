// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © QuantiLuxe

//@version=5
indicator("Bollinger Band Percent Suite", "{Ʌ} -‌ 𝐵𝐵𝒫𝒸𝓉 𝒮𝓊𝒾𝓉𝑒", false)

f_kama(src, len, kamaf, kamas) =>
    white = math.abs(src - src[1])
    ama = 0.0
    nsignal = math.abs(src - src[len])
    nnoise = math.sum(white, len)
    nefratio = nnoise != 0 ? nsignal / nnoise : 0
    nsmooth = math.pow(nefratio * (kamaf - kamas) + kamas, 2) 
    ama := nz(ama[1]) + nsmooth * (src - nz(ama[1]))

    ama

f_t3(src, len) =>
    x1 = ta.ema(src, len)
    x2 = ta.ema(x1, len)
    x3 = ta.ema(x2, len)
    x4 = ta.ema(x3, len)
    x5 = ta.ema(x4, len)
    x6 = ta.ema(x5, len)
    b = 0.7
    c1 = - math.pow(b, 3)
    c2 = 3 * math.pow(b, 2) + 3 * math.pow(b, 3)
    c3 = -6 * math.pow(b, 2) - 3 * b - 3 * math.pow(b, 3)
    c4 = 1 + 3 * b + math.pow(b, 3) + 3 * math.pow(b, 2)
    
    c1 * x6 + c2 * x5 + c3 * x4 + c4 * x3

f_ehma(src, length) =>  
    ta.ema(2 * ta.ema(src, length / 2) - ta.ema(src, length), math.round(math.sqrt(length)))

f_thma(src, length) =>  
    ta.wma(ta.wma(src, length / 3) * 3 - ta.wma(src, length / 2) - ta.wma(src, length), length)

f_tema(src, len) =>
    x = ta.ema(src, len)
    y = ta.ema(x, len)
    z = ta.ema(y, len)
    
    3 * x - 3 * y + z

f_dema(src, len) =>
    x = ta.ema(src, len)
    y = ta.ema(x, len)

    2 * x - y

f_ma(src, len, type, kamaf, kamas, offset, sigma) =>
    x = switch type
        "SMA" => ta.sma(src, len)
        "EMA" => ta.ema(src, len)
        "HMA" => ta.hma(src, len)
        "RMA" => ta.rma(src, len)
        "WMA" => ta.wma(src, len)
        "VWMA" => ta.vwma(src, len)
        "ALMA" => ta.alma(src, len, offset, sigma)
        "DEMA" => f_dema(src, len)
        "TEMA" => f_tema(src, len)
        "EHMA" => f_ehma(src, len)
        "THMA" => f_thma(src, len)
        "T3" => f_t3(src, len)
        "KAMA" => f_kama(src, len, kamaf, kamas)
        "LSMA" => ta.linreg(src, len, 0)
    
    x

f_wstdev(src, len) =>
    mean = ta.wma(src, len)
    norm = 0.0
    sum = 0.0
    for i = 0 to len - 1
        weight = len - i
        norm := norm + weight
        sum := sum + math.pow((src[i] - mean), 2) * weight

    math.sqrt(sum / norm)

matype = input.string("EMA", "BaseLine", ["SMA", "EMA", "DEMA", "TEMA", "HMA", "EHMA", "THMA", "RMA", "WMA", "VWMA", "T3", "KAMA", "ALMA", "LSMA"], inline = "2", group = "BBPct")
devtype = input.string("Standard", "Deviation", ["Weighted", "Standard"], inline = "2", group = "BBPct")
src = input(close, "Source", inline = "1", group = "BBPct")
len = input.int(20, "Length", inline = "1", group = "BBPct")
mult = input.float(2.0, "Multi", step = 0.25, group = "BBPct")

hi = input.int(100, "High Threshold", 50, 200, 5, group = "Thresholds")
lo = input.int(0, "Low Threshold", -200, 50, 5, group = "Thresholds")

kamaf = input.float(0.666, "Kaufman Fast", group = "MA Settings")
kamas = input.float(0.0645, "Kaufman Slow", group = "MA Settings")
offset = input.float(0.85, "ALMA Offset", group = "MA Settings")
sigma = input.int(6, "ALMA Sigma", group = "MA Settings")

revshow = input.bool(true, "Display Reversion Bubbles", inline = "0", group = "UI Options")
colbar = input.string("None", "Bar Coloring", ["None", "Trend", "Extremities", "Reversions"], group = "UI Options")

basis = f_ma(src, len, matype, kamaf, kamas, offset, sigma)
dev = mult * (devtype == "Standard" ? ta.stdev(src, len) : f_wstdev(src, len))
upper = basis + dev
lower = basis - dev

bbpct = (src - lower) / (upper - lower) * 100

lh = plot(hi, "Overbought", #bb0010, display = display.pane)
hh = plot(hi + 15, "Overbought", #bb0010, display = display.pane)
hline(50, "Middle Band", #f5f5dc6c, hline.style_solid)
hl = plot(lo, "Oversold", #009bafc0, display = display.pane)
ll = plot(lo - 15, "Oversold", #009bafc0, display = display.pane)
b = plot(bbpct, "𝐵𝐵𝒫𝒸𝓉", chart.fg_color)

fill(lh, hh, color = #bb001031)
fill(ll, hl, color = #009baf23)

fill(hl, b, bbpct[1] < lo and not (bbpct > lo) ? #009baf7e : na)
fill(lh, b, bbpct[1] > hi and not (bbpct < hi) ? #bb0010a2 : na)

ob = ta.crossunder(bbpct, hi)
os = ta.crossover(bbpct, lo)

plotchar(ob ? hi + 25 : na, "OB", '⚬', location.absolute, #bb0010, size = size.tiny)
plotchar(os ? lo - 25 : na, "OS", '⚬', location.absolute, #009baf, size = size.tiny)

color col = switch colbar
    "Trend" => bbpct > 50 ? #009baf : #bb0010
    "Extremities" => bbpct > hi ? #bb0010 : bbpct < lo ? #009baf : #787b86
    "Reversions" => ob ? #bb0010 : os ? #009baf : #787b86
    "None" => na

barcolor(col)
