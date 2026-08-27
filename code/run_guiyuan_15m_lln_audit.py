"""归元·极值 15m 真实历史 / 合成大样本双轨审计。"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
if str(STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_DIR))

from guiyuan_zscore_reversion import calculate_signal


DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reports" / "guiyuan_15m_lln_20260827"
PARAMETER_GRID = [(stop, trail) for stop in (2.0, 2.5, 3.0, 3.5) for trail in (4.0, 5.0, 6.0, 7.0)]


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


def audit_bars(symbol: str, track: str, df: pd.DataFrame) -> dict[str, Any]:
    required = ["open", "high", "low", "close", "volume", "open_interest"]
    available = [column for column in required if column in df]
    duplicate_timestamps = int(len(df) - df.index.nunique())
    missing_values = int(df[available].isna().sum().sum())
    if {"open", "high", "low", "close"}.issubset(df.columns):
        invalid = (
            df["high"].lt(df[["open", "close", "low"]].max(axis=1))
            | df["low"].gt(df[["open", "close", "high"]].min(axis=1))
        )
        ohlc_errors = int(invalid.sum())
    else:
        ohlc_errors = len(df)
    return {
        "symbol": symbol,
        "track": track,
        "bars": int(len(df)),
        "start": str(df.index.min()) if len(df) else "",
        "end": str(df.index.max()) if len(df) else "",
        "duplicate_timestamps": duplicate_timestamps,
        "missing_values": missing_values,
        "ohlc_errors": ohlc_errors,
    }


def _wilson_interval(wins: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.96
    proportion = wins / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return 100.0 * max(0.0, center - margin), 100.0 * min(1.0, center + margin)


def summarize_simulation(
    symbol: str,
    name: str,
    track: str,
    result: dict[str, Any],
    bars: int,
) -> dict[str, Any]:
    trades = result["trades"]
    count = len(trades)
    wins = int(trades["net_pnl"].gt(0).sum()) if count else 0
    gross_profit = float(trades.loc[trades["net_pnl"].gt(0), "net_pnl"].sum()) if count else 0.0
    gross_loss = float(-trades.loc[trades["net_pnl"].lt(0), "net_pnl"].sum()) if count else 0.0
    ci_low, ci_high = _wilson_interval(wins, count)
    fees = float(trades[["entry_fee", "exit_fee"]].sum().sum()) if count else 0.0
    slippage = float(trades["slippage_cost"].sum()) if count else 0.0

    equity = result["equity"].astype(float)
    peaks = equity.cummax()
    max_drawdown = float(((peaks - equity) / peaks.replace(0.0, np.nan)).max() * 100.0)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) > 1 and returns.std(ddof=0) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=0) * math.sqrt(252.0 * 32.0))
    else:
        sharpe = 0.0
    downside = returns.loc[returns.lt(0)]
    if len(downside) > 1 and downside.std(ddof=0) > 0:
        sortino = float(returns.mean() / downside.std(ddof=0) * math.sqrt(252.0 * 32.0))
    else:
        sortino = 0.0
    initial_capital = float(result["final_equity"] - result["net_pnl"])

    return {
        "symbol": symbol,
        "name": name,
        "track": track,
        "bars": int(bars),
        "trade_count": int(count),
        "win_rate_pct": 100.0 * wins / count if count else 0.0,
        "win_rate_ci95_low": ci_low,
        "win_rate_ci95_high": ci_high,
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0),
        "expectancy": float(trades["net_pnl"].mean()) if count else 0.0,
        "net_pnl": float(result["net_pnl"]),
        "return_pct": 100.0 * float(result["net_pnl"]) / initial_capital,
        "max_drawdown_pct": 0.0 if math.isnan(max_drawdown) else max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_holding_hours": float(trades["holding_bars"].mean() * 0.25) if count else 0.0,
        "fees": fees,
        "slippage": slippage,
        "cost_to_gross_pct": 100.0 * (fees + slippage) / max(1e-12, gross_profit),
        "ledger_reconciled": bool(result["ledger_reconciled"]),
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
    if df.empty:
        return {
            "trades": pd.DataFrame(columns=TRADE_COLUMNS),
            "equity": pd.Series(dtype=float),
            "final_equity": float(initial_capital),
            "net_pnl": 0.0,
            "ledger_reconciled": True,
        }

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


def _contract_specs() -> dict[str, dict[str, Any]]:
    from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

    return ACTIVE_CONTRACT_SPECS


def load_real_bars(symbol: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT trade_time, open, high, low, close, volume, open_interest
            FROM futures_min_bars
            WHERE symbol = ? AND timeframe = '15m'
            ORDER BY trade_time
            """,
            connection,
            params=(symbol,),
        )
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "open_interest"])
    frame["trade_time"] = pd.to_datetime(frame["trade_time"])
    return frame.set_index("trade_time")


def _stable_seed(symbol: str) -> int:
    return 20_260_827 + sum((index + 1) * ord(char) for index, char in enumerate(symbol))


def generate_until_lln(
    symbol: str,
    spec: dict[str, Any],
    target: int = 1_001,
    bars_per_regime: int = 30_000,
    max_batches: int = 4,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import synthetic_market_regime_generator as generator_module
    from synthetic_market_regime_generator import SyntheticMarketRegimeGenerator

    generator = SyntheticMarketRegimeGenerator(seed=_stable_seed(symbol))
    chunks: list[pd.DataFrame] = []
    next_time = pd.Timestamp("2015-01-01 09:00:00")
    start_price = float(spec["base_price"])
    result: dict[str, Any] = {}

    for _ in range(max_batches):
        original_dir = generator_module.SYNTHETIC_DATA_DIR
        with tempfile.TemporaryDirectory(prefix=f"guiyuan_{symbol.lower()}_") as temporary_dir:
            generator_module.SYNTHETIC_DATA_DIR = temporary_dir
            try:
                batch = generator.generate_regime_bars(
                    symbol,
                    start_price=start_price,
                    bars_per_regime=bars_per_regime,
                    tick_size=float(spec["tick"]),
                    timeframe="15m",
                )
            finally:
                generator_module.SYNTHETIC_DATA_DIR = original_dir

        batch = batch.copy()
        batch.index = pd.date_range(next_time, periods=len(batch), freq="15min")
        next_time = batch.index[-1] + pd.Timedelta(minutes=15)
        start_price = float(batch["close"].iloc[-1])
        chunks.append(batch)
        combined = pd.concat(chunks)
        result = simulate_guiyuan(combined, calculate_signal(combined), spec)
        if len(result["trades"]) >= target and lln_gate(len(result["trades"])):
            return combined, result

    count = len(result.get("trades", ()))
    raise RuntimeError(f"{symbol} generated only {count} trades after {max_batches} batches")


def _attach_trade_context(
    trades: pd.DataFrame,
    symbol: str,
    track: str,
    bars: pd.DataFrame,
) -> pd.DataFrame:
    contextual = trades.copy()
    contextual.insert(0, "track", track)
    contextual.insert(0, "symbol", symbol)
    regime_column = "regime" if "regime" in bars else "regime_label" if "regime_label" in bars else None
    if regime_column and not contextual.empty:
        contextual["regime"] = contextual["entry_time"].map(bars[regime_column])
    else:
        contextual["regime"] = "REAL_HISTORY" if track == "real" else "UNKNOWN"
    return contextual


def _robustness_audit(
    bars: pd.DataFrame,
    signals: pd.Series,
    spec: dict[str, Any],
) -> dict[str, Any]:
    split = int(len(bars) * 0.70)
    holdout_bars = bars.iloc[split:].copy()
    holdout_signals = calculate_signal(holdout_bars)
    holdout = simulate_guiyuan(holdout_bars, holdout_signals, spec)
    profitable_parameters = 0
    parameter_rows = []
    for stop, trail in PARAMETER_GRID:
        check = simulate_guiyuan(
            holdout_bars,
            holdout_signals,
            spec,
            stop_atr_mult=stop,
            trail_atr_mult=trail,
        )
        profitable_parameters += check["net_pnl"] > 0
        parameter_rows.append(
            {
                "stop_atr": stop,
                "trail_atr": trail,
                "trades": len(check["trades"]),
                "net_pnl": check["net_pnl"],
            }
        )
    stress = simulate_guiyuan(bars, signals, spec, cost_multiplier=3.0)
    return {
        "holdout_trades": len(holdout["trades"]),
        "holdout_net_pnl": float(holdout["net_pnl"]),
        "parameter_profitable": int(profitable_parameters),
        "parameter_total": len(PARAMETER_GRID),
        "stress_3x_net_pnl": float(stress["net_pnl"]),
        "parameter_rows": parameter_rows,
    }


def classify_symbol(real: dict[str, Any], synthetic: dict[str, Any], robustness: dict[str, Any]) -> str:
    hard_failure = (
        not real["ledger_reconciled"]
        or not synthetic["ledger_reconciled"]
        or real["net_pnl"] <= 0
        or real["profit_factor"] <= 1.0
        or robustness["holdout_net_pnl"] <= 0
        or robustness["stress_3x_net_pnl"] <= 0
        or robustness["parameter_profitable"] < 10
    )
    if hard_failure:
        return "REJECTED"
    if not lln_gate(real["trade_count"]):
        return "INSUFFICIENT_REAL_SAMPLE"
    return "PAPER_ONLY"


def run_symbol(
    symbol: str,
    spec: dict[str, Any],
    target: int,
    bars_per_regime: int,
) -> dict[str, Any]:
    real_bars = load_real_bars(symbol)
    real_quality = audit_bars(symbol, "real", real_bars)
    real_result = simulate_guiyuan(real_bars, calculate_signal(real_bars), spec)
    real_metrics = summarize_simulation(symbol, spec["name"], "real", real_result, len(real_bars))

    synthetic_bars, synthetic_result = generate_until_lln(
        symbol,
        spec,
        target=target,
        bars_per_regime=bars_per_regime,
    )
    synthetic_quality = audit_bars(symbol, "synthetic", synthetic_bars)
    synthetic_signals = calculate_signal(synthetic_bars)
    synthetic_metrics = summarize_simulation(
        symbol,
        spec["name"],
        "synthetic",
        synthetic_result,
        len(synthetic_bars),
    )
    robustness = _robustness_audit(synthetic_bars, synthetic_signals, spec)
    synthetic_metrics.update({key: value for key, value in robustness.items() if key != "parameter_rows"})
    status = classify_symbol(real_metrics, synthetic_metrics, robustness)
    real_metrics["status"] = status
    synthetic_metrics["status"] = status

    synthetic_trades = _attach_trade_context(synthetic_result["trades"], symbol, "synthetic", synthetic_bars)
    real_trades = _attach_trade_context(real_result["trades"], symbol, "real", real_bars)
    regime_metrics = []
    if not synthetic_trades.empty:
        for regime, group in synthetic_trades.groupby("regime", dropna=False):
            regime_metrics.append(
                {
                    "symbol": symbol,
                    "regime": str(regime),
                    "trades": len(group),
                    "win_rate_pct": 100.0 * group["net_pnl"].gt(0).mean(),
                    "net_pnl": float(group["net_pnl"].sum()),
                }
            )

    return {
        "metrics": [real_metrics, synthetic_metrics],
        "trades": pd.concat([real_trades, synthetic_trades], ignore_index=True),
        "quality": [real_quality, synthetic_quality],
        "regime_metrics": regime_metrics,
        "parameter_rows": [dict(symbol=symbol, **row) for row in robustness["parameter_rows"]],
    }
