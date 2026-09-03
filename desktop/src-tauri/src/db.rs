use chrono::{NaiveDate, NaiveDateTime};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct KlineBar {
    pub time: i64, // Unix timestamp in seconds
    pub datetime_str: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub amount: Option<f64>,
    pub open_interest: Option<f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct StockBasicItem {
    pub symbol: String,
    pub name: String,
    pub price: f64,
    pub pe_ttm: f64,
    pub pb: f64,
    pub total_mv: f64,
}

pub fn get_db_path() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let db_path = manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("data").join("ashare_quant.db"))
        .unwrap_or_else(|| PathBuf::from("/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"));
    
    if db_path.exists() {
        db_path
    } else {
        PathBuf::from("/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db")
    }
}

pub fn get_synthetic_db_path() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let db_path = manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("data").join("synthetic_sandbox").join("futures_synthetic_bars.db"))
        .unwrap_or_else(|| PathBuf::from("/Users/tang/PycharmProjects/pythonProject/lianghua/data/synthetic_sandbox/futures_synthetic_bars.db"));

    if db_path.exists() {
        db_path
    } else {
        PathBuf::from("/Users/tang/PycharmProjects/pythonProject/lianghua/data/synthetic_sandbox/futures_synthetic_bars.db")
    }
}

pub fn parse_trade_time(dt_str: &str) -> i64 {
    let dt_str = dt_str.trim();
    if dt_str.contains(' ') {
        if let Ok(dt) = NaiveDateTime::parse_from_str(dt_str, "%Y-%m-%d %H:%M:%S") {
            return dt.and_utc().timestamp();
        }
        if let Ok(dt) = NaiveDateTime::parse_from_str(dt_str, "%Y-%m-%d %H:%M") {
            return dt.and_utc().timestamp();
        }
    } else {
        if let Ok(d) = NaiveDate::parse_from_str(dt_str, "%Y-%m-%d") {
            return d.and_hms_opt(15, 0, 0).unwrap().and_utc().timestamp();
        }
        if let Ok(d) = NaiveDate::parse_from_str(dt_str, "%Y%m%d") {
            return d.and_hms_opt(15, 0, 0).unwrap().and_utc().timestamp();
        }
    }
    0
}

pub fn query_futures_kline(
    symbol: &str,
    timeframe: &str,
    limit: usize,
) -> Result<Vec<KlineBar>, String> {
    let db_path = get_db_path();
    let conn = Connection::open(&db_path).map_err(|e| format!("Failed to open DB: {}", e))?;

    let sql = "SELECT trade_time, open, high, low, close, volume, amount, open_interest 
               FROM futures_min_bars 
               WHERE symbol = ? AND timeframe = ? 
               ORDER BY trade_time DESC LIMIT ?";

    let mut stmt = conn.prepare(sql).map_err(|e| format!("Query prepare failed: {}", e))?;
    let rows = stmt
        .query_map(params![symbol, timeframe, limit as i64], |row| {
            let dt_str: String = row.get(0)?;
            let ts = parse_trade_time(&dt_str);
            Ok(KlineBar {
                time: ts,
                datetime_str: dt_str,
                open: row.get(1)?,
                high: row.get(2)?,
                low: row.get(3)?,
                close: row.get(4)?,
                volume: row.get(5)?,
                amount: row.get(6).ok(),
                open_interest: row.get(7).ok(),
            })
        })
        .map_err(|e| format!("Query map failed: {}", e))?;

    let mut bars = Vec::new();
    for row in rows {
        if let Ok(b) = row {
            if b.time > 0 {
                bars.push(b);
            }
        }
    }
    bars.reverse();
    Ok(bars)
}

pub fn query_synthetic_futures_kline(
    symbol: &str,
    timeframe: &str,
    limit: usize,
) -> Result<Vec<KlineBar>, String> {
    let db_path = get_synthetic_db_path();
    if !db_path.exists() {
        return Err("虚拟K线数据库 (futures_synthetic_bars.db) 暂未就绪".to_string());
    }
    let conn = Connection::open(&db_path).map_err(|e| format!("Failed to open synthetic DB: {}", e))?;

    let sym_clean = symbol.to_lowercase().replace("_idx", "_idx");
    let tf_clean = match timeframe {
        "15m" | "30m" | "1h" => timeframe,
        _ => "15m",
    };
    let tbl = format!("bars_{}_{}", sym_clean, tf_clean);

    let sql = format!(
        "SELECT trade_time, open, high, low, close, volume FROM {} ORDER BY trade_time DESC LIMIT ?",
        tbl
    );
    let mut stmt = conn.prepare(&sql).map_err(|e| format!("Query synthetic failed for table {}: {}", tbl, e))?;
    let rows = stmt
        .query_map(params![limit as i64], |row| {
            let dt_str: String = row.get(0)?;
            let ts = parse_trade_time(&dt_str);
            Ok(KlineBar {
                time: ts,
                datetime_str: dt_str,
                open: row.get(1)?,
                high: row.get(2)?,
                low: row.get(3)?,
                close: row.get(4)?,
                volume: row.get(5)?,
                amount: None,
                open_interest: None,
            })
        })
        .map_err(|e| format!("Query map synthetic failed: {}", e))?;

    let mut bars = Vec::new();
    for row in rows {
        if let Ok(b) = row {
            if b.time > 0 {
                bars.push(b);
            }
        }
    }
    bars.reverse();
    Ok(bars)
}

pub fn query_stock_daily(
    symbol: &str,
    limit: usize,
) -> Result<Vec<KlineBar>, String> {
    let db_path = get_db_path();
    let conn = Connection::open(&db_path).map_err(|e| format!("Failed to open DB: {}", e))?;

    let sql = "SELECT trade_date, open, high, low, close, volume, amount 
               FROM stock_daily 
               WHERE symbol = ? 
               ORDER BY trade_date DESC LIMIT ?";

    let mut stmt = conn.prepare(sql).map_err(|e| format!("Query prepare failed: {}", e))?;
    let rows = stmt
        .query_map(params![symbol, limit as i64], |row| {
            let dt_str: String = row.get(0)?;
            let ts = parse_trade_time(&dt_str);
            Ok(KlineBar {
                time: ts,
                datetime_str: dt_str,
                open: row.get(1)?,
                high: row.get(2)?,
                low: row.get(3)?,
                close: row.get(4)?,
                volume: row.get(5)?,
                amount: row.get(6).ok(),
                open_interest: None,
            })
        })
        .map_err(|e| format!("Query map failed: {}", e))?;

    let mut bars = Vec::new();
    for row in rows {
        if let Ok(b) = row {
            if b.time > 0 {
                bars.push(b);
            }
        }
    }
    bars.reverse();
    Ok(bars)
}

pub fn query_stock_basic(query: &str) -> Result<Vec<StockBasicItem>, String> {
    let db_path = get_db_path();
    let conn = Connection::open(&db_path).map_err(|e| format!("Failed to open DB: {}", e))?;

    let query_param = format!("%{}%", query.trim());
    let sql = "SELECT symbol, name, price, pe_ttm, pb, total_mv 
               FROM stock_basic 
               WHERE symbol LIKE ? OR name LIKE ? 
               ORDER BY total_mv DESC LIMIT 30";

    let mut stmt = conn.prepare(sql).map_err(|e| format!("Prepare failed: {}", e))?;
    let rows = stmt
        .query_map(params![query_param, query_param], |row| {
            Ok(StockBasicItem {
                symbol: row.get(0)?,
                name: row.get(1)?,
                price: row.get(2)?,
                pe_ttm: row.get(3).unwrap_or(0.0),
                pb: row.get(4).unwrap_or(0.0),
                total_mv: row.get(5).unwrap_or(0.0),
            })
        })
        .map_err(|e| format!("Query failed: {}", e))?;

    let mut list = Vec::new();
    for r in rows {
        if let Ok(item) = r {
            list.push(item);
        }
    }
    Ok(list)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_query_futures_kline() {
        let bars = query_futures_kline("SN_IDX", "10m", 10).expect("Query failed");
        assert!(!bars.is_empty());
        println!("Successfully queried {} bars for SN_IDX (first time={})", bars.len(), bars[0].datetime_str);
    }

    #[test]
    fn test_query_synthetic_futures_kline() {
        let bars = query_synthetic_futures_kline("AU_IDX", "15m", 100).expect("Synthetic query failed");
        assert!(!bars.is_empty());
        println!("Successfully queried {} synthetic bars for AU_IDX (first time={})", bars.len(), bars[0].datetime_str);
    }

    #[test]
    fn test_query_stock_basic() {
        let res = query_stock_basic("600519").expect("Stock basic query failed");
        assert!(!res.is_empty());
        println!("Successfully found stock: {} - {}", res[0].symbol, res[0].name);
    }
}
