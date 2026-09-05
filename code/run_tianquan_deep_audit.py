"""
code/run_tianquan_deep_audit.py — 「天权·极值条件相变反转策略」工业级多品种多周期因果回测与压力审计
Tianquan Extreme-Phase Reversal Causal Audit Runner
"""

from __future__ import annotations

import json
import math
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

import tianquan_extreme_phase_reversal as tianquan_mod

DB_PATH = str(DATA_DIR / "ashare_quant.db")
REPORT_JSON = DATA_DIR / "tianquan_deep_audit_report.json"

ACTIVE_CONTRACT_SPECS = {
    "AU_IDX": {"name": "沪金", "sector": "贵金属", "multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00005, "margin_rate": 0.10},
    "AG_IDX": {"name": "沪银", "sector": "贵金属", "multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "RB_IDX": {"name": "螺纹钢", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "CU_IDX": {"name": "沪铜", "sector": "有色金属", "multiplier": 5.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "SC_IDX": {"name": "原油", "sector": "能源化工", "multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005, "margin_rate": 0.12},
    "TA_IDX": {"name": "PTA", "sector": "纺织化工", "multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "MA_IDX": {"name": "甲醇", "sector": "能源化工", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "LC_IDX": {"name": "碳酸锂", "sector": "新能源", "multiplier": 1.0, "tick": 50.0, "fee_rate": 0.00005, "margin_rate": 0.15},
    "SN_IDX": {"name": "沪锡", "sector": "有色金属", "multiplier": 1.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "SA_IDX": {"name": "纯碱", "sector": "能源化工", "multiplier": 20.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
}

BENCHMARK_UNIVERSE = list(ACTIVE_CONTRACT_SPECS.keys())


def load_symbol_bars(conn: sqlite3.Connection, symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    """从 ashare_quant.db 提取纯因果分钟 K 线序列"""
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
    纯因果逐柱模拟器:
    - 第 t 根 Bar 收盘信号 -> 第 t+1 根 Bar 开盘价 (Next-Open) + 1 Tick 滑点撮合
    - 初始止损 1.2 * ATR
    - 保本触发 1.0 * ATR
    - 动态吊灯追踪 2.5 * ATR (无微观死止盈，捕捉肥尾)
    - 最大持仓 40 根 Bar 超时出场
    """
    n = len(df)
    if n < 50:
        return {"error": "样本过少"}

    spec = ACTIVE_CONTRACT_SPECS.get(symbol, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12})
    contract_mult = float(spec["multiplier"])
    tick_size = float(spec["tick"])
    fee_rate = float(spec["fee_rate"]) * friction_mult
    slippage = tick_size * friction_mult

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df.index
    sigs = signals.values
    atrs = factors["atr"].values

    capital = initial_capital
    position = 0  # +1 long, -1 short, 0 flat
    lots = 0
    entry_price = 0.0
    stop_loss = 0.0
    highest_price = 0.0
    lowest_price = 1e9
    be_locked = False
    holding_bars = 0

    trades: List[Dict[str, Any]] = []
    equity_curve: List[float] = [capital]

    sma_20_arr = factors["atr"].values  # will use filt_slow
    filt_slow_arr = factors["filt_slow"].values

    for i in range(1, n):
        # 1. 优先检查当前持仓的出场判定 (在第 i 根 Bar 内发生)
        if position != 0:
            holding_bars += 1
            cur_h = highs[i]
            cur_l = lows[i]
            cur_o = opens[i]
            cur_c = closes[i]
            cur_atr = atrs[i]
            center_price = filt_slow_arr[i]
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            if position == 1:
                if cur_h > highest_price:
                    highest_price = cur_h

                float_gain = highest_price - entry_price

                # 动态保本: 浮盈达到 1.0 * ATR，抬升至 Entry + 0.1 * ATR
                if not be_locked and float_gain >= 1.0 * cur_atr:
                    stop_loss = max(stop_loss, entry_price + 0.1 * cur_atr)
                    be_locked = True

                # 动态吊灯追踪: 浮盈扩大至 1.8 * ATR 以上，按最高价回撤 2.5 * ATR 宽幅追踪，不截断右尾
                if float_gain >= 1.8 * cur_atr:
                    trail_stop = highest_price - 2.5 * cur_atr
                    stop_loss = max(stop_loss, trail_stop)

                # 判定出场
                if cur_l <= stop_loss:
                    exit_triggered = True
                    exit_price = min(cur_o, stop_loss) - slippage
                    exit_reason = "STOP_OR_TRAILING"
                elif holding_bars >= 40:
                    exit_triggered = True
                    exit_price = cur_o - slippage
                    exit_reason = "TIMEOUT"

            elif position == -1:
                if cur_l < lowest_price:
                    lowest_price = cur_l

                float_gain = entry_price - lowest_price

                # 动态保本: 浮盈达到 1.0 * ATR，抬升至 Entry - 0.1 * ATR
                if not be_locked and float_gain >= 1.0 * cur_atr:
                    stop_loss = min(stop_loss, entry_price - 0.1 * cur_atr)
                    be_locked = True

                # 动态吊灯追踪: 浮盈扩大至 1.8 * ATR 以上，按最低价反弹 2.5 * ATR 宽幅追踪，不截断右尾
                if float_gain >= 1.8 * cur_atr:
                    trail_stop = lowest_price + 2.5 * cur_atr
                    stop_loss = min(stop_loss, trail_stop)

                # 判定出场
                if cur_h >= stop_loss:
                    exit_triggered = True
                    exit_price = max(cur_o, stop_loss) + slippage
                    exit_reason = "STOP_OR_TRAILING"
                elif holding_bars >= 40:
                    exit_triggered = True
                    exit_price = cur_o + slippage
                    exit_reason = "TIMEOUT"

            if exit_triggered:
                # 结算平仓
                gross_pnl = (exit_price - entry_price) * lots * contract_mult if position == 1 else (entry_price - exit_price) * lots * contract_mult
                fee = (entry_price * fee_rate + exit_price * fee_rate) * lots * contract_mult
                net_pnl = gross_pnl - fee
                capital += net_pnl
                trades.append({
                    "symbol": symbol,
                    "direction": position,
                    "lots": lots,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "net_pnl": net_pnl,
                    "holding_bars": holding_bars,
                    "reason": exit_reason
                })
                position = 0
                lots = 0

        # 2. 检查前一根 Bar (i-1) 收盘信号触发开仓 (在第 i 根 Bar 开盘按 Next-Open 撮合)
        prev_sig = sigs[i - 1]
        if position == 0 and prev_sig != 0:
            cur_atr = atrs[i - 1]
            risk_amount = capital * risk_pct
            sl_dist = 1.2 * cur_atr
            unit_risk = sl_dist * contract_mult
            calc_lots = int(risk_amount / max(unit_risk, 1.0))
            calc_lots = max(1, min(calc_lots, 100))

            if prev_sig == 1:
                position = 1
                lots = calc_lots
                entry_price = opens[i] + slippage
                stop_loss = entry_price - 1.2 * cur_atr
                highest_price = entry_price
                be_locked = False
                holding_bars = 0
            elif prev_sig == -1:
                position = -1
                lots = calc_lots
                entry_price = opens[i] - slippage
                stop_loss = entry_price + 1.2 * cur_atr
                lowest_price = entry_price
                be_locked = False
                holding_bars = 0

        equity_curve.append(capital)

    # 计算统计指标
    if not trades:
        return {
            "symbol": symbol, "trades": 0, "net_pnl": 0.0, "win_rate": 0.0,
            "profit_factor": 0.0, "max_dd_pct": 0.0, "sharpe": 0.0
        }

    pnls = [t["net_pnl"] for t in trades]
    total_net = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99.0

    eq = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq)
    dds = (peaks - eq) / peaks
    max_dd = np.max(dds) * 100.0 if len(dds) > 0 else 0.0

    returns = np.diff(eq) / eq[:-1]
    sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * math.sqrt(252 * 16) if len(returns) > 1 else 0.0

    return {
        "symbol": symbol,
        "trades": len(trades),
        "net_pnl": round(total_net, 2),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "max_dd_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "avg_trade_pnl": round(total_net / len(trades), 2),
        "trades_list": trades
    }


def run_full_market_audit():
    print("=" * 75)
    print("「天权·极值条件相变反转策略」全市场工业级深度审计")
    print(f"数据源: {DB_PATH}")
    print("=" * 75)

    conn = sqlite3.connect(DB_PATH)
    timeframes = ["15m", "30m"]
    audit_results: Dict[str, Any] = {
        "strategy": tianquan_mod.STRATEGY_NAME,
        "description": tianquan_mod.STRATEGY_DESCRIPTION,
        "universe": BENCHMARK_UNIVERSE,
        "timeframe_metrics": {}
    }

    for tf in timeframes:
        print(f"\n>>> 正在审计时间级别: {tf} <<<")
        tf_summary_1x: List[Dict[str, Any]] = []
        tf_summary_3x: List[Dict[str, Any]] = []
        tf_summary_oos: List[Dict[str, Any]] = []

        for symbol in BENCHMARK_UNIVERSE:
            df = load_symbol_bars(conn, symbol, timeframe=tf)
            if df.empty or len(df) < 200:
                continue

            signals = tianquan_mod.calculate_signal(df)
            factors = tianquan_mod.calculate_factors(df)

            # 1. 正常 1x 成本
            res_1x = simulate_single_symbol(df, signals, factors, symbol, friction_mult=1.0)
            tf_summary_1x.append(res_1x)

            # 2. 极端 3x 成本压力测试
            res_3x = simulate_single_symbol(df, signals, factors, symbol, friction_mult=3.0)
            tf_summary_3x.append(res_3x)

            # 3. 70/30 严格样本外 (OOS) 盲测
            split_idx = int(len(df) * 0.7)
            df_oos = df.iloc[split_idx:].copy()
            sig_oos = tianquan_mod.calculate_signal(df_oos)
            fac_oos = tianquan_mod.calculate_factors(df_oos)
            res_oos = simulate_single_symbol(df_oos, sig_oos, fac_oos, symbol, friction_mult=1.0)
            tf_summary_oos.append(res_oos)

            print(f"  [{symbol:7s}] 1x 净利: ¥{res_1x['net_pnl']:>10.2f} | 交易: {res_1x['trades']:>3d} 笔 | 胜率: {res_1x['win_rate']:>5.1f}% | PF: {res_1x['profit_factor']:>4.2f} | 3x 净利: ¥{res_3x['net_pnl']:>10.2f}")

        # 汇总
        total_pnl_1x = sum(r["net_pnl"] for r in tf_summary_1x)
        total_trades_1x = sum(r["trades"] for r in tf_summary_1x)
        profit_symbols_1x = sum(1 for r in tf_summary_1x if r["net_pnl"] > 0)
        cov_1x = (profit_symbols_1x / len(tf_summary_1x)) * 100.0 if tf_summary_1x else 0.0

        total_pnl_3x = sum(r["net_pnl"] for r in tf_summary_3x)
        total_pnl_oos = sum(r["net_pnl"] for r in tf_summary_oos)

        print("-" * 75)
        print(f"【{tf} 汇总看板】")
        print(f"• 1x 总净利润: ¥{total_pnl_1x:>12.2f} (品种盈利覆盖率: {cov_1x:.1f}%)")
        print(f"• 1x 总交易笔数: {total_trades_1x} 笔")
        print(f"• 3x 极端压力净利: ¥{total_pnl_3x:>12.2f}")
        print(f"• 30% OOS 盲测净利: ¥{total_pnl_oos:>12.2f}")

        audit_results["timeframe_metrics"][tf] = {
            "total_net_pnl_1x": round(total_pnl_1x, 2),
            "total_trades_1x": total_trades_1x,
            "profitable_symbols_pct": round(cov_1x, 2),
            "total_net_pnl_3x": round(total_pnl_3x, 2),
            "total_net_pnl_oos": round(total_pnl_oos, 2),
            "symbols_detail": tf_summary_1x
        }

    conn.close()

    # 判定实盘准入决策
    all_pnl_1x = sum(m["total_net_pnl_1x"] for m in audit_results["timeframe_metrics"].values())
    all_pnl_3x = sum(m["total_net_pnl_3x"] for m in audit_results["timeframe_metrics"].values())
    all_pnl_oos = sum(m["total_net_pnl_oos"] for m in audit_results["timeframe_metrics"].values())

    is_accepted = (all_pnl_1x > 0) and (all_pnl_3x > 0) and (all_pnl_oos > 0)
    audit_results["decision"] = "APPROVED_FOR_INCUBATION" if is_accepted else "REVISE_PARAMETERS"
    audit_results["summary"] = {
        "all_pnl_1x": round(all_pnl_1x, 2),
        "all_pnl_3x": round(all_pnl_3x, 2),
        "all_pnl_oos": round(all_pnl_oos, 2),
    }

    # 写入报告
    clean_results = json.loads(json.dumps(audit_results, default=str))
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(clean_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print(f"★ 审计决策结论: {audit_results['decision']}")
    print(f"★ 审计报告已保存至: {REPORT_JSON}")
    print("=" * 75)


if __name__ == "__main__":
    run_full_market_audit()
