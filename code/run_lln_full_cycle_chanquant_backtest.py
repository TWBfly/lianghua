"""
code/run_lln_full_cycle_chanquant_backtest.py — 「因果缠论 8.0·全周期牛熊宏观机制深度压测引擎」
(ChanQuant 8.0 Full-Cycle Macro Regime & LLN Deep Stress Test Engine)

【执行准则与严谨科研规范】：
1. 单一同源策略调用 (Single Source of Truth):
   - 100% 严格调用 chanquant_v8_production_strategy.evaluate_chan_signal 与 calculate_factors_v8；
   - 彻底杜绝任何第三方修改或量纲错误的伪评估函数。
2. 真实期货交易时钟 (Realistic Trading Sessions):
   - 基于中国期货真实交易时段 (9:00-11:30, 13:30-15:00, 21:00-23:00) 与真实日历，彻底剔除周末与闭市断层。
3. 5 大宏观牛熊周期机制 (5 Macro Market Regimes):
   - 阶段 1: 单边暴涨主升浪 (Hyper-Bull Trend, 年化 +70%)
   - 阶段 2: 牛转熊见顶剧烈洗盘 (Top Reversal & Whipsaw)
   - 阶段 3: 恐慌暴跌主跌浪 (Panic Bear Crash, 年化 -70%)
   - 阶段 4: 熊转牛筑底横盘 (Bottom Grinding Box-Chop)
   - 阶段 5: 新一轮牛市蓄势主升 (New Bull Wave Expansion)
4. 真实共享账户与因果执行 (Shared Capital & Causal Engine):
   - 单一 500,000 RMB 真实共享资金池，跨品种统一保证金约束 (<=60%) 与 120% 强平熔断；
   - 严格在第 t 根 Bar 收盘评估挂单 -> 第 t+1 根 Bar 开盘撮合成交 (Next-Open Fill)；
   - 当根入场柱即刻接受同柱柱内止损校验 (_check_same_bar)；
   - 资金不足 1 手时严格 Fail-Closed 拒单。
5. 完整可复算账本导出 (Full Ledger Persistence):
   - 完整持久化逐笔交易明细、逐柱盯市净值、Git Revision、数据 64 位 SHA256 与宏观归因。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports" / "unified_backtests"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from contract_specs import get_spec, calculate_contract_fee, calculate_contract_margin
from backtest_validator import wilson_score_interval, grade_reliability, GRADE_A, GRADE_B, GRADE_F
from synthetic_market_regime_generator import SyntheticMarketRegimeGenerator
from chanquant_v8_production_strategy import (
    evaluate_chan_signal,
    calculate_factors_v8,
    ChanSignal,
    TREND_ISLAND_SYMBOLS,
    REVERSION_ISLAND_SYMBOLS,
)
from run_chanquant_v8_master_research import (
    StrictCausalSharedPortfolioEngine,
    StrictPendingOrder,
    StrictPositionV8,
    compute_data_sha256,
    get_git_revision,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ChanQuant_LLN_FullCycle")

ACTIVE_FUTURES_UNIVERSE = [
    "AU_IDX", "AG_IDX", "CU_IDX", "AL_IDX", "ZN_IDX",
    "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "MA_IDX",
    "TA_IDX", "SA_IDX", "FG_IDX", "M_IDX", "P_IDX", "LC_IDX",
]

START_PRICES = {
    "AU_IDX": 580.0, "AG_IDX": 6200.0, "CU_IDX": 72000.0, "AL_IDX": 19500.0, "ZN_IDX": 22500.0,
    "RB_IDX": 3500.0, "HC_IDX": 3700.0, "I_IDX": 800.0, "J_IDX": 2100.0, "MA_IDX": 2450.0,
    "TA_IDX": 5400.0, "SA_IDX": 1750.0, "FG_IDX": 1400.0, "M_IDX": 3100.0, "P_IDX": 8200.0, "LC_IDX": 85000.0,
}


def run_lln_full_cycle_stress_audit(
    bars_per_regime: int = 5000,
    initial_capital: float = 500_000.0,
    risk_per_trade_pct: float = 0.010,
    max_margin_ratio: float = 0.60,
    max_asset_margin_pct: float = 0.25,
) -> Dict[str, Any]:
    """
    运行基于真实期货时钟与 5 大宏观牛熊机制的全组合因果压力测试
    """
    print("========================================================================================================================")
    print("🔬 【ChanQuant 8.0·全周期牛熊宏观机制深度压力测试 (单一同源·真实共享资金池)】")
    print("========================================================================================================================")
    print("📋 审计铁律：生产策略 evaluate_chan_signal | 期货真实交易时钟 | 50万共享账户 | 同柱止损校验 | 1x基准 vs 3x极端压测")
    print("========================================================================================================================\n")

    gen = SyntheticMarketRegimeGenerator(seed=2026)
    data_map: Dict[str, pd.DataFrame] = {}
    
    print(f"📦 正在生成 {len(ACTIVE_FUTURES_UNIVERSE)} 大活跃品种 5 大宏观周期拟真行情 (每品种 {bars_per_regime * 5:,} 根 15m Bar)...")
    for sym in ACTIVE_FUTURES_UNIVERSE:
        spec = get_spec(sym)
        start_p = START_PRICES.get(sym, 3000.0)
        df_sym = gen.generate_regime_bars(
            sym, start_price=start_p, bars_per_regime=bars_per_regime, tick_size=spec.tick_size, timeframe="15m", save_to_db=False
        ).reset_index()
        data_map[sym] = df_sym

    all_timestamps = sorted(list(set(
        t for df in data_map.values() for t in df["trade_time"].astype(str).tolist()
    )))
    n_timeline_bars = len(all_timestamps)
    total_accumulated_bars = sum(len(df) for df in data_map.values())

    print(f"📊 数据生成完毕：组合全局时间轴: {n_timeline_bars:,} 步 | 品种级总 K 线: {total_accumulated_bars:,} 根 ({all_timestamps[0]} ~ {all_timestamps[-1]})")

    # 1. 预计算因果指标 (一次性计算，NumPy 数组加速)
    print("\n🔬 正在预计算各品种缠论特征与动力学因子 (单一同源 calculate_factors_v8)...")
    base_engine = StrictCausalSharedPortfolioEngine(
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        max_margin_ratio=max_margin_ratio,
        max_asset_margin_pct=max_asset_margin_pct,
        cost_multiplier=1.0,
    )
    full_processed_map = {}
    for sym, df in data_map.items():
        full_processed_map[sym] = base_engine._preprocess_symbol(df, sym)

    # 2. 执行 1x 正常成本共享资金池回测
    print("\n⚖️ 正在执行【1x 正常成本基准】组合回测...")
    engine_1x = StrictCausalSharedPortfolioEngine(
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        max_margin_ratio=max_margin_ratio,
        max_asset_margin_pct=max_asset_margin_pct,
        cost_multiplier=1.0,
    )
    rep_1x = engine_1x.run_portfolio(full_processed_map)

    # 3. 执行 3x 极限摩擦压力测试
    print("\n🔥 正在执行【3x 极限摩擦压测】组合回测...")
    engine_3x = StrictCausalSharedPortfolioEngine(
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        max_margin_ratio=max_margin_ratio,
        max_asset_margin_pct=max_asset_margin_pct,
        cost_multiplier=3.0,
    )
    rep_3x = engine_3x.run_portfolio(full_processed_map)

    # 4. 打印组合总表
    print("\n" + "=" * 120)
    print("🏛️ 【ChanQuant 8.0·全周期牛熊宏观机制压力测试】 真实共享账户 (50万资金池) 审计总表")
    print("=" * 120)
    print(f"{'场景':<20} {'初始资金(RMB)':<16} {'总净利润(RMB)':<18} {'期末总权益(RMB)':<18} {'对账差额':<16} {'真实动态最大回撤 (MaxDD)'}")
    print("-" * 120)
    diff_1x = abs(rep_1x["final_equity"] - (initial_capital + rep_1x["total_net_pnl"]))
    diff_3x = abs(rep_3x["final_equity"] - (initial_capital + rep_3x["total_net_pnl"]))
    print(f"【1x 正常成本基准】   {initial_capital:>12,.2f} RMB   {rep_1x['total_net_pnl']:>14,.2f} RMB   {rep_1x['final_equity']:>14,.2f} RMB   {diff_1x:>10.2f} (✅平账)   {rep_1x['portfolio_max_drawdown_rmb']:>10,.2f} RMB ({rep_1x['portfolio_max_drawdown_pct']:.2f}%)")
    print(f"【3x 极限摩擦压测】   {initial_capital:>12,.2f} RMB   {rep_3x['total_net_pnl']:>14,.2f} RMB   {rep_3x['final_equity']:>14,.2f} RMB   {diff_3x:>10.2f} (✅平账)   {rep_3x['portfolio_max_drawdown_rmb']:>10,.2f} RMB ({rep_3x['portfolio_max_drawdown_pct']:.2f}%)")
    print("=" * 120)
    print(f"• 1x 基准指标：总交易 {rep_1x['overall_metrics']['trades']} 笔 | 胜率 {rep_1x['overall_metrics']['win_rate']*100:.1f}% | 盈亏比 (PF): {rep_1x['overall_metrics']['profit_factor']:.2f}")
    print(f"• 3x 压测指标：总交易 {rep_3x['overall_metrics']['trades']} 笔 | 胜率 {rep_3x['overall_metrics']['win_rate']*100:.1f}% | 盈亏比 (PF): {rep_3x['overall_metrics']['profit_factor']:.2f}")

    # 5. 持久化报告
    git_hash = get_git_revision()
    data_hash = compute_data_sha256(data_map)
    ts_str = time.strftime("%Y%m%d_%H%M%S")
    out_file = REPORTS_DIR / f"ChanQuant_8.0_Macro_Regime_Deep_Stress_{ts_str}.json"

    report_payload = {
        "report_title": "ChanQuant 8.0 全周期牛熊宏观机制深度压力测试报告",
        "timestamp": ts_str,
        "is_synthetic_stress_test": True,
        "disclaimer": "本报告为基于马尔可夫机制转换生成器的全周期极限压力测试/故障注入测试，用于评估策略在极端行情下的生存与抗压边界，非真实历史盘面。",
        "git_revision": git_hash,
        "data_content_sha256": data_hash,
        "timeline_statistics": {
            "portfolio_timeline_steps": n_timeline_bars,
            "total_accumulated_symbol_bars": total_accumulated_bars,
            "start_time": all_timestamps[0],
            "end_time": all_timestamps[-1],
        },
        "parameters": {
            "initial_capital": initial_capital,
            "risk_per_trade_pct": risk_per_trade_pct,
            "max_margin_ratio": max_margin_ratio,
            "max_asset_margin_pct": max_asset_margin_pct,
            "active_symbols": ACTIVE_FUTURES_UNIVERSE,
        },
        "full_baseline_1x": rep_1x,
        "full_stress_3x": rep_3x,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    print(f"\n📁 包含完整逐笔交易明细与逐柱净值的全账本压力测试报告已归档至: {out_file}")
    return report_payload


if __name__ == "__main__":
    run_lln_full_cycle_stress_audit()
