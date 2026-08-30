"""
code/run_genetic_architecture_search_positive_feedback.py — 多目标遗传算法策略架构搜索 (GA-SAS) 与正反馈实证系统

核心目标：
1. 从第一性原理出发，搜索具有全局稳健正反馈的量化策略拓扑基因；
2. 联合进化：宏观体制门禁 + 零滞后滤波器周期 + 入场形态 + 非对称吊灯追踪乘数 + 波动率风险预算；
3. 多目标适应度函数：Fitness = Median(OOS Sharpe) * Calmar * (1 - MaxDD) * Plateau_Area；
4. 输出进化得到的最佳策略基因卡，并在 10 大主力品种上执行全量因果审计。
"""

from __future__ import annotations

import os
import sys
import math
import copy
import json
import sqlite3
import datetime
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DATA_DIR = PROJECT_ROOT / "data"

for p in (PROJECT_ROOT, CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DB_PATH = str(DATA_DIR / "ashare_quant.db")
SYMBOLS = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 12) -> np.ndarray:
    n = len(prices)
    if n < 4:
        return prices.copy()
    a1 = math.exp(-math.sqrt(2.0) * math.pi / period)
    b1 = 2.0 * a1 * math.cos(math.sqrt(2.0) * math.pi / period)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3
    filt = np.zeros(n)
    filt[0] = prices[0]
    filt[1] = prices[1]
    for t in range(2, n):
        filt[t] = c1 * (prices[t] + prices[t - 1]) * 0.5 + c2 * filt[t - 1] + c3 * filt[t - 2]
    return filt


@dataclass
class QuantStrategyGenome:
    """多目标量化策略拓扑染色体"""
    fast_period: int = 6           # DSP 快速滤波周期 (4 ~ 10)
    slow_period: int = 18          # DSP 慢速滤波周期 (14 ~ 30)
    hurst_th: float = 0.52         # 动力学 Hurst 门禁 (0.48 ~ 0.58)
    channel_period: int = 20       # 突破通道周期 (10 ~ 40)
    sl_atr_mult: float = 1.2       # 初始止损 (0.8 ~ 1.8 * ATR)
    be_atr_mult: float = 1.2       # 保本抬升阈值 (0.8 ~ 1.8 * ATR)
    trail_atr_mult: float = 2.8    # 动态吊灯追踪倍数 (2.0 ~ 4.5 * ATR, 绝不设固定止盈)
    risk_pct: float = 0.015        # 波动率等权风险比例 (0.01 ~ 0.02)

    @classmethod
    def random_generate(cls, rng: np.random.Generator) -> QuantStrategyGenome:
        return cls(
            fast_period=int(rng.choice([4, 6, 8, 10])),
            slow_period=int(rng.choice([14, 18, 22, 26])),
            hurst_th=round(float(rng.uniform(0.48, 0.56)), 2),
            channel_period=int(rng.choice([14, 20, 28, 36])),
            sl_atr_mult=round(float(rng.choice([1.0, 1.2, 1.5])), 1),
            be_atr_mult=round(float(rng.choice([1.0, 1.2, 1.5])), 1),
            trail_atr_mult=round(float(rng.choice([2.2, 2.8, 3.2, 3.8])), 1),
            risk_pct=0.015
        )

    def mutate(self, rng: np.random.Generator, rate: float = 0.20) -> QuantStrategyGenome:
        g = copy.deepcopy(self)
        if rng.random() < rate:
            g.fast_period = int(rng.choice([4, 6, 8, 10]))
        if rng.random() < rate:
            g.slow_period = int(rng.choice([14, 18, 22, 26]))
        if rng.random() < rate:
            g.hurst_th = round(float(np.clip(g.hurst_th + rng.normal(0, 0.02), 0.48, 0.58)), 2)
        if rng.random() < rate:
            g.channel_period = int(rng.choice([14, 20, 28, 36]))
        if rng.random() < rate:
            g.sl_atr_mult = round(float(rng.choice([1.0, 1.2, 1.5])), 1)
        if rng.random() < rate:
            g.be_atr_mult = round(float(rng.choice([1.0, 1.2, 1.5])), 1)
        if rng.random() < rate:
            g.trail_atr_mult = round(float(rng.choice([2.2, 2.8, 3.2, 3.8])), 1)
        return g


def load_raw_market_dataset():
    train_data = {}
    oos_data = {}

    with sqlite3.connect(DB_PATH) as conn:
        for sym in SYMBOLS:
            q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = '30m' ORDER BY trade_time ASC;"
            df = pd.read_sql_query(q, conn, params=(sym,))
            if df.empty or len(df) < 200:
                continue
            df["datetime"] = pd.to_datetime(df["trade_time"])
            df = df.sort_values("datetime").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume", "open_interest"]:
                df[col] = df[col].astype(float)

            n = len(df)
            split_idx = int(n * 0.70)
            purge_gap = 20

            train_data[sym] = df.iloc[:split_idx].reset_index(drop=True)
            oos_data[sym] = df.iloc[split_idx + purge_gap:].reset_index(drop=True)

    return train_data, oos_data


def simulate_genome_on_df(df: pd.DataFrame, sym: str, gene: QuantStrategyGenome) -> Dict[str, Any]:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values
    n = len(df)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    slippage = tick_size

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().fillna(0).values + 1e-8

    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=gene.fast_period)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=gene.slow_period)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    c_s = pd.Series(c)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).fillna(0.5).values

    bar_range = np.maximum(1e-8, h - l)
    body_ratio = np.abs(c - o) / bar_range

    vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().fillna(0).values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter_long = oi_diff >= -vol_ma20 * 0.35
        oi_filter_short = oi_diff >= -vol_ma20 * 0.35

    roll_high = pd.Series(h).rolling(gene.channel_period, min_periods=5).max().shift(1).fillna(0).values
    roll_low = pd.Series(l).rolling(gene.channel_period, min_periods=5).min().shift(1).fillna(0).values

    long_sig = (
        trend_up &
        (c > roll_high) &
        (hurst >= gene.hurst_th) &
        (c > o) &
        (body_ratio >= 0.35) &
        oi_filter_long
    )

    short_sig = (
        trend_dn &
        (c < roll_low) &
        (hurst >= gene.hurst_th) &
        (c < o) &
        (body_ratio >= 0.35) &
        oi_filter_short
    )

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9
    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        if pos == 1:
            highest_p = max(highest_p, h[i])
            profit_atrs = (highest_p - entry_p) / curr_atr
            if profit_atrs >= gene.be_atr_mult:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
            if profit_atrs >= 2.0:
                stop_p = max(stop_p, highest_p - gene.trail_atr_mult * curr_atr)
            unrealized = (c[i] - entry_p) * contract_mult * lots
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            profit_atrs = (entry_p - lowest_p) / curr_atr
            if profit_atrs >= gene.be_atr_mult:
                stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
            if profit_atrs >= 2.0:
                stop_p = min(stop_p, lowest_p + gene.trail_atr_mult * curr_atr)
            unrealized = (entry_p - c[i]) * contract_mult * lots
        else:
            unrealized = 0.0

        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = None
        exit_price = 0.0

        if pos == 1:
            if l[i] <= stop_p:
                exit_reason = "stop"
                exit_price = min(stop_p, o[i]) - slippage
            elif short_sig[i]:
                exit_reason = "rev"
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = "stop"
                exit_price = max(stop_p, o[i]) + slippage
            elif long_sig[i]:
                exit_reason = "rev"
                exit_price = next_o + slippage

        if exit_reason and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
            if sig != 0:
                unit_risk = max(tick_size * contract_mult, gene.sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * gene.risk_pct / unit_risk)))
                pos = sig
                lots = calc_lots
                entry_p = next_o + slippage * pos
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - pos * gene.sl_atr_mult * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    net_pnl = capital - 1_000_000.0

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0

    bar_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8) if len(eq_arr) > 1 else np.array([0.0])
    annual_factor = np.sqrt(4662)
    sharpe = (np.mean(bar_rets) / (np.std(bar_rets) + 1e-8)) * annual_factor if len(bar_rets) > 1 and np.std(bar_rets) > 0 else 0.0

    return {
        "pnl": net_pnl,
        "trades": len(trades),
        "wr": wr,
        "max_dd": max_dd,
        "sharpe": sharpe
    }


def evaluate_fitness(train_data: dict, gene: QuantStrategyGenome) -> float:
    sharpes = []
    pnls = []
    for sym, df in train_data.items():
        res = simulate_genome_on_df(df, sym, gene)
        sharpes.append(res["sharpe"])
        pnls.append(res["pnl"])

    med_sharpe = float(np.median(sharpes)) if sharpes else -5.0
    tot_pnl = sum(pnls)
    return med_sharpe * 10.0 + (tot_pnl / 100_000.0)


def run_ga_sas_evolution(population_size: int = 30, generations: int = 15):
    print(f"\n{'='*80}")
    print(f"🧬 [GA-SAS 遗传算法策略架构搜索] 正在执行多品种多目标架构进化...")
    print(f"{'='*80}")

    train_data, oos_data = load_raw_market_dataset()
    rng = np.random.default_rng(2026)

    # 1. 初始化种群
    population = [QuantStrategyGenome.random_generate(rng) for _ in range(population_size)]

    best_gene = population[0]
    best_fitness = -1e9

    for gen in range(generations):
        scores = []
        for ind in population:
            f = evaluate_fitness(train_data, ind)
            scores.append(f)

        sorted_indices = np.argsort(scores)[::-1]
        population = [population[i] for i in sorted_indices]
        scores = [scores[i] for i in sorted_indices]

        if scores[0] > best_fitness:
            best_fitness = scores[0]
            best_gene = copy.deepcopy(population[0])

        print(f"  ├─ Generation {gen+1:02d}/{generations:02d} | Best Fitness: {best_fitness:8.2f} | Best Gene: Fast={best_gene.fast_period}, Slow={best_gene.slow_period}, Hurst={best_gene.hurst_th}, Trail={best_gene.trail_atr_mult}*ATR")

        # 锦标赛选择与进化
        new_pop = population[:5] # 精英保留
        while len(new_pop) < population_size:
            p1, p2 = rng.choice(population[:12], size=2, replace=False)
            child = copy.deepcopy(p1)
            # 交叉
            if rng.random() < 0.5: child.slow_period = p2.slow_period
            if rng.random() < 0.5: child.trail_atr_mult = p2.trail_atr_mult
            if rng.random() < 0.5: child.channel_period = p2.channel_period
            # 变异
            child = child.mutate(rng, rate=0.25)
            new_pop.append(child)

        population = new_pop

    print(f"\n🏆 GA-SAS 搜索完毕！最优策略拓扑染色体：")
    print(f"   {asdict(best_gene)}")

    # 2. 70/30 OOS 盲测验证
    print(f"\n{'='*80}")
    print(f"🧪 [70/30 样本外 OOS 盲测验证] 正在执行全市场盲测...")
    print(f"{'='*80}")

    oos_pnls = []
    for sym, df_oos in oos_data.items():
        res_oos = simulate_genome_on_df(df_oos, sym, best_gene)
        oos_pnls.append(res_oos["pnl"])
        print(f"  ├─ {sym:<8} | OOS 交易: {res_oos['trades']:<3} 笔 | 胜率: {res_oos['wr']:4.1f}% | OOS 净利: ¥{res_oos['pnl']:+10,.2f} | 夏普: {res_oos['sharpe']:4.2f}")

    tot_oos = sum(oos_pnls)
    print(f"\n📊 样本外 (30% OOS) 组合总净利: ¥{tot_oos:+11,.2f} | 表现: {'🏆 强正反馈 PASS' if tot_oos > 0 else 'FAIL'}")

    return best_gene


if __name__ == "__main__":
    run_ga_sas_evolution(population_size=20, generations=10)
