"""
Test script for precise Asymmetric PnL Ratio Optimization on Top-4 Long / Top-4 Short Baseline
"""
import pandas as pd
import numpy as np
import sqlite3
from pathlib import Path
import sys

CODE_DIR = Path("/Users/tang/PycharmProjects/pythonProject/lianghua/code")
sys.path.insert(0, str(CODE_DIR))

import qlib_model_adapter
from run_qlib_futures_15m_research import FUTURES_SPECS, load_and_resample_15m_futures, extract_pure_ohlcv_features_15m
from backtest_metrics import calculate_performance
from strategy_evaluator_agent import StrategyEvaluatorAgent

db_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"
df_15m = load_and_resample_15m_futures(db_path)
feature_df = extract_pure_ohlcv_features_15m(df_15m)

feature_cols = [
    "kaufman_efficiency_20", "vol_squeeze_ratio_20", "momentum_acceleration_5_20",
    "breakout_channel_pos_20", "garman_klass_vol_10", "intraday_intensity_10",
    "amihud_illiquidity_20", "ret_3", "ret_5",
]
clean_df = feature_df.dropna(subset=feature_cols + ["label"]).copy()

unique_times = sorted(clean_df["trade_time"].unique())
split_idx = int(len(unique_times) * 0.60)
train_df = clean_df[clean_df["trade_time"].isin(unique_times[:split_idx])].copy()
test_df = clean_df[clean_df["trade_time"].isin(unique_times[split_idx:])].copy()

# Fit Qlib LGBModel
raw_scores, _ = qlib_model_adapter.fit_qlib_lightgbm(
    x_train=train_df[feature_cols],
    y_train=(train_df["label"] > 0.0).astype(int),
    sample_weight=np.ones(len(train_df)),
    x_evaluation=test_df[feature_cols],
    seed=42,
)
test_df["ml_score"] = raw_scores

def _calc_futures_score(g):
    ker = g["kaufman_efficiency_20"].rank(pct=True)
    sq = g["vol_squeeze_ratio_20"].rank(pct=True)
    mom = g["momentum_acceleration_5_20"].rank(pct=True)
    ch = g["breakout_channel_pos_20"].rank(pct=True)
    ml = g["ml_score"].rank(pct=True)
    g["score"] = 2.0 * ker + 1.5 * sq + 1.2 * mom + 1.0 * ch + 1.8 * ml
    return g

test_eval_df = test_df.groupby("trade_time", group_keys=False).apply(_calc_futures_score)

# Run Backtest with Asymmetric Stop / Run Logic
top_k = 4
rebalance_bars = 8
initial_cash = 2_000_000.0

times = sorted(test_eval_df["trade_time"].unique())
prices = test_eval_df.pivot(index="trade_time", columns="symbol", values="close")
scores = test_eval_df.pivot(index="trade_time", columns="symbol", values="score")

cash = initial_cash
long_positions = {}
short_positions = {}
daily_records = []
trade_logs = []
prev_day_str = None
peak_equity = initial_cash

for i, t in enumerate(times):
    current_prices = prices.loc[t].dropna()
    current_scores = scores.loc[t].dropna() if t in scores.index else pd.Series(dtype=float)
    trading_cost = 0.0
    turnover = 0.0
    day_str = pd.Timestamp(t).strftime("%Y-%m-%d")

    # 1. Asymmetric Stop Loss & Profit Runner
    # Long positions
    for sym in list(long_positions.keys()):
        pos = long_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        pos["peak_price"] = max(pos.get("peak_price", p), p)
        entry_p = pos["entry_price"]
        peak_p = pos["peak_price"]

        # Cut loss fast at -0.9%, Trail profit when peak >= +1.6%
        hard_stop = entry_p * 0.991
        trailing_stop = peak_p * 0.992 if peak_p >= entry_p * 1.016 else 0.0

        if p <= hard_stop or (trailing_stop > 0 and p <= trailing_stop):
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
            mult = spec["multiplier"]
            pnl = pos["lots"] * mult * (p - entry_p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            tag = "TRAIL_PROFIT_LONG" if trailing_stop > 0 else "HARD_STOP_LONG"
            trade_logs.append({"time": t, "symbol": sym, "side": tag, "pnl": pnl, "cost": cost})
            del long_positions[sym]

    # Short positions
    for sym in list(short_positions.keys()):
        pos = short_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        pos["trough_price"] = min(pos.get("trough_price", p), p)
        entry_p = pos["entry_price"]
        trough_p = pos["trough_price"]

        # Cut loss fast at +0.9%, Trail profit when trough <= -1.6%
        hard_stop = entry_p * 1.009
        trailing_stop = trough_p * 1.008 if trough_p <= entry_p * 0.984 else 999999.0

        if p >= hard_stop or (trailing_stop < 999999.0 and p >= trailing_stop):
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
            mult = spec["multiplier"]
            pnl = pos["lots"] * mult * (entry_p - p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            tag = "TRAIL_PROFIT_SHORT" if trailing_stop < 999999.0 else "HARD_STOP_SHORT"
            trade_logs.append({"time": t, "symbol": sym, "side": tag, "pnl": pnl, "cost": cost})
            del short_positions[sym]

    # 2. Rebalance (Every 8 bars)
    is_rebalance_bar = (i % rebalance_bars == 0)
    if is_rebalance_bar and len(current_scores) >= (top_k * 2) * 2:
        long_targets = current_scores.nlargest(top_k).index.tolist()
        short_targets = current_scores.nsmallest(top_k).index.tolist()

        # Close non-targets UNLESS they are in profit (let winners run!)
        for sym in list(long_positions.keys()):
            if sym not in long_targets:
                p = current_prices.get(sym, 0.0)
                pos = long_positions[sym]
                is_winning = (p > pos["entry_price"] * 1.005)
                # If winning, keep holding until trailing stop triggers; otherwise close
                if not is_winning:
                    pos = long_positions.pop(sym)
                    spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
                    mult = spec["multiplier"]
                    pnl = pos["lots"] * mult * (p - pos["entry_price"])
                    notional = pos["lots"] * mult * p
                    cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
                    cash += (pos["margin_locked"] + pnl - cost)
                    trading_cost += cost
                    turnover += notional
                    trade_logs.append({"time": t, "symbol": sym, "side": "CLOSE_LONG", "pnl": pnl, "cost": cost})

        for sym in list(short_positions.keys()):
            if sym not in short_targets:
                p = current_prices.get(sym, 0.0)
                pos = short_positions[sym]
                is_winning = (p < pos["entry_price"] * 0.995)
                if not is_winning:
                    pos = short_positions.pop(sym)
                    spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
                    mult = spec["multiplier"]
                    pnl = pos["lots"] * mult * (pos["entry_price"] - p)
                    notional = pos["lots"] * mult * p
                    cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
                    cash += (pos["margin_locked"] + pnl - cost)
                    trading_cost += cost
                    turnover += notional
                    trade_logs.append({"time": t, "symbol": sym, "side": "CLOSE_SHORT", "pnl": pnl, "cost": cost})

        # Calculate capital
        long_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (current_prices.get(s, 0.0) - pos["entry_price"]) for s, pos in long_positions.items())
        short_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (pos["entry_price"] - current_prices.get(s, 0.0)) for s, pos in short_positions.items())
        total_margin = sum(pos["margin_locked"] for pos in list(long_positions.values()) + list(short_positions.values()))
        total_equity = cash + total_margin + long_floating + short_floating

        alloc_margin_per_pos = (total_equity * 0.35) / max(1, top_k)

        for sym in long_targets:
            if sym in long_positions or len(long_positions) >= top_k:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            lots = int(alloc_margin_per_pos / margin_per_lot)
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                long_positions[sym] = {"lots": lots, "entry_price": p, "peak_price": p, "margin_locked": locked}
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_LONG", "lots": lots, "price": p})

        for sym in short_targets:
            if sym in short_positions or len(short_positions) >= top_k:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            lots = int(alloc_margin_per_pos / margin_per_lot)
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                short_positions[sym] = {"lots": lots, "entry_price": p, "trough_price": p, "margin_locked": locked}
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_SHORT", "lots": lots, "price": p})

    # Accounting
    long_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (current_prices.get(s, 0.0) - pos["entry_price"]) for s, pos in long_positions.items())
    short_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (pos["entry_price"] - current_prices.get(s, 0.0)) for s, pos in short_positions.items())
    total_margin = sum(pos["margin_locked"] for pos in list(long_positions.values()) + list(short_positions.values()))
    equity = cash + total_margin + long_floating + short_floating
    peak_equity = max(peak_equity, equity)
    drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

    if prev_day_str != day_str:
        if prev_day_str is not None:
            prev_eq = daily_records[-1]["end_equity"] if daily_records else initial_cash
            daily_records.append({
                "date": prev_day_str,
                "start_equity": prev_eq,
                "end_equity": equity,
                "cash": cash,
                "margin": total_margin,
                "daily_return": (equity - prev_eq) / prev_eq,
                "drawdown": drawdown,
                "turnover": turnover,
                "trading_cost": trading_cost,
            })
        prev_day_str = day_str

if prev_day_str is not None:
    prev_eq = daily_records[-1]["end_equity"] if daily_records else initial_cash
    daily_records.append({
        "date": prev_day_str,
        "start_equity": prev_eq,
        "end_equity": equity,
        "cash": cash,
        "margin": total_margin,
        "daily_return": (equity - prev_eq) / prev_eq,
        "drawdown": drawdown,
        "turnover": turnover,
        "trading_cost": trading_cost,
    })

perf = calculate_performance(daily_records, initial_cash)
closed_trades = [t for t in trade_logs if "pnl" in t]
wins = [t["pnl"] for t in closed_trades if t["pnl"] > 0]
losses = [abs(t["pnl"]) for t in closed_trades if t["pnl"] < 0]
win_rate = len(wins) / max(1, len(closed_trades)) * 100.0
avg_win = np.mean(wins) if wins else 0.0
avg_loss = np.mean(losses) if losses else 1.0
pl_ratio = avg_win / max(1e-5, avg_loss)

print("=" * 60)
print(f"Total Trades:       {len(closed_trades)}")
print(f"Win Rate:           {win_rate:.2f} %")
print(f"Avg Win:            {avg_win:,.2f} CNY")
print(f"Avg Loss:           {avg_loss:,.2f} CNY")
print(f"PROFIT / LOSS RATIO:{pl_ratio:.2f}")
print(f"Total Return:       {((equity - initial_cash)/initial_cash*100):.2f} %")
print(f"Sharpe Ratio:       {perf.get('sharpe_ratio', 0.0):.2f}")
print(f"Max Drawdown:       {perf.get('max_drawdown_pct', 0.0):.2f} %")
print("=" * 60)
