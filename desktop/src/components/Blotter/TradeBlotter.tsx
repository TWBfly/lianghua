import React, { useState } from 'react';
import { TradeRecord } from '../../types';
import { ArrowUpRight, ArrowDownRight, Clock } from 'lucide-react';

interface TradeBlotterProps {
  trades: TradeRecord[];
  currentSymbol: string;
}

export const TradeBlotter: React.FC<TradeBlotterProps> = ({ trades, currentSymbol }) => {
  const [filterSymbolOnly, setFilterSymbolOnly] = useState(false);

  const displayedTrades = filterSymbolOnly
    ? trades.filter((t) => t.symbol === currentSymbol)
    : trades;

  return (
    <section className="h-56 bg-[#161b22] border-t border-[#30363d] flex flex-col select-none">
      {/* Blotter Header */}
      <div className="h-9 px-4 border-b border-[#30363d] flex items-center justify-between bg-[#21262d]/50">
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-[#f0f6fc] flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-[#58a6ff]" />
            战队交易流水与盘中活跃持仓 ({displayedTrades.length})
          </span>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1.5 text-[#8b949e] cursor-pointer hover:text-[#f0f6fc]">
            <input
              type="checkbox"
              checked={filterSymbolOnly}
              onChange={(e) => setFilterSymbolOnly(e.target.checked)}
              className="rounded bg-[#0d1117] border-[#30363d] text-[#1f6feb] focus:ring-0"
            />
            <span>仅看当前品种 ({currentSymbol})</span>
          </label>
        </div>
      </div>

      {/* Table Container */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="bg-[#161b22] sticky top-0 border-b border-[#30363d] text-[#8b949e]">
            <tr>
              <th className="py-2 px-3 font-semibold">标的品种</th>
              <th className="py-2 px-3 font-semibold">策略战队</th>
              <th className="py-2 px-3 font-semibold">方向</th>
              <th className="py-2 px-3 font-semibold">开仓时间</th>
              <th className="py-2 px-3 font-semibold">开仓均价</th>
              <th className="py-2 px-3 font-semibold">平仓/止损价</th>
              <th className="py-2 px-3 font-semibold">手数</th>
              <th className="py-2 px-3 font-semibold">结算净利润</th>
              <th className="py-2 px-3 font-semibold">平仓依据 / 止损轨</th>
              <th className="py-2 px-3 font-semibold">状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#30363d]/40 font-mono">
            {displayedTrades.length > 0 ? (
              displayedTrades.map((t, idx) => {
                const isLong = t.side === 'LONG' || t.side.includes('多');
                const isLive = t.status.includes('活跃持仓');
                const isWin = t.pnl >= 0;

                return (
                  <tr
                    key={idx}
                    className={`hover:bg-[#21262d]/70 transition ${
                      isLive ? 'bg-[#1f6feb]/10 font-semibold' : ''
                    }`}
                  >
                    <td className="py-2 px-3">
                      <span className="font-bold text-[#f0f6fc]">{t.symbol}</span>
                    </td>
                    <td className="py-2 px-3 text-[#8b949e] font-sans truncate max-w-[140px]">
                      {t.strategy_id}
                    </td>
                    <td className="py-2 px-3">
                      <span
                        className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-[11px] font-bold ${
                          isLong
                            ? 'bg-[#3fb950]/20 text-[#3fb950] border border-[#3fb950]/30'
                            : 'bg-[#f85149]/20 text-[#f85149] border border-[#f85149]/30'
                        }`}
                      >
                        {isLong ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        {isLong ? '买多' : '卖空'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-[#8b949e]">{t.entry_dt}</td>
                    <td className="py-2 px-3 text-[#f0f6fc]">
                      ¥{t.entry_p.toLocaleString(undefined, { minimumFractionDigits: 1 })}
                    </td>
                    <td className="py-2 px-3 text-[#f0f6fc]">
                      {t.exit_p > 0
                        ? `¥${t.exit_p.toLocaleString(undefined, { minimumFractionDigits: 1 })}`
                        : '-'}
                    </td>
                    <td className="py-2 px-3 text-[#58a6ff]">{t.lots} 手</td>
                    <td className="py-2 px-3 font-bold">
                      {isLive ? (
                        <span className="text-[#00ff88]">🔥 盘中浮盈浮亏监控</span>
                      ) : (
                        <span className={isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}>
                          {isWin ? '+' : ''}¥{t.pnl.toLocaleString()}
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-[#8b949e] font-sans truncate max-w-[180px]">
                      {t.exit_reason}
                    </td>
                    <td className="py-2 px-3">
                      <span
                        className={`text-[11px] px-2 py-0.5 rounded ${
                          isLive
                            ? 'bg-[#00ff88]/20 text-[#00ff88] border border-[#00ff88]/40 font-bold'
                            : 'bg-[#21262d] text-[#8b949e]'
                        }`}
                      >
                        {t.status}
                      </span>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={10} className="py-8 text-center text-[#8b949e] font-sans">
                  暂无相关交易记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
