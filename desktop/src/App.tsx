import React, { useState, useEffect } from 'react';
import { safeInvoke } from './utils/ipc';
import { TopNav } from './components/TopNav/TopNav';
import { SquadSidebar } from './components/Sidebar/SquadSidebar';
import { TVChartContainer } from './components/Chart/TVChartContainer';
import { DecisionDrawer } from './components/Drawer/DecisionDrawer';
import { TradeBlotter } from './components/Blotter/TradeBlotter';
import { BacktestControlBar } from './components/Backtest/BacktestControlBar';
import { BacktestMetricsBar } from './components/Backtest/BacktestMetricsBar';
import { BacktestTradeTable } from './components/Backtest/BacktestTradeTable';
import { BacktestSidebar } from './components/Backtest/BacktestSidebar';
import { BacktestPortfolioModal } from './components/Backtest/BacktestPortfolioModal';
import { BacktestDualTrackModal } from './components/Backtest/BacktestDualTrackModal';
import {
  StrategyMeta,
  TradeRecord,
  ChartMarker,
  SystemStatus,
  BacktestRequest,
  BacktestResponse,
  BacktestTradeItem,
  PortfolioBacktestResponse,
  DualTrackEvaluationReport,
} from './types';

export const App: React.FC = () => {
  const [appMode, setAppMode] = useState<'LIVE' | 'BACKTEST'>('LIVE');

  // Live / Paper Trading State
  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);
  const [currentStrategyId, setCurrentStrategyId] = useState<string>('taichong_dual_squad');
  const [currentSymbol, setCurrentSymbol] = useState<string>('SN_IDX');
  const [currentSymbolName, setCurrentSymbolName] = useState<string>('沪锡');
  const [currentTimeframe, setCurrentTimeframe] = useState<string>('15m');
  const [selectedMarker, setSelectedMarker] = useState<ChartMarker | null>(null);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

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
  });
  const [backtestLoading, setBacktestLoading] = useState<boolean>(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResponse | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<BacktestTradeItem | null>(null);
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

  // 1. Initial load
  useEffect(() => {
    async function init() {
      try {
        const strats: StrategyMeta[] = await safeInvoke('get_strategy_registry');
        setStrategies(strats);
        if (strats.length > 0) {
          const defaultStrat = strats[1] || strats[0];
          setCurrentStrategyId(defaultStrat.id);
          setCurrentSymbol(defaultStrat.default_symbol);
          setCurrentTimeframe(defaultStrat.timeframe || '15m');
        }

        const status: SystemStatus = await safeInvoke('get_system_status');
        setSystemStatus(status);
      } catch (err) {
        console.error('Initialization error:', err);
      }
    }
    init();
  }, []);

  // 2. Fetch live trades when strategy changes
  useEffect(() => {
    async function loadTrades() {
      try {
        const tradeList: TradeRecord[] = await safeInvoke('get_strategy_trades', {
          strategyId: currentStrategyId,
          symbol: null,
        });
        setTrades(tradeList);
      } catch (err) {
        console.error('Failed to load trades:', err);
      }
    }
    if (appMode === 'LIVE') {
      loadTrades();
    }
  }, [currentStrategyId, appMode]);

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

  // Initial backtest when entering backtest mode
  useEffect(() => {
    if (appMode === 'BACKTEST' && !backtestResult) {
      handleRunBacktest();
    }
  }, [appMode]);

  // Handle timeframe switch from TopNav (only in Live mode)
  const handleTimeframeChange = (tf: string) => {
    setCurrentTimeframe(tf);
  };

  // Strategy switch handler
  const handleSelectStrategy = (strat: StrategyMeta) => {
    setCurrentStrategyId(strat.id);
    setCurrentSymbol(strat.default_symbol);
    setCurrentTimeframe(strat.timeframe || '15m');
    setSelectedMarker(null);
  };

  // Stock search select handler
  const handleSelectStock = (symbol: string, name: string) => {
    if (appMode === 'BACKTEST') {
      const newParams = { symbol, timeframe: '15m' };
      setBacktestParams((prev) => ({ ...prev, ...newParams }));
      handleRunBacktest(newParams);
    } else {
      setCurrentSymbol(symbol);
      setCurrentSymbolName(name);
      setCurrentTimeframe('15m');
      setCurrentStrategyId('ashare_causal_pool');
      setSelectedMarker(null);
    }
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0d1117] text-[#f0f6fc] overflow-hidden">
      {/* Top Header */}
      <TopNav
        appMode={appMode}
        systemStatus={systemStatus}
        currentTimeframe={currentTimeframe}
        onSelectAppMode={(mode) => {
          setAppMode(mode);
          setSelectedMarker(null);
        }}
        onSelectTimeframe={handleTimeframeChange}
        onSelectStock={handleSelectStock}
      />

      {/* Mode 1: Live / Paper Trading Monitor */}
      {appMode === 'LIVE' ? (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 flex min-h-0 relative">
            {/* Left: Squad & Symbol Selector */}
            <SquadSidebar
              strategies={strategies}
              currentStrategyId={currentStrategyId}
              currentSymbol={currentSymbol}
              onSelectStrategy={handleSelectStrategy}
              onSelectSymbol={(sym) => {
                setCurrentSymbol(sym);
                setSelectedMarker(null);
              }}
            />

            {/* Center: TradingView Chart */}
            <main className="flex-1 flex flex-col min-w-0 h-full relative">
              <TVChartContainer
                symbol={currentSymbol}
                symbolName={currentSymbolName}
                timeframe={currentTimeframe}
                strategyId={currentStrategyId}
                isDrawerOpen={isDrawerOpen}
                onToggleDrawer={() => setIsDrawerOpen((prev) => !prev)}
                onSelectMarker={(m) => {
                  setSelectedMarker(m);
                  if (m) setIsDrawerOpen(true);
                }}
              />
            </main>

            {/* Right: Strategy Decision Drawer */}
            {isDrawerOpen && (
              <DecisionDrawer
                selectedMarker={selectedMarker}
                currentSymbol={currentSymbol}
                onClose={() => {
                  setIsDrawerOpen(false);
                  setSelectedMarker(null);
                }}
              />
            )}
          </div>

          {/* Bottom: Trade Blotter */}
          <TradeBlotter trades={trades} currentSymbol={currentSymbol} />
        </div>
      ) : (
        /* Mode 2: Strategy Backtest Studio */
        <div className="flex-1 flex flex-col min-h-0">
          {/* Backtest Controls with dual data source & default 15m */}
          <BacktestControlBar
            requestParams={backtestParams}
            loading={backtestLoading}
            totalBarsCount={backtestResult?.metrics?.total_bars_count}
            onChangeParams={(p) => setBacktestParams((prev) => ({ ...prev, ...p }))}
            onRunBacktest={handleRunBacktest}
            onOpenPortfolioModal={handleOpenPortfolioModal}
            onOpenDualTrackModal={handleOpenDualTrackModal}
          />

          {/* Backtest Metrics 7 Cards */}
          <BacktestMetricsBar metrics={backtestResult?.metrics || null} timeframe={backtestResult?.timeframe || backtestParams.timeframe} />

          {/* Main Backtest Workspace */}
          <div className="flex-1 flex min-h-0 relative">
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
        </div>
      )}
    </div>
  );
};
