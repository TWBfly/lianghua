import React, { useState } from 'react';
import { BacktestTradeItem } from '../../types';
import { FileText, Crosshair, CheckCircle2 } from 'lucide-react';

interface BacktestTradeTableProps {
  trades: BacktestTradeItem[];
  selectedTradeId?: number | null;
  onSelectTrade?: (trade: BacktestTradeItem) => void;
}

export const BacktestTradeTable: React.FC<BacktestTradeTableProps> = ({
  trades,
  selectedTradeId,
  onSelectTrade,
}) => {
  const [filterType, setFilterType] = useState<'ALL' | 'WIN' | 'LOSS'>('ALL');

  const filteredTrades = trades.filter((t) => {
    if (filterType === 'WIN') return t.pnl_amount >= 0;
    if (filterType === 'LOSS') return t.pnl_amount < 0;
    return true;
  });

  return (
    <section className="h-64 bg-[#161b22] border-t border-[#30363d] flex flex-col select-none">
      {/* Table Header Controls */}
      <div className="h-9 px-4 border-b border-[#30363d] flex items-center justify-between bg-[#21262d]/60">
        <div className="flex items-center gap-2">
          <FileText className="w-3.5 h-3.5 text-[#58a6ff]" />
          <span className="text-xs font-bold text-[#f0f6fc]">
            当前策略回测买卖清单 ({filteredTrades.length} 笔)
          </span>
          <span className="text-[10px] text-[#8b949e] ml-2">
            💡 点击任意记录可立即将 K 线跳转并聚焦至对应的开仓位置
          </span>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 text-xs">
          <button
            onClick={() => setFilterType('ALL')}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
              filterType === 'ALL'
                ? 'bg-[#1f6feb] text-white font-bold shadow'
                : 'text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            全部 ({trades.length})
          </button>
          <button
            onClick={() => setFilterType('WIN')}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
              filterType === 'WIN'
                ? 'bg-[#3fb950]/20 text-[#3fb950] border border-[#3fb950]/30 font-bold shadow'
                : 'text-[#8b949e] hover:text-[#3fb950]'
            }`}
          >
            盈利 ({trades.filter((t) => t.pnl_amount >= 0).length})
          </button>
          <button
            onClick={() => setFilterType('LOSS')}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
              filterType === 'LOSS'
                ? 'bg-[#f85149]/20 text-[#f85149] border border-[#f85149]/30 font-bold shadow'
                : 'text-[#8b949e] hover:text-[#f85149]'
            }`}
          >
            亏损 ({trades.filter((t) => t.pnl_amount < 0).length})
          </button>
        </div>
      </div>

      {/* Table Container */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="bg-[#161b22] sticky top-0 border-b border-[#30363d] text-[#8b949e] z-10">
            <tr>
              <th className="py-2 px-3 font-semibold">编号</th>
              <th className="py-2 px-3 font-semibold">标的代码</th>
              <th className="py-2 px-3 font-semibold">名称</th>
              <th className="py-2 px-3 font-semibold">买入开仓时间</th>
              <th className="py-2 px-3 font-semibold">买入均价</th>
              <th className="py-2 px-3 font-semibold">卖出平仓时间</th>
              <th className="py-2 px-3 font-semibold">卖出均价</th>
              <th className="py-2 px-3 font-semibold">成交手数/股</th>
              <th className="py-2 px-3 font-semibold">盈亏率(%)</th>
              <th className="py-2 px-3 font-semibold">实现净利润(¥)</th>
              <th className="py-2 px-3 font-semibold">决策理由 / 退出依据</th>
              <th className="py-2 px-3 font-semibold">摩擦规费</th>
              <th className="py-2 px-3 font-semibold text-right">K线定位</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#30363d]/40 font-mono">
            {filteredTrades.length > 0 ? (
              filteredTrades.map((t) => {
                const isWin = t.pnl_amount >= 0;
                const isSelected = selectedTradeId === t.id;
                return (
                  <tr
                    key={t.id}
                    onClick={() => onSelectTrade?.(t)}
                    className={`transition cursor-pointer ${
                      isSelected
                        ? 'bg-[#1f6feb]/20 border-l-4 border-[#58a6ff] text-[#f0f6fc]'
                        : 'hover:bg-[#21262d]/70'
                    }`}
                  >
                    <td className="py-2 px-3 text-[#8b949e] font-sans">
                      {isSelected ? (
                        <span className="text-[#58a6ff] font-bold flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> #{t.id}
                        </span>
                      ) : (
                        `#${t.id}`
                      )}
                    </td>
                    <td className="py-2 px-3 font-bold text-[#58a6ff]">{t.symbol}</td>
                    <td className="py-2 px-3 text-[#f0f6fc] font-sans font-medium">{t.name}</td>
                    <td className="py-2 px-3 text-[#f0f6fc] font-semibold bg-[#161b22]/40">
                      {t.buy_date}
                    </td>
                    <td className="py-2 px-3 text-[#f0f6fc]">
                      ¥{t.buy_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-2 px-3 text-[#8b949e]">{t.sell_date}</td>
                    <td className="py-2 px-3 text-[#f0f6fc]">
                      ¥{t.sell_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-2 px-3 text-[#58a6ff]">{t.shares} 手</td>
                    <td className={`py-2 px-3 font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                      {isWin ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                    </td>
                    <td className={`py-2 px-3 font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                      {isWin ? '+' : ''}¥{t.pnl_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-2 px-3 font-sans max-w-xs truncate" title={t.sell_reason}>
                      {t.sell_reason}
                    </td>
                    <td className="py-2 px-3 text-[#8b949e] text-[11px] font-sans">
                      {t.fees_detail}
                    </td>
                    <td className="py-2 px-3 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectTrade?.(t);
                        }}
                        className={`text-[11px] px-2 py-0.5 rounded font-sans flex items-center gap-1 ml-auto transition ${
                          isSelected
                            ? 'bg-[#1f6feb] text-white font-bold'
                            : 'bg-[#1f6feb]/15 text-[#58a6ff] border border-[#58a6ff]/30 hover:bg-[#1f6feb] hover:text-white'
                        }`}
                      >
                        <Crosshair className="w-3 h-3" />
                        <span>{isSelected ? '已定位' : '定位'}</span>
                      </button>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={13} className="py-12 text-center text-[#8b949e] font-sans">
                  暂无回测交易明细
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
