export interface KlineBar {
  time: number; // Unix timestamp in seconds
  datetime_str: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount?: number;
  open_interest?: number;
}

export interface StrategyMeta {
  id: string;
  name: string;
  short_name: string;
  timeframe: string;
  symbols: string[];
  default_symbol: string;
  initial_capital: number;
  summary_win_rate: number;
  execution_status: string;
}

export interface TradeRecord {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  side: string;
  entry_dt: string;
  entry_p: number;
  entry_reason: string;
  exit_dt: string;
  exit_p: number;
  exit_reason: string;
  lots: number;
  pnl: number;
  status: string;
}

export interface ChartMarker {
  time: number;
  position: 'belowBar' | 'aboveBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
  id: string;
  price: number;
  reason: string;
  action: 'ENTRY' | 'EXIT';
  pnl?: number;
}

export interface SystemStatus {
  engine_status: string;
  total_equity: number;
  active_positions_count: number;
  total_trades_count: number;
  total_pnl: number;
  win_rate: number;
}

export interface StockBasicItem {
  symbol: string;
  name: string;
  price: number;
  pe_ttm: number;
  pb: number;
  total_mv: number;
}

export interface BacktestRequest {
  symbol: string;
  strategy: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  backtest_mode: string;
  data_source?: 'REAL' | 'SYNTHETIC';
  use_synthetic?: boolean;
  fixed_lots?: number;
}

export interface BacktestMetrics {
  initial_capital: number;
  final_equity: number;
  net_pnl_total: number;
  total_return_pct: number;
  annualized_return_pct: number;
  win_rate_pct: number;
  total_trades: number;
  win_trades_count: number;
  loss_trades_count: number;
  profit_loss_ratio: number;
  avg_holding_days: number;
  max_drawdown_pct: number;
  backtest_period: string;
  total_friction_cny: number;
  lln_compliant: boolean;
  data_source_label: string;
  total_bars_count: number;
}

export interface BacktestTradeItem {
  id: number;
  symbol: string;
  name: string;
  buy_date: string;
  buy_price: number;
  buy_reason?: string;
  sell_date: string;
  sell_price: number;
  shares: number;
  pnl_amount: number;
  pnl_pct: number;
  ml_score_pct: number;
  sell_reason: string;
  fees_detail: string;
}

export interface BacktestResponse {
  symbol: string;
  name: string;
  timeframe: string;
  data_source: string;
  metrics: BacktestMetrics;
  trades: BacktestTradeItem[];
  markers: ChartMarker[];
  bars: KlineBar[];
}

export interface PortfolioBacktestRequest {
  strategy: string;
  timeframe: string;
  initial_capital: number;
  data_source?: string;
  use_synthetic?: boolean;
  start_date: string;
  end_date: string;
}

export interface SymbolPerformance {
  symbol: string;
  name: string;
  sector: string;
  trades_count: number;
  win_trades_count: number;
  loss_trades_count: number;
  win_rate_pct: number;
  net_pnl: number;
  return_pct: number;
  profit_loss_ratio: number;
  max_drawdown_pct: number;
  expectancy_cny: number;
}

export interface PortfolioBacktestResponse {
  strategy: string;
  strategy_name: string;
  timeframe: string;
  timeframe_label: string;
  data_source: string;
  data_source_label: string;
  start_date: string;
  end_date: string;
  total_trades: usize;
  win_trades_count: usize;
  loss_trades_count: usize;
  lln_compliant: boolean;
  total_equity: number;
  initial_capital: number;
  total_net_pnl: number;
  total_return_pct: number;
  annualized_return_pct: number;
  sharpe_ratio: number;
  calmar_ratio: number;
  expectancy_cny: number;
  overall_win_rate_pct: number;
  overall_pl_ratio: number;
  overall_max_drawdown_pct: number;
  total_friction_cny: number;
  stress_test_3x_pnl: number;
  p_ruin_pct: number;
  symbol_breakdowns: SymbolPerformance[];
}
type usize = number;

export interface DualTrackEvaluationRequest {
  symbol: string;
  strategy: string;
  timeframe: string;
  initial_capital: number;
}

export interface TrackPerformance {
  data_source_type: string;
  data_source_label: string;
  period_label: string;
  total_bars: number;
  total_trades: number;
  win_trades_count: number;
  loss_trades_count: number;
  win_rate_pct: number;
  profit_loss_ratio: number;
  total_net_pnl: number;
  total_return_pct: number;
  annualized_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  calmar_ratio: number;
  expectancy_cny: number;
  total_friction_cny: number;
  stress_test_3x_pnl: number;
}

export interface ScoreDimension {
  name: string;
  max_score: number;
  score: number;
  description: string;
  assessment: string;
}

export interface StrategyScorecard {
  total_score: number;
  grade: string;
  grade_badge: string;
  summary_comment: string;
  dimensions: ScoreDimension[];
}

export interface StrategyLogicDetails {
  title: string;
  core_formula: string;
  trigger_conditions: string[];
  execution_mechanics: string;
}

export interface OptimizationItem {
  dimension: string;
  title: string;
  suggestion: string;
  expected_impact: string;
}

export interface ExecutiveVerdict {
  overall_rating: string;
  summary: string;
  core_strengths: string[];
  potential_risks: string[];
  suitable_market_regime: string;
  deployment_recommendation: string;
}

export interface DualTrackEvaluationReport {
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  symbol_name: string;
  timeframe: string;
  timeframe_label: string;
  initial_capital: number;
  real_benchmark: TrackPerformance;
  synthetic_benchmark: TrackPerformance;
  scorecard: StrategyScorecard;
  entry_logic: StrategyLogicDetails;
  exit_logic: StrategyLogicDetails;
  optimization_suggestions: OptimizationItem[];
  executive_verdict: ExecutiveVerdict;
}

export interface FactorZooItem {
  factor_id: string;
  name: string;
  family: string;
  hypothesis: string;
  formula_dsl: string;
  total_score: number;
  grade: string;
  rank_ic: number;
  icir: number;
  win_rate: number;
  sharpe: number;
  profit_factor: number;
  max_dd: number;
  breakeven_cost_mult: number;
  cross_market_pass_rate: number;
  tested_symbols: string;
  status: 'EXCELLENT' | 'CANDIDATE' | 'GRAVEYARD' | 'LEGACY_UNVERIFIED';
  fail_reason?: string | null;
  created_at: string;
}

export interface ContinuousResearchStatus {
  is_running: boolean;
  pid?: number | null;
  start_time?: number | null;
  duration_seconds?: number | null;
  elapsed_seconds?: number | null;
  remaining_seconds?: number | null;
  total_evaluated_this_run?: number | null;
  total_in_zoo?: number | null;
  latest_factor_id?: string | null;
  latest_factor_name?: string | null;
  latest_factor_score?: number | null;
  latest_factor_status?: string | null;
  latest_fail_reason?: string | null;
  updated_at?: string | null;
}

