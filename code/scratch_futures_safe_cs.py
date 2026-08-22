"""
Safe 0.9x Gross Notional Multi-Commodity Qlib Alpha Spread on 15m Futures
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

def _calc_futures_score(group):
    ker_rank = group["kaufman_efficiency_20"].rank(pct=True)
    sq_rank = group["vol_squeeze_ratio_20"].rank(pct=True)
    mom_acc = group["momentum_acceleration_5_20"].rank(pct=True)
    ch_rank = group["breakout_channel_pos_20"].rank(pct=True)
    ml_rank = group["ml_score"].rank(pct=True)
    group["score"] = 2.0 * ker_rank + 1.5 * sq_rank + 1.2 * mom_acc + 1.0 * ch_rank + 1.8 * ml_rank
    return group

test_eval_df = test_df.groupby("trade_time", group_keys=False).apply(_calc_futures_score)

# Portfolio Simulation (Safe Notional 0.45x Long, 0.45x Short)
top_k = 4
rebalance_bars = 16  # every 4 hours
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

    # 1. Intra-Bar Asymmetric Risk Guard (Cut Losers Early at -1.0%)
    # Check Long positions
    for sym in list(long_positions.keys()):
        pos = long_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        entry_p = pos["entry_price"]
        # Cut losers fast at -1.0%
        if p <= entry_p * 0.990:
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
            mult = spec["multiplier"]
            pnl = pos["lots"] * mult * (p - entry_p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            trade_logs.append({"time": t, "symbol": sym, "side": "STOP_LOSS_LONG", "pnl": pnl, "cost": cost})
            del long_positions[sym]

    # Check Short positions
    for sym in list(short_positions.keys()):
        pos = short_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        entry_p = pos["entry_price"]
        # Cut losers fast at +1.0%
        if p >= entry_p * 1.010:
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
            mult = spec["multiplier"]
            pnl = pos["lots"] * mult * (entry_p - p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            trade_logs.append({"time": t, "symbol": sym, "side": "STOP_LOSS_SHORT", "pnl": pnl, "cost": cost})
            del short_positions[sym]

    # 2. Scheduled Rebalance (Every 16 bars)
    is_rebalance_bar = (i % rebalance_bars == 0)
    if is_rebalance_bar and len(current_scores) >= (top_k * 2) * 2:
        long_targets = current_scores.nlargest(top_k).index.tolist()
        long_buffer = set(current_scores.nlargest(top_k * 2 + 2).index.tolist())
        short_targets = current_scores.nsmallest(top_k).index.tolist()
        short_buffer = set(current_scores.nsmallest(top_k * 2 + 2).index.tolist())

        # Close non-target long positions UNLESS in profit and in buffer (let winners run!)
        for sym in list(long_positions.keys()):
            pos = long_positions[sym]
            p = current_prices.get(sym, 0.0)
            is_winning_runner = (p >= pos["entry_price"] * 1.010 and sym in long_buffer)
            if sym not in long_targets and not is_winning_runner:
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

        # Close non-target short positions UNLESS in profit and in buffer
        for sym in list(short_positions.keys()):
            pos = short_positions[sym]
            p = current_prices.get(sym, 0.0)
            is_winning_runner = (p <= pos["entry_price"] * 0.990 and sym in short_buffer)
            if sym not in short_targets and not is_winning_runner:
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

        # Mark total equity & compute allocatable notional per leg
        long_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (current_prices.get(s, 0.0) - pos["entry_price"]) for s, pos in long_positions.items())
        short_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (pos["entry_price"] - current_prices.get(s, 0.0)) for s, pos in short_positions.items())
        total_margin = sum(pos["margin_locked"] for pos in list(long_positions.values()) + list(short_positions.values()))
        total_equity = cash + total_margin + long_floating + short_floating

        alloc_notional_per_pos = (total_equity * 0.45) / max(1, top_k)

        # Open Longs
        for sym in long_targets:
            if sym in long_positions:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            lots = int(alloc_notional_per_pos / notional_per_lot)
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                long_positions[sym] = {"lots": lots, "entry_price": p, "margin_locked": locked}
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_LONG", "lots": lots, "price": p})

        # Open Shorts
        for sym in short_targets:
            if sym in short_positions:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            lots = int(alloc_notional_per_pos / notional_per_lot)
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                short_positions[sym] = {"lots": lots, "entry_price": p, "margin_locked": locked}
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
print(f"Sortino Ratio:      {perf.get('sortino_ratio', 0.0):.2f}")
print(f"Max Drawdown:       {perf.get('max_drawdown_pct', 0.0):.2f} %")
print("=" * 60)
