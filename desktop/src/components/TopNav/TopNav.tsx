import React, { useState, useEffect } from 'react';
import { SystemStatus, StockBasicItem } from '../../types';
import { Search, Flame, LineChart } from 'lucide-react';
import { safeInvoke } from '../../utils/ipc';

interface TopNavProps {
  appMode: 'LIVE' | 'BACKTEST';
  systemStatus: SystemStatus | null;
  currentTimeframe: string;
  onSelectAppMode: (mode: 'LIVE' | 'BACKTEST') => void;
  onSelectTimeframe: (tf: string) => void;
  onSelectStock: (symbol: string, name: string) => void;
}

const TIMEFRAMES = ['1m', '5m', '10m', '15m', '30m', '1h', '4h', '1d'];

export const TopNav: React.FC<TopNavProps> = ({
  appMode,
  systemStatus,
  currentTimeframe,
  onSelectAppMode,
  onSelectTimeframe,
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
      {/* Brand & Mode Switcher */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xl">🔮</span>
          <h1 className="font-bold text-sm tracking-wide text-[#f0f6fc]">
            天极·太冲·归元 <span className="text-[#8b949e] font-normal text-xs">量化交易工作站</span>
          </h1>
        </div>

        {/* Mode Switcher Tabs */}
        <div className="flex items-center bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d]">
          <button
            onClick={() => onSelectAppMode('LIVE')}
            className={`px-3 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 transition ${
              appMode === 'LIVE'
                ? 'bg-[#1f6feb] text-white shadow'
                : 'text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            <Flame className="w-3.5 h-3.5 text-[#00ff88]" />
            <span>虚拟盘/实盘监控</span>
          </button>
          <button
            onClick={() => onSelectAppMode('BACKTEST')}
            className={`px-3 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 transition ${
              appMode === 'BACKTEST'
                ? 'bg-[#1f6feb] text-white shadow'
                : 'text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            <LineChart className="w-3.5 h-3.5 text-[#58a6ff]" />
            <span>策略因果回测实验台</span>
          </button>
        </div>
      </div>

      {/* Center: ONLY show in LIVE mode so there is NO duplicate timeframe bar in Backtest mode! */}
      {appMode === 'LIVE' ? (
        <div className="flex items-center bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d]">
          {TIMEFRAMES.map((tf) => {
            const isActive = tf === currentTimeframe;
            return (
              <button
                key={tf}
                onClick={() => onSelectTimeframe(tf)}
                className={`px-2.5 py-1 rounded-md text-xs font-mono font-medium transition ${
                  isActive
                    ? 'bg-[#1f6feb] text-white shadow font-bold'
                    : 'text-[#8b949e] hover:text-[#f0f6fc] hover:bg-[#21262d]'
                }`}
              >
                {tf}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-[#8b949e]">
          <span className="w-2 h-2 rounded-full bg-[#00ff88] animate-pulse"></span>
          <span>因果大数回测引擎已就绪 (支持1m-1d与50,000根虚拟全域深度K线)</span>
        </div>
      )}

      {/* Right Controls: Metrics + Search */}
      <div className="flex items-center gap-4">
        {/* Dynamic Equity Badge */}
        <div className="flex items-center gap-3 text-xs">
          <div className="flex flex-col text-right">
            <span className="text-[10px] text-[#8b949e]">战队动态净值</span>
            <span className="font-mono font-bold text-[#3fb950]">
              ¥{systemStatus?.total_equity.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '2,000,000.00'}
            </span>
          </div>

          <div className="h-6 w-[1px] bg-[#30363d]" />

          <div className="flex flex-col text-right">
            <span className="text-[10px] text-[#8b949e]">大数综合胜率</span>
            <span className="font-mono font-bold text-[#58a6ff]">
              {systemStatus?.win_rate.toFixed(1) || '78.6'}%
            </span>
          </div>
        </div>

        {/* Stock/Commodity Search Box */}
        <div className="relative">
          <div className="flex items-center bg-[#0d1117] border border-[#30363d] rounded-lg px-2.5 py-1 w-44 focus-within:w-60 focus-within:border-[#58a6ff] transition-all">
            <Search className="w-3.5 h-3.5 text-[#8b949e] mr-2 flex-shrink-0" />
            <input
              type="text"
              placeholder="搜单股/标的 (600519)..."
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
                A 股全市场估值快照 (5,884只)
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
                      <div className="text-[10px] text-[#8b949e] font-mono">PE: {stock.pe_ttm.toFixed(1)}</div>
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
