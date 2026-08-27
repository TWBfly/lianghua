"""归元·极值 15m 真实历史 / 合成大样本双轨审计。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


TRADE_COLUMNS = [
    "entry_time",
    "exit_time",
    "side",
    "lots",
    "entry_price",
    "exit_price",
    "entry_fee",
    "exit_fee",
    "slippage_cost",
    "gross_pnl",
    "net_pnl",
    "exit_reason",
    "holding_bars",
]


def lln_gate(trades: int) -> bool:
    return trades > 1_000


def summarize_portfolio(rows: pd.DataFrame, track: str) -> dict[str, Any]:
    selected = rows.loc[rows["track"].eq(track)]
    return {
        "track": track,
        "net_pnl": float(selected["net_pnl"].sum()),
        "trade_count": int(selected["trade_count"].sum()),
    }


def simulate_guiyuan(
    df: pd.DataFrame,
    signals: pd.Series,
    spec: dict[str, float],
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 2.5,
    breakeven_atr_mult: float = 2.0,
    trail_atr_mult: float = 5.0,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    """以 t 收盘信号在 t+1 开盘成交，并完整记录期货双边成本。"""
    required = {"open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("bars must have a sorted, unique index")

    bars = df.astype({column: float for column in required})
    sig = signals.reindex(bars.index).fillna(0).astype(int).to_numpy()
    open_ = bars["open"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    times = bars.index

    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - previous_close).abs(),
            (bars["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean().to_numpy()
    sma5 = bars["close"].rolling(5, min_periods=5).mean().to_numpy()

    multiplier = float(spec["multiplier"])
    tick = float(spec["tick"])
    fee_rate = float(spec["fee_rate"]) * cost_multiplier
    slip = tick * cost_multiplier
    cash = float(initial_capital)
    position = 0
    lots = 0
    entry_index = 0
    entry_price = entry_fee = entry_atr = stop_price = 0.0
    favorable_extreme = 0.0
    trades: list[dict[str, Any]] = []
    equity = [cash]

    def close_position(index: int, raw_price: float, reason: str) -> None:
        nonlocal cash, position, lots
        exit_price = raw_price - slip if position > 0 else raw_price + slip
        exit_fee = exit_price * multiplier * lots * fee_rate
        gross_pnl = (exit_price - entry_price) * multiplier * lots * position
        net_pnl = gross_pnl - entry_fee - exit_fee
        cash += gross_pnl - exit_fee
        trades.append(
            {
                "entry_time": times[entry_index],
                "exit_time": times[index],
                "side": "LONG" if position > 0 else "SHORT",
                "lots": lots,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "slippage_cost": 2.0 * slip * multiplier * lots,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "exit_reason": reason,
                "holding_bars": index - entry_index,
            }
        )
        position = 0
        lots = 0

    for i in range(1, len(bars)):
        signal = int(sig[i - 1])

        if position and signal == -position:
            close_position(i, open_[i], "reverse_signal")

        if position == 0 and signal and np.isfinite(atr[i - 1]):
            entry_atr = max(float(atr[i - 1]), 2.0 * tick)
            unit_risk = max(tick * multiplier, stop_atr_mult * entry_atr * multiplier)
            lots = max(1, min(50, int(initial_capital * 0.005 / unit_risk)))
            position = signal
            entry_index = i
            entry_price = open_[i] + slip * position
            entry_fee = entry_price * multiplier * lots * fee_rate
            cash -= entry_fee
            stop_price = entry_price - position * stop_atr_mult * entry_atr
            favorable_extreme = entry_price

        if position > 0 and low[i] <= stop_price:
            close_position(i, min(open_[i], stop_price), "stop")
        elif position < 0 and high[i] >= stop_price:
            close_position(i, max(open_[i], stop_price), "stop")

        if position > 0:
            favorable_extreme = max(favorable_extreme, high[i])
            if favorable_extreme - entry_price >= breakeven_atr_mult * entry_atr:
                stop_price = max(stop_price, entry_price)
            if np.isfinite(sma5[i]) and close[i] >= sma5[i]:
                stop_price = max(stop_price, entry_price)
            stop_price = max(stop_price, favorable_extreme - trail_atr_mult * entry_atr)
        elif position < 0:
            favorable_extreme = min(favorable_extreme, low[i])
            if entry_price - favorable_extreme >= breakeven_atr_mult * entry_atr:
                stop_price = min(stop_price, entry_price)
            if np.isfinite(sma5[i]) and close[i] <= sma5[i]:
                stop_price = min(stop_price, entry_price)
            stop_price = min(stop_price, favorable_extreme + trail_atr_mult * entry_atr)

        unrealized = (
            (close[i] - entry_price) * multiplier * lots * position if position else 0.0
        )
        equity.append(cash + unrealized)

    if position:
        close_position(len(bars) - 1, close[-1], "end_of_data")
        equity[-1] = cash

    trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    net_total = float(trades_df["net_pnl"].sum()) if not trades_df.empty else 0.0
    ledger_reconciled = bool(np.isclose(cash, initial_capital + net_total, atol=1e-6))
    return {
        "trades": trades_df,
        "equity": pd.Series(equity, index=times[: len(equity)], dtype=float),
        "final_equity": cash,
        "net_pnl": cash - initial_capital,
        "ledger_reconciled": ledger_reconciled,
    }

