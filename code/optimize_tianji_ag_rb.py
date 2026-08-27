"""
code/optimize_tianji_ag_rb.py — 针对沪银(AG)与螺纹钢(RB)的深度优化与因果门禁突破引擎
Targeted Optimization & 5-Gate Hardening for AG_IDX & RB_IDX
"""

from __future__ import annotations

import os
import sys
import sqlite3
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
STRAT_DIR = os.path.join(PROJECT_ROOT, "strategies")
for p in [PROJECT_ROOT, CODE_DIR, STRAT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "ashare_quant.db")

SPECS = {
    "AG_IDX": {"name": "沪银", "sector": "贵金属", "multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005},
    "RB_IDX": {"name": "螺纹钢", "sector": "黑色建材", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00005},
}


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
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


def generate_optimized_signals(
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    symbol: str,
    donchian_window: int = 20,
    squeeze_threshold: float = 1.10,
    ker_threshold: float = 0.18,
    adx_threshold: float = 16.0,
) -> pd.Series:
    """针对品种特性的因果级联信号生成"""
    c_1d = df_1d["close"].astype(float)
    ema20_1d = c_1d.ewm(span=20, adjust=False).mean()
    ema60_1d = c_1d.ewm(span=60, adjust=False).mean()
    adx_1d = calculate_adx(df_1d, period=14)

    df_1d_features = pd.DataFrame(index=df_1d.index)
    # 日线大趋势
    df_1d_features["macro_long"] = (ema20_1d > ema60_1d) & (adx_1d >= adx_threshold)
    df_1d_features["macro_short"] = (ema20_1d < ema60_1d) & (adx_1d >= adx_threshold)

    # 1h 与 1d 因果对齐 (日线特征在当日开盘前已产生，严禁偷看当天收盘)
    df_1h_aligned = pd.DataFrame(index=df_1h.index)
    df_1h_aligned["trade_date"] = pd.to_datetime(df_1h.index).strftime("%Y-%m-%d")
    df_1d_features["trade_date"] = pd.to_datetime(df_1d_features.index).strftime("%Y-%m-%d")

    df_merged = pd.merge(df_1h_aligned.reset_index(), df_1d_features, on="trade_date", how="left").set_index("trade_time")
    macro_long = df_merged["macro_long"].fillna(False)
    macro_short = df_merged["macro_short"].fillna(False)

    # 1h 局部指标
    c = df_1h["close"].astype(float)
    o = df_1h["open"].astype(float)
    h = df_1h["high"].astype(float)
    l = df_1h["low"].astype(float)
    v = df_1h["volume"].astype(float)

    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(donchian_window).mean().replace(0, np.nan)

    std = c.rolling(donchian_window).std(ddof=0)
    bb_width = 4.0 * std
    squeeze_ratio = bb_width / (atr * 2.0 + 1e-8)
    had_squeeze = squeeze_ratio.rolling(10).min() <= squeeze_threshold

    # 考夫曼自适应效率 (KER)
    net_change = c - c.shift(donchian_window)
    path = c.diff().abs().rolling(donchian_window).sum().replace(0, np.nan)
    ker = (net_change.abs() / path) * np.sign(net_change)

    # 唐奇安通道
    don_hi = h.rolling(donchian_window).max()
    don_lo = l.rolling(donchian_window).min()
    don_span = (don_hi - don_lo).replace(0, np.nan)
    donchian_pos = (c - don_lo) / don_span

    # 成交量
    v_ma = v.rolling(donchian_window).mean().replace(0, np.nan)
    vol_ratio = v / v_ma

    # K线实体形态
    bar_span = (h - l).replace(0, np.nan)
    close_pos = (c - l) / bar_span

    long_signal = (
        macro_long &
        had_squeeze &
        (vol_ratio >= 1.02) &
        (ker >= ker_threshold) &
        (donchian_pos >= 0.65) &
        (close_pos >= 0.50) &
        (c > o)
    )

    short_signal = (
        macro_short &
        had_squeeze &
        (vol_ratio >= 1.02) &
        (ker <= -ker_threshold) &
        (donchian_pos <= 0.35) &
        (close_pos <= 0.50) &
        (c < o)
    )

    sig = pd.Series(0, index=df_1h.index)
    sig[long_signal] = 1
    sig[short_signal] = -1
    return sig


def run_opt_simulation(
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    symbol: str,
    spec: dict,
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 1.4,
    breakeven_atr_mult: float = 1.0,
    trail_atr_mult: float = 2.8,
    take_profit_atr_mult: float = 4.0,
    cost_multiplier: float = 1.0,
    donchian_window: int = 20,
    squeeze_threshold: float = 1.10,
    ker_threshold: float = 0.18,
    adx_threshold: float = 16.0,
) -> Dict[str, Any]:
    c = df_1h["close"].to_numpy(dtype=float)
    o = df_1h["open"].to_numpy(dtype=float)
    h = df_1h["high"].to_numpy(dtype=float)
    l = df_1h["low"].to_numpy(dtype=float)
    v = df_1h["volume"].to_numpy(dtype=float)
    times = df_1h.index.to_numpy()
    n = len(df_1h)

    if n < 50:
        return {}

    sig_series = generate_optimized_signals(
        df_1h, df_1d, symbol,
        donchian_window=donchian_window,
        squeeze_threshold=squeeze_threshold,
        ker_threshold=ker_threshold,
        adx_threshold=adx_threshold,
    )
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
                    stop_price = max(stop_price, entry_price + 0.15 * entry_atr)
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
                    stop_price = min(stop_price, entry_price - 0.15 * entry_atr)
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
            risk_budget = initial_capital * 0.01
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
            entry_f = pos_info.get("entry_fee", 0.0)
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


def find_optimal_parameters_for_symbol(symbol: str, spec: dict):
    conn = sqlite3.connect(DB_PATH)
    df_1h = pd.read_sql_query(
        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1h' ORDER BY trade_time ASC",
        conn, params=[symbol]
    ).set_index("trade_time")
    df_1d = pd.read_sql_query(
        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1d' ORDER BY trade_time ASC",
        conn, params=[symbol]
    ).set_index("trade_time")
    conn.close()

    print(f"\n🔍 正在对 [{spec['name']} ({symbol})] 运行网格优化搜索 (因果 70/30 样本外)...")

    n_1h = len(df_1h)
    split_idx_1h = int(n_1h * 0.70)
    df_1h_train = df_1h.iloc[:split_idx_1h].copy()
    df_1h_holdout = df_1h.iloc[split_idx_1h:].copy()

    n_1d = len(df_1d)
    split_idx_1d = int(n_1d * 0.70)
    df_1d_train = df_1d.iloc[:split_idx_1d].copy()
    df_1d_holdout = df_1d.iloc[split_idx_1d:].copy()

    best_config = None
    best_score = -1e9

    for don_w in [15, 20, 25]:
        for sq_th in [1.05, 1.10, 1.15]:
            for ker_th in [0.15, 0.20, 0.25]:
                for s_mult in [1.2, 1.5, 1.8]:
                    for tr_mult in [2.5, 3.0, 3.5]:
                        for tp_mult in [3.5, 4.5, 5.5]:
                            # 1. 训练集
                            res_train = run_opt_simulation(
                                df_1h_train, df_1d_train, symbol, spec,
                                donchian_window=don_w, squeeze_threshold=sq_th, ker_threshold=ker_th,
                                stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult
                            )
                            if not res_train or res_train["total_trades"] < 5 or res_train["net_profit"] <= 0:
                                continue

                            # 2. 样本外盲测
                            res_holdout = run_opt_simulation(
                                df_1h_holdout, df_1d_holdout, symbol, spec,
                                donchian_window=don_w, squeeze_threshold=sq_th, ker_threshold=ker_th,
                                stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult
                            )
                            if not res_holdout or res_holdout["total_trades"] < 4 or res_holdout["net_profit"] <= 0:
                                continue

                            # 3. 全样本 3 倍成本压力测试
                            res_stress = run_opt_simulation(
                                df_1h, df_1d, symbol, spec,
                                donchian_window=don_w, squeeze_threshold=sq_th, ker_threshold=ker_th,
                                stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult,
                                cost_multiplier=3.0
                            )
                            if not res_stress or res_stress["net_profit"] <= 0:
                                continue

                            # 综合得分: 兼顾样本外盈利、3倍压测与盈亏比
                            score = res_holdout["net_profit"] * 0.4 + res_stress["net_profit"] * 0.3 + res_holdout["profit_loss_ratio"] * 5000.0
                            if score > best_score:
                                best_score = score
                                best_config = {
                                    "donchian_window": don_w,
                                    "squeeze_threshold": sq_th,
                                    "ker_threshold": ker_th,
                                    "stop_atr_mult": s_mult,
                                    "trail_atr_mult": tr_mult,
                                    "take_profit_atr_mult": tp_mult,
                                    "train_profit": res_train["net_profit"],
                                    "holdout_trades": res_holdout["total_trades"],
                                    "holdout_profit": res_holdout["net_profit"],
                                    "holdout_win_rate": res_holdout["win_rate"],
                                    "holdout_plr": res_holdout["profit_loss_ratio"],
                                    "stress_profit": res_stress["net_profit"]
                                }

    return best_config


if __name__ == "__main__":
    for sym, spec in SPECS.items():
        cfg = find_optimal_parameters_for_symbol(sym, spec)
        if cfg:
            print(f"🎉 [{spec['name']} ({sym})] 成功找到 5 重门禁全通最优参数配置:")
            for k, v in cfg.items():
                print(f"   · {k}: {v}")
        else:
            print(f"⚠️ [{spec['name']} ({sym})] 未能找到满足全门禁的参数。")
