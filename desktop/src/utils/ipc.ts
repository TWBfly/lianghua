import { invoke } from '@tauri-apps/api/core';

// 检查是否运行在 Tauri 桌面端环境中
export const isTauri = () => {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
};

// 安全调用 Tauri Command，在纯浏览器开发时自动 Fallback 到 Mock 数据
export async function safeInvoke<T>(cmd: string, args?: Record<string, any>): Promise<T> {
  if (isTauri()) {
    return invoke<T>(cmd, args);
  }

  // === 纯浏览器开发 Mock 数据 (无需 Rust 后端即可极速调试 UI) ===
  console.log(`[Browser Mock IPC] ${cmd}`, args);

  if (cmd === 'get_strategy_registry') {
    return [
      {
        id: 'tianji_dual_island_v2',
        name: '👑 【天极·双岛正交自适应策略 V2.0】 第一梯队 (4H宏观趋势 + 30m产业均值)',
        short_name: '👑 天极·双岛正交 V2.0 (8大主力)',
        timeframe: '30m',
        symbols: ['AU_IDX', 'AG_IDX', 'LC_IDX', 'SN_IDX', 'P_IDX', 'TA_IDX', 'SC_IDX', 'MA_IDX'],
        default_symbol: 'AU_IDX',
        initial_capital: 1000000.0,
        summary_win_rate: 56.9,
        execution_status: 'AVAILABLE',
      },
      {
        id: 'taichong_dual_squad',
        name: '🔮 【太冲·弹塑性张量】双战队 (10m微观弹性 + 30m波段中枢回归)',
        short_name: '⚡ 太冲·双战队全景 (10m+30m 11主力)',
        timeframe: '10m',
        symbols: ['SN_IDX', 'AU_IDX', 'AG_IDX', 'MA_IDX', 'P_IDX', 'SC_IDX', 'LC_IDX', 'J_IDX', 'AL_IDX', 'TA_IDX', 'SI_IDX'],
        default_symbol: 'SN_IDX',
        initial_capital: 2000000.0,
        summary_win_rate: 78.6,
        execution_status: 'LIVE_ACTIVE',
      },
      {
        id: 'guiyuan_zscore_15m',
        name: '⚡ 【极值均值反转】15m 归元·极值策略 + ML Meta-Labeling',
        short_name: '⚡ 归元·15m极值策略 (8大主力)',
        timeframe: '15m',
        symbols: ['AU_IDX', 'AG_IDX', 'SC_IDX', 'TA_IDX', 'MA_IDX', 'SA_IDX', 'HC_IDX', 'P_IDX'],
        default_symbol: 'AU_IDX',
        initial_capital: 1000000.0,
        summary_win_rate: 76.5,
        execution_status: 'LIVE_ACTIVE',
      },
    ] as unknown as T;
  }

  if (cmd === 'get_system_status') {
    return {
      engine_status: 'TqSim 守护运行中 (Dev)',
      total_equity: 2148320.0,
      active_positions_count: 3,
      total_trades_count: 142,
      total_pnl: 148320.0,
      win_rate: 78.6,
    } as unknown as T;
  }

  if (cmd === 'run_portfolio_backtest_command') {
    const strat = args?.req?.strategy || 'guiyuan_zscore_reversion';
    const tf = args?.req?.timeframe || '15m';
    const isSynth = args?.req?.data_source === 'SYNTHETIC' || !!args?.req?.use_synthetic;

    return {
      strategy: strat,
      strategy_name: strat.includes('guiyuan') ? '⚡ 归元·Z-Score 极值均值反转' : strat.includes('supertrend') ? '📈 SuperTrend 经典趋势追踪' : '🔮 太冲·弹塑性张量 (微观谐振)',
      timeframe: tf,
      timeframe_label: `${tf} (${tf === '15m' ? '15 分钟分时级别' : tf === '1h' ? '1 小时级别' : tf + '分时'})`,
      data_source: isSynth ? 'SYNTHETIC' : 'REAL',
      data_source_label: isSynth ? '算法构建全域深度沙盒 (50,000根/标的)' : '真实实盘历史分时 (8,000根/标的)',
      start_date: isSynth ? '2015-01-05 09:15' : '2024-01-01 09:00',
      end_date: isSynth ? '2020-03-10 14:30' : '2026-08-24 15:00',
      total_trades: isSynth ? 1421 : 477,
      win_trades_count: isSynth ? 972 : 311,
      loss_trades_count: isSynth ? 449 : 166,
      lln_compliant: isSynth,
      total_equity: 2182267.68,
      initial_capital: 2000000.0,
      total_net_pnl: 182267.68,
      total_return_pct: 9.11,
      annualized_return_pct: 4.10,
      sharpe_ratio: 1.85,
      calmar_ratio: 5.06,
      expectancy_cny: 382.11,
      overall_win_rate_pct: 65.2,
      overall_pl_ratio: 1.28,
      overall_max_drawdown_pct: 0.81,
      total_friction_cny: 22546.73,
      stress_test_3x_pnl: 137174.22,
      p_ruin_pct: 0.001,
      symbol_breakdowns: [
        { symbol: 'AU_IDX', name: '沪金主力', sector: '贵金属', trades_count: 55, win_trades_count: 35, loss_trades_count: 20, win_rate_pct: 63.6, net_pnl: 20275.33, return_pct: 9.12, profit_loss_ratio: 1.28, max_drawdown_pct: 0.81, expectancy_cny: 368.6 },
        { symbol: 'AG_IDX', name: '沪银主力', sector: '贵金属', trades_count: 55, win_trades_count: 32, loss_trades_count: 23, win_rate_pct: 58.2, net_pnl: -20158.80, return_pct: -9.07, profit_loss_ratio: 0.80, max_drawdown_pct: 0.79, expectancy_cny: -366.5 },
        { symbol: 'SN_IDX', name: '沪锡主力', sector: '有色金属', trades_count: 53, win_trades_count: 39, loss_trades_count: 14, win_rate_pct: 73.6, net_pnl: 3186.18, return_pct: 1.43, profit_loss_ratio: 1.06, max_drawdown_pct: 0.78, expectancy_cny: 60.1 },
        { symbol: 'CU_IDX', name: '沪铜主力', sector: '有色金属', trades_count: 59, win_trades_count: 38, loss_trades_count: 21, win_rate_pct: 64.4, net_pnl: 16970.64, return_pct: 7.64, profit_loss_ratio: 1.48, max_drawdown_pct: 0.69, expectancy_cny: 287.6 },
        { symbol: 'SC_IDX', name: '原油主力', sector: '能源化工', trades_count: 59, win_trades_count: 31, loss_trades_count: 28, win_rate_pct: 52.5, net_pnl: -25078.32, return_pct: -11.29, profit_loss_ratio: 0.83, max_drawdown_pct: 0.81, expectancy_cny: -425.1 },
        { symbol: 'LC_IDX', name: '碳酸锂主力', sector: '新能源', trades_count: 30, win_trades_count: 19, loss_trades_count: 11, win_rate_pct: 63.3, net_pnl: 149263.42, return_pct: 67.17, profit_loss_ratio: 1.86, max_drawdown_pct: 0.77, expectancy_cny: 4975.4 },
        { symbol: 'MA_IDX', name: '甲醇主力', sector: '能源化工', trades_count: 56, win_trades_count: 37, loss_trades_count: 19, win_rate_pct: 66.1, net_pnl: 12450.00, return_pct: 5.60, profit_loss_ratio: 1.35, max_drawdown_pct: 0.72, expectancy_cny: 222.3 },
        { symbol: 'P_IDX', name: '棕榈油主力', sector: '农产品', trades_count: 54, win_trades_count: 40, loss_trades_count: 14, win_rate_pct: 74.1, net_pnl: 18250.00, return_pct: 8.21, profit_loss_ratio: 1.55, max_drawdown_pct: 0.65, expectancy_cny: 338.0 },
        { symbol: 'TA_IDX', name: 'PTA主力', sector: '纺织化工', trades_count: 56, win_trades_count: 37, loss_trades_count: 19, win_rate_pct: 66.1, net_pnl: 7100.00, return_pct: 3.20, profit_loss_ratio: 1.25, max_drawdown_pct: 0.58, expectancy_cny: 126.8 },
      ],
    } as unknown as T;
  }

  if (cmd === 'run_strategy_dual_track_evaluation_command') {
    const strat = args?.req?.strategy || 'causal_ml';
    const sym = args?.req?.symbol || 'AU_IDX';
    const tf = args?.req?.timeframe || '15m';

    return {
      strategy_id: strat,
      strategy_name: '🧠 Causal ML (因果机器学习 Meta-Labeling)',
      symbol: sym,
      symbol_name: sym === 'AU_IDX' ? '沪金主力' : '贵金属主力',
      timeframe: tf,
      timeframe_label: `${tf} 分时级别`,
      initial_capital: 1000000.0,
      real_benchmark: {
        data_source_type: 'REAL',
        data_source_label: '真实实盘分时K线 (8,136 根)',
        period_label: '2024-01-01 09:00 至 2026-08-24 15:00',
        total_bars: 8136,
        total_trades: 115,
        win_trades_count: 71,
        loss_trades_count: 44,
        win_rate_pct: 61.7,
        profit_loss_ratio: 2.15,
        total_net_pnl: 389080.0,
        total_return_pct: 38.91,
        annualized_return_pct: 17.51,
        max_drawdown_pct: 4.82,
        sharpe_ratio: 1.82,
        calmar_ratio: 3.63,
        expectancy_cny: 3383.3,
        total_friction_cny: 8450.0,
        stress_test_3x_pnl: 372180.0,
      },
      synthetic_benchmark: {
        data_source_type: 'SYNTHETIC',
        data_source_label: '算法构建全周期沙盒 (50,000 根)',
        period_label: '2015-01-05 09:15 至 2020-03-10 14:30',
        total_bars: 50000,
        total_trades: 514,
        win_trades_count: 298,
        loss_trades_count: 216,
        win_rate_pct: 58.0,
        profit_loss_ratio: 1.92,
        total_net_pnl: 845600.0,
        total_return_pct: 84.56,
        annualized_return_pct: 26.85,
        max_drawdown_pct: 5.60,
        sharpe_ratio: 2.15,
        calmar_ratio: 4.79,
        expectancy_cny: 1645.1,
        total_friction_cny: 38500.0,
        stress_test_3x_pnl: 768600.0,
      },
      scorecard: {
        total_score: 92.5,
        grade: 'AA (顶级实盘量化母策略)',
        grade_badge: 'bg-[#3fb950]/20 text-[#3fb950] border-[#3fb950]/40',
        summary_comment: '该策略在大数显著性、非对称收益期望及极端尾部抗压均表现极优，具备高权重实盘准入资质。',
        dimensions: [
          { name: '大数样本显著性 (LLN Scale)', max_score: 15.0, score: 15.0, description: '考核真实样本与全域宏观沙盒总样本规模，确保统计显著性杜绝幸存者偏差。', assessment: '算法沙盒 514 笔 + 真实分时 115 笔，大数定律充分验证。' },
          { name: '期望收益与非对称盈亏比 (Asymmetry)', max_score: 15.0, score: 14.5, description: '计算数学期望方程 E = WR * AvgWin - (1-WR) * AvgLoss，验证收益分布的右偏特征。', assessment: '综合胜率 58.0%，盈亏比 1.92:1，单笔期望 +¥1,645。' },
          { name: '尾部极端动态回撤控制 (Tail Risk)', max_score: 15.0, score: 14.0, description: '衡量跨越单边极端牛熊与黑天鹅震荡期间的最大动态盯市回撤 (M2M Drawdown)。', assessment: '沙盒最大回撤仅 -5.60%，极端下行风险被刚性截断。' },
          { name: '双轨跨机制泛化一致性 (Generalization)', max_score: 15.0, score: 14.5, description: '对比真实实盘历史与算法生成全域宏观沙盒的胜率衰减与盈亏比衰减率。', assessment: '真实 vs 沙盒胜率偏差仅 3.7%，无严重过拟合特征漂移。' },
          { name: '交易摩擦与 3x 极端滑点耐受度 (Friction)', max_score: 10.0, score: 10.0, description: '在真实交易所手续费、印花税基础上施加 3 倍滑点冲击压力测试。', assessment: '在 3x 极端滑点承压下仍保持净盈利 ¥768,600。' },
          { name: '破产概率与资本生存安全性 (P(Ruin))', max_score: 10.0, score: 10.0, description: '10,000 次蒙特卡洛随机路径重抽样模拟下的破产爆仓概率。', assessment: 'P(Ruin) < 0.001%，具备机构级资本本金保全高安全边际。' },
          { name: '信号因果严谨性 (无未来函数)', max_score: 10.0, score: 10.0, description: '强制执行次柱开盘价撮合 (Next-Bar Open Fill)，严禁当前柱收盘价穿透。', assessment: '100% 因果闭环，绝无 Look-ahead 偏差与成交漂移。' },
          { name: '参数平原鲁棒性与容量弹性 (Plateau)', max_score: 10.0, score: 9.5, description: '参数在 +/-20% 扰动区间内的收益曲面平坦度，杜绝孤岛尖峰过拟合。', assessment: '处于宽阔参数邻域平原，资金容量与抗冲击弹性良好。' },
        ],
      },
      entry_logic: {
        title: 'Causal ML 因果机器学习 Meta-Labeling 开仓逻辑',
        core_formula: 'P(Causal) = 0.40*Trend + 0.35*RSI_Regime + 0.25*Vol_Pulse >= 0.75',
        trigger_conditions: [
          '因果多特征联合概率 >= 75%（基于无未来函数的一阶差分元标签体系）',
          '趋势项：收盘价站上 SMA20（权重 0.40）',
          '动量项：RSI 处于 [48, 72] 健康扩张区（权重 0.35）',
          '流动性项：成交量超越均量形成能量脉冲（权重 0.25）',
        ],
        execution_mechanics: '因果置信度达标后次柱开盘进场，有效过滤 60% 以上的市场噪声。',
      },
      exit_logic: {
        title: '因果特征漂移与元标签风控退出逻辑',
        core_formula: 'Exit if P(Causal) < 0.45 ∪ Gain >= +4.6% ∪ Loss <= -2.1%',
        trigger_conditions: [
          '因果置信度跌破 45% 警戒线，判定当前市场微观机制发生漂移，立即离场',
          '正期望目标止盈 +4.6%，元标签风控硬截断 -2.1%',
        ],
        execution_mechanics: '概率图自适应调仓，回撤抑制能力极强。',
      },
      optimization_suggestions: [
        {
          dimension: '在线自适应学习',
          title: '引入 Online Stochastic Gradient 动态校准特征权重',
          suggestion: '每 500 根 K 线根据残差动态更新 Trend、RSI、VolPulse 的因果加权系数，抵抗机制衰减。',
          expected_impact: '在长达 5 年以上的周期跨度中保持 Sharpe > 2.0 不退化。',
        },
        {
          dimension: '隐马尔可夫分簇',
          title: '构建 3 状态 Gaussian HMM（牛市/熊市/混沌震荡）顶层门禁',
          suggestion: '在 HMM 识别为混沌震荡状态时，主动降低头寸比例至 0.2 倍。',
          expected_impact: '最大动态回撤抑制在 3% 以内。',
        },
      ],
      executive_verdict: {
        overall_rating: '⭐⭐⭐⭐⭐ 卓越母策略 (Institutional Tier-1)',
        summary: '本策略在真实实盘分时（8,136根）与算法全域宏观沙盒（50,000根）的双轨对冲测试中表现出高度自洽性。实盘收益率 +38.91%，沙盒收益率 +84.56%，综合得分 92.5/100 分。该策略逻辑因果闭环严谨，右偏盈亏分布清晰，无任何未来函数污染，具备成熟的量化实盘部署能力。',
        core_strengths: [
          '因果结构性强：通过概率图元标签避免了传统机器学习的黑盒过拟合。',
          '自适应机制漂移：能根据行情特征动态调节阈值，抗衰退能力优异。',
          '胜率与盈亏比平衡：兼具 60%+ 的稳健胜率与 1.8+ 的盈亏比。',
        ],
        potential_risks: [
          '在极端瞬时脉冲（秒级闪崩）时因计算平滑窗口可能存在轻微反应时滞。',
        ],
        suitable_market_regime: '结构性轮动市、震荡向趋势过渡期、全天候多资产组合',
        deployment_recommendation: '高度推荐实盘准入。可作为多资产商品期货组合的核心主控 Alpha 驱动源。',
      },
    } as unknown as T;
  }

  if (cmd === 'run_backtest_command') {
    const symbol = args?.req?.symbol || 'AU_IDX';
    const tf = args?.req?.timeframe || '15m';
    const isSynth = args?.req?.data_source === 'SYNTHETIC' || !!args?.req?.use_synthetic;
    const initial_capital = args?.req?.initial_capital || 1000000;
    const now = Math.floor(Date.now() / 1000);
    const bars = [];
    let basePrice = symbol.includes('AU') ? 955.0 : 1680.0;

    const count = isSynth ? 1200 : 250;
    const tradeCount = isSynth ? 1045 : 38;

    for (let i = count; i >= 0; i--) {
      const stepSecs = tf === '1d' ? 86400 : tf === '1h' ? 3600 : tf === '30m' ? 1800 : tf === '10m' ? 600 : 900;
      const time = now - i * stepSecs;
      const change = (Math.random() - 0.47) * (symbol.includes('AU') ? 2.5 : 20);
      const open = basePrice;
      const close = basePrice + change;
      const high = Math.max(open, close) + Math.random() * (symbol.includes('AU') ? 1.5 : 10);
      const low = Math.min(open, close) - Math.random() * (symbol.includes('AU') ? 1.5 : 10);
      const volume = Math.floor(Math.random() * 50000) + 10000;
      basePrice = close;
      bars.push({
        time,
        datetime_str: new Date(time * 1000).toISOString().replace('T', ' ').substring(0, 19),
        open,
        high,
        low,
        close,
        volume,
      });
    }

    const markers = [];
    for (let j = 0; j < 25; j++) {
      const bIndex = bars.length - 1 - (j * 8);
      if (bIndex >= 0 && bIndex < bars.length) {
        const b = bars[bIndex];
        const isEntry = j % 2 === 0;
        markers.push({
          time: b.time,
          position: isEntry ? 'belowBar' : 'aboveBar',
          color: isEntry ? '#3fb950' : '#d29922',
          shape: isEntry ? 'arrowUp' : 'circle',
          text: isEntry ? `🟢 买入 2手 @${b.close.toFixed(1)}` : `🎯 止盈 +4.5%`,
          id: `marker_${b.time}`,
          price: b.close,
          reason: isEntry ? '太冲弹塑性势能触发' : '动量目标止盈',
          action: isEntry ? 'ENTRY' : 'EXIT',
          pnl: isEntry ? undefined : 4500,
        });
      }
    }
    markers.sort((a, b) => a.time - b.time);

    return {
      symbol,
      name: symbol === 'AU_IDX' ? '沪金主力' : symbol === '600519' ? '贵州茅台' : symbol,
      timeframe: tf,
      data_source: isSynth ? 'SYNTHETIC' : 'REAL',
      metrics: {
        initial_capital,
        final_equity: initial_capital * 1.485,
        net_pnl_total: initial_capital * 0.485,
        total_return_pct: 48.5,
        annualized_return_pct: 22.4,
        win_rate_pct: 75.0,
        total_trades: tradeCount,
        win_trades_count: Math.round(tradeCount * 0.72),
        loss_trades_count: Math.round(tradeCount * 0.28),
        profit_loss_ratio: 2.45,
        avg_holding_days: 8.5,
        max_drawdown_pct: 3.8,
        backtest_period: isSynth ? '2015-01-05 至 2020-03-10' : '2024-01-01 至 最新',
        total_friction_cny: 1240.0,
        lln_compliant: tradeCount >= 1000,
        data_source_label: isSynth ? '算法构建全域K线 (50,000 根)' : '真实实盘分时K线 (8,136 根)',
        total_bars_count: count,
      },
      trades: [
        {
          id: 1,
          symbol,
          name: symbol === 'AU_IDX' ? '沪金主力' : '贵州茅台',
          buy_date: '2026-08-10 10:00:00',
          buy_price: 940.0,
          sell_date: '2026-08-12 14:30:00',
          sell_price: 985.0,
          shares: 2,
          pnl_amount: 90000.0,
          pnl_pct: 4.79,
          ml_score_pct: 92.5,
          sell_reason: '🎯 目标动态止盈 (+4.79%)',
          fees_detail: '手续费/滑点: ¥120.00',
        },
      ],
      markers,
      bars,
    } as unknown as T;
  }

  if (cmd === 'fetch_kline_bars') {
    const bars = [];
    let basePrice = 250000;
    const now = Math.floor(Date.now() / 1000);
    for (let i = 200; i >= 0; i--) {
      const time = now - i * 600;
      const change = (Math.random() - 0.48) * 600;
      const open = basePrice;
      const close = basePrice + change;
      const high = Math.max(open, close) + Math.random() * 200;
      const low = Math.min(open, close) - Math.random() * 200;
      const volume = Math.floor(Math.random() * 10000) + 1000;
      basePrice = close;
      bars.push({
        time,
        datetime_str: new Date(time * 1000).toISOString().replace('T', ' ').substring(0, 19),
        open,
        high,
        low,
        close,
        volume,
      });
    }
    return bars as unknown as T;
  }

  if (cmd === 'get_strategy_markers') {
    const now = Math.floor(Date.now() / 1000);
    return [
      {
        time: now - 3600 * 5,
        position: 'belowBar',
        color: '#3fb950',
        shape: 'arrowUp',
        text: '🟢 买多 1手 @251,400',
        id: 'mock_entry_1',
        price: 251400,
        reason: '太冲弹塑性共振信号',
        action: 'ENTRY',
      },
    ] as unknown as T;
  }

  if (cmd === 'get_strategy_trades') {
    return [
      {
        strategy_id: '太冲·双战队全景',
        symbol: 'SN_IDX',
        timeframe: '10m',
        side: 'LONG',
        entry_dt: '2026-08-24 10:30:00',
        entry_p: 251400.0,
        entry_reason: '太冲·盘中弹塑性共振触发 (实盘开仓)',
        exit_dt: '⏳ 持仓监控中',
        exit_p: 250800.0,
        exit_reason: '跟踪止损线: ¥250,800.00',
        lots: 1,
        pnl: 0.0,
        status: '🔥 盘中实盘活跃持仓',
      },
    ] as unknown as T;
  }

  if (cmd === 'search_stocks') {
    return [
      { symbol: '600519', name: '贵州茅台', price: 1680.0, pe_ttm: 28.5, pb: 8.2, total_mv: 2100000000000 },
      { symbol: '300750', name: '宁德时代', price: 195.0, pe_ttm: 22.1, pb: 4.5, total_mv: 850000000000 },
    ] as unknown as T;
  }

  return [] as unknown as T;
}
