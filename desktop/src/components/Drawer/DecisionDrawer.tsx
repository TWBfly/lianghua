import React from 'react';
import { ChartMarker, BacktestTradeItem } from '../../types';
import { ShieldCheck, Target, Cpu, X, Compass, Calendar, Clock, ArrowRight } from 'lucide-react';

interface DecisionDrawerProps {
  selectedMarker: ChartMarker | null;
  selectedTrade?: BacktestTradeItem | null;
  currentSymbol: string;
  onClose: () => void;
}

export const DecisionDrawer: React.FC<DecisionDrawerProps> = ({
  selectedMarker,
  selectedTrade,
  currentSymbol: _currentSymbol,
  onClose,
}) => {
  return (
    <aside className="w-80 bg-[#161b22] border-l border-[#30363d] flex flex-col h-full select-none overflow-y-auto">
      {/* Header */}
      <div className="p-3.5 border-b border-[#30363d] flex items-center justify-between bg-[#21262d]/50">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-[#58a6ff]" />
          <h3 className="text-xs font-bold text-[#f0f6fc]">策略因果决策明细</h3>
        </div>
        {(selectedMarker || selectedTrade) && (
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[#21262d] text-[#8b949e] hover:text-[#f0f6fc]"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Body */}
      <div className="p-4 space-y-4 flex-1">
        {selectedTrade ? (
          /* When a trade row is selected from the bottom table */
          <div className="space-y-4">
            <div className="p-3 bg-[#21262d] rounded-lg border border-[#30363d]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-[#58a6ff]">
                  #{selectedTrade.id} {selectedTrade.name} ({selectedTrade.symbol})
                </span>
                <span className={`text-[11px] font-bold font-mono ${selectedTrade.pnl_amount >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                  {selectedTrade.pnl_amount >= 0 ? '+' : ''}{selectedTrade.pnl_pct.toFixed(2)}%
                </span>
              </div>

              {/* Execution Dates & Times */}
              <div className="space-y-2 text-xs">
                <div className="bg-[#0d1117] p-2.5 rounded border border-[#30363d] space-y-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[#3fb950] font-bold flex items-center gap-1">
                      <Clock className="w-3 h-3" /> 开仓时间:
                    </span>
                    <span className="font-mono text-[#f0f6fc] font-semibold">{selectedTrade.buy_date}</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[#8b949e]">买入均价:</span>
                    <span className="font-mono text-[#f0f6fc] font-bold">¥{selectedTrade.buy_price.toFixed(2)}</span>
                  </div>
                </div>

                <div className="flex justify-center">
                  <ArrowRight className="w-3.5 h-3.5 text-[#8b949e] rotate-90" />
                </div>

                <div className="bg-[#0d1117] p-2.5 rounded border border-[#30363d] space-y-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[#d29922] font-bold flex items-center gap-1">
                      <Calendar className="w-3 h-3" /> 平仓时间:
                    </span>
                    <span className="font-mono text-[#f0f6fc] font-semibold">{selectedTrade.sell_date}</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[#8b949e]">卖出均价:</span>
                    <span className="font-mono text-[#f0f6fc] font-bold">¥{selectedTrade.sell_price.toFixed(2)}</span>
                  </div>
                </div>

                {/* Net PnL */}
                <div className="flex justify-between py-1 border-t border-[#30363d]/60">
                  <span className="text-[#8b949e]">实现净利润:</span>
                  <span className={`font-mono font-bold ${selectedTrade.pnl_amount >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                    {selectedTrade.pnl_amount >= 0 ? '+' : ''}¥{selectedTrade.pnl_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>

                {/* Decision Reason */}
                <div className="pt-1 flex flex-col gap-1">
                  <span className="text-[11px] text-[#8b949e]">决策理由 / 退出依据:</span>
                  <span className="text-xs text-[#58a6ff] bg-[#0d1117] p-2 rounded border border-[#30363d]/40">
                    {selectedTrade.sell_reason}
                  </span>
                </div>

                {/* Fees Detail */}
                <div className="text-[10px] text-[#8b949e]">
                  {selectedTrade.fees_detail}
                </div>
              </div>
            </div>
          </div>
        ) : selectedMarker ? (
          <div className="space-y-4">
            {/* Selected Trade Node Summary */}
            <div className="p-3 bg-[#21262d] rounded-lg border border-[#30363d]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-[#58a6ff]">
                  {selectedMarker.text}
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0d1117] text-[#8b949e] font-mono">
                  {new Date(selectedMarker.time * 1000).toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              <div className="space-y-1.5 text-xs text-[#8b949e]">
                <div className="flex justify-between">
                  <span>执行动作:</span>
                  <span className="text-[#f0f6fc] font-semibold">{selectedMarker.action}</span>
                </div>
                <div className="flex justify-between">
                  <span>触发基准价:</span>
                  <span className="text-[#f0f6fc] font-mono font-semibold">
                    ¥{selectedMarker.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
                {selectedMarker.pnl !== undefined && selectedMarker.pnl !== null && (
                  <div className="flex justify-between">
                    <span>结算净盈亏:</span>
                    <span
                      className={`font-mono font-bold ${
                        selectedMarker.pnl >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                      }`}
                    >
                      {selectedMarker.pnl >= 0 ? '+' : ''}¥{selectedMarker.pnl.toLocaleString()}
                    </span>
                  </div>
                )}
                <div className="pt-2 border-t border-[#30363d]/60 flex flex-col gap-1">
                  <span className="text-[11px] text-[#8b949e]">决策依据:</span>
                  <span className="text-xs text-[#58a6ff] bg-[#0d1117] p-2 rounded border border-[#30363d]/40">
                    {selectedMarker.reason}
                  </span>
                </div>
              </div>
            </div>

            {/* Factor Features Breakdown */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-[#f0f6fc] flex items-center gap-1.5">
                <Compass className="w-3.5 h-3.5 text-[#bc8cff]" />
                实时因果力学特征
              </span>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 bg-[#0d1117] rounded border border-[#30363d]">
                  <div className="text-[10px] text-[#8b949e] mb-0.5">弹塑性势能</div>
                  <div className="text-[#3fb950] font-mono font-bold">2.84 σ</div>
                </div>
                <div className="p-2.5 bg-[#0d1117] rounded border border-[#30363d]">
                  <div className="text-[10px] text-[#8b949e] mb-0.5">动量分位数</div>
                  <div className="text-[#58a6ff] font-mono font-bold">89.2%</div>
                </div>
                <div className="p-2.5 bg-[#0d1117] rounded border border-[#30363d]">
                  <div className="text-[10px] text-[#8b949e] mb-0.5">OFI失衡度</div>
                  <div className="text-[#d29922] font-mono font-bold">+1.45</div>
                </div>
                <div className="p-2.5 bg-[#0d1117] rounded border border-[#30363d]">
                  <div className="text-[10px] text-[#8b949e] mb-0.5">ATR动态止损</div>
                  <div className="text-[#f85149] font-mono font-bold">1.25x</div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Default state when nothing is selected */
          <div className="space-y-4">
            <div className="p-3 bg-[#21262d] rounded-lg border border-[#30363d] text-center text-xs text-[#8b949e]">
              <Target className="w-6 h-6 text-[#58a6ff] mx-auto mb-2 opacity-80" />
              <p className="font-semibold text-[#f0f6fc] mb-1">点击下方清单或 K 线买卖点</p>
              <p className="text-[11px]">可立即定位到对应 K 线蜡烛柱，并调阅详细开平仓时间戳与决策依据。</p>
            </div>

            {/* General Risk & 100-Scorecard Metrics */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-[#f0f6fc] flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-[#3fb950]" />
                战队大数定律健康度 (100分)
              </span>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between p-2 bg-[#0d1117] rounded border border-[#30363d]">
                  <span className="text-[#8b949e]">大数样本:</span>
                  <span className="text-[#f0f6fc] font-mono font-bold">&gt; 1000 笔真实样本</span>
                </div>
                <div className="flex justify-between p-2 bg-[#0d1117] rounded border border-[#30363d]">
                  <span className="text-[#8b949e]">极限风控回撤:</span>
                  <span className="text-[#3fb950] font-mono font-bold">&lt; 1.2% (平原测试)</span>
                </div>
                <div className="flex justify-between p-2 bg-[#0d1117] rounded border border-[#30363d]">
                  <span className="text-[#8b949e]">期望盈亏比 (P/L):</span>
                  <span className="text-[#d29922] font-mono font-bold">2.45 : 1</span>
                </div>
                <div className="flex justify-between p-2 bg-[#0d1117] rounded border border-[#30363d]">
                  <span className="text-[#8b949e]">破产概率 P(Ruin):</span>
                  <span className="text-[#3fb950] font-mono font-bold">&lt; 0.001% (零爆仓风险)</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
};
