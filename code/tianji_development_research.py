from __future__ import annotations

import numpy as np
import pandas as pd

from futures_research_backtest import (
    ResearchRejected,
    TIANJI_REBALANCE_BARS,
    _tianji_leg,
    build_tianji_scores,
    simulate_tianji_ledger,
    tianji_metrics,
)

CANDIDATES = ("continuation", "reversal", "timeseries_donchian")
FORBIDDEN_HOLDOUT_START = pd.Timestamp("2026-06-26 10:45:00")


def development_folds(times, forbidden_start=FORBIDDEN_HOLDOUT_START):
    times = pd.DatetimeIndex(sorted(pd.DatetimeIndex(times).unique()))
    times = times[times < forbidden_start]
    blocks = np.array_split(times, 4)
    folds = tuple(pd.DatetimeIndex(block) for block in blocks[1:])
    if len(folds) != 3 or any(fold.empty for fold in folds):
        raise ResearchRejected("insufficient TianJi development folds")
    return folds


def candidate_targets(scores, market, candidate, fold_times):
    if candidate not in CANDIDATES:
        raise ResearchRejected("unknown TianJi development candidate")
    required = {
        "decision_time", "symbol", "signal_ready", "score",
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
        "prior_breakout_up_20", "prior_breakout_down_20", "atr", "atr_pct",
        "sector",
    }
    missing = required.difference(scores.columns)
    if missing:
        raise ResearchRejected(
            f"missing TianJi development columns: {', '.join(sorted(missing))}"
        )
    frame = scores[
        scores["decision_time"].isin(fold_times) & scores["signal_ready"]
    ].copy()
    percentile = frame.groupby("decision_time")["score"].rank(
        pct=True, method="average"
    )
    continuation_long = (
        (percentile >= 0.90)
        & frame["signed_kaufman_efficiency_20"].gt(0.30)
        & frame["donchian_position_20"].gt(0.80)
        & frame["momentum_acceleration_5_20"].gt(0.0)
        & frame["intraday_intensity_10"].gt(0.0)
    )
    continuation_short = (
        (percentile <= 0.10)
        & frame["signed_kaufman_efficiency_20"].lt(-0.30)
        & frame["donchian_position_20"].lt(-0.80)
        & frame["momentum_acceleration_5_20"].lt(0.0)
        & frame["intraday_intensity_10"].lt(0.0)
    )
    if candidate == "continuation":
        long_mask, short_mask = continuation_long, continuation_short
    elif candidate == "reversal":
        long_mask, short_mask = continuation_short, continuation_long
    else:
        long_mask = frame["prior_breakout_up_20"].astype(bool) & continuation_long
        short_mask = frame["prior_breakout_down_20"].astype(bool) & continuation_short

    rows = []
    times = pd.DatetimeIndex(sorted(frame["decision_time"].unique()))
    rebalance_times = times[::TIANJI_REBALANCE_BARS]
    for time in rebalance_times:
        at_time = frame[frame["decision_time"].eq(time)]
        longs = _tianji_leg(
            at_time[long_mask.reindex(at_time.index, fill_value=False)], 1
        )[:2]
        shorts = _tianji_leg(
            at_time[short_mask.reindex(at_time.index, fill_value=False)], -1
        )[:2]
        count = min(len(longs), len(shorts))
        rows.extend(longs[:count])
        rows.extend(shorts[:count])
    targets = pd.DataFrame(rows, columns=(
        "decision_time", "symbol", "direction", "atr", "atr_pct", "score",
        "sector",
    ))
    targets["trail_activation_r"] = 3.0
    return targets, rebalance_times


def development_gates(metrics):
    checks = {
        "payoff_ratio": float(metrics["payoff_ratio"]) >= 3.0,
        "max_drawdown": float(metrics["max_drawdown"]) <= 0.15,
        "positive_return": float(metrics["total_return"]) > 0.0,
        "minimum_trades": int(metrics["trades"]) >= 200,
    }
    return {"passed": all(checks.values()), "checks": checks}


def select_development_candidate(rows):
    eligible = rows[rows["eligible"]].sort_values(
        ["worst_payoff", "worst_drawdown", "turnover", "candidate"],
        ascending=[False, True, True, True],
        kind="stable",
    )
    return None if eligible.empty else str(eligible.iloc[0]["candidate"])


def development_status(selected):
    return "DEVELOPMENT_CANDIDATE" if selected else "DEVELOPMENT_REJECTED"


def _combined_metrics(fold_results):
    trades = pd.concat(
        [result["trades"] for result in fold_results], ignore_index=True
    )
    pnl = (
        trades["sleeve_pnl"].astype(float)
        if len(trades) else pd.Series(dtype=float)
    )
    winners = pnl[pnl > 0.0]
    losers = -pnl[pnl < 0.0]
    return {
        "payoff_ratio": (
            float(winners.mean() / losers.mean())
            if len(winners) and len(losers) else 0.0
        ),
        "max_drawdown": max(
            (result["metrics"]["max_drawdown"] for result in fold_results),
            default=0.0,
        ),
        "total_return": float(np.prod([
            1.0 + result["metrics"]["total_return"]
            for result in fold_results
        ]) - 1.0),
        "trades": int(len(trades)),
        "turnover": float(sum(
            result["metrics"]["turnover"] for result in fold_results
        )),
    }


def _evaluate_fold(scores, market, candidate, fold, cost):
    targets, rebalances = candidate_targets(
        scores, market, candidate, fold
    )
    fold_market = market[market["trade_time"].isin(fold)].copy()
    if targets.empty:
        return {
            "trades": pd.DataFrame(columns=["sleeve_pnl"]),
            "metrics": {
                "payoff_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "trades": 0,
                "turnover": 0.0,
            },
        }
    trades, bars, daily = simulate_tianji_ledger(
        targets, rebalances, fold_market, cost
    )
    return {
        "trades": trades,
        "metrics": tianji_metrics(trades, bars, daily),
    }


def evaluate_development(segmented, quality, config):
    segmented = segmented[
        segmented["trade_time"] < FORBIDDEN_HOLDOUT_START
    ].copy()
    if segmented.empty:
        raise ResearchRejected("empty TianJi development market")
    scores = build_tianji_scores(segmented)
    if scores["decision_time"].ge(FORBIDDEN_HOLDOUT_START).any():
        raise ResearchRejected("viewed holdout entered development scores")
    folds = development_folds(scores["decision_time"].unique())
    atr = scores[["symbol", "decision_time", "atr"]].rename(
        columns={"decision_time": "trade_time"}
    )
    market = segmented.merge(
        atr, on=["symbol", "trade_time"], how="left", validate="one_to_one"
    )
    candidate_rows = []
    fold_rows = []
    for candidate in CANDIDATES:
        results = []
        for number, fold in enumerate(folds, start=1):
            result = _evaluate_fold(scores, market, candidate, fold, 5)
            results.append(result)
            fold_rows.append({
                "candidate": candidate,
                "fold": number,
                "cost_bps": 5,
                **result["metrics"],
            })
        combined = _combined_metrics(results)
        gate = development_gates(combined)
        fold_returns = [
            result["metrics"]["total_return"] for result in results
        ]
        candidate_rows.append({
            "candidate": candidate,
            "eligible": bool(
                gate["passed"] and all(value > 0.0 for value in fold_returns)
            ),
            "worst_payoff": min(
                result["metrics"]["payoff_ratio"] for result in results
            ),
            "worst_drawdown": max(
                result["metrics"]["max_drawdown"] for result in results
            ),
            **combined,
            "gates": gate,
        })
    candidate_frame = pd.DataFrame(candidate_rows)
    selected = select_development_candidate(candidate_frame)
    stress_rows = []
    if selected:
        for cost in (0, 2, 10, 15, 20):
            results = [
                _evaluate_fold(scores, market, selected, fold, cost)
                for fold in folds
            ]
            stress_rows.append({
                "cost_bps": cost,
                **_combined_metrics(results),
            })
    return {
        "status": development_status(selected),
        "selected_candidate": selected,
        "candidate_metrics": candidate_frame,
        "fold_metrics": pd.DataFrame(fold_rows),
        "stress_metrics": pd.DataFrame(stress_rows),
        "quality": quality,
        "forbidden_holdout_start": FORBIDDEN_HOLDOUT_START,
        "limitations": (
            "development-only weighted-index research",
            "viewed holdout excluded; not final OOS evidence",
        ),
    }
