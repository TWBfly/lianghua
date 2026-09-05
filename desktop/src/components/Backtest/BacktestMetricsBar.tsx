import React from 'react';
import { BacktestMetrics } from '../../types';
import { ShieldCheck, AlertCircle, Clock, Calendar, Zap, ArrowRight, RotateCcw } from 'lucide-react';

interface BacktestMetricsBarProps {
  metrics: BacktestMetrics | null;
  timeframe?: string;
  symbol?: string;
  strategyId?: string;
  onSwitchStrategy?: (strategyId: string) => void;
  onSwitchSymbol?: (symbol: string) => void;
}

export const BacktestMetricsBar: React.FC<BacktestMetricsBarProps> = ({
  metrics,
  timeframe,
  symbol,
  strategyId,
  onSwitchStrategy,
  onSwitchSymbol,
}) => {
  if (!metrics) return null;

  const isPos = metrics.total_return_pct >= 0;
  const isDistorted = Boolean(
    metrics.is_annual_distorted ||
    (metrics.duration_days !== undefined && metrics.duration_days < 180) ||
    (metrics.total_trades < 500 && metrics.total_trades > 0) ||
    metrics.sample_warning
  );

  // 判断是否为黄金/白银与逆势策略相性不匹配
  const isPreciousSymbol = Boolean(
    symbol && (
      symbol === 'AU_IDX' ||
      symbol === 'AG_IDX' ||
      symbol.startsWith('AU') ||
      symbol.startsWith('AG')
    )
  );
  const isCounterTrend =
    strategyId === 'taichong_elastoplastic_tensor' ||
    strategyId === 'tianquan_extreme_phase_reversal' ||
    strategyId === 'tianquan';

  const isMismatch = Boolean(
    (metrics.sample_warning && (
      metrics.sample_warning.includes('相性') ||
      metrics.sample_warning.includes('不适用') ||
      metrics.sample_warning.includes('不适合') ||
      metrics.sample_warning.includes('沪金') ||
      metrics.sample_warning.includes('厚尾')
    )) || (isPreciousSymbol && isCounterTrend)
  );

  const warningText = metrics.sample_warning || (
    isDistorted
      ? `⚠️ 短样本数据提示：当前样本跨度${metrics.duration_days ? `仅 ${metrics.duration_days} 天` : '不足 180 天'} / 成交仅 ${metrics.total_trades} 笔 (未达 500 笔大数门禁)。系统已自动锁定真实区间收益，防止短期失真。`
      : null
  );

  return (
    <div className="flex flex-col bg-[#0d1117] border-b border-[#30363d] select-none">
      {/* 1. 策略与品种不匹配：通俗大白话诊断卡与一键切换按钮 */}
      {isMismatch && (
        <div className="bg-[#2d1515] border-b border-[#f85149]/40 p-3 flex flex-col gap-2.5 text-xs">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 font-bold text-[#ff7b72] text-sm">
              <AlertCircle className="w-4 h-4 shrink-0 text-[#f85149]" />
              <span>⚠️ 策略与当前品种不匹配：【{symbol?.includes('AU') ? '沪金' : '沪银'}】严禁使用逆势做空摸顶策略！</span>
            </div>
            <div className="text-[11px] text-[#8b949e]">
              当前策略：<span className="text-[#f0f6fc] font-mono font-semibold">【太冲·弹塑性 / 天权】</span>
            </div>
          </div>

          {/* 三列清晰大白话原因分析 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 bg-[#161b22]/90 border border-[#30363d] rounded-lg p-2.5 text-[#c9d1d9]">
            <div className="flex flex-col gap-1">
              <div className="text-[#f85149] font-bold flex items-center gap-1">
                <span>1. 标的特征：单边大牛市</span>
              </div>
              <p className="text-[11px] text-[#8b949e] leading-relaxed">
                沪金/沪银属于宏观长期上涨的单边牛市品种，动量极强，极少深度回调。
              </p>
            </div>

            <div className="flex flex-col gap-1 border-t md:border-t-0 md:border-l border-[#30363d] pt-2 md:pt-0 md:pl-2.5">
              <div className="text-[#d29922] font-bold flex items-center gap-1">
                <span>2. 策略缺陷：逆势猜顶摸空</span>
              </div>
              <p className="text-[11px] text-[#8b949e] leading-relaxed">
                【太冲/天权】是震荡市摸顶策略。在黄金大涨中会频繁开空做空，导致连续止损割肉！
              </p>
            </div>

            <div className="flex flex-col gap-1 border-t md:border-t-0 md:border-l border-[#30363d] pt-2 md:pt-0 md:pl-2.5">
              <div className="text-[#3fb950] font-bold flex items-center gap-1">
                <span>3. 解决方案：顺势突破跟随</span>
              </div>
              <p className="text-[11px] text-[#8b949e] leading-relaxed">
                黄金必须顺水推舟，在创出新高时顺势做多，跟随大趋势吃满主升浪红利。
              </p>
            </div>
          </div>

          {/* 一键直达交互按钮区 */}
          <div className="flex items-center gap-2 flex-wrap pt-0.5">
            <span className="text-[#8b949e] text-xs font-semibold">👉 推荐操作（点击直接切换并自动重跑回测）：</span>

            <button
              onClick={() => onSwitchStrategy?.('supertrend')}
              className="px-3 py-1.5 rounded bg-[#238636] hover:bg-[#2ea043] text-white font-bold text-xs flex items-center gap-1.5 transition shadow cursor-pointer border border-[#3fb950]/50 active:scale-95"
              title="切换至自适应 ATR 顺势趋势追踪策略"
            >
              <Zap className="w-3.5 h-3.5 text-yellow-300" />
              <span>🚀 一键切换至：SuperTrend 顺势突破策略</span>
            </button>

            <button
              onClick={() => onSwitchStrategy?.('barbell_guiyuan_supertrend')}
              className="px-3 py-1.5 rounded bg-[#1f6feb] hover:bg-[#388bfd] text-white font-bold text-xs flex items-center gap-1.5 transition shadow cursor-pointer border border-[#58a6ff]/50 active:scale-95"
              title="切换至杠铃对冲策略（兼顾趋势追踪与极值反转）"
            >
              <ArrowRight className="w-3.5 h-3.5" />
              <span>⚖️ 一键切换至：杠铃·双星对冲 (顺势+反转)</span>
            </button>

            <button
              onClick={() => onSwitchSymbol?.('RB_IDX')}
              className="px-2.5 py-1.5 rounded bg-[#21262d] hover:bg-[#30363d] text-[#e6edf3] font-medium text-xs flex items-center gap-1.5 transition cursor-pointer border border-[#30363d] active:scale-95"
              title="保持当前太冲策略不变，切换到适合震荡策略的螺纹钢主力合约"
            >
              <RotateCcw className="w-3 h-3 text-[#8b949e]" />
              <span>🔄 保持策略，切换标的为：螺纹主力 (高震荡)</span>
            </button>
          </div>
        </div>
      )}

      {/* 2. 普通样本提示 (仅非相性冲突且有警告时展示) */}
      {!isMismatch && warningText && (
        <div className="bg-[#b08800]/15 border-b border-[#d29922]/30 px-3 py-1.5 flex items-center gap-2 text-[#e3b341] text-xs font-medium">
          <AlertCircle className="w-4 h-4 shrink-0 text-[#d29922]" />
          <span className="truncate" title={warningText}>{warningText}</span>
        </div>
      )}

      <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 p-3">
        {/* 1. 累积收益率 */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
          <div className="text-[11px] text-[#8b949e]">累积收益率</div>
          <div className={`text-base font-bold font-mono ${isPos ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
            {isPos ? '+' : ''}{metrics.total_return_pct.toFixed(2)}%
          </div>
          <div className="text-[10px] text-[#8b949e] truncate">
            净利: {metrics.net_pnl_total >= 0 ? '+' : ''}¥{metrics.net_pnl_total.toLocaleString()}
          </div>
        </div>

        {/* 2. 年化收益率 (防伪屏蔽) */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
          <div className="text-[11px] text-[#8b949e] flex items-center justify-between">
            <span>年化收益率</span>
            {isDistorted && (
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#f85149]/20 text-[#f85149] font-sans">
                失真锁定
              </span>
            )}
          </div>
          <div className={`text-base font-bold font-mono ${isDistorted ? 'text-[#d29922]' : metrics.annualized_return_pct >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
            {isDistorted
              ? `${isPos ? '+' : ''}${metrics.total_return_pct.toFixed(2)}%`
              : `${metrics.annualized_return_pct >= 0 ? '+' : ''}${metrics.annualized_return_pct.toFixed(2)}%`}
          </div>
          <div className="text-[10px] text-[#8b949e] truncate">
            {isDistorted ? '⚠️ 真实区间 (严禁外推)' : '复合年化复权 (CAGR)'}
          </div>
        </div>

      {/* 3. 胜率与大数定律标识 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e] flex items-center justify-between">
          <span>策略胜率</span>
          {metrics.lln_compliant || metrics.total_trades >= 1000 ? (
            <span className="text-[9px] px-1 py-0.2 rounded bg-[#3fb950]/20 text-[#3fb950] flex items-center gap-0.5 font-sans">
              <ShieldCheck className="w-2.5 h-2.5" /> 大数达标
            </span>
          ) : (
            <span className="text-[9px] px-1 py-0.2 rounded bg-[#d29922]/20 text-[#d29922] flex items-center gap-0.5 font-sans">
              <AlertCircle className="w-2.5 h-2.5" /> 局部样本
            </span>
          )}
        </div>
        <div className="text-base font-bold font-mono text-[#58a6ff]">
          {metrics.win_rate_pct.toFixed(1)}%
        </div>
        <div className="text-[10px] text-[#8b949e]">
          {metrics.win_trades_count} 胜 / {metrics.loss_trades_count} 负 ({metrics.total_trades}笔)
        </div>
      </div>

      {/* 4. 盈亏比 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e]">盈亏比 (P/L Ratio)</div>
        <div className="text-base font-bold font-mono text-[#d29922]">
          {metrics.profit_loss_ratio.toFixed(2)} : 1
        </div>
        <div className="text-[10px] text-[#8b949e]">均盈 / 均亏比率</div>
      </div>

      {/* 5. 平均持仓周期与分时级别 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e] flex items-center justify-between">
          <span>平均持仓 / 级别</span>
          <span className="text-[9px] px-1 py-0.2 rounded bg-[#21262d] text-[#00ff88] font-mono flex items-center gap-0.5">
            <Clock className="w-2.5 h-2.5" /> {timeframe || '15m'}
          </span>
        </div>
        <div className="text-base font-bold font-mono text-[#bc8cff]">
          {metrics.avg_holding_days >= 1.0
            ? `${metrics.avg_holding_days.toFixed(1)} 天`
            : metrics.avg_holding_days * 24 >= 1.0
            ? `${(metrics.avg_holding_days * 24).toFixed(1)} 小时`
            : `${Math.max(1, Math.round(metrics.avg_holding_days * 1440))} 分钟`}
        </div>
        <div className="text-[10px] text-[#8b949e] truncate">
          {metrics.data_source_label}
        </div>
      </div>

      {/* 6. 最大回撤 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e]">最大回撤 (Max DD)</div>
        <div className="text-base font-bold font-mono text-[#f85149]">
          -{metrics.max_drawdown_pct.toFixed(2)}%
        </div>
        <div className="text-[10px] text-[#8b949e]">风控警戒线 &lt; 15%</div>
      </div>

      {/* 7. 起止时空与摩擦成本 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e] flex items-center justify-between">
          <span>回测区间 / 摩擦</span>
          <Calendar className="w-2.5 h-2.5 text-[#bc8cff]" />
        </div>
        <div className="text-xs font-bold font-mono text-[#f0f6fc] truncate" title={metrics.backtest_period}>
          {metrics.backtest_period}
        </div>
        <div className="text-[10px] text-[#8b949e] truncate">
          滑点规费: ¥{metrics.total_friction_cny.toFixed(2)}
        </div>
      </div>
    </section>
    </div>
  );
};
