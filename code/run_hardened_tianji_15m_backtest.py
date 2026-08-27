"""
code/run_hardened_tianji_15m_backtest.py — 「破阵·天玑」15m 全市场商品期货严格因果回测与五重硬性门禁审计引擎
Hardened Causal Next-Open Execution, Net-of-Friction Accounting, 70/30 Holdout Split & 5-Gate Validation
"""

from __future__ import annotations

import os
import sys
import math
import sqlite3
import datetime
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
STRAT_DIR = os.path.join(PROJECT_ROOT, "strategies")
for p in [PROJECT_ROOT, CODE_DIR, STRAT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy_evaluator_agent import StrategyEvaluatorAgent
from strategies.tianji_orderflow_breakout import calculate_signal
from backtest_metrics import calculate_performance

DB_PATH = os.path.join(PROJECT_ROOT, "data", "ashare_quant.db")

# 25 大主流活跃商品期货主力合约规格表 (交易所标准乘数与最小变动价位)
CONTRACT_SPECS = {
    "AU_IDX": {"name": "沪金", "sector": "贵金属", "multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00005},
    "AG_IDX": {"name": "沪银", "sector": "贵金属", "multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005},
    "SC_IDX": {"name": "原油", "sector": "能源化工", "multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005},
    "LC_IDX": {"name": "碳酸锂", "sector": "新能源", "multiplier": 1.0, "tick": 50.0, "fee_rate": 0.00005},
    "CU_IDX": {"name": "沪铜", "sector": "有色金属", "multiplier": 5.0, "tick": 10.0, "fee_rate": 0.00005},
    "SN_IDX": {"name": "沪锡", "sector": "有色金属", "multiplier": 1.0, "tick": 10.0, "fee_rate": 0.00005},
    "AL_IDX": {"name": "沪铝", "sector": "有色金属", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005},
    "ZN_IDX": {"name": "沪锌", "sector": "有色金属", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005},
    "SI_IDX": {"name": "工业硅", "sector": "新能源", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005},
    "RB_IDX": {"name": "螺纹钢", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "HC_IDX": {"name": "热卷", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "I_IDX":  {"name": "铁矿石", "sector": "黑色原料", "multiplier": 100.0, "tick": 0.5, "fee_rate": 0.00005},
    "J_IDX":  {"name": "焦炭", "sector": "黑色原料", "multiplier": 100.0, "tick": 0.5, "fee_rate": 0.00005},
    "JM_IDX": {"name": "焦煤", "sector": "黑色原料", "multiplier": 60.0, "tick": 0.5, "fee_rate": 0.00005},
    "RU_IDX": {"name": "橡胶", "sector": "能源化工", "multiplier": 10.0, "tick": 5.0, "fee_rate": 0.00005},
    "TA_IDX": {"name": "PTA", "sector": "纺织化工", "multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00005},
    "MA_IDX": {"name": "甲醇", "sector": "能源化工", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "SA_IDX": {"name": "纯碱", "sector": "能源化工", "multiplier": 20.0, "tick": 1.0, "fee_rate": 0.00005},
    "FG_IDX": {"name": "玻璃", "sector": "建材玻璃", "multiplier": 20.0, "tick": 1.0, "fee_rate": 0.00005},
    "CF_IDX": {"name": "棉花", "sector": "软商品", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005},
    "SR_IDX": {"name": "白糖", "sector": "软商品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "C_IDX":  {"name": "玉米", "sector": "农产品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "M_IDX":  {"name": "豆粕", "sector": "农产品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "Y_IDX":  {"name": "豆油", "sector": "油脂油料", "multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00005},
    "P_IDX":  {"name": "棕榈油", "sector": "油脂油料", "multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00005},
}


def run_tianji_symbol_simulation(
    df: pd.DataFrame,
    symbol: str,
    spec: dict,
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 1.2,
    breakeven_atr_mult: float = 1.0,
    trail_atr_mult: float = 2.5,
    take_profit_atr_mult: float = 2.0,
    cost_multiplier: float = 1.0,
) -> Dict[str, Any]:
    """严格因果时序与全额净盈亏撮合核心函数"""
    c = df["close"].to_numpy(dtype=float)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    v = df["volume"].to_numpy(dtype=float)
    times = df.index.to_numpy()
    n = len(df)

    if n < 40:
        return {}

    # 1. 严格因果信号生成
    sig_series = calculate_signal(df)
    sig = sig_series.reindex(df.index).fillna(0).to_numpy(dtype=int)

    # 2. 预计算 ATR(14)
    prev_c = np.roll(c, 1)
    prev_c[0] = o[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr_series = pd.Series(tr, index=df.index)
    atr = tr_series.rolling(14).mean().bfill().to_numpy(dtype=float)

    mult = spec["multiplier"]
    tick = spec["tick"]
    fee_rate = spec["fee_rate"] * cost_multiplier
    slippage_cost = 1.0 * tick * cost_multiplier

    cash = float(initial_capital)
    pos = 0.0
    entry_price = 0.0
    entry_idx = 0
    entry_atr = 0.0
    stop_price = 0.0
    highest_price = 0.0
    lowest_price = 1e9

    trades = []
    daily_equity_map = {}
    current_date = None
    daily_start_equity = cash
    equity_curve = [cash]

    for i in range(1, n):
        bar_date = str(times[i])[:10]
        if current_date is None:
            current_date = bar_date
            daily_start_equity = cash

        # 逐日结盯市 (Mark-to-Market)
        if bar_date != current_date:
            m2m_equity = cash + (pos * mult * (c[i-1] - entry_price) if pos > 0 else abs(pos) * mult * (entry_price - c[i-1])) if pos != 0 else cash
            daily_equity_map[current_date] = {
                "date": current_date,
                "start_equity": daily_start_equity,
                "end_equity": m2m_equity,
                "daily_return": (m2m_equity / daily_start_equity - 1.0) if daily_start_equity > 0 else 0.0,
            }
            current_date = bar_date
            daily_start_equity = m2m_equity

        # 逐柱盯市记录
        unrealized = (pos * mult * (c[i] - entry_price) if pos > 0 else abs(pos) * mult * (entry_price - c[i])) if pos != 0 else 0.0
        equity_curve.append(cash + unrealized)

        # ---------------- 1. 持仓出场与动态跟踪止损 (Causal Next-Open Exit) ----------------
        if pos > 0:
            highest_price = max(highest_price, h[i])
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            # 阶梯止盈
            if take_profit_atr_mult > 0 and h[i] >= entry_price + take_profit_atr_mult * entry_atr:
                exit_triggered = True
                exit_price = min(h[i], entry_price + take_profit_atr_mult * entry_atr) - slippage_cost
                exit_reason = "ATR 止盈达成"
            else:
                if (highest_price - entry_price) >= breakeven_atr_mult * entry_atr:
                    stop_price = max(stop_price, entry_price + 0.1 * entry_atr)
                dyn_trail = highest_price - trail_atr_mult * atr[i]
                stop_price = max(stop_price, dyn_trail)

                if l[i] <= stop_price:
                    exit_triggered = True
                    exit_price = min(o[i], stop_price) - slippage_cost
                    exit_reason = "跟踪吊灯止损"
                elif sig[i-1] == -1:
                    exit_triggered = True
                    exit_price = o[i] - slippage_cost
                    exit_reason = "反向信号平多"

            if exit_triggered:
                exit_fee = exit_price * (pos * mult) * fee_rate
                gross_pnl = (exit_price - entry_price) * (pos * mult)
                net_pnl = gross_pnl - exit_fee
                cash += (pos * mult * exit_price - exit_fee)
                trades.append({
                    "entry_time": str(times[entry_idx]),
                    "exit_time": str(times[i]),
                    "side": "BUY",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "lots": pos,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "return_pct": (exit_price / entry_price - 1.0) * 100.0,
                    "is_win": net_pnl > 0,
                    "reason": exit_reason,
                })
                pos = 0.0

        elif pos < 0:
            lowest_price = min(lowest_price, l[i])
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            # 阶梯止盈
            if take_profit_atr_mult > 0 and l[i] <= entry_price - take_profit_atr_mult * entry_atr:
                exit_triggered = True
                exit_price = max(l[i], entry_price - take_profit_atr_mult * entry_atr) + slippage_cost
                exit_reason = "ATR 止盈达成"
            else:
                if (entry_price - lowest_price) >= breakeven_atr_mult * entry_atr:
                    stop_price = min(stop_price, entry_price - 0.1 * entry_atr)
                dyn_trail = lowest_price + trail_atr_mult * atr[i]
                stop_price = min(stop_price, dyn_trail)

                if h[i] >= stop_price:
                    exit_triggered = True
                    exit_price = max(o[i], stop_price) + slippage_cost
                    exit_reason = "跟踪吊灯止损"
                elif sig[i-1] == 1:
                    exit_triggered = True
                    exit_price = o[i] + slippage_cost
                    exit_reason = "反向信号平空"

            if exit_triggered:
                exit_fee = exit_price * (abs(pos) * mult) * fee_rate
                gross_pnl = (entry_price - exit_price) * (abs(pos) * mult)
                net_pnl = gross_pnl - exit_fee
                cash -= (abs(pos) * mult * exit_price + exit_fee)
                trades.append({
                    "entry_time": str(times[entry_idx]),
                    "exit_time": str(times[i]),
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "lots": abs(pos),
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "return_pct": (entry_price / exit_price - 1.0) * 100.0,
                    "is_win": net_pnl > 0,
                    "reason": exit_reason,
                })
                pos = 0.0

        # ---------------- 2. 开仓判定与下一柱开盘成交 (Causal Next-Open Entry) ----------------
        if pos == 0 and v[i-1] >= 10:  # 流动性门禁
            entry_atr = max(atr[i], tick * 2.0)
            risk_budget = initial_capital * 0.005  # 5,000 元风险预算
            unit_risk = max(tick * mult, stop_atr_mult * entry_atr * mult)
            lot_size = max(1, min(50, int(risk_budget / unit_risk)))

            if sig[i-1] == 1:
                pos = float(lot_size)
                entry_price = o[i] + slippage_cost
                entry_idx = i
                stop_price = entry_price - stop_atr_mult * entry_atr
                highest_price = h[i]
                fee = entry_price * (pos * mult) * fee_rate
                cash -= (pos * mult * entry_price + fee)

            elif sig[i-1] == -1:
                pos = -float(lot_size)
                entry_price = o[i] - slippage_cost
                entry_idx = i
                stop_price = entry_price + stop_atr_mult * entry_atr
                lowest_price = l[i]
                fee = entry_price * (abs(pos) * mult) * fee_rate
                cash += (abs(pos) * mult * entry_price - fee)

    # 末柱可平仓清算
    unclosed = False
    if pos != 0:
        if v[-1] >= 10:
            last_p = c[-1]
            last_fee = last_p * abs(pos) * mult * fee_rate
            if pos > 0:
                pnl = (last_p - entry_price) * pos * mult - last_fee
                cash += (pos * mult * last_p - last_fee)
            else:
                pnl = (entry_price - last_p) * abs(pos) * mult - last_fee
                cash -= (abs(pos) * mult * last_p + last_fee)
            trades.append({
                "entry_time": str(times[entry_idx]),
                "exit_time": str(times[-1]),
                "side": "BUY" if pos > 0 else "SHORT",
                "entry_price": entry_price,
                "exit_price": last_p,
                "lots": abs(pos),
                "gross_pnl": pnl + last_fee,
                "net_pnl": pnl,
                "return_pct": (last_p / entry_price - 1.0) * 100.0 if pos > 0 else (entry_price / last_p - 1.0) * 100.0,
                "is_win": pnl > 0,
                "reason": "期末强平",
            })
            pos = 0.0
        else:
            unclosed = True

    # 账本核算
    net_profit = cash - initial_capital
    df_trades = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["net_pnl", "is_win"])
    total_trades = len(df_trades)
    win_rate = (len(df_trades[df_trades["is_win"]]) / total_trades * 100.0) if total_trades > 0 else 0.0

    wins = df_trades[df_trades["net_pnl"] > 0]["net_pnl"]
    losses = df_trades[df_trades["net_pnl"] < 0]["net_pnl"].abs()
    plr = (wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() > 0 else (99.0 if len(wins) > 0 else 0.0)

    # 动态 M2M 最大回撤
    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = (peak - eq_arr) / np.maximum(peak, 1.0)
    max_dd = float(np.max(dd_arr) * 100.0)

    ledger_reconciled = (not unclosed) and abs(sum(df_trades["net_pnl"]) - net_profit) < 1.0

    return {
        "symbol": symbol,
        "name": spec["name"],
        "sector": spec["sector"],
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_loss_ratio": plr,
        "max_drawdown_pct": max_dd,
        "net_profit": net_profit,
        "trades": df_trades,
        "unclosed": unclosed,
        "ledger_reconciled": ledger_reconciled,
        "equity_curve": equity_curve,
    }


def validate_tianji_symbol(
    df: pd.DataFrame,
    symbol: str,
    spec: dict,
) -> Dict[str, Any]:
    """五重硬性准入闸门审计函数"""
    # 1. 全样本基础回测
    base_res = run_tianji_symbol_simulation(df, symbol, spec, cost_multiplier=1.0)
    if not base_res or base_res["total_trades"] == 0:
        return {
            "symbol": symbol, "name": spec["name"], "status": "INSUFFICIENT_EVIDENCE",
            "trades": 0, "win_rate": 0.0, "max_dd": 0.0, "net_profit": 0.0,
            "holdout_trades": 0, "holdout_net_profit": 0.0, "param_pass_count": 0, "stress_3x_profit": 0.0
        }

    # 2. 70/30 时间序列尾部样本盲测
    n = len(df)
    split_idx = int(n * 0.70)
    df_holdout = df.iloc[split_idx:].copy()
    holdout_res = run_tianji_symbol_simulation(df_holdout, symbol, spec, cost_multiplier=1.0)
    h_trades = holdout_res.get("total_trades", 0)
    h_profit = holdout_res.get("net_profit", 0.0)

    # 3. 16 组参数平原扰动检验 (stop_atr ∈ [0.8, 1.2, 1.6, 2.0], trail_atr ∈ [1.8, 2.2, 2.6, 3.0])
    param_pass_count = 0
    for s_mult in [0.8, 1.2, 1.6, 2.0]:
        for t_mult in [1.8, 2.2, 2.6, 3.0]:
            p_res = run_tianji_symbol_simulation(
                df_holdout, symbol, spec,
                stop_atr_mult=s_mult, trail_atr_mult=t_mult,
                cost_multiplier=1.0
            )
            if p_res.get("net_profit", 0.0) > 0:
                param_pass_count += 1

    # 4. 3 倍极端成本压力测试
    stress_res = run_tianji_symbol_simulation(df, symbol, spec, cost_multiplier=3.0)
    stress_profit = stress_res.get("net_profit", 0.0)

    # 5. 准入判定 (Hard Gates)
    ledger_ok = base_res["ledger_reconciled"]
    unclosed = base_res["unclosed"]

    if not ledger_ok or unclosed or h_profit <= 0 or stress_profit <= 0:
        status = "REJECTED"
    elif h_trades < 15 or param_pass_count < 10:  # 15m 周期适度参数平原阈值
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "BACKTEST_VALIDATED"

    return {
        "symbol": symbol,
        "name": spec["name"],
        "sector": spec["sector"],
        "trades": base_res["total_trades"],
        "win_rate": base_res["win_rate"],
        "plr": base_res["profit_loss_ratio"],
        "max_dd": base_res["max_drawdown_pct"],
        "net_profit": base_res["net_profit"],
        "holdout_trades": h_trades,
        "holdout_net_profit": h_profit,
        "param_pass_count": param_pass_count,
        "stress_3x_profit": stress_profit,
        "status": status,
        "ledger_reconciled": ledger_ok,
    }


def run_full_tianji_15m_backtest():
    print("=" * 130)
    print("💎 【破阵·天玑】15m 全市场商品期货严格因果回测与五重硬性门禁审计系统")
    print("📌 核心原则: 完成柱收盘算信号 | 下一柱开盘(Open)+滑点撮合 | 全额净盈亏核算 | 70/30 样本外盲测 | 16组参数平原 | 3x 成本压测")
    print("=" * 130)

    conn = sqlite3.connect(DB_PATH)
    all_results = []
    total_trades_all = 0
    total_net_pnl = 0.0

    symbols_list = list(CONTRACT_SPECS.keys())
    start_times = []
    end_times = []

    for sym in symbols_list:
        spec = CONTRACT_SPECS[sym]
        df = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='15m' ORDER BY trade_time ASC",
            conn, params=[sym]
        )
        if df.empty or len(df) < 100:
            continue

        df["trade_time"] = pd.to_datetime(df["trade_time"])
        df = df.set_index("trade_time").sort_index()

        start_times.append(df.index[0])
        end_times.append(df.index[-1])

        eval_res = validate_tianji_symbol(df, sym, spec)
        all_results.append(eval_res)
        total_trades_all += eval_res["trades"]
        total_net_pnl += eval_res["net_profit"]

    conn.close()

    df_res = pd.DataFrame(all_results)
    if df_res.empty:
        print("⚠️ 未能在数据库中查询到 15m K线数据！")
        return

    # 打印全量明细表
    print(f"\n📊 【交易时间区间】: {min(start_times)} 至 {max(end_times)}")
    print(f"📈 【覆盖品种类别】: 商品期货 25 大主流活跃品种 (包含贵金属/有色/黑色/能化/农产品/新能源)")
    print(f"📝 【总成交交易笔数】: {total_trades_all} 笔")
    print(f"💰 【组合总净利润】: ¥{total_net_pnl:,.2f}")
    print("-" * 130)
    print(f"{'代码':<8} {'品种':<8} {'板块':<8} {'交易笔数':<8} {'真实净胜率':<10} {'盈亏比':<8} {'M2M回撤':<10} {'扣费净利润(元)':<16} {'尾部交易':<8} {'尾部净利(元)':<14} {'参数平原':<8} {'3倍压测(元)':<14} {'准入状态':<18}")
    print("-" * 130)

    for _, r in df_res.iterrows():
        print(
            f"{r['symbol']:<8} {r['name']:<8} {r['sector']:<8} "
            f"{r['trades']:<8} {r['win_rate']:<6.1f}%   {r['plr']:<8.2f} {r['max_dd']:<6.2f}%   "
            f"¥{r['net_profit']:<14,.2f} {r['holdout_trades']:<8} ¥{r['holdout_net_profit']:<12,.2f} "
            f"{r['param_pass_count']}/16    ¥{r['stress_3x_profit']:<12,.2f} {r['status']:<18}"
        )
    print("-" * 130)

    # 统计准入
    pass_cnt = len(df_res[df_res["status"] == "BACKTEST_VALIDATED"])
    rej_cnt = len(df_res[df_res["status"] == "REJECTED"])
    ins_cnt = len(df_res[df_res["status"] == "INSUFFICIENT_EVIDENCE"])
    profit_sym_cnt = len(df_res[df_res["net_profit"] > 0])

    print(f"\n🏁 【准入审计汇总】: 全部 {len(df_res)} 个品种 | 盈利品种: {profit_sym_cnt}/{len(df_res)} | 通过门禁: {pass_cnt} | 拒绝: {rej_cnt} | 证据不足: {ins_cnt}")
    print("📌 声明: BACKTEST_VALIDATED 仅代表通过严格历史因果与五重门禁，准予进入模拟盘跟踪，不代表实盘交易许可。\n")


if __name__ == "__main__":
    run_full_tianji_15m_backtest()
