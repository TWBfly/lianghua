use crate::backtest::{
    execute_backtest, execute_dual_track_evaluation, execute_portfolio_backtest, BacktestRequest,
    BacktestResponse, DualTrackEvaluationReport, DualTrackEvaluationRequest,
    PortfolioBacktestRequest, PortfolioBacktestResponse,
};
use crate::db::{query_futures_kline, query_stock_basic, query_stock_daily, KlineBar, StockBasicItem};
use crate::strategies::{
    calculate_system_status, get_strategies_registry, load_trades_and_markers, ChartMarker,
    StrategyMeta, SystemStatus, TradeRecord,
};

#[tauri::command]
pub fn fetch_kline_bars(
    symbol: String,
    timeframe: String,
    limit: Option<usize>,
) -> Result<Vec<KlineBar>, String> {
    let limit = limit.unwrap_or(1000);
    if symbol.chars().all(|c| c.is_ascii_digit()) && symbol.len() == 6 {
        query_stock_daily(&symbol, limit)
    } else {
        query_futures_kline(&symbol, &timeframe, limit)
    }
}

#[tauri::command]
pub fn fetch_stock_bars(
    symbol: String,
    limit: Option<usize>,
) -> Result<Vec<KlineBar>, String> {
    let limit = limit.unwrap_or(1000);
    query_stock_daily(&symbol, limit)
}

#[tauri::command]
pub fn search_stocks(query: String) -> Result<Vec<StockBasicItem>, String> {
    query_stock_basic(&query)
}

#[tauri::command]
pub fn get_strategy_registry() -> Result<Vec<StrategyMeta>, String> {
    Ok(get_strategies_registry())
}

#[tauri::command]
pub fn get_strategy_trades(
    strategy_id: String,
    symbol: Option<String>,
) -> Result<Vec<TradeRecord>, String> {
    let sym_ref = symbol.as_deref();
    let (trades, _) = load_trades_and_markers(&strategy_id, sym_ref);
    Ok(trades)
}

#[tauri::command]
pub fn get_strategy_markers(
    strategy_id: String,
    symbol: String,
) -> Result<Vec<ChartMarker>, String> {
    let (_, markers) = load_trades_and_markers(&strategy_id, Some(&symbol));
    Ok(markers)
}

#[tauri::command]
pub fn get_system_status() -> Result<SystemStatus, String> {
    Ok(calculate_system_status())
}

#[tauri::command]
pub fn run_backtest_command(req: BacktestRequest) -> Result<BacktestResponse, String> {
    execute_backtest(req)
}

#[tauri::command]
pub fn run_portfolio_backtest_command(
    req: PortfolioBacktestRequest,
) -> Result<PortfolioBacktestResponse, String> {
    execute_portfolio_backtest(req)
}

#[tauri::command]
pub fn run_strategy_dual_track_evaluation_command(
    req: DualTrackEvaluationRequest,
) -> Result<DualTrackEvaluationReport, String> {
    execute_dual_track_evaluation(req)
}
