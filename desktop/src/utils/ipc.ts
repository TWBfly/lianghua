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

    const STRATEGY_NAME_MAP: Record<string, string> = {
      adaptive_regime_evolution: '🌌 【开阳·三阶演化】状态识别 × 延续预测 × 自适应路由',
      rc_lsr: '💎 【RC-LSR·流动性冲击】极端位移 × 边际吸收 × 截面广度',
      rc_lsr_strategy: '💎 【RC-LSR·流动性冲击】极端位移 × 边际吸收 × 截面广度',
      tianquan_extreme_phase_reversal: '⚖️ 【天权·极值相变】做市商吸收 × 持仓衰竭 × 动态吊灯',
      tianquan: '⚖️ 【天权·极值相变】做市商吸收 × 持仓衰竭 × 动态吊灯',
      taichong_elastoplastic_tensor: '🔮 【太冲·弹塑性】协方差白化 × 微观谐振 × 相变自适应',
      guiyuan_zscore_reversion: '⚡ 【归元·极值反转】Z-Score 极值偏离 × Connors RSI',
      barbell_guiyuan_supertrend: '⚖️ 【杠铃·双星对冲】归元极值反转 × SuperTrend 趋势追踪',
      fac_comp_001: '👑 【正交复合 1号】动量突破 × 路径效率比 ER × 成交量脉冲 (86.4分)',
      fac_comp_007: '👑 【正交复合 2号】四因子非对称共振投票 (83.7分)',
      fac_comp_002: '👑 【正交复合 3号】因果微观动力学自适应三屏 (84.5分)',
      supertrend: '📈 【经典趋势通道】SuperTrend 自适应 ATR 波动率追踪',
      alphatrend: '📊 【自适应动量】AlphaTrend 动量通道突破',
      bollinger_breakout: '🌊 【布林波动突破】Bollinger Bands 动态带宽爆发',
      squeeze_momentum: '💥 【动量能量挤压】Squeeze Momentum 能量积蓄释放',
      chandelier_exit: '🛑 【动态吊灯追踪】Chandelier Exit 非对称浮动止损',
      causal_ml: '🧠 【因果机器学习】Meta-Labeling 次级障碍概率过滤',
    };

    const stratName = STRATEGY_NAME_MAP[strat] || `⚖️ 【${strat}】因果量化策略`;

    let entryLogic = {
      title: `${stratName}·开仓买入机制`,
      core_formula: 'Causal_Signal > Threshold ∩ Filter_Passed',
      trigger_conditions: [
        '① 因果多特征联合概率达标',
        '② 宏观趋势与波动率过滤器检验通过',
      ],
      execution_mechanics: '严格次柱开盘对价撮合成交 (Next-Open Fill)，扣除真实滑点与规费。',
    };

    let exitLogic = {
      title: `${stratName}·平仓退出风控机制`,
      core_formula: 'Chandelier_Trailing ∪ BreakEven ∪ Hard_Stop',
      trigger_conditions: [
        '① 动态浮动止盈与移动追踪保护',
        '② 严格硬止损截断左尾风险',
      ],
      execution_mechanics: '次柱开盘对价市价单成交，全额释放保证金。',
    };

    let optimizationSuggestions = [
      {
        dimension: '趋势状态门禁',
        title: '增加更高一级时间框架趋势过滤门禁',
        suggestion: '小周期信号必须顺应 4H 或日线级别主趋势方向，减少逆势回撤。',
        expected_impact: '整体胜率提升 5%-8%，有效控制资金曲线最大回撤。',
      },
      {
        dimension: '非对称追踪出场',
        title: '采用自适应移动吊灯追踪',
        suggestion: '根据行情波动率分位数动态调节止盈追踪间距，彻底打开右尾利润。',
        expected_impact: '平均单笔盈亏比提升 30% 以上。',
      },
    ];

    let executiveVerdict = {
      overall_rating: '⭐⭐⭐⭐ 优质稳健策略 (Production Ready)',
      summary: `本策略在真实实盘分时与算法全域宏观沙盒的双轨对冲测试中表现出良好自洽性。因果闭环严谨，右偏盈亏分布清晰，无任何未来函数污染。`,
      core_strengths: [
        '因果结构扎实，零未来函数，次柱开盘成交完全贴合实盘。',
        '风险收益比优良，包含动态风控与刚性止损截断。',
      ],
      potential_risks: [
        '在特定极端单边行情或低流动性时段可能面临滑点磨损。',
      ],
      suitable_market_regime: '主流大宗商品期货活跃合约',
      deployment_recommendation: '推荐实盘灰度测试部署，配合资产白名单与趋势状态门禁。',
    };

    if (strat === 'adaptive_regime_evolution') {
      entryLogic = {
        title: '开阳·自适应三阶演化策略开仓机制',
        core_formula: 'State ∈ {UP, DOWN} ∩ DynamicMomentum(DS, KalmanVel) ∩ {Kickoff ∪ Resume ∪ Breakout} ∩ Macro_SS48',
        trigger_conditions: [
          '① 第一步当前状态识别: 12 周期 Ehlers 2-Pole 零滞后滤波器 + 20 周期 Kaufman DER + 归一化均线斜率，经迟滞状态机锁定动力学多空',
          '② 第二步统计物理与动量门禁: 因果方差比 Hurst 指数 + 3 阶符号排列熵 (PE) + 运动学卡尔曼速度，强单边动量冲击可自适应放行',
          '③ 第三步自适应路由器: 顺 48 周期 SuperSmoother 宏观中枢，提供趋势反转初生破位、记忆回踩恢复与动量突破三重顺势通道，配合微观箱体极值真突破校验',
          '④ 转换与噪声态休眠: 在反持续高熵混沌或微宏观冲突且无强动量冲击时，强制空仓观望，规避高频洗盘磨损',
        ],
        execution_mechanics: '次柱开盘对价市价单严格撮合 (Next-Open Fill)，扣除 1 Tick 真实滑点与双边及平今手续费。',
      };
      exitLogic = {
        title: '开阳·动态保本与 Chandelier 移动吊灯非对称追踪出场',
        core_formula: 'Chandelier_Trailing(Highest - 2.8*ATR if Float >= 2.2*ATR) ∪ BreakEven(Entry + Friction if Float >= 1.85*ATR) ∪ Regime_Reversal',
        trigger_conditions: [
          '① 动态移动吊灯追踪: 持仓浮盈达到 2.2 * ATR 时激活，以持仓极值减 2.8 * ATR 动态推移，绝不使用固定点位止盈截断右尾暴利',
          '② 动态净保本锁定: 持仓浮盈达到 1.85 * ATR 时，止损自动抬升至建仓成本上方并覆盖双边手续费、滑点与最小跳位缓冲，杜绝利润回撤为亏损',
          '③ 状态对冲翻转退出: 当状态机彻底翻转为反向单边趋势且持仓满 2 根 Bar，或持仓满 48 根且趋势度衰竭时立即平仓离场',
        ],
        execution_mechanics: '次柱开盘对价平仓，全额释放保证金与风险预算。',
      };
      optimizationSuggestions = [
        {
          dimension: '微观摩擦与资产分层',
          title: '执行资产摩擦比率定律 (Friction / ATR)',
          suggestion: '主力配置沪银(AG)、沪金(AU)、沪锡(SN)等摩擦低于 10% ATR 的高 Alpha 合约；螺纹(RB)、热卷(HC)等高摩擦品种下调风险预算或迁移至 30m/1h 周期。',
          expected_impact: '消灭高摩擦损耗，大幅提振组合夏普比率与卡尔玛比率。',
        },
        {
          dimension: '滚动分位数自适应',
          title: '动态 500 根 Bar 滚动分位数门禁',
          suggestion: '根据资产波动率特征动态自适应调整门槛，消除跨品种硬编码缺陷。',
          expected_impact: '各品种交易频次与胜率显著均衡，全面通过大数定律检验。',
        },
      ];
    }

    if (strat === 'rc_lsr' || strat === 'rc_lsr_strategy') {
      entryLogic = {
        title: 'RC-LSR·流动性冲击反转与微观吸收开仓机制',
        core_formula: 'DownExc >= 2.5*ATR ∩ RVOL ∈ [1.3, 3.2] ∩ ER <= 0.28 ∩ ADX <= 28.0 ∩ (FailedBreak || Close > Open)',
        trigger_conditions: [
          '① 极端位移下潜 (DownExcursion >= 2.5 ATR)：多头流动性踩踏枯竭，价格深度超卖',
          '② 边际成交量温和放大 (RVOL ∈ [1.3, 3.2])：多头爆仓盘释放，做市商被动建仓承接',
          '③ 考夫曼路径效率衰竭 (ER <= 0.28)：单边暴跌势能衰退，价格在极值区调头',
          '④ 趋势状态硬门禁 (ADX <= 28.0 且 120 均线倾角安全)：物理级关停单边暴走状态，杜绝接飞刀',
          '⑤ 微观吸收确认 (Pin Bar 下影线防守 || 假跌破反抽收复)：底部分形反转确立',
        ],
        execution_mechanics: '次柱开盘对价市价单严格撮合 (Next-Open Fill)，扣除 1 Tick 真实不利滑点与双边规费。',
      };
      exitLogic = {
        title: 'RC-LSR·动态保本与移动吊灯追踪平仓机制',
        core_formula: 'Exit if Low <= Trail (Highest - 1.2*ATR if Gain >= 1.4*ATR, else BreakEven if Gain >= 0.75*ATR, else BuyPrice - 0.85*ATR) ∪ Bars >= 24',
        trigger_conditions: [
          '① 动态保本锁定 (Break-even)：持仓浮盈达 0.75 ATR 时，止损线自动提拉至建仓成本之上 (+0.10 ATR)，锁定无风险头寸',
          '② 移动吊灯追踪止盈 (Chandelier Trailing)：浮盈达 1.40 ATR 时激活，平仓线动态跟随最高价下移 1.20 ATR，彻底打开右尾利润',
          '③ 极值硬止损截断：下破入场价 -0.85 ATR 严格执行次柱开盘市价对价平仓，坚决阻断左尾跳空风险',
          '④ 半衰期时间硬清仓：持仓超过 24 根 Bar (12小时) 超时离场，释放资金时间成本',
        ],
        execution_mechanics: '次柱开盘对价平仓释放保证金，杜绝任何学术挂单排队假设，让右尾大波段利润自由奔跑。',
      };
      optimizationSuggestions = [
        {
          dimension: '品种与摩擦白名单',
          title: '坚决执行资产白名单准入机制 (已实装)',
          suggestion: '在沪金(AU)、沪锌(ZN)、白糖(SR)、焦煤(JM)等深厚做市商且低摩擦资产上部署，严禁在原油(SC)、沪铜(CU)等高点差强单边品种上逆势摸底。',
          expected_impact: '直接剔除 90% 以上的单边黑天鹅亏损，组合净利润由负转正。',
        },
        {
          dimension: '趋势状态门禁',
          title: 'ADX > 28 强单边暴走物理锁定 (已实装)',
          suggestion: '当 ADX 处于高位强单边趋势中，强制休眠反转开仓状态机，避免逆大势接飞刀。',
          expected_impact: '胜率提升至 50% 以上，最大回撤压降 60%。',
        },
        {
          dimension: '右尾盈亏比重构',
          title: '废除静态止盈，采用非对称移动吊灯追踪 (已实装)',
          suggestion: '彻底拆除 1.35 ATR 固定硬天花板，允许反转主升浪奔跑至 2.5~4.0 ATR，大幅拉升平均盈亏比。',
          expected_impact: '盈亏比从 0.69 飙升至 1.45~1.93:1，期望值全面转正。',
        },
      ];
      executiveVerdict = {
        overall_rating: '⭐⭐⭐⭐ 优质稳健策略 (Production Ready)',
        summary: '本策略在真实实盘分时与算法全域宏观沙盒的双轨对冲测试中表现出高度自洽性。基于微观流动性踩踏吸收与非对称移动吊灯出场，逻辑因果闭环严谨，右偏盈亏分布清晰，无任何未来函数污染。',
        core_strengths: [
          '因果机制扎实：基于微观订单流踩踏耗尽与做市商流动性承接的第一性原理。',
          '非对称右尾重构：移动吊灯追踪彻底解放反转后的大波段利润，盈亏比达到 1.45~1.93:1。',
          '严格因果撮合：次柱开盘对价撮合，扣除全额滑点规费，实盘 100% 可完美复现。',
        ],
        potential_risks: [
          '严禁全品种盲目无脑普适，在原油、沪铜等高摩擦强单边品种上必须保持物理休眠。',
          '极端突发地缘跳空（隔夜跳空缺口）可能穿透动态保本线。',
        ],
        suitable_market_regime: '低单边趋势度 (ADX <= 28)、高流动性深厚做市商资产 (沪金/沪锌/白糖/焦煤) 的宽幅震荡与阶段性洗盘区间',
        deployment_recommendation: '白名单品种强烈推荐实盘准入！严格配合趋势状态门禁与动态吊灯出场，作为全天候 CTA 矩阵中卓越的均值回归流动性供给核心策略。',
      };
    } else if (strat === 'taichong_elastoplastic_tensor') {
      entryLogic = {
        title: '太冲·弹塑性张量势能爆发开仓机制',
        core_formula: 'Strain = (Close - Close_{t-10})/ATR_10 > 0.85 ∩ Vol > Vol_SMA_20 * 1.1',
        trigger_conditions: [
          '① 微观应变位能 Strain > 0.85：价格累积变形能突破弹性极限，进入塑性流动区',
          '② 能量脉冲：成交量放大至均量 1.1 倍以上，微观订单流共振确认',
        ],
        execution_mechanics: '次柱开盘开多，捕获连续介质力学势能跃迁阶段。',
      };
      exitLogic = {
        title: '太冲·塑性屈服耗散与极限止损退出机制',
        core_formula: 'Exit if Yield_Ratio > 1.8 ∪ Gain >= +4.5% ∪ Loss <= -2.0%',
        trigger_conditions: [
          '① 屈服耗散率 > 1.8：塑性变形能量释放完毕，到达动力学衰竭中枢',
          '② 动态共振止盈 +4.5%，形变失效硬止损 -2.0%',
        ],
        execution_mechanics: '力学能量耗散闭环控制。',
      };
      optimizationSuggestions = [
        {
          dimension: '高阶张量导数',
          title: '引入应变率高阶导数 d(Strain)/dt 预测势能奇点',
          suggestion: '在应变位能加速放大的拐点即刻进场，降低入场滑点成本。',
          expected_impact: '平均建仓点位优化 0.35%，单笔盈亏比显著增加。',
        },
        {
          dimension: '持仓量验证',
          title: '结合主力合约持仓量 (Open Interest) 资金沉淀验证',
          suggestion: '要求形变发生时持仓量同步增加（增仓上行），确保是真金白银推进。',
          expected_impact: '大幅提升有色金属和新能源板块的实盘有效性。',
        },
      ];
      executiveVerdict = {
        overall_rating: '⭐⭐⭐⭐⭐ 卓越母策略 (Institutional Tier-1)',
        summary: '以连续介质力学应力应变理论揭示主力资金建仓与拉升势能，在形变位能释放瞬间介入，资金占用性价比极佳。',
        core_strengths: [
          '物理力学穿透力强，揭示微观形变本质。',
          '爆发段收益丰厚，双轨检验一致性评分高达 92+ 分。',
        ],
        potential_risks: [
          '对微观分时量能跳变要求较高，需要高质量行情源。',
        ],
        suitable_market_regime: '有色金属 (沪铜/沪锡)、新能源等高弹性高矛盾品种',
        deployment_recommendation: '具备实盘顶级部署资质，建议作为主力进攻战队的核心配置。',
      };
    }

    return {
      strategy_id: strat,
      strategy_name: stratName,
      symbol: sym,
      symbol_name: sym === 'AU_IDX' ? '沪金主力' : (sym === 'AG_IDX' ? '沪银主力' : (sym === 'RB_IDX' ? '螺纹主力' : '期货主力')),
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
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      optimization_suggestions: optimizationSuggestions,
      executive_verdict: executiveVerdict,
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

  if (cmd === 'get_factor_zoo_command' || cmd === 'run_autonomous_factor_research_command') {
    return [
      {
        factor_id: 'FAC_COMP_001',
        name: '正交量价趋势信噪比共振 (Orthogonal Trend-SNR-Volume)',
        family: '正交复合 Alpha (Orthogonal)',
        hypothesis: '将动量突破、Kaufman 效率比 (ER) 与成交量脉冲三者进行几何正交乘积，低效率震荡市自动静默归零，高纯度放量单边趋势强力爆发，全面击败单一指标。',
        formula_dsl: 'BreakoutStrength[20] * EfficiencyRatio[20] * Log(Volume / SMA(Vol,20) + 1.0)',
        total_score: 86.4,
        grade: 'A',
        rank_ic: -0.0181,
        icir: -1.15,
        win_rate: 54.2,
        sharpe: 1.85,
        profit_factor: 1.85,
        max_dd: 3.2,
        breakeven_cost_mult: 3.4,
        cross_market_pass_rate: 66.7,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.82, "pnl": 42500.0}}',
        status: 'EXCELLENT',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_COMP_002',
        name: '因果微观动力学自适应三屏 (Causal Micro-Dynamics Triple Barrier)',
        family: '因果复合系统 (Causal ML)',
        hypothesis: '结合路径信噪比 (SNR)、EMA 偏离度与微观能量释放，严格结合动态波动率三屏止盈 (+2.2 ATR) 与时间衰竭屏障，收益率对 3x 摩擦具备极强免疫力。',
        formula_dsl: 'Sign(Close - SMA[20]) * (Path_SNR[12] >= 0.28) * (Volume / SMA(Vol, 20) >= 1.05)',
        total_score: 84.5,
        grade: 'A',
        rank_ic: -0.0108,
        icir: -0.69,
        win_rate: 52.8,
        sharpe: 1.72,
        profit_factor: 1.85,
        max_dd: 3.5,
        breakeven_cost_mult: 3.4,
        cross_market_pass_rate: 66.7,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.75, "pnl": 38900.0}}',
        status: 'EXCELLENT',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_COMP_003',
        name: '双轨动量吊灯自适应追踪 (SuperTrend-Chandelier Hybrid)',
        family: '趋势追踪体系 (Trend Following)',
        hypothesis: '基于自适应真实波幅通道进行多头趋势锁定，配合动态吊灯追踪止损截断左尾极端下挫，跨越黑色、有色、能化大宗商品展现出极其坚固的跨市场普适性。',
        formula_dsl: 'TrendDirection * (1.0 - (Highest[22] - Close) / (3.0 * ATR[22] + 1e-6))',
        total_score: 81.2,
        grade: 'A',
        rank_ic: -0.011,
        icir: -0.7,
        win_rate: 51.5,
        sharpe: 1.61,
        profit_factor: 1.85,
        max_dd: 3.8,
        breakeven_cost_mult: 3.4,
        cross_market_pass_rate: 50.0,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.62, "pnl": 31200.0}}',
        status: 'EXCELLENT',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_BRK_001',
        name: 'ATR 波动率通道突破 (Volatility Channel Breakout)',
        family: '通道突破 (Breakout)',
        hypothesis: '价格打破过去 20 周期阻力位并穿越 ATR 动态阈值，表明边际信息差驱动资产价格重构，多头突破具备正向持续溢出效应。',
        formula_dsl: 'BreakoutStrength = (Close[t] - MaxHigh[t-20:t-1]) / ATR[20]',
        total_score: 74.9,
        grade: 'B',
        rank_ic: -0.0202,
        icir: -1.28,
        win_rate: 49.3,
        sharpe: 1.35,
        profit_factor: 1.15,
        max_dd: 6.5,
        breakeven_cost_mult: 2.8,
        cross_market_pass_rate: 66.7,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.4, "pnl": 21000.0}}',
        status: 'CANDIDATE',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_MOM_001',
        name: '波动率归一化动量 (Normalized Momentum)',
        family: '动量家族 (Momentum)',
        hypothesis: '机构资金在宏观趋势确立后存在分批建仓与止损追涨行为，中周期位移相对真实波幅显著超越随机游走，形成趋势惯性溢价。',
        formula_dsl: 'Momentum_20 = (Close[t] - Close[t-20]) / ATR[20]',
        total_score: 71.7,
        grade: 'B',
        rank_ic: -0.0076,
        icir: -0.48,
        win_rate: 48.6,
        sharpe: 1.28,
        profit_factor: 1.15,
        max_dd: 7.2,
        breakeven_cost_mult: 2.8,
        cross_market_pass_rate: 66.7,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.3, "pnl": 19500.0}}',
        status: 'CANDIDATE',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_TQ_001',
        name: '考夫曼趋势效率比 (Kaufman Efficiency Ratio)',
        family: '趋势质量 (Trend Quality)',
        hypothesis: '真正具备 Alpha 的趋势价格路径具有极高几何纯度与信噪比，过滤白噪声频繁锯齿，在价格净位移效率 ER >= 0.35 时介入可大幅提高盈亏比。',
        formula_dsl: 'EfficiencyRatio = (|Close[t] - Close[t-20]| / Sum(|Diff(Close, 1)|, 20)) * Sign(Close[t] - Close[t-20])',
        total_score: 71.2,
        grade: 'B',
        rank_ic: -0.0055,
        icir: -0.35,
        win_rate: 47.9,
        sharpe: 1.25,
        profit_factor: 1.15,
        max_dd: 7.5,
        breakeven_cost_mult: 2.8,
        cross_market_pass_rate: 66.7,
        tested_symbols: '{"AU_IDX": {"sharpe": 1.28, "pnl": 18200.0}}',
        status: 'CANDIDATE',
        fail_reason: null,
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_MR_001',
        name: '残差 Z-Score 极值均值反转 (ZScore Reversion)',
        family: '均值回归 (Mean Reversion)',
        hypothesis: '短周期价格因恐慌踩踏或过度杠杆造成短线流动性错杀，远离 20 周期均线达 2.2 个标准差后，短期边际均值回归概率高达 70% 以上。',
        formula_dsl: 'ZScore = -(Close[t] - SMA[20]) / Std[20]',
        total_score: 59.5,
        grade: 'C',
        rank_ic: 0.0198,
        icir: 1.25,
        win_rate: 44.1,
        sharpe: 0.85,
        profit_factor: 1.15,
        max_dd: 9.8,
        breakeven_cost_mult: 1.2,
        cross_market_pass_rate: 50.0,
        tested_symbols: '{"AU_IDX": {"sharpe": 0.88, "pnl": 6500.0}}',
        status: 'GRAVEYARD',
        fail_reason: '3x 极端滑点规费压力测试下净利润归零崩塌',
        created_at: '2026-09-03 18:00:00',
      },
      {
        factor_id: 'FAC_OVERFIT_001',
        name: '多重过拟合复杂套娃因子 (Overfitting Complex Toy)',
        family: '淘汰测试 (Graveyard Demo)',
        hypothesis: '无经济学逻辑的高维参数拟合，在样本内呈现虚高收益，但在 3x 成本压力测试与跨品种泛化测试中必然崩塌，用作负样本墓地对照组。',
        formula_dsl: 'Rank(EMA(RSI(14), 5)) * Sin(Close * 100) / (Std[10] + 1e-6)',
        total_score: 29.8,
        grade: 'D',
        rank_ic: -0.006,
        icir: -0.38,
        win_rate: 38.2,
        sharpe: -0.42,
        profit_factor: 0.75,
        max_dd: 18.5,
        breakeven_cost_mult: 0.4,
        cross_market_pass_rate: 16.7,
        tested_symbols: '{"AU_IDX": {"sharpe": -0.4, "pnl": -32000.0}}',
        status: 'GRAVEYARD',
        fail_reason: '人工过拟合套娃结构，缺乏微观经济学逻辑 | 3x 极端滑点规费压力测试下净利润归零崩塌 | 跨市场多品种泛化失败',
        created_at: '2026-09-03 18:00:00',
      },
    ] as unknown as T;
  }

  if (cmd === 'start_continuous_research_command') {
    (window as any).__mockContinuousRunning = true;
    (window as any).__mockContinuousStartTime = Math.floor(Date.now() / 1000);
    return {
      is_running: true,
      pid: 12345,
      start_time: (window as any).__mockContinuousStartTime,
      duration_seconds: 3600,
      elapsed_seconds: 0,
      remaining_seconds: 3600,
      total_evaluated_this_run: 1,
      total_in_zoo: 1681,
      latest_factor_id: 'FAC_COMP_007',
      latest_factor_name: '自适应四因子非对称共振投票引擎',
      latest_factor_score: 83.7,
      latest_factor_status: 'EXCELLENT',
      updated_at: new Date().toISOString(),
    } as unknown as T;
  }

  if (cmd === 'stop_continuous_research_command') {
    (window as any).__mockContinuousRunning = false;
    return true as unknown as T;
  }

  if (cmd === 'get_continuous_research_status_command') {
    const isRunning = !!(window as any).__mockContinuousRunning;
    const startTime = (window as any).__mockContinuousStartTime || Math.floor(Date.now() / 1000);
    const elapsed = isRunning ? Math.floor(Date.now() / 1000) - startTime : 0;
    return {
      is_running: isRunning,
      pid: isRunning ? 12345 : null,
      start_time: isRunning ? startTime : null,
      duration_seconds: 3600,
      elapsed_seconds: elapsed,
      remaining_seconds: isRunning ? Math.max(0, 3600 - elapsed) : 0,
      total_evaluated_this_run: isRunning ? 1 : 0,
      total_in_zoo: 1681,
      latest_factor_id: isRunning ? 'FAC_COMP_007' : null,
      latest_factor_name: isRunning ? '自适应四因子非对称共振投票引擎' : null,
      latest_factor_score: isRunning ? 83.7 : null,
      latest_factor_status: isRunning ? 'EXCELLENT' : null,
      updated_at: new Date().toISOString(),
    } as unknown as T;
  }

  return [] as unknown as T;
}
