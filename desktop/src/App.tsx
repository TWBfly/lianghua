import React, { useState, useEffect } from 'react';
import { safeInvoke } from './utils/ipc';
import { TopNav } from './components/TopNav/TopNav';
import { TVChartContainer } from './components/Chart/TVChartContainer';
import { DecisionDrawer } from './components/Drawer/DecisionDrawer';
import { BacktestControlBar } from './components/Backtest/BacktestControlBar';
import { BacktestMetricsBar } from './components/Backtest/BacktestMetricsBar';
import { BacktestTradeTable } from './components/Backtest/BacktestTradeTable';
import { BacktestSidebar } from './components/Backtest/BacktestSidebar';
import { BacktestPortfolioModal } from './components/Backtest/BacktestPortfolioModal';
import { BacktestDualTrackModal } from './components/Backtest/BacktestDualTrackModal';
import { BacktestFactorZooModal } from './components/Backtest/BacktestFactorZooModal';
import {
  ChartMarker,
  BacktestRequest,
  BacktestResponse,
  BacktestTradeItem,
  PortfolioBacktestResponse,
  DualTrackEvaluationReport,
} from './types';

export const App: React.FC = () => {
  // Backtest Studio State (Default 15m, Default REAL 8000 Bars)
  const [backtestParams, setBacktestParams] = useState<BacktestRequest>({
    symbol: 'AU_IDX',
    strategy: 'taichong_elastoplastic_tensor',
    timeframe: '15m', // 默认严格为 15 分钟
    start_date: '2024-01-01',
    end_date: '2026-12-31',
    initial_capital: 1000000.0,
    backtest_mode: 'RESEARCH_PROXY',
    data_source: 'REAL', // 默认真实 8000 根实盘分时
    use_synthetic: false,
    fixed_lots: -1, // 默认名义价值对齐 (¥30万/笔 · 跨资产平权基准)
  });
  const [backtestLoading, setBacktestLoading] = useState<boolean>(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResponse | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<BacktestTradeItem | null>(null);
  const [selectedMarker, setSelectedMarker] = useState<ChartMarker | null>(null);
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  // Portfolio LLN Modal State
  const [showPortfolioModal, setShowPortfolioModal] = useState<boolean>(false);
  const [portfolioLoading, setPortfolioLoading] = useState<boolean>(false);
  const [portfolioData, setPortfolioData] = useState<PortfolioBacktestResponse | null>(null);

  // Dual-Track Benchmark 100-Point Audit Modal State
  const [showDualTrackModal, setShowDualTrackModal] = useState<boolean>(false);
  const [dualTrackLoading, setDualTrackLoading] = useState<boolean>(false);
  const [dualTrackData, setDualTrackData] = useState<DualTrackEvaluationReport | null>(null);

  // Factor Zoo & Autonomous Strategy Research Modal State
  const [showFactorZooModal, setShowFactorZooModal] = useState<boolean>(false);

  // Execute Backtest
  const handleRunBacktest = async (customParams?: Partial<BacktestRequest>) => {
    const params = { ...backtestParams, ...customParams };
    setBacktestLoading(true);
    try {
      const res: BacktestResponse = await safeInvoke('run_backtest_command', {
        req: params,
      });
      setBacktestResult(res);
      setSelectedMarker(null);
      setSelectedTrade(null);
      setFocusDate(null);
    } catch (err: any) {
      console.error('Backtest error:', err);
      alert('回测失败: ' + String(err));
    } finally {
      setBacktestLoading(false);
    }
  };

  // Execute All-Commodity Portfolio LLN Backtest
  const handleOpenPortfolioModal = async () => {
    setShowPortfolioModal(true);
    setPortfolioLoading(true);
    try {
      const res: PortfolioBacktestResponse = await safeInvoke('run_portfolio_backtest_command', {
        req: {
          strategy: backtestParams.strategy,
          timeframe: backtestParams.timeframe,
          initial_capital: 2000000.0,
          data_source: backtestParams.data_source,
          use_synthetic: backtestParams.use_synthetic,
          start_date: backtestParams.start_date,
          end_date: backtestParams.end_date,
        },
      });
      setPortfolioData(res);
    } catch (err: any) {
      console.error('Portfolio backtest error:', err);
      alert('全品种大数回测失败: ' + String(err));
    } finally {
      setPortfolioLoading(false);
    }
  };

  // Execute Dual-Track Benchmark 100-Point Audit
  const handleOpenDualTrackModal = async () => {
    setDualTrackData(null);
    setShowDualTrackModal(true);
    setDualTrackLoading(true);
    try {
      const res: DualTrackEvaluationReport = await safeInvoke('run_strategy_dual_track_evaluation_command', {
        req: {
          symbol: backtestParams.symbol,
          strategy: backtestParams.strategy,
          timeframe: backtestParams.timeframe,
          initial_capital: backtestParams.initial_capital || 1000000.0,
        },
      });
      setDualTrackData(res);
    } catch (err: any) {
      console.error('Dual-track evaluation error:', err);
      alert('双轨对冲综合体检失败: ' + String(err));
    } finally {
      setDualTrackLoading(false);
    }
  };

  // Initial backtest on startup
  useEffect(() => {
    handleRunBacktest();
  }, []);

  // Stock search select handler
  const handleSelectStock = (symbol: string) => {
    const newParams = { symbol, timeframe: '15m' };
    setBacktestParams((prev) => ({ ...prev, ...newParams }));
    handleRunBacktest(newParams);
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0d1117] text-[#f0f6fc] overflow-hidden">
      {/* Top Header */}
      <TopNav onSelectStock={handleSelectStock} />

      {/* Pure Strategy Backtest Studio (支持整页上下平滑滚动与各板块自适应展开) */}
      <div className="flex-1 flex flex-col min-h-0 overflow-y-auto overflow-x-hidden scroll-smooth">
        {/* Backtest Controls with dual data source & default 15m */}
        <BacktestControlBar
          requestParams={backtestParams}
          loading={backtestLoading}
          totalBarsCount={backtestResult?.metrics?.total_bars_count}
          onChangeParams={(p) => setBacktestParams((prev) => ({ ...prev, ...p }))}
          onRunBacktest={handleRunBacktest}
          onOpenPortfolioModal={handleOpenPortfolioModal}
          onOpenDualTrackModal={handleOpenDualTrackModal}
          onOpenFactorZooModal={() => setShowFactorZooModal(true)}
        />

        {/* Backtest Metrics 7 Cards */}
        <BacktestMetricsBar
          metrics={backtestResult?.metrics || null}
          timeframe={backtestResult?.timeframe || backtestParams.timeframe}
          symbol={backtestParams.symbol}
          strategyId={backtestParams.strategy}
          onSwitchStrategy={(stratId) => {
            const nextParams = { strategy: stratId };
            setBacktestParams((prev) => ({ ...prev, ...nextParams }));
            handleRunBacktest(nextParams);
          }}
          onSwitchSymbol={(sym) => {
            const nextParams = { symbol: sym, timeframe: '15m' };
            setBacktestParams((prev) => ({ ...prev, ...nextParams }));
            handleRunBacktest(nextParams);
          }}
        />

        {/* Main Backtest Workspace (图表与标的资产池专属高度，充裕清晰) */}
        <div className="h-[460px] min-h-[420px] flex-shrink-0 flex relative">
          {/* Left Backtest Preset Assets */}
          <BacktestSidebar
            currentSymbol={backtestParams.symbol}
            onSelectSymbol={(sym) => {
              const newParams = { symbol: sym, timeframe: '15m' };
              setBacktestParams((prev) => ({ ...prev, ...newParams }));
              handleRunBacktest(newParams);
            }}
          />

          {/* Center: TradingView Chart with Backtest Markers */}
          <main className="flex-1 flex flex-col min-w-0 h-full relative">
            <TVChartContainer
              symbol={backtestResult?.symbol || backtestParams.symbol}
              symbolName={backtestResult?.name || backtestParams.symbol}
              timeframe={backtestResult?.timeframe || backtestParams.timeframe}
              strategyId={backtestParams.strategy}
              dataSourceLabel={backtestResult?.metrics?.data_source_label}
              customBars={backtestResult?.bars}
              customMarkers={backtestResult?.markers}
              customTrendSeries={backtestResult?.trend_series}
              focusDate={focusDate}
              isDrawerOpen={isDrawerOpen}
              onToggleDrawer={() => setIsDrawerOpen((prev) => !prev)}
              onSelectMarker={(m) => {
                setSelectedMarker(m);
                if (m) {
                  setIsDrawerOpen(true);
                  const matchedTrade = backtestResult?.trades.find(
                    (t) => t.buy_date.startsWith(new Date(m.time * 1000).toISOString().substring(0, 10))
                  );
                  if (matchedTrade) setSelectedTrade(matchedTrade);
                }
              }}
            />
          </main>

          {/* Right: Decision Drawer */}
          {isDrawerOpen && (
            <DecisionDrawer
              selectedMarker={selectedMarker}
              selectedTrade={selectedTrade}
              currentSymbol={backtestParams.symbol}
              onClose={() => {
                setIsDrawerOpen(false);
                setSelectedMarker(null);
                setSelectedTrade(null);
              }}
            />
          )}
        </div>

        {/* Bottom: Backtest Trade Table */}
        <BacktestTradeTable
          trades={backtestResult?.trades || []}
          selectedTradeId={selectedTrade?.id}
          onSelectTrade={(trade) => {
            setSelectedTrade(trade);
            setSelectedMarker(null);
            setFocusDate(trade.buy_date);
            setIsDrawerOpen(true);
          }}
        />

        {/* All-Commodity Portfolio Matrix Modal */}
        {showPortfolioModal && (
          <BacktestPortfolioModal
            data={portfolioData}
            loading={portfolioLoading}
            onClose={() => setShowPortfolioModal(false)}
            onSelectSymbol={(sym) => {
              const newParams = { symbol: sym, timeframe: '15m' };
              setBacktestParams((prev) => ({ ...prev, ...newParams }));
              handleRunBacktest(newParams);
            }}
          />
        )}

        {/* Dual-Track Benchmark 100-Point Audit Modal */}
        {showDualTrackModal && (
          <BacktestDualTrackModal
            data={dualTrackData}
            loading={dualTrackLoading}
            onClose={() => setShowDualTrackModal(false)}
          />
        )}

        {/* Autonomous Factor & Strategy Research Modal (Factor Zoo) */}
        <BacktestFactorZooModal
          isOpen={showFactorZooModal}
          onClose={() => setShowFactorZooModal(false)}
          onApplyFactorToBacktest={(symbol, strategyId, factorId, formulaDsl) => {
            const newParams = {
              symbol,
              strategy: strategyId,
              timeframe: '15m',
              factor_id: factorId,
              formula_dsl: formulaDsl,
            };
            setBacktestParams((prev) => ({ ...prev, ...newParams }));
            handleRunBacktest(newParams);
          }}
        />
      </div>
    </div>
  );
};
