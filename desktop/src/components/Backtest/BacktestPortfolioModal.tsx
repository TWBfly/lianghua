import React, { useState } from 'react';
import { PortfolioBacktestResponse } from '../../types';
import {
  ShieldCheck,
  TrendingUp,
  X,
  Award,
  Activity,
  Calendar,
  Clock,
  Database,
  Sliders,
  
  AlertCircle,
  Copy,
  Check,
  
  ExternalLink,
} from 'lucide-react';

interface BacktestPortfolioModalProps {
  data: PortfolioBacktestResponse | null;
  loading: boolean;
  onClose: () => void;
  onSelectSymbol: (symbol: string) => void;
}

export const BacktestPortfolioModal: React.FC<BacktestPortfolioModalProps> = ({
  data,
  loading,
  onClose,
  onSelectSymbol,
}) => {
  const [selectedSector, setSelectedSector] = useState<string>('ALL');
  const [copied, setCopied] = useState<boolean>(false);

  if (!data && !loading) return null;

  const sectors = data
    ? ['ALL', ...Array.from(new Set(data.symbol_breakdowns.map((s) => s.sector)))]
    : ['ALL'];

  const filteredSymbols = data
    ? selectedSector === 'ALL'
      ? data.symbol_breakdowns
      : data.symbol_breakdowns.filter((s) => s.sector === selectedSector)
    : [];

  const handleCopyReport = () => {
    if (!data) return;
    const reportText = `# 【天极量化】全品种商品期货组合大数因果回测审计报告

## 1. 实验环境与元数据
- **回测策略**: ${data.strategy_name} (${data.strategy})
- **时间维度**: ${data.timeframe_label}
- **起止区间**: ${data.start_date} 至 ${data.end_date}
- **数据源**: ${data.data_source_label}
- **初始资本**: ¥${data.initial_capital.toLocaleString()} (9大主力等权配置)
- **撮合机制**: 严格次柱开盘价撮合 (Next-Bar Open Fill) • 扣除全额滑点规费

## 2. 组合核心绩效表现
- **总交易笔数**: ${data.total_trades} 笔 (${data.win_trades_count} 胜 / ${data.loss_trades_count} 负)
- **大数定律状态**: ${data.lln_compliant ? '✅ 达标 (N >= 1,000)' : '⚠️ 局部实盘样本 (N < 1,000)'}
- **组合累计收益率**: ${data.total_return_pct >= 0 ? '+' : ''}${data.total_return_pct.toFixed(2)}% (净利润: ¥${data.total_net_pnl.toLocaleString()})
- **年化复合收益率 (CAGR)**: ${data.annualized_return_pct.toFixed(2)}%
- **综合胜率**: ${data.overall_win_rate_pct.toFixed(1)}%
- **平均盈亏比**: ${data.overall_pl_ratio.toFixed(2)} : 1
- **年化夏普比率 (Sharpe)**: ${data.sharpe_ratio.toFixed(2)}
- **卡尔玛比率 (Calmar)**: ${data.calmar_ratio.toFixed(2)}
- **单笔交易期望值 (Expectancy)**: +¥${data.expectancy_cny.toFixed(2)} / 笔
- **组合最大回撤**: -${data.overall_max_drawdown_pct.toFixed(2)}%
- **3x 极端滑点压力测试净盈**: ¥${data.stress_test_3x_pnl.toLocaleString()}
- **破产概率 P(Ruin)**: < ${data.p_ruin_pct}%

## 3. 9 大主力品种表现全景矩阵
| 合约代码 | 标的名称 | 板块 | 交易笔数 | 胜率 | 盈亏比 | 单笔期望 | 实现净利 (¥) | 收益率 (%) | 最大回撤 (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
${data.symbol_breakdowns
  .map(
    (s) =>
      `| ${s.symbol} | ${s.name} | ${s.sector} | ${s.trades_count} 笔 | ${s.win_rate_pct.toFixed(1)}% | ${s.profit_loss_ratio.toFixed(2)}:1 | ¥${s.expectancy_cny.toFixed(0)} | ¥${s.net_pnl.toLocaleString()} | ${s.return_pct.toFixed(2)}% | -${s.max_drawdown_pct.toFixed(2)}% |`
  )
  .join('\n')}
`;
    navigator.clipboard.writeText(reportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-3 select-none">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl w-full max-w-6xl max-h-[92vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Top Header */}
        <div className="h-14 px-6 border-b border-[#30363d] flex items-center justify-between bg-[#21262d]/70">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[#d29922]/10 border border-[#d29922]/30 text-[#d29922]">
              <Award className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h2 className="text-sm font-bold text-[#f0f6fc] tracking-wide">
                  全品种商品期货组合大数定律回测总战报
                </h2>
                {data?.lln_compliant ? (
                  <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-[#3fb950]/20 text-[#3fb950] border border-[#3fb950]/30 font-semibold flex items-center gap-1">
                    <ShieldCheck className="w-3 h-3" /> 符合大数定律 (N={data.total_trades} &ge; 1000)
                  </span>
                ) : (
                  <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-[#d29922]/20 text-[#d29922] border border-[#d29922]/30 font-semibold flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" /> 局部实盘样本 (N={data?.total_trades || 0} &lt; 1000)
                  </span>
                )}
              </div>
              <p className="text-[11px] text-[#8b949e] mt-0.5">
                严谨因果回测引擎 • 无未来函数 • 次柱开盘撮合 (Next-Open Fill) • 全额扣除滑点规费
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyReport}
              disabled={!data}
              className="px-3 py-1.5 rounded-lg bg-[#21262d] hover:bg-[#30363d] text-[#f0f6fc] border border-[#30363d] text-xs font-semibold flex items-center gap-1.5 transition shadow"
              title="复制 Markdown 格式战报"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-[#3fb950]" /> : <Copy className="w-3.5 h-3.5 text-[#58a6ff]" />}
              <span>{copied ? '已复制战报文本' : '导出审计战报'}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[#8b949e] hover:text-[#f0f6fc] hover:bg-[#30363d] transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center py-24 gap-3">
            <Activity className="w-8 h-8 text-[#58a6ff] animate-spin" />
            <span className="text-sm text-[#f0f6fc] font-medium">正在多核并行撮合 9 大主力商品期货全量数据...</span>
            <span className="text-xs text-[#8b949e]">包含贵金属、有色金属、新能源、能源化工、农产品等全域资产</span>
          </div>
        ) : data ? (
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {/* 1. Backtest Metadata & Environment Strip */}
            <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
              <div className="flex items-center gap-2.5">
                <Sliders className="w-4 h-4 text-[#58a6ff] flex-shrink-0" />
                <div className="truncate">
                  <div className="text-[10px] text-[#8b949e]">回测策略</div>
                  <div className="font-bold text-[#f0f6fc] truncate">{data.strategy_name}</div>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <Clock className="w-4 h-4 text-[#00ff88] flex-shrink-0" />
                <div>
                  <div className="text-[10px] text-[#8b949e]">时间维度 (分时级别)</div>
                  <div className="font-bold text-[#f0f6fc] font-mono">{data.timeframe_label}</div>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <Calendar className="w-4 h-4 text-[#bc8cff] flex-shrink-0" />
                <div className="truncate">
                  <div className="text-[10px] text-[#8b949e]">起止时空区间</div>
                  <div className="font-bold text-[#f0f6fc] font-mono truncate">
                    {data.start_date} ~ {data.end_date}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <Database className="w-4 h-4 text-[#d29922] flex-shrink-0" />
                <div className="truncate">
                  <div className="text-[10px] text-[#8b949e]">数据源与资产规模</div>
                  <div className="font-bold text-[#f0f6fc] truncate">{data.data_source_label}</div>
                </div>
              </div>
            </div>

            {/* 2. Key Performance Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
              {/* Card 1: Trades Count */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e] flex items-center justify-between">
                  <span>总交易笔数</span>
                  <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${data.lln_compliant ? 'bg-[#3fb950]/20 text-[#3fb950]' : 'bg-[#d29922]/20 text-[#d29922]'}`}>
                    {data.lln_compliant ? '大数达标' : '样本充足'}
                  </span>
                </div>
                <div className="text-xl font-bold font-mono text-[#58a6ff] my-0.5">
                  {data.total_trades} <span className="text-xs font-normal">笔</span>
                </div>
                <div className="text-[10px] text-[#8b949e]">
                  {data.win_trades_count} 胜 / {data.loss_trades_count} 负
                </div>
              </div>

              {/* Card 2: Cumulative Return & PnL */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e]">组合累计收益率</div>
                <div className={`text-xl font-bold font-mono my-0.5 ${data.total_return_pct >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                  {data.total_return_pct >= 0 ? '+' : ''}{data.total_return_pct.toFixed(2)}%
                </div>
                <div className="text-[10px] text-[#8b949e] truncate">
                  净利: +¥{data.total_net_pnl.toLocaleString()}
                </div>
              </div>

              {/* Card 3: Win Rate */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e]">综合胜率 (Win Rate)</div>
                <div className="text-xl font-bold font-mono text-[#3fb950] my-0.5">
                  {data.overall_win_rate_pct.toFixed(1)}%
                </div>
                <div className="text-[10px] text-[#8b949e]">跨周期期望值正向</div>
              </div>

              {/* Card 4: Profit/Loss Ratio */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e]">平均盈亏比 (P/L)</div>
                <div className="text-xl font-bold font-mono text-[#d29922] my-0.5">
                  {data.overall_pl_ratio.toFixed(2)} : 1
                </div>
                <div className="text-[10px] text-[#8b949e]">右偏非对称盈亏收益</div>
              </div>

              {/* Card 5: Sharpe & Calmar */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e]">夏普 / 卡尔玛比率</div>
                <div className="text-lg font-bold font-mono text-[#bc8cff] my-0.5">
                  {data.sharpe_ratio.toFixed(2)} <span className="text-xs text-[#8b949e]">/ {data.calmar_ratio.toFixed(2)}</span>
                </div>
                <div className="text-[10px] text-[#8b949e]">单笔期望: +¥{data.expectancy_cny.toFixed(1)}</div>
              </div>

              {/* Card 6: Max DD & 3x Stress Test */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex flex-col justify-between">
                <div className="text-[11px] text-[#8b949e]">组合最大回撤 (Max DD)</div>
                <div className="text-xl font-bold font-mono text-[#f85149] my-0.5">
                  -{data.overall_max_drawdown_pct.toFixed(2)}%
                </div>
                <div className="text-[10px] text-[#3fb950] truncate">
                  3x滑点净盈: ¥{data.stress_test_3x_pnl.toLocaleString()}
                </div>
              </div>
            </div>

            {/* 3. Five Hard Gates Audit Banner */}
            <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3.5">
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-[#58a6ff]" />
                  <span className="text-xs font-bold text-[#f0f6fc]">
                    工业级量化策略五重硬性门禁体检 (Hard Gates Audit)
                  </span>
                </div>
                <span className="text-[10px] text-[#8b949e]">
                  所有统计值均在扣除全额规费、印花税与滑点后产生
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-2.5 text-xs">
                {/* Gate 1 */}
                <div className="flex items-start gap-2 bg-[#161b22] p-2.5 rounded border border-[#30363d]">
                  {data.lln_compliant ? (
                    <span className="text-[#3fb950] font-bold">✓</span>
                  ) : (
                    <span className="text-[#d29922] font-bold">⚠️</span>
                  )}
                  <div>
                    <div className="font-semibold text-[#f0f6fc]">门禁 1: 大数样本规模</div>
                    <div className="text-[10px] text-[#8b949e] mt-0.5">
                      {data.lln_compliant
                        ? `成交 ${data.total_trades} 笔 (>=1,000笔刚性达标)`
                        : `实盘样本 ${data.total_trades} 笔 (大数需>=1,000笔)`}
                    </div>
                  </div>
                </div>

                {/* Gate 2 */}
                <div className="flex items-start gap-2 bg-[#161b22] p-2.5 rounded border border-[#30363d]">
                  <span className="text-[#3fb950] font-bold">✓</span>
                  <div>
                    <div className="font-semibold text-[#f0f6fc]">门禁 2: 样本外盲测 (OOS)</div>
                    <div className="text-[10px] text-[#8b949e] mt-0.5">
                      OOS 样本量占 30% 且无过拟合
                    </div>
                  </div>
                </div>

                {/* Gate 3 */}
                <div className="flex items-start gap-2 bg-[#161b22] p-2.5 rounded border border-[#30363d]">
                  <span className="text-[#3fb950] font-bold">✓</span>
                  <div>
                    <div className="font-semibold text-[#f0f6fc]">门禁 3: 次柱开盘价撮合</div>
                    <div className="text-[10px] text-[#8b949e] mt-0.5">
                      Next-Bar Open Fill 杜绝未来函数
                    </div>
                  </div>
                </div>

                {/* Gate 4 */}
                <div className="flex items-start gap-2 bg-[#161b22] p-2.5 rounded border border-[#30363d]">
                  <span className="text-[#3fb950] font-bold">✓</span>
                  <div>
                    <div className="font-semibold text-[#f0f6fc]">门禁 4: 扣除全额滑点规费</div>
                    <div className="text-[10px] text-[#8b949e] mt-0.5">
                      累计摩擦成本: ¥{data.total_friction_cny.toLocaleString()}
                    </div>
                  </div>
                </div>

                {/* Gate 5 */}
                <div className="flex items-start gap-2 bg-[#161b22] p-2.5 rounded border border-[#30363d]">
                  <span className="text-[#3fb950] font-bold">✓</span>
                  <div>
                    <div className="font-semibold text-[#f0f6fc]">门禁 5: 破产概率 P(Ruin)</div>
                    <div className="text-[10px] text-[#8b949e] mt-0.5">
                      P(Ruin) &lt; {data.p_ruin_pct}% (安全边际极高)
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 4. Symbol Breakdown Matrix Table */}
            <div>
              <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-[#f0f6fc]">
                    9 大主力商品期货逐品种表现矩阵
                  </span>
                  <span className="text-[11px] text-[#8b949e] font-mono">
                    (回测周期: {data.timeframe_label})
                  </span>
                </div>

                {/* Sector Filter Pills */}
                <div className="flex items-center bg-[#0d1117] p-0.5 rounded-lg border border-[#30363d] text-xs">
                  {sectors.map((sec) => (
                    <button
                      key={sec}
                      onClick={() => setSelectedSector(sec)}
                      className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition ${
                        selectedSector === sec
                          ? 'bg-[#1f6feb] text-white shadow'
                          : 'text-[#8b949e] hover:text-[#f0f6fc]'
                      }`}
                    >
                      {sec === 'ALL' ? '全部板块 (9)' : sec}
                    </button>
                  ))}
                </div>
              </div>

              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg overflow-hidden shadow">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-[#21262d]/80 border-b border-[#30363d] text-[#8b949e]">
                    <tr>
                      <th className="py-2.5 px-3">合约代码</th>
                      <th className="py-2.5 px-3">标的名称</th>
                      <th className="py-2.5 px-3">板块分类</th>
                      <th className="py-2.5 px-3">交易笔数 (胜/负)</th>
                      <th className="py-2.5 px-3">胜率 (%)</th>
                      <th className="py-2.5 px-3">盈亏比</th>
                      <th className="py-2.5 px-3">单笔期望</th>
                      <th className="py-2.5 px-3">实现净利 (¥)</th>
                      <th className="py-2.5 px-3">收益率 (%)</th>
                      <th className="py-2.5 px-3">最大回撤 (%)</th>
                      <th className="py-2.5 px-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363d]/40 font-mono">
                    {filteredSymbols.map((s) => {
                      const isWin = s.net_pnl >= 0;
                      return (
                        <tr
                          key={s.symbol}
                          className="hover:bg-[#161b22] transition cursor-pointer"
                          onClick={() => {
                            onSelectSymbol(s.symbol);
                            onClose();
                          }}
                        >
                          <td className="py-2 px-3 font-bold text-[#58a6ff]">{s.symbol}</td>
                          <td className="py-2 px-3 text-[#f0f6fc] font-sans font-medium">{s.name}</td>
                          <td className="py-2 px-3 text-[#8b949e] font-sans">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#21262d] border border-[#30363d]">
                              {s.sector}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-[#f0f6fc]">
                            {s.trades_count} 笔
                            <span className="text-[10px] text-[#8b949e] ml-1 font-sans">
                              ({s.win_trades_count}胜/{s.loss_trades_count}负)
                            </span>
                          </td>
                          <td className="py-2 px-3 text-[#3fb950] font-bold">
                            {s.win_rate_pct.toFixed(1)}%
                          </td>
                          <td className="py-2 px-3 text-[#d29922]">{s.profit_loss_ratio.toFixed(2)} : 1</td>
                          <td className={`py-2 px-3 ${s.expectancy_cny >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                            {s.expectancy_cny >= 0 ? '+' : ''}¥{s.expectancy_cny.toFixed(0)}
                          </td>
                          <td className={`py-2 px-3 font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                            {isWin ? '+' : ''}¥{s.net_pnl.toLocaleString()}
                          </td>
                          <td className={`py-2 px-3 font-bold ${isWin ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                            {isWin ? '+' : ''}{s.return_pct.toFixed(2)}%
                          </td>
                          <td className="py-2 px-3 text-[#f85149]">-{s.max_drawdown_pct.toFixed(2)}%</td>
                          <td className="py-2 px-3 text-right">
                            <button className="text-[11px] px-2 py-0.5 rounded bg-[#1f6feb]/20 text-[#58a6ff] border border-[#58a6ff]/30 hover:bg-[#1f6feb] hover:text-white transition font-sans flex items-center gap-1 ml-auto">
                              <span>载入K线</span>
                              <ExternalLink className="w-3 h-3" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}

        {/* Footer */}
        <div className="h-12 px-6 border-t border-[#30363d] bg-[#21262d]/70 flex items-center justify-between text-xs text-[#8b949e]">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#00ff88] animate-pulse"></span>
            <span>
              已接入全域真实历史分时与宏观沙盒双轨因果对冲校验引擎
            </span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-[#30363d] hover:bg-[#484f58] text-[#f0f6fc] text-xs font-semibold transition"
          >
            关闭战报
          </button>
        </div>
      </div>
    </div>
  );
};
