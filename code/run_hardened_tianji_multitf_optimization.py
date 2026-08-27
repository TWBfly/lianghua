"""
code/run_hardened_tianji_multitf_optimization.py — 「破阵·天玑」大周期 (1h / 4h / 日线) 深度优化与多周期严格因果对比审计
Multi-Timeframe Causal Backtest & Hardened 5-Gate Validation for Tianji Strategy
"""

from __future__ import annotations

import os
import sys
import sqlite3
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
STRAT_DIR = os.path.join(PROJECT_ROOT, "strategies")
for p in [PROJECT_ROOT, CODE_DIR, STRAT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies.tianji_orderflow_breakout import calculate_signal

DB_PATH = os.path.join(PROJECT_ROOT, "data", "ashare_quant.db")

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


def run_tianji_simulation_core(
    df: pd.DataFrame,
    symbol: str,
    spec: dict,
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 1.5,
    breakeven_atr_mult: float = 1.2,
    trail_atr_mult: float = 3.0,
    take_profit_atr_mult: float = 4.0,  # 大周期采用大盈亏比阶梯止盈
    cost_multiplier: float = 1.0,
) -> Dict[str, Any]:
    c = df["close"].to_numpy(dtype=float)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    v = df["volume"].to_numpy(dtype=float)
    times = df.index.to_numpy()
    n = len(df)

    if n < 40:
        return {}

    sig_series = calculate_signal(df)
    sig = sig_series.reindex(df.index).fillna(0).to_numpy(dtype=int)

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
    total_gross = 0.0
    total_fees_and_slip = 0.0

    for i in range(1, n):
        bar_date = str(times[i])[:10]
        if current_date is None:
            current_date = bar_date
            daily_start_equity = cash

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

        unrealized = (pos * mult * (c[i] - entry_price) if pos > 0 else abs(pos) * mult * (entry_price - c[i])) if pos != 0 else 0.0
        equity_curve.append(cash + unrealized)

        # 1. 持仓出场 (下一柱开盘 Open 成交)
        if pos > 0:
            highest_price = max(highest_price, h[i])
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            if take_profit_atr_mult > 0 and h[i] >= entry_price + take_profit_atr_mult * entry_atr:
                exit_triggered = True
                exit_price = min(h[i], entry_price + take_profit_atr_mult * entry_atr) - slippage_cost
                exit_reason = "大波段 ATR 目标达成"
            else:
                if (highest_price - entry_price) >= breakeven_atr_mult * entry_atr:
                    stop_price = max(stop_price, entry_price + 0.2 * entry_atr)
                dyn_trail = highest_price - trail_atr_mult * atr[i]
                stop_price = max(stop_price, dyn_trail)

                if l[i] <= stop_price:
                    exit_triggered = True
                    exit_price = min(o[i], stop_price) - slippage_cost
                    exit_reason = "大周期跟踪止损"
                elif sig[i-1] == -1:
                    exit_triggered = True
                    exit_price = o[i] - slippage_cost
                    exit_reason = "反向信号翻转"

            if exit_triggered:
                exit_fee = exit_price * (pos * mult) * fee_rate
                gross_pnl = (exit_price - entry_price) * (pos * mult)
                net_pnl = gross_pnl - exit_fee
                cash += (pos * mult * exit_price - exit_fee)
                total_gross += gross_pnl
                total_fees_and_slip += (exit_fee + slippage_cost * pos * mult)
                trades.append({
                    "entry_time": str(times[entry_idx]),
                    "exit_time": str(times[i]),
                    "side": "BUY",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "lots": pos,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "is_win": net_pnl > 0,
                    "reason": exit_reason,
                })
                pos = 0.0

        elif pos < 0:
            lowest_price = min(lowest_price, l[i])
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            if take_profit_atr_mult > 0 and l[i] <= entry_price - take_profit_atr_mult * entry_atr:
                exit_triggered = True
                exit_price = max(l[i], entry_price - take_profit_atr_mult * entry_atr) + slippage_cost
                exit_reason = "大波段 ATR 目标达成"
            else:
                if (entry_price - lowest_price) >= breakeven_atr_mult * entry_atr:
                    stop_price = min(stop_price, entry_price - 0.2 * entry_atr)
                dyn_trail = lowest_price + trail_atr_mult * atr[i]
                stop_price = min(stop_price, dyn_trail)

                if h[i] >= stop_price:
                    exit_triggered = True
                    exit_price = max(o[i], stop_price) + slippage_cost
                    exit_reason = "大周期跟踪止损"
                elif sig[i-1] == 1:
                    exit_triggered = True
                    exit_price = o[i] + slippage_cost
                    exit_reason = "反向信号翻转"

            if exit_triggered:
                exit_fee = exit_price * (abs(pos) * mult) * fee_rate
                gross_pnl = (entry_price - exit_price) * (abs(pos) * mult)
                net_pnl = gross_pnl - exit_fee
                cash -= (abs(pos) * mult * exit_price + exit_fee)
                total_gross += gross_pnl
                total_fees_and_slip += (exit_fee + slippage_cost * abs(pos) * mult)
                trades.append({
                    "entry_time": str(times[entry_idx]),
                    "exit_time": str(times[i]),
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "lots": abs(pos),
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "is_win": net_pnl > 0,
                    "reason": exit_reason,
                })
                pos = 0.0

        # 2. 开仓撮合 (大周期下一柱开盘)
        if pos == 0 and v[i-1] >= 10:
            entry_atr = max(atr[i], tick * 2.0)
            risk_budget = initial_capital * 0.01  # 大周期波段赋予 1.0% 单笔风险预算
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
                total_fees_and_slip += (fee + slippage_cost * pos * mult)

            elif sig[i-1] == -1:
                pos = -float(lot_size)
                entry_price = o[i] - slippage_cost
                entry_idx = i
                stop_price = entry_price + stop_atr_mult * entry_atr
                lowest_price = l[i]
                fee = entry_price * (abs(pos) * mult) * fee_rate
                cash += (abs(pos) * mult * entry_price - fee)
                total_fees_and_slip += (fee + slippage_cost * abs(pos) * mult)

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
                "is_win": pnl > 0,
                "reason": "期末平仓",
            })
            pos = 0.0
        else:
            unclosed = True

    net_profit = cash - initial_capital
    df_trades = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["net_pnl", "is_win"])
    total_trades = len(df_trades)
    win_rate = (len(df_trades[df_trades["is_win"]]) / total_trades * 100.0) if total_trades > 0 else 0.0

    wins = df_trades[df_trades["net_pnl"] > 0]["net_pnl"]
    losses = df_trades[df_trades["net_pnl"] < 0]["net_pnl"].abs()
    plr = (wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() > 0 else (99.0 if len(wins) > 0 else 0.0)

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = (peak - eq_arr) / np.maximum(peak, 1.0)
    max_dd = float(np.max(dd_arr) * 100.0)

    ledger_reconciled = (not unclosed) and abs(sum(df_trades["net_pnl"]) - net_profit) < 1.0
    friction_ratio = (total_fees_and_slip / (abs(total_gross) + 1e-6) * 100.0) if total_gross != 0 else 0.0

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
        "friction_ratio": friction_ratio,
    }


def validate_symbol_tf(df: pd.DataFrame, symbol: str, spec: dict) -> Dict[str, Any]:
    base_res = run_tianji_simulation_core(df, symbol, spec, cost_multiplier=1.0)
    if not base_res or base_res["total_trades"] == 0:
        return {
            "symbol": symbol, "name": spec["name"], "status": "INSUFFICIENT_EVIDENCE",
            "trades": 0, "win_rate": 0.0, "plr": 0.0, "max_dd": 0.0, "net_profit": 0.0,
            "holdout_trades": 0, "holdout_net_profit": 0.0, "param_pass_count": 0, "stress_3x_profit": 0.0,
            "friction_ratio": 0.0
        }

    n = len(df)
    split_idx = int(n * 0.70)
    df_holdout = df.iloc[split_idx:].copy()
    holdout_res = run_tianji_simulation_core(df_holdout, symbol, spec, cost_multiplier=1.0)
    h_trades = holdout_res.get("total_trades", 0)
    h_profit = holdout_res.get("net_profit", 0.0)

    param_pass_count = 0
    for s_mult in [1.0, 1.4, 1.8, 2.2]:
        for t_mult in [2.2, 2.8, 3.4, 4.0]:
            p_res = run_tianji_simulation_core(
                df_holdout, symbol, spec,
                stop_atr_mult=s_mult, trail_atr_mult=t_mult,
                cost_multiplier=1.0
            )
            if p_res.get("net_profit", 0.0) > 0:
                param_pass_count += 1

    stress_res = run_tianji_simulation_core(df, symbol, spec, cost_multiplier=3.0)
    stress_profit = stress_res.get("net_profit", 0.0)

    ledger_ok = base_res["ledger_reconciled"]
    unclosed = base_res["unclosed"]

    if not ledger_ok or unclosed or h_profit <= 0 or stress_profit <= 0:
        status = "REJECTED"
    elif h_trades < 10 or param_pass_count < 8:
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
        "friction_ratio": base_res["friction_ratio"],
        "status": status,
    }


def run_comparative_multitf_research():
    print("=" * 135)
    print("🚀 【破阵·天玑】多周期严格因果回测对比与大周期 (15m vs 30m vs 1h vs 1d) 深度优化")
    print("📌 核心命题验证: 检验大周期 (1h / 1d) 是否实现 盈亏比 >= 3:1、信噪比提升、摩擦占比骤降与五重门禁突破")
    print("=" * 135)

    conn = sqlite3.connect(DB_PATH)
    timeframes = ["15m", "30m", "1h", "1d"]
    summary_cards = []

    for tf in timeframes:
        tf_results = []
        tot_trades = 0
        tot_pnl = 0.0
        start_t = []
        end_t = []

        for sym, spec in CONTRACT_SPECS.items():
            df = pd.read_sql_query(
                "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
                conn, params=[sym, tf]
            )
            if df.empty or len(df) < 50:
                continue

            df["trade_time"] = pd.to_datetime(df["trade_time"])
            df = df.set_index("trade_time").sort_index()

            start_t.append(df.index[0])
            end_t.append(df.index[-1])

            eval_res = validate_symbol_tf(df, sym, spec)
            tf_results.append(eval_res)
            tot_trades += eval_res["trades"]
            tot_pnl += eval_res["net_profit"]

        df_tf = pd.DataFrame(tf_results)
        if df_tf.empty:
            continue

        pass_cnt = len(df_tf[df_tf["status"] == "BACKTEST_VALIDATED"])
        profit_cnt = len(df_tf[df_tf["net_profit"] > 0])
        avg_win_rate = df_tf[df_tf["trades"] > 0]["win_rate"].mean()
        avg_plr = df_tf[df_tf["trades"] > 0]["plr"].mean()
        avg_fric = df_tf[df_tf["trades"] > 0]["friction_ratio"].mean()

        summary_cards.append({
            "timeframe": tf,
            "symbols_count": len(df_tf),
            "date_range": f"{min(start_t).strftime('%Y-%m-%d')} ~ {max(end_t).strftime('%Y-%m-%d')}",
            "total_trades": tot_trades,
            "profit_symbols": f"{profit_cnt}/{len(df_tf)}",
            "avg_win_rate": avg_win_rate,
            "avg_plr": avg_plr,
            "friction_ratio": avg_fric,
            "total_net_profit": tot_pnl,
            "validated_count": pass_cnt,
            "df_details": df_tf
        })

    conn.close()

    # 1. 打印多周期横向对比大盘卡
    print("\n" + "=" * 135)
    print("📊 【多周期严格因果大盘横向对比表】")
    print("=" * 135)
    print(f"{'周期':<8} {'时间跨度':<25} {'覆盖品种':<8} {'总交易笔数':<12} {'盈利品种比':<12} {'平均净胜率':<12} {'平均盈亏比':<12} {'摩擦损耗占比':<14} {'组合总净利润':<18} {'门禁通过数':<10}")
    print("-" * 135)
    for s in summary_cards:
        print(
            f"{s['timeframe']:<8} {s['date_range']:<25} {s['symbols_count']:<8} "
            f"{s['total_trades']:<12} {s['profit_symbols']:<12} {s['avg_win_rate']:<10.1f}%   "
            f"{s['avg_plr']:<10.2f} {s['friction_ratio']:<12.1f}%  "
            f"¥{s['total_net_profit']:<16,.2f} {s['validated_count']} 个品种"
        )
    print("-" * 135)

    # 2. 打印 1h / 1d 最优周期的品种明细
    for s in summary_cards:
        if s["timeframe"] in ["1h", "1d"]:
            print(f"\n💎 【{s['timeframe']} 周期 25 大品种详细因果审计报告】 (时间跨度: {s['date_range']})")
            print("-" * 135)
            print(f"{'代码':<8} {'品种':<8} {'板块':<8} {'交易':<6} {'净胜率':<8} {'盈亏比':<8} {'M2M回撤':<10} {'扣费净利润(元)':<16} {'尾部交易':<8} {'尾部净利(元)':<14} {'参数平原':<8} {'3倍压测(元)':<14} {'准入状态':<18}")
            print("-" * 135)
            for _, r in s["df_details"].iterrows():
                print(
                    f"{r['symbol']:<8} {r['name']:<8} {r['sector']:<8} "
                    f"{r['trades']:<6} {r['win_rate']:<6.1f}% {r['plr']:<8.2f} {r['max_dd']:<6.2f}%   "
                    f"¥{r['net_profit']:<14,.2f} {r['holdout_trades']:<8} ¥{r['holdout_net_profit']:<12,.2f} "
                    f"{r['param_pass_count']}/16    ¥{r['stress_3x_profit']:<12,.2f} {r['status']:<18}"
                )
            print("-" * 135)


if __name__ == "__main__":
    run_comparative_multitf_research()
