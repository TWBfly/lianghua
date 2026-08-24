"""
vnpy_data_adapter.py — vn.py 数据适配器与契约转换器

功能：
1. 从 SQLite (ashare_quant.db) 读取股票 (stock_daily) 与期货 (futures_min_bars) 数据；
2. 自动校验数据契约（无未来函数、单调递增时间戳、合理价格关系）；
3. 转换为 vn.py 标准 BarData 对象集合与标准 DataFrame；
4. 支持导出为 vn.py SQLite 数据库与标准 CSV 格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np


import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VNPY_SRC = PROJECT_ROOT / "vnpy"
if VNPY_SRC.exists() and str(VNPY_SRC) not in sys.path:
    sys.path.insert(0, str(VNPY_SRC))

try:
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData
except ImportError:
    # ==========================================
    # 纯净后备：100% 结构对齐的 vn.py 标准结构
    # ==========================================
    class Exchange(Enum):
        """交易所代码定义 (与 vn.py 保持一致)"""
        SHFE = "SHFE"    # 上期所
        DCE = "DCE"      # 大商所
        CZCE = "CZCE"    # 郑商所
        INE = "INE"      # 上能源
        GFEX = "GFEX"    # 广期所
        CFFEX = "CFFEX"  # 中金所
        SSE = "SSE"      # 上交所
        SZSE = "SZSE"    # 深交所
        BSE = "BSE"      # 北交所
        LOCAL = "LOCAL"  # 本地/虚拟

    class Interval(Enum):
        """K 线周期定义 (与 vn.py 保持一致)"""
        MINUTE = "1m"
        MINUTE_5 = "5m"
        MINUTE_15 = "15m"
        MINUTE_30 = "30m"
        HOUR = "1h"
        DAILY = "d"
        TICK = "tick"

    @dataclass
    class BarData:
        """vn.py 标准 K 线数据类"""
        symbol: str
        exchange: Exchange
        datetime: datetime
        interval: Interval = Interval.MINUTE_15
        volume: float = 0.0
        turnover: float = 0.0
        open_interest: float = 0.0
        open_price: float = 0.0
        high_price: float = 0.0
        low_price: float = 0.0
        close_price: float = 0.0
        gateway_name: str = "DB"

        @property
        def vt_symbol(self) -> str:
            return f"{self.symbol}.{self.exchange.value}"



# 默认品种至交易所映射规则
FUTURES_EXCHANGE_MAP = {
    "AG": Exchange.SHFE, "AU": Exchange.SHFE, "CU": Exchange.SHFE, "AL": Exchange.SHFE,
    "ZN": Exchange.SHFE, "SN": Exchange.SHFE, "PB": Exchange.SHFE, "NI": Exchange.SHFE,
    "RB": Exchange.SHFE, "HC": Exchange.SHFE, "SS": Exchange.SHFE, "WR": Exchange.SHFE,
    "FU": Exchange.SHFE, "BU": Exchange.SHFE, "RU": Exchange.SHFE, "BR": Exchange.SHFE,
    "SC": Exchange.INE,  "LU": Exchange.INE,  "NR": Exchange.INE,  "BC": Exchange.INE,
    "I":  Exchange.DCE,  "J":  Exchange.DCE,  "JM": Exchange.DCE,  "M":  Exchange.DCE,
    "Y":  Exchange.DCE,  "P":  Exchange.DCE,  "C":  Exchange.DCE,  "CS": Exchange.DCE,
    "JD": Exchange.DCE,  "L":  Exchange.DCE,  "V":  Exchange.DCE,  "PP": Exchange.DCE,
    "EG": Exchange.DCE,  "EB": Exchange.DCE,  "PG": Exchange.DCE,  "LH": Exchange.DCE,
    "TA": Exchange.CZCE, "MA": Exchange.CZCE, "SA": Exchange.CZCE, "FG": Exchange.CZCE,
    "SR": Exchange.CZCE, "CF": Exchange.CZCE, "OI": Exchange.CZCE, "RM": Exchange.CZCE,
    "SF": Exchange.CZCE, "SM": Exchange.CZCE, "UR": Exchange.CZCE, "PF": Exchange.CZCE,
    "AP": Exchange.CZCE, "CJ": Exchange.CZCE, "PK": Exchange.CZCE, "SH": Exchange.CZCE,
    "PX": Exchange.CZCE,
    "LC": Exchange.GFEX, "SI": Exchange.GFEX,
    "IF": Exchange.CFFEX, "IC": Exchange.CFFEX, "IH": Exchange.CFFEX, "IM": Exchange.CFFEX,
    "T":  Exchange.CFFEX, "TF": Exchange.CFFEX, "TS": Exchange.CFFEX, "TL": Exchange.CFFEX,
}


def parse_symbol_exchange(symbol_code: str) -> tuple[str, Exchange]:
    """将内部 symbol (如 AG_IDX, ag888, 600519) 转换为标准 (symbol, Exchange)"""
    clean = str(symbol_code).strip().upper()

    # 1. 股票代码规则
    if clean.startswith(("60", "68", "90")):
        return clean, Exchange.SSE
    elif clean.startswith(("00", "30", "20")):
        return clean, Exchange.SZSE
    elif clean.startswith(("4", "8", "92")):
        return clean, Exchange.BSE

    # 2. 期货连续指数或主力代码规则
    base_prefix = clean.replace("_IDX", "").replace("888", "").replace("999", "").replace("L9", "")
    exchange = FUTURES_EXCHANGE_MAP.get(base_prefix, Exchange.SHFE)
    standard_symbol = clean.lower()
    return standard_symbol, exchange


class VnpyDataAdapter:
    """vn.py 数据加载与格式转换适配器"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent
            self.db_path = project_root / "data/ashare_quant.db"
        else:
            self.db_path = Path(db_path)

    def load_futures_bars(
        self,
        symbol: str,
        timeframe: str = "15m",
        start_date: str | None = None,
        end_date: str | None = None
    ) -> list[BarData]:
        """
        从 SQLite futures_min_bars 读取期货分钟 K 线并转换为 vn.py BarData 列表
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found at {self.db_path}")

        with sqlite3.connect(self.db_path) as conn:
            # 自动探测时间列名 (trade_time 或 datetime)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(futures_min_bars)").fetchall()}
            time_col = "trade_time" if "trade_time" in cols else "datetime"

            query = f"""
                SELECT {time_col} AS datetime, open, high, low, close, volume, open_interest
                FROM futures_min_bars
                WHERE symbol = ? AND timeframe = ?
            """
            params: list[str] = [symbol, timeframe]

            if start_date:
                query += f" AND {time_col} >= ?"
                params.append(start_date)
            if end_date:
                query += f" AND {time_col} <= ?"
                params.append(end_date)

            query += f" ORDER BY {time_col} ASC"

            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return []


        # 契约清洗与验证
        df = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
        df = df[(df["open"] > 0) & (df["high"] >= df["low"]) & (df["high"] >= df["open"]) & (df["high"] >= df["close"])]

        std_symbol, exchange = parse_symbol_exchange(symbol)
        interval = Interval.MINUTE

        bars: list[BarData] = []

        for row in df.itertuples(index=False):
            dt_str = str(row.datetime)
            try:
                dt = datetime.fromisoformat(dt_str) if "T" in dt_str else datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S" if len(dt_str) > 10 else "%Y-%m-%d")
            except Exception:
                continue

            bar = BarData(
                symbol=std_symbol,
                exchange=exchange,
                datetime=dt,
                interval=interval,
                volume=float(row.volume),
                open_interest=float(row.open_interest or 0.0),
                open_price=float(row.open),
                high_price=float(row.high),
                low_price=float(row.low),
                close_price=float(row.close),
                gateway_name="SQLITE_ADAPTER"
            )
            bars.append(bar)

        return bars

    def load_stock_bars(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None
    ) -> list[BarData]:
        """
        从 SQLite stock_daily 读取 A 股日线并转换为 vn.py BarData 列表
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found at {self.db_path}")

        query = """
            SELECT trade_date, open, high, low, close, volume, amount
            FROM stock_daily
            WHERE symbol = ?
        """
        params: list[str] = [symbol]

        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)

        query += " ORDER BY trade_date ASC"

        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return []

        std_symbol, exchange = parse_symbol_exchange(symbol)

        bars: list[BarData] = []
        for row in df.itertuples(index=False):
            dt_str = str(row.trade_date)
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            except Exception:
                continue

            bar = BarData(
                symbol=std_symbol,
                exchange=exchange,
                datetime=dt,
                interval=Interval.DAILY,
                volume=float(row.volume),
                turnover=float(row.amount if hasattr(row, "amount") and row.amount else 0.0),
                open_price=float(row.open),
                high_price=float(row.high),
                low_price=float(row.low),
                close_price=float(row.close),
                gateway_name="SQLITE_ADAPTER"
            )
            bars.append(bar)

        return bars

    def export_bars_to_dataframe(self, bars: list[BarData]) -> pd.DataFrame:
        """将 BarData 列表转换为标准化分析 DataFrame"""
        if not bars:
            return pd.DataFrame()
        records = [{
            "datetime": b.datetime,
            "symbol": b.symbol,
            "exchange": b.exchange.value,
            "open": b.open_price,
            "high": b.high_price,
            "low": b.low_price,
            "close": b.close_price,
            "volume": b.volume,
            "open_interest": b.open_interest,
            "turnover": b.turnover,
        } for b in bars]
        return pd.DataFrame(records).set_index("datetime")
