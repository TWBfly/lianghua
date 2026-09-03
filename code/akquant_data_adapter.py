"""
akquant_data_adapter.py — AKQuant 数据适配器与格式转换桥接器

核心职责：
1. 从 lianghua 系统的 SQLite (ashare_quant.db) 或 CSV/Parquet 读取股票与期货数据；
2. 遵循 data_contract.py 因果契约（时间单调递增、严禁未来函数、高低开收合法）；
3. 转换为 AKQuant 引擎所需的标准数据字典或 Polars/Pandas DataFrame (支持 zero-copy 数组导入)；
4. 彻底解耦上游 akquant 数据结构变动，保证对外输出格式纯净稳定。
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AKQUANT_SRC = PROJECT_ROOT / "akquant" / "python"
if AKQUANT_SRC.exists() and str(AKQUANT_SRC) not in sys.path:
    sys.path.insert(0, str(AKQUANT_SRC))

logger = logging.getLogger("akquant_data_adapter")


@dataclass
class StandardBar:
    """标准化通用 K 线结构 (解耦内部与外部格式)"""
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0
    turnover: float = 0.0


class AkquantDataAdapter:
    """AKQuant 数据适配转换器"""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            self.db_path = PROJECT_ROOT / "data" / "ashare_quant.db"
        else:
            self.db_path = Path(db_path)

    def load_futures_dataframe(
        self,
        symbol: str,
        timeframe: str = "15m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        从 SQLite futures_min_bars 或指定 CSV 读取期货分钟 K 线，
        转换为 AKQuant 标准回测 DataFrame (包含 date/timestamp, open, high, low, close, volume)。
        """
        clean_symbol = symbol.strip().upper()
        clean_code = clean_symbol.replace("_IDX", "").lower()

        df = pd.DataFrame()

        # 1. 尝试从 SQLite 读取
        if self.db_path.exists():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cols = {
                        row[1]
                        for row in conn.execute(
                            "PRAGMA table_info(futures_min_bars)"
                        ).fetchall()
                    }
                    time_col = "trade_time" if "trade_time" in cols else "datetime"

                    query = f"""
                        SELECT {time_col} AS datetime, open, high, low, close, volume, open_interest
                        FROM futures_min_bars
                        WHERE (symbol = ? OR symbol = ? OR symbol = ?) AND timeframe = ?
                    """
                    params = [clean_symbol, clean_code, f"{clean_code}888", timeframe]

                    if start_date:
                        query += f" AND {time_col} >= ?"
                        params.append(start_date)
                    if end_date:
                        query += f" AND {time_col} <= ?"
                        params.append(end_date)

                    query += f" ORDER BY {time_col} ASC"

                    df = pd.read_sql_query(query, conn, params=params)
            except Exception as e:
                logger.warning(f"Failed to load from SQLite for {symbol}: {e}")

        # 2. 若数据库为空，尝试从 data/futures_15m_real/ 等文件读取
        if df.empty:
            candidates = [
                PROJECT_ROOT / f"data/futures_15m_real/{clean_symbol}.csv",
                PROJECT_ROOT / f"data/futures_15m_real/{clean_code}.csv",
                PROJECT_ROOT / f"data/{clean_symbol}.csv",
            ]
            for cand in candidates:
                if cand.exists():
                    try:
                        df_raw = pd.read_csv(cand)
                        # 字段标准化
                        dt_col = next(
                            (c for c in df_raw.columns if c.lower() in ("datetime", "trade_time", "date", "time")),
                            None
                        )
                        if dt_col:
                            df_raw = df_raw.rename(columns={dt_col: "datetime"})
                            df = df_raw
                            break
                    except Exception as e:
                        logger.warning(f"Failed to read CSV {cand}: {e}")

        if df.empty:
            logger.info(f"No data found for {symbol} ({timeframe})")
            return pd.DataFrame()

        # 3. 因果契约清洗与合法性校验
        df = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0
        if "open_interest" in df.columns:
            df["open_interest"] = df["open_interest"].astype(float)
        else:
            df["open_interest"] = 0.0

        # 过滤价格异常
        df = df[
            (df["open"] > 0)
            & (df["high"] >= df["low"])
            & (df["high"] >= df["open"])
            & (df["high"] >= df["close"])
            & (df["low"] <= df["open"])
            & (df["low"] <= df["close"])
        ]

        # 格式化日期列
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"] = df["datetime"]
        df["symbol"] = clean_code

        # 过滤日期区间
        if start_date:
            df = df[df["datetime"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["datetime"] <= pd.to_datetime(end_date)]

        return df

    def load_stock_dataframe(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        从 SQLite stock_daily 读取 A 股日线数据并转换为 AKQuant 标准 DataFrame。
        """
        clean_symbol = symbol.strip().upper()
        df = pd.DataFrame()

        if self.db_path.exists():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    query = """
                        SELECT trade_date AS datetime, open, high, low, close, volume, amount
                        FROM stock_daily
                        WHERE symbol = ?
                    """
                    params = [clean_symbol]

                    if start_date:
                        query += " AND trade_date >= ?"
                        params.append(start_date)
                    if end_date:
                        query += " AND trade_date <= ?"
                        params.append(end_date)

                    query += " ORDER BY trade_date ASC"
                    df = pd.read_sql_query(query, conn, params=params)
            except Exception as e:
                logger.warning(f"Failed to load stock data from SQLite for {symbol}: {e}")

        if df.empty:
            return pd.DataFrame()

        df = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"] = df["datetime"]
        df["symbol"] = clean_symbol
        return df

    def convert_for_akquant_feed(
        self,
        symbols_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """
        格式化并打包为 AKQuant run_backtest 所要求的字典结构：
        {
            "symbol_1": DataFrame(date, open, high, low, close, volume, ...),
            "symbol_2": ...
        }
        """
        feed = {}
        for sym, df in symbols_data.items():
            if df.empty:
                continue
            formatted = df.copy()
            if "date" not in formatted.columns and "datetime" in formatted.columns:
                formatted["date"] = formatted["datetime"]
            feed[sym] = formatted
        return feed
