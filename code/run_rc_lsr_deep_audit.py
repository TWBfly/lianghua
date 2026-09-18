"""
code/run_rc_lsr_deep_audit.py — 「RC-LSR·市场状态条件化流动性冲击反转策略」工业级多品种多周期因果回测与压力审计
RC-LSR Causal Audit Runner: Next-Open Fill, Chandelier Trailing, M2M Drawdown, 0 Leakage, Train vs OOS Split
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DATA_DIR = PROJECT_ROOT / "data"

for p in (PROJECT_ROOT, CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rc_lsr_strategy as rc_lsr_mod

DB_PATH = str(DATA_DIR / "ashare_quant.db")
REPORT_JSON = DATA_DIR / "rc_lsr_deep_audit_report.json"

# 覆盖全部 25 个商品期货主力连续合约规范
ACTIVE_CONTRACT_SPECS = {
    "AU_IDX": {"name": "沪金", "sector": "贵金属", "multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00005, "margin_rate": 0.10},
    "AG_IDX": {"name": "沪银", "sector": "贵金属", "multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "RB_IDX": {"name": "螺纹钢", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "HC_IDX": {"name": "热卷", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "I_IDX":  {"name": "铁矿石", "sector": "黑色原料", "multiplier": 100.0, "tick": 0.5, "fee_rate": 0.00005, "margin_rate": 0.13},
    "J_IDX":  {"name": "焦炭", "sector": "黑色原料", "multiplier": 100.0, "tick": 0.5, "fee_rate": 0.00005, "margin_rate": 0.12},
    "JM_IDX": {"name": "焦煤", "sector": "黑色原料", "multiplier": 60.0, "tick": 0.5, "fee_rate": 0.00005, "margin_rate": 0.12},
    "CU_IDX": {"name": "沪铜", "sector": "有色金属", "multiplier": 5.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "AL_IDX": {"name": "沪铝", "sector": "有色金属", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "ZN_IDX": {"name": "沪锌", "sector": "有色金属", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "SN_IDX": {"name": "沪锡", "sector": "有色金属", "multiplier": 1.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "SC_IDX": {"name": "原油", "sector": "能源化工", "multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005, "margin_rate": 0.12},
    "TA_IDX": {"name": "PTA", "sector": "纺织化工", "multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "MA_IDX": {"name": "甲醇", "sector": "能源化工", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "SA_IDX": {"name": "纯碱", "sector": "能源化工", "multiplier": 20.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "FG_IDX": {"name": "玻璃", "sector": "建材玻璃", "multiplier": 20.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "RU_IDX": {"name": "橡胶", "sector": "能源化工", "multiplier": 10.0, "tick": 5.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "LC_IDX": {"name": "碳酸锂", "sector": "新能源", "multiplier": 1.0, "tick": 50.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "SI_IDX": {"name": "工业硅", "sector": "新能源", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "CF_IDX": {"name": "棉花", "sector": "软商品", "multiplier": 5.0, "tick": 5.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "SR_IDX": {"name": "白糖", "sector": "软商品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "C_IDX":  {"name": "玉米", "sector": "农产品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "M_IDX":  {"name": "豆粕", "sector": "农产品", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "Y_IDX":  {"name": "豆油", "sector": "油脂油料", "multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "P_IDX":  {"name": "棕榈油", "sector": "油脂油料", "multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00005, "margin_rate": 0.10},
}

BENCHMARK_UNIVERSE = list(ACTIVE_CONTRACT_SPECS.keys())
OOS_SPLIT_DATE = "2025-07-01"


def load_symbol_bars(conn: sqlite3.Connection, symbol: str, timeframe: str = "30m") -> pd.DataFrame:
    """从 ashare_quant.db 提取纯因果 30m K 线序列"""
    query = """
    SELECT trade_time, open, high, low, close, volume, open_interest
    FROM futures_min_bars
    WHERE symbol = ? AND timeframe = ?
    ORDER BY trade_time ASC
    """
    df = pd.read_sql_query(query, conn, params=(symbol, timeframe))
    if df.empty:
        return df
    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df.set_index("trade_time", inplace=True)
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    return df


def compute_stats(trades: List[Dict[str, Any]], equity_curve: List[float] = None) -> Dict[str, Any]:
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "net_profit": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "avg_trade_pnl": 0.0,
        }
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net_profit = sum(pnls)
    gross_win = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 1e-6
    profit_factor = gross_win / gross_loss
    win_rate = len(wins) / total_trades

    max_dd = 0.0
    if equity_curve and len(equity_curve) > 1:
        eq_series = pd.Series(equity_curve)
        cummax = eq_series.cummax()
        dd_series = (eq_series - cummax) / cummax.replace(0, 1)
        max_dd = abs(float(dd_series.min()))

    return {
        "total_trades": total_trades,
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "net_profit": round(net_profit, 2),
        "profit_factor": round(profit_factor, 2),
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(max_dd, 4),
        "avg_trade_pnl": round(net_profit / total_trades, 2),
    }


def simulate_single_symbol(
    df: pd.DataFrame,
    signals: pd.Series,
    factors: pd.DataFrame,
    symbol: str,
    friction_mult: float = 1.0,
    risk_pct: float = 0.015,
    initial_capital: float = 1_000_000.0,
) -> Dict[str, Any]:
    """
    RC-LSR 严格因果回测撮合引擎:
    - 绝不未来穿梭：第 t 根 Bar 收盘信号 -> 第 t+1 根 Bar 开盘市价 (Next-Open Fill) 扣除滑点撮合
    - 结构破裂与时间止损：第 t 根 Bar 收盘达标，严格保存至 pending_exit，在第 t+1 根 Bar 开盘撮合出场
    - 悲观止损优先：盘中先检查止损与跳空缺口，严禁使用同根 Bar 的 High 抬高止损逃避止损
    - 动态保本与移动吊灯：浮盈达 0.75 ATR 锁定 +0.10 ATR，浮盈达 1.40 ATR 激活 Chandelier (跟踪最高价 -1.20 ATR)
    - 逐柱动态盯市 (M2M)：包含持仓浮动盈亏，真实反映账户峰谷与最大回撤
    - 期末强制归行：最后一根 Bar 结束时清算未平仓头寸
    """
    n = len(df)
    if n < 50:
        return {"error": "样本过少"}

    spec = ACTIVE_CONTRACT_SPECS.get(
        symbol,
        {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12, "name": symbol, "sector": "其他"}
    )
    contract_mult = float(spec["multiplier"])
    tick_size = float(spec["tick"])
    fee_rate = float(spec["fee_rate"]) * friction_mult
    slippage = tick_size * friction_mult

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    times = df.index.values
    sigs = signals.values
    atrs = factors["atr"].values
    c_devs = factors["close_deviation"].values

    capital = initial_capital
    position = 0  # +1 long, -1 short, 0 flat
    lots = 0
    entry_price = 0.0
    entry_bar_idx = 0
    stop_loss = 0.0
    highest_price = 0.0
    lowest_price = 1e9
    be_locked = False
    chandelier_active = False
    holding_bars = 0
    pending_exit: str | None = None

    trades: List[Dict[str, Any]] = []
    equity_curve: List[float] = [capital]

    for i in range(1, n):
        # ----------------------------------------------------
        # 1. 严格处理上一根 Bar 收盘触发的 pending_exit (Next-Open Fill)
        # ----------------------------------------------------
        if position != 0 and pending_exit is not None:
            cur_o = opens[i]
            exit_price = (cur_o - slippage) if position == 1 else (cur_o + slippage)
            gross_pnl = (exit_price - entry_price) * lots * contract_mult if position == 1 else (entry_price - exit_price) * lots * contract_mult
            fee = (entry_price * fee_rate + exit_price * fee_rate) * lots * contract_mult
            net_pnl = gross_pnl - fee
            capital += net_pnl
            trades.append({
                "symbol": symbol,
                "direction": position,
                "lots": lots,
                "entry_price": round(entry_price, 4),
                "entry_time": str(times[entry_bar_idx]),
                "exit_price": round(exit_price, 4),
                "exit_time": str(times[i]),
                "net_pnl": round(net_pnl, 2),
                "holding_bars": holding_bars,
                "reason": pending_exit,
            })
            position = 0
            lots = 0
            pending_exit = None

        # ----------------------------------------------------
        # 2. 严格处理上一根 Bar (i-1) 收盘产生的入场信号 (Next-Open Fill)
        # ----------------------------------------------------
        prev_sig = sigs[i - 1]
        if position == 0 and prev_sig != 0:
            cur_atr = max(atrs[i - 1], opens[i] * 0.001)
            risk_amount = capital * risk_pct
            sl_dist = 0.85 * cur_atr  # 与 Rust 引擎对齐 0.85 ATR
            unit_risk = sl_dist * contract_mult
            calc_lots = int(risk_amount / max(unit_risk, 1.0))

            # S03: 增加真实保证金硬约束 (Margin Constraint)
            margin_rate = spec.get("margin_rate", 0.10)
            margin_per_lot = opens[i] * contract_mult * margin_rate
            max_margin_lots = int(capital / margin_per_lot) if margin_per_lot > 0 else 0
            calc_lots = min(calc_lots, max_margin_lots)
            calc_lots = min(calc_lots, 100)

            # 资金不足开 1 手时拒单，允许 0 手 (S03)
            if calc_lots > 0:
                if prev_sig == 1:
                    position = 1
                    lots = calc_lots
                    entry_price = opens[i] + slippage
                    stop_loss = entry_price - sl_dist
                    highest_price = entry_price
                    lowest_price = entry_price
                    be_locked = False
                    chandelier_active = False
                    holding_bars = 0
                    entry_bar_idx = i
                elif prev_sig == -1:
                    position = -1
                    lots = calc_lots
                    entry_price = opens[i] - slippage
                    stop_loss = entry_price + sl_dist
                    highest_price = entry_price
                    lowest_price = entry_price
                    be_locked = False
                    chandelier_active = False
                    holding_bars = 0
                    entry_bar_idx = i

        # ----------------------------------------------------
        # 3. 盘中与收盘持仓逻辑评估 (悲观止损优先 + 吊灯追踪)
        # ----------------------------------------------------
        if position != 0:
            holding_bars += 1
            cur_h = highs[i]
            cur_l = lows[i]
            cur_o = opens[i]
            cur_c = closes[i]
            cur_atr = max(atrs[i], cur_c * 0.001)
            cur_dev = c_devs[i]

            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            if position == 1:
                # 悲观优先检查：开盘跳空跌破 或 盘中下探跌破当前止损
                if cur_o <= stop_loss:
                    exit_triggered = True
                    exit_price = cur_o - slippage
                    exit_reason = "GAP_STOP_LOSS"
                elif cur_l <= stop_loss:
                    exit_triggered = True
                    exit_price = stop_loss - slippage
                    exit_reason = "CHANDELIER_TRAIL" if chandelier_active else ("BE_LOCK" if be_locked else "STOP_LOSS")

                if exit_triggered:
                    gross_pnl = (exit_price - entry_price) * lots * contract_mult
                    fee = (entry_price * fee_rate + exit_price * fee_rate) * lots * contract_mult
                    net_pnl = gross_pnl - fee
                    capital += net_pnl
                    trades.append({
                        "symbol": symbol,
                        "direction": position,
                        "lots": lots,
                        "entry_price": round(entry_price, 4),
                        "entry_time": str(times[entry_bar_idx]),
                        "exit_price": round(exit_price, 4),
                        "exit_time": str(times[i]),
                        "net_pnl": round(net_pnl, 2),
                        "holding_bars": holding_bars,
                        "reason": exit_reason,
                    })
                    position = 0
                    lots = 0
                else:
                    # 未触发止损，方可根据本根最高价推进止损线 (彻底打开右尾)
                    if cur_h > highest_price:
                        highest_price = cur_h
                    profit_atr = (highest_price - entry_price) / cur_atr

                    # 动态保本线 (浮盈达 0.75 ATR 锁定 +0.10 ATR 利润)
                    if not be_locked and profit_atr >= 0.75:
                        be_locked = True
                        stop_loss = max(stop_loss, entry_price + 0.10 * cur_atr)

                    # 移动吊灯追踪止盈 (Chandelier Trailing Exit): 浮盈超过 1.40 ATR 时激活，跟踪最高价回撤 1.20 ATR
                    if profit_atr >= 1.40:
                        chandelier_active = True
                        chandelier_trail = highest_price - 1.20 * cur_atr
                        stop_loss = max(stop_loss, chandelier_trail)

                    # Bar 收盘信号判断 (次柱开盘 Next-Open 撮合)
                    if cur_dev <= -3.5:
                        pending_exit = "STRUCTURAL_RUPTURE"
                    elif holding_bars >= 24:
                        pending_exit = "TIME_STOP"

            elif position == -1:
                # 空头对称悲观优先检查
                if cur_o >= stop_loss:
                    exit_triggered = True
                    exit_price = cur_o + slippage
                    exit_reason = "GAP_STOP_LOSS"
                elif cur_h >= stop_loss:
                    exit_triggered = True
                    exit_price = stop_loss + slippage
                    exit_reason = "CHANDELIER_TRAIL" if chandelier_active else ("BE_LOCK" if be_locked else "STOP_LOSS")

                if exit_triggered:
                    gross_pnl = (entry_price - exit_price) * lots * contract_mult
                    fee = (entry_price * fee_rate + exit_price * fee_rate) * lots * contract_mult
                    net_pnl = gross_pnl - fee
                    capital += net_pnl
                    trades.append({
                        "symbol": symbol,
                        "direction": position,
                        "lots": lots,
                        "entry_price": round(entry_price, 4),
                        "entry_time": str(times[entry_bar_idx]),
                        "exit_price": round(exit_price, 4),
                        "exit_time": str(times[i]),
                        "net_pnl": round(net_pnl, 2),
                        "holding_bars": holding_bars,
                        "reason": exit_reason,
                    })
                    position = 0
                    lots = 0
                else:
                    if cur_l < lowest_price:
                        lowest_price = cur_l
                    profit_atr = (entry_price - lowest_price) / cur_atr

                    if not be_locked and profit_atr >= 0.75:
                        be_locked = True
                        stop_loss = min(stop_loss, entry_price - 0.10 * cur_atr)

                    if profit_atr >= 1.40:
                        chandelier_active = True
                        chandelier_trail = lowest_price + 1.20 * cur_atr
                        stop_loss = min(stop_loss, chandelier_trail)

                    if cur_dev >= 3.5:
                        pending_exit = "STRUCTURAL_RUPTURE"
                    elif holding_bars >= 24:
                        pending_exit = "TIME_STOP"

        # ----------------------------------------------------
        # 4. 逐柱动态盯市 (Mark-to-Market Equity)
        # ----------------------------------------------------
        if position == 1:
            unrealized_pnl = (closes[i] - entry_price) * lots * contract_mult
            m2m_equity = capital + unrealized_pnl
        elif position == -1:
            unrealized_pnl = (entry_price - closes[i]) * lots * contract_mult
            m2m_equity = capital + unrealized_pnl
        else:
            m2m_equity = capital

        equity_curve.append(m2m_equity)

    # ----------------------------------------------------
    # 5. 期末头寸强制清算 (Terminal Settlement)
    # ----------------------------------------------------
    if position != 0:
        last_i = n - 1
        exit_price = (closes[last_i] - slippage) if position == 1 else (closes[last_i] + slippage)
        gross_pnl = (exit_price - entry_price) * lots * contract_mult if position == 1 else (entry_price - exit_price) * lots * contract_mult
        fee = (entry_price * fee_rate + exit_price * fee_rate) * lots * contract_mult
        net_pnl = gross_pnl - fee
        capital += net_pnl
        trades.append({
            "symbol": symbol,
            "direction": position,
            "lots": lots,
            "entry_price": round(entry_price, 4),
            "entry_time": str(times[entry_bar_idx]),
            "exit_price": round(exit_price, 4),
            "exit_time": str(times[last_i]),
            "net_pnl": round(net_pnl, 2),
            "holding_bars": holding_bars,
            "reason": "TERMINAL_SETTLEMENT",
        })
        position = 0
        equity_curve[-1] = capital

    # ----------------------------------------------------
    # 6. 分段统计 (全样本 vs 训练段 vs 样本外盲测段, S02)
    # ----------------------------------------------------
    train_trades = [t for t in trades if t["entry_time"] < OOS_SPLIT_DATE]
    oos_trades = [t for t in trades if t["entry_time"] >= OOS_SPLIT_DATE]

    # S02: 提取对应时段的真实权益子序列，防止分段回撤恒为 0
    oos_mask = [str(t) >= OOS_SPLIT_DATE for t in times]
    train_equity = [eq for eq, m in zip(equity_curve, oos_mask) if not m]
    oos_equity = [eq for eq, m in zip(equity_curve, oos_mask) if m]

    overall_stats = compute_stats(trades, equity_curve)
    train_stats = compute_stats(train_trades, train_equity)
    oos_stats = compute_stats(oos_trades, oos_equity)

    exit_reasons = {}
    for t in trades:
        r = t["reason"]
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    return {
        "symbol": symbol,
        "name": spec.get("name", symbol),
        "sector": spec.get("sector", "其他"),
        "overall": overall_stats,
        "train": train_stats,
        "oos": oos_stats,
        "exit_reasons": exit_reasons,
        "trades_count": len(trades),
        "trades_sample": trades[:3],
    }


def run_full_audit():
    print("=" * 96)
    print("  「RC-LSR·市场状态条件化流动性冲击反转策略」25品种因果审计与严密样本外盲测")
    print("  时序标准: 严格Next-Open市价撮合 | 移动吊灯追踪 | 悲观止损优先 | 动态逐柱盯市M2M")
    print(f"  样本内(Train): 2023.01 ~ 2025.06 | 样本外盲测(OOS): 2025.07 ~ 2026.08")
    print("=" * 96)

    conn = sqlite3.connect(DB_PATH)
    results_0x: Dict[str, Any] = {}
    results_1x: Dict[str, Any] = {}
    results_3x: Dict[str, Any] = {}

    for symbol in BENCHMARK_UNIVERSE:
        spec = ACTIVE_CONTRACT_SPECS[symbol]
        name = spec["name"]
        df = load_symbol_bars(conn, symbol, timeframe="30m")
        if df.empty or len(df) < 200:
            print(f"[-] {symbol} ({name}): 样本数据不足，跳过")
            continue

        factors = rc_lsr_mod.calculate_factors(df)
        signals = rc_lsr_mod.calculate_signal(df, cooldown_bars=8)

        # 0x 纯毛收益 (检验数学反转内核是否存在)
        res_0x = simulate_single_symbol(df, signals, factors, symbol, friction_mult=0.0)
        results_0x[symbol] = res_0x

        # 1x 标准交易成本 (1 Tick 滑点 + 双边万0.5手续费)
        res_1x = simulate_single_symbol(df, signals, factors, symbol, friction_mult=1.0)
        results_1x[symbol] = res_1x

        # 3x 极端流动性枯竭压力测试 (3 Tick 滑点 + 3倍规费)
        res_3x = simulate_single_symbol(df, signals, factors, symbol, friction_mult=3.0)
        results_3x[symbol] = res_3x

    conn.close()

    # 1. 打印全品种 1x vs 3x 对比报表
    print(f"\n【一、全样本 1x vs 3x 摩擦压测对照表 (25 品种)】")
    print(f"{'代码':<8}{'名称':<6}{'板块':<6}{'交易数':<7}{'1x净利润(元)':<14}{'1x PF':<7}{'1x胜率':<8}{'3x净利润(元)':<14}{'3x PF':<7}{'3x胜率':<8}{'M2M回撤':<8}")
    print("-" * 105)

    tot_trades = 0
    tot_net_0x = 0.0
    tot_net_1x = 0.0
    tot_net_3x = 0.0
    tot_wins_1x = 0
    tot_losses_1x = 0

    tot_train_pnl_1x = 0.0
    tot_oos_pnl_1x = 0.0
    tot_train_trades = 0
    tot_oos_trades = 0

    combined_exit_reasons: Dict[str, int] = {}

    for symbol in BENCHMARK_UNIVERSE:
        if symbol not in results_1x:
            continue
        r0 = results_0x[symbol]
        r1 = results_1x[symbol]
        r3 = results_3x[symbol]
        o1 = r1["overall"]
        o3 = r3["overall"]
        name = r1["name"]
        sector = r1["sector"]

        tot_trades += o1["total_trades"]
        tot_net_0x += r0["overall"]["net_profit"]
        tot_net_1x += o1["net_profit"]
        tot_net_3x += o3["net_profit"]
        tot_wins_1x += o1["win_trades"]
        tot_losses_1x += o1["loss_trades"]

        tot_train_pnl_1x += r1["train"]["net_profit"]
        tot_oos_pnl_1x += r1["oos"]["net_profit"]
        tot_train_trades += r1["train"]["total_trades"]
        tot_oos_trades += r1["oos"]["total_trades"]

        for reason, cnt in r1["exit_reasons"].items():
            combined_exit_reasons[reason] = combined_exit_reasons.get(reason, 0) + cnt

        print(
            f"{symbol:<8}{name:<6}{sector:<6}{o1['total_trades']:<7}"
            f"{o1['net_profit']:>12,.2f}  {o1['profit_factor']:<7}{o1['win_rate']*100:>5.1f}%   "
            f"{o3['net_profit']:>12,.2f}  {o3['profit_factor']:<7}{o3['win_rate']*100:>5.1f}%   "
            f"{o1['max_drawdown']*100:>5.1f}%"
        )

    print("-" * 105)
    overall_win_rate_1x = (tot_wins_1x / max(tot_trades, 1)) * 100
    print(f"【全组合 1x 汇总】 交易数: {tot_trades} | 胜率: {overall_win_rate_1x:.1f}% | 0x毛利: {tot_net_0x:+,.2f} | 1x净利: {tot_net_1x:+,.2f} | 3x净利: {tot_net_3x:+,.2f}")

    # 2. 打印样本内 (Train) 与 样本外盲测 (OOS) 对照表
    print(f"\n【二、严格因果时间盲测对照表 (Train 2023.01~2025.06 vs OOS 2025.07~2026.08)】")
    print(f"{'代码':<8}{'名称':<6}{'Train交易':<10}{'Train净利(元)':<14}{'Train PF':<10}{'OOS交易':<9}{'OOS净利(元)':<14}{'OOS PF':<9}{'OOS状态'}")
    print("-" * 92)

    oos_pos_symbols = []
    oos_neg_symbols = []

    for symbol in BENCHMARK_UNIVERSE:
        if symbol not in results_1x:
            continue
        r1 = results_1x[symbol]
        tr = r1["train"]
        os_ = r1["oos"]
        name = r1["name"]

        status = "✅ 盈利" if os_["net_profit"] > 0 else "❌ 亏损"
        if os_["net_profit"] > 0:
            oos_pos_symbols.append(symbol)
        else:
            oos_neg_symbols.append(symbol)

        print(
            f"{symbol:<8}{name:<6}{tr['total_trades']:<10}"
            f"{tr['net_profit']:>12,.2f}  {tr['profit_factor']:<10}"
            f"{os_['total_trades']:<9}"
            f"{os_['net_profit']:>12,.2f}  {os_['profit_factor']:<9}"
            f"{status}"
        )

    print("-" * 92)
    print(f"【阶段汇总】 Train 净利: {tot_train_pnl_1x:+,.2f} 元 (交易 {tot_train_trades}) | OOS 盲测净利: {tot_oos_pnl_1x:+,.2f} 元 (交易 {tot_oos_trades})")
    print(f"【OOS 盈利品种占比】 {len(oos_pos_symbols)} / {len(results_1x)} ({len(oos_pos_symbols)/len(results_1x)*100:.1f}%)")

    # 3. 打印平仓出场原因分布
    print(f"\n【三、平仓出场行为学分布】")
    for reason, cnt in sorted(combined_exit_reasons.items(), key=lambda x: -x[1]):
        pct = cnt / max(tot_trades, 1) * 100
        print(f"  - {reason:<22}: {cnt:>5} 次 ({pct:>5.1f}%)")

    # 4. 保存 JSON 报告
    report_payload = {
        "strategy": "RC-LSR (Regime-Conditioned Liquidity Shock Reversal)",
        "timeframe": "30m",
        "oos_split_date": OOS_SPLIT_DATE,
        "friction_0x": results_0x,
        "friction_1x": results_1x,
        "friction_3x": results_3x,
        "summary": {
            "total_trades": tot_trades,
            "win_rate_1x_pct": round(overall_win_rate_1x, 2),
            "net_pnl_0x": round(tot_net_0x, 2),
            "net_pnl_1x": round(tot_net_1x, 2),
            "net_pnl_3x": round(tot_net_3x, 2),
            "train_pnl_1x": round(tot_train_pnl_1x, 2),
            "oos_pnl_1x": round(tot_oos_pnl_1x, 2),
            "oos_positive_count": len(oos_pos_symbols),
            "total_symbols": len(results_1x),
            "exit_reasons": combined_exit_reasons,
        }
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    print(f"\n[+] 25品种完整因果审计报告已保存至: {REPORT_JSON}")


if __name__ == "__main__":
    run_full_audit()
