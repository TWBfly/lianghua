import React from 'react';
import { BacktestMetrics } from '../../types';
import { ShieldCheck, AlertCircle, Clock, Calendar } from 'lucide-react';

interface BacktestMetricsBarProps {
  metrics: BacktestMetrics | null;
  timeframe?: string;
}

export const BacktestMetricsBar: React.FC<BacktestMetricsBarProps> = ({ metrics, timeframe }) => {
  if (!metrics) return null;

  const isPos = metrics.total_return_pct >= 0;

  return (
    <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 p-3 bg-[#0d1117] border-b border-[#30363d] select-none">
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

      {/* 2. 年化收益率 */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-2.5 flex flex-col justify-between">
        <div className="text-[11px] text-[#8b949e]">年化收益率 (CAGR)</div>
        <div className={`text-base font-bold font-mono ${metrics.annualized_return_pct >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
          {metrics.annualized_return_pct >= 0 ? '+' : ''}{metrics.annualized_return_pct.toFixed(2)}%
        </div>
        <div className="text-[10px] text-[#8b949e]">
          {metrics.total_bars_count && metrics.total_bars_count < 15000 ? '折算年化 (252日)' : '复利年化复权'}
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
  );
};
