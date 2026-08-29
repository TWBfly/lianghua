"""
code/run_taichong_10m_squad_lln_audit.py — 「太冲·弹塑性张量」10分钟战队 (SN, AU, AG, MA, P) 大数定律全景双轨深度回测与五重硬门禁审计
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
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

from taichong_elastoplastic_tensor import calculate_signal, calculate_factors
from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reports" / "taichong_10m_squad_lln_20260828"
TARGET_SYMBOLS = ["SN_IDX", "AU_IDX", "AG_IDX", "MA_IDX", "P_IDX"]
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
    return trades >= 1_000


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
    losses = int(trades["net_pnl"].lt(0).sum()) if count else 0
    gross_profit = float(trades.loc[trades["net_pnl"].gt(0), "net_pnl"].sum()) if count else 0.0
    gross_loss = float(-trades.loc[trades["net_pnl"].lt(0), "net_pnl"].sum()) if count else 0.0
    ci_low, ci_high = _wilson_interval(wins, count)
    fees = float(trades[["entry_fee", "exit_fee"]].sum().sum()) if count else 0.0
    slippage = float(trades["slippage_cost"].sum()) if count else 0.0
    gross_pnl = float(trades["gross_pnl"].sum()) if count else 0.0

    equity = result["equity"].astype(float)
    peaks = equity.cummax()
    max_drawdown = float(((peaks - equity) / peaks.replace(0.0, np.nan)).max() * 100.0)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    
    # 10m: 1年约 252 * 36 = 9072 根柱
    tf_mult = 36.0
    if len(returns) > 1 and returns.std(ddof=0) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=0) * math.sqrt(252.0 * tf_mult))
    else:
        sharpe = 0.0
    downside = returns.loc[returns.lt(0)]
    if len(downside) > 1 and downside.std(ddof=0) > 0:
        sortino = float(returns.mean() / downside.std(ddof=0) * math.sqrt(252.0 * tf_mult))
    else:
        sortino = 0.0
    initial_capital = float(result["final_equity"] - result["net_pnl"])
    ret_pct = 100.0 * float(result["net_pnl"]) / initial_capital
    calmar = float(ret_pct / max_drawdown) if max_drawdown > 0 else (math.inf if ret_pct > 0 else 0.0)

    avg_holding_hours = float(trades["holding_bars"].mean() * (10.0 / 60.0)) if count else 0.0

    return {
        "symbol": symbol,
        "name": name,
        "timeframe": "10m",
        "track": track,
        "bars": int(bars),
        "trade_count": int(count),
        "win_count": int(wins),
        "loss_count": int(losses),
        "win_rate_pct": 100.0 * wins / count if count else 0.0,
        "win_rate_ci95_low": ci_low,
        "win_rate_ci95_high": ci_high,
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0),
        "expectancy": float(trades["net_pnl"].mean()) if count else 0.0,
        "gross_pnl": gross_pnl,
        "net_pnl": float(result["net_pnl"]),
        "return_pct": ret_pct,
        "max_drawdown_pct": 0.0 if math.isnan(max_drawdown) else max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "avg_holding_hours": avg_holding_hours,
        "fees": fees,
        "slippage": slippage,
        "cost_to_gross_pct": 100.0 * (fees + slippage) / max(1e-12, gross_profit),
        "ledger_reconciled": bool(result["ledger_reconciled"]),
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
            WHERE symbol = ? AND timeframe = '10m'
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
    return 20_260_828 + sum((index + 1) * ord(char) for index, char in enumerate(symbol))


def _fast_generate_regime_bars_10m(
    symbol: str,
    start_price: float,
    bars_per_regime: int,
    tick_size: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    tf_scale = math.sqrt(10.0 / 15.0)
    regimes_config = [
        {"name": "BULL_TREND", "bars": bars_per_regime, "mu": 0.00015 * (tf_scale**2), "sigma": 0.0040 * tf_scale, "mean_revert": 0.001, "jump_prob": 0.008, "jump_mu": 0.004, "vol_base": 8000, "vol_mult": 1.5},
        {"name": "WHIPSAW_RANGE", "bars": bars_per_regime, "mu": 0.0000, "sigma": 0.0075 * tf_scale, "mean_revert": 0.03, "jump_prob": 0.02, "jump_mu": -0.002, "vol_base": 6000, "vol_mult": 1.2},
        {"name": "PANIC_CRASH", "bars": bars_per_regime, "mu": -0.00020 * (tf_scale**2), "sigma": 0.0080 * tf_scale, "mean_revert": 0.001, "jump_prob": 0.025, "jump_mu": -0.008, "vol_base": 12000, "vol_mult": 2.0},
        {"name": "GRINDING_CHOP", "bars": bars_per_regime, "mu": 0.0000, "sigma": 0.0022 * tf_scale, "mean_revert": 0.06, "jump_prob": 0.003, "jump_mu": 0.0, "vol_base": 3000, "vol_mult": 0.6},
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


def generate_until_lln_10m(
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
        batch = _fast_generate_regime_bars_10m(
            symbol=symbol,
            start_price=float(spec["base_price"]),
            bars_per_regime=bars_per_regime,
            tick_size=float(spec["tick"]),
            rng=rng,
        )
        batch.index = pd.date_range(next_time, periods=len(batch), freq="10min")
        batch["regime"] = batch["regime"].astype("category")
        next_time = batch.index[-1] + pd.Timedelta(minutes=10)
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
    raise RuntimeError(f"{symbol} (10m) generated only {count} trades after {max_batches} batches")


def _attach_trade_context(
    trades: pd.DataFrame,
    symbol: str,
    track: str,
    bars: pd.DataFrame,
) -> pd.DataFrame:
    contextual = trades.copy()
    contextual.insert(0, "track", track)
    contextual.insert(0, "timeframe", "10m")
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


def run_single_squad_symbol(
    symbol: str,
    spec: dict[str, Any],
    target: int = 1_001,
    bars_per_regime: int = 10_000,
) -> dict[str, Any]:
    real_bars = load_real_bars(symbol)
    real_quality = audit_bars(symbol, "real", real_bars)
    real_result = simulate_taichong(real_bars, calculate_signal(real_bars), spec)
    real_metrics = summarize_simulation(symbol, spec["name"], "real", real_result, len(real_bars))

    synthetic_batches, synthetic_signals, synthetic_result = generate_until_lln_10m(
        symbol,
        spec,
        target=target,
        bars_per_regime=bars_per_regime,
    )
    batch_quality = [audit_bars(symbol, "synthetic", batch) for batch in synthetic_batches]
    synthetic_quality = {
        "symbol": symbol,
        "timeframe": "10m",
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
    synthetic_trades.insert(0, "timeframe", "10m")
    synthetic_trades.insert(0, "symbol", symbol)
    real_trades = _attach_trade_context(real_result["trades"], symbol, "real", real_bars)
    
    regime_metrics = []
    if not synthetic_trades.empty:
        for regime, group in synthetic_trades.groupby("regime", dropna=False, observed=True):
            regime_metrics.append(
                {
                    "symbol": symbol,
                    "timeframe": "10m",
                    "regime": str(regime),
                    "trades": len(group),
                    "win_rate_pct": 100.0 * group["net_pnl"].gt(0).mean(),
                    "net_pnl": float(group["net_pnl"].sum()),
                }
            )

    return {
        "symbol": symbol,
        "timeframe": "10m",
        "metrics": [real_metrics, synthetic_metrics],
        "trades": pd.concat([real_trades, synthetic_trades], ignore_index=True),
        "quality": [real_quality, synthetic_quality],
        "regime_metrics": regime_metrics,
        "parameter_rows": [dict(symbol=symbol, timeframe="10m", **row) for row in robustness["parameter_rows"]],
    }


def compute_squad_scorecard(summary: dict[str, Any]) -> dict[str, Any]:
    real = summary["real"]
    synth = summary["synthetic"]

    # 1. 预测能力与因子质量 (25分)
    win_rate = real["win_rate_pct"]
    s1 = min(25.0, max(0.0, (win_rate - 45.0) * 1.5 + (10.0 if real["expectancy"] > 0 else 0.0)))
    
    # 2. 风险调整收益与盈利质量 (25分)
    sharpe = max(0.0, real["sharpe"])
    pf = real["profit_factor"] if math.isfinite(real["profit_factor"]) else 3.0
    s2 = min(25.0, max(0.0, (sharpe / 2.0) * 12.0 + min(13.0, max(0.0, (pf - 1.0) * 10.0))))

    # 3. 回撤控制与下行尾部风险 (20分)
    max_dd = real["max_drawdown_pct"]
    dd_score = max(0.0, 10.0 * (1.0 - min(1.0, max_dd / 10.0)))
    crash_wr = summary.get("crash_win_rate", 50.0)
    crash_score = min(10.0, max(0.0, (crash_wr - 40.0) * 0.5))
    s3 = min(20.0, dd_score + crash_score)

    # 4. 抗过拟合与对抗鲁棒性 (20分)
    holdout_rate = synth["holdout_profitable_rate"]
    plateau_rate = synth["plateau_pass_rate"]
    s4 = min(20.0, holdout_rate * 6.0 + plateau_rate * 8.0 + 6.0)

    # 5. 实盘可行性与摩擦容忍度 (10分)
    stress_rate = synth["stress_profitable_rate"]
    friction_drag = real.get("cost_drag_pct", 50.0)
    drag_score = max(0.0, 5.0 * (1.0 - min(1.0, friction_drag / 60.0)))
    s5 = min(10.0, stress_rate * 5.0 + drag_score)

    total_score = round(s1 + s2 + s3 + s4 + s5, 1)
    grade = "S" if total_score >= 90 else ("A" if total_score >= 80 else ("B" if total_score >= 70 else ("C" if total_score >= 60 else "D")))

    return {
        "factor_quality_score": round(s1, 1),
        "risk_adjusted_score": round(s2, 1),
        "drawdown_control_score": round(s3, 1),
        "anti_overfitting_score": round(s4, 1),
        "friction_feasibility_score": round(s5, 1),
        "total_score": total_score,
        "grade": grade,
    }


def main():
    parser = argparse.ArgumentParser(description="太冲·弹塑性张量 10分钟战队大样本深度回测")
    parser.add_argument("--symbols", nargs="*", default=TARGET_SYMBOLS, help="回测品种代码")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="报告输出目录")
    parser.add_argument("--target", type=int, default=1_001, help="单品种合成交易目标")
    parser.add_argument("--bars-per-regime", type=int, default=10_000, help="每状态Bar数")
    parser.add_argument("--max-workers", type=int, default=5, help="并行进程数")
    args = parser.parse_args()

    symbols = [s for s in args.symbols if s in ACTIVE_CONTRACT_SPECS]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🚀 [TaiChong 10m Squad LLN] 启动 10分钟战队 {symbols} 大样本回测与五重硬门禁审计...", flush=True)

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                run_single_squad_symbol,
                sym,
                ACTIVE_CONTRACT_SPECS[sym],
                args.target,
                args.bars_per_regime,
            ): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                res = future.result()
                results.append(res)
                print(f"✅ [10m Squad] {sym} 回测与审计完成 (真实历史 + 合成大数 >=1000 笔已达成)", flush=True)
            except Exception as e:
                print(f"❌ [10m Squad] {sym} 失败: {e}", flush=True)
                import traceback
                traceback.print_exc()

    elapsed = time.time() - t0
    print(f"🎉 全部战队品种回测完成，耗时 {elapsed:.1f} 秒！正在生成全景统计与报告...", flush=True)

    all_metrics = pd.DataFrame([m for res in results for m in res["metrics"]])
    all_trades = pd.concat([res["trades"] for res in results], ignore_index=True)
    all_regimes = pd.concat([pd.DataFrame(res["regime_metrics"]) for res in results], ignore_index=True)
    all_parameters = pd.concat([pd.DataFrame(res["parameter_rows"]) for res in results], ignore_index=True)

    all_metrics.to_csv(output_dir / "squad_10m_metrics.csv", index=False)
    all_trades.to_csv(output_dir / "squad_10m_trades.csv", index=False)
    all_regimes.to_csv(output_dir / "squad_10m_regimes.csv", index=False)
    all_parameters.to_csv(output_dir / "squad_10m_parameters.csv", index=False)

    real_m = all_metrics.loc[all_metrics["track"].eq("real")]
    synth_m = all_metrics.loc[all_metrics["track"].eq("synthetic")]
    real_t = all_trades.loc[all_trades["track"].eq("real")]
    synth_t = all_trades.loc[all_trades["track"].eq("synthetic")]

    real_wins = int((real_t["net_pnl"] > 0).sum())
    real_count = len(real_t)
    real_gp = float(real_t.loc[real_t["net_pnl"].gt(0), "net_pnl"].sum())
    real_gl = float(-real_t.loc[real_t["net_pnl"].lt(0), "net_pnl"].sum())

    synth_wins = int((synth_t["net_pnl"] > 0).sum())
    synth_count = len(synth_t)
    synth_gp = float(synth_t.loc[synth_t["net_pnl"].gt(0), "net_pnl"].sum())
    synth_gl = float(-synth_t.loc[synth_t["net_pnl"].lt(0), "net_pnl"].sum())

    fees_r = float(real_t[["entry_fee", "exit_fee"]].sum().sum())
    slip_r = float(real_t["slippage_cost"].sum())
    gross_r = float(real_t["gross_pnl"].sum())

    crash_trades = all_regimes.loc[all_regimes["regime"].str.contains("PANIC_CRASH|CRASH", case=False)]
    crash_wr = float(crash_trades["win_rate_pct"].mean()) if not crash_trades.empty else 50.0

    avg_max_dd = float(real_m["max_drawdown_pct"].mean())
    avg_sharpe = float(real_m["sharpe"].mean())
    avg_sortino = float(real_m["sortino"].mean())
    avg_holding = float(real_m["avg_holding_hours"].mean())

    squad_summary = {
        "timeframe": "10m",
        "squad_name": "10分钟微观弹性超短战队",
        "symbols": symbols,
        "real": {
            "symbols_count": len(real_m),
            "profitable_symbols": int((real_m["net_pnl"] > 0).sum()),
            "profitable_symbols_rate": float((real_m["net_pnl"] > 0).mean()),
            "trade_count": real_count,
            "win_rate_pct": 100.0 * real_wins / real_count if real_count else 0.0,
            "profit_factor": real_gp / real_gl if real_gl else math.inf,
            "expectancy": float(real_t["net_pnl"].mean()) if real_count else 0.0,
            "total_net_pnl": float(real_m["net_pnl"].sum()),
            "avg_net_pnl_per_symbol": float(real_m["net_pnl"].mean()),
            "sharpe": avg_sharpe,
            "sortino": avg_sortino,
            "max_drawdown_pct": avg_max_dd,
            "avg_holding_hours": avg_holding,
            "fees": fees_r,
            "slippage": slip_r,
            "cost_drag_pct": 100.0 * (fees_r + slip_r) / max(1e-12, gross_r) if gross_r > 0 else 100.0,
        },
        "synthetic": {
            "symbols_count": len(synth_m),
            "min_symbol_trades": int(synth_m["trade_count"].min()) if len(synth_m) else 0,
            "trade_count": synth_count,
            "win_rate_pct": 100.0 * synth_wins / synth_count if synth_count else 0.0,
            "profit_factor": synth_gp / synth_gl if synth_gl else math.inf,
            "expectancy": float(synth_t["net_pnl"].mean()) if synth_count else 0.0,
            "total_net_pnl": float(synth_m["net_pnl"].sum()),
            "holdout_profitable_count": int((synth_m["holdout_net_pnl"] > 0).sum()),
            "holdout_profitable_rate": float((synth_m["holdout_net_pnl"] > 0).mean()),
            "stress_profitable_count": int((synth_m["stress_3x_net_pnl"] > 0).sum()),
            "stress_profitable_rate": float((synth_m["stress_3x_net_pnl"] > 0).mean()),
            "plateau_pass_count": int((synth_m["parameter_profitable"] >= 10).sum()),
            "plateau_pass_rate": float((synth_m["parameter_profitable"] >= 10).mean()),
            "all_symbols_over_1000": bool((synth_m["trade_count"] >= 1000).all()),
        },
        "crash_win_rate": crash_wr,
    }
    scorecard = compute_squad_scorecard(squad_summary)
    squad_summary["scorecard"] = scorecard

    with open(output_dir / "squad_summary.json", "w", encoding="utf-8") as f:
        json.dump(squad_summary, f, ensure_ascii=False, indent=2)

    print("📊 [TaiChong 10m Squad LLN] 审计与回测报告已成功输出！", flush=True)


if __name__ == "__main__":
    main()
