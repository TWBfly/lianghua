"""
A-Share & Futures Quantitative Strategy Engine - Comprehensive Data Integrity & Portfolio Test Suite
【期货全量数据质量、北京时间校准与多品种回测自动化测试套件】
"""

import sys
import sqlite3
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"
sys.path.append(str(PROJECT_ROOT / "code"))

from run_real_dominant_portfolio_backtest import RealDominantPortfolioEngine, DOMINANT_COMMODITY_SPECS


def test_metadata_and_bars_perfect_alignment():
    """测试所有 REAL_DOMINANT_CONTRACT 元数据与数据表 1:1 绝对对齐 (每组恰好 8000 根)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, timeframe, row_count, start_time, end_time, source_title
        FROM futures_series_metadata
        WHERE series_type = 'REAL_DOMINANT_CONTRACT' AND source_title LIKE '%(北京时间)%'
        ORDER BY symbol, timeframe;
    """)
    meta_rows = cursor.fetchall()
    assert len(meta_rows) >= 34, f"期望至少 34 组北京时间真实主力时序，实际仅 {len(meta_rows)} 组"

    for sym, tf, expected_cnt, start_t, end_t, title in meta_rows:
        cursor.execute(f"SELECT count(*), min(trade_time), max(trade_time) FROM futures_min_bars WHERE symbol='{sym}' AND timeframe='{tf}'")
        actual_cnt, actual_start, actual_end = cursor.fetchone()

        assert actual_cnt == expected_cnt == 8000, f"[{sym} {tf}] 行数不匹配: actual={actual_cnt}, expected={expected_cnt}"
        assert actual_start == start_t, f"[{sym} {tf}] 起始时间不匹配: actual={actual_start}, meta={start_t}"
        assert actual_end == end_t, f"[{sym} {tf}] 结束时间不匹配: actual={actual_end}, meta={end_t}"

    conn.close()


def test_beijing_time_session_validity():
    """测试时间戳是否完全符合中国期货交易所交易时段（消除 8 小时 UTC 偏移）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 抽取螺纹钢、铁矿石、沪金的最新 500 根 5m K 线进行时段校验
    for sym in ["RB_IDX", "I_IDX", "AU_IDX"]:
        df = pd.read_sql_query(f"SELECT trade_time FROM futures_min_bars WHERE symbol='{sym}' AND timeframe='5m' ORDER BY trade_time DESC LIMIT 500", conn)
        df["dt"] = pd.to_datetime(df["trade_time"])
        hours = df["dt"].dt.hour.unique()

        # 中国期货市场交易时间为：
        # 早盘: 09:00 - 11:30 (小时: 9, 10, 11)
        # 午盘: 13:30 - 15:00 (小时: 13, 14, 15)
        # 夜盘: 21:00 - 02:30 (小时: 21, 22, 23, 0, 1, 2)
        valid_hours = {9, 10, 11, 13, 14, 15, 21, 22, 23, 0, 1, 2}
        for h in hours:
            assert h in valid_hours, f"[{sym}] 发现非交易时段异常小时: {h}点 (说明存在未校准的时区偏移！)"

    conn.close()


def test_ohlc_invariants_across_all_dominant_symbols():
    """测试所有 17 个主力品种数据无几何倒挂且价格严格大于 0"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT count(*) FROM futures_min_bars
        WHERE symbol IN (SELECT symbol FROM futures_series_metadata WHERE series_type = 'REAL_DOMINANT_CONTRACT')
          AND (high < low 
            OR high < open 
            OR high < close 
            OR low > open 
            OR low > close 
            OR open <= 0 
            OR high <= 0 
            OR low <= 0 
            OR close <= 0);
    """)
    invalid_cnt = cursor.fetchone()[0]
    assert invalid_cnt == 0, f"发现 {invalid_cnt} 根存在物理几何倒挂或非正价格的异常 K 线！"
    conn.close()


def test_multi_commodity_backtest_with_winsorization():
    """测试带软截断与动态内存重采样的多品种解耦生产回测引擎"""
    from symbol_strategies.decoupled_symbol_engines import DecoupledSymbolStrategyRunner
    runner = DecoupledSymbolStrategyRunner()
    test_symbols = ["AU_IDX", "AG_IDX", "RB_IDX", "SC_IDX", "MA_IDX"]

    for sym in test_symbols:
        res = runner.run_single_symbol_backtest(sym, initial_capital=500000.0)
        assert res["total_trades"] > 0, f"品种 {sym} 应该产生交易"
        assert res["final_equity"] > 0, f"品种 {sym} 期末权益应为正"
        assert 0.0 <= res["win_rate_pct"] <= 100.0, f"品种 {sym} 胜率应在 0~100 之间"
        assert 7900 <= res["total_bars"] <= 8000, f"品种 {sym} 15m 特征预热后有效K线数应在 7900~8000 之间，实际: {res['total_bars']}"


def test_futures_data_contract_enforcement():
    """测试 data_contract.py 中的 validate_futures_universe 对全量25个主力品种在5m和15m进行契约拦截验证"""
    from data_contract import validate_futures_universe, DataContractError
    conn = sqlite3.connect(DB_PATH)
    symbols = [
        "AU", "AG", "SA", "I", "CU", "SC", "RB", "HC", "J", "JM",
        "AL", "ZN", "SN", "RU", "M", "P", "LC", "MA", "TA", "FG",
        "SR", "CF", "C", "Y", "SI"
    ]
    for tf in ["5m", "15m"]:
        provenances = validate_futures_universe(conn, symbols, timeframe=tf)
        assert len(provenances) == 25
        for p in provenances:
            assert p["verification_status"] == "VERIFIED_REAL_DOMINANT"
            assert "(北京时间)" in p["source_title"]
            assert p["row_count"] == 8000
    conn.close()

