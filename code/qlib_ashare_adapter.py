"""
Qlib A-Share Data and Feature Adapter.
Bridges local clean SQLite A-share daily bars into Qlib Dataset format for alpha research.

Features:
- Validates data contract via data_contract.py (RESEARCH_PROXY / QFQ)
- Extracts causal multi-factor features (Momentum, Volatility, Volume Z-Score, ATR, Trend, Reversion)
- Generates forward label (e.g., N-day forward relative/absolute return)
- Converts to Qlib multi-index dataset protocol [('feature', name), ('label', 'label')]
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import pandas as pd

CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parent

from data_contract import validate_stock_universe, DataContractError
import qlib_model_adapter
from alpha_factor_miner import FactorRegistry


STOCK_FEATURE_COLUMNS = tuple(FactorRegistry.list_factors())


@dataclass
class QlibAShareDataset:
    train_df: pd.DataFrame
    valid_df: pd.DataFrame
    test_df: pd.DataFrame
    features: Tuple[str, ...]
    train_dates: Tuple[str, str]
    valid_dates: Tuple[str, str]
    test_dates: Tuple[str, str]
    symbols: List[str]


def calculate_ashare_features(df_symbol: pd.DataFrame, label_horizon: int = 5, factor_names: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """
    Calculate causal quant alpha features for a single stock time series using FactorRegistry.
    Input df_symbol must have columns: trade_date, open, high, low, close, volume, amount, turnover_rate
    """
    df = df_symbol.sort_values("trade_date").copy()
    close = df["close"].astype(float)
    
    target_factors = factor_names or FactorRegistry.list_factors()
    for name in target_factors:
        func = FactorRegistry.get_factor(name)
        if func is not None:
            df[name] = func(df)

    # Label: Forward N-day relative return
    df["label"] = close.shift(-label_horizon) / close - 1.0
    return df


def load_ashare_dataset(
    db_path: Path | str,
    symbols: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    train_ratio: float = 0.60,
    valid_ratio: float = 0.20,
    label_horizon: int = 5,
    min_stock_rows: int = 250,
) -> QlibAShareDataset:
    """
    Load data from SQLite, validate contract, compute features and create train/valid/test datasets.
    """
    db_file = Path(db_path).resolve()
    with sqlite3.connect(db_file) as conn:
        if symbols is None:
            # Query all cataloged stocks
            catalog_rows = conn.execute("""
                SELECT symbol FROM stock_daily_catalog 
                WHERE asset_type='STOCK' AND price_mode='QFQ' AND row_count >= ?
                ORDER BY row_count DESC;
            """, (min_stock_rows,)).fetchall()
            symbols = [row[0] for row in catalog_rows]

        if not symbols:
            raise ValueError("No qualified stocks found in database")

        # Determine effective date range from catalog if not explicitly set or bounded
        placeholders = ",".join("?" for _ in symbols)
        cat_info = conn.execute(f"""
            SELECT MAX(start_date), MIN(end_date)
            FROM stock_daily_catalog
            WHERE symbol IN ({placeholders}) AND asset_type='STOCK';
        """, tuple(symbols)).fetchone()

        max_start, min_end = cat_info if cat_info else (None, None)
        if start_date is None:
            start_date = max_start or "2022-01-04"
        elif max_start and start_date < max_start:
            start_date = max_start

        if end_date is None:
            end_date = min_end or "2026-08-06"
        elif min_end and end_date > min_end:
            end_date = min_end

        # Validate contract for the universe
        validate_stock_universe(conn, symbols, start_date, end_date, backtest_mode="RESEARCH_PROXY")

        # Load daily data in bulk
        query = f"""
            SELECT symbol, trade_date, open, close, high, low, volume, amount, turnover_rate
            FROM stock_daily
            WHERE symbol IN ({placeholders}) AND trade_date >= ? AND trade_date <= ?
            ORDER BY symbol, trade_date ASC;
        """
        raw_df = pd.read_sql_query(query, conn, params=(*symbols, start_date, end_date))

    if raw_df.empty:
        raise ValueError("No stock daily data loaded for specified symbols and date range")

    # Compute features symbol by symbol
    feature_dfs = []
    for sym, group in raw_df.groupby("symbol", sort=False):
        if len(group) < 60:
            continue
        feat_df = calculate_ashare_features(group, label_horizon=label_horizon)
        feature_dfs.append(feat_df)

    if not feature_dfs:
        raise ValueError("Failed to calculate features: insufficient rows")

    full_df = pd.concat(feature_dfs, ignore_index=True)
    full_df["trade_date"] = pd.to_datetime(full_df["trade_date"])
    full_df = full_df.sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    # Time-based train / valid / test split to ensure zero future leakage
    unique_dates = sorted(full_df["trade_date"].unique())
    n_dates = len(unique_dates)
    train_end_idx = int(n_dates * train_ratio)
    valid_end_idx = int(n_dates * (train_ratio + valid_ratio))

    train_dates = (str(unique_dates[0])[:10], str(unique_dates[train_end_idx - 1])[:10])
    valid_dates = (str(unique_dates[train_end_idx])[:10], str(unique_dates[valid_end_idx - 1])[:10])
    test_dates = (str(unique_dates[valid_end_idx])[:10], str(unique_dates[-1])[:10])

    train_df = full_df[full_df["trade_date"] < unique_dates[train_end_idx]].dropna(subset=[*STOCK_FEATURE_COLUMNS, "label"]).copy()
    valid_df = full_df[(full_df["trade_date"] >= unique_dates[train_end_idx]) & (full_df["trade_date"] < unique_dates[valid_end_idx])].dropna(subset=[*STOCK_FEATURE_COLUMNS, "label"]).copy()
    test_df = full_df[full_df["trade_date"] >= unique_dates[valid_end_idx]].dropna(subset=STOCK_FEATURE_COLUMNS).copy()

    return QlibAShareDataset(
        train_df=train_df,
        valid_df=valid_df,
        test_df=test_df,
        features=STOCK_FEATURE_COLUMNS,
        train_dates=train_dates,
        valid_dates=valid_dates,
        test_dates=test_dates,
        symbols=symbols,
    )


def convert_to_qlib_dataset(dataset: QlibAShareDataset):
    """
    Convert QlibAShareDataset into Qlib _FrameDataset format.
    """
    train = pd.concat({
        "feature": dataset.train_df[list(dataset.features)].reset_index(drop=True),
        "label": dataset.train_df[["label"]].reset_index(drop=True),
    }, axis=1)
    
    valid = pd.concat({
        "feature": dataset.valid_df[list(dataset.features)].reset_index(drop=True),
        "label": dataset.valid_df[["label"]].reset_index(drop=True),
    }, axis=1)

    test = pd.concat({
        "feature": dataset.test_df[list(dataset.features)].reset_index(drop=True),
    }, axis=1)

    return qlib_model_adapter._FrameDataset(train, test), valid
