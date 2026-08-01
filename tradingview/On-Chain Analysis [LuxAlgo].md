// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5

indicator('On-Chain Analysis [LuxAlgo]', 'LuxAlgo - On-Chain Analysis', format = format.volume)

//---------------------------------------------------------------------------------------------------------------------}
// Settings
//---------------------------------------------------------------------------------------------------------------------{

display = display.all - display.status_line

wGR = 'On-Chain Analysis'

opt1 = "Wallet Profitability"
opt2 = "Exchange Flow (USD)"
opt8 = "Miner Flow (USD)"
opt3 = "On-Chain Volume (USD)"
opt4 = "Market Capitalization"
opt12 = "Market Dominance"
opt5 = "Active Addresses"
opt6 = "Total Value Locked"
opt13 = 'Market Value to Realized Value'
opt11 = "Social Sentiment"
opt9 = "Holder Balance (Behavior)"
opt10 = "Holder Balance (Type)"

papDisplay = input.string(opt1, 'On-Chain Data', options = [opt1, opt2, opt8, opt3, opt4, opt12, opt5, opt6, opt13, opt11, opt9, opt10, "None"], group = wGR, display = display)

papSmooth = input.int(7, 'Smoothing', minval = 1, maxval = 50, inline = 'PAP', group = wGR, display = display)
papColor = input.color(color.new(#3179F5, 50), '', inline = 'PAP', group = wGR)
lapColor = input.color(color.new(#FF5D00, 50), '', inline = 'PAP', group = wGR)
bapColor = input.color(color.new(color.gray, 50), '', inline = 'PAP', group = wGR)

papMAT = input.string("None", 'Signal Line', options = ["SMA", "EMA", "RMA", "None"], inline = 'PAP1', group = wGR, display = display)
papMAL = input.int(13, '', minval = 1, maxval = 50, inline = 'PAP1', group = wGR, display = display)

statGR = 'On-Chain Dashboard'
statTip = 'The table tooltips include the definition and importance of each metric.'
block = input.bool(true, 'On-Chain Stats', group = statGR, tooltip = statTip)
perfText = input.string('Small', 'Dashboard Size', options=['Tiny', 'Small', 'Normal'], group = statGR, display = display)
perfPos = input.string('Bottom Right', 'Dashboard Position', options = ['Top Right', 'Bottom Right', 'Bottom Left'], group = statGR, display = display)
tlColor = input.color(#ffffff, 'Title', inline = 'PAP', group = statGR)
naColor = input.color(#3179f5, '', inline = 'PAP', group = statGR)
txColor = input.color(#b2b5be, 'Text', inline = 'PAP', group = statGR)
upColor = input.color(#26a69a, '', inline = 'PAP', group = statGR)
dnColor = input.color(#ef5350, '', inline = 'PAP', group = statGR)

//---------------------------------------------------------------------------------------------------------------------}
// Functions/Methods
//---------------------------------------------------------------------------------------------------------------------{

smooth(_source, _length, _type) => 
    switch _type
        "SMA"  => ta.sma (_source, _length)
        "EMA"  => ta.ema (_source, _length)
        "RMA"  => ta.rma (_source, _length)

interpolate(value, rangeHigh) =>
    value * rangeHigh / 100

//---------------------------------------------------------------------------------------------------------------------}
// On-Chain Data Collection
//---------------------------------------------------------------------------------------------------------------------{

apSyminfo = syminfo.basecurrency != '' ? syminfo.basecurrency : str.replace(syminfo.ticker, str.match(syminfo.ticker, syminfo.currency),  "", 0)

profiting = request.security(apSyminfo + '_INOUTMONEYINPERCENTAGE', 'D', close, ignore_invalid_symbol = true)
losing = request.security(apSyminfo + '_INOUTMONEYOUTPERCENTAGE', 'D', close, ignore_invalid_symbol = true)
breakingeven = request.security(apSyminfo + '_INOUTMONEYBETWEENPERCENTAGE', 'D', close, ignore_invalid_symbol = true)
profabilityTip = 'The percentage distribution of addresses by profitability at the current price.\n\n' + 
                 'Importance: A high percentage of profiting addresses may indicate potential selling pressure, as investors might look to realize gains. ' +
                 'Conversely, a higher proportion of losing addresses could suggest reduced selling pressure, as holders might prefer to wait for prices to recover. ' +
                 'The distribution also provides insights into market sentiment and potential future price movements.'

[inflowN, inflowNC] = request.security(apSyminfo + '_INFLOWTXVOLUME', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[inflow, inflowC]  = request.security(apSyminfo + '_INFLOWTXVOLUMEUSD', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[outflowN, outflowNC] = request.security(apSyminfo + '_OUTFLOWTXVOLUME', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[outflow, outflowC] = request.security(apSyminfo + '_OUTFLOWTXVOLUMEUSD', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
exFlowTip = 'Importance: Large inflows to exchanges can indicate potential selling pressure, while large outflows might suggest accumulation or long-term holding.'

[MinflowN, MinflowNC] = request.security(apSyminfo + '_MINERINFLOWS', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[Minflow, MinflowC]  = request.security(apSyminfo + '_MINERINFLOWSUSD', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[MoutflowN, MoutflowNC] = request.security(apSyminfo + '_MINEROUTFLOWS', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[Moutflow, MoutflowC] = request.security(apSyminfo + '_MINEROUTFLOWSUSD', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
MexFlowTip = 'Importance: High inflows may indicate selling pressure, while low inflows or outflows suggest miners are holding, signaling confidence in the asset.'

[taransN, taransNC] = request.security(apSyminfo + '_TXVOLUME', 'D',  [close, close / close[1] - 1], ignore_invalid_symbol = true)
[tarans, taransC] = request.security(apSyminfo + '_TXVOLUMEUSD', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
taransTip = 'On-Chain Volume: The total value of transactions conducted on a blockchain within a specific period.\n\n' +
             'Importance: On-chain volume reflects actual usage of the network, indicating how actively a cryptocurrency is being utilized for transactions.'

[mcap, mcap1, mcapC] = request.security(apSyminfo + '_MARKETCAP', 'D', [close, close[1], close / close[1] - 1], ignore_invalid_symbol = true)
mcapTip = 'Market Capitalization is the total value of a cryptocurrency\'s circulating supply, calculated by multiplying the current price by the total supply.\n\n' +
          'Importance: Market cap is a key indicator of a cryptocurrency’s size and market dominance. It helps compare the relative size of different cryptocurrencies.'

var string dom = ''
if apSyminfo == 'BTC'
    dom := 'TOTAL'
else if apSyminfo == 'ETH'
    dom := 'TOTAL2'
else
    dom := 'TOTAL3'

domTip = dom == 'TOTAL2' ? ' (excl. BTC)' : dom == 'TOTAL3' ? ' (excl. BTC and ETH)' : ''

[total, total1] = request.security(dom, 'D', [close, close[1]])
totalTip = apSyminfo + ' Market Capitalization: ' +  str.tostring(mcap, format.volume) + 
           '\nTotal Market Capitalization' + domTip + ': ' +  str.tostring(total, format.volume) 
totalTip2 = 'Market dominance is the percentage of a cryptocurrency\'s market cap relative to the total market cap of all cryptocurrencies' + domTip + '.\n\n' +
             'Importance: It indicates the cryptocurrency’s market influence and relative strength compared to others.'

[active, activeC] = request.security(apSyminfo + '_ACTIVEADDRESSES', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
activeTip = 'The addresses that made one or more on-chain transaction(s) on a given day.\n\n' +
             'Importance: A higher number of active addresses suggests greater network activity and user adoption, which can be a sign of a healthy ecosystem.'

[github, githubC] = request.security(apSyminfo + '_GITHUBCOMMITS', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
githubTip = 'Developer Activity is the level of activity on a cryptocurrency’s public repositories (e.g., GitHub).\n\n' +
             'Importance: Strong developer activity is a sign of ongoing innovation, updates, and a healthy project.'

[tvl, tvlC] = request.security(apSyminfo + '_TVL', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
tvlTip = 'The total value of assets locked in a decentralized finance (DeFi) protocol.\n\n' +
          'Importance: TVL is a key metric for DeFi platforms, indicating the level of trust and the amount of liquidity in a protocol.'

[mvrv, mvrvC] = request.security(apSyminfo + '_MVRV', 'D', [close, close / close[1] - 1], ignore_invalid_symbol = true)
mvrvTip = 'Ratio of market cap (in USD) to realized Marker Cap (in USD).\n\n' +
          'Importance: The MVRV ratio is a key indicator used to assess potential market tops or bottoms. ' +
          'A high MVRV ratio may suggest that the asset is overvalued and a price correction could be imminent, while a low ratio could indicate undervaluation, signaling a buying opportunity. ' +
          'It helps traders and investors identify extreme market conditions.'

pTelegram = request.security(apSyminfo + '_TELEGRAMPOSITIVE', 'D', close, ignore_invalid_symbol = true)
mTelegram = request.security(apSyminfo + '_TELEGRAMNEGATIVE', 'D', close, ignore_invalid_symbol = true)
nTelegram = request.security(apSyminfo + '_TELEGRAMNEUTRAL', 'D', close, ignore_invalid_symbol = true)
telegramTip = 'The general sentiment or mood of the community and investors as expressed on social media (Telegram).\n\n' +
              'Importance: Positive sentiment often correlates with price increases, while negative sentiment can signal potential downtrends.'

traders = request.security(apSyminfo + '_TRADERS', 'D', close, ignore_invalid_symbol = true)
tradersB = request.security(apSyminfo + '_TRADERSBALANCE', 'D', close, ignore_invalid_symbol = true)

cruisers = request.security(apSyminfo + '_CRUISERS', 'D', close, ignore_invalid_symbol = true)
cruisersB = request.security(apSyminfo + '_CRUISERSBALANCE', 'D', close, ignore_invalid_symbol = true)

hodlers = request.security(apSyminfo + '_HODLERS', 'D', close, ignore_invalid_symbol = true)
hodlersB = request.security(apSyminfo + '_HODLERSBALANCE', 'D', close, ignore_invalid_symbol = true)

holdingBehaviorTip = 'The distribution of cryptocurrency addresses by holding behavior: Traders (short-term), Cruisers (mid-term), and Hodlers (long-term).\n\n' +
                     'Importance: A higher number of Traders can signal volatility, Hodlers suggest long-term confidence, and Cruisers indicate moderate holding periods. ' +
                     'This distribution helps predict market behavior based on holder types.'

tradersP = traders / (traders + cruisers + hodlers)
cruisersP = cruisers / (traders + cruisers + hodlers)
hodlersP = hodlers / (traders + cruisers + hodlers)
tradersBP = tradersB / (tradersB + cruisersB + hodlersB)
cruisersBP = cruisersB / (tradersB + cruisersB + hodlersB)
hodlersBP = hodlersB / (tradersB + cruisersB + hodlersB)

retails = request.security(apSyminfo + '_RETAIL', 'D', close, ignore_invalid_symbol = true)
retailsA = request.security(apSyminfo + '_RETAILASSETS', 'D', close, ignore_invalid_symbol = true)

whales = request.security(apSyminfo + '_WHALES', 'D', close, ignore_invalid_symbol = true)
whalesA = request.security(apSyminfo + '_WHALESASSETS', 'D', close, ignore_invalid_symbol = true)

investors = request.security(apSyminfo + '_INVESTORS', 'D', close, ignore_invalid_symbol = true)
investorsA = request.security(apSyminfo + '_INVESTORSASSETS', 'D', close, ignore_invalid_symbol = true)

userTypesTip = 'The distribution of cryptocurrency holdings among Retail (small holders), Whales (large holders), and Investors (institutional players).\n\n' +
               'Importance: Retail holders reflect broad adoption but can be more reactive to market changes. Whales have the power to move markets with large trades, affecting volatility. ' +
               'Investors often indicate long-term confidence, contributing to stability. This distribution helps assess the potential impact of different user groups on the market.'

retailsX = retails / (retails + whales + investors)
whalesX = whales / (retails + whales + investors)
investorsX = investors / (retails + whales + investors)
retailsP = retailsA / (retailsA + whalesA + investorsA)
whalesP = whalesA / (retailsA + whalesA + investorsA)
investorsP = investorsA / (retailsA + whalesA + investorsA)

cghTip = 'The daily percentage change'

//---------------------------------------------------------------------------------------------------------------------}
// Dashboard
//---------------------------------------------------------------------------------------------------------------------{

tablePos = perfPos == 'Bottom Left' ? position.bottom_left : perfPos == 'Top Right' ? position.top_right : position.bottom_right
textSize = perfText == 'Small' ? size.small : perfText == 'Normal' ? size.normal : size.tiny

if barstate.islast 
    var table oiT = table.new(tablePos, 5, 31, bgcolor = #1e222d, border_color = #373a46, border_width = 1, frame_color = #373a46, frame_width = 1, force_overlay = true)

    if syminfo.type == 'crypto'
        if na(profiting) and na(inflow) and na(Minflow) and na(tarans) and na(mcap) and na(active) and na(tvl) and na(mvrv) and na(github) and na(pTelegram) and na(traders) and na(retails) //and na(bullVol)
            table.cell(oiT, 0, 1, 'No on-chain data found\n for the ' + apSyminfo + ' symbol.', text_size = textSize, text_color = color.white, text_halign = text.align_center)
            table.merge_cells(oiT, 0, 1, 4, 1)
        else
            if block

                if not na(profiting)
                    table.merge_cells(oiT, 0, 0, 1, 0)
                    table.cell(oiT, 2, 0, 'Profiting', text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.cell(oiT, 3, 0, 'Losing', text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.cell(oiT, 4, 0, 'Breaking\nEven', text_size = textSize, text_color = tlColor, text_halign = text.align_center)

                    table.cell(oiT, 0, 1, apSyminfo + ' Profitability', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = profabilityTip)
                    table.merge_cells(oiT, 0, 1, 1, 1)
                    table.cell(oiT, 2, 1, str.tostring(profiting, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center, 
                           tooltip = 'The percentage of ' + apSyminfo + ' addresses that are profiting on their positions at current price')
                    table.cell(oiT, 3, 1, str.tostring(losing, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center, 
                           tooltip = 'The percentage of ' + apSyminfo + ' addresses that are losing money on their positions at current price')
                    table.cell(oiT, 4, 1, str.tostring(breakingeven, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center, 
                           tooltip = 'The percentage of ' + apSyminfo + ' addresses that are breaking even on their positions at current price')

                    table.cell(oiT, 0, 2, '', bgcolor = naColor, height = 1)
                    table.merge_cells(oiT, 0, 2, 4, 2)

                if not na(inflow) or not na(outflow) or not na(Minflow) or not na(Moutflow) or not na(tarans)
                    table.cell(oiT, 0, 3, 'Flow', text_size = textSize, text_color = tlColor, text_halign = text.align_left)
                    table.cell(oiT, 1, 3, apSyminfo, text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.merge_cells(oiT, 1, 3, 2, 3)
                    table.cell(oiT, 3, 3, 'USD', text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.merge_cells(oiT, 3, 3, 4, 3)

                if inflow > 0 or inflowN > 0
                    table.cell(oiT, 0, 4, 'EX-IN', text_size = textSize, text_color = tlColor, text_halign = text.align_left,
                           tooltip = 'The amount of a given crypto-asset flowing into exchanges and measured in native units/USD.\n\n' + exFlowTip)
                    table.cell(oiT, 1, 4, str.tostring(inflowN, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 2, 4, not na(inflowNC) ? str.tostring(inflowNC, '#.##%') : '-', text_size = textSize, text_color = inflowN == 0 ? txColor : inflowNC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 
                    table.cell(oiT, 3, 4, str.tostring(inflow, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 4, not na(inflowC) ? str.tostring(inflowC, '#.##%') : '-', text_size = textSize, text_color = inflow == 0 ? txColor : inflowC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if outflow > 0 or outflowN > 0
                    table.cell(oiT, 0, 5, 'EX-OUT', text_size = textSize, text_color = tlColor, text_halign = text.align_left,
                           tooltip = 'Total amount of a given crypto-asset in native units/USD flowing out of exchanges\' withdrawal addresses.\n\n' + exFlowTip)
                    table.cell(oiT, 1, 5, str.tostring(outflowN, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 2, 5, not na(outflowNC) ? str.tostring(outflowNC, '#.##%') : '-', text_size = textSize, text_color = outflowN == 0 ? txColor : outflowNC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 
                    table.cell(oiT, 3, 5, str.tostring(outflow, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 5, not na(outflowC) ? str.tostring(outflowC, '#.##%') : '-', text_size = textSize, text_color = outflow == 0 ? txColor : outflowC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if Minflow > 0 or MinflowN > 0
                    table.cell(oiT, 0, 6, 'MNR-IN', text_size = textSize, text_color = tlColor, text_halign = text.align_left,
                           tooltip = 'Miner inflows for all mining pools measured in native units/USD.\n\n' + MexFlowTip)
                    table.cell(oiT, 1, 6, str.tostring(MinflowN, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 2, 6, not na(MinflowNC) ? str.tostring(MinflowNC, '#.##%') : '-', text_size = textSize, text_color = MinflowN == 0 ? txColor : MinflowNC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 
                    table.cell(oiT, 3, 6, str.tostring(Minflow, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 6, not na(MinflowC) ? str.tostring(MinflowC, '#.##%') : '-', text_size = textSize, text_color = Minflow == 0 ? txColor : MinflowC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if Moutflow > 0 or MoutflowN > 0
                    table.cell(oiT, 0, 7, 'MNR-OUT', text_size = textSize, text_color = tlColor, text_halign = text.align_left,
                           tooltip = ' Miner outflows for all mining pools measured in native units/USD.\n\n' + MexFlowTip)
                    table.cell(oiT, 1, 7, str.tostring(MoutflowN, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 2, 7, not na(MoutflowNC) ? str.tostring(MoutflowNC, '#.##%') : '-', text_size = textSize, text_color = MoutflowN == 0 ? txColor : MoutflowNC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 
                    table.cell(oiT, 3, 7, str.tostring(Moutflow, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 7, not na(MoutflowC) ? str.tostring(MoutflowC, '#.##%') : '-', text_size = textSize, text_color = Moutflow == 0 ? txColor : MoutflowC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if tarans > 0 or taransN > 0
                    table.cell(oiT, 0, 8, 'TX', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = taransTip)
                    table.cell(oiT, 1, 8, str.tostring(taransN, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 2, 8, not na(taransNC) ? str.tostring(taransNC, '#.##%') : '-', text_size = textSize, text_color = taransN == 0 ? txColor : taransNC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 
                    table.cell(oiT, 3, 8, str.tostring(tarans, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 8, not na(taransC) ? str.tostring(taransC, '#.##%') : '-', text_size = textSize, text_color = tarans == 0 ? txColor : taransC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(mcap) or not na(active) or not na(tvl) or not na(github)
                    table.cell(oiT, 0, 11, '', bgcolor = naColor, height = 1)
                    table.merge_cells(oiT, 0, 11, 4, 11)

                if not na(mcap)
                    table.cell(oiT, 0, 12, 'Market Capitalization', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = mcapTip)
                    table.merge_cells(oiT, 0, 12, 2, 12)
                    table.cell(oiT, 3, 12, str.tostring(mcap, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 12, not na(mcapC) ? str.tostring(mcapC, '#.##%') : '-', text_size = textSize, text_color = mcap == 0 ? txColor : mcapC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                    table.cell(oiT, 0, 13, 'Market Dominance', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = totalTip2)
                    table.merge_cells(oiT, 0, 13, 2, 13)
                    table.cell(oiT, 3, 13, mcap/total > .9999 ? '>99.99%' : mcap/total < .0001 ? '<0.01%' : str.tostring(mcap/total, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center, tooltip = totalTip + '\n\n' + apSyminfo + ' Market Dominance: %' + str.tostring(mcap/total * 100)) 
                    table.cell(oiT, 4, 13, not na(mcapC) ? str.tostring( (mcap/total) / (mcap1/total1) - 1, '#.##%') : '-', text_size = textSize, text_color = mcap == 0 ? txColor : (mcap/total) > (mcap1/total1) ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(active)
                    table.cell(oiT, 0, 14, 'Active Addresses', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = activeTip)
                    table.merge_cells(oiT, 0, 14, 2, 14)
                    table.cell(oiT, 3, 14, str.tostring(active, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 14, not na(activeC) ? str.tostring(activeC, '#.##%') : '-', text_size = textSize, text_color = active == 0 ? txColor : activeC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(tvl)
                    table.cell(oiT, 0, 15, 'Total Value Locked', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = tvlTip)
                    table.merge_cells(oiT, 0, 15, 2, 15)
                    table.cell(oiT, 3, 15, str.tostring(tvl, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 15, not na(tvlC) ? str.tostring(tvlC, '#.##%') : '-', text_size = textSize, text_color = tvl == 0 ? txColor : tvlC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(mvrv)
                    table.cell(oiT, 0, 16, 'Market to Realized Value', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = mvrvTip)
                    table.merge_cells(oiT, 0, 16, 2, 16)
                    table.cell(oiT, 3, 16, str.tostring(mvrv, '#.##'), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 16, not na(mvrvC) ? str.tostring(mvrvC, '#.##%') : '-', text_size = textSize, text_color = mvrv == 0 ? txColor : mvrvC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(github)
                    table.cell(oiT, 0, 17, 'Developer Activity', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = githubTip)
                    table.merge_cells(oiT, 0, 17, 2, 17)
                    table.cell(oiT, 3, 17, str.tostring(github, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center) 
                    table.cell(oiT, 4, 17, not na(githubC) ? str.tostring(githubC, '#.##%') : '-', text_size = textSize, text_color = github == 0 ? txColor : githubC > 0 ? upColor : dnColor, text_halign = text.align_center, tooltip = cghTip) 

                if not na(pTelegram)
                    table.cell(oiT, 0, 18, '', bgcolor = naColor, height = 1)
                    table.merge_cells(oiT, 0, 18, 4, 18)

                    table.cell(oiT, 0, 19, 'Social Sentiment', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = telegramTip)
                    table.merge_cells(oiT, 0, 19, 1, 19)
                    table.cell(oiT, 2, 19, str.tostring(pTelegram) + '(+)', text_size = textSize, text_color = txColor, text_halign = text.align_center,
                                               tooltip = 'The amount of messages with positive connatation in top Telegram groups for ' + apSyminfo + ' crypto-asset')
                    table.cell(oiT, 3, 19, str.tostring(mTelegram) + '(-)', text_size = textSize, text_color = txColor, text_halign = text.align_center, 
                                               tooltip = 'The amount of messages with negative connatation in top Telegram groups for ' + apSyminfo + ' crypto-asset')
                    table.cell(oiT, 4, 19, str.tostring(nTelegram), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                                               tooltip = 'The amount of messages with neutral connatation in top Telegram groups for ' + apSyminfo + ' crypto-asset')

                if not na(investors) or not na(whales) or not na(cruisers) or not na(retails) or not na(hodlers) or not na(traders)
                    table.cell(oiT, 0, 21, '', bgcolor = naColor, height = 1)
                    table.merge_cells(oiT, 0, 21, 4, 21)

                    table.cell(oiT, 1, 22, '#', text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.cell(oiT, 2, 22, '#%', text_size = textSize, text_color = tlColor, text_halign = text.align_center)
                    table.cell(oiT, 3, 22, apSyminfo, text_size = textSize, text_color = tlColor, text_halign = text.align_center, tooltip = 'Native Units - ' + apSyminfo)
                    table.cell(oiT, 4, 22, apSyminfo + '%', text_size = textSize, text_color = tlColor, text_halign = text.align_center)

                if not na(traders)
                    table.cell(oiT, 0, 23, 'Traders', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = holdingBehaviorTip)
                    table.cell(oiT, 1, 23, str.tostring(traders, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center, 
                         tooltip = 'The number of Traders\' addresses')
                    table.cell(oiT, 2, 23, str.tostring(tradersP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Traders\' addresses out of all addresses')
                    table.cell(oiT, 3, 23, str.tostring(tradersB, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The balance of assets belonging to Traders')
                    table.cell(oiT, 4, 23, str.tostring(tradersBP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'Total percentage of assets belonging to Traders')

                if not na(cruisers)
                    table.cell(oiT, 0, 24, 'Cruisers', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = holdingBehaviorTip)
                    table.cell(oiT, 1, 24, str.tostring(cruisers, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The number of Cruisers\' addresses')
                    table.cell(oiT, 2, 24, str.tostring(cruisersP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Cruisers\' addresses out of all addresses')
                    table.cell(oiT, 3, 24, str.tostring(cruisersB, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The balance of assets belonging to Cruisers')
                    table.cell(oiT, 4, 24, str.tostring(cruisersBP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'Total percentage of assets belonging to Cruisers')

                if not na(hodlers)
                    table.cell(oiT, 0, 25, 'Hodlers', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = holdingBehaviorTip)
                    table.cell(oiT, 1, 25, str.tostring(hodlers, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The number of Hodlers\' addresses')
                    table.cell(oiT, 2, 25, str.tostring(hodlersP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Hodlers\' addresses out of all addresses')
                    table.cell(oiT, 3, 25, str.tostring(hodlersB, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The balance of assets belonging to Hodlers')
                    table.cell(oiT, 4, 25, str.tostring(hodlersBP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'Total percentage of assets belonging to Hodlers')

                if not na(retails)
                    table.cell(oiT, 0, 26, '', height = 1)
                    table.merge_cells(oiT, 0, 26, 4, 26)

                    table.cell(oiT, 0, 27, 'Retails', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = userTypesTip)
                    table.cell(oiT, 1, 27, str.tostring(retails, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The number of Retail users')
                    table.cell(oiT, 2, 27, retailsX > .9999 ? '>99.99%' : retailsX < .0001 ? '<0.01%' : str.tostring(retailsX, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Retail users out of all users %' + str.tostring(retailsX * 100))
                    table.cell(oiT, 3, 27, str.tostring(retailsA, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The amount of asset held by Retail users in a given day')
                    table.cell(oiT, 4, 27, str.tostring(retailsP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of assets belonging to Retail users')

                if not na(whales)
                    table.cell(oiT, 0, 28, 'Whales', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = userTypesTip)
                    table.cell(oiT, 1, 28, str.tostring(whales, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The number of Whales')
                    table.cell(oiT, 2, 28, whalesX > .9999 ? '>99.99%' : whalesX < .0001 ? '<0.01%' : str.tostring(whalesX, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Whales out of all users %' + str.tostring(whalesX * 100))
                    table.cell(oiT, 3, 28, str.tostring(whalesA, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The amount of asset held by Whales in a given day')
                    table.cell(oiT, 4, 28, str.tostring(whalesP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of assets belonging to Whales')

                if not na(investors)
                    table.cell(oiT, 0, 29, 'Investors', text_size = textSize, text_color = tlColor, text_halign = text.align_left, tooltip = userTypesTip)
                    table.cell(oiT, 1, 29, str.tostring(investors, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The number of Investors')
                    table.cell(oiT, 2, 29, investorsX > .9999 ? '>99.99%' : investorsX < .0001 ? '<0.01%' : str.tostring(investorsX, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of Investors out of all users %' + str.tostring(investorsX * 100))
                    table.cell(oiT, 3, 29, str.tostring(investorsA, format.volume), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The amount of asset held by Investors in a given day')
                    table.cell(oiT, 4, 29, str.tostring(investorsP, '#.##%'), text_size = textSize, text_color = txColor, text_halign = text.align_center,
                         tooltip = 'The percentage of assets belonging to Investors')
    else    
        table.cell(oiT, 0, 0, 'Only Cryptocurrencies.', text_size = size.normal, text_color = color.white, text_halign = text.align_left)

//---------------------------------------------------------------------------------------------------------------------}
// Plots
//---------------------------------------------------------------------------------------------------------------------{

chartTFinM = timeframe.in_seconds() / 60 >= 240

[plotA, plotB, plotC] = switch papDisplay
    opt1 => [interpolate(ta.sma(profiting * 100, papSmooth), 91), 100 - interpolate(ta.sma(losing * 100, papSmooth), 91), interpolate(ta.sma(breakingeven * 100, papSmooth), 91)]
    opt9 => [ta.sma(hodlersBP * 100, papSmooth), ta.sma(cruisersBP * 100, papSmooth), ta.sma(tradersBP * 100, papSmooth)]
    opt10 => [ta.sma(retailsP * 100, papSmooth), ta.sma(investorsP * 100, papSmooth), ta.sma(whalesP * 100, papSmooth)]

a = plot(chartTFinM ? plotA : na, 'Profiting/Hodler/Retail', papColor, display = display)
signalA = smooth(plotA, papMAL, papMAT)
z = plot(chartTFinM and papMAT != 'None' ? signalA : na, 'Profiting/Hodler/Retail Signal', papColor, display = display)
b = plot(0, color = color(na), editable = false, display = display)
fill(a, b, 100, 0, top_color = color.new(papColor, 73), bottom_color = color.new(chart.bg_color, 80))
fill(a, z, plotA > signalA ? color.new(papColor, 73) : color.new(papColor, 93))

c = plot(chartTFinM ? plotB : na, 'Losing/Cruiser/Investor', lapColor, display = display)
signalB = smooth(plotB, papMAL, papMAT)
y = plot(chartTFinM and papMAT != 'None' ? signalB : na, 'Losing/Cruiser/Investor Signal', lapColor, display = display)
e = plot(papDisplay == opt1 ? 100 : 0, color = color(na), editable = false, display = display)
fill(c, e, 100, 0, top_color = papDisplay == opt1 ? color.new(chart.bg_color, 80) : color.new(lapColor, 73), bottom_color = papDisplay == opt1 ? color.new(lapColor, 73) : color.new(chart.bg_color, 80))
fill(c, y, plotB > signalB ? color.new(lapColor, 93) : color.new(lapColor, 73))

d = plot(chartTFinM ? plotC : na, 'BreakingEven/Trader/Whale', bapColor, display = display)
signalC = smooth(plotC, papMAL, papMAT)
g = plot(chartTFinM and papMAT != 'None' ? signalC : na, 'BreakingEven/Trader/Whale Signal', bapColor, display = display)
fill(d, b, 100, 0, top_color = color.new(bapColor, 73), bottom_color = color.new(chart.bg_color, 80))
fill(d, g, plotC > signalC ? color.new(bapColor, 73) : color.new(bapColor, 93))

[plotI, plotO, plotD, plotDC] = switch papDisplay
    opt2 => [ta.sma(inflow, papSmooth), -ta.sma(outflow, papSmooth), math.abs(inflow - outflow), inflow > outflow ? papColor : lapColor]
    opt8 => [ta.sma(Minflow, papSmooth), -ta.sma(Moutflow, papSmooth), math.abs(Minflow - Moutflow), Minflow > Moutflow ? papColor : lapColor]
    opt11 => [ta.sma(pTelegram, papSmooth), -ta.sma(mTelegram, papSmooth), ta.sma(nTelegram, papSmooth), bapColor]

o = plot(chartTFinM ? plotI : na, 'Inflow/LargeBuyers/Positive', color.new(papColor, 73), style = plot.style_area, display = display)
signalI = smooth(plotI, papMAL, papMAT)
s = plot(chartTFinM and papMAT != 'None' ? signalI : na, 'Inflow/LargeBuyers/Positive Signal', papColor, display = display)
fill(o, s, plotI > signalI ? color.new(papColor, 73) : color.new(papColor, 93))

t = plot(chartTFinM ? plotO : na, 'Outflow/LargeSellers/Negative', color.new(lapColor, 73), style = plot.style_area, display = display)
signalO = smooth(plotO, papMAL, papMAT)
k = plot(chartTFinM and papMAT != 'None' ? signalO : na, 'Outflow/LargeSellers/Negative Signal', lapColor, display = display)
fill(t, k, plotO > signalO ? color.new(lapColor, 93) : color.new(lapColor, 73))

plot(chartTFinM ? plotD : na, 'Netflow/NetActivity/Neurtal', plotDC, style = plot.style_columns, display = display)

plot = switch papDisplay
    opt3 => ta.sma(tarans, papSmooth)
    opt4 => ta.sma(mcap, papSmooth)
    opt12 => ta.sma(mcap/total * 100, papSmooth)
    opt5 => ta.sma(active, papSmooth)
    opt6 => ta.sma(tvl, papSmooth)
    opt13 => ta.sma(mvrv, papSmooth)

plot(chartTFinM ? plot : na, 'TX/MCAP/DOM/ACTIVE/TVL/MVRV/DEV', papColor, style = plot.style_columns, display = display)
plot(chartTFinM and papMAT != 'None' ? smooth(plot, papMAL, papMAT) : na, 'TX/MCAP/DOM/ACTIVE/TVL/MVRV/DEV Signal', lapColor, display = display) 

[test, txA, txB, txC, txD] = switch papDisplay
    opt1 => [not na(profiting), 'Profiting Addresses · ' + str.tostring(profiting, '#.##%'), 'Losing Addresses · ' + str.tostring(losing, '#.##%'), 'Breaking Even Addresses · ' + str.tostring(breakingeven, '#.##%'), '']
    opt9 => [not na(hodlers), 'Hodlers\' Addresses Balance · ' + str.tostring(hodlersB, format.volume) + ' (' + str.tostring(hodlersBP, '#.##%') + ')', 'Cruisers\' Addresses Balance · ' + str.tostring(cruisersB, format.volume) + ' (' + str.tostring(cruisersBP, '#.##%') + ')', 'Traders\' Addresses Balance · ' + str.tostring(tradersB, format.volume) + ' (' + str.tostring(tradersBP, '#.##%') + ')', '']
    opt10 => [not na(retails), 'Retail Users Balance · ' + str.tostring(retailsA, format.volume) + ' (' + str.tostring(retailsP, '#.##%') + ')', 'Investor Users Balance · ' + str.tostring(investorsA, format.volume) + ' (' + str.tostring(investorsP, '#.##%') + ')', 'Whale Users Balance · ' + str.tostring(whalesA, format.volume) + ' (' + str.tostring(whalesP, '#.##%') + ')', '']
    opt2 => [inflow > 0 or inflowN > 0, 'Exchange Inflow · ' + str.tostring(inflow, format.volume),  'Exchange Outflow · ' + str.tostring(outflow, format.volume), '', 'Exchange Netflow · ' + str.tostring(inflow - outflow, format.volume)]
    opt8 => [Minflow > 0 or MinflowN > 0, 'Miners Inflow · ' + str.tostring(Minflow, format.volume),  'Miners Outflow · '  + str.tostring(Moutflow, format.volume), '', 'Miners Netflow · '  + str.tostring(Minflow - Moutflow, format.volume)]
    opt11 => [not na(pTelegram), 'Positive Connotation · ' + str.tostring(pTelegram), 'Negative Connotation · ' + str.tostring(mTelegram), 'Neutral Connotation · ' + str.tostring(nTelegram), '']
    opt3 => [tarans > 0 or taransN > 0, 'On-Chain Volume · ' + str.tostring(tarans, format.volume), '', '', '']
    opt4 => [not na(mcap), 'Market Capitalization · ' + str.tostring(mcap, format.volume), '', '', '']
    opt12 => [not na(mcap), 'Market Dominance · ' + str.tostring(mcap/total, '#.##%'), '', '', '']
    opt5 => [not na(active), 'Active Addresses · ' + str.tostring(active, format.volume), '', '', '']
    opt13 => [not na(mvrv), 'Market Value to Realized Value · ' + str.tostring(mvrv, '#.##'), '', '', '']
    opt6 => [not na(tvl), 'Total Value Locked · ' + str.tostring(tvl, format.volume), '', '', '']

var table legend = table.new(position.middle_right, 3, 3)
if test and chartTFinM
    if txA != ''
        table.cell(legend, 0, 0, txA, text_size = size.small, text_color = color.new(papColor, 0), text_halign = text.align_right)
        table.cell(legend, 2, 0, "█", text_size = size.small, text_color = color.new(papColor, 0), text_halign = text.align_right)
    if txB != ''
        table.cell(legend, 0, 1, txB, text_size = size.small, text_color = color.new(lapColor, 0), text_halign = text.align_right)
        table.cell(legend, 2, 1, "█", text_size = size.small, text_color = color.new(lapColor, 0), text_halign = text.align_right)
    if txC != ''
        table.cell(legend, 0, 2, txC, text_size = size.small, text_color = color.new(bapColor, 0), text_halign = text.align_right)
        table.cell(legend, 2, 2, "█", text_size = size.small, text_color = color.new(bapColor, 0), text_halign = text.align_right)
    if txD != ''
        table.cell(legend, 0, 2, txD, text_size = size.small, text_color = color.new(bapColor, 0), text_halign = text.align_right)
        table.cell(legend, 1, 2, "█", text_size = size.small, text_color = color.new(papColor, 0), text_halign = text.align_right)
        table.cell(legend, 2, 2, "█", text_size = size.small, text_color = color.new(lapColor, 0), text_halign = text.align_right)
else
    if papDisplay != 'None' and syminfo.type == 'crypto'
        if chartTFinM
            table.cell(legend, 0, 0, papDisplay + ' on-chain data for ' + apSyminfo + ' is not available. ', text_size = size.normal, text_color = chart.fg_color, text_halign = text.align_center)
        else
            table.cell(legend, 0, 0, 'On-chain data visualization is supported for 4H and higher timeframes.', text_size = size.normal, text_color = chart.fg_color, text_halign = text.align_center)

    else if syminfo.type != 'crypto'
        table.cell(legend, 0, 0, 'Only Cryptocurrencies.', text_size = size.normal, text_color = chart.fg_color, text_halign = text.align_right)

//---------------------------------------------------------------------------------------------------------------------}