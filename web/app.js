/**
 * A-Share causal strategy backtest UI.
 */

let chartInstance = null;
let currentBacktestData = null;
let mungerStocksData = [];

document.addEventListener('DOMContentLoaded', async () => {
  initChart();
  bindEvents();
  await loadStrategies();
  await fetchMungerStocks('');
  // 页面初次加载时自动执行默认股票 (贵州茅台 600519) 与大组合配仓回测
  fetchAndRenderBacktest();
  fetchPortfolioBacktest();
});


function initChart() {
  const chartDom = document.getElementById('klineChart');
  chartInstance = echarts.init(chartDom, 'dark');
  window.addEventListener('resize', () => chartInstance.resize());
}

function bindEvents() {
  const searchInput = document.getElementById('stockSearchInput');
  const suggestList = document.getElementById('stockSuggestList');
  const mungerListSearch = document.getElementById('mungerListSearch');
  const capitalInput = document.getElementById('capitalInput');

  let debounceTimer = null;

  // 本金变更监听
  capitalInput.addEventListener('change', () => {
    const val = parseFloat(capitalInput.value) || 200000;
    const formatCapital = (val / 10000).toFixed(0) + '万';
    document.getElementById('capitalText').innerText = formatCapital;
  });

  // 全局股票搜索框
  searchInput.addEventListener('input', (e) => {
    clearTimeout(debounceTimer);
    const query = e.target.value.trim();
    debounceTimer = setTimeout(() => {
      fetchStockSuggestions(query);
    }, 180);
  });

  searchInput.addEventListener('focus', () => {
    const val = searchInput.value.split(' - ')[0] || '';
    fetchStockSuggestions(val);
  });

  // 左侧芒格好股票池搜索
  mungerListSearch.addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    const filtered = mungerStocksData.filter(s => 
      s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
    );
    renderMungerStockList(filtered);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-input-wrapper')) {
      suggestList.classList.add('hidden');
    }
  });

  document.getElementById('runBtn').addEventListener('click', () => {
    fetchAndRenderBacktest();
    fetchPortfolioBacktest();
  });

  chartInstance.on('click', (params) => {
    if (params.componentType === 'markPoint' && params.data && params.data.tradeRecord) {
      renderDecisionDrawer(params.data.tradeRecord, params.data.type);
    }
  });
}

let latestPortfolioData = null;

function selectedBacktestOptions() {
  const proxyCheckbox = document.getElementById('researchProxyMode');
  const isProxy = proxyCheckbox ? proxyCheckbox.checked : true;
  return {
    strategy: document.getElementById('strategySelect')?.value || 'causal_ml',
    backtest_mode: isProxy ? 'RESEARCH_PROXY' : 'STRICT'
  };
}


async function loadStrategies() {
  const response = await fetch('/api/strategies');
  const strategies = await response.json();
  const select = document.getElementById('strategySelect');
  select.innerHTML = strategies
    .map(s => {
      const name = typeof s === 'string' ? s : s.name;
      const desc = s.description ? ` - ${s.description}` : '';
      const customBadge = s.is_custom ? '🔥 [热插拔] ' : '';
      const isSelected = name === 'causal_ml' ? 'selected' : '';
      return `<option value="${name}" ${isSelected}>${customBadge}${name}${desc}</option>`;
    })
    .join('');
}




/**
 * 调取【全组合多股总体战报 + 固定风险资金分配】
 */
async function fetchPortfolioBacktest() {
  const initialCapital = parseFloat(document.getElementById('capitalInput').value) || 200000;
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;

  const container = document.getElementById('kellyAllocationsList');
  if (container) {
    container.innerHTML = '<div class="loading-state">正在计算固定风险配仓...</div>';
  }

  try {
    const response = await fetch('/api/run_portfolio_backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        initial_capital: initialCapital,
        start_date: startDate,
        end_date: endDate,
        ...selectedBacktestOptions()
      })
    });

    const data = await response.json();
    if (data.error) {
      if (container) container.innerHTML = `<div class="empty-state">计算失败: ${data.error}</div>`;
      return;
    }

    latestPortfolioData = data;
    renderPortfolioMetrics(data.portfolio_metrics);
    renderKellyAllocations(data.kelly_allocations, initialCapital);

  } catch (err) {
    console.error('Fetch portfolio backtest error:', err);
    if (container) container.innerHTML = '<div class="empty-state">配仓调取超时，请重新点击运行回测</div>';
  }
}

function renderPortfolioMetrics(pm) {
  if (!pm) return;
  document.getElementById('pMetricAssets').innerText = `¥${(pm.initial_capital || 200000).toLocaleString()} ➔ ¥${(pm.final_equity || 200000).toLocaleString()}`;
  
  const retElem = document.getElementById('pMetricReturn');
  retElem.innerText = (pm.total_return_pct >= 0 ? '+' : '') + pm.total_return_pct + '%';
  retElem.className = 'p-val ' + (pm.total_return_pct >= 0 ? 'green' : 'red');

  const pnlPrefix = pm.total_pnl >= 0 ? '+¥' : '-¥';
  document.getElementById('pMetricPnL').innerText = `净利: ${pnlPrefix}${Math.abs(pm.total_pnl || 0).toLocaleString()}`;

  document.getElementById('pMetricWinRate').innerText = pm.overall_win_rate_pct + '%';
  document.getElementById('pMetricTradesCount').innerText = `${pm.win_trades_count} 胜 / ${pm.loss_trades_count} 负 (${pm.total_trades_count}笔)`;

  document.getElementById('pMetricPLRatio').innerText = `${pm.overall_profit_loss_ratio} : 1`;
  document.getElementById('pMetricMaxDD').innerText = pm.overall_max_dd_pct + '%';
}

/**
 * 打开分年度收益明细 Modal 弹窗
 */
function openYearlyModal() {
  const modal = document.getElementById('yearlyBreakdownModal');
  if (!modal) return;

  modal.style.display = 'flex';

  if (!latestPortfolioData || !latestPortfolioData.yearly_breakdown) {
    document.getElementById('yearlyCardsGrid').innerHTML = '<div class="empty-state">暂无年度统计数据</div>';
    return;
  }

  const pm = latestPortfolioData.portfolio_metrics || {};
  document.getElementById('modalPeriodText').innerText = `回测时间跨度: ${pm.backtest_period || '2024-01-01 至 2026-07-29'} (共 940 天 / 2.58 年)`;

  const yearly = latestPortfolioData.yearly_breakdown;

  // 渲染年度卡片
  const grid = document.getElementById('yearlyCardsGrid');
  grid.innerHTML = yearly.map(y => `
    <div class="yearly-card">
      <div class="y-title">${y.year} 年度战报</div>
      <div class="y-return ${y.return_pct >= 0 ? 'green' : 'red'}">${y.return_pct >= 0 ? '+' : ''}${y.return_pct}%</div>
      <div class="y-sub">年度净利: <strong>${y.net_pnl >= 0 ? '+¥' : '-¥'}${Math.abs(y.net_pnl).toLocaleString()}</strong></div>
      <div class="y-sub">胜率 ${y.win_rate_pct}% (${y.trades_count}笔平仓)</div>
    </div>
  `).join('');

  // 渲染年度表格
  const tbody = document.getElementById('yearlyTableBody');
  tbody.innerHTML = yearly.map(y => `
    <tr>
      <td><strong>${y.year} 年</strong></td>
      <td class="${y.net_pnl >= 0 ? 'green' : 'red'}">${y.net_pnl >= 0 ? '+' : ''}¥${y.net_pnl.toLocaleString()}</td>
      <td class="${y.return_pct >= 0 ? 'green' : 'red'}"><strong>${y.return_pct >= 0 ? '+' : ''}${y.return_pct}%</strong></td>
      <td>${y.win_rate_pct}%</td>
      <td>${y.trades_count} 笔</td>
    </tr>
  `).join('');
}

function closeYearlyModal() {
  const modal = document.getElementById('yearlyBreakdownModal');
  if (modal) modal.style.display = 'none';
}

function renderKellyAllocations(allocs, totalCap) {
  const container = document.getElementById('kellyAllocationsList');
  if (!container) return;

  const count = allocs ? allocs.length : 0;
  const badge = document.getElementById('portfolioBadge');
  if (badge) badge.innerHTML = `多股联动 + 固定风险上限 (共 <span style="color: #ff4d4f; font-weight: bold; font-size: 13px;">${count}</span> 只股票池)`;

  const countBadge = document.getElementById('kellyStockCountBadge');
  if (countBadge) countBadge.innerHTML = `(共 <span style="color: #ff4d4f; font-weight: bold; font-size: 13px;">${count}</span> 只推荐配仓股)`;

  if (!allocs || allocs.length === 0) {
    container.innerHTML = '<div class="empty-state">无配仓结果</div>';
    return;
  }

  container.innerHTML = allocs.map(k => `
    <div class="kelly-item" onclick="selectMungerCard('${k.symbol}', '${k.name}')">
      <div class="k-top">
        <span>${k.symbol} ${k.name} (¥${k.price})</span>
        <span class="k-alloc-badge">目标配仓 ${k.allocation_pct}%</span>
      </div>
      <div class="k-detail">
        <span>固定风险配仓</span>
        <span>分配金额: <strong>¥${k.recommend_capital.toLocaleString()}</strong> (${k.recommend_shares}股)</span>
      </div>
    </div>
  `).join('');
}

/**
 * 调取当前估值快照
 */
async function fetchMungerStocks(query) {
  const container = document.getElementById('mungerStockCardsList');
  try {
    const response = await fetch(`/api/munger_stocks?q=${encodeURIComponent(query)}`);
    mungerStocksData = await response.json();

    document.getElementById('mungerPoolCount').innerText = `${mungerStocksData.length} 只`;
    renderMungerStockList(mungerStocksData);
  } catch (err) {
    console.error('Fetch Munger stocks error:', err);
  }
}

function renderMungerStockList(stocks) {
  const container = document.getElementById('mungerStockCardsList');
  const currentSymbol = document.getElementById('selectedSymbol').value;

  if (!stocks || stocks.length === 0) {
    container.innerHTML = '<div class="empty-state">未找到匹配的估值快照</div>';
    return;
  }

  container.innerHTML = stocks.map(s => {
    const isActive = s.symbol === currentSymbol;
    const statusText = s.fundamental_status || 'UNKNOWN';
    const marketValueText = s.total_mv ? `市值 ${(s.total_mv / 1e8).toFixed(0)} 亿` : '市值未知';

    return `
      <div class="munger-stock-card ${isActive ? 'active' : ''}" onclick="selectMungerCard('${s.symbol}', '${s.name}')">
        <div class="card-top-line">
          <span class="stock-code-name">${s.symbol} ${s.name}</span>
          <span class="roe-tag">基本面 ${statusText}</span>
        </div>
        <div class="card-metrics-line">
          <span>PE: ${s.pe_ttm ? s.pe_ttm.toFixed(1) : '--'}</span>
          <span>PB: ${s.pb ? s.pb.toFixed(2) : '--'}</span>
          <span>${marketValueText}</span>
        </div>
      </div>
    `;
  }).join('');
}

function selectMungerCard(symbol, name) {
  document.getElementById('selectedSymbol').value = symbol;
  document.getElementById('stockSearchInput').value = `${symbol} - ${name}`;

  renderMungerStockList(mungerStocksData);
  // 点击股票卡片时，立即自动调取并渲染该股票的 K 线图、买卖点与交易记录
  fetchAndRenderBacktest();
}


async function fetchStockSuggestions(query) {
  const suggestList = document.getElementById('stockSuggestList');
  try {
    const response = await fetch(`/api/search_stocks?q=${encodeURIComponent(query)}`);
    const stocks = await response.json();

    if (!stocks || stocks.length === 0) {
      suggestList.innerHTML = '<li class="suggest-item" style="color: #8b949e">无匹配股票</li>';
      suggestList.classList.remove('hidden');
      return;
    }

    suggestList.innerHTML = stocks.map(s => `
      <li class="suggest-item" data-symbol="${s.symbol}" data-name="${s.name}">
        <div>
          <span class="code-badge">${s.symbol}</span> - 
          <span class="name-text">${s.name}</span>
        </div>
        <div class="price-text">¥${s.price || '--'}</div>
      </li>
    `).join('');

    suggestList.classList.remove('hidden');

    suggestList.querySelectorAll('.suggest-item').forEach(item => {
      item.addEventListener('click', () => {
        const symbol = item.getAttribute('data-symbol');
        const name = item.getAttribute('data-name');
        if (symbol) {
          selectMungerCard(symbol, name);
          suggestList.classList.add('hidden');
        }
      });
    });

  } catch (err) {
    console.error('Search stock error:', err);
  }
}

async function fetchAndRenderBacktest() {
  const symbol = document.getElementById('selectedSymbol').value || '600519';
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;
  const capital = parseFloat(document.getElementById('capitalInput').value) || 200000;

  document.getElementById('runBtn').disabled = true;

  try {
    const response = await fetch('/api/run_backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol,
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
        ...selectedBacktestOptions()
      })
    });

    const data = await response.json();
    if (data.error) {
      alert(data.error);
      return;
    }

    currentBacktestData = data;

    updateMetrics(data.metrics);
    document.getElementById('chartTitle').innerText = `${data.symbol} - ${data.name} (K线与策略成交记录)`;
    renderKlineChart(data);
    renderTradeTable(data.trades);

    if (data.trades && data.trades.length > 0) {
      renderDecisionDrawer(data.trades[0], 'BUY');
    }

  } catch (err) {
    console.error('Fetch error:', err);
  } finally {
    document.getElementById('runBtn').disabled = false;
  }
}

function updateMetrics(m) {
  const retElem = document.getElementById('metricReturn');
  retElem.innerText = (m.total_return_pct >= 0 ? '+' : '') + m.total_return_pct + '%';
  retElem.className = 'metric-value ' + (m.total_return_pct >= 0 ? 'green' : 'red');

  const pnlPrefix = m.net_pnl_total >= 0 ? '+¥' : '-¥';
  document.getElementById('metricNetPnLSub').innerText = `本金: ¥${(m.initial_capital || 30000).toLocaleString()} ➔ 净盈亏: ${pnlPrefix}${Math.abs(m.net_pnl_total || 0).toLocaleString()}`;

  const annElem = document.getElementById('metricAnnualized');
  const annVal = m.annualized_return_pct || 0;
  annElem.innerText = (annVal >= 0 ? '+' : '') + annVal + '%';
  annElem.className = 'metric-value ' + (annVal >= 0 ? 'green' : 'red');

  document.getElementById('metricWinRate').innerText = m.win_rate_pct + '%';
  const lossCount = m.loss_trades_count !== undefined ? m.loss_trades_count : (m.total_trades - m.win_trades_count);
  document.getElementById('metricTradesCount').innerText = `交易: ${m.total_trades} 笔 (${m.win_trades_count} 胜 / ${lossCount} 负)`;

  document.getElementById('metricPLRatio').innerText = `${m.profit_loss_ratio || '1.00'} : 1`;
  document.getElementById('metricHoldingDays').innerText = `${m.avg_holding_days || '0.0'} 天`;
  document.getElementById('metricMaxDD').innerText = m.max_drawdown_pct + '%';

  if (m.friction_summary) {
    document.getElementById('metricFriction').innerText = '¥' + m.friction_summary.total_friction_cny.toLocaleString('zh-CN', { minimumFractionDigits: 2 });
    document.getElementById('metricFrictionSub').innerText = `印花税:¥${m.friction_summary.total_stamp_duty_cny} | 佣金:¥${m.friction_summary.total_commission_cny} | 滑点:¥${m.friction_summary.total_slippage_cny}`;
  }
}

function renderKlineChart(data) {
  const dates = data.category_dates;
  const kdata = data.kline_chart_data;

  const ohlc = kdata.map(item => [item[0], item[1], item[2], item[3]]);
  const volumes = kdata.map((item, idx) => [idx, item[4], item[1] >= item[0] ? 1 : -1]);

  const ma5 = calculateMA(5, ohlc);
  const ma20 = calculateMA(20, ohlc);

  const markPoints = [];
  data.trades.forEach(t => {
    const buyIdx = dates.indexOf(t.buy_date);
    if (buyIdx !== -1) {
      markPoints.push({
        name: '买入信号',
        type: 'BUY',
        tradeRecord: t,
        coord: [t.buy_date, t.buy_price],
        value: '买入',
        symbol: 'path://M12 2L22 22H2L12 2Z',
        symbolSize: 20,
        itemStyle: { color: '#2ea043' },
        label: { show: true, position: 'top', formatter: `🟢 买入\n¥${t.buy_price}`, color: '#2ea043', fontWeight: 'bold', fontSize: 10 }
      });
    }

    const sellIdx = dates.indexOf(t.sell_date);
    if (sellIdx !== -1) {
      markPoints.push({
        name: '卖出信号',
        type: 'SELL',
        tradeRecord: t,
        coord: [t.sell_date, t.sell_price],
        value: '卖出',
        symbol: 'path://M12 22L2 2H22L12 22Z',
        symbolSize: 20,
        itemStyle: { color: '#f85149' },
        label: { show: true, position: 'bottom', formatter: `🔴 卖出\n¥${t.sell_price}\n(${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%)`, color: '#f85149', fontWeight: 'bold', fontSize: 10 }
      });
    }
  });

  const option = {
    backgroundColor: '#161b22',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(22, 27, 34, 0.95)',
      borderColor: '#30363d',
      textStyle: { color: '#f0f6fc' }
    },
    grid: [
      { left: '50px', right: '20px', top: '35px', height: '60%' },
      { left: '50px', right: '20px', top: '75%', height: '18%' }
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { show: false } }
    ],
    yAxis: [
      { scale: true, splitLine: { lineStyle: { color: '#21262d' } }, axisLabel: { color: '#8b949e' } },
      { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '95%', height: '15px' }
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: ohlc,
        itemStyle: { color: '#f85149', color0: '#2ea043', borderColor: '#f85149', borderColor0: '#2ea043' },
        markPoint: { data: markPoints }
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, lineStyle: { width: 1, color: '#58a6ff' } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { width: 1, color: '#d29922' } },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes.map(v => ({ value: v[1], itemStyle: { color: v[2] === 1 ? '#f85149' : '#2ea043' } }))
      }
    ]
  };

  chartInstance.setOption(option, true);
}

function calculateMA(dayCount, data) {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < dayCount - 1) {
      result.push('-');
      continue;
    }
    let sum = 0;
    for (let j = 0; j < dayCount; j++) {
      sum += data[i - j][1];
    }
    result.push(+(sum / dayCount).toFixed(2));
  }
  return result;
}

function renderDecisionDrawer(t, actionType) {
  const isBuy = actionType === 'BUY';
  document.getElementById('aiStatusBadge').innerText = isBuy ? `🟢 买入信号 - ${t.buy_date}` : `🔴 卖出信号 - ${t.sell_date}`;

  const html = `
    <div class="ai-card">
      <div class="card-header-row">
        <span class="trade-type-badge ${isBuy ? 'BUY' : 'SELL'}">${isBuy ? '🟢 建仓买入' : '🔴 策略卖出/止盈止损'}</span>
        <span class="price-text">成交价: ¥${isBuy ? t.buy_price : t.sell_price}</span>
      </div>

      <div class="dim-section">
        <div class="dim-title">执行策略</div>
        <div class="dim-content">
          <strong>${currentBacktestData?.backtest_metadata?.strategy_name || 'unknown'}</strong>
          | AI 参与: <strong>${currentBacktestData?.backtest_metadata?.ai_used === true ? '是' : '否'}</strong>
        </div>
      </div>

      <div class="dim-section">
        <div class="dim-title">信号值</div>
        <div class="dim-content">
          <strong>${t.ml_score_pct}</strong>
        </div>
      </div>

      <div class="dim-section">
        <div class="dim-title">历史数据边界</div>
        <div class="dim-content">
          ${t.financial_status || 'UNKNOWN'}
        </div>
      </div>

      <div class="dim-section">
        <div class="dim-title">决策理由</div>
        <div class="dim-content">
          ${isBuy ? (t.deepseek_reason || '策略信号触发') : t.sell_reason}
        </div>
      </div>

      ${!isBuy ? `
      <div class="dim-section" style="border-color: #2ea043;">
        <div class="dim-title" style="color: #2ea043;">💰 本单交易总结 (已扣税费/滑点)</div>
        <div class="dim-content">
          买入: ${t.buy_date} (¥${t.buy_price}) ➔ 卖出: ${t.sell_date} (¥${t.sell_price})<br>
          净收益率: <span class="${t.pnl_pct >= 0 ? 'pnl-pos' : 'pnl-neg'}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%</span> (净利: ¥${t.pnl_amount})<br>
          <small style="color: #8b949e">${t.fees_detail || ''}</small>
        </div>
      </div>
      ` : ''}
    </div>
  `;

  document.getElementById('aiDrawerContent').innerHTML = html;
}

function renderTradeTable(trades) {
  const tbody = document.getElementById('tradeTableBody');
  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" class="text-center">回测区间内未产生买卖交易信号。</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => `
    <tr onclick="onTableRowClick(${t.id})">
      <td>${t.id}</td>
      <td>${t.symbol}</td>
      <td>${t.name}</td>
      <td>${t.buy_date}</td>
      <td>¥${t.buy_price}</td>
      <td>${t.sell_date}</td>
      <td>¥${t.sell_price}</td>
      <td>${t.shares} 股</td>
      <td class="${t.pnl_pct >= 0 ? 'pnl-pos' : 'pnl-neg'}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%</td>
      <td class="${t.pnl_amount >= 0 ? 'pnl-pos' : 'pnl-neg'}">¥${t.pnl_amount}</td>
      <td>${t.ml_score_pct}</td>
      <td><button class="btn-detail" onclick="event.stopPropagation(); onTableRowClick(${t.id})">查看理由 🔍</button></td>
    </tr>
  `).join('');
}

function onTableRowClick(tradeId) {
  if (!currentBacktestData || !currentBacktestData.trades) return;
  const trade = currentBacktestData.trades.find(t => t.id === tradeId);
  if (trade) {
    renderDecisionDrawer(trade, 'BUY');
    chartInstance.dispatchAction({ type: 'showTip', seriesIndex: 0, name: trade.buy_date });
  }
}
