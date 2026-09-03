import React, { useState } from 'react';
import { Layers, ChevronRight } from 'lucide-react';

interface BacktestSidebarProps {
  currentSymbol: string;
  onSelectSymbol: (symbol: string, name: string) => void;
}

const STOCK_POOL = [
  { symbol: '600519', name: '贵州茅台', pe: 28.5, mv: '2.1万亿' },
  { symbol: '300750', name: '宁德时代', pe: 22.1, mv: '8500亿' },
  { symbol: '601318', name: '中国平安', pe: 8.9, mv: '8800亿' },
  { symbol: '000858', name: '五粮液', pe: 18.2, mv: '5200亿' },
  { symbol: '600036', name: '招商银行', pe: 5.8, mv: '9400亿' },
  { symbol: '601899', name: '紫金矿业', pe: 14.2, mv: '4600亿' },
  { symbol: '002594', name: '比亚迪', pe: 19.8, mv: '7200亿' },
  { symbol: '600900', name: '长江电力', pe: 17.5, mv: '6800亿' },
  { symbol: '000333', name: '美的集团', pe: 12.6, mv: '4900亿' },
  { symbol: '600309', name: '万华化学', pe: 13.8, mv: '2400亿' },
];

const FUTURES_POOL = [
  { symbol: 'AU_IDX', name: '沪金主力', pe: 0, mv: '贵金属' },
  { symbol: 'AG_IDX', name: '沪银主力', pe: 0, mv: '贵金属' },
  { symbol: 'SN_IDX', name: '沪锡主力', pe: 0, mv: '有色' },
  { symbol: 'CU_IDX', name: '沪铜主力', pe: 0, mv: '有色' },
  { symbol: 'SC_IDX', name: '原油主力', pe: 0, mv: '能源化工' },
  { symbol: 'LC_IDX', name: '碳酸锂主力', pe: 0, mv: '新能源' },
  { symbol: 'MA_IDX', name: '甲醇主力', pe: 0, mv: '化工' },
  { symbol: 'P_IDX', name: '棕榈油主力', pe: 0, mv: '农产品' },
  { symbol: 'TA_IDX', name: 'PTA主力', pe: 0, mv: '化工' },
];

export const BacktestSidebar: React.FC<BacktestSidebarProps> = ({
  currentSymbol,
  onSelectSymbol,
}) => {
  const [activeTab, setActiveTab] = useState<'STOCK' | 'FUTURES'>('STOCK');
  const [search, setSearch] = useState('');

  const pool = activeTab === 'STOCK' ? STOCK_POOL : FUTURES_POOL;
  const filtered = pool.filter(
    (item) =>
      item.symbol.toLowerCase().includes(search.toLowerCase()) ||
      item.name.includes(search)
  );

  return (
    <aside className="w-64 bg-[#161b22] border-r border-[#30363d] flex flex-col h-full select-none">
      {/* Category Tabs */}
      <div className="p-3 border-b border-[#30363d]">
        <label className="text-[11px] font-semibold uppercase text-[#8b949e] tracking-wider mb-2 block">
          回测标的资产池
        </label>
        <div className="grid grid-cols-2 gap-1 bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d]">
          <button
            onClick={() => setActiveTab('STOCK')}
            className={`py-1 rounded text-xs font-semibold transition ${
              activeTab === 'STOCK'
                ? 'bg-[#1f6feb] text-white shadow'
                : 'text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            🏛️ 芒格A股池
          </button>
          <button
            onClick={() => setActiveTab('FUTURES')}
            className={`py-1 rounded text-xs font-semibold transition ${
              activeTab === 'FUTURES'
                ? 'bg-[#1f6feb] text-white shadow'
                : 'text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            🏆 商品期货
          </button>
        </div>
      </div>

      {/* Search Box */}
      <div className="px-3 py-2 border-b border-[#30363d]/60">
        <input
          type="text"
          placeholder="搜索回测标的..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs text-[#f0f6fc] placeholder-[#8b949e] focus:outline-none focus:border-[#58a6ff]"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {filtered.map((item) => {
          const isSelected = item.symbol === currentSymbol;
          return (
            <div
              key={item.symbol}
              onClick={() => onSelectSymbol(item.symbol, item.name)}
              className={`px-3 py-2 rounded-md cursor-pointer transition flex items-center justify-between ${
                isSelected
                  ? 'bg-[#1f6feb]/20 border border-[#58a6ff]/50 text-[#f0f6fc]'
                  : 'hover:bg-[#21262d] text-[#8b949e] hover:text-[#f0f6fc] border border-transparent'
              }`}
            >
              <div className="flex flex-col">
                <span className={`text-xs font-bold ${isSelected ? 'text-[#58a6ff]' : 'text-[#f0f6fc]'}`}>
                  {item.name}
                </span>
                <span className="text-[10px] text-[#8b949e] font-mono">{item.symbol}</span>
              </div>

              <div className="flex items-center gap-1.5 text-right">
                <span className="text-[10px] text-[#8b949e] font-mono">
                  {activeTab === 'STOCK' ? `PE ${item.pe}` : item.mv}
                </span>
                <ChevronRight className={`w-3.5 h-3.5 ${isSelected ? 'text-[#58a6ff]' : 'text-[#484f58]'}`} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-[#30363d] bg-[#0d1117]/50 text-[11px] text-[#8b949e]">
        <div className="flex items-center gap-1.5 font-medium text-[#3fb950]">
          <Layers className="w-3.5 h-3.5" />
          <span>点击标的即刻载入回测</span>
        </div>
      </div>
    </aside>
  );
};
