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
    let mut last_error = String::new();

    for py in &python_candidates {
        if let Ok(output) = Command::new(py)
            .arg(script_path)
            .current_dir(cwd)
            .output()
        {
            if output.status.success() {
                executed = true;
                break;
            } else {
                last_error = String::from_utf8_lossy(&output.stderr).to_string();
            }
        }
    }

    if !executed {
        if !last_error.is_empty() {
            return Err(format!("Python 因子研究引擎执行失败: {}", last_error));
        } else {
            return Err("未找到可用的 Python 运行环境或执行失败".to_string());
        }
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
    pub current_evaluating_factor: Option<String>,
    pub current_evaluating_name: Option<String>,
    pub updated_at: Option<String>,
}

fn is_pid_alive(pid: u32) -> bool {
    Command::new("kill")
        .arg("-0")
        .arg(pid.to_string())
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn terminate_pid(pid: u32) {
    let _ = Command::new("kill")
        .arg("-15")
        .arg(pid.to_string())
        .output();
}

fn force_kill_pid(pid: u32) {
    let _ = Command::new("kill")
        .arg("-9")
        .arg(pid.to_string())
        .output();
}

#[tauri::command]
pub fn start_continuous_research_command(duration_seconds: Option<u64>) -> Result<ContinuousResearchStatus, String> {
    let dur = duration_seconds.unwrap_or(3600);

    // 1. Single-instance mutex check: If already running, return current status
    if let Ok(st) = get_continuous_research_status_command() {
        if st.is_running {
            if let Some(pid) = st.pid {
                if is_pid_alive(pid) {
                    return Ok(st);
                }
            }
        }
    }

    let python_candidates = [
        "/Users/tang/PycharmProjects/pythonProject/env10/bin/python",
        "python3",
        "python",
    ];
    let script_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/code/continuous_alpha_miner.py";
    let cwd = "/Users/tang/PycharmProjects/pythonProject/lianghua";

    let stop_file = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/stop_continuous_miner.signal";
    let _ = std::fs::remove_file(stop_file);

    let mut spawned_child_pid: Option<u32> = None;
    for py in &python_candidates {
        if let Ok(child) = Command::new(py)
            .arg(script_path)
            .arg("--duration")
            .arg(dur.to_string())
            .current_dir(cwd)
            .spawn()
        {
            spawned_child_pid = Some(child.id());
            break;
        }
    }

    let child_pid = match spawned_child_pid {
        Some(pid) => pid,
        None => return Err("Failed to spawn background python continuous miner".into()),
    };

    // 2. Poll up to 3000ms for Python startup confirmation
    for _ in 0..15 {
        std::thread::sleep(std::time::Duration::from_millis(200));
        if let Ok(st) = get_continuous_research_status_command() {
            if st.is_running && st.pid == Some(child_pid) {
                return Ok(st);
            }
        }
    }

    Err("Python continuous miner failed to start within 3s".into())
}

#[tauri::command]
pub fn stop_continuous_research_command() -> Result<bool, String> {
    let stop_file = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/stop_continuous_miner.signal";
    let status_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/continuous_miner_status.json";
    
    // 1. Write stop signal file
    let _ = std::fs::write(stop_file, "STOP");

    // 2. Terminate process gracefully with SIGTERM
    if let Ok(content) = std::fs::read_to_string(status_path) {
        if let Ok(mut status) = serde_json::from_str::<ContinuousResearchStatus>(&content) {
            if let Some(pid) = status.pid {
                if is_pid_alive(pid) {
                    terminate_pid(pid);
                    // Wait up to 1.5s for graceful exit
                    for _ in 0..15 {
                        std::thread::sleep(std::time::Duration::from_millis(100));
                        if !is_pid_alive(pid) {
                            break;
                        }
                    }
                    // If still alive, force kill
                    if is_pid_alive(pid) {
                        force_kill_pid(pid);
                        std::thread::sleep(std::time::Duration::from_millis(200));
                        if is_pid_alive(pid) {
                            return Err(format!("Failed to kill continuous miner process (pid={})", pid));
                        }
                    }
                }
            }
            // 3. Immediately mark is_running as false in the status file!
            status.is_running = false;
            status.remaining_seconds = Some(0);
            if let Ok(updated_json) = serde_json::to_string_pretty(&status) {
                let _ = std::fs::write(status_path, updated_json);
            }
        }
    }

    let _ = std::fs::remove_file(stop_file);
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
            current_evaluating_factor: None,
            current_evaluating_name: None,
            updated_at: None,
        });
    }

    let content = std::fs::read_to_string(status_path).map_err(|e| e.to_string())?;
    let mut status: ContinuousResearchStatus = serde_json::from_str(&content).map_err(|e| e.to_string())?;

    // Liveness verification: If status says is_running == true, verify that the OS process actually exists!
    if status.is_running {
        let alive = match status.pid {
            Some(pid) => is_pid_alive(pid),
            None => false,
        };

        if !alive {
            status.is_running = false;
            status.remaining_seconds = Some(0);
            if let Ok(corrected) = serde_json::to_string_pretty(&status) {
                let _ = std::fs::write(status_path, corrected);
            }
        }
    }

    Ok(status)
}

