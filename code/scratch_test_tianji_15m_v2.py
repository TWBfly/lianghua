"""
TianJi-Futures-15M-CSM V2 Test Bench:
1. ATR Volatility-Parity Position Sizing (Risk Equalization)
2. Adaptive Dynamic ATR Stop Loss & Trailing Ratchet Lock (1.5x ATR Stop, 2.0x ATR Trailing Lock)
3. Sector Diversification Guard (Max 2 positions per sector in Long/Short)
4. Qlib LightGBM Cross-Sectional Ranking Matrix
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

SECTOR_MAP = {
    "AG_IDX": "PRECIOUS", "AU_IDX": "PRECIOUS",
    "CU_IDX": "BASE_METALS", "AL_IDX": "BASE_METALS", "ZN_IDX": "BASE_METALS", "SN_IDX": "BASE_METALS", "LC_IDX": "BASE_METALS", "SI_IDX": "BASE_METALS",
    "RB_IDX": "FERROUS", "HC_IDX": "FERROUS", "I_IDX": "FERROUS", "JM_IDX": "FERROUS", "J_IDX": "FERROUS", "FG_IDX": "FERROUS",
    "MA_IDX": "CHEMICALS", "TA_IDX": "CHEMICALS", "SA_IDX": "CHEMICALS", "RU_IDX": "CHEMICALS", "SC_IDX": "CHEMICALS",
    "M_IDX": "AGRI", "Y_IDX": "AGRI", "P_IDX": "AGRI", "C_IDX": "AGRI", "CF_IDX": "AGRI", "SR_IDX": "AGRI",
    "IF_IDX": "FINANCIAL", "IC_IDX": "FINANCIAL", "IM_IDX": "FINANCIAL",
}

db_path = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"
df_15m = load_and_resample_15m_futures(db_path)
feature_df = extract_pure_ohlcv_features_15m(df_15m)

# Compute 15m ATR for adaptive volatility parity and stop loss
def _add_atr(group):
    c = group["close"].astype(float)
    h = group["high"].astype(float)
    l = group["low"].astype(float)
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    group["atr_20"] = tr.rolling(20).mean()
    group["atr_pct_20"] = group["atr_20"] / c.replace(0, np.nan)
    return group

feature_df = feature_df.groupby("symbol", group_keys=False).apply(_add_atr)

feature_cols = [
    "kaufman_efficiency_20", "vol_squeeze_ratio_20", "momentum_acceleration_5_20",
    "breakout_channel_pos_20", "garman_klass_vol_10", "intraday_intensity_10",
    "amihud_illiquidity_20", "ret_3", "ret_5",
]
clean_df = feature_df.dropna(subset=feature_cols + ["label", "atr_20"]).copy()

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

top_k = 4
rebalance_bars = 16  # 4 hours
initial_cash = 2_000_000.0

times = sorted(test_eval_df["trade_time"].unique())
prices = test_eval_df.pivot(index="trade_time", columns="symbol", values="close")
scores = test_eval_df.pivot(index="trade_time", columns="symbol", values="score")
atrs = test_eval_df.pivot(index="trade_time", columns="symbol", values="atr_20")

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

    # 1. Dynamic ATR Asymmetric Risk Guard & Trailing Ratchet Lock
    # Check Longs
    for sym in list(long_positions.keys()):
        pos = long_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        entry_p = pos["entry_price"]
        spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
        mult = spec["multiplier"]
        pos_atr = pos.get("entry_atr", current_atrs.get(sym, p * 0.01))
        
        # Track Peak Price for Trailing Lock
        pos["peak_price"] = max(pos.get("peak_price", entry_p), p)
        peak_p = pos["peak_price"]
        
        # Trigger Conditions:
        # A. Hard Stop at entry - 1.5 * ATR
        is_hard_stop = (p <= entry_p - 1.5 * pos_atr)
        # B. Trailing Ratchet Lock: if peak >= entry + 2.0 * ATR and drops by 0.8 * ATR from peak
        is_trailing_lock = (peak_p >= entry_p + 2.0 * pos_atr and p <= peak_p - 0.8 * pos_atr)

        if is_hard_stop or is_trailing_lock:
            pnl = pos["lots"] * mult * (p - entry_p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            reason = "TRAILING_LOCK_LONG" if is_trailing_lock else "ATR_STOP_LONG"
            trade_logs.append({"time": t, "symbol": sym, "side": reason, "pnl": pnl, "cost": cost})
            del long_positions[sym]

    # Check Shorts
    for sym in list(short_positions.keys()):
        pos = short_positions[sym]
        p = current_prices.get(sym, 0.0)
        if p <= 0:
            continue
        entry_p = pos["entry_price"]
        spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
        mult = spec["multiplier"]
        pos_atr = pos.get("entry_atr", current_atrs.get(sym, p * 0.01))

        # Track Lowest Price for Trailing Lock
        pos["trough_price"] = min(pos.get("trough_price", entry_p), p)
        trough_p = pos["trough_price"]

        # Trigger Conditions:
        # A. Hard Stop at entry + 1.5 * ATR
        is_hard_stop = (p >= entry_p + 1.5 * pos_atr)
        # B. Trailing Ratchet Lock: if trough <= entry - 2.0 * ATR and rises by 0.8 * ATR from trough
        is_trailing_lock = (trough_p <= entry_p - 2.0 * pos_atr and p >= trough_p + 0.8 * pos_atr)

        if is_hard_stop or is_trailing_lock:
            pnl = pos["lots"] * mult * (entry_p - p)
            notional = pos["lots"] * mult * p
            cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
            cash += (pos["margin_locked"] + pnl - cost)
            trading_cost += cost
            turnover += notional
            reason = "TRAILING_LOCK_SHORT" if is_trailing_lock else "ATR_STOP_SHORT"
            trade_logs.append({"time": t, "symbol": sym, "side": reason, "pnl": pnl, "cost": cost})
            del short_positions[sym]

    # 2. Rebalance with Sector Diversification Guard (Max 2 per Sector)
    is_rebalance_bar = (i % rebalance_bars == 0)
    if is_rebalance_bar and len(current_scores) >= (top_k * 2) * 2:
        # Sector Diversified Selection for Longs
        long_candidates = current_scores.sort_values(ascending=False).index.tolist()
        long_targets = []
        long_sector_counts = {}
        for s in long_candidates:
            sec = SECTOR_MAP.get(s, "OTHER")
            if long_sector_counts.get(sec, 0) < 2:
                long_targets.append(s)
                long_sector_counts[sec] = long_sector_counts.get(sec, 0) + 1
                if len(long_targets) >= top_k:
                    break

        # Sector Diversified Selection for Shorts
        short_candidates = current_scores.sort_values(ascending=True).index.tolist()
        short_targets = []
        short_sector_counts = {}
        for s in short_candidates:
            sec = SECTOR_MAP.get(s, "OTHER")
            if short_sector_counts.get(sec, 0) < 2:
                short_targets.append(s)
                short_sector_counts[sec] = short_sector_counts.get(sec, 0) + 1
                if len(short_targets) >= top_k:
                    break

        # Close non-targets
        for sym in list(long_positions.keys()):
            if sym not in long_targets:
                pos = long_positions.pop(sym)
                p = current_prices.get(sym, 0.0)
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
                pos = short_positions.pop(sym)
                p = current_prices.get(sym, 0.0)
                spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0})
                mult = spec["multiplier"]
                pnl = pos["lots"] * mult * (pos["entry_price"] - p)
                notional = pos["lots"] * mult * p
                cost = notional * spec["fee_rate"] + pos["lots"] * mult * spec["tick"]
                cash += (pos["margin_locked"] + pnl - cost)
                trading_cost += cost
                turnover += notional
                trade_logs.append({"time": t, "symbol": sym, "side": "CLOSE_SHORT", "pnl": pnl, "cost": cost})

        # Calculate Capital
        long_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (current_prices.get(s, 0.0) - pos["entry_price"]) for s, pos in long_positions.items())
        short_floating = sum(pos["lots"] * FUTURES_SPECS.get(s, {}).get("multiplier", 10.0) * (pos["entry_price"] - current_prices.get(s, 0.0)) for s, pos in short_positions.items())
        total_margin = sum(pos["margin_locked"] for pos in list(long_positions.values()) + list(short_positions.values()))
        total_equity = cash + total_margin + long_floating + short_floating

        # 3. ATR Volatility Parity Weighting: Target Dollar Risk per position
        # Target Risk = 1.25% of Total Equity per position
        target_risk_per_pos = total_equity * 0.0125
        
        # Open Longs
        for sym in long_targets:
            if sym in long_positions:
                continue
            p = current_prices.get(sym, 0.0)
            if p <= 0:
                continue
            spec = FUTURES_SPECS.get(sym, {"multiplier": 10.0, "fee_rate": 0.00005, "tick": 1.0, "margin": 0.10})
            mult = spec["multiplier"]
            sym_atr = current_atrs.get(sym, p * 0.01)
            atr_dollar_per_lot = 1.5 * sym_atr * mult
            lots = int(target_risk_per_pos / max(1.0, atr_dollar_per_lot))
            lots = max(1, min(lots, int((total_equity * 0.15) / (p * mult))))  # cap at 15% notional

            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                long_positions[sym] = {"lots": lots, "entry_price": p, "entry_atr": sym_atr, "margin_locked": locked}
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
            sym_atr = current_atrs.get(sym, p * 0.01)
            atr_dollar_per_lot = 1.5 * sym_atr * mult
            lots = int(target_risk_per_pos / max(1.0, atr_dollar_per_lot))
            lots = max(1, min(lots, int((total_equity * 0.15) / (p * mult))))

            notional_per_lot = p * mult
            margin_per_lot = notional_per_lot * spec["margin"]
            if lots >= 1 and cash >= lots * margin_per_lot:
                locked = lots * margin_per_lot
                notional = lots * notional_per_lot
                cost = notional * spec["fee_rate"] + lots * mult * spec["tick"]
                cash -= (locked + cost)
                short_positions[sym] = {"lots": lots, "entry_price": p, "entry_atr": sym_atr, "margin_locked": locked}
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

print("=" * 65)
print("     TIANJI FUTURES 15M CSM V2 - ADVANCED ENGINE BENCHMARK")
print("=" * 65)
print(f"Total Trades:       {len(closed_trades)}")
print(f"Win Rate:           {win_rate:.2f} %")
print(f"Avg Win:            {avg_win:,.2f} CNY")
print(f"Avg Loss:           {avg_loss:,.2f} CNY")
print(f"PROFIT / LOSS RATIO:{pl_ratio:.2f}")
print(f"Total Return:       {((equity - initial_cash)/initial_cash*100):.2f} %")
print(f"Sharpe Ratio:       {perf.get('sharpe_ratio', 0.0):.2f}")
print(f"Sortino Ratio:      {perf.get('sortino_ratio', 0.0):.2f}")
print(f"Calmar Ratio:       {perf.get('calmar_ratio', 0.0):.2f}")
print(f"Max Drawdown:       {perf.get('max_drawdown_pct', 0.0):.2f} %")
print("=" * 65)
