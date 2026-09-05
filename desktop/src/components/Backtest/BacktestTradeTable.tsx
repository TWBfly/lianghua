import React, { useState, useEffect } from 'react';
import { BacktestTradeItem } from '../../types';
import { FileText, Crosshair, CheckCircle2, ChevronDown, ChevronUp, Maximize2, Minimize2 } from 'lucide-react';

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
  const [isExpanded, setIsExpanded] = useState(trades.length > 0);
  const [filterType, setFilterType] = useState<'ALL' | 'WIN' | 'LOSS'>('ALL');
  const [tableHeight, setTableHeight] = useState<number>(() => {
    const saved = localStorage.getItem('BACKTEST_TABLE_HEIGHT');
    return saved ? Math.max(140, Math.min(1000, Number(saved))) : 340;
  });
  const [isMaximized, setIsMaximized] = useState(false);
  const [density, setDensity] = useState<'normal' | 'compact'>('normal');
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    // 当有成交记录生成时，自动展开；若为0笔（如熔断状态）则默认折叠
    setIsExpanded(trades.length > 0);
  }, [trades.length]);

  useEffect(() => {
    localStorage.setItem('BACKTEST_TABLE_HEIGHT', String(tableHeight));
  }, [tableHeight]);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';

    const startY = e.clientY;
    const startHeight = isMaximized ? 650 : tableHeight;

    const handleMouseMove = (ev: MouseEvent) => {
      // 向上拉：startY > ev.clientY，deltaY 为正，高度增加
      const deltaY = startY - ev.clientY;
      const nextHeight = Math.max(140, Math.min(1200, startHeight + deltaY));
      setTableHeight(nextHeight);
      setIsExpanded(true);
      setIsMaximized(false);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  };

  const filteredTrades = trades.filter((t) => {
    if (filterType === 'WIN') return t.pnl_amount >= 0;
    if (filterType === 'LOSS') return t.pnl_amount < 0;
    return true;
  });

  const sectionHeight = !isExpanded
    ? '36px'
    : isMaximized
    ? '680px'
    : `${tableHeight}px`;

  const cellCls = density === 'compact' ? 'py-1 px-2.5' : 'py-2 px-3';

  return (
    <section
      style={{ height: sectionHeight }}
      className="bg-[#161b22] border-t border-[#30363d] flex flex-col flex-shrink-0 select-none relative transition-all duration-75"
    >
      {/* 顶部拖拽调整高度把手 (自由向上拉大、向下拉小，支持看更多数据) */}
      <div
        onMouseDown={handleMouseDown}
        className={`h-3 w-full cursor-row-resize flex items-center justify-center group flex-shrink-0 select-none z-30 transition-colors ${
          isDragging
            ? 'bg-[#1f6feb]/30 border-b border-[#58a6ff]'
            : 'bg-[#161b22] hover:bg-[#1f6feb]/15 hover:border-b hover:border-[#58a6ff]/40'
        }`}
        title="按住鼠标向上拖动：拉大表格查看更多数据；向下拖动缩小"
      >
        <div
          className={`h-1 rounded-full transition-all duration-150 ${
            isDragging
              ? 'w-24 bg-[#58a6ff]'
              : 'w-16 bg-[#58a6ff]/50 group-hover:w-24 group-hover:bg-[#58a6ff]'
          }`}
        />
      </div>

      {/* Table Header Controls */}
      <div className="h-9 px-3 sm:px-4 border-b border-[#30363d] flex items-center justify-between bg-[#21262d]/60 flex-shrink-0 gap-2">
        <div className="flex items-center gap-2 truncate">
          <FileText className="w-3.5 h-3.5 text-[#58a6ff] shrink-0" />
          <span className="text-xs font-bold text-[#f0f6fc] shrink-0">
            策略交易清单 ({filteredTrades.length} 笔)
          </span>
          {isExpanded && (
            <span className="text-[10px] text-[#8b949e] ml-2 hidden lg:inline truncate">
              💡 点击任意记录可立即将 K 线跳转聚焦至对应开仓点
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          {/* Filter Pills */}
          {trades.length > 0 && isExpanded && (
            <div className="flex items-center gap-1 text-xs">
              <button
                onClick={() => setFilterType('ALL')}
                className={`px-2 py-0.5 rounded text-[11px] font-medium transition cursor-pointer ${
                  filterType === 'ALL'
                    ? 'bg-[#1f6feb] text-white font-bold shadow'
                    : 'text-[#8b949e] hover:text-[#f0f6fc]'
                }`}
              >
                全部 ({trades.length})
              </button>
              <button
                onClick={() => setFilterType('WIN')}
                className={`px-2 py-0.5 rounded text-[11px] font-medium transition cursor-pointer ${
                  filterType === 'WIN'
                    ? 'bg-[#3fb950]/20 text-[#3fb950] border border-[#3fb950]/30 font-bold shadow'
                    : 'text-[#8b949e] hover:text-[#3fb950]'
                }`}
              >
                盈利 ({trades.filter((t) => t.pnl_amount >= 0).length})
              </button>
              <button
                onClick={() => setFilterType('LOSS')}
                className={`px-2 py-0.5 rounded text-[11px] font-medium transition cursor-pointer ${
                  filterType === 'LOSS'
                    ? 'bg-[#f85149]/20 text-[#f85149] border border-[#f85149]/30 font-bold shadow'
                    : 'text-[#8b949e] hover:text-[#f85149]'
                }`}
              >
                亏损 ({trades.filter((t) => t.pnl_amount < 0).length})
              </button>
            </div>
          )}

          {/* 缩小/放大 快捷档位调节器 */}
          {isExpanded && (
            <div className="flex items-center bg-[#0d1117] border border-[#30363d] rounded p-0.5 text-[11px]">
              <button
                onClick={() => {
                  setTableHeight(180);
                  setIsMaximized(false);
                }}
                className={`px-1.5 py-0.5 rounded hover:text-white transition cursor-pointer ${
                  !isMaximized && tableHeight <= 200
                    ? 'bg-[#21262d] text-[#58a6ff] font-bold'
                    : 'text-[#8b949e]'
                }`}
                title="缩小表格高度至 180px"
              >
                缩小
              </button>
              <button
                onClick={() => {
                  setTableHeight(340);
                  setIsMaximized(false);
                }}
                className={`px-1.5 py-0.5 rounded hover:text-white transition cursor-pointer ${
                  !isMaximized && tableHeight > 200 && tableHeight < 450
                    ? 'bg-[#21262d] text-[#58a6ff] font-bold'
                    : 'text-[#8b949e]'
                }`}
                title="适中表格高度至 340px"
              >
                默认
              </button>
              <button
                onClick={() => {
                  setTableHeight(520);
                  setIsMaximized(false);
                }}
                className={`px-1.5 py-0.5 rounded hover:text-white transition cursor-pointer ${
                  !isMaximized && tableHeight >= 450
                    ? 'bg-[#21262d] text-[#58a6ff] font-bold'
                    : 'text-[#8b949e]'
                }`}
                title="放大表格高度至 520px"
              >
                放大
              </button>
              <button
                onClick={() => setIsMaximized(!isMaximized)}
                className={`px-1.5 py-0.5 rounded hover:text-white transition cursor-pointer flex items-center gap-0.5 ${
                  isMaximized
                    ? 'bg-[#1f6feb] text-white font-bold'
                    : 'text-[#8b949e]'
                }`}
                title={isMaximized ? '还原常规高度' : '全屏展开 680px 查看全部交易记录'}
              >
                {isMaximized ? (
                  <>
                    <Minimize2 className="w-3 h-3" />
                    <span>还原</span>
                  </>
                ) : (
                  <>
                    <Maximize2 className="w-3 h-3" />
                    <span>全屏</span>
                  </>
                )}
              </button>
            </div>
          )}

          {/* 密度紧凑度切换 (A- / A+) */}
          {isExpanded && (
            <button
              onClick={() => setDensity(density === 'normal' ? 'compact' : 'normal')}
              className="text-[11px] px-1.5 py-0.5 rounded bg-[#0d1117] hover:bg-[#21262d] border border-[#30363d] text-[#8b949e] hover:text-[#f0f6fc] transition cursor-pointer hidden sm:block"
              title={density === 'compact' ? '切换为标准字号间距' : '切换为紧凑字号间距（同屏看更多记录）'}
            >
              {density === 'compact' ? '字号:紧凑' : '字号:标准'}
            </button>
          )}

          {/* Toggle Expand/Collapse Button */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-[11px] text-[#58a6ff] hover:text-[#79c0ff] px-2 py-0.5 rounded hover:bg-[#30363d]/60 transition cursor-pointer border border-[#30363d]"
            title={isExpanded ? '收起交易清单，为上方标的列表与图表留出空间' : '展开交易清单'}
          >
            {isExpanded ? (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                <span>收起表格</span>
              </>
            ) : (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                <span>展开明细 ({trades.length})</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Table Container (带 min-h-0 确保在 Flexbox 伸缩时内部滚动条完美工作) */}
      {isExpanded && (
        <div className="flex-1 min-h-0 overflow-auto">
        <table className={`w-full text-left border-collapse ${density === 'compact' ? 'text-[11px]' : 'text-xs'}`}>
          <thead className="bg-[#161b22] sticky top-0 border-b border-[#30363d] text-[#8b949e] z-10">
            <tr>
              <th className={`${cellCls} font-semibold`}>编号</th>
              <th className={`${cellCls} font-semibold`}>标的代码</th>
              <th className={`${cellCls} font-semibold`}>名称</th>
              <th className={`${cellCls} font-semibold`}>买入开仓时间</th>
              <th className={`${cellCls} font-semibold`}>买入均价</th>
              <th className={`${cellCls} font-semibold`}>卖出平仓时间</th>
              <th className={`${cellCls} font-semibold`}>卖出均价</th>
              <th className={`${cellCls} font-semibold`}>成交手数/股</th>
              <th className={`${cellCls} font-semibold`}>盈亏率(%)</th>
              <th className={`${cellCls} font-semibold`}>实现净利润(¥)</th>
              <th className={`${cellCls} font-semibold`}>决策理由 / 退出依据</th>
              <th className={`${cellCls} font-semibold`}>摩擦规费</th>
              <th className={`${cellCls} font-semibold text-right`}>K线定位</th>
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
                    <td className={`${cellCls} text-[#8b949e] font-sans`}>
                      {isSelected ? (
                        <span className="text-[#58a6ff] font-bold flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> #{t.id}
                        </span>
                      ) : (
                        `#${t.id}`
                      )}
                    </td>
                    <td className={`${cellCls} font-bold text-[#58a6ff]`}>{t.symbol}</td>
                    <td className={`${cellCls} text-[#f0f6fc] font-sans font-medium`}>{t.name}</td>
                    <td className={`${cellCls} text-[#f0f6fc] font-semibold bg-[#161b22]/40`}>
                      {t.buy_date}
                    </td>
                    <td className={`${cellCls} text-[#f0f6fc]`}>
                      ¥{t.buy_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className={`${cellCls} text-[#8b949e]`}>{t.sell_date}</td>
                    <td className={`${cellCls} text-[#f0f6fc]`}>
                      ¥{t.sell_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className={`${cellCls}`}>
                      <span className={`text-[10px] px-1 py-0.5 rounded mr-1.5 font-bold ${
                        (t.buy_reason || '').includes('做空') || (t.sell_reason || '').includes('空')
                          ? 'bg-[#f85149]/20 text-[#f85149] border border-[#f85149]/40'
                          : 'bg-[#3fb950]/20 text-[#3fb950] border border-[#3fb950]/40'
                      }`}>
                        {(t.buy_reason || '').includes('做空') || (t.sell_reason || '').includes('空') ? '空' : '多'}
                      </span>
                      <span className="text-[#58a6ff]">{t.shares} 手</span>
                    </td>
                    <td className={`${cellCls} font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                      {isWin ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                    </td>
                    <td className={`${cellCls} font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                      {isWin ? '+' : ''}¥{t.pnl_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className={`${cellCls} font-sans max-w-xs truncate`} title={t.sell_reason}>
                      {t.sell_reason}
                    </td>
                    <td className={`${cellCls} text-[#8b949e] text-[11px] font-sans`}>
                      {t.fees_detail}
                    </td>
                    <td className={`${cellCls} text-right`}>
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
      )}
    </section>
  );
};
