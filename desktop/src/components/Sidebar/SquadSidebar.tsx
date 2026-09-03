import React, { useState } from 'react';
import { StrategyMeta } from '../../types';
import { Layers, ChevronRight, CheckCircle2 } from 'lucide-react';

interface SquadSidebarProps {
  strategies: StrategyMeta[];
  currentStrategyId: string;
  currentSymbol: string;
  onSelectStrategy: (strat: StrategyMeta) => void;
  onSelectSymbol: (symbol: string) => void;
}

const SYMBOL_NAME_MAP: Record<string, string> = {
  SN_IDX: '沪锡',
  AU_IDX: '沪金',
  AG_IDX: '沪银',
  CU_IDX: '沪铜',
  AL_IDX: '沪铝',
  ZN_IDX: '沪锌',
  RB_IDX: '螺纹钢',
  HC_IDX: '热卷',
  SC_IDX: '原油',
  LC_IDX: '碳酸锂',
  SI_IDX: '工业硅',
  MA_IDX: '甲醇',
  TA_IDX: 'PTA',
  SA_IDX: '纯碱',
  FG_IDX: '玻璃',
  P_IDX: '棕榈油',
  Y_IDX: '豆油',
  M_IDX: '豆粕',
  J_IDX: '焦炭',
  JM_IDX: '焦煤',
  CF_IDX: '棉花',
  SR_IDX: '白糖',
  MA_PP: '甲醇-PP 套利',
  TA_PF: 'PTA-短纤 套利',
  SC_FU: '原油-燃料油 套利',
  TA_EG: 'PTA-乙二醇 套利',
  C_CS: '玉米-淀粉 套利',
  JM_J: '焦煤-焦炭 套利',
  '600519': '贵州茅台',
  '300750': '宁德时代',
  '601318': '中国平安',
  '000858': '五粮液',
  '600036': '招商银行',
  '601899': '紫金矿业',
  '002594': '比亚迪',
  '600900': '长江电力',
  '000333': '美的集团',
  '600309': '万华化学',
};

export const SquadSidebar: React.FC<SquadSidebarProps> = ({
  strategies,
  currentStrategyId,
  currentSymbol,
  onSelectStrategy,
  onSelectSymbol,
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  const currentStrat =
    strategies.find((s) => s.id === currentStrategyId) || strategies[0];

  const filteredSymbols = (currentStrat?.symbols || []).filter((sym) => {
    const name = SYMBOL_NAME_MAP[sym] || '';
    return (
      sym.toLowerCase().includes(searchTerm.toLowerCase()) ||
      name.includes(searchTerm)
    );
  });

  return (
    <aside className="w-64 bg-[#161b22] border-r border-[#30363d] flex flex-col h-full select-none">
      {/* Squad Header */}
      <div className="p-3 border-b border-[#30363d]">
        <label className="text-[11px] font-semibold uppercase text-[#8b949e] tracking-wider mb-2 block">
          策略战队库 (S-Grade Squads)
        </label>
        <div className="space-y-1 max-h-48 overflow-y-auto pr-1">
          {strategies.map((strat) => {
            const isActive = strat.id === currentStrategyId;
            return (
              <button
                key={strat.id}
                onClick={() => onSelectStrategy(strat)}
                className={`w-full text-left px-2.5 py-1.5 rounded text-xs font-medium flex items-center justify-between transition ${
                  isActive
                    ? 'bg-[#1f6feb] text-white shadow-sm font-semibold'
                    : 'text-[#8b949e] hover:bg-[#21262d] hover:text-[#f0f6fc]'
                }`}
              >
                <span className="truncate">{strat.short_name}</span>
                {isActive && <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* Symbol List Section */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="p-3 pb-2 flex items-center justify-between border-b border-[#30363d]/60">
          <span className="text-xs font-semibold text-[#f0f6fc] flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-[#58a6ff]" />
            战队主力品种 ({filteredSymbols.length})
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#21262d] text-[#8b949e] font-mono">
            {currentStrat?.timeframe}
          </span>
        </div>

        {/* Search Input */}
        <div className="px-3 py-2">
          <input
            type="text"
            placeholder="搜索品种 (如 沪锡/SN)..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs text-[#f0f6fc] placeholder-[#8b949e] focus:outline-none focus:border-[#58a6ff]"
          />
        </div>

        {/* Scrollable Symbol List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {filteredSymbols.map((sym) => {
            const isSelected = sym === currentSymbol;
            const symName = SYMBOL_NAME_MAP[sym] || sym;
            return (
              <div
                key={sym}
                onClick={() => onSelectSymbol(sym)}
                className={`px-3 py-2 rounded-md cursor-pointer transition flex items-center justify-between ${
                  isSelected
                    ? 'bg-[#1f6feb]/20 border border-[#58a6ff]/50 text-[#f0f6fc]'
                    : 'hover:bg-[#21262d] text-[#8b949e] hover:text-[#f0f6fc] border border-transparent'
                }`}
              >
                <div className="flex flex-col">
                  <span className={`text-xs font-bold ${isSelected ? 'text-[#58a6ff]' : 'text-[#f0f6fc]'}`}>
                    {symName}
                  </span>
                  <span className="text-[10px] text-[#8b949e] font-mono">{sym}</span>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#0d1117] text-[#3fb950] font-semibold border border-[#30363d]/60">
                    主力
                  </span>
                  <ChevronRight className={`w-3.5 h-3.5 ${isSelected ? 'text-[#58a6ff]' : 'text-[#484f58]'}`} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer Info */}
      <div className="p-3 border-t border-[#30363d] bg-[#0d1117]/50 text-[11px] text-[#8b949e] space-y-1">
        <div className="flex justify-between">
          <span>大数定律胜率:</span>
          <span className="text-[#3fb950] font-bold font-mono">{currentStrat?.summary_win_rate}%</span>
        </div>
        <div className="flex justify-between">
          <span>分配初始本金:</span>
          <span className="text-[#f0f6fc] font-mono">¥{currentStrat?.initial_capital.toLocaleString()}</span>
        </div>
      </div>
    </aside>
  );
};
