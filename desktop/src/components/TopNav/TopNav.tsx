import React, { useState, useEffect } from 'react';
import { StockBasicItem } from '../../types';
import { Search, LineChart, ShieldCheck } from 'lucide-react';
import { safeInvoke } from '../../utils/ipc';

interface TopNavProps {
  onSelectStock: (symbol: string, name: string) => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  onSelectStock,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<StockBasicItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res: StockBasicItem[] = await safeInvoke('search_stocks', { query: searchQuery });
        setSearchResults(res || []);
        setShowDropdown(true);
      } catch (err) {
        console.error('Search failed:', err);
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  return (
    <header className="h-12 bg-[#161b22] border-b border-[#30363d] px-4 flex items-center justify-between select-none relative z-30">
      {/* Brand & Pure Backtest Mode Tag */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">🔮</span>
          <h1 className="font-bold text-sm tracking-wide text-[#f0f6fc]">
            天极·太冲·归元 <span className="text-[#8b949e] font-normal text-xs">量化策略因果回测工作站</span>
          </h1>
        </div>

        <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#1f6feb]/20 text-[#58a6ff] border border-[#1f6feb]/40">
          <LineChart className="w-3.5 h-3.5" />
          <span>纯净回测系统</span>
        </div>
      </div>

      {/* Center: Backtest System Engine Status */}
      <div className="hidden md:flex items-center gap-2 text-xs text-[#8b949e]">
        <span className="w-2 h-2 rounded-full bg-[#00ff88] animate-pulse" />
        <span className="font-medium text-[#c9d1d9]">因果回测引擎已就绪</span>
        <span className="text-[#30363d]">|</span>
        <span>Next-Open 次柱撮合 · 物理跳价滑点与真实规费 · 逐柱动态盯市 (M2M)</span>
      </div>

      {/* Right Controls: Audit Badge + Search */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-[#3fb950] bg-[#3fb950]/10 border border-[#3fb950]/30 px-2.5 py-1 rounded-md">
          <ShieldCheck className="w-3.5 h-3.5" />
          <span className="font-semibold text-[11px]">无未来函数 · 严格因果</span>
        </div>

        {/* Stock/Commodity Search Box */}
        <div className="relative">
          <div className="flex items-center bg-[#0d1117] border border-[#30363d] rounded-lg px-2.5 py-1 w-44 focus-within:w-60 focus-within:border-[#58a6ff] transition-all">
            <Search className="w-3.5 h-3.5 text-[#8b949e] mr-2 flex-shrink-0" />
            <input
              type="text"
              placeholder="搜品种/标的..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => { if (searchResults.length > 0) setShowDropdown(true); }}
              className="bg-transparent text-xs text-[#f0f6fc] placeholder-[#8b949e] focus:outline-none w-full"
            />
          </div>

          {/* Search Dropdown */}
          {showDropdown && searchResults.length > 0 && (
            <div className="absolute right-0 top-full mt-1.5 w-72 bg-[#161b22] border border-[#30363d] rounded-lg shadow-2xl overflow-hidden z-50">
              <div className="p-2 border-b border-[#30363d] text-[10px] font-semibold text-[#8b949e] uppercase">
                标的快速检索
              </div>
              <div className="max-h-60 overflow-y-auto divide-y divide-[#30363d]/40">
                {searchResults.map((stock) => (
                  <div
                    key={stock.symbol}
                    onClick={() => {
                      onSelectStock(stock.symbol, stock.name);
                      setShowDropdown(false);
                      setSearchQuery('');
                    }}
                    className="p-2 hover:bg-[#21262d] cursor-pointer flex items-center justify-between text-xs transition"
                  >
                    <div>
                      <div className="font-bold text-[#f0f6fc]">{stock.name}</div>
                      <div className="text-[10px] text-[#8b949e] font-mono">{stock.symbol}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[#58a6ff]">¥{stock.price.toFixed(2)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
