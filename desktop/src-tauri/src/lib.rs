pub mod backtest;
pub mod commands;
pub mod db;
pub mod strategies;

use commands::*;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            fetch_kline_bars,
            fetch_stock_bars,
            search_stocks,
            get_strategy_registry,
            get_strategy_trades,
            get_strategy_markers,
            get_system_status,
            run_backtest_command,
            run_portfolio_backtest_command,
            run_strategy_dual_track_evaluation_command,
            get_factor_zoo_command,
            run_autonomous_factor_research_command,
            start_continuous_research_command,
            stop_continuous_research_command,
            get_continuous_research_status_command,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
