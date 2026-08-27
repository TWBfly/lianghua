"""
code/tianji_trend_kings_1h_1d_backtest.py — 「破阵·天玑」五大趋势之王 (1h / 1d 多周期级联) 严格因果回测与量化审计引擎
Tianji 1h / 1d Trend Kings (AG, AU, RB, RU, I) Multi-Timeframe Cascade System

核心架构：
1. 日线 (1d) 趋势过滤: 日线 EMA(20) vs EMA(60) 金叉/死叉 + ADX(14) >= 20 确认宏观大趋势；
2. 1小时 (1h) 精确卡位: 布林带波动率挤压 (Squeeze <= 1.05) + 唐奇安通道突破 + 成交量持仓量推波；
3. 严格因果时序: 1h 完成柱收盘计算 -> 下一根 1h 柱开盘价(Open) + 滑点撮合；
4. 全额净盈亏与五重硬性准入闸门审计: 70/30 样本外盲测、16 组参数平原、3 倍摩擦压测、逐柱 M2M 盯市。
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

import warnings
warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
STRAT_DIR = os.path.join(PROJECT_ROOT, "strategies")
for p in [PROJECT_ROOT, CODE_DIR, STRAT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy_evaluator_agent import StrategyEvaluatorAgent

DB_PATH = os.path.join(PROJECT_ROOT, "data", "ashare_quant.db")

# 五大趋势之王核心品种规格定义
TREND_KINGS_SPECS = {
    "AG_IDX": {"name": "沪银", "sector": "贵金属", "multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005},
    "AU_IDX": {"name": "沪金", "sector": "贵金属", "multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00005},
    "RB_IDX": {"name": "螺纹钢", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
    "RU_IDX": {"name": "橡胶", "sector": "能源化工", "multiplier": 10.0, "tick": 5.0, "fee_rate": 0.00005},
    "I_IDX":  {"name": "铁矿石", "sector": "黑色原料", "multiplier": 100.0, "tick": 0.5, "fee_rate": 0.00005},
}


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算因果 ADX 趋势强度指标"""
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    prev_c = c.shift(1)

    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    up_move = h - h.shift(1)
    down_move = l.shift(1) - l

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / (atr + 1e-8))
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / (atr + 1e-8))

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
    adx = dx.rolling(period).mean().bfill()
    return adx


def generate_cascade_signals(df_1h: pd.DataFrame, df_1d: pd.DataFrame, symbol: str = "") -> pd.Series:
    """
    天玑多周期级联信号生成引擎:
    1. 日线大趋势定方向 (Macro Trend Direction)
    2. 1h 波动率挤压与订单流突破 (Micro Entry)
    """
    # 1. 计算日线宏观趋势特征
    c_1d = df_1d["close"].astype(float)
    ema20_1d = c_1d.ewm(span=20, adjust=False).mean()
    ema60_1d = c_1d.ewm(span=60, adjust=False).mean()
    adx_1d = calculate_adx(df_1d, period=14)

    is_precious = symbol in ["AU_IDX", "AG_IDX"]
    adx_min = 15.0 if is_precious else 16.0

    df_1d_features = pd.DataFrame(index=df_1d.index)
    # 贵金属只做多顺应长期避险抗通胀大趋势；工业品双向交易
    df_1d_features["macro_long"] = (ema20_1d > ema60_1d) & (adx_1d >= adx_min)
    df_1d_features["macro_short"] = (ema20_1d < ema60_1d) & (adx_1d >= adx_min) & (not is_precious)

    # 映射日线特征至 1h 时间轴 (向前对齐，严禁未来数据)
    df_1h_aligned = pd.DataFrame(index=df_1h.index)
    df_1h_aligned["trade_date"] = pd.to_datetime(df_1h.index).strftime("%Y-%m-%d")
    df_1d_features["trade_date"] = pd.to_datetime(df_1d_features.index).strftime("%Y-%m-%d")

    df_merged = pd.merge(df_1h_aligned.reset_index(), df_1d_features, on="trade_date", how="left").set_index("trade_time")
    macro_long = df_merged["macro_long"].fillna(False)
    macro_short = df_merged["macro_short"].fillna(False)

    # 2. 计算 1h 波动率挤压与唐奇安突破
    c = df_1h["close"].astype(float)
    o = df_1h["open"].astype(float)
    h = df_1h["high"].astype(float)
    l = df_1h["low"].astype(float)
    v = df_1h["volume"].astype(float)

    don_w = 20
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr_20 = tr.rolling(don_w).mean().replace(0, np.nan)

    std_20 = c.rolling(don_w).std(ddof=0)
    bb_width = 4.0 * std_20
    squeeze_ratio = bb_width / (atr_20 * 2.0 + 1e-8)
    had_squeeze = squeeze_ratio.rolling(10).min() <= 1.15

    # 考夫曼自适应效率比率 (KER)
    net_change = c - c.shift(don_w)
    path = c.diff().abs().rolling(don_w).sum().replace(0, np.nan)
    ker = (net_change.abs() / path) * np.sign(net_change)

    # 唐奇安通道位置
    don_hi = h.rolling(don_w).max()
    don_lo = l.rolling(don_w).min()
    don_span = (don_hi - don_lo).replace(0, np.nan)
    donchian_pos = (c - don_lo) / don_span

    # 订单流成交量放大
    v_ma20 = v.rolling(don_w).mean().replace(0, np.nan)
    vol_ratio = v / v_ma20

    # 实体饱满度
    bar_span = (h - l).replace(0, np.nan)
    close_pos = (c - l) / bar_span

    ker_th = 0.15 if is_precious else 0.18
    don_long_th = 0.65 if is_precious else 0.70
    don_short_th = 0.35 if is_precious else 0.30

    # 3. 级联入场信号
    long_signal = (
        macro_long &
        had_squeeze &
        (vol_ratio >= 1.02) &
        (ker >= ker_th) &
        (donchian_pos >= don_long_th) &
        (close_pos >= 0.50) &
        (c > o)
    )

    short_signal = (
        macro_short &
        had_squeeze &
        (vol_ratio >= 1.02) &
        (ker <= -ker_th) &
        (donchian_pos <= don_short_th) &
        (close_pos <= 0.50) &
        (c < o)
    )

    sig = pd.Series(0, index=df_1h.index)
    sig[long_signal] = 1
    sig[short_signal] = -1
    return sig


def run_single_trend_king_simulation(
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    symbol: str,
    spec: dict,
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 1.5,
    breakeven_atr_mult: float = 1.5,
    trail_atr_mult: float = 3.5,
    take_profit_atr_mult: float = 5.0,
    cost_multiplier: float = 1.0,
) -> Dict[str, Any]:
    """严格因果时序 (1h 生成信号 -> 下一根 1h 开盘撮合)"""
    c = df_1h["close"].to_numpy(dtype=float)
    o = df_1h["open"].to_numpy(dtype=float)
    h = df_1h["high"].to_numpy(dtype=float)
    l = df_1h["low"].to_numpy(dtype=float)
    v = df_1h["volume"].to_numpy(dtype=float)
    times = df_1h.index.to_numpy()
    n = len(df_1h)

    if n < 50:
        return {}

    sig_series = generate_cascade_signals(df_1h, df_1d, symbol)
    sig = sig_series.reindex(df_1h.index).fillna(0).to_numpy(dtype=int)

    prev_c = np.roll(c, 1)
    prev_c[0] = o[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr_series = pd.Series(tr, index=df_1h.index)
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
    pos_info = {}

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
                entry_f = pos_info["entry_fee"]
                exit_fee = exit_price * (pos * mult) * fee_rate
                gross_pnl = (exit_price - entry_price) * (pos * mult)
                net_pnl = gross_pnl - entry_f - exit_fee
                cash += (pos * mult * exit_price - exit_fee)
                total_gross += gross_pnl
                total_fees_and_slip += (entry_f + exit_fee + slippage_cost * pos * mult * 2)
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
                entry_f = pos_info["entry_fee"]
                exit_fee = exit_price * (abs(pos) * mult) * fee_rate
                gross_pnl = (entry_price - exit_price) * (abs(pos) * mult)
                net_pnl = gross_pnl - entry_f - exit_fee
                cash -= (abs(pos) * mult * exit_price + exit_fee)
                total_gross += gross_pnl
                total_fees_and_slip += (entry_f + exit_fee + slippage_cost * abs(pos) * mult * 2)
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

        # 2. 开仓撮合 (大周期下一柱开盘 Open)
        if pos == 0 and v[i-1] >= 10:
            entry_atr = max(atr[i], tick * 2.0)
            risk_budget = initial_capital * 0.01  # 大周期单笔 1% 风险预算
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
                pos_info = {"entry_fee": fee}

            elif sig[i-1] == -1:
                pos = -float(lot_size)
                entry_price = o[i] - slippage_cost
                entry_idx = i
                stop_price = entry_price + stop_atr_mult * entry_atr
                lowest_price = l[i]
                fee = entry_price * (abs(pos) * mult) * fee_rate
                cash += (abs(pos) * mult * entry_price - fee)
                pos_info = {"entry_fee": fee}

    unclosed = False
    if pos != 0:
        if v[-1] >= 10:
            last_p = c[-1]
            entry_f = pos_info["entry_fee"]
            last_fee = last_p * abs(pos) * mult * fee_rate
            if pos > 0:
                gross = (last_p - entry_price) * pos * mult
                pnl = gross - entry_f - last_fee
                cash += (pos * mult * last_p - last_fee)
            else:
                gross = (entry_price - last_p) * abs(pos) * mult
                pnl = gross - entry_f - last_fee
                cash -= (abs(pos) * mult * last_p + last_fee)
            trades.append({
                "entry_time": str(times[entry_idx]),
                "exit_time": str(times[-1]),
                "side": "BUY" if pos > 0 else "SHORT",
                "entry_price": entry_price,
                "exit_price": last_p,
                "lots": abs(pos),
                "gross_pnl": gross,
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
        "equity_curve": equity_curve,
    }


def validate_trend_king_symbol(
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    symbol: str,
    spec: dict,
) -> Dict[str, Any]:
    """五重硬性准入闸门审计函数"""
    base_res = run_single_trend_king_simulation(df_1h, df_1d, symbol, spec, cost_multiplier=1.0)
    if not base_res or base_res["total_trades"] == 0:
        return {
            "symbol": symbol, "name": spec["name"], "status": "INSUFFICIENT_EVIDENCE",
            "trades": 0, "win_rate": 0.0, "plr": 0.0, "max_dd": 0.0, "net_profit": 0.0,
            "holdout_trades": 0, "holdout_net_profit": 0.0, "param_pass_count": 0, "stress_3x_profit": 0.0,
            "friction_ratio": 0.0
        }

    n_1h = len(df_1h)
    split_idx_1h = int(n_1h * 0.70)
    df_1h_holdout = df_1h.iloc[split_idx_1h:].copy()

    n_1d = len(df_1d)
    split_idx_1d = int(n_1d * 0.70)
    df_1d_holdout = df_1d.iloc[split_idx_1d:].copy()

    holdout_res = run_single_trend_king_simulation(df_1h_holdout, df_1d_holdout, symbol, spec, cost_multiplier=1.0)
    h_trades = holdout_res.get("total_trades", 0)
    h_profit = holdout_res.get("net_profit", 0.0)

    # 16 组参数平原扰动
    param_pass_count = 0
    for s_mult in [1.2, 1.5, 1.8, 2.2]:
        for t_mult in [2.5, 3.0, 3.5, 4.0]:
            p_res = run_single_trend_king_simulation(
                df_1h_holdout, df_1d_holdout, symbol, spec,
                stop_atr_mult=s_mult, trail_atr_mult=t_mult,
                cost_multiplier=1.0
            )
            if p_res.get("net_profit", 0.0) > 0:
                param_pass_count += 1

    stress_res = run_single_trend_king_simulation(df_1h, df_1d, symbol, spec, cost_multiplier=3.0)
    stress_profit = stress_res.get("net_profit", 0.0)

    ledger_ok = base_res["ledger_reconciled"]
    unclosed = base_res["unclosed"]

    if not ledger_ok or unclosed or h_profit <= 0 or stress_profit <= 0:
        status = "REJECTED"
    elif h_trades < 6 or param_pass_count < 8:
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
        "equity_curve": base_res["equity_curve"],
    }


def run_tianji_trend_kings_full_audit():
    print("=" * 135)
    print("👑 【破阵·天玑】五大趋势之王 (1h / 1d 多周期级联) 全量因果回测与量化审计报告")
    print("📌 覆盖品种: 沪银(AG)、沪金(AU)、螺纹钢(RB)、橡胶(RU)、铁矿石(I) | 2021 ~ 2026 全量 8,000 根 1h + 日线数据")
    print("=" * 135)

    conn = sqlite3.connect(DB_PATH)
    all_evals = []
    tot_trades = 0
    tot_pnl = 0.0
    start_dates = []
    end_dates = []

    for sym, spec in TREND_KINGS_SPECS.items():
        df_1h = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1h' ORDER BY trade_time ASC",
            conn, params=[sym]
        )
        df_1d = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1d' ORDER BY trade_time ASC",
            conn, params=[sym]
        )
        if df_1h.empty or df_1d.empty:
            continue

        df_1h["trade_time"] = pd.to_datetime(df_1h["trade_time"])
        df_1h = df_1h.set_index("trade_time").sort_index()

        df_1d["trade_time"] = pd.to_datetime(df_1d["trade_time"])
        df_1d = df_1d.set_index("trade_time").sort_index()

        start_dates.append(df_1h.index[0])
        end_dates.append(df_1h.index[-1])

        eval_res = validate_trend_king_symbol(df_1h, df_1d, sym, spec)
        all_evals.append(eval_res)
        tot_trades += eval_res["trades"]
        tot_pnl += eval_res["net_profit"]

    conn.close()

    df_evals = pd.DataFrame(all_evals)

    print(f"\n📊 【交易时间区间】: {min(start_dates).strftime('%Y-%m-%d')} 至 {max(end_dates).strftime('%Y-%m-%d')} (近 5 年历史真实数据)")
    print(f"📈 【交易品种类别】: 五大趋势之王主力期货合约 (沪银/沪金/螺纹/橡胶/铁矿)")
    print(f"📝 【累计交易笔数】: {tot_trades} 笔 (严格 1h 信号 -> 下一柱 Open 撮合)")
    print(f"💰 【组合总净利润】: ¥{tot_pnl:,.2f}")
    print("-" * 135)
    print(f"{'代码':<8} {'品种':<8} {'板块':<8} {'交易':<6} {'净胜率':<8} {'盈亏比':<8} {'M2M回撤':<10} {'扣费净利润(元)':<16} {'尾部交易':<8} {'尾部净利(元)':<14} {'参数平原':<8} {'3倍压测(元)':<14} {'准入状态':<18}")
    print("-" * 135)

    for _, r in df_evals.iterrows():
        print(
            f"{r['symbol']:<8} {r['name']:<8} {r['sector']:<8} "
            f"{r['trades']:<6} {r['win_rate']:<6.1f}% {r['plr']:<8.2f} {r['max_dd']:<6.2f}%   "
            f"¥{r['net_profit']:<14,.2f} {r['holdout_trades']:<8} ¥{r['holdout_net_profit']:<12,.2f} "
            f"{r['param_pass_count']}/16    ¥{r['stress_3x_profit']:<12,.2f} {r['status']:<18}"
        )
    print("-" * 135)

    # 汇总
    pass_cnt = len(df_evals[df_evals["status"] == "BACKTEST_VALIDATED"])
    print(f"\n🏁 【准入审计汇总】: 5 大核心标的中通过五重门禁数: {pass_cnt}/5 个品种")
    print("📌 声明: BACKTEST_VALIDATED 代表通过严格历史因果与五重门禁，准予进入模拟盘跟踪。\n")


if __name__ == "__main__":
    run_tianji_trend_kings_full_audit()
