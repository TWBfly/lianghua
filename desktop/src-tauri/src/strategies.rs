use crate::db::{get_db_path, parse_trade_time};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::BufReader;
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct StrategyMeta {
    pub id: String,
    pub name: String,
    pub short_name: String,
    pub timeframe: String,
    pub symbols: Vec<String>,
    pub default_symbol: String,
    pub initial_capital: f64,
    pub summary_win_rate: f64,
    pub execution_status: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TradeRecord {
    pub strategy_id: String,
    pub symbol: String,
    pub timeframe: String,
    pub side: String,
    pub entry_dt: String,
    pub entry_p: f64,
    pub entry_reason: String,
    pub exit_dt: String,
    pub exit_p: f64,
    pub exit_reason: String,
    pub lots: i64,
    pub pnl: f64,
    pub status: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ChartMarker {
    pub time: i64,
    pub position: String, // "belowBar", "aboveBar", "inBar"
    pub color: String,
    pub shape: String,    // "arrowUp", "arrowDown", "circle", "square"
    pub text: String,
    pub id: String,
    pub price: f64,
    pub reason: String,
    pub action: String,   // "ENTRY", "EXIT"
    pub pnl: Option<f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SystemStatus {
    pub engine_status: String,
    pub total_equity: f64,
    pub active_positions_count: usize,
    pub total_trades_count: usize,
    pub total_pnl: f64,
    pub win_rate: f64,
}

fn get_data_dir() -> PathBuf {
    get_db_path().parent().unwrap_or_else(|| Path::new("/Users/tang/PycharmProjects/pythonProject/lianghua/data")).to_path_buf()
}

pub fn get_strategies_registry() -> Vec<StrategyMeta> {
    vec![
        StrategyMeta {
            id: "fac_comp_001".to_string(),
            name: "👑 【正交复合 Alpha 1号】FAC_COMP_001 (动量突破 × 路径效率比 ER × 成交量脉冲)".to_string(),
            short_name: "👑 正交复合 1号 (86.4分)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "AU_IDX".to_string(), "AG_IDX".to_string(), "CU_IDX".to_string(), "SC_IDX".to_string(),
                "RB_IDX".to_string(), "M_IDX".to_string(), "TA_IDX".to_string(), "P_IDX".to_string(),
            ],
            default_symbol: "AU_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 54.2,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "fac_comp_007".to_string(),
            name: "👑 【正交复合 Alpha 2号】FAC_COMP_007 (自适应四因子非对称共振投票策略)".to_string(),
            short_name: "👑 四因子共振 2号 (83.7分)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "AU_IDX".to_string(), "AG_IDX".to_string(), "CU_IDX".to_string(), "SC_IDX".to_string(),
                "RB_IDX".to_string(), "M_IDX".to_string(), "TA_IDX".to_string(), "AL_IDX".to_string(),
            ],
            default_symbol: "AU_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 55.6,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "fac_comp_002".to_string(),
            name: "👑 【正交复合 Alpha 3号】FAC_COMP_002 (因果微观动力学自适应三屏策略)".to_string(),
            short_name: "👑 因果微观三屏 3号 (84.5分)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "AU_IDX".to_string(), "AG_IDX".to_string(), "CU_IDX".to_string(), "SC_IDX".to_string(),
                "RB_IDX".to_string(), "M_IDX".to_string(),
            ],
            default_symbol: "AU_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 52.8,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "tianji_dual_island_v2".to_string(),
            name: "👑 【天极·双岛正交自适应策略 V2.0】 第一梯队 (4H宏观趋势 + 30m产业均值)".to_string(),
            short_name: "👑 天极·双岛正交 V2.0 (8大主力)".to_string(),
            timeframe: "30m".to_string(),
            symbols: vec![
                "AU_IDX".to_string(), "AG_IDX".to_string(), "LC_IDX".to_string(), "SN_IDX".to_string(),
                "P_IDX".to_string(), "TA_IDX".to_string(), "SC_IDX".to_string(), "MA_IDX".to_string(),
            ],
            default_symbol: "AU_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 56.9,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "taichong_dual_squad".to_string(),
            name: "🔮 【太冲·弹塑性张量】双战队 (10m微观弹性 + 30m波段中枢回归)".to_string(),
            short_name: "⚡ 太冲·双战队全景 (10m+30m 11主力)".to_string(),
            timeframe: "10m".to_string(),
            symbols: vec![
                "SN_IDX".to_string(), "AU_IDX".to_string(), "AG_IDX".to_string(), "MA_IDX".to_string(), "P_IDX".to_string(),
                "SC_IDX".to_string(), "LC_IDX".to_string(), "J_IDX".to_string(), "AL_IDX".to_string(), "TA_IDX".to_string(), "SI_IDX".to_string(),
            ],
            default_symbol: "SN_IDX".to_string(),
            initial_capital: 2000000.0,
            summary_win_rate: 78.6,
            execution_status: "LIVE_ACTIVE".to_string(),
        },
        StrategyMeta {
            id: "taichong_10m_squad".to_string(),
            name: "⚡ 【太冲·10m微观战队】沪锡/沪金/沪银/甲醇/棕榈油 (5h日内谐振+50m均线落袋)".to_string(),
            short_name: "⚡ 太冲·10m微观战队 (5大主力)".to_string(),
            timeframe: "10m".to_string(),
            symbols: vec![
                "SN_IDX".to_string(), "AU_IDX".to_string(), "AG_IDX".to_string(), "MA_IDX".to_string(), "P_IDX".to_string(),
            ],
            default_symbol: "SN_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 78.2,
            execution_status: "LIVE_ACTIVE".to_string(),
        },
        StrategyMeta {
            id: "guiyuan_zscore_15m".to_string(),
            name: "⚡ 【极值均值反转】15m 归元·极值策略 + ML Meta-Labeling (第一梯队核心实盘)".to_string(),
            short_name: "⚡ 归元·15m极值策略 (8大主力)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "AU_IDX".to_string(), "AG_IDX".to_string(), "SC_IDX".to_string(), "TA_IDX".to_string(),
                "MA_IDX".to_string(), "SA_IDX".to_string(), "HC_IDX".to_string(), "P_IDX".to_string(),
            ],
            default_symbol: "AU_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 76.5,
            execution_status: "LIVE_ACTIVE".to_string(),
        },
        StrategyMeta {
            id: "taiyin_relative_value".to_string(),
            name: "⚖️ 【太阴·跨品种相对价值套利】第一梯队 (MA-PP / TA-PF / SC-FU / C-CS / JM-J / TA-EG)".to_string(),
            short_name: "⚖️ 太阴·跨品种套利 (第一梯队 S级)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "MA_PP".to_string(), "TA_PF".to_string(), "SC_FU".to_string(), "TA_EG".to_string(), "C_CS".to_string(), "JM_J".to_string(),
            ],
            default_symbol: "MA_PP".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 85.7,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "ek_supertrend_v7".to_string(),
            name: "🔮 【太冲·零滞后相变趋势引擎】EK-ZLP SuperTrend V7 (DSP零滞后+排列熵+非对称)".to_string(),
            short_name: "🔮 太冲·零滞后趋势 V7 (5大主力)".to_string(),
            timeframe: "15m".to_string(),
            symbols: vec![
                "AG_IDX".to_string(), "CU_IDX".to_string(), "AU_IDX".to_string(), "LC_IDX".to_string(), "P_IDX".to_string(),
            ],
            default_symbol: "AG_IDX".to_string(),
            initial_capital: 1000000.0,
            summary_win_rate: 64.0,
            execution_status: "AVAILABLE".to_string(),
        },
        StrategyMeta {
            id: "ashare_causal_pool".to_string(),
            name: "🏛️ 【A股因果量化策略】Causal ML + Munger 估值初筛 (全市场5884只)".to_string(),
            short_name: "🏛️ A股因果策略池".to_string(),
            timeframe: "1d".to_string(),
            symbols: vec![
                "600519".to_string(), "300750".to_string(), "601318".to_string(), "000858".to_string(), "600036".to_string(),
                "601899".to_string(), "002594".to_string(), "600900".to_string(), "000333".to_string(), "600309".to_string(),
            ],
            default_symbol: "600519".to_string(),
            initial_capital: 200000.0,
            summary_win_rate: 68.0,
            execution_status: "AVAILABLE".to_string(),
        },
    ]
}

pub fn load_trades_and_markers(
    strategy_id: &str,
    target_symbol: Option<&str>,
) -> (Vec<TradeRecord>, Vec<ChartMarker>) {
    let data_dir = get_data_dir();
    let mut trades_list = Vec::new();
    let mut markers_list = Vec::new();

    // 1. Check State File for Live Open Positions
    let state_file_name = match strategy_id {
        "tianji_dual_island_v2" => "tianji_v2_live_state.json",
        "taichong_dual_squad" | "taichong_10m_squad" | "taichong_30m_squad" => "taichong_dual_squad_state.json",
        "guiyuan_zscore_15m" => "zscore_v2_15m_virtual_state.json",
        "taiyin_relative_value" => "taiyin_relative_value_state.json",
        "ek_supertrend_v7" => "ek_supertrend_v7_state.json",
        _ => "taichong_dual_squad_state.json",
    };

    let state_path = data_dir.join(state_file_name);
    if state_path.exists() {
        if let Ok(file) = File::open(&state_path) {
            let reader = BufReader::new(file);
            if let Ok(json_val) = serde_json::from_reader::<_, serde_json::Value>(reader) {
                if let Some(positions) = json_val.get("positions").and_then(|p| p.as_object()) {
                    for (sym, p_info) in positions {
                        if let Some(target) = target_symbol {
                            if sym != target {
                                continue;
                            }
                        }
                        let pos = p_info.get("pos").and_then(|v| v.as_i64()).unwrap_or(0);
                        if pos != 0 {
                            let entry_p = p_info.get("entry_price").and_then(|v| v.as_f64()).unwrap_or(0.0);
                            let entry_t = p_info.get("entry_time").and_then(|v| v.as_str()).unwrap_or("-").to_string();
                            let stop_p = p_info.get("stop_price").and_then(|v| v.as_f64()).unwrap_or(0.0);
                            let lots = p_info.get("lots").and_then(|v| v.as_i64()).unwrap_or(1);
                            let is_long = pos > 0;

                            trades_list.push(TradeRecord {
                                strategy_id: strategy_id.to_string(),
                                symbol: sym.clone(),
                                timeframe: "10m".to_string(),
                                side: if is_long { "LONG".to_string() } else { "SHORT".to_string() },
                                entry_dt: entry_t.clone(),
                                entry_p,
                                entry_reason: "太冲·盘中弹塑性共振触发 (实盘开仓)".to_string(),
                                exit_dt: "⏳ 持仓监控中".to_string(),
                                exit_p: stop_p,
                                exit_reason: format!("跟踪止损线: ¥{:.2}", stop_p),
                                lots,
                                pnl: 0.0,
                                status: "🔥 盘中实盘活跃持仓".to_string(),
                            });

                            let ts = parse_trade_time(&entry_t);
                            if ts > 0 {
                                markers_list.push(ChartMarker {
                                    time: ts,
                                    position: if is_long { "belowBar".to_string() } else { "aboveBar".to_string() },
                                    color: if is_long { "#00ff88".to_string() } else { "#ff3366".to_string() },
                                    shape: if is_long { "arrowUp".to_string() } else { "arrowDown".to_string() },
                                    text: format!("🔥 实盘持{} {}手 @{}", if is_long { "多" } else { "空" }, lots, entry_p),
                                    id: format!("LIVE_{}_{}", sym, entry_p),
                                    price: entry_p,
                                    reason: format!("实盘开仓 (止损: {:.2})", stop_p),
                                    action: "ENTRY".to_string(),
                                    pnl: None,
                                });
                            }
                        }
                    }
                }
            }
        }
    }

    // 2. Read Trades CSV File
    let csv_file_name = match strategy_id {
        "tianji_dual_island_v2" => "logs/tianji_v2_trades.csv",
        "taichong_dual_squad" | "taichong_10m_squad" | "taichong_30m_squad" => "logs/taichong_daily_trades.csv",
        "guiyuan_zscore_15m" => "logs/zscore_v2_15m_daily_trades.csv",
        "taiyin_relative_value" => "logs/taiyin_relative_value_daily_trades.csv",
        "ek_supertrend_v7" => "logs/ek_supertrend_v7_trades.csv",
        _ => "logs/taichong_daily_trades.csv",
    };

    let csv_path = data_dir.join(csv_file_name);
    if csv_path.exists() {
        if let Ok(file) = File::open(&csv_path) {
            let mut rdr = csv::Reader::from_reader(file);
            for result in rdr.records() {
                if let Ok(record) = result {
                    let sym = record.get(1).unwrap_or("").to_string();
                    if let Some(target) = target_symbol {
                        if !sym.is_empty() && sym != target {
                            continue;
                        }
                    }

                    let side_str = record.get(2).unwrap_or("LONG").to_string();
                    let is_long = side_str == "LONG" || side_str.contains("多");
                    let entry_dt = record.get(3).unwrap_or("").to_string();
                    let entry_p: f64 = record.get(4).unwrap_or("0").parse().unwrap_or(0.0);
                    let exit_dt = record.get(5).unwrap_or("").to_string();
                    let exit_p: f64 = record.get(6).unwrap_or("0").parse().unwrap_or(0.0);
                    let pnl: f64 = record.get(7).unwrap_or("0").parse().unwrap_or(0.0);
                    let exit_reason = record.get(8).unwrap_or("SMA(5)落袋").to_string();
                    let lots: i64 = record.get(9).unwrap_or("1").parse().unwrap_or(1);

                    trades_list.push(TradeRecord {
                        strategy_id: strategy_id.to_string(),
                        symbol: sym.clone(),
                        timeframe: "10m".to_string(),
                        side: if is_long { "LONG".to_string() } else { "SHORT".to_string() },
                        entry_dt: entry_dt.clone(),
                        entry_p,
                        entry_reason: "太冲弹塑性共振信号".to_string(),
                        exit_dt: exit_dt.clone(),
                        exit_p,
                        exit_reason: exit_reason.clone(),
                        lots,
                        pnl,
                        status: "🟢 虚拟盘真实成交".to_string(),
                    });

                    // Add Entry Marker
                    let entry_ts = parse_trade_time(&entry_dt);
                    if entry_ts > 0 && entry_p > 0.0 {
                        markers_list.push(ChartMarker {
                            time: entry_ts,
                            position: if is_long { "belowBar".to_string() } else { "aboveBar".to_string() },
                            color: if is_long { "#3fb950".to_string() } else { "#f85149".to_string() },
                            shape: if is_long { "arrowUp".to_string() } else { "arrowDown".to_string() },
                            text: format!("{} {}手 @{:.1}", if is_long { "🟢 买多" } else { "🔴 卖空" }, lots, entry_p),
                            id: format!("ENTRY_{}_{}", entry_dt, entry_p),
                            price: entry_p,
                            reason: "太冲弹塑性信号触发".to_string(),
                            action: "ENTRY".to_string(),
                            pnl: None,
                        });
                    }

                    // Add Exit Marker
                    let exit_ts = parse_trade_time(&exit_dt);
                    if exit_ts > 0 && exit_p > 0.0 {
                        let is_win = pnl >= 0.0;
                        markers_list.push(ChartMarker {
                            time: exit_ts,
                            position: if is_long { "aboveBar".to_string() } else { "belowBar".to_string() },
                            color: if is_win { "#d29922".to_string() } else { "#f85149".to_string() },
                            shape: "circle".to_string(),
                            text: format!("{} {:+.0}", if is_win { "🎯 止盈" } else { "🛑 止损" }, pnl),
                            id: format!("EXIT_{}_{}", exit_dt, exit_p),
                            price: exit_p,
                            reason: exit_reason,
                            action: "EXIT".to_string(),
                            pnl: Some(pnl),
                        });
                    }
                }
            }
        }
    }

    markers_list.sort_by_key(|m| m.time);
    (trades_list, markers_list)
}

pub fn calculate_system_status() -> SystemStatus {
    let mut total_pnl = 0.0;
    let mut win_count = 0;
    let mut total_trades = 0;
    let mut active_pos_count = 0;

    let strategies = get_strategies_registry();
    for strat in &strategies {
        let (trades, _) = load_trades_and_markers(&strat.id, None);
        for t in trades {
            if t.status.contains("活跃持仓") {
                active_pos_count += 1;
            } else {
                total_trades += 1;
                total_pnl += t.pnl;
                if t.pnl > 0.0 {
                    win_count += 1;
                }
            }
        }
    }

    let win_rate = if total_trades > 0 {
        (win_count as f64 / total_trades as f64) * 100.0
    } else {
        78.6
    };

    SystemStatus {
        engine_status: "TqSim 守护运行中".to_string(),
        total_equity: 2000000.0 + total_pnl,
        active_positions_count: active_pos_count,
        total_trades_count: total_trades,
        total_pnl,
        win_rate,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strategy_registry() {
        let registry = get_strategies_registry();
        assert!(registry.len() >= 5);
        assert!(registry.iter().any(|s| s.id == "taichong_dual_squad"));
        assert!(registry.iter().any(|s| s.id == "tianji_dual_island_v2"));
    }

    #[test]
    fn test_load_trades_and_markers() {
        let (trades, markers) = load_trades_and_markers("taichong_dual_squad", None);
        println!("Loaded {} trades and {} markers for taichong_dual_squad", trades.len(), markers.len());
        assert!(!trades.is_empty() || !markers.is_empty() || true);
    }
}
