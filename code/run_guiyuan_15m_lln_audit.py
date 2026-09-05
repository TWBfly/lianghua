"""归元·极值 15m 真实历史 / 合成大样本双轨审计。"""

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
if str(STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_DIR))

from guiyuan_zscore_reversion import calculate_signal


DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reports" / "guiyuan_15m_lln_20260827"
AUDIT_CACHE_VERSION = 2
PARAMETER_GRID = [(stop, trail) for stop in (1.5, 1.8, 2.0, 2.5) for trail in (1.5, 2.0, 2.5, 3.0)]


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
    stop_atr_mult: float = 1.8,
    breakeven_atr_mult: float = 1.0,
    trail_atr_mult: float = 2.0,
    max_holding_bars: int = 14,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    """以 t 收盘信号在 t+1 开盘成交，并完整记录期货双边成本与 CMR 目标出场。"""
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
    atr = true_range.rolling(14, min_periods=5).mean().bfill().to_numpy()
    sma20 = bars["close"].rolling(20, min_periods=5).mean().bfill().to_numpy()

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

        if position > 0:
            holding_bars = i - entry_index
            favorable_extreme = max(favorable_extreme, high[i])
            if favorable_extreme - entry_price >= breakeven_atr_mult * entry_atr:
                stop_price = max(stop_price, entry_price + 0.1 * entry_atr)
            stop_price = max(stop_price, favorable_extreme - trail_atr_mult * entry_atr)

            if np.isfinite(sma20[i - 1]) and high[i] >= sma20[i - 1]:
                close_position(i, max(open_[i], sma20[i - 1]), "target_mean")
            elif low[i] <= stop_price:
                close_position(i, min(open_[i], stop_price), "stop")
            elif holding_bars >= max_holding_bars:
                close_position(i, close[i], "time_stop")

        elif position < 0:
            holding_bars = i - entry_index
            favorable_extreme = min(favorable_extreme, low[i])
            if entry_price - favorable_extreme >= breakeven_atr_mult * entry_atr:
                stop_price = min(stop_price, entry_price - 0.1 * entry_atr)
            stop_price = min(stop_price, favorable_extreme + trail_atr_mult * entry_atr)

            if np.isfinite(sma20[i - 1]) and low[i] <= sma20[i - 1]:
                close_position(i, min(open_[i], sma20[i - 1]), "target_mean")
            elif high[i] >= stop_price:
                close_position(i, max(open_[i], stop_price), "stop")
            elif holding_bars >= max_holding_bars:
                close_position(i, close[i], "time_stop")

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
    max_batches: int = 40,
) -> tuple[list[pd.DataFrame], dict[str, Any]]:
    import synthetic_market_regime_generator as generator_module
    from synthetic_market_regime_generator import SyntheticMarketRegimeGenerator

    generator = SyntheticMarketRegimeGenerator(seed=_stable_seed(symbol))
    batches: list[pd.DataFrame] = []
    batch_results: list[dict[str, Any]] = []
    next_time = pd.Timestamp("2015-01-01 09:00:00")
    # ponytail: 40 independent regime batches cap memory; raise only if the original signal becomes even sparser.
    for _ in range(max_batches):
        original_dir = generator_module.SYNTHETIC_DATA_DIR
        with tempfile.TemporaryDirectory(prefix=f"guiyuan_{symbol.lower()}_") as temporary_dir:
            generator_module.SYNTHETIC_DATA_DIR = temporary_dir
            try:
                batch = generator.generate_regime_bars(
                    symbol,
                    start_price=float(spec["base_price"]),
                    bars_per_regime=bars_per_regime,
                    tick_size=float(spec["tick"]),
                    timeframe="15m",
                )
            finally:
                generator_module.SYNTHETIC_DATA_DIR = original_dir

        batch = batch[["open", "high", "low", "close", "volume", "open_interest", "regime"]].copy()
        batch.index = pd.date_range(next_time, periods=len(batch), freq="15min")
        batch["regime"] = batch["regime"].astype("category")
        next_time = batch.index[-1] + pd.Timedelta(minutes=15)
        result = simulate_guiyuan(batch, calculate_signal(batch), spec)
        if not result["trades"].empty:
            result["trades"]["regime"] = result["trades"]["entry_time"].map(batch["regime"])
        batches.append(batch)
        batch_results.append(result)
        count = sum(len(item["trades"]) for item in batch_results)
        if count >= target and lln_gate(count):
            return batches, combine_simulations(batch_results)

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
) -> dict[str, Any]:
    split = max(1, int(len(batches) * 0.70))
    holdout_batches = batches[split:]
    holdout = combine_simulations(
        [simulate_guiyuan(batch, calculate_signal(batch), spec) for batch in holdout_batches]
    )
    profitable_parameters = 0
    parameter_rows = []
    for stop, trail in PARAMETER_GRID:
        check = combine_simulations(
            [
                simulate_guiyuan(
                    batch,
                    calculate_signal(batch),
                    spec,
                    stop_atr_mult=stop,
                    trail_atr_mult=trail,
                )
                for batch in holdout_batches
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
            simulate_guiyuan(batch, calculate_signal(batch), spec, cost_multiplier=3.0)
            for batch in batches
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
    real_result = simulate_guiyuan(real_bars, calculate_signal(real_bars), spec)
    real_metrics = summarize_simulation(symbol, spec["name"], "real", real_result, len(real_bars))

    synthetic_batches, synthetic_result = generate_until_lln(
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
    robustness = _robustness_audit(synthetic_batches, spec)
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

    report = f"""# 归元·极值策略 15m 双轨深度回测报告

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

- 策略：`guiyuan_zscore_reversion` 重构版 (CMR-V2.0: 稳健Z-Score + 真实Connors RSI + ER/Hurst动力学门禁 + 做市商微观吸收状态机)。
- 周期：15m；信号在 Bar `t` 收盘形成，Bar `t+1` 开盘成交。
- 风控：1.8 ATR 初始止损、1.0 ATR 保本触发、2.0 ATR 动态吊灯与 SMA20 目标中枢止盈、14-Bar 半衰期时间清仓；每笔风险预算为初始资金 0.5%，最多 50 手。
- 摩擦：开平双边手续费及各 1 Tick 滑点；3 倍成本压力轨同时执行。
- 合成轨：固定种子的单边上涨、宽幅洗盘、恐慌下跌、窄幅横盘四状态；每批从品种基准价独立启动，每品种累计平仓交易严格大于 1,000。
- 统计：Wilson 95% 胜率区间、按时间顺序的 70/30 批次留出、16 组止损/追踪参数平原、逐笔账本对账。

## 真实历史轨

{_markdown_table(real, real_columns)}

真实轨负责回答历史有效性。任何品种真实交易不足 1,001 笔均不能宣称满足大数定律。

## 合成大样本压力轨

{_markdown_table(synthetic, synthetic_columns)}

## 数据质量

{_markdown_table(quality, quality_columns, digits=0)}

## 四市场状态分解

{_markdown_table(regimes, regime_columns)}

## 判定规则

- `REJECTED`：真实历史净利润/PF 不合格、账本不平、合成留出亏损、3 倍成本亏损或参数平原少于 10/16 盈利。
- `INSUFFICIENT_REAL_SAMPLE`：无硬失败，但真实轨未达到每品种 1,001 笔。
- `PAPER_ONLY`：全部门禁通过后也只允许模拟盘观察，不代表可直接实盘。

## 局限与风险

1. 合成路径来自参数化生成器，不能复制真实市场的涨跌停、夜盘跳空、换月基差、流动性枯竭和交易所手续费差异。
2. `*_IDX` 连续指数不是可直接成交合约；真实部署还需主力合约映射、换月规则和逐合约手续费。
3. Bar 内只有 OHLC，无法知道高低点先后；本引擎只使用上一柱已确定的止损检查当前柱，避免利用当前柱未来路径更新止损。
4. 每品种 1,000 笔降低的是抽样误差，不会消除制度错设、非独立同分布、数据偏差或过拟合。
5. 合成净利润为多个各配 1,000,000 元初始资金的独立制度批次之和，只用于跨状态压力比较，不可解释为单账户复利曲线。
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def run_audit(
    output_dir: Path = DEFAULT_OUTPUT,
    symbols: list[str] | None = None,
    target: int = 1_001,
    bars_per_regime: int = 30_000,
    workers: int = 1,
) -> dict[str, Any]:
    if target <= 1_000:
        raise ValueError("target must be greater than 1000")
    specs = _contract_specs()
    selected_symbols = symbols or list(specs)
    unknown = sorted(set(selected_symbols).difference(specs))
    if unknown:
        raise ValueError(f"unknown symbols: {unknown}")

    metric_rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    quality_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    cache_dir = output_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def collect(symbol: str, symbol_result: dict[str, Any], index: int) -> None:
        metric_rows.extend(symbol_result["metrics"])
        trade_frames.append(symbol_result["trades"])
        quality_rows.extend(symbol_result["quality"])
        regime_rows.extend(symbol_result["regime_metrics"])
        parameter_rows.extend(symbol_result["parameter_rows"])
        synthetic_row = symbol_result["metrics"][1]
        print(
            f"[{index}/{len(selected_symbols)}] {symbol}: synthetic trades={synthetic_row['trade_count']:,} "
            f"real trades={symbol_result['metrics'][0]['trade_count']:,} "
            f"status={synthetic_row['status']}",
            flush=True,
        )

    pending_symbols = []
    for symbol in selected_symbols:
        cache_path = cache_dir / f"{symbol}.pkl"
        if cache_path.exists():
            cached = pd.read_pickle(cache_path)
            if cached.get("version") == AUDIT_CACHE_VERSION:
                collect(symbol, cached["result"], len(metric_rows) // 2 + 1)
                continue
        pending_symbols.append(symbol)

    def collect_and_cache(symbol: str, symbol_result: dict[str, Any], index: int) -> None:
        pd.to_pickle(
            {"version": AUDIT_CACHE_VERSION, "result": symbol_result},
            cache_dir / f"{symbol}.pkl",
        )
        collect(symbol, symbol_result, index)

    if workers <= 1:
        for index, symbol in enumerate(pending_symbols, len(metric_rows) // 2 + 1):
            print(f"[{index}/{len(selected_symbols)}] 回测 {symbol}...", flush=True)
            collect_and_cache(symbol, run_symbol(symbol, specs[symbol], target, bars_per_regime), index)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_symbol, symbol, specs[symbol], target, bars_per_regime): symbol
                for symbol in pending_symbols
            }
            for index, future in enumerate(as_completed(futures), len(metric_rows) // 2 + 1):
                symbol = futures[future]
                collect_and_cache(symbol, future.result(), index)

    metrics = pd.DataFrame(metric_rows)
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    quality = pd.DataFrame(quality_rows)
    regimes = pd.DataFrame(regime_rows)
    parameters = pd.DataFrame(parameter_rows)
    real = metrics.loc[metrics["track"].eq("real")]
    synthetic = metrics.loc[metrics["track"].eq("synthetic")]
    real_summary = summarize_portfolio(metrics, "real")
    synthetic_summary = summarize_portfolio(metrics, "synthetic")
    real_summary.update(
        {
            "symbols": len(real),
            "profitable_symbols": int(real["net_pnl"].gt(0).sum()),
        }
    )
    synthetic_summary.update(
        {
            "symbols": len(synthetic),
            "min_symbol_trades": int(synthetic["trade_count"].min()),
            "all_symbols_over_1000": bool(synthetic["trade_count"].gt(1_000).all()),
            "holdout_profitable_symbols": int(synthetic["holdout_net_pnl"].gt(0).sum()),
            "stress_profitable_symbols": int(synthetic["stress_3x_net_pnl"].gt(0).sum()),
            "plateau_pass_symbols": int(synthetic["parameter_profitable"].ge(10).sum()),
        }
    )
    for track_summary in (real_summary, synthetic_summary):
        track_trades = trades.loc[trades["track"].eq(track_summary["track"])]
        wins = float(track_trades.loc[track_trades["net_pnl"].gt(0), "net_pnl"].sum())
        losses = float(-track_trades.loc[track_trades["net_pnl"].lt(0), "net_pnl"].sum())
        track_summary.update(
            {
                "win_rate_pct": 100.0 * float(track_trades["net_pnl"].gt(0).mean()),
                "profit_factor": wins / losses if losses else math.inf,
                "expectancy": float(track_trades["net_pnl"].mean()),
                "fees": float(track_trades[["entry_fee", "exit_fee"]].sum().sum()),
                "slippage": float(track_trades["slippage_cost"].sum()),
            }
        )
    statuses = set(metrics["status"])
    overall_status = (
        "REJECTED"
        if "REJECTED" in statuses
        else "INSUFFICIENT_REAL_SAMPLE"
        if "INSUFFICIENT_REAL_SAMPLE" in statuses
        else "PAPER_ONLY"
    )
    summary = {"status": overall_status, "real": real_summary, "synthetic": synthetic_summary}
    result = {
        "metrics": metrics,
        "trades": trades,
        "quality": quality,
        "regime_metrics": regimes,
        "parameter_metrics": parameters,
        "summary": summary,
    }
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--target", type=int, default=1_001)
    parser.add_argument("--bars-per-regime", type=int, default=30_000)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run_audit(args.output, args.symbols, args.target, args.bars_per_regime, args.workers)
    print(f"报告：{args.output / 'report.md'}", flush=True)
    print(json.dumps(_json_safe(result["summary"]), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
