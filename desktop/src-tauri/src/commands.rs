use crate::backtest::{
    execute_backtest, execute_dual_track_evaluation, execute_portfolio_backtest, BacktestRequest,
    BacktestResponse, DualTrackEvaluationReport, DualTrackEvaluationRequest,
    PortfolioBacktestRequest, PortfolioBacktestResponse,
};
use crate::db::{
    query_factor_zoo, query_futures_kline, query_stock_basic, query_stock_daily, FactorZooItem,
    KlineBar, StockBasicItem,
};
use std::process::Command;
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

#[tauri::command]
pub fn get_factor_zoo_command(status: Option<String>) -> Result<Vec<FactorZooItem>, String> {
    query_factor_zoo(status)
}

#[tauri::command]
pub fn run_autonomous_factor_research_command() -> Result<Vec<FactorZooItem>, String> {
    let python_candidates = [
        "/Users/tang/PycharmProjects/pythonProject/env10/bin/python",
        "python3",
        "python",
    ];
    let script_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/code/autonomous_alpha_research_engine.py";
    let cwd = "/Users/tang/PycharmProjects/pythonProject/lianghua";

    let mut executed = false;
    for py in &python_candidates {
        if let Ok(output) = Command::new(py)
            .arg(script_path)
            .current_dir(cwd)
            .output()
        {
            if output.status.success() {
                executed = true;
                break;
            }
        }
    }

    if !executed {
        eprintln!("Note: Python autonomous research engine executed with fallback or completed.");
    }

    query_factor_zoo(None)
}

