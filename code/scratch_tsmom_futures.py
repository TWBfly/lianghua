"""
Time-Series Structural Momentum (TSMOM) + ML Regime Filter on 15m Futures
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

# Feature extraction
computed_chunks = []
for sym, group in df_15m.groupby("symbol", sort=False):
    g = group.sort_values("trade_time").copy()
    c = g["close"].astype(float)
    h = g["high"].astype(float)
    l = g["low"].astype(float)
    o = g["open"].astype(float)
    v = g["volume"].astype(float)
    prev_c = c.shift(1).replace(0, np.nan)

    # 1. Kaufman Trend Efficiency (20)
    net_change_20 = (c - c.shift(20)).abs()
    path_20 = c.diff().abs().rolling(20).sum().replace(0, np.nan)
    g["ker_20"] = net_change_20 / path_20

    # 2. EMAs
    g["ema_24"] = c.ewm(span=24, adjust=False).mean()
    g["ema_48"] = c.ewm(span=48, adjust=False).mean()
    g["ema_96"] = c.ewm(span=96, adjust=False).mean()

    # 3. Donchian 20-bar & 40-bar
    g["dh_20"] = h.shift(1).rolling(20).max()
    g["dl_20"] = l.shift(1).rolling(20).min()
    g["dh_40"] = h.shift(1).rolling(40).max()
    g["dl_40"] = l.shift(1).rolling(40).min()

    # 4. ATR 14
    tr14 = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    g["atr_14"] = tr14.rolling(14).mean()

    # 5. Volatility Squeeze
    std20 = c.rolling(20).std(ddof=0)
    bb_width = 4.0 * std20 / c.replace(0, np.nan)
    atr20 = (tr14.rolling(20).mean() / c).replace(0, np.nan)
    g["vol_squeeze_20"] = bb_width / atr20

    # 6. Momentum Acceleration
    g["ret_5"] = c.pct_change(5)
    g["ret_20"] = c.pct_change(20)
    g["mom_accel"] = g["ret_5"] - (g["ret_20"] / 4.0)

    # Label: 24-bar forward return (~6h ahead trend)
    g["label"] = (c.shift(-24) / c.shift(-1) - 1.0)
    computed_chunks.append(g)

df_all = pd.concat(computed_chunks, ignore_index=True).sort_values(["trade_time", "symbol"]).reset_index(drop=True)
feature_cols = ["ker_20", "vol_squeeze_20", "mom_accel", "ret_5", "ret_20"]
clean_df = df_all.dropna(subset=feature_cols + ["label", "ema_48", "dh_20", "dl_20", "atr_14"]).copy()

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

# Pivot
times = sorted(test_df["trade_time"].unique())
prices = test_df.pivot(index="trade_time", columns="symbol", values="close")
highs = test_df.pivot(index="trade_time", columns="symbol", values="high")
lows = test_df.pivot(index="trade_time", columns="symbol", values="low")
ema24s = test_df.pivot(index="trade_time", columns="symbol", values="ema_24")
ema48s = test_df.pivot(index="trade_time", columns="symbol", values="ema_48")
dh20s = test_df.pivot(index="trade_time", columns="symbol", values="dh_20")
dl20s = test_df.pivot(index="trade_time", columns="symbol", values="dl_20")
atrs = test_df.pivot(index="trade_time", columns="symbol", values="atr_14")
kers = test_df.pivot(index="trade_time", columns="symbol", values="ker_20")
ml_scores = test_df.pivot(index="trade_time", columns="symbol", values="ml_score")

initial_cash = 2_000_000.0
cash = initial_cash
positions = {}
daily_records = []
trade_logs = []
prev_day_str = None
peak_equity = initial_cash

for i, t in enumerate(times):
    current_p = prices.loc[t].dropna()
    current_dh = dh20s.loc[t].dropna() if t in dh20s.index else pd.Series(dtype=float)
    current_dl = dl20s.loc[t].dropna() if t in dl20s.index else pd.Series(dtype=float)
    current_ema24 = ema24s.loc[t].dropna() if t in ema24s.index else pd.Series(dtype=float)
    current_ema48 = ema48s.loc[t].dropna() if t in ema48s.index else pd.Series(dtype=float)
    current_atrs = atrs.loc[t].dropna() if t in atrs.index else pd.Series(dtype=float)
    current_kers = kers.loc[t].dropna() if t in kers.index else pd.Series(dtype=float)
    current_ml = ml_scores.loc[t].dropna() if t in ml_scores.index else pd.Series(dtype=float)

    trading_cost = 0.0
    turnover = 0.0
    day_str = pd.Timestamp(t).strftime("%Y-%m-%d")

    # 1. Manage Active Positions (Asymmetric Dynamic Trailing Stop & Moving Average Exit)
    for sym in list(positions.keys()):
        pos = positions[sym]
        p = current_p.get(sym, 0.0)
        if p <= 0:
            continue
        spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
        mult = spec["multiplier"]
        side = pos["side"]
        atr_val = current_atrs.get(sym, p * 0.008)

        exit_triggered = False
        pnl = 0.0
        if side == "LONG":
            pos["peak_price"] = max(pos["peak_price"], p)
            peak_p = pos["peak_price"]
            entry_p = pos["entry_price"]
            # Asymmetric Rules:
            # - Hard Stop Loss: Entry - 1.5 * ATR
            # - EMA24 Exit: if Close < EMA24 and profit > +1.0 ATR
            # - Trailing Stop: Peak - 1.2 * ATR when Peak >= Entry + 2.0 * ATR
            hard_stop = entry_p - 1.5 * atr_val
            trailing_stop = peak_p - 1.2 * atr_val if peak_p >= entry_p + 2.0 * atr_val else 0.0
            ema_exit = (p < current_ema24.get(sym, 0.0) and p >= entry_p + 1.0 * atr_val)

            if p <= hard_stop or (trailing_stop > 0 and p <= trailing_stop) or ema_exit:
                exit_triggered = True
                pnl = pos["lots"] * mult * (p - entry_p)
                tag = "TRAIL_PROFIT_LONG" if trailing_stop > 0 else ("EMA_EXIT_LONG" if ema_exit else "HARD_STOP_LONG")

        elif side == "SHORT":
            pos["trough_price"] = min(pos["trough_price"], p)
            trough_p = pos["trough_price"]
            entry_p = pos["entry_price"]
            # Asymmetric Rules for Short:
            hard_stop = entry_p + 1.5 * atr_val
            trailing_stop = trough_p + 1.2 * atr_val if trough_p <= entry_p - 2.0 * atr_val else 999999.0
            ema_exit = (p > current_ema24.get(sym, 999999.0) and p <= entry_p - 1.0 * atr_val)

            if p >= hard_stop or (trailing_stop < 999999.0 and p >= trailing_stop) or ema_exit:
                exit_triggered = True
                pnl = pos["lots"] * mult * (entry_p - p)
                tag = "TRAIL_PROFIT_SHORT" if trailing_stop < 999999.0 else ("EMA_EXIT_SHORT" if ema_exit else "HARD_STOP_SHORT")

        if exit_triggered:
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            trade_logs.append({"time": t, "symbol": sym, "side": tag, "pnl": pnl, "cost": cost})
            del positions[sym]

    # Calculate Current Account Value
    floating_pnl = 0.0
    total_margin = 0.0
    for sym, pos in positions.items():
        p = current_p.get(sym, 0.0)
        if p > 0:
            mult = FUTURES_SPECS.get(sym, {}).get("multiplier", 10.0)
            if pos["side"] == "LONG":
                floating_pnl += pos["lots"] * mult * (p - pos["entry_price"])
            else:
                floating_pnl += pos["lots"] * mult * (pos["entry_price"] - p)
            total_margin += pos["margin_locked"]
    equity = cash + total_margin + floating_pnl
    peak_equity = max(peak_equity, equity)
    drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

    # 2. Check New Trend Entries (Max 6 concurrent positions across 28 commodities)
    if len(positions) < 6 and i % 4 == 0:  # Check hourly
        max_margin_per_pos = equity * 0.05  # 5% margin per position
        risk_per_trade = equity * 0.008     # 0.8% portfolio risk

        for sym in current_p.index:
            if sym in positions or len(positions) >= 6:
                continue
            p = current_p[sym]
            ema24_val = current_ema24.get(sym, 0.0)
            ema48_val = current_ema48.get(sym, 0.0)
            dh_val = current_dh.get(sym, 999999.0)
            dl_val = current_dl.get(sym, -1.0)
            ker_val = current_kers.get(sym, 0.0)
            ml_val = current_ml.get(sym, 0.5)
            atr_val = current_atrs.get(sym, p * 0.008)
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]

            # Long Entry: Strong Upward Trend (Price > EMA24 > EMA48, KER >= 0.35, Breakout > DH20, ML >= 0.50)
            if p > dh_val and p > ema24_val > ema48_val and ker_val >= 0.30 and ml_val >= 0.50:
                risk_stop_dist = 1.5 * atr_val
                lots_risk = int(risk_per_trade / max(1e-4, mult * risk_stop_dist))
                margin_per_lot = p * mult * spec["margin"]
                lots_margin = int(max_margin_per_pos / max(1e-4, margin_per_lot))
                lots = max(1, min(lots_risk, lots_margin))

                if cash >= lots * margin_per_lot:
                    locked = lots * margin_per_lot
                    notional = lots * p * mult
                    cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                    cash -= (locked + cost)
                    positions[sym] = {
                        "side": "LONG",
                        "lots": lots,
                        "entry_price": p,
                        "peak_price": p,
                        "margin_locked": locked,
                    }
                    trading_cost += cost
                    turnover += notional
                    trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_LONG", "lots": lots, "price": p})

            # Short Entry: Strong Downward Trend (Price < DL20 < EMA24 < EMA48, KER >= 0.35, ML <= 0.50)
            elif p < dl_val and p < ema24_val < ema48_val and ker_val >= 0.30 and ml_val <= 0.50:
                risk_stop_dist = 1.5 * atr_val
                lots_risk = int(risk_per_trade / max(1e-4, mult * risk_stop_dist))
                margin_per_lot = p * mult * spec["margin"]
                lots_margin = int(max_margin_per_pos / max(1e-4, margin_per_lot))
                lots = max(1, min(lots_risk, lots_margin))

                if cash >= lots * margin_per_lot:
                    locked = lots * margin_per_lot
                    notional = lots * p * mult
                    cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                    cash -= (locked + cost)
                    positions[sym] = {
                        "side": "SHORT",
                        "lots": lots,
                        "entry_price": p,
                        "trough_price": p,
                        "margin_locked": locked,
                    }
                    trading_cost += cost
                    turnover += notional
                    trade_logs.append({"time": t, "symbol": sym, "side": "OPEN_SHORT", "lots": lots, "price": p})

    # Daily ledger record
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
