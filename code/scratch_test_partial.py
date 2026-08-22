"""
Test script: 2-stage partial profit lock + ATR trailing on 15m active futures
"""
import pandas as pd
import numpy as np
import sqlite3
from pathlib import Path
import sys

CODE_DIR = Path("/Users/tang/PycharmProjects/pythonProject/lianghua/code")
sys.path.insert(0, str(CODE_DIR))

import qlib_model_adapter
from run_qlib_futures_15m_research import FUTURES_SPECS, load_and_resample_15m_futures
from backtest_metrics import calculate_performance

db_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"
df_15m = load_and_resample_15m_futures(db_path)

# Extract Features
computed_chunks = []
for sym, group in df_15m.groupby("symbol", sort=False):
    g = group.sort_values("trade_time").copy()
    c = g["close"].astype(float)
    h = g["high"].astype(float)
    l = g["low"].astype(float)
    o = g["open"].astype(float)
    v = g["volume"].astype(float)
    prev_c = c.shift(1).replace(0, np.nan)

    # 1. Kaufman Trend Efficiency Ratio (20 bars)
    net_change_20 = (c - c.shift(20)).abs()
    path_20 = c.diff().abs().rolling(20).sum().replace(0, np.nan)
    g["ker_20"] = net_change_20 / path_20

    # 2. Volatility Squeeze Ratio
    std20 = c.rolling(20).std(ddof=0)
    bb_width = 4.0 * std20 / c.replace(0, np.nan)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    g["atr_14"] = tr.rolling(14).mean()
    atr20 = (tr.rolling(20).mean() / c).replace(0, np.nan)
    g["vol_squeeze_ratio_20"] = bb_width / atr20

    # 3. Momentum Acceleration
    g["ret_3"] = c.pct_change(3)
    g["ret_5"] = c.pct_change(5)
    g["ret_20"] = c.pct_change(20)
    g["momentum_acceleration_5_20"] = g["ret_5"] - (g["ret_20"] / 4.0)

    # 4. Donchian Breakout Channel Position
    max20 = h.rolling(20).max()
    min20 = l.rolling(20).min()
    span20 = (max20 - min20).replace(0, np.nan)
    g["breakout_channel_pos_20"] = (c - min20) / span20

    # 5. Garman-Klass Volatility
    hl = (h / l.replace(0, np.nan)).apply(np.log)
    co = (c / o.replace(0, np.nan)).apply(np.log)
    gk = 0.5 * (hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (co ** 2)
    g["garman_klass_vol_10"] = np.sqrt(gk.clip(lower=0).rolling(10).mean())

    # 6. Amihud Illiquidity
    g["amihud_illiquidity_20"] = (c.pct_change(1).abs() / v.replace(0, np.nan) * 1e6).rolling(20).mean()

    # Target Label: 16-bar forward return (4h ahead swing)
    g["label"] = (c.shift(-16) / c.shift(-1) - 1.0)
    computed_chunks.append(g)

df_all = pd.concat(computed_chunks, ignore_index=True).sort_values(["trade_time", "symbol"]).reset_index(drop=True)
feature_cols = [
    "ker_20", "vol_squeeze_ratio_20", "momentum_acceleration_5_20",
    "breakout_channel_pos_20", "garman_klass_vol_10", "amihud_illiquidity_20",
    "ret_3", "ret_5", "ret_20",
]
clean_df = df_all.dropna(subset=feature_cols + ["label", "atr_14"]).copy()

# Time Split
unique_times = sorted(clean_df["trade_time"].unique())
split_idx = int(len(unique_times) * 0.60)
train_df = clean_df[clean_df["trade_time"].isin(unique_times[:split_idx])].copy()
test_df = clean_df[clean_df["trade_time"].isin(unique_times[split_idx:])].copy()

# Train LightGBM
raw_scores, _ = qlib_model_adapter.fit_qlib_lightgbm(
    x_train=train_df[feature_cols],
    y_train=(train_df["label"] > 0.0).astype(int),
    sample_weight=np.ones(len(train_df)),
    x_evaluation=test_df[feature_cols],
    seed=42,
)
test_df["ml_score"] = raw_scores

def _calc_futures_composite(g):
    ker = g["ker_20"].rank(pct=True)
    ch = g["breakout_channel_pos_20"].rank(pct=True)
    sq = g["vol_squeeze_ratio_20"].rank(pct=True)
    mom = g["ret_20"].rank(pct=True)
    ml = g["ml_score"].rank(pct=True)
    g["score"] = 2.0 * ker + 1.5 * ch + 1.2 * sq + 1.5 * mom + 1.8 * ml
    return g

test_eval_df = test_df.groupby("trade_time", group_keys=False).apply(_calc_futures_composite)

# Portfolio Parameters
top_k = 3
rebalance_bars = 16  # every 4 hours (16 * 15m)
initial_cash = 2_000_000.0

times = sorted(test_eval_df["trade_time"].unique())
prices = test_eval_df.pivot(index="trade_time", columns="symbol", values="close")
scores = test_eval_df.pivot(index="trade_time", columns="symbol", values="score")
atrs = test_eval_df.pivot(index="trade_time", columns="symbol", values="atr_14")

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
    current_atrs = atrs.loc[t].dropna() if t in atrs.index else pd.Series(dtype=float)
    trading_cost = 0.0
    turnover = 0.0
    day_str = pd.Timestamp(t).strftime("%Y-%m-%d")

    # 1. Check Trailing Stops & Profit Taking on Active Positions
    # Long positions check
    for sym in list(long_positions.keys()):
        pos = long_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        pos["peak_price"] = max(pos["peak_price"], p)
        entry_p = pos["entry_price"]
        peak_p = pos["peak_price"]
        atr_val = current_atrs.get(sym, p * 0.008)

        # Dynamic Stop Rules:
        # Hard Stop = Entry - 1.2 * ATR
        # If profit >= +2.0 * ATR: Trail Stop at Peak - 1.0 * ATR
        hard_stop = entry_p - 1.2 * atr_val
        trailing_stop = peak_p - 1.0 * atr_val if peak_p >= entry_p + 2.0 * atr_val else 0.0
        effective_stop = max(hard_stop, trailing_stop)

        if p <= effective_stop:
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

    # Short positions check
    for sym in list(short_positions.keys()):
        pos = short_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        pos["trough_price"] = min(pos["trough_price"], p)
        entry_p = pos["entry_price"]
        trough_p = pos["trough_price"]
        atr_val = current_atrs.get(sym, p * 0.008)

        # Dynamic Stop Rules for Short:
        # Hard Stop = Entry + 1.2 * ATR
        # If profit >= +2.0 * ATR: Trail Stop at Trough + 1.0 * ATR
        hard_stop = entry_p + 1.2 * atr_val
        trailing_stop = trough_p + 1.0 * atr_val if trough_p <= entry_p - 2.0 * atr_val else 999999.0
        effective_stop = min(hard_stop, trailing_stop)

        if p >= effective_stop:
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

    # Calculate Current Account Value
    long_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (current_prices.get(s, 0.0) - pos["entry_price"]) for s, pos in long_positions.items())
    short_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (pos["entry_price"] - current_prices.get(s, 0.0)) for s, pos in short_positions.items())
    total_margin = sum(pos["margin_locked"] for pos in list(long_positions.values()) + list(short_positions.values()))
    equity = cash + total_margin + long_floating + short_floating
    peak_equity = max(peak_equity, equity)
    drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

    # 2. Rebalance Entry Every 16 Bars
    is_rebalance_bar = (i % rebalance_bars == 0)
    if is_rebalance_bar and len(current_scores) >= (top_k * 2 + 4):
        long_targets = current_scores.nlargest(top_k).index.tolist()
        short_targets = current_scores.nsmallest(top_k).index.tolist()

        # Fixed Capital Allocation: 5% of account margin per position (Total 30% margin)
        alloc_margin_per_pos = equity * 0.05

        for sym in long_targets:
            if len(long_positions) >= top_k:
                break
            if sym in long_positions:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            margin_per_lot = p * mult * spec["margin"]
            lots = int(alloc_margin_per_pos / max(1e-4, margin_per_lot))
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * p * mult
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                long_positions[sym] = {"lots": lots, "entry_price": p, "peak_price": p, "margin_locked": locked}
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_LONG", "lots": lots, "price": p})

        for sym in short_targets:
            if len(short_positions) >= top_k:
                break
            if sym in short_positions:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            margin_per_lot = p * mult * spec["margin"]
            lots = int(alloc_margin_per_pos / max(1e-4, margin_per_lot))
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * p * mult
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                short_positions[sym] = {"lots": lots, "entry_price": p, "trough_price": p, "margin_locked": locked}
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_SHORT", "lots": lots, "price": p})

    # Daily mark to market
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
