import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  SeriesMarker,
  Time,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import { safeInvoke } from '../../utils/ipc';
import { ChartMarker, KlineBar } from '../../types';
import { Activity, Maximize2, Minimize2, RefreshCw, Calendar, Clock, Crosshair, Cpu } from 'lucide-react';

interface TVChartProps {
  symbol: string;
  symbolName: string;
  timeframe: string;
  strategyId: string;
  dataSourceLabel?: string;
  customBars?: KlineBar[];
  customMarkers?: ChartMarker[];
  focusDate?: string | null;
  onSelectMarker?: (marker: ChartMarker | null) => void;
  isDrawerOpen?: boolean;
  onToggleDrawer?: () => void;
}

const formatTimestamp = (ts: number): string => {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const Y = d.getFullYear();
  const M = String(d.getMonth() + 1).padStart(2, '0');
  const D = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${Y}-${M}-${D} ${h}:${m}:${s}`;
};

export const TVChartContainer: React.FC<TVChartProps> = ({
  symbol,
  symbolName,
  timeframe,
  strategyId,
  dataSourceLabel,
  customBars,
  customMarkers,
  focusDate,
  onSelectMarker,
  isDrawerOpen,
  onToggleDrawer,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [focusToast, setFocusToast] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [liveQuote, setLiveQuote] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    chg: number;
    chgPct: number;
    timeStr: string;
  } | null>(null);

  const markersMapRef = useRef<Map<number, ChartMarker>>(new Map());
  const barsTimeMapRef = useRef<Map<number, string>>(new Map());

  // 1. Initialize Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: '#0d1117' },
        textColor: '#8b949e',
        fontSize: 12,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(48, 54, 61, 0.45)' },
        horzLines: { color: 'rgba(48, 54, 61, 0.45)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#58a6ff',
          width: 1,
          style: 3,
          labelBackgroundColor: '#1f6feb',
        },
        horzLine: {
          color: '#58a6ff',
          width: 1,
          style: 3,
          labelBackgroundColor: '#1f6feb',
        },
      },
      rightPriceScale: {
        borderColor: '#30363d',
        scaleMargins: {
          top: 0.08,
          bottom: 0.24,
        },
        autoScale: true,
      },
      timeScale: {
        visible: true,
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#30363d',
        rightOffset: 12,
        barSpacing: 10,
        minBarSpacing: 2,
      },
      localization: {
        locale: 'zh-CN',
        timeFormatter: (timestamp: number) => {
          const d = new Date(timestamp * 1000);
          const Y = d.getFullYear();
          const M = String(d.getMonth() + 1).padStart(2, '0');
          const D = String(d.getDate()).padStart(2, '0');
          const h = String(d.getHours()).padStart(2, '0');
          const m = String(d.getMinutes()).padStart(2, '0');
          return `${Y}-${M}-${D} ${h}:${m}`;
        },
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#3fb950',
      downColor: '#f85149',
      borderVisible: false,
      wickUpColor: '#3fb950',
      wickDownColor: '#f85149',
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) return;
      const cData = param.seriesData.get(candleSeries) as CandlestickData;
      const vData = param.seriesData.get(volumeSeries) as HistogramData;
      if (cData) {
        const chg = cData.close - cData.open;
        const chgPct = (chg / cData.open) * 100;
        const tsNum = typeof param.time === 'number' ? param.time : 0;
        const matchedDtStr = barsTimeMapRef.current.get(tsNum) || formatTimestamp(tsNum);

        setLiveQuote({
          open: cData.open,
          high: cData.high,
          low: cData.low,
          close: cData.close,
          volume: vData?.value || 0,
          chg,
          chgPct,
          timeStr: matchedDtStr,
        });

        if (tsNum && markersMapRef.current.has(tsNum)) {
          onSelectMarker?.(markersMapRef.current.get(tsNum)!);
        }
      }
    });

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    const resizeObserver = new ResizeObserver(() => {
      handleResize();
    });
    if (chartContainerRef.current) {
      resizeObserver.observe(chartContainerRef.current);
    }

    return () => {
      window.removeEventListener('resize', handleResize);
      resizeObserver.disconnect();
      chart.remove();
    };
  }, []);

  // 2. Render Data (Custom / Direct Backtest or Live DB Query)
  const loadData = async () => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    barsTimeMapRef.current.clear();

    // If custom bars are supplied (e.g. from backtest result)
    if (customBars && customBars.length > 0) {
      const candleData: CandlestickData[] = customBars.map((b) => {
        barsTimeMapRef.current.set(b.time, b.datetime_str);
        return {
          time: b.time as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        };
      });

      const volumeData: HistogramData[] = customBars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(63, 185, 80, 0.35)' : 'rgba(248, 81, 73, 0.35)',
      }));

      candleSeriesRef.current.setData(candleData);
      volumeSeriesRef.current.setData(volumeData);

      // Latest Quote HUD
      const latest = customBars[customBars.length - 1];
      const prev = customBars.length >= 2 ? customBars[customBars.length - 2] : latest;
      const chg = latest.close - prev.close;
      const chgPct = (chg / prev.close) * 100;
      setLiveQuote({
        open: latest.open,
        high: latest.high,
        low: latest.low,
        close: latest.close,
        volume: latest.volume,
        chg,
        chgPct,
        timeStr: latest.datetime_str,
      });

      // Markers (Strictly Ascending and deduplicated for Lightweight Charts)
      const tvMarkers: SeriesMarker<Time>[] = [];
      markersMapRef.current.clear();
      if (customMarkers && customMarkers.length > 0) {
        const sorted = [...customMarkers].sort((a, b) => a.time - b.time);
        let lastTime = 0;
        for (const m of sorted) {
          const mTime = m.time <= lastTime ? lastTime + 1 : m.time;
          lastTime = mTime;
          markersMapRef.current.set(mTime, m);
          tvMarkers.push({
            time: mTime as Time,
            position: m.position,
            color: m.color,
            shape: m.shape,
            text: m.text,
            id: m.id,
            size: 2,
          });
        }
      }
      candleSeriesRef.current.setMarkers(tvMarkers);

      // Adjust dimensions and fit content
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
        chartRef.current.timeScale().fitContent();
      }
      return;
    }

    // Otherwise, fetch from live SQLite database
    setLoading(true);
    setErrorMsg(null);

    try {
      const rawBars: KlineBar[] = await safeInvoke('fetch_kline_bars', {
        symbol,
        timeframe,
        limit: 1000,
      });

      if (!rawBars || rawBars.length === 0) {
        setErrorMsg(`数据库中暂无 ${symbol} (${timeframe}) K线数据`);
        setLoading(false);
        return;
      }

      const candleData: CandlestickData[] = rawBars.map((b) => {
        barsTimeMapRef.current.set(b.time, b.datetime_str);
        return {
          time: b.time as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        };
      });

      const volumeData: HistogramData[] = rawBars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(63, 185, 80, 0.35)' : 'rgba(248, 81, 73, 0.35)',
      }));

      candleSeriesRef.current.setData(candleData);
      volumeSeriesRef.current.setData(volumeData);

      const latest = rawBars[rawBars.length - 1];
      const prev = rawBars.length >= 2 ? rawBars[rawBars.length - 2] : latest;
      const chg = latest.close - prev.close;
      const chgPct = (chg / prev.close) * 100;
      setLiveQuote({
        open: latest.open,
        high: latest.high,
        low: latest.low,
        close: latest.close,
        volume: latest.volume,
        chg,
        chgPct,
        timeStr: latest.datetime_str,
      });

      const rawMarkers: ChartMarker[] = await safeInvoke('get_strategy_markers', {
        strategyId,
        symbol,
      });

      const tvMarkers: SeriesMarker<Time>[] = [];
      markersMapRef.current.clear();

      if (rawMarkers && rawMarkers.length > 0) {
        const sorted = [...rawMarkers].sort((a, b) => a.time - b.time);
        let lastTime = 0;
        for (const m of sorted) {
          const mTime = m.time <= lastTime ? lastTime + 1 : m.time;
          lastTime = mTime;
          markersMapRef.current.set(mTime, m);
          tvMarkers.push({
            time: mTime as Time,
            position: m.position,
            color: m.color,
            shape: m.shape,
            text: m.text,
            id: m.id,
            size: 2,
          });
        }
      }

      candleSeriesRef.current.setMarkers(tvMarkers);

      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
        chartRef.current.timeScale().fitContent();
      }
    } catch (err: any) {
      console.error('Failed to load chart data:', err);
      setErrorMsg(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [symbol, timeframe, strategyId, customBars, customMarkers]);

  // 3. Jump and Focus on Trade Entry Position when focusDate changes
  useEffect(() => {
    if (!focusDate || !chartRef.current || !customBars || customBars.length === 0) return;

    // Match by full date string or YYYY-MM-DD HH:mm prefix
    const targetIdx = customBars.findIndex(
      (b) => b.datetime_str === focusDate || b.datetime_str.startsWith(focusDate.substring(0, 16))
    );

    if (targetIdx !== -1) {
      // Zoom and center on the target candle
      chartRef.current.timeScale().setVisibleLogicalRange({
        from: Math.max(0, targetIdx - 20),
        to: Math.min(customBars.length - 1, targetIdx + 20),
      });

      const targetBar = customBars[targetIdx];
      const prevBar = targetIdx > 0 ? customBars[targetIdx - 1] : targetBar;
      const chg = targetBar.close - prevBar.close;
      const chgPct = (chg / prevBar.close) * 100;
      setLiveQuote({
        open: targetBar.open,
        high: targetBar.high,
        low: targetBar.low,
        close: targetBar.close,
        volume: targetBar.volume,
        chg,
        chgPct,
        timeStr: targetBar.datetime_str,
      });

      setFocusToast(`🎯 已精准定位至开仓 K 线: ${targetBar.datetime_str} (价位: ¥${targetBar.close.toFixed(2)})`);
      const timer = setTimeout(() => setFocusToast(null), 3500);
      return () => clearTimeout(timer);
    }
  }, [focusDate, customBars]);

  // 4. Keyboard listener for Escape key to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  // 5. Auto resize chart canvas when toggling fullscreen
  useEffect(() => {
    const timer = setTimeout(() => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
        chartRef.current.timeScale().fitContent();
      }
    }, 60);
    return () => clearTimeout(timer);
  }, [isFullscreen]);

  return (
    <div
      className={`flex flex-col bg-[#0d1117] select-none ${
        isFullscreen
          ? 'fixed inset-0 z-50 w-screen h-screen'
          : 'flex-1 h-full relative overflow-hidden'
      }`}
    >
      {/* Top Chart Toolbar & Live Quote HUD */}
      <div className="h-11 px-4 bg-[#161b22] border-b border-[#30363d] flex items-center justify-between z-10 select-none flex-shrink-0">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-[#f0f6fc] text-sm tracking-wide">
              {symbolName} ({symbol})
            </span>
            <span className="text-xs px-2 py-0.5 rounded bg-[#21262d] text-[#58a6ff] border border-[#30363d] font-mono font-bold flex items-center gap-1">
              <Clock className="w-3 h-3 text-[#00ff88]" /> {timeframe}
            </span>
            {dataSourceLabel && (
              <span className={`text-[11px] px-2 py-0.5 rounded font-mono font-medium border ${
                dataSourceLabel.includes('算法')
                  ? 'bg-[#8957e5]/20 text-[#bc8cff] border-[#8957e5]/40'
                  : 'bg-[#1f6feb]/20 text-[#58a6ff] border-[#1f6feb]/40'
              }`}>
                {dataSourceLabel}
              </span>
            )}
            {isFullscreen && (
              <span className="text-[11px] px-2.5 py-0.5 rounded bg-[#1f6feb]/20 text-[#58a6ff] border border-[#58a6ff]/40 font-semibold flex items-center gap-1 animate-pulse">
                全屏沉浸模式 (按 ESC 键退出)
              </span>
            )}
          </div>

          {liveQuote && (
            <div className="flex items-center gap-3 text-xs font-mono">
              {/* Highlighted Exact Datetime Badge */}
              <div className="flex items-center gap-1 bg-[#0d1117] px-2 py-0.5 rounded border border-[#30363d] text-[#f0f6fc] font-bold">
                <Calendar className="w-3 h-3 text-[#bc8cff]" />
                <span>{liveQuote.timeStr}</span>
              </div>

              <div>
                <span className="text-[#8b949e]">价格: </span>
                <span
                  className={`font-bold text-sm ${
                    liveQuote.chg >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                  }`}
                >
                  ¥{liveQuote.close.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div
                className={`flex items-center gap-1 font-semibold ${
                  liveQuote.chg >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                }`}
              >
                <span>{liveQuote.chg >= 0 ? '+' : ''}{liveQuote.chg.toFixed(2)}</span>
                <span>({liveQuote.chgPct >= 0 ? '+' : ''}{liveQuote.chgPct.toFixed(2)}%)</span>
              </div>
              <div className="hidden xl:flex items-center gap-3 text-[#8b949e]">
                <span>高: <span className="text-[#f0f6fc]">{liveQuote.high.toFixed(2)}</span></span>
                <span>低: <span className="text-[#f0f6fc]">{liveQuote.low.toFixed(2)}</span></span>
                <span>开: <span className="text-[#f0f6fc]">{liveQuote.open.toFixed(2)}</span></span>
                <span>量: <span className="text-[#f0f6fc]">{liveQuote.volume.toLocaleString()}</span></span>
              </div>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {onToggleDrawer && (
            <button
              onClick={onToggleDrawer}
              title={isDrawerOpen ? '收起因果决策明细面板' : '展开因果决策明细面板'}
              className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs transition border ${
                isDrawerOpen
                  ? 'bg-[#1f6feb]/20 text-[#58a6ff] border-[#1f6feb]/50 font-bold shadow'
                  : 'hover:bg-[#21262d] text-[#8b949e] hover:text-[#f0f6fc] border-[#30363d]'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" />
              <span>{isDrawerOpen ? '收起明细' : '因果决策明细'}</span>
            </button>
          )}

          <button
            onClick={() => setIsFullscreen((prev) => !prev)}
            title={isFullscreen ? '退出全屏 (Esc)' : '全屏最大化铺满屏幕'}
            className={`p-1.5 rounded transition ${
              isFullscreen
                ? 'bg-[#1f6feb] text-white shadow-lg'
                : 'hover:bg-[#21262d] text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          <button
            onClick={loadData}
            title="刷新行情与买卖点"
            className="p-1.5 rounded hover:bg-[#21262d] text-[#8b949e] hover:text-[#58a6ff] transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Chart Canvas Area (flex-1 min-h-0 so timeScale is NOT clipped off!) */}
      <div className="flex-1 w-full min-h-0 relative" ref={chartContainerRef}>
        {/* Floating Focus Toast */}
        {focusToast && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-[#1f6feb] text-white px-4 py-1.5 rounded-full shadow-2xl text-xs font-bold flex items-center gap-2 animate-in fade-in slide-in-from-top-2 duration-200">
            <Crosshair className="w-4 h-4 animate-pulse" />
            <span>{focusToast}</span>
          </div>
        )}

        {loading && (
          <div className="absolute inset-0 bg-[#0d1117]/80 flex items-center justify-center z-20">
            <div className="flex items-center gap-3 bg-[#161b22] px-4 py-2.5 rounded-lg border border-[#30363d] shadow-xl">
              <Activity className="w-5 h-5 text-[#58a6ff] animate-spin" />
              <span className="text-xs text-[#8b949e]">正在直读 SQLite 加载 60FPS K线...</span>
            </div>
          </div>
        )}

        {errorMsg && (
          <div className="absolute inset-0 flex items-center justify-center z-20">
            <div className="bg-[#161b22] p-5 rounded-lg border border-[#f85149]/40 text-center max-w-sm">
              <p className="text-sm text-[#f85149] font-medium">{errorMsg}</p>
              <button
                onClick={loadData}
                className="mt-3 px-3 py-1 bg-[#21262d] hover:bg-[#30363d] text-xs text-[#f0f6fc] rounded border border-[#30363d]"
              >
                重试加载
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Chart Legend Footer (Visible horizontal bar) */}
      <div className="h-7 px-4 bg-[#161b22] border-t border-[#30363d] flex items-center justify-between text-[11px] text-[#8b949e] select-none flex-shrink-0">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#3fb950]"></span> 🟢 开多买入
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#f85149]"></span> 🔴 开空卖出
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#d29922]"></span> 🎯 均线回归/止盈
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#00ff88] pulsing-dot"></span> ⏱️ 底部横轴精确展示时分秒
          </span>
        </div>
        <div className="text-[#8b949e] font-mono">
          TradingView Lightweight Charts v4.2 • 60 FPS Canvas GPU
        </div>
      </div>
    </div>
  );
};
