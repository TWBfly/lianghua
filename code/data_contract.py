from __future__ import annotations

import sqlite3
from pathlib import Path

from market_data import MarketDataError


class DataContractError(MarketDataError):
    def __init__(self, message, error_code="DATA_CONTRACT_INVALID"):
        super().__init__(message)
        self.error_code = error_code


def ensure_asset_type_column(conn):
    columns = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(stock_daily_catalog)"
        )
    }
    if "asset_type" not in columns:
        conn.execute(
            "ALTER TABLE stock_daily_catalog ADD COLUMN "
            "asset_type TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED'"
        )


def _reject_symbol(symbol):
    value = str(symbol).strip().upper()
    if value.endswith("_IDX"):
        raise DataContractError(
            f"{value} is a futures index, not a stock asset",
            "ASSET_TYPE_MISMATCH",
        )
    return value


def validate_stock_contract(conn, symbol, start_date, end_date, backtest_mode):
    value = _reject_symbol(symbol)
    if backtest_mode not in {"STRICT", "RESEARCH_PROXY"}:
        raise DataContractError(
            "invalid stock backtest mode", "INVALID_BACKTEST_MODE"
        )
    ensure_asset_type_column(conn)
    catalog = conn.execute("""
        SELECT symbol, asset_type, price_mode, source, start_date, end_date,
               row_count, updated_at
        FROM stock_daily_catalog WHERE symbol=?
    """, (value,)).fetchone()
    if catalog is None:
        raise DataContractError(
            f"stock symbol {value} has no catalog provenance",
            "UNCATALOGED_STOCK",
        )
    keys = (
        "symbol", "asset_type", "price_mode", "source", "start_date",
        "end_date", "row_count", "updated_at",
    )
    provenance = dict(zip(keys, catalog))
    if provenance["asset_type"] not in {"STOCK", "ETF"}:
        raise DataContractError(
            f"stock symbol {value} has unverified asset type",
            "UNVERIFIED_ASSET_TYPE",
        )
    actual = conn.execute("""
        SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
        FROM stock_daily WHERE symbol=?
    """, (value,)).fetchone()
    if tuple(actual) != (
        provenance["start_date"], provenance["end_date"], provenance["row_count"]
    ):
        raise DataContractError(
            f"stock catalog coverage mismatch for {value}",
            "CATALOG_COVERAGE_MISMATCH",
        )
    if provenance["start_date"] > start_date or provenance["end_date"] < end_date:
        raise DataContractError(
            f"stock data does not cover requested range for {value}",
            "INSUFFICIENT_DATA_COVERAGE",
        )
    if provenance["price_mode"] not in {"RAW", "QFQ"}:
        raise DataContractError(
            f"stock symbol {value} has unknown price mode",
            "UNKNOWN_PRICE_MODE",
        )
    if backtest_mode == "STRICT" and provenance["price_mode"] != "RAW":
        raise DataContractError(
            "strict stock backtest requires RAW prices",
            "RAW_EXECUTION_UNAVAILABLE",
        )
    provenance["verification_status"] = "VERIFIED"
    provenance["price_semantics"] = (
        "RAW_EXECUTION" if provenance["price_mode"] == "RAW"
        else "ADJUSTED_PROXY"
    )
    return provenance


def validate_stock_universe(conn, symbols, start_date, end_date, backtest_mode):
    values = [str(symbol).strip().upper() for symbol in symbols]
    if not values or len(set(values)) != len(values):
        raise DataContractError("stock universe must be non-empty and unique")
    return [
        validate_stock_contract(
            conn, value, start_date, end_date, backtest_mode
        )
        for value in values
    ]


def audit_database(db_path):
    path = Path(db_path)
    if not path.is_file():
        raise DataContractError("database is missing", "DATABASE_MISSING")
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        catalog_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(stock_daily_catalog)"
            )
        }
        asset_type_available = "asset_type" in catalog_columns
        stock = conn.execute("""
            SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols,
                   SUM(symbol LIKE '%_IDX') AS index_rows
            FROM stock_daily
        """).fetchone()
        uncataloged = conn.execute("""
            SELECT COUNT(DISTINCT d.symbol) FROM stock_daily d
            LEFT JOIN stock_daily_catalog c ON c.symbol=d.symbol
            WHERE c.symbol IS NULL
        """).fetchone()[0]
        asset_type_clause = (
            "c.asset_type='LEGACY_UNVERIFIED'"
            if asset_type_available else "1=1"
        )
        mismatch = conn.execute(f"""
            SELECT COUNT(*) FROM stock_daily_catalog c
            WHERE {asset_type_clause}
               OR c.row_count != (
                   SELECT COUNT(*) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.start_date != (
                   SELECT MIN(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.end_date != (
                   SELECT MAX(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
        """).fetchone()[0]
        futures = (
            conn.execute("""
                SELECT COUNT(*) rows, COUNT(DISTINCT symbol) symbols,
                       SUM(volume=0) zero_volume
                FROM futures_min_bars WHERE timeframe='5m'
            """).fetchone()
            if "futures_min_bars" in tables else (0, 0, 0)
        )
    return {
        "stock": {
            "rows": stock[0], "symbols": stock[1],
            "index_rows": stock[2] or 0,
            "uncataloged_symbols": uncataloged,
            "catalog_mismatch_count": mismatch,
        },
        "futures_5m": {
            "rows": futures[0], "symbols": futures[1],
            "zero_volume": futures[2] or 0,
        },
    }


def validate_futures_contract(conn: sqlite3.Connection, symbol: str, timeframe: str = "15m") -> dict:
    """
    严格校验期货真实主力合约数据契约与血缘规范：
    1. 必须在 futures_series_metadata 中注册为 REAL_DOMINANT_CONTRACT
    2. 必须为北京时间校准版本 (source_title 包含 '(北京时间)')
    3. 表内行数、起止时间必须与元数据 1:1 严格对齐
    4. 无 OHLC 几何倒挂与非正价格
    5. 零成交量占比必须 < 5%
    """
    value = str(symbol).strip().upper()
    if not value.endswith("_IDX"):
        value = f"{value}_IDX"
    tf = str(timeframe).strip().lower()

    # 1. 检查元数据
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, timeframe, series_type, source_file, source_title, row_count, start_time, end_time
        FROM futures_series_metadata
        WHERE symbol = ? AND timeframe = ?
    """, (value, tf))
    meta = cursor.fetchone()
    if meta is None:
        raise DataContractError(f"期货标的 [{value}] 在 [{tf}] 周期无元数据血缘登记！", "UNCATALOGED_FUTURES")

    keys = ("symbol", "timeframe", "series_type", "source_file", "source_title", "row_count", "start_time", "end_time")
    provenance = dict(zip(keys, meta))

    if provenance["series_type"] != "REAL_DOMINANT_CONTRACT":
        raise DataContractError(f"期货标的 [{value} {tf}] 属于合成或非真实主力类型 [{provenance['series_type']}]，禁止直接回测！", "NON_DOMINANT_DATA")

    if "(北京时间)" not in provenance["source_title"]:
        raise DataContractError(f"期货标的 [{value} {tf}] 未通过标准北京时间时区校准！", "UNALIGNED_TIMEZONE")

    # 2. 检查实际表记录与元数据一致性
    actual = cursor.execute("""
        SELECT COUNT(*), MIN(trade_time), MAX(trade_time),
               SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END),
               SUM(CASE
                   WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL
                     OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                     OR volume < 0
                     OR high < low OR high < open OR high < close OR low > open OR low > close
                   THEN 1 ELSE 0 END)
        FROM futures_min_bars
        WHERE symbol = ? AND timeframe = ?
    """, (value, tf)).fetchone()

    actual_cnt, actual_start, actual_end, zero_vol_cnt, ohlc_err_cnt = actual
    ohlc_err_cnt = ohlc_err_cnt or 0
    zero_vol_cnt = zero_vol_cnt or 0
    if actual_cnt != provenance["row_count"]:
        raise DataContractError(f"期货标的 [{value} {tf}] 表内行数 ({actual_cnt}) 与元数据声明 ({provenance['row_count']}) 不一致！", "ROW_COUNT_MISMATCH")

    if actual_start != provenance["start_time"] or actual_end != provenance["end_time"]:
        raise DataContractError(f"期货标的 [{value} {tf}] 表内时段与元数据声明不一致！", "TIME_RANGE_MISMATCH")

    if ohlc_err_cnt > 0:
        raise DataContractError(f"期货标的 [{value} {tf}] 发现 {ohlc_err_cnt} 处数据损坏、缺失、几何倒挂或非正价格/负成交量！", "OHLC_INVARIANT_VIOLATION")

    if zero_vol_cnt / max(1, actual_cnt) > 0.05:
        raise DataContractError(f"期货标的 [{value} {tf}] 零成交量占比高达 {zero_vol_cnt/actual_cnt*100:.1f}%，违反流动性契约！", "ILLIQUID_ASSET")

    provenance["verification_status"] = "VERIFIED_REAL_DOMINANT"
    return provenance


def validate_futures_universe(conn: sqlite3.Connection, symbols: list[str], timeframe: str = "15m") -> list[dict]:
    """批量校验期货品种池数据契约"""
    return [validate_futures_contract(conn, s, timeframe) for s in symbols]


def check_futures_rollover_gaps(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str = "15m",
    gap_pct_threshold: float = 0.03
) -> list[dict]:
    """
    检查未复权主力连续合约中的换月异常跳空 (Rollover Gaps)。
    未复权连续数据在主力换月瞬间易出现 >3% 的基差跳跃，回测持仓穿越跳空点会导致伪 PnL。
    返回所有超过阈值的跳空记录。
    """
    value = str(symbol).strip().upper()
    if not value.endswith("_IDX"):
        value = f"{value}_IDX"
    cursor = conn.cursor()
    cursor.execute("""
        SELECT trade_time, open, high, low, close
        FROM futures_min_bars
        WHERE symbol = ? AND timeframe = ?
        ORDER BY trade_time ASC
    """, (value, str(timeframe).strip().lower()))
    rows = cursor.fetchall()
    if len(rows) < 2:
        return []

    gaps = []
    for i in range(1, len(rows)):
        prev_close = rows[i - 1][4]
        curr_open = rows[i][1]
        if prev_close and prev_close > 0:
            jump = (curr_open - prev_close) / prev_close
            if abs(jump) >= gap_pct_threshold:
                gaps.append({
                    "symbol": value,
                    "timeframe": timeframe,
                    "prev_time": rows[i - 1][0],
                    "trade_time": rows[i][0],
                    "prev_close": prev_close,
                    "curr_open": curr_open,
                    "gap_pct": round(jump * 100.0, 3)
                })
    return gaps


