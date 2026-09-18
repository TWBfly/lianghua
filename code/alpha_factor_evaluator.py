"""
Alpha Factor Multi-Dimensional Evaluation & Analysis Engine.
Provides comprehensive metrics for factor quality:
1. Information Coefficient: Pearson IC, Spearman Rank IC, Rank ICIR, t-stat, Win Rate.
2. Quantile Analysis: Monotonicity, Group Returns (Q1..QN), Long-Short Spread, Long-Short Sharpe.
3. Factor Stability & Decay: IC Decay across horizons (1d, 3d, 5d, 10d, 20d), 1-day Rank Autocorrelation.
4. Factor Correlation Matrix & Redundancy Analysis.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Any

import numpy as np
import pandas as pd
from scipy import stats

CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from alpha_factor_miner import FactorRegistry, compute_factors_for_panel
from qlib_ashare_adapter import load_ashare_dataset


@dataclass
class FactorEvaluationResult:
    factor_name: str
    mean_ic: float
    mean_rank_ic: float
    rank_icir: float
    ic_positive_ratio: float
    t_stat: float
    p_value: float
    rank_autocorr_1d: float
    monotonicity_score: float
    long_short_annual_return: float
    long_short_sharpe: float
    quantile_returns: Dict[str, float]
    ic_decay: Dict[int, float]
    evaluated_days: int


def calculate_factor_ic_series(
    df: pd.DataFrame,
    factor_col: str,
    label_col: str = "label",
    date_col: str = "trade_date",
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate daily cross-sectional Pearson IC and Spearman Rank IC time series.
    """
    dates = []
    ic_values = []
    rank_ic_values = []

    for date, group in df.groupby(date_col):
        valid = group[[factor_col, label_col]].dropna()
        if len(valid) < 10:
            continue
        ic = valid[factor_col].corr(valid[label_col], method="pearson")
        rank_ic = valid[factor_col].corr(valid[label_col], method="spearman")
        if pd.notna(ic) and pd.notna(rank_ic):
            dates.append(date)
            ic_values.append(ic)
            rank_ic_values.append(rank_ic)

    ic_s = pd.Series(ic_values, index=pd.to_datetime(dates), name=f"{factor_col}_ic")
    rank_ic_s = pd.Series(rank_ic_values, index=pd.to_datetime(dates), name=f"{factor_col}_rank_ic")
    return ic_s, rank_ic_s


def _newey_west_t(series: np.ndarray, max_lag: int = 5) -> Tuple[float, float]:
    """Newey-West HAC adjusted t-statistic for mean != 0."""
    n = len(series)
    if n < 3:
        return 0.0, 1.0
    mean = np.mean(series)
    centered = series - mean
    gamma_0 = float(np.var(series, ddof=1))
    nw_var = gamma_0
    for j in range(1, min(max_lag + 1, n)):
        w = 1.0 - j / (max_lag + 1)
        gamma_j = float(np.mean(centered[j:] * centered[:-j]))
        nw_var += 2 * w * gamma_j
    nw_var = max(nw_var, 1e-16)
    se = np.sqrt(nw_var / n)
    t = mean / se
    p = float(2 * (1 - stats.t.cdf(abs(t), df=n - 1)))
    return float(t), p


def evaluate_single_factor(
    df: pd.DataFrame,
    factor_col: str,
    label_col: str = "label",
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    quantiles: int = 5,
    decay_horizons: Sequence[int] = (1, 2, 3, 5, 10, 20),
    holding_period: int = 1,
) -> FactorEvaluationResult:
    """
    Perform deep evaluation on a single factor.
    """
    df_clean = df.dropna(subset=[factor_col, label_col]).copy()
    if df_clean.empty:
        raise ValueError(f"No valid data for factor '{factor_col}' and label '{label_col}'")

    # 1. IC and Rank IC analysis
    ic_s, rank_ic_s = calculate_factor_ic_series(df_clean, factor_col, label_col, date_col)
    n_days = len(rank_ic_s)
    if n_days < 5:
        raise ValueError(f"Insufficient trading days ({n_days}) for factor evaluation")

    mean_ic = float(ic_s.mean())
    mean_rank_ic = float(rank_ic_s.mean())
    std_rank_ic = float(rank_ic_s.std(ddof=1)) if n_days > 1 else 1.0
    rank_icir = (mean_rank_ic / std_rank_ic) * math.sqrt(252) if std_rank_ic > 0 else 0.0
    ic_pos_ratio = float((rank_ic_s > 0).mean())

    # t-statistic and p-value for Rank IC != 0
    t_stat, p_value = _newey_west_t(rank_ic_s.to_numpy(), max_lag=max(1, holding_period)) if n_days > 2 else (0.0, 1.0)
    t_stat = float(t_stat) if pd.notna(t_stat) else 0.0
    p_value = float(p_value) if pd.notna(p_value) else 1.0

    # 2. Factor stability / 1-day Rank Autocorrelation
    daily_autocorr = []
    prev_ranks = None
    prev_date = None
    for date, group in df_clean.groupby(date_col):
        curr_ranks = group.set_index(symbol_col)[factor_col].rank()
        if prev_ranks is not None and prev_date is not None:
            common = curr_ranks.index.intersection(prev_ranks.index)
            if len(common) >= 10:
                corr = curr_ranks.loc[common].corr(prev_ranks.loc[common], method="spearman")
                if pd.notna(corr):
                    daily_autocorr.append(corr)
        prev_ranks = curr_ranks
        prev_date = date
    rank_autocorr_1d = float(np.mean(daily_autocorr)) if daily_autocorr else 0.0

    # 3. Quantile / Layering Monotonicity Analysis
    # Assign cross-sectional quantile each day
    def _assign_quantile(series: pd.Series) -> pd.Series:
        if len(series) < quantiles:
            return pd.Series(np.nan, index=series.index)
        return pd.qcut(series.rank(method="first"), q=quantiles, labels=[f"Q{i+1}" for i in range(quantiles)])

    df_clean["quantile"] = df_clean.groupby(date_col)[factor_col].transform(_assign_quantile)
    
    # Calculate average daily return for each quantile group
    group_daily = df_clean.groupby([date_col, "quantile"], observed=False)[label_col].mean().unstack("quantile")
    group_means = group_daily.mean()
    quantile_returns = {str(col): float(group_means[col]) for col in group_means.index if pd.notna(col)}

    # Monotonicity score: Spearman correlation between quantile rank (1..N) and mean return
    q_ranks = np.arange(1, len(quantile_returns) + 1)
    q_vals = [quantile_returns.get(f"Q{i}", 0.0) for i in q_ranks]
    mono_score, _ = stats.spearmanr(q_ranks, q_vals)
    monotonicity_score = float(mono_score) if pd.notna(mono_score) else 0.0

    # Long-Short spread (Top Quantile - Bottom Quantile)
    top_q = f"Q{quantiles}"
    bot_q = "Q1"
    annual_periods = 252.0 / holding_period
    if top_q in group_daily.columns and bot_q in group_daily.columns:
        ls_daily = (group_daily[top_q] - group_daily[bot_q]).dropna()
        ls_annual_ret = float(ls_daily.mean() * annual_periods)
        ls_std = float(ls_daily.std(ddof=1))
        ls_sharpe = float((ls_daily.mean() / ls_std) * math.sqrt(annual_periods)) if ls_std > 0 else 0.0
    else:
        ls_annual_ret = 0.0
        ls_sharpe = 0.0

    # 4. IC Decay across different forward horizons
    ic_decay = {}
    prices = df.pivot(index=date_col, columns=symbol_col, values="close")
    factor_panel = df.pivot(index=date_col, columns=symbol_col, values=factor_col)
    
    for lag in decay_horizons:
        fwd_ret = (prices.shift(-lag) / prices - 1.0)
        daily_decay_ic = []
        for d in factor_panel.index:
            if d in fwd_ret.index:
                f_row = factor_panel.loc[d].dropna()
                r_row = fwd_ret.loc[d].dropna()
                common = f_row.index.intersection(r_row.index)
                if len(common) >= 10:
                    c = f_row.loc[common].corr(r_row.loc[common], method="spearman")
                    if pd.notna(c):
                        daily_decay_ic.append(c)
        ic_decay[lag] = float(np.mean(daily_decay_ic)) if daily_decay_ic else 0.0

    return FactorEvaluationResult(
        factor_name=factor_col,
        mean_ic=mean_ic,
        mean_rank_ic=mean_rank_ic,
        rank_icir=rank_icir,
        ic_positive_ratio=ic_pos_ratio,
        t_stat=t_stat,
        p_value=p_value,
        rank_autocorr_1d=rank_autocorr_1d,
        monotonicity_score=monotonicity_score,
        long_short_annual_return=ls_annual_ret,
        long_short_sharpe=ls_sharpe,
        quantile_returns=quantile_returns,
        ic_decay=ic_decay,
        evaluated_days=n_days,
    )


def evaluate_factor_pool(
    df: pd.DataFrame,
    factor_cols: Sequence[str],
    label_col: str = "label",
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    quantiles: int = 5,
    holding_period: int = 1,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Evaluate multiple alpha factors and produce a ranked Leaderboard and Correlation Matrix.
    """
    records = []
    for factor in factor_cols:
        try:
            res = evaluate_single_factor(
                df=df,
                factor_col=factor,
                label_col=label_col,
                date_col=date_col,
                symbol_col=symbol_col,
                quantiles=quantiles,
                holding_period=holding_period,
            )
            records.append({
                "factor": res.factor_name,
                "mean_rank_ic": res.mean_rank_ic,
                "rank_icir": res.rank_icir,
                "mean_ic": res.mean_ic,
                "ic_pos_pct": res.ic_positive_ratio * 100,
                "t_stat": res.t_stat,
                "p_val": res.p_value,
                "autocorr_1d": res.rank_autocorr_1d,
                "monotonicity": res.monotonicity_score,
                "ls_annual_ret_pct": res.long_short_annual_return * 100,
                "ls_sharpe": res.long_short_sharpe,
            })
        except Exception as err:
            print(f"[Warning] Failed to evaluate factor '{factor}': {err}")

    leaderboard = pd.DataFrame(records)
    if not leaderboard.empty:
        leaderboard["abs_icir"] = leaderboard["rank_icir"].abs()
        leaderboard = leaderboard.sort_values("abs_icir", ascending=False).drop(columns=["abs_icir"]).reset_index(drop=True)

    if not leaderboard.empty and "p_val" in leaderboard.columns:
        p_vals = leaderboard["p_val"].values.copy()
        m = len(p_vals)
        sorted_idx = np.argsort(p_vals)
        q_vals = np.empty(m)
        for rank_i, orig_i in enumerate(sorted_idx):
            q_vals[orig_i] = min(1.0, p_vals[orig_i] * m / (rank_i + 1))
        # Enforce monotonicity
        for rank_i in range(m - 2, -1, -1):
            orig_i = sorted_idx[rank_i]
            next_i = sorted_idx[rank_i + 1]
            q_vals[orig_i] = min(q_vals[orig_i], q_vals[next_i])
        leaderboard["q_val_bh"] = q_vals

    # Compute Factor Correlation Matrix (Spearman rank correlation across pooled observations)
    valid_factors = [f for f in factor_cols if f in df.columns]
    # ponytail: daily cross-sectional correlation mean avoids Simpson's paradox from pooling
    daily_corrs = []
    for _, grp in df.groupby(date_col):
        if len(grp) >= 10 and len(valid_factors) > 1:
            daily_corrs.append(grp[valid_factors].corr(method="spearman"))
    if daily_corrs:
        factor_corr = pd.concat(daily_corrs).groupby(level=0).mean().reindex(index=valid_factors, columns=valid_factors)
    else:
        factor_corr = df[valid_factors].corr(method="spearman")

    return leaderboard, factor_corr


def print_factor_evaluation_report(result: FactorEvaluationResult):
    """Print formatted single factor analysis report to terminal."""
    print("=" * 65)
    print(f"       ALPHA FACTOR EVALUATION REPORT: {result.factor_name.upper()}")
    print("=" * 65)
    print("1. Cross-Sectional Information Coefficient (IC):")
    print(f"   ├─ Mean Pearson IC:        {result.mean_ic:>10.4f}")
    print(f"   ├─ Mean Rank IC (Spearman): {result.mean_rank_ic:>10.4f}")
    print(f"   ├─ Rank ICIR (Annualized): {result.rank_icir:>10.4f}")
    print(f"   ├─ Rank IC > 0 Win Rate:   {result.ic_positive_ratio * 100:>9.2f} %")
    print(f"   ├─ t-statistic (p-value):  {result.t_stat:>10.2f} (p={result.p_value:.3e})")
    print(f"   └─ Evaluated Days:         {result.evaluated_days:>10} trading days")

    print("\n2. Quantile Layering & Monotonicity:")
    print(f"   ├─ Monotonicity Score:     {result.monotonicity_score:>10.4f} (-1.0 ~ +1.0)")
    print(f"   ├─ Long-Short Ann. Return: {result.long_short_annual_return * 100:>9.2f} %")
    print(f"   ├─ Long-Short Sharpe:      {result.long_short_sharpe:>10.2f}")
    print("   └─ Quantile Mean Returns:")
    for q_name, q_val in sorted(result.quantile_returns.items()):
        print(f"        {q_name}: {q_val * 100:>+7.3f}%")

    print("\n3. Stability & IC Decay Across Horizons:")
    print(f"   ├─ 1-Day Rank Autocorr:    {result.rank_autocorr_1d:>10.4f} (Factor Stability)")
    print("   └─ Multi-Horizon Rank IC:")
    for lag, ic_val in sorted(result.ic_decay.items()):
        print(f"        T+{lag:>2} Day IC: {ic_val:>+10.4f}")
    print("=" * 65)


def run_alpha_factor_suite(
    db_path: Path | str = PROJECT_ROOT / "data" / "ashare_quant.db",
    target_factor: Optional[str] = None,
    quantiles: int = 5,
    top_n: int = 15,
):
    print("=" * 70)
    print("           ALPHA FACTOR MINING & EVALUATION ENGINE")
    print("=" * 70)

    # 1. Load dataset via adapter
    print(f"\n[1/3] Loading verified A-share dataset from {Path(db_path).name}...")
    dataset = load_ashare_dataset(db_path=db_path, train_ratio=0.60, valid_ratio=0.20)
    
    # F01: 因子排行榜严格在开发/训练集上挖掘与排序，禁止把测试集拼接进来 (防止测试集泄漏)
    dev_df = dataset.train_df.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    test_df = dataset.test_df.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    
    # 2. Compute registered factors if missing
    available_factors = FactorRegistry.list_factors()
    print(f"[2/3] Checking factor pool ({len(available_factors)} factors registered)...")
    computed_dev_df = compute_factors_for_panel(dev_df, factor_names=available_factors)

    # 3. Evaluation
    print("[3/3] Running multi-dimensional factor quality evaluation on DEV set...\n")
    if target_factor:
        if target_factor not in computed_dev_df.columns:
            raise ValueError(f"Factor '{target_factor}' not found in computed features")
        res = evaluate_single_factor(computed_dev_df, factor_col=target_factor, quantiles=quantiles, holding_period=5)
        print_factor_evaluation_report(res)
    else:
        # Batch evaluate all factors on Dev set and print Leaderboard
        factor_cols = [f for f in available_factors if f in computed_dev_df.columns]
        leaderboard, corr_matrix = evaluate_factor_pool(computed_dev_df, factor_cols=factor_cols, quantiles=quantiles, holding_period=5)

        print("=" * 70)
        print(f"            ALPHA FACTOR DEV LEADERBOARD (Train Split, Top {top_n})")
        print("=" * 70)
        display_cols = ["factor", "mean_rank_ic", "rank_icir", "ic_pos_pct", "monotonicity", "ls_sharpe"]
        print(leaderboard[display_cols].head(top_n).to_string(index=False, justify="right", formatters={
            "mean_rank_ic": "{:+0.4f}".format,
            "rank_icir": "{:+0.2f}".format,
            "ic_pos_pct": "{:0.1f}%".format,
            "monotonicity": "{:+0.2f}".format,
            "ls_sharpe": "{:+0.2f}".format,
        }))
        print("=" * 70)

        # 独立进行测试集 (OOS) 盲测验证
        if not test_df.empty and not leaderboard.empty:
            print("\n" + "=" * 70)
            print(f"            ALPHA FACTOR OUT-OF-SAMPLE (OOS Test Split) AUDIT")
            print("=" * 70)
            computed_test_df = compute_factors_for_panel(test_df, factor_names=available_factors)
            top_factors = [f for f in leaderboard["factor"].head(5).tolist() if f in computed_test_df.columns]
            if top_factors:
                oos_leaderboard, _ = evaluate_factor_pool(computed_test_df, factor_cols=top_factors, quantiles=quantiles, holding_period=5)
                print(oos_leaderboard[display_cols].to_string(index=False, justify="right", formatters={
                    "mean_rank_ic": "{:+0.4f}".format,
                    "rank_icir": "{:+0.2f}".format,
                    "ic_pos_pct": "{:0.1f}%".format,
                    "monotonicity": "{:+0.2f}".format,
                    "ls_sharpe": "{:+0.2f}".format,
                }))
                print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alpha Factor Evaluation Suite")
    parser.add_argument("--factor", type=str, default=None, help="Target factor name to evaluate in detail")
    parser.add_argument("--quantiles", type=int, default=5, help="Number of quantile groups (default: 5)")
    parser.add_argument("--top", type=int, default=15, help="Number of top factors to display in leaderboard")
    args = parser.parse_args()

    run_alpha_factor_suite(target_factor=args.factor, quantiles=args.quantiles, top_n=args.top)
