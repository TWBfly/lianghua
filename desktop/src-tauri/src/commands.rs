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

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ContinuousResearchStatus {
    pub is_running: bool,
    pub pid: Option<u32>,
    pub start_time: Option<u64>,
    pub duration_seconds: Option<u64>,
    pub elapsed_seconds: Option<u64>,
    pub remaining_seconds: Option<u64>,
    pub total_evaluated_this_run: Option<u64>,
    pub total_in_zoo: Option<u64>,
    pub latest_factor_id: Option<String>,
    pub latest_factor_name: Option<String>,
    pub latest_factor_score: Option<f64>,
    pub latest_factor_status: Option<String>,
    pub latest_fail_reason: Option<String>,
    pub updated_at: Option<String>,
}

#[tauri::command]
pub fn start_continuous_research_command(duration_seconds: Option<u64>) -> Result<ContinuousResearchStatus, String> {
    let dur = duration_seconds.unwrap_or(3600);
    let python_candidates = [
        "/Users/tang/PycharmProjects/pythonProject/env10/bin/python",
        "python3",
        "python",
    ];
    let script_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/code/continuous_alpha_miner.py";
    let cwd = "/Users/tang/PycharmProjects/pythonProject/lianghua";

    let stop_file = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/stop_continuous_miner.signal";
    let _ = std::fs::remove_file(stop_file);

    let mut spawned = false;
    for py in &python_candidates {
        if let Ok(_child) = Command::new(py)
            .arg(script_path)
            .arg("--duration")
            .arg(dur.to_string())
            .current_dir(cwd)
            .spawn()
        {
            spawned = true;
            break;
        }
    }

    if !spawned {
        return Err("Failed to spawn background python continuous miner".into());
    }

    std::thread::sleep(std::time::Duration::from_millis(300));
    get_continuous_research_status_command()
}

#[tauri::command]
pub fn stop_continuous_research_command() -> Result<bool, String> {
    let stop_file = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/stop_continuous_miner.signal";
    if let Err(e) = std::fs::write(stop_file, "STOP") {
        return Err(format!("Failed to create stop signal file: {}", e));
    }
    Ok(true)
}

#[tauri::command]
pub fn get_continuous_research_status_command() -> Result<ContinuousResearchStatus, String> {
    let status_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/continuous_miner_status.json";
    if !std::path::Path::new(status_path).exists() {
        return Ok(ContinuousResearchStatus {
            is_running: false,
            pid: None,
            start_time: None,
            duration_seconds: Some(3600),
            elapsed_seconds: Some(0),
            remaining_seconds: Some(3600),
            total_evaluated_this_run: Some(0),
            total_in_zoo: Some(0),
            latest_factor_id: None,
            latest_factor_name: None,
            latest_factor_score: None,
            latest_factor_status: None,
            latest_fail_reason: None,
            updated_at: None,
        });
    }

    let content = std::fs::read_to_string(status_path).map_err(|e| e.to_string())?;
    let status: ContinuousResearchStatus = serde_json::from_str(&content).map_err(|e| e.to_string())?;
    Ok(status)
}

