import React, { useState } from 'react';
import { Play, RotateCcw, Calendar, Settings2, Clock, Plus, Database, Award, ShieldCheck, Scale } from 'lucide-react';
import { BacktestRequest } from '../../types';

interface BacktestControlBarProps {
  requestParams: BacktestRequest;
  loading: boolean;
  totalBarsCount?: number;
  onChangeParams: (params: Partial<BacktestRequest>) => void;
  onRunBacktest: (params?: Partial<BacktestRequest>) => void;
  onOpenPortfolioModal: () => void;
  onOpenDualTrackModal: () => void;
}

const STRATEGY_OPTIONS = [
  { id: 'causal_ml', name: '🧠 Causal ML (因果机器学习)' },
  { id: 'supertrend', name: '📈 SuperTrend (超级趋势带)' },
  { id: 'taichong_elastoplastic_tensor', name: '🔮 太冲·弹塑性张量 (微观谐振)' },
  { id: 'guiyuan_zscore_reversion', name: '⚡ 归元·Z-Score 极值均值反转' },
  { id: 'alphatrend', name: '📊 AlphaTrend (自适应动量)' },
  { id: 'chandelier_exit', name: '🛑 Chandelier Exit (吊灯追踪止损)' },
  { id: 'bollinger_breakout', name: '🌊 Bollinger Bands (布林带突破)' },
  { id: 'squeeze_momentum', name: '💥 Squeeze Momentum (动量挤压)' },
];

const STANDARD_TIMEFRAMES = ['1m', '5m', '10m', '15m', '30m', '1h', '4h', '1d'];

export const BacktestControlBar: React.FC<BacktestControlBarProps> = ({
  requestParams,
  loading,
  totalBarsCount,
  onChangeParams,
  onRunBacktest,
  onOpenPortfolioModal,
  onOpenDualTrackModal,
}) => {
  const [showCustomTf, setShowCustomTf] = useState(false);
  const [customTfInput, setCustomTfInput] = useState('');

  // 默认周期严格为 15m
  const currentTf = requestParams.timeframe || '15m';
  const isSynthetic = requestParams.data_source === 'SYNTHETIC' || !!requestParams.use_synthetic;

  const handleSelectTimeframe = (tf: string) => {
    onChangeParams({ timeframe: tf });
    onRunBacktest({ timeframe: tf });
  };

  const handleApplyCustomTf = () => {
    const val = customTfInput.trim().toLowerCase();
    if (val) {
      handleSelectTimeframe(val);
      setShowCustomTf(false);
    }
  };

  const handleSelectDataSource = (source: 'REAL' | 'SYNTHETIC') => {
    const nextSynthetic = source === 'SYNTHETIC';
    const dateUpdates = nextSynthetic
      ? { start_date: '2015-01-01', end_date: '2020-03-10' }
      : { start_date: '2024-01-01', end_date: '2026-12-31' };
    const nextParams: Partial<BacktestRequest> = {
      data_source: source,
      use_synthetic: nextSynthetic,
      ...dateUpdates,
    };
    onChangeParams(nextParams);
    onRunBacktest(nextParams);
  };

  return (
    <div className="bg-[#161b22] border-b border-[#30363d] px-4 py-2.5 flex flex-col gap-2.5 select-none">
      {/* Row 1: Symbol, Strategy, Capital, Dates, Data Source Switcher, Actions */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap text-xs">
          {/* Symbol Input */}
          <div className="flex items-center gap-1.5 bg-[#0d1117] border border-[#30363d] rounded-md px-2.5 py-1">
            <span className="text-[#8b949e]">标的代码:</span>
            <input
              type="text"
              value={requestParams.symbol}
              onChange={(e) => onChangeParams({ symbol: e.target.value.trim().toUpperCase() })}
              placeholder="如 AU_IDX / 600519"
              className="bg-transparent font-bold text-[#f0f6fc] w-24 focus:outline-none"
            />
          </div>

          {/* Strategy Selector */}
          <div className="flex items-center gap-1.5 bg-[#0d1117] border border-[#30363d] rounded-md px-2.5 py-1">
            <Settings2 className="w-3.5 h-3.5 text-[#58a6ff]" />
            <span className="text-[#8b949e]">策略:</span>
            <select
              value={requestParams.strategy}
              onChange={(e) => {
                onChangeParams({ strategy: e.target.value });
                onRunBacktest({ strategy: e.target.value });
              }}
              className="bg-transparent text-[#f0f6fc] font-medium focus:outline-none cursor-pointer"
            >
              {STRATEGY_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.id} className="bg-[#161b22] text-[#f0f6fc]">
                  {opt.name}
                </option>
              ))}
            </select>
          </div>

          {/* 明确分离的数据源双模态切换: 真实实盘8000根 vs 算法构建50000根 */}
          <div className="flex items-center bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d]">
            <button
              onClick={() => handleSelectDataSource('REAL')}
              className={`px-3 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 transition ${
                !isSynthetic
                  ? 'bg-[#1f6feb] text-white shadow font-bold'
                  : 'text-[#8b949e] hover:text-[#f0f6fc]'
              }`}
            >
              <Database className="w-3.5 h-3.5 text-[#00ff88]" />
              <span>🏦 真实实盘分时 (8,000根K线)</span>
            </button>
            <button
              onClick={() => handleSelectDataSource('SYNTHETIC')}
              className={`px-3 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 transition ${
                isSynthetic
                  ? 'bg-[#8957e5] text-white shadow font-bold'
                  : 'text-[#8b949e] hover:text-[#f0f6fc]'
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5 text-[#bc8cff]" />
              <span>🧬 算法构建全域 (50,000根大数)</span>
            </button>
          </div>

          {/* Date Range Picker */}
          <div className="flex items-center gap-1.5 bg-[#0d1117] border border-[#30363d] rounded-md px-2.5 py-1">
            <Calendar className="w-3.5 h-3.5 text-[#bc8cff]" />
            <span className="text-[#8b949e]">{isSynthetic ? '沙盒周期:' : '区间:'}</span>
            <input
              type="date"
              value={requestParams.start_date}
              onChange={(e) => onChangeParams({ start_date: e.target.value })}
              className="bg-transparent text-[#f0f6fc] focus:outline-none"
            />
            <span className="text-[#8b949e]">至</span>
            <input
              type="date"
              value={requestParams.end_date}
              onChange={(e) => onChangeParams({ end_date: e.target.value })}
              className="bg-transparent text-[#f0f6fc] focus:outline-none"
            />
          </div>

          {/* Capital */}
          <div className="flex items-center gap-1.5 bg-[#0d1117] border border-[#30363d] rounded-md px-2.5 py-1">
            <span className="text-[#8b949e]">本金:</span>
            <input
              type="number"
              value={requestParams.initial_capital}
              onChange={(e) => onChangeParams({ initial_capital: parseFloat(e.target.value) || 1000000 })}
              step="100000"
              className="bg-transparent font-mono font-bold text-[#3fb950] w-24 focus:outline-none"
            />
          </div>
        </div>

        {/* Right Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Dual-Track Benchmark & 100-Point Audit Report Button */}
          <button
            onClick={onOpenDualTrackModal}
            className="px-3 py-1.5 rounded-lg bg-[#8957e5]/20 hover:bg-[#8957e5]/30 text-[#bc8cff] border border-[#8957e5]/40 text-xs font-bold flex items-center gap-1.5 transition shadow"
            title="综合对比真实K线与算法K线，进行100分策略体检打分、开平仓逻辑与改进建议"
          >
            <Scale className="w-3.5 h-3.5" />
            <span>⚖️ 真实 vs 算法双轨体检 (100分)</span>
          </button>

          {/* Portfolio LLN Modal Button */}
          <button
            onClick={onOpenPortfolioModal}
            className="px-3 py-1.5 rounded-lg bg-[#21262d] hover:bg-[#30363d] text-[#d29922] border border-[#d29922]/40 text-xs font-bold flex items-center gap-1.5 transition shadow"
          >
            <Award className="w-3.5 h-3.5" />
            <span>全品种大数矩阵战报 (1000+笔)</span>
          </button>

          {/* Run Backtest Button */}
          <button
            onClick={() => onRunBacktest()}
            disabled={loading}
            className="px-4 py-1.5 rounded-lg bg-[#1f6feb] hover:bg-[#388bfd] text-white text-xs font-bold flex items-center gap-1.5 shadow transition disabled:opacity-50"
          >
            {loading ? (
              <RotateCcw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{loading ? '撮合中...' : '🚀 运行深度回测'}</span>
          </button>
        </div>
      </div>

      {/* Row 2: Authoritative Single Multi-Timeframe Toolbar (Default: 15m) */}
      <div className="flex items-center justify-between border-t border-[#30363d]/60 pt-2 text-xs flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 text-[#8b949e] mr-1">
            <Clock className="w-3.5 h-3.5 text-[#00ff88]" />
            <span className="font-semibold">回测 K 线时间维度 (默认15m):</span>
          </div>

          {/* Timeframe Pills */}
          <div className="flex items-center bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d]">
            {STANDARD_TIMEFRAMES.map((tf) => {
              const isActive = currentTf === tf;
              return (
                <button
                  key={tf}
                  onClick={() => handleSelectTimeframe(tf)}
                  className={`px-3 py-1 rounded-md text-xs font-mono font-bold transition ${
                    isActive
                      ? 'bg-[#1f6feb] text-white shadow'
                      : 'text-[#8b949e] hover:text-[#f0f6fc] hover:bg-[#21262d]'
                  }`}
                >
                  {tf}
                </button>
              );
            })}
          </div>

          {/* Custom Timeframe Trigger */}
          <div className="relative flex items-center">
            {showCustomTf ? (
              <div className="flex items-center gap-1 bg-[#0d1117] border border-[#58a6ff] rounded-md px-2 py-0.5">
                <input
                  type="text"
                  placeholder="如 2h, 45m, 2m"
                  value={customTfInput}
                  onChange={(e) => setCustomTfInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleApplyCustomTf(); }}
                  className="bg-transparent text-xs text-[#f0f6fc] w-20 font-mono focus:outline-none"
                  autoFocus
                />
                <button
                  onClick={handleApplyCustomTf}
                  className="px-2 py-0.5 bg-[#1f6feb] text-white rounded text-[11px] font-bold"
                >
                  确认
                </button>
                <button
                  onClick={() => setShowCustomTf(false)}
                  className="text-[#8b949e] hover:text-[#f0f6fc] text-xs px-1"
                >
                  ✕
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowCustomTf(true)}
                className={`px-2.5 py-1 rounded-md text-xs flex items-center gap-1 border transition ${
                  !STANDARD_TIMEFRAMES.includes(currentTf)
                    ? 'bg-[#1f6feb]/20 text-[#58a6ff] border-[#58a6ff] font-bold font-mono'
                    : 'bg-[#0d1117] text-[#8b949e] border-[#30363d] hover:text-[#f0f6fc] hover:border-[#8b949e]'
                }`}
              >
                <Plus className="w-3 h-3" />
                <span>
                  {!STANDARD_TIMEFRAMES.includes(currentTf) ? `自定义: ${currentTf}` : '自定义维度'}
                </span>
              </button>
            )}
          </div>
        </div>

        {/* Status Badge */}
        <div className="text-[11px] font-mono flex items-center gap-2">
          <span className="text-[#8b949e]">当前载入:</span>
          {isSynthetic ? (
            <span className="px-2 py-0.5 rounded bg-[#8957e5]/20 text-[#bc8cff] border border-[#8957e5]/30 font-semibold flex items-center gap-1">
              🧬 算法构建全域深度沙盒 ({totalBarsCount || 35000} 根K线 • 1000+笔大数定律)
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded bg-[#1f6feb]/20 text-[#58a6ff] border border-[#1f6feb]/30 font-semibold flex items-center gap-1">
              🏦 真实历史实盘行情 ({totalBarsCount || 8136} 根真实K线 • 真实成交)
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
