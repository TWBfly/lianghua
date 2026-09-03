import React, { useState, useEffect } from 'react';
import { safeInvoke } from '../../utils/ipc';
import { FactorZooItem, ContinuousResearchStatus } from '../../types';
import {
  Dna,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  X,
  ShieldAlert,
  Copy,
  Check,
  Search,
  ArrowUpRight,
  BarChart3,
  Database,
  Layers,
  Award,
  RefreshCw,
  Clock,
  Square,
  Flame,
} from 'lucide-react';

interface BacktestFactorZooModalProps {
  isOpen: boolean;
  onClose: () => void;
  onApplyFactorToBacktest: (symbol: string, strategyId: string) => void;
}

export const BacktestFactorZooModal: React.FC<BacktestFactorZooModalProps> = ({
  isOpen,
  onClose,
  onApplyFactorToBacktest,
}) => {
  const [factors, setFactors] = useState<FactorZooItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [researching, setResearching] = useState<boolean>(false);
  const [researchStatus, setResearchStatus] = useState<string | null>(null);
  const [latestFactor, setLatestFactor] = useState<FactorZooItem | null>(null);
  const [lastRunTime, setLastRunTime] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [familyFilter, setFamilyFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const [continuousStatus, setContinuousStatus] = useState<ContinuousResearchStatus | null>(null);
  const [isStartingContinuous, setIsStartingContinuous] = useState<boolean>(false);

  const fetchFactors = async (status?: string) => {
    try {
      setLoading(true);
      const res: FactorZooItem[] = await safeInvoke('get_factor_zoo_command', {
        status: status === 'ALL' ? null : status,
      });
      setFactors(res || []);
    } catch (err) {
      console.error('Failed to fetch factor zoo:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchFactors(statusFilter);
    }
  }, [isOpen, statusFilter]);

  // Polling continuous research status & auto-refreshing factors
  useEffect(() => {
    if (!isOpen) return;

    let timerId: any = null;
    const checkStatus = async () => {
      try {
        const st: ContinuousResearchStatus = await safeInvoke('get_continuous_research_status_command');
        setContinuousStatus(st);
        if (st && st.is_running) {
          // If continuous miner is running, periodically refresh factors list
          const res: FactorZooItem[] = await safeInvoke('get_factor_zoo_command', {
            status: statusFilter === 'ALL' ? null : statusFilter,
          });
          if (res && res.length > 0) {
            setFactors(res);
          }
        }
      } catch (e) {
        console.error('Failed to check continuous miner status:', e);
      }
    };

    checkStatus();
    timerId = setInterval(checkStatus, 3000);
    return () => {
      if (timerId) clearInterval(timerId);
    };
  }, [isOpen, statusFilter]);

  const handleStartContinuous = async (durationSecs: number = 3600) => {
    try {
      setIsStartingContinuous(true);
      const st: ContinuousResearchStatus = await safeInvoke('start_continuous_research_command', {
        durationSeconds: durationSecs,
      });
      setContinuousStatus(st);
      setResearchStatus(
        `🚀 1小时连续自动因子研究任务已启动！后台正持续对各大商品期货执行大数矩阵回测、3x压力测试与入库...`
      );
    } catch (e: any) {
      console.error('Failed to start continuous research:', e);
      setResearchStatus(`❌ 启动连续研究失败: ${e?.message || e}`);
    } finally {
      setIsStartingContinuous(false);
    }
  };

  const handleStopContinuous = async () => {
    try {
      await safeInvoke('stop_continuous_research_command');
      setResearchStatus('🛑 已发送停止信号，正在平稳退出连续研究任务...');
      setTimeout(async () => {
        const st: ContinuousResearchStatus = await safeInvoke('get_continuous_research_status_command');
        setContinuousStatus(st);
        fetchFactors(statusFilter);
      }, 1000);
    } catch (e: any) {
      console.error('Failed to stop continuous research:', e);
    }
  };

  const formatSeconds = (secs?: number | null) => {
    if (!secs || secs <= 0) return '00:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const handleRunResearch = async () => {
    try {
      setResearching(true);
      setResearchStatus(
        '⚡ 正在调用 Python 确定性因果内核，对沪金 (AU)、沪银 (AG)、沪铜 (CU)、原油 (SC)、螺纹 (RB)、豆粕 (M) 等 6 大期货主力合约执行全样本矩阵回测与 3x 极端成本压力测试...'
      );
      const res: FactorZooItem[] = await safeInvoke('run_autonomous_factor_research_command');
      if (res && res.length > 0) {
        // Detect newly discovered factor
        const newlyAdded = res.find((f) => !factors.some((prev) => prev.factor_id === f.factor_id));
        if (newlyAdded) {
          setLatestFactor(newlyAdded);
        }
        setFactors(res);
      }
      const now = new Date();
      const timeStr = now.toTimeString().split(' ')[0];
      setLastRunTime(timeStr);
      setResearchStatus(
        `✅ 全品种因子挖掘完成！成功在本地 SQLite (ashare_quant.db) 更新因子库（共计 ${res?.length || factors.length} 个因子），100分稳健度体检指标已刷新！`
      );
    } catch (err: any) {
      console.error('Failed to run autonomous research:', err);
      setResearchStatus(`❌ 挖掘过程中出现异常: ${err?.message || err}`);
    } finally {
      setResearching(false);
    }
  };

  const handleCopyFormula = (id: string, formula: string) => {
    navigator.clipboard.writeText(formula);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (!isOpen) return null;

  // Compute metrics
  const totalCount = factors.length;
  const excellentCount = factors.filter((f) => f.status === 'EXCELLENT').length;
  const candidateCount = factors.filter((f) => f.status === 'CANDIDATE').length;
  const graveyardCount = factors.filter((f) => f.status === 'GRAVEYARD').length;
  const avgScore = totalCount > 0 ? (factors.reduce((acc, f) => acc + f.total_score, 0) / totalCount).toFixed(1) : '0';
  const avgIC = totalCount > 0 ? (factors.reduce((acc, f) => acc + f.rank_ic, 0) / totalCount).toFixed(4) : '0';

  // Distinct families
  const families = ['ALL', ...Array.from(new Set(factors.map((f) => f.family)))];

  // Filtering
  const filteredFactors = factors.filter((f) => {
    const matchStatus = statusFilter === 'ALL' || f.status === statusFilter;
    const matchFamily = familyFilter === 'ALL' || f.family === familyFilter;
    const matchSearch =
      searchQuery.trim() === '' ||
      f.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.factor_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.hypothesis.toLowerCase().includes(searchQuery.toLowerCase());
    return matchStatus && matchFamily && matchSearch;
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 sm:p-6 overflow-hidden animate-in fade-in duration-200">
      <div className="relative w-full max-w-6xl max-h-[92vh] flex flex-col bg-[#0d1117] border border-[#30363d] rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#30363d] bg-[#161b22]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#58a6ff]/10 border border-[#58a6ff]/30 flex items-center justify-center text-[#58a6ff]">
              <Dna className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-[#f0f6fc]">
                  🧬 因子与策略自动研究实验室 (Autonomous Factor Zoo)
                </h2>
                <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-[#8957e5]/20 text-[#bc8cff] border border-[#8957e5]/40">
                  《研究策略.md》第一性原理落地
                </span>
              </div>
              <p className="text-xs text-[#8b949e] mt-0.5">
                8大 Alpha 家族与正交复合体系 • 涵盖各大期货交易所 24 大主流主力合约池 • 3x 极端滑点规费压力测试 • 100分稳健度体检
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {lastRunTime && (
              <span className="text-[11px] font-mono text-[#8b949e] hidden sm:inline-block bg-[#0d1117] px-2 py-1 rounded border border-[#30363d]">
                上次挖掘: {lastRunTime}
              </span>
            )}

            {/* 1-Hour Continuous Research Toggle */}
            {continuousStatus?.is_running ? (
              <button
                onClick={handleStopContinuous}
                className="px-3.5 py-1.5 rounded-lg bg-[#f85149]/20 hover:bg-[#f85149]/30 border border-[#f85149]/60 text-[#f85149] text-xs font-bold flex items-center gap-1.5 transition animate-pulse shadow"
                title="点击停止连续研究任务"
              >
                <Square className="w-3.5 h-3.5 fill-current" />
                <span>⏹️ 停止自动研究 ({formatSeconds(continuousStatus.remaining_seconds)})</span>
              </button>
            ) : (
              <button
                onClick={() => handleStartContinuous(3600)}
                disabled={isStartingContinuous || researching}
                className="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-[#8957e5] to-[#6f42c1] hover:from-[#9d6ff5] hover:to-[#8250df] text-white text-xs font-bold flex items-center gap-1.5 transition shadow disabled:opacity-50"
                title="启动 1 小时连续自动研究模式，机器自主进行参数变异、大数回测、3x摩擦检验与持久化入库"
              >
                <Clock className="w-3.5 h-3.5" />
                <span>⏱️ 自动研究 1 小时 (60m)</span>
              </button>
            )}

            <button
              onClick={handleRunResearch}
              disabled={researching || continuousStatus?.is_running}
              className="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-[#238636] to-[#2ea043] hover:from-[#2ea043] hover:to-[#3fb950] text-white text-xs font-bold flex items-center gap-1.5 transition shadow disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${researching ? 'animate-spin' : ''}`} />
              <span>{researching ? '单次全品种挖掘中...' : '🚀 启动单次全品种挖掘'}</span>
            </button>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[#8b949e] hover:text-[#f0f6fc] hover:bg-[#30363d] transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Continuous 1-Hour Research Active Progress Ribbon */}
        {continuousStatus?.is_running && (
          <div className="px-6 py-2.5 bg-gradient-to-r from-[#8957e5]/25 via-[#161b22] to-[#238636]/25 border-b border-[#8957e5]/50 flex flex-wrap items-center justify-between gap-3 animate-in fade-in">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 text-xs font-bold text-[#bc8cff]">
                <Flame className="w-4 h-4 text-[#d29922] animate-bounce" />
                <span>🔥 1小时自动化量化科研任务进行中:</span>
              </div>
              <span className="text-xs font-mono text-[#f0f6fc]">
                剩余倒计时: <b className="text-[#58a6ff]">{formatSeconds(continuousStatus.remaining_seconds)}</b>
              </span>
              <span className="text-xs font-mono text-[#8b949e]">
                (已运行 {formatSeconds(continuousStatus.elapsed_seconds)})
              </span>
            </div>

            <div className="flex items-center gap-4 text-xs">
              <span className="text-[#c9d1d9]">
                本轮已探索并验证: <b className="text-[#3fb950] font-mono">{continuousStatus.total_evaluated_this_run ?? 0} 个新因子</b>
              </span>
              {continuousStatus.latest_factor_id && (
                <span className="text-[#8b949e] font-mono hidden md:inline">
                  最新探索: <b className="text-[#79c0ff]">[{continuousStatus.latest_factor_id}] {continuousStatus.latest_factor_name}</b> ({continuousStatus.latest_factor_score ?? 0}分)
                </span>
              )}
            </div>
          </div>
        )}

        {/* Real-time Research Status Banner */}
        {researchStatus && (
          <div
            className={`px-6 py-2.5 flex items-center justify-between text-xs font-semibold border-b transition ${
              researching
                ? 'bg-[#1f6feb]/15 border-[#1f6feb]/40 text-[#58a6ff]'
                : researchStatus.startsWith('❌')
                ? 'bg-[#f85149]/15 border-[#f85149]/40 text-[#f85149]'
                : 'bg-[#238636]/15 border-[#238636]/40 text-[#3fb950]'
            }`}
          >
            <div className="flex items-center gap-2">
              {researching ? (
                <RefreshCw className="w-4 h-4 animate-spin shrink-0 text-[#58a6ff]" />
              ) : researchStatus.startsWith('❌') ? (
                <AlertTriangle className="w-4 h-4 shrink-0 text-[#f85149]" />
              ) : (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-[#3fb950]" />
              )}
              <span>{researchStatus}</span>
            </div>
            <button
              onClick={() => setResearchStatus(null)}
              className="text-[#8b949e] hover:text-[#f0f6fc] text-xs p-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Latest Discovered Factor Spotlight */}
        {latestFactor && (
          <div className="px-6 py-2.5 bg-gradient-to-r from-[#1f6feb]/20 via-[#161b22] to-[#8957e5]/20 border-b border-[#30363d] flex flex-wrap items-center justify-between gap-3 animate-in fade-in">
            <div className="flex items-center gap-2.5">
              <span className="px-2 py-0.5 rounded bg-[#f0883e]/20 text-[#f0883e] border border-[#f0883e]/40 text-[10px] font-bold uppercase tracking-wide flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-[#f0883e]" /> 刚刚挖掘验证
              </span>
              <span className="font-mono text-xs text-[#58a6ff] font-bold">[{latestFactor.factor_id}]</span>
              <span className="text-xs text-[#f0f6fc] font-bold">{latestFactor.name}</span>
              <span className="text-xs text-[#8b949e]">({latestFactor.family})</span>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-[#c9d1d9]">
                综合得分: <b className="text-[#58a6ff]">{latestFactor.total_score}分 ({latestFactor.grade}级)</b>
              </span>
              <span
                className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                  latestFactor.status === 'EXCELLENT'
                    ? 'bg-[#238636]/20 text-[#3fb950] border border-[#238636]/50'
                    : latestFactor.status === 'CANDIDATE'
                    ? 'bg-[#d29922]/20 text-[#d29922] border border-[#d29922]/50'
                    : 'bg-[#f85149]/20 text-[#f85149] border border-[#f85149]/50'
                }`}
              >
                {latestFactor.status === 'EXCELLENT'
                  ? '👑 晋级优秀因子库'
                  : latestFactor.status === 'CANDIDATE'
                  ? '🔬 列入候选观察池'
                  : '🪦 门禁否决入墓'}
              </span>
              {latestFactor.fail_reason && (
                <span className="text-[11px] text-[#f85149] italic max-w-xs truncate" title={latestFactor.fail_reason}>
                  原因: {latestFactor.fail_reason}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Top KPI Metrics Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-6 gap-3 px-6 py-3.5 bg-[#161b22]/50 border-b border-[#30363d]">
          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#30363d]">
            <span className="text-[11px] text-[#8b949e] flex items-center gap-1">
              <Database className="w-3 h-3 text-[#58a6ff]" /> 已研因子总数
            </span>
            <div className="text-lg font-mono font-bold text-[#f0f6fc] mt-0.5">{totalCount} 个</div>
          </div>

          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#238636]/40">
            <span className="text-[11px] text-[#3fb950] flex items-center gap-1 font-bold">
              <CheckCircle2 className="w-3 h-3 text-[#3fb950]" /> 👑 优秀因子库
            </span>
            <div className="text-lg font-mono font-bold text-[#3fb950] mt-0.5">{excellentCount} 个</div>
          </div>

          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#d29922]/40">
            <span className="text-[11px] text-[#d29922] flex items-center gap-1 font-bold">
              <Sparkles className="w-3 h-3 text-[#d29922]" /> 🔬 候选观察池
            </span>
            <div className="text-lg font-mono font-bold text-[#d29922] mt-0.5">{candidateCount} 个</div>
          </div>

          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#f85149]/40">
            <span className="text-[11px] text-[#f85149] flex items-center gap-1 font-bold">
              <ShieldAlert className="w-3 h-3 text-[#f85149]" /> 🪦 淘汰墓地
            </span>
            <div className="text-lg font-mono font-bold text-[#f85149] mt-0.5">{graveyardCount} 个</div>
          </div>

          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#30363d]">
            <span className="text-[11px] text-[#8b949e] flex items-center gap-1">
              <Award className="w-3 h-3 text-[#bc8cff]" /> 平均体检总分
            </span>
            <div className="text-lg font-mono font-bold text-[#bc8cff] mt-0.5">{avgScore} 分</div>
          </div>

          <div className="bg-[#0d1117] p-2.5 rounded-xl border border-[#30363d]">
            <span className="text-[11px] text-[#8b949e] flex items-center gap-1">
              <BarChart3 className="w-3 h-3 text-[#79c0ff]" /> 平均 Rank IC
            </span>
            <div className="text-lg font-mono font-bold text-[#79c0ff] mt-0.5">{avgIC}</div>
          </div>
        </div>

        {/* Filter Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 border-b border-[#30363d] bg-[#0d1117]">
          {/* Status Tabs */}
          <div className="flex items-center gap-1.5 bg-[#161b22] p-1 rounded-xl border border-[#30363d]">
            {[
              { id: 'ALL', label: '全部' },
              { id: 'EXCELLENT', label: '👑 优秀因子库' },
              { id: 'CANDIDATE', label: '🔬 候选池' },
              { id: 'GRAVEYARD', label: '🪦 淘汰墓地' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`px-3 py-1 text-xs font-bold rounded-lg transition ${
                  statusFilter === tab.id
                    ? 'bg-[#58a6ff]/20 text-[#58a6ff] border border-[#58a6ff]/40 shadow-sm'
                    : 'text-[#8b949e] hover:text-[#f0f6fc] hover:bg-[#21262d]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Family & Search */}
          <div className="flex items-center gap-3">
            {/* Family Dropdown */}
            <div className="flex items-center gap-1.5 bg-[#161b22] border border-[#30363d] rounded-lg px-2.5 py-1 text-xs">
              <Layers className="w-3.5 h-3.5 text-[#8b949e]" />
              <span className="text-[#8b949e]">家族:</span>
              <select
                value={familyFilter}
                onChange={(e) => setFamilyFilter(e.target.value)}
                className="bg-transparent text-[#f0f6fc] font-bold focus:outline-none cursor-pointer"
              >
                {families.map((fam) => (
                  <option key={fam} value={fam} className="bg-[#161b22] text-[#f0f6fc]">
                    {fam === 'ALL' ? '全部分类 (All Families)' : fam}
                  </option>
                ))}
              </select>
            </div>

            {/* Search Box */}
            <div className="relative flex items-center">
              <Search className="w-3.5 h-3.5 text-[#8b949e] absolute left-2.5 pointer-events-none" />
              <input
                type="text"
                placeholder="搜索因子名/代码/假设..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-[#161b22] border border-[#30363d] rounded-lg pl-8 pr-3 py-1 text-xs text-[#f0f6fc] placeholder-[#8b949e] focus:outline-none focus:border-[#58a6ff] w-48 transition"
              />
            </div>
          </div>
        </div>

        {/* Main Factors List Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-[#8b949e]">
              <RefreshCw className="w-8 h-8 animate-spin text-[#58a6ff] mb-3" />
              <p className="text-sm">正在加载本地数据库 SQLite 因子知识库...</p>
            </div>
          ) : filteredFactors.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-[#8b949e]">
              <AlertTriangle className="w-8 h-8 text-[#d29922] mb-3" />
              <p className="text-sm">未检索到匹配的量化因子，请调整筛选条件或点击右上角重新挖掘。</p>
            </div>
          ) : (
            filteredFactors.map((f) => {
              const isExcellent = f.status === 'EXCELLENT';
              const isCandidate = f.status === 'CANDIDATE';
              const isGraveyard = f.status === 'GRAVEYARD';

              return (
                <div
                  key={f.factor_id}
                  className={`bg-[#161b22] border rounded-2xl p-4 transition duration-200 hover:border-[#58a6ff]/50 ${
                    isExcellent
                      ? 'border-[#238636]/60 shadow-[0_0_15px_rgba(46,160,67,0.1)]'
                      : isCandidate
                      ? 'border-[#d29922]/50'
                      : 'border-[#f85149]/40 opacity-80'
                  }`}
                >
                  {/* Card Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#30363d]/60 pb-3">
                    <div className="flex items-center gap-2.5">
                      <span className="font-mono text-xs px-2 py-0.5 rounded bg-[#21262d] text-[#8b949e] border border-[#30363d]">
                        {f.factor_id}
                      </span>
                      <h3 className="text-sm font-bold text-[#f0f6fc]">{f.name}</h3>
                      <span className="text-[11px] px-2 py-0.5 rounded bg-[#30363d]/60 text-[#c9d1d9]">
                        {f.family}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      {/* Score Badge */}
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold border ${
                          isExcellent
                            ? 'bg-[#238636]/20 text-[#3fb950] border-[#238636]/60'
                            : isCandidate
                            ? 'bg-[#d29922]/20 text-[#d29922] border-[#d29922]/60'
                            : 'bg-[#f85149]/20 text-[#f85149] border-[#f85149]/60'
                        }`}
                      >
                        {f.grade} 级 • {f.total_score} 分
                      </span>

                      {/* Status Tag */}
                      <span
                        className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                          isExcellent
                            ? 'bg-[#3fb950]/20 text-[#3fb950]'
                            : isCandidate
                            ? 'bg-[#d29922]/20 text-[#d29922]'
                            : 'bg-[#f85149]/20 text-[#f85149]'
                        }`}
                      >
                        {isExcellent ? '👑 优秀因子' : isCandidate ? '🔬 观察候选' : '🪦 淘汰入墓'}
                      </span>
                    </div>
                  </div>

                  {/* Economic Hypothesis */}
                  <div className="mt-3 text-xs leading-relaxed text-[#c9d1d9] bg-[#0d1117] p-2.5 rounded-xl border border-[#30363d]/60">
                    <span className="text-[#58a6ff] font-bold mr-1.5">💡 经济机制假设:</span>
                    <span className="italic">{f.hypothesis}</span>
                  </div>

                  {/* Formula DSL */}
                  <div className="mt-2.5 flex items-center justify-between gap-2 bg-[#0d1117] px-3 py-1.5 rounded-lg border border-[#30363d]/60 font-mono text-[11px] text-[#79c0ff]">
                    <div className="truncate">
                      <span className="text-[#8b949e] select-none mr-2">DSL:</span>
                      {f.formula_dsl}
                    </div>
                    <button
                      onClick={() => handleCopyFormula(f.factor_id, f.formula_dsl)}
                      className="p-1 text-[#8b949e] hover:text-[#f0f6fc] transition"
                      title="复制公式"
                    >
                      {copiedId === f.factor_id ? (
                        <Check className="w-3.5 h-3.5 text-[#3fb950]" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>

                  {/* Fail Reason if Graveyard */}
                  {isGraveyard && f.fail_reason && (
                    <div className="mt-2.5 flex items-center gap-2 bg-[#f85149]/10 border border-[#f85149]/30 px-3 py-1.5 rounded-lg text-xs text-[#f85149]">
                      <ShieldAlert className="w-4 h-4 shrink-0" />
                      <span>硬性门禁违规记录: {f.fail_reason}</span>
                    </div>
                  )}

                  {/* Multi-Commodity Scoreboard Breakdown */}
                  {f.tested_symbols && (() => {
                    try {
                      const symData = typeof f.tested_symbols === 'string' ? JSON.parse(f.tested_symbols) : f.tested_symbols;
                      const symKeys = Object.keys(symData || {});
                      if (symKeys.length === 0) return null;
                      const namesMap: Record<string, string> = {
                        AU_IDX: '沪金',
                        AG_IDX: '沪银',
                        CU_IDX: '沪铜',
                        SC_IDX: '原油',
                        RB_IDX: '螺纹',
                        M_IDX: '豆粕',
                      };
                      return (
                        <div className="mt-2.5 bg-[#0d1117] p-2.5 rounded-xl border border-[#30363d]/60">
                          <div className="flex items-center justify-between text-[11px] font-semibold text-[#8b949e] mb-1.5">
                            <span className="flex items-center gap-1">
                              <BarChart3 className="w-3 h-3 text-[#58a6ff]" />
                              6 大代表性商品期货大数逐柱实测表现透视:
                            </span>
                            <span className="text-[10px] text-[#8b949e]">8000+ Bars 严格次柱开盘成交</span>
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-6 gap-1.5">
                            {symKeys.map((k) => {
                              const s = symData[k];
                              const isPos = (s?.pnl || 0) > 0;
                              return (
                                <div
                                  key={k}
                                  className={`px-2 py-1 rounded-lg border text-center font-mono ${
                                    isPos
                                      ? 'bg-[#238636]/10 border-[#238636]/40 text-[#3fb950]'
                                      : 'bg-[#f85149]/10 border-[#f85149]/40 text-[#f85149]'
                                  }`}
                                >
                                  <div className="text-[10px] font-bold text-[#c9d1d9]">
                                    {namesMap[k] || k}
                                  </div>
                                  <div className="text-[11px] font-bold">
                                    {isPos
                                      ? `+¥${((s?.pnl || 0) / 10000).toFixed(1)}万`
                                      : `-¥${(Math.abs(s?.pnl || 0) / 10000).toFixed(1)}万`}
                                  </div>
                                  <div className="text-[9px] text-[#8b949e]">
                                    夏普 {s?.sharpe?.toFixed(1) ?? '0.0'}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    } catch (e) {
                      return null;
                    }
                  })()}

                  {/* Metrics Row & Action */}
                  <div className="mt-3.5 pt-3 border-t border-[#30363d]/40 flex flex-wrap items-center justify-between gap-4">
                    {/* Metrics Grid */}
                    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
                      <div>
                        <span className="text-[#8b949e]">Rank IC: </span>
                        <span className="font-mono font-bold text-[#f0f6fc]">{f.rank_ic}</span>
                      </div>
                      <div>
                        <span className="text-[#8b949e]">ICIR: </span>
                        <span className="font-mono font-bold text-[#f0f6fc]">{f.icir}</span>
                      </div>
                      <div>
                        <span className="text-[#8b949e]">回测胜率: </span>
                        <span
                          className={`font-mono font-bold ${
                            f.win_rate >= 50 ? 'text-[#3fb950]' : 'text-[#f85149]'
                          }`}
                        >
                          {f.win_rate}%
                        </span>
                      </div>
                      <div>
                        <span className="text-[#8b949e]">夏普比率: </span>
                        <span
                          className={`font-mono font-bold ${
                            f.sharpe >= 1.5 ? 'text-[#3fb950]' : 'text-[#d29922]'
                          }`}
                        >
                          {f.sharpe}
                        </span>
                      </div>
                      <div>
                        <span className="text-[#8b949e]">3x成本耐受: </span>
                        <span
                          className={`font-mono font-bold ${
                            f.breakeven_cost_mult >= 2.0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                          }`}
                        >
                          {f.breakeven_cost_mult}x
                        </span>
                      </div>
                      <div>
                        <span className="text-[#8b949e]">跨品种正收益率: </span>
                        <span
                          className={`font-mono font-bold ${
                            f.cross_market_pass_rate >= 60 ? 'text-[#3fb950]' : 'text-[#d29922]'
                          }`}
                        >
                          {f.cross_market_pass_rate}%
                        </span>
                      </div>
                    </div>

                    {/* Apply Button */}
                    <button
                      onClick={() => {
                        let stratId = 'taichong_elastoplastic_tensor';
                        if (f.factor_id.includes('MOM') || f.factor_id.includes('TQ')) {
                          stratId = 'causal_ml';
                        } else if (f.factor_id.includes('BRK') || f.factor_id.includes('COMP_003')) {
                          stratId = 'chandelier_exit';
                        } else if (f.factor_id.includes('MR')) {
                          stratId = 'guiyuan_zscore_reversion';
                        }
                        onApplyFactorToBacktest('AU_IDX', stratId);
                        onClose();
                      }}
                      className="px-3 py-1 rounded-lg bg-[#58a6ff]/15 hover:bg-[#58a6ff]/25 text-[#58a6ff] border border-[#58a6ff]/30 text-xs font-bold flex items-center gap-1.5 transition ml-auto"
                    >
                      <span>📊 一键应用至主图回测</span>
                      <ArrowUpRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-[#30363d] bg-[#161b22] flex items-center justify-between text-xs text-[#8b949e]">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#3fb950]" />
            <span>数据源: 本地 SQLite 真实分时数据 (data/ashare_quant.db) • 严格次柱开盘成交</span>
          </div>
          <span>天极量化因果科研实验室 • V4.0</span>
        </div>
      </div>
    </div>
  );
};
