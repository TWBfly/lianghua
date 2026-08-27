"""
code/run_taichong_15m_lln_audit.py — 「太冲·弹塑性张量」策略 15m 各品种期货大数定律双轨回测与五重硬门禁审计
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
CODE_DIR = PROJECT_ROOT / "code"
for p in (STRATEGIES_DIR, CODE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from taichong_elastoplastic_tensor import calculate_signal
from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reports" / "taichong_15m_lln_20260827"
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


def simulate_taichong(
    df: pd.DataFrame,
    signals: pd.Series,
    spec: dict[str, float],
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 2.5,
    breakeven_atr_mult: float = 2.0,
    trail_atr_mult: float = 5.0,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    """以 t 收盘信号在 t+1 开盘成交，支持卡方硬熔断离场与严格双边摩擦成本。"""
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

        # 反向信号或卡方熔断归零时，强制离场
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

        # 1. 均值回归第一目标达成止盈 (SMA5 Take Profit)
        if position > 0 and np.isfinite(sma5[i]) and high[i] >= sma5[i]:
            fill_p = min(high[i], max(open_[i], sma5[i]))
            close_position(i, fill_p, "take_profit_sma5")
        elif position < 0 and np.isfinite(sma5[i]) and low[i] <= sma5[i]:
            fill_p = max(low[i], min(open_[i], sma5[i]))
            close_position(i, fill_p, "take_profit_sma5")

        # 2. 初始/追踪硬止损 (Stop Loss)
        if position > 0 and low[i] <= stop_price:
            close_position(i, min(open_[i], stop_price), "stop")
        elif position < 0 and high[i] >= stop_price:
            close_position(i, max(open_[i], stop_price), "stop")

        if position > 0:
            favorable_extreme = max(favorable_extreme, high[i])
            if favorable_extreme - entry_price >= breakeven_atr_mult * entry_atr:
                stop_price = max(stop_price, entry_price)
            stop_price = max(stop_price, favorable_extreme - trail_atr_mult * entry_atr)
        elif position < 0:
            favorable_extreme = min(favorable_extreme, low[i])
            if entry_price - favorable_extreme >= breakeven_atr_mult * entry_atr:
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


def combine_simulations(
    results: list[dict[str, Any]],
    initial_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    if not results:
        return {
            "trades": pd.DataFrame(columns=TRADE_COLUMNS),
            "equity": pd.Series(dtype=float),
            "final_equity": 0.0,
            "net_pnl": 0.0,
            "ledger_reconciled": True,
        }
    trades = pd.concat([result["trades"] for result in results], ignore_index=True)
    equity = pd.concat(
        [result["equity"].reset_index(drop=True) for result in results],
        axis=1,
    ).sum(axis=1)
    net_pnl = float(sum(result["net_pnl"] for result in results))
    total_initial = initial_capital * len(results)
    final_equity = total_initial + net_pnl
    trade_total = float(trades["net_pnl"].sum()) if not trades.empty else 0.0
    return {
        "trades": trades,
        "equity": equity,
        "final_equity": final_equity,
        "net_pnl": net_pnl,
        "ledger_reconciled": bool(
            all(result["ledger_reconciled"] for result in results)
            and np.isclose(net_pnl, trade_total, atol=1e-6)
        ),
    }


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


def _fast_generate_regime_bars(
    symbol: str,
    start_price: float,
    bars_per_regime: int,
    tick_size: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    regimes_config = [
        {"name": "BULL_TREND", "bars": bars_per_regime, "mu": 0.00015, "sigma": 0.0040, "mean_revert": 0.001, "jump_prob": 0.008, "jump_mu": 0.004, "vol_base": 8000, "vol_mult": 1.5},
        {"name": "WHIPSAW_RANGE", "bars": bars_per_regime, "mu": 0.0000, "sigma": 0.0075, "mean_revert": 0.03, "jump_prob": 0.02, "jump_mu": -0.002, "vol_base": 6000, "vol_mult": 1.2},
        {"name": "PANIC_CRASH", "bars": bars_per_regime, "mu": -0.00020, "sigma": 0.0080, "mean_revert": 0.001, "jump_prob": 0.025, "jump_mu": -0.008, "vol_base": 12000, "vol_mult": 2.0},
        {"name": "GRINDING_CHOP", "bars": bars_per_regime, "mu": 0.0000, "sigma": 0.0022, "mean_revert": 0.06, "jump_prob": 0.003, "jump_mu": 0.0, "vol_base": 3000, "vol_mult": 0.6},
    ]
    all_open, all_high, all_low, all_close, all_vol, all_oi, all_reg = [], [], [], [], [], [], []
    curr = float(start_price)
    for reg in regimes_config:
        center = curr
        nb = reg["bars"]
        mu, sig, theta = reg["mu"], reg["sigma"], reg["mean_revert"]
        jp, jmu = reg["jump_prob"], reg["jump_mu"]
        vbase, vmult = reg["vol_base"], reg["vol_mult"]
        for _ in range(nb):
            drift = mu + theta * (math.log(center) - math.log(curr))
            diff = sig * rng.normal(0, 1)
            jump = rng.normal(jmu, sig * 1.5) if rng.random() < jp else 0.0
            ret = drift + diff + jump
            nxt = max(tick_size * 5, curr * math.exp(ret))
            p_open, p_close = curr, nxt
            ivol = sig * math.sqrt(0.5) * curr
            up_w = abs(rng.normal(0, ivol))
            dn_w = abs(rng.normal(0, ivol))
            p_high = max(p_open, p_close) + up_w
            p_low = max(tick_size, min(p_open, p_close) - dn_w)
            vol = int(vbase * vmult * (1.0 + abs(ret) * 30.0 + rng.exponential(0.3)))
            oi = int(vol * 8.5 + rng.normal(5000, 200))
            all_open.append(round(p_open / tick_size) * tick_size)
            all_high.append(round(p_high / tick_size) * tick_size)
            all_low.append(round(p_low / tick_size) * tick_size)
            all_close.append(round(p_close / tick_size) * tick_size)
            all_vol.append(max(10, vol))
            all_oi.append(max(100, oi))
            all_reg.append(reg["name"])
            curr = nxt
    df = pd.DataFrame(
        {
            "open": all_open,
            "high": all_high,
            "low": all_low,
            "close": all_close,
            "volume": all_vol,
            "open_interest": all_oi,
            "regime": all_reg,
        }
    )
    return df


def generate_until_lln(
    symbol: str,
    spec: dict[str, Any],
    target: int = 1_001,
    bars_per_regime: int = 10_000,
    max_batches: int = 40,
) -> tuple[list[pd.DataFrame], list[pd.Series], dict[str, Any]]:
    rng = np.random.default_rng(_stable_seed(symbol))
    batches: list[pd.DataFrame] = []
    batch_signals: list[pd.Series] = []
    batch_results: list[dict[str, Any]] = []
    next_time = pd.Timestamp("2015-01-01 09:00:00")

    for _ in range(max_batches):
        batch = _fast_generate_regime_bars(
            symbol=symbol,
            start_price=float(spec["base_price"]),
            bars_per_regime=bars_per_regime,
            tick_size=float(spec["tick"]),
            rng=rng,
        )
        batch.index = pd.date_range(next_time, periods=len(batch), freq="15min")
        batch["regime"] = batch["regime"].astype("category")
        next_time = batch.index[-1] + pd.Timedelta(minutes=15)
        sig = calculate_signal(batch)
        result = simulate_taichong(batch, sig, spec)
        if not result["trades"].empty:
            result["trades"]["regime"] = result["trades"]["entry_time"].map(batch["regime"])
        batches.append(batch)
        batch_signals.append(sig)
        batch_results.append(result)
        count = sum(len(item["trades"]) for item in batch_results)
        if count >= target and lln_gate(count):
            return batches, batch_signals, combine_simulations(batch_results)

    count = sum(len(item["trades"]) for item in batch_results)
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
    batches: list[pd.DataFrame],
    spec: dict[str, Any],
    batch_signals: list[pd.Series] | None = None,
) -> dict[str, Any]:
    if batch_signals is None:
        batch_signals = [calculate_signal(b) for b in batches]

    split = max(1, int(len(batches) * 0.70))
    holdout_batches = batches[split:]
    holdout_signals = batch_signals[split:]

    holdout = combine_simulations(
        [
            simulate_taichong(batch, sig, spec)
            for batch, sig in zip(holdout_batches, holdout_signals)
        ]
    )
    profitable_parameters = 0
    parameter_rows = []
    for stop, trail in PARAMETER_GRID:
        check = combine_simulations(
            [
                simulate_taichong(
                    batch,
                    sig,
                    spec,
                    stop_atr_mult=stop,
                    trail_atr_mult=trail,
                )
                for batch, sig in zip(holdout_batches, holdout_signals)
            ]
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
    stress = combine_simulations(
        [
            simulate_taichong(batch, sig, spec, cost_multiplier=3.0)
            for batch, sig in zip(batches, batch_signals)
        ]
    )
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
    real_result = simulate_taichong(real_bars, calculate_signal(real_bars), spec)
    real_metrics = summarize_simulation(symbol, spec["name"], "real", real_result, len(real_bars))

    synthetic_batches, synthetic_signals, synthetic_result = generate_until_lln(
        symbol,
        spec,
        target=target,
        bars_per_regime=bars_per_regime,
    )
    batch_quality = [audit_bars(symbol, "synthetic", batch) for batch in synthetic_batches]
    synthetic_quality = {
        "symbol": symbol,
        "track": "synthetic",
        "bars": sum(row["bars"] for row in batch_quality),
        "start": batch_quality[0]["start"],
        "end": batch_quality[-1]["end"],
        "duplicate_timestamps": sum(row["duplicate_timestamps"] for row in batch_quality),
        "missing_values": sum(row["missing_values"] for row in batch_quality),
        "ohlc_errors": sum(row["ohlc_errors"] for row in batch_quality),
    }
    synthetic_metrics = summarize_simulation(
        symbol,
        spec["name"],
        "synthetic",
        synthetic_result,
        synthetic_quality["bars"],
    )
    robustness = _robustness_audit(synthetic_batches, spec, synthetic_signals)
    synthetic_metrics.update({key: value for key, value in robustness.items() if key != "parameter_rows"})
    status = classify_symbol(real_metrics, synthetic_metrics, robustness)
    real_metrics["status"] = status
    synthetic_metrics["status"] = status

    synthetic_trades = synthetic_result["trades"].copy()
    synthetic_trades.insert(0, "track", "synthetic")
    synthetic_trades.insert(0, "symbol", symbol)
    real_trades = _attach_trade_context(real_result["trades"], symbol, "real", real_bars)
    regime_metrics = []
    if not synthetic_trades.empty:
        for regime, group in synthetic_trades.groupby("regime", dropna=False, observed=True):
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


def _format_number(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "是" if value else "否"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        if math.isinf(float(value)):
            return "∞"
        return f"{float(value):,.{digits}f}"
    return str(value)


def _markdown_table(frame: pd.DataFrame, columns: list[tuple[str, str]], digits: int = 2) -> str:
    if frame.empty:
        return "无数据。"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    rows = [header, divider]
    for _, row in frame.iterrows():
        rows.append(
            "| " + " | ".join(_format_number(row.get(column), digits) for column, _ in columns) + " |"
        )
    return "\n".join(rows)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if pd.isna(value):
        return None
    return value


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = result["metrics"]
    trades = result["trades"]
    quality = result["quality"]
    regimes = result["regime_metrics"]
    parameters = result["parameter_metrics"]
    summary = result["summary"]

    metrics.to_csv(output_dir / "symbol_metrics.csv", index=False)
    trades.to_csv(output_dir / "trades.csv", index=False)
    quality.to_csv(output_dir / "data_quality.csv", index=False)
    regimes.to_csv(output_dir / "regime_metrics.csv", index=False)
    parameters.to_csv(output_dir / "parameter_metrics.csv", index=False)

    payload = {
        "summary": summary,
        "symbol_metrics": metrics.to_dict("records"),
        "data_quality": quality.to_dict("records"),
        "regime_metrics": regimes.to_dict("records"),
        "parameter_metrics": parameters.to_dict("records"),
    }
    (output_dir / "report.json").write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    real = metrics.loc[metrics["track"].eq("real")].copy()
    synthetic = metrics.loc[metrics["track"].eq("synthetic")].copy()
    real_columns = [
        ("symbol", "品种"),
        ("trade_count", "交易"),
        ("win_rate_pct", "胜率%"),
        ("profit_factor", "PF"),
        ("net_pnl", "净利润"),
        ("max_drawdown_pct", "最大回撤%"),
        ("sharpe", "Sharpe"),
        ("status", "结论"),
    ]
    synthetic_columns = [
        ("symbol", "品种"),
        ("trade_count", "交易"),
        ("win_rate_pct", "胜率%"),
        ("win_rate_ci95_low", "CI低%"),
        ("win_rate_ci95_high", "CI高%"),
        ("profit_factor", "PF"),
        ("net_pnl", "净利润"),
        ("holdout_net_pnl", "30%留出净利"),
        ("stress_3x_net_pnl", "3倍成本净利"),
        ("parameter_profitable", "盈利参数/16"),
    ]
    quality_columns = [
        ("symbol", "品种"),
        ("track", "轨道"),
        ("bars", "Bars"),
        ("start", "开始"),
        ("end", "结束"),
        ("duplicate_timestamps", "重复"),
        ("missing_values", "缺失"),
        ("ohlc_errors", "OHLC错误"),
    ]
    regime_columns = [
        ("symbol", "品种"),
        ("regime", "市场状态"),
        ("trades", "交易"),
        ("win_rate_pct", "胜率%"),
        ("net_pnl", "净利润"),
    ]

    report = f"""# 太冲·弹塑性张量策略 15m 双轨深度回测报告

## 结论先行

最终审计结论：**{summary['status']}**。

- 真实历史轨净利润：{_format_number(summary['real']['net_pnl'])} 元；交易 {_format_number(summary['real']['trade_count'])} 笔；胜率 {_format_number(summary['real'].get('win_rate_pct'))}%；PF {_format_number(summary['real'].get('profit_factor'))}；盈利品种 {summary['real'].get('profitable_symbols', 0)}/{summary['real'].get('symbols', len(real))}。
- 合成压力轨净利润：{_format_number(summary['synthetic']['net_pnl'])} 元；交易 {_format_number(summary['synthetic']['trade_count'])} 笔；胜率 {_format_number(summary['synthetic'].get('win_rate_pct'))}%；PF {_format_number(summary['synthetic'].get('profit_factor'))}；最少单品种交易 {_format_number(summary['synthetic'].get('min_symbol_trades', 0))} 笔。
- 大数门禁：{('通过' if summary['synthetic'].get('all_symbols_over_1000') else '未通过')}。这里是**合成压力轨，不是历史绩效**，不可与真实收益合并，也不构成实盘有效性证明。
- 合成鲁棒性通过数：30% 留出盈利 {summary['synthetic'].get('holdout_profitable_symbols', 0)}/{len(synthetic)}；3 倍成本盈利 {summary['synthetic'].get('stress_profitable_symbols', 0)}/{len(synthetic)}；参数平原达标 {summary['synthetic'].get('plateau_pass_symbols', 0)}/{len(synthetic)}。

## 组合级统计

| 轨道 | 交易 | 胜率% | PF | 单笔期望 | 净利润 | 手续费 | 滑点成本 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 真实历史 | {_format_number(summary['real'].get('trade_count'))} | {_format_number(summary['real'].get('win_rate_pct'))} | {_format_number(summary['real'].get('profit_factor'))} | {_format_number(summary['real'].get('expectancy'))} | {_format_number(summary['real'].get('net_pnl'))} | {_format_number(summary['real'].get('fees'))} | {_format_number(summary['real'].get('slippage'))} |
| 合成压力 | {_format_number(summary['synthetic'].get('trade_count'))} | {_format_number(summary['synthetic'].get('win_rate_pct'))} | {_format_number(summary['synthetic'].get('profit_factor'))} | {_format_number(summary['synthetic'].get('expectancy'))} | {_format_number(summary['synthetic'].get('net_pnl'))} | {_format_number(summary['synthetic'].get('fees'))} | {_format_number(summary['synthetic'].get('slippage'))} |

## 回测口径

- 策略：`taichong_elastoplastic_tensor` 协方差白化、弹塑性应变分解、卡方破裂熔断与微观做市商吸收。
- 周期：15m；信号在 Bar `t` 收盘形成，Bar `t+1` 开盘成交。
- 风控：2.5 ATR 初始止损、2.0 ATR 保本触发、5.0 ATR 追踪；每笔风险预算为初始资金 0.5%，最多 50 手。
- 摩擦：开平双边手续费及各 1 Tick 滑点；3 倍成本压力轨同时执行。
- 合成轨：固定种子的单边上涨、宽幅洗盘、恐慌下跌、窄幅横盘四状态；每批从品种基准价独立启动，每品种累计平仓交易严格大于 1,000。
- 统计：Wilson 95% 胜率区间、按时间顺序的 70/30 批次留出、16 组止损/追踪参数平原、逐笔账本对账。

## 真实历史轨

{_markdown_table(real, real_columns)}

## 合成压力轨与五重硬门禁

{_markdown_table(synthetic, synthetic_columns)}

## 四状态市场表现

{_markdown_table(regimes, regime_columns)}

## 数据质量审计

{_markdown_table(quality, quality_columns)}
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="太冲·弹塑性张量策略 15m 双轨大样本回测")
    parser.add_argument("--symbols", nargs="*", default=list(ACTIVE_CONTRACT_SPECS.keys()), help="回测品种代码")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="报告输出目录")
    parser.add_argument("--target", type=int, default=1_001, help="单品种合成交易目标")
    parser.add_argument("--bars-per-regime", type=int, default=10_000, help="每状态Bar数")
    parser.add_argument("--max-workers", type=int, default=4, help="并行进程数")
    args = parser.parse_args()

    specs = {symbol: ACTIVE_CONTRACT_SPECS[symbol] for symbol in args.symbols if symbol in ACTIVE_CONTRACT_SPECS}
    print(f"[TaiChong 15m LLN] 🚀 启动 {len(specs)} 个期货品种的 15m 双轨大样本回测...")

    symbol_results = []
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                run_symbol,
                symbol,
                spec,
                args.target,
                args.bars_per_regime,
            ): symbol
            for symbol, spec in specs.items()
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                res = future.result()
                symbol_results.append(res)
                print(f"[TaiChong 15m LLN] ✅ 品种 {sym} 回测完成 (真实+合成均已核算)")
            except Exception as e:
                print(f"[TaiChong 15m LLN] ❌ 品种 {sym} 失败: {e}")
                import traceback
                traceback.print_exc()

    all_metrics = pd.DataFrame([m for res in symbol_results for m in res["metrics"]])
    all_trades = pd.concat([res["trades"] for res in symbol_results], ignore_index=True)
    all_quality = pd.DataFrame([q for res in symbol_results for q in res["quality"]])
    all_regimes = pd.concat([pd.DataFrame(res["regime_metrics"]) for res in symbol_results], ignore_index=True)
    all_parameters = pd.concat([pd.DataFrame(res["parameter_rows"]) for res in symbol_results], ignore_index=True)

    real_metrics = all_metrics.loc[all_metrics["track"].eq("real")]
    synth_metrics = all_metrics.loc[all_metrics["track"].eq("synthetic")]

    real_wins = int((all_trades.loc[all_trades["track"].eq("real"), "net_pnl"] > 0).sum())
    real_count = len(all_trades.loc[all_trades["track"].eq("real")])
    real_gp = float(all_trades.loc[all_trades["track"].eq("real") & all_trades["net_pnl"].gt(0), "net_pnl"].sum())
    real_gl = float(-all_trades.loc[all_trades["track"].eq("real") & all_trades["net_pnl"].lt(0), "net_pnl"].sum())

    synth_wins = int((all_trades.loc[all_trades["track"].eq("synthetic"), "net_pnl"] > 0).sum())
    synth_count = len(all_trades.loc[all_trades["track"].eq("synthetic")])
    synth_gp = float(all_trades.loc[all_trades["track"].eq("synthetic") & all_trades["net_pnl"].gt(0), "net_pnl"].sum())
    synth_gl = float(-all_trades.loc[all_trades["track"].eq("synthetic") & all_trades["net_pnl"].lt(0), "net_pnl"].sum())

    summary = {
        "status": "BACKTEST_VALIDATED" if (synth_metrics["status"] == "PAPER_ONLY").all() else ("REJECTED" if (synth_metrics["status"] == "REJECTED").any() else "INSUFFICIENT_EVIDENCE"),
        "real": {
            "symbols": len(real_metrics),
            "profitable_symbols": int((real_metrics["net_pnl"] > 0).sum()),
            "trade_count": real_count,
            "win_rate_pct": 100.0 * real_wins / real_count if real_count else 0.0,
            "profit_factor": real_gp / real_gl if real_gl else math.inf,
            "expectancy": float(all_trades.loc[all_trades["track"].eq("real"), "net_pnl"].mean()) if real_count else 0.0,
            "net_pnl": float(real_metrics["net_pnl"].sum()),
            "fees": float(all_trades.loc[all_trades["track"].eq("real"), ["entry_fee", "exit_fee"]].sum().sum()),
            "slippage": float(all_trades.loc[all_trades["track"].eq("real"), "slippage_cost"].sum()),
        },
        "synthetic": {
            "symbols": len(synth_metrics),
            "min_symbol_trades": int(synth_metrics["trade_count"].min()) if len(synth_metrics) else 0,
            "all_symbols_over_1000": bool((synth_metrics["trade_count"] > 1000).all()),
            "holdout_profitable_symbols": int((synth_metrics["holdout_net_pnl"] > 0).sum()),
            "stress_profitable_symbols": int((synth_metrics["stress_3x_net_pnl"] > 0).sum()),
            "plateau_pass_symbols": int((synth_metrics["parameter_profitable"] >= 10).sum()),
            "trade_count": synth_count,
            "win_rate_pct": 100.0 * synth_wins / synth_count if synth_count else 0.0,
            "profit_factor": synth_gp / synth_gl if synth_gl else math.inf,
            "expectancy": float(all_trades.loc[all_trades["track"].eq("synthetic"), "net_pnl"].mean()) if synth_count else 0.0,
            "net_pnl": float(synth_metrics["net_pnl"].sum()),
            "fees": float(all_trades.loc[all_trades["track"].eq("synthetic"), ["entry_fee", "exit_fee"]].sum().sum()),
            "slippage": float(all_trades.loc[all_trades["track"].eq("synthetic"), "slippage_cost"].sum()),
        }
    }

    result = {
        "metrics": all_metrics,
        "trades": all_trades,
        "quality": all_quality,
        "regime_metrics": all_regimes,
        "parameter_metrics": all_parameters,
        "summary": summary,
    }

    write_report(Path(args.output_dir), result)
    print(f"[TaiChong 15m LLN] 🎉 回测与大数审计完成！报告已保存至 {args.output_dir}")


if __name__ == "__main__":
    main()
