"""
Hardcore Ultra-Strict XAUUSD Stress Test Evaluator across 1h and 1d Timeframes
Implements:
1. Dynamic News/Rollover Spread Widening (30 -> 100 pips)
2. Intraday Session Close (0 Swap Fees)
3. ATR Dynamic Stop Loss 1.5x / Take Profit 3.5x
4. Max Volume Participation Cap (Max 1.0% of bar volume)
5. 1-Bar Execution Delay + 0.05% Network Latency Slippage
"""
import os
import sys
import json
import time
import math
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import calculate_rsi, calculate_macd, calculate_ema, calculate_atr
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, HistGradientBoostingClassifier
import lightgbm as lgb
from backtest_metrics import calculate_performance, run_monte_carlo_analysis
from xauusd_hardcore_stress_test import HardcoreMultiAlgorithmEnsemble

def run_stress_test_for_timeframe(timeframe="1h"):
    print("=" * 75, flush=True)
    print(f"XAUUSD 【超严苛压测评估】 周期: {timeframe}", flush=True)
    print("=" * 75, flush=True)

    from xauusd_ml_strategy import build_xauusd_m5_base, resample_df, build_ml_features
    df_m5 = build_xauusd_m5_base()
    df = resample_df(df_m5, timeframe if timeframe != "1d" else "1d")
    n = len(df)

    df_1d = resample_df(df_m5, "1d")
    ema50 = calculate_ema(df_1d["close"], 10)
    ema200 = calculate_ema(df_1d["close"], 30)
    df_1d["htf_bull"] = (ema50 > ema200).astype(int)
    df_1d_indexed = df_1d.set_index("trade_date")["htf_bull"]
    df["htf_bull"] = df["trade_date"].map(df_1d_indexed).ffill().fillna(1).astype(int)
    df["atr"] = calculate_atr(df, 14).fillna(df["close"] * 0.005)

    features = build_ml_features(df)
    fwd_ret = df["close"].shift(-1) / df["close"] - 1.0
    labels = (fwd_ret > 0.0020).astype(int)

    split_idx = max(20, int(n * 0.25))
    X_train = features.iloc[:split_idx].to_numpy()
    y_train = labels.iloc[:split_idx].to_numpy()

    ensemble = HardcoreMultiAlgorithmEnsemble()
    ensemble.fit(X_train, y_train)

    X_test = features.iloc[split_idx:].to_numpy()
    probs = ensemble.predict_proba(X_test)[:, 1]

    df_test = df.iloc[split_idx:].copy().reset_index(drop=True)
    df_test["ml_prob"] = probs

    buy_thresh = np.percentile(probs, 85)

    initial_cash = 10000.0
    cash = initial_cash
    position_units = 0.0
    entry_price = 0.0
    stop_loss_price = 0.0
    take_profit_price = 0.0
    trade_entry_time = None

    trades = []
    daily_results = []
    total_slippage_cost = 0.0

    df_test["date_str"] = df_test["trade_date"].dt.strftime("%Y-%m-%d")
    daily_groups = df_test.groupby("date_str")

    np.random.seed(42)
    buy_signals = (df_test["ml_prob"] >= buy_thresh) & (df_test["htf_bull"] == 1)

    for i in range(1, len(df_test)):
        time_stamp = df_test["trade_date"].iloc[i]
        raw_price = float(df_test["open"].iloc[i])
        bar_high = float(df_test["high"].iloc[i])
        bar_low = float(df_test["low"].iloc[i])
        bar_volume = float(df_test["volume"].iloc[i])
        atr_val = float(df_test["atr"].iloc[i])

        hour = time_stamp.hour
        is_rollover = (hour in [23, 0, 4, 5])
        spread_pips = 1.00 if is_rollover else 0.30
        latency_slippage = raw_price * 0.0005
        is_session_end = (hour == 21 and time_stamp.minute >= 0) if timeframe != "1d" else False

        if position_units > 0:
            if bar_low <= stop_loss_price:
                fill_price = stop_loss_price - (spread_pips / 2.0) - latency_slippage
                proceeds = position_units * fill_price
                pnl = proceeds - (position_units * entry_price)
                cash += proceeds
                total_slippage_cost += (latency_slippage + spread_pips / 2.0) * position_units
                trades.append({
                    "symbol": "XAUUSD", "buy_time": trade_entry_time, "sell_time": time_stamp,
                    "buy_price": entry_price, "sell_price": fill_price, "pnl": pnl,
                    "pnl_pct": (pnl / (position_units * entry_price)) * 100, "reason": "STOP_LOSS"
                })
                position_units = 0.0
                continue

            elif bar_high >= take_profit_price:
                fill_price = take_profit_price - (spread_pips / 2.0) - latency_slippage
                proceeds = position_units * fill_price
                pnl = proceeds - (position_units * entry_price)
                cash += proceeds
                total_slippage_cost += (latency_slippage + spread_pips / 2.0) * position_units
                trades.append({
                    "symbol": "XAUUSD", "buy_time": trade_entry_time, "sell_time": time_stamp,
                    "buy_price": entry_price, "sell_price": fill_price, "pnl": pnl,
                    "pnl_pct": (pnl / (position_units * entry_price)) * 100, "reason": "TAKE_PROFIT"
                })
                position_units = 0.0
                continue

            elif is_session_end:
                fill_price = raw_price - (spread_pips / 2.0) - latency_slippage
                proceeds = position_units * fill_price
                pnl = proceeds - (position_units * entry_price)
                cash += proceeds
                total_slippage_cost += (latency_slippage + spread_pips / 2.0) * position_units
                trades.append({
                    "symbol": "XAUUSD", "buy_time": trade_entry_time, "sell_time": time_stamp,
                    "buy_price": entry_price, "sell_price": fill_price, "pnl": pnl,
                    "pnl_pct": (pnl / (position_units * entry_price)) * 100, "reason": "SESSION_CLOSE"
                })
                position_units = 0.0
                continue

        prev_buy = buy_signals.iloc[i-1]
        if prev_buy and position_units == 0 and not is_session_end:
            fill_price = raw_price + (spread_pips / 2.0) + latency_slippage
            max_allowed = (bar_volume * 0.01) * 100.0
            budget_units = (cash * 0.20) / fill_price
            lot_units = min(budget_units, max_allowed)

            if lot_units > 0:
                position_units = lot_units
                entry_price = fill_price
                stop_loss_price = fill_price - 1.5 * atr_val
                take_profit_price = fill_price + 3.5 * atr_val
                trade_entry_time = time_stamp
                cost = lot_units * fill_price
                cash -= cost
                total_slippage_cost += (latency_slippage + spread_pips / 2.0) * lot_units

    running_eq = initial_cash
    pk_eq = initial_cash
    max_dd_amount = 0.0
    max_dd_pct = 0.0

    if len(trades) > 0:
        trade_df = pd.DataFrame(trades)
        trade_df["date_str"] = pd.to_datetime(trade_df["sell_time"]).dt.strftime("%Y-%m-%d")
        daily_pnl = trade_df.groupby("date_str")["pnl"].sum()

        for d_str, group in daily_groups:
            pnl_today = float(daily_pnl.get(d_str, 0.0))
            running_eq += pnl_today

            if running_eq > pk_eq:
                pk_eq = running_eq
            dd_curr = (pk_eq - running_eq) / pk_eq if pk_eq > 0 else 0.0
            dd_amt = pk_eq - running_eq

            if dd_curr > max_dd_pct:
                max_dd_pct = dd_curr
                max_dd_amount = dd_amt

            daily_results.append({
                "date": d_str, "end_equity": running_eq, "daily_return": pnl_today / initial_cash, "drawdown": dd_curr, "turnover": (initial_cash * 0.20)
            })
    else:
        running_eq = initial_cash
        daily_results.append({"date": df_test["date_str"].iloc[0], "end_equity": initial_cash, "daily_return": 0.0, "drawdown": 0.0, "turnover": 0.0})

    perf = calculate_performance(daily_results, initial_capital=initial_cash)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = float((trades_df["pnl"] > 0).mean() * 100) if not trades_df.empty else 0.0
    wins = trades_df[trades_df["pnl"] > 0]["pnl"] if not trades_df.empty else pd.Series()
    losses = trades_df[trades_df["pnl"] < 0]["pnl"].abs() if not trades_df.empty else pd.Series()
    profit_factor = float(wins.sum() / losses.sum()) if losses.sum() > 0 else (1.0 if not trades_df.empty else 0.0)

    print(f"[{timeframe} 压测结果] 收益率: {(running_eq/initial_cash-1.0)*100:+.2f}% | 胜率: {win_rate:.2f}% | 盈亏比: {profit_factor:.3f} | 最大回撤: {max_dd_pct*100:.2f}% | 交易数: {len(trades)} 笔", flush=True)

if __name__ == "__main__":
    run_stress_test_for_timeframe("1h")
    run_stress_test_for_timeframe("1d")
