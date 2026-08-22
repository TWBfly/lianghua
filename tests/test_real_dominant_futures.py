"""
Unit tests for Real Dominant Futures Historical Data and Rebar Backtest Engine
【真实期货历史主力合约数据与螺纹钢回测引擎测试套件】
"""

import sys
import sqlite3
import pytest
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from run_real_dominant_rb_backtest import RealRBBacktestEngine
from sync_real_dominant_futures_data import DOMINANT_SYMBOL_MAP, TIMEFRAME_MAP, ensure_db_schema

DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"


def test_dominant_symbol_map():
    assert "RB_IDX" in DOMINANT_SYMBOL_MAP
    assert DOMINANT_SYMBOL_MAP["RB_IDX"]["tq_code"] == "KQ.m@SHFE.rb"
    assert DOMINANT_SYMBOL_MAP["RB_IDX"]["name"] == "螺纹钢主力连续"


def test_db_schema_and_metadata():
    conn = sqlite3.connect(DB_PATH)
    ensure_db_schema(conn)
    cursor = conn.cursor()

    # 验证 5m 与 15m 元数据
    meta_df = pd.read_sql("SELECT * FROM futures_series_metadata WHERE symbol='RB_IDX'", conn)
    assert not meta_df.empty, "RB_IDX 元数据未注册"
    assert set(meta_df["timeframe"]) >= {"5m", "15m"}, "未包含 5m 和 15m 元数据"
    assert all(meta_df["series_type"] == "REAL_DOMINANT_CONTRACT"), "元数据类型必须为 REAL_DOMINANT_CONTRACT"
    conn.close()


def test_dominant_bars_quality():
    conn = sqlite3.connect(DB_PATH)
    for tf in ["5m", "15m"]:
        df = pd.read_sql(f"SELECT * FROM futures_min_bars WHERE symbol='RB_IDX' AND timeframe='{tf}'", conn)
        assert len(df) >= 1000, f"RB_IDX {tf} 数据量不足"
        # 物理合规性检查
        assert (df["high"] >= df["low"]).all()
        assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
        assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
        assert (df["volume"] >= 0).all()
        assert (df["open_interest"] >= 0).all()
    conn.close()


def test_rb_5m_backtest():
    engine = RealRBBacktestEngine(db_path=DB_PATH)
    res_5m = engine.run_backtest(timeframe="5m", initial_capital=500000.0, lots=10)
    assert res_5m["timeframe"] == "5m"
    assert res_5m["total_bars"] > 0
    assert res_5m["eval_bars"] > 0
    assert res_5m["total_trades"] > 0
    assert 0 <= res_5m["win_rate"] <= 100
    assert res_5m["max_drawdown_pct"] >= 0


def test_rb_15m_backtest():
    engine = RealRBBacktestEngine(db_path=DB_PATH)
    res_15m = engine.run_backtest(timeframe="15m", initial_capital=500000.0, lots=10)
    assert res_15m["timeframe"] == "15m"
    assert res_15m["total_bars"] > 0
    assert res_15m["eval_bars"] > 0
    assert res_15m["total_trades"] > 0
    assert 0 <= res_15m["win_rate"] <= 100
    assert res_15m["max_drawdown_pct"] >= 0
