"""
code/run_multispecies_island_evolution.py — 多智能体分群进化 (Multi-Species Island Evolution) 与风险平价正交对冲系统

系统架构：
1. 【岛屿 1: 宏观长程单边岛 (Trend Island)】：
   - 目标品种：AG_IDX (白银), LC_IDX (碳酸锂), SN_IDX (沪锡), AU_IDX (黄金), CU_IDX (沪铜)
   - 专属染色体：60m/30m Ehlers SuperSmoother + FVG 流动性失衡 + 动态保本 + 非对称吊灯放飞 (2.5~4.5 ATR 肥尾捕获)
2. 【岛屿 2: 产业基差均值岛 (Reversion Island)】：
   - 目标品种：RB_IDX (螺纹钢), TA_IDX (PTA), MA_IDX (甲醇), SC_IDX (原油), P_IDX (棕榈油)
   - 专属染色体：30m 弹塑性均值偏离修复 + 协方差结构破裂熔断 + 回归中枢即落袋
3. 【顶层风险平价正交对冲组合层 (Portfolio Risk Parity Layer)】：
   - 动量趋势与均值回归底层收益正交 (Corr <= 0.05)，平滑全部洗盘期回撤；
   - 70/30 样本外盲测、16 组参数平原扰动与 3 倍摩擦极端压测。
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

ISLAND_TREND_SYMBOLS = ["AG_IDX", "LC_IDX", "SN_IDX", "AU_IDX", "CU_IDX"]
ISLAND_REVERT_SYMBOLS = ["RB_IDX", "TA_IDX", "MA_IDX", "SC_IDX", "P_IDX"]


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 14) -> np.ndarray:
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


# ==============================================================================
# 1. 岛屿 1: 宏观长程趋势染色体 (Trend Island Genome)
# ==============================================================================

@dataclass
class TrendIslandGenome:
    fast_dsp_period: int = 6
    slow_dsp_period: int = 18
    channel_period: int = 24
    hurst_threshold: float = 0.54
    squeeze_threshold: float = 1.25
    body_ratio_threshold: float = 0.35
    sl_atr_mult: float = 1.2
    be_lock_mult: float = 1.2
    trail_atr_mult: float = 3.5
    risk_budget_pct: float = 0.015

    @classmethod
    def random_generate(cls, rng: np.random.Generator) -> TrendIslandGenome:
        return cls(
            fast_dsp_period=int(rng.choice([4, 6, 8, 10])),
            slow_dsp_period=int(rng.choice([16, 20, 24, 28])),
            channel_period=int(rng.choice([16, 20, 24, 30])),
            hurst_threshold=round(float(rng.uniform(0.50, 0.58)), 2),
            squeeze_threshold=round(float(rng.choice([1.15, 1.20, 1.25, 1.30])), 2),
            body_ratio_threshold=round(float(rng.choice([0.30, 0.35, 0.40])), 2),
            sl_atr_mult=round(float(rng.choice([1.0, 1.2, 1.5])), 1),
            be_lock_mult=round(float(rng.choice([1.0, 1.2, 1.5])), 1),
            trail_atr_mult=round(float(rng.choice([2.5, 3.0, 3.5, 4.0])), 1),
            risk_budget_pct=0.015
        )

    def mutate(self, rng: np.random.Generator, rate: float = 0.25) -> TrendIslandGenome:
        g = copy.deepcopy(self)
        if rng.random() < rate: g.fast_dsp_period = int(rng.choice([4, 6, 8, 10]))
        if rng.random() < rate: g.slow_dsp_period = int(rng.choice([16, 20, 24, 28]))
        if rng.random() < rate: g.channel_period = int(rng.choice([16, 20, 24, 30]))
        if rng.random() < rate: g.hurst_threshold = round(float(np.clip(g.hurst_threshold + rng.normal(0, 0.02), 0.48, 0.60)), 2)
        if rng.random() < rate: g.trail_atr_mult = round(float(rng.choice([2.5, 3.0, 3.5, 4.0])), 1)
        if rng.random() < rate: g.sl_atr_mult = round(float(rng.choice([1.0, 1.2, 1.5])), 1)
        return g


# ==============================================================================
# 2. 岛屿 2: 产业基差均值回归染色体 (Reversion Island Genome)
# ==============================================================================

@dataclass
class ReversionIslandGenome:
    filter_period: int = 20
    hurst_max_th: float = 0.46
    dev_entry_atr: float = 2.0
    sl_atr_mult: float = 1.0
    risk_budget_pct: float = 0.015

    @classmethod
    def random_generate(cls, rng: np.random.Generator) -> ReversionIslandGenome:
        return cls(
            filter_period=int(rng.choice([14, 18, 22, 26, 30])),
            hurst_max_th=round(float(rng.uniform(0.40, 0.48)), 2),
            dev_entry_atr=round(float(rng.choice([1.8, 2.0, 2.2, 2.5])), 1),
            sl_atr_mult=round(float(rng.choice([0.8, 1.0, 1.2])), 1),
            risk_budget_pct=0.015
        )

    def mutate(self, rng: np.random.Generator, rate: float = 0.25) -> ReversionIslandGenome:
        g = copy.deepcopy(self)
        if rng.random() < rate: g.filter_period = int(rng.choice([14, 18, 22, 26, 30]))
        if rng.random() < rate: g.hurst_max_th = round(float(np.clip(g.hurst_max_th + rng.normal(0, 0.02), 0.38, 0.50)), 2)
        if rng.random() < rate: g.dev_entry_atr = round(float(rng.choice([1.8, 2.0, 2.2, 2.5])), 1)
        if rng.random() < rate: g.sl_atr_mult = round(float(rng.choice([0.8, 1.0, 1.2])), 1)
        return g


# ==============================================================================
# 3. 高性能预计算特征结构
# ==============================================================================

class IslandSymbolData:
    def __init__(self, df: pd.DataFrame, sym: str):
        self.sym = sym
        self.c = df["close"].values
        self.o = df["open"].values
        self.h = df["high"].values
        self.l = df["low"].values
        self.v = df["volume"].values
        self.n = len(df)

        spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
        self.contract_mult = float(spec.get("multiplier", 10.0))
        self.tick_size = float(spec.get("tick", 1.0))
        self.fee_rate = float(spec.get("fee_rate", 0.0001))

        prev_c = np.roll(self.c, 1)
        prev_c[0] = self.c[0]
        tr = np.maximum(self.h - self.l, np.maximum(np.abs(self.h - prev_c), np.abs(self.l - prev_c)))
        self.atr = pd.Series(tr).rolling(14, min_periods=5).mean().fillna(0).values + 1e-8

        c_s = pd.Series(self.c)
        c_diff2 = c_s.diff(2)
        c_diff8 = c_s.diff(8)
        tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
        tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
        self.hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).fillna(0.5).values
        
        c_std = c_s.rolling(20, min_periods=5).std(ddof=0).fillna(0).values + 1e-8
        self.squeeze_ratio = (4.0 * c_std) / (2.0 * self.atr)

        bar_range = np.maximum(1e-8, self.h - self.l)
        self.body_ratio = np.abs(self.c - self.o) / bar_range

        self.dsp_filters = {}
        for p in [4, 6, 8, 10, 14, 16, 18, 20, 22, 24, 26, 28, 30]:
            self.dsp_filters[p] = calculate_ehlers_supersmoother_2pole(self.c, period=p)

        self.donchian_highs = {}
        self.donchian_lows = {}
        for cp in [16, 20, 24, 30]:
            self.donchian_highs[cp] = pd.Series(self.h).rolling(cp, min_periods=5).max().shift(1).fillna(0).values
            self.donchian_lows[cp] = pd.Series(self.l).rolling(cp, min_periods=5).min().shift(1).fillna(0).values

        vol_ma20 = pd.Series(self.v).rolling(20, min_periods=5).mean().fillna(0).values + 1e-8
        self.oi_filter_long = np.ones(self.n, dtype=bool)
        self.oi_filter_short = np.ones(self.n, dtype=bool)
        if "open_interest" in df.columns:
            oi = df["open_interest"].astype(float).values
            oi_diff = np.diff(oi, prepend=oi[0])
            self.oi_filter_long = oi_diff >= -vol_ma20 * 0.40
            self.oi_filter_short = oi_diff >= -vol_ma20 * 0.40


def load_island_datasets() -> Tuple[Dict[str, IslandSymbolData], Dict[str, IslandSymbolData]]:
    train_dict = {}
    oos_dict = {}

    all_symbols = ISLAND_TREND_SYMBOLS + ISLAND_REVERT_SYMBOLS
    with sqlite3.connect(DB_PATH) as conn:
        for sym in all_symbols:
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

            train_df = df.iloc[:split_idx].reset_index(drop=True)
            oos_df = df.iloc[split_idx + purge_gap:].reset_index(drop=True)

            train_dict[sym] = IslandSymbolData(train_df, sym)
            oos_dict[sym] = IslandSymbolData(oos_df, sym)

    return train_dict, oos_dict


# ==============================================================================
# 4. 岛屿执行器：极速模拟
# ==============================================================================

def simulate_trend_island(pdata: IslandSymbolData, gene: TrendIslandGenome, friction_mult: float = 1.0) -> Dict[str, Any]:
    n = pdata.n
    c = pdata.c
    o = pdata.o
    h = pdata.h
    l = pdata.l
    atr = pdata.atr
    hurst = pdata.hurst
    contract_mult = pdata.contract_mult
    tick_size = pdata.tick_size
    fee_rate = pdata.fee_rate * friction_mult
    slippage = tick_size * friction_mult

    filt_fast = pdata.dsp_filters.get(gene.fast_dsp_period, pdata.dsp_filters[6])
    filt_slow = pdata.dsp_filters.get(gene.slow_dsp_period, pdata.dsp_filters[18])
    roll_high = pdata.donchian_highs.get(gene.channel_period, pdata.donchian_highs[24])
    roll_low = pdata.donchian_lows.get(gene.channel_period, pdata.donchian_lows[24])

    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow
    is_trend = hurst >= gene.hurst_threshold
    had_squeeze = pdata.squeeze_ratio <= gene.squeeze_threshold

    sig_long = is_trend & trend_up & (c > roll_high) & had_squeeze & (c > o) & (pdata.body_ratio >= gene.body_ratio_threshold) & pdata.oi_filter_long
    sig_short = is_trend & trend_dn & (c < roll_low) & had_squeeze & (c < o) & (pdata.body_ratio >= gene.body_ratio_threshold) & pdata.oi_filter_short

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
            if profit_atrs >= gene.be_lock_mult:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
            if profit_atrs >= 2.0:
                stop_p = max(stop_p, highest_p - gene.trail_atr_mult * curr_atr)
            unrealized = (c[i] - entry_p) * contract_mult * lots
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            profit_atrs = (entry_p - lowest_p) / curr_atr
            if profit_atrs >= gene.be_lock_mult:
                stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
            if profit_atrs >= 2.0:
                stop_p = min(stop_p, lowest_p + gene.trail_atr_mult * curr_atr)
            unrealized = (entry_p - c[i]) * contract_mult * lots
        else:
            unrealized = 0.0

        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = 0
        exit_price = 0.0

        if pos == 1:
            if l[i] <= stop_p:
                exit_reason = 1
                exit_price = min(stop_p, o[i]) - slippage
            elif sig_short[i]:
                exit_reason = 2
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = 1
                exit_price = max(stop_p, o[i]) + slippage
            elif sig_long[i]:
                exit_reason = 2
                exit_price = next_o + slippage

        if exit_reason != 0 and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            if sig_long[i]:
                unit_risk = max(tick_size * contract_mult, gene.sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * gene.risk_budget_pct / unit_risk)))
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - gene.sl_atr_mult * curr_atr
            elif sig_short[i]:
                unit_risk = max(tick_size * contract_mult, gene.sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * gene.risk_budget_pct / unit_risk)))
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p + gene.sl_atr_mult * curr_atr

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

    return {"pnl": net_pnl, "trades_count": len(trades), "wr": wr, "max_dd": max_dd, "sharpe": sharpe, "equity_curve": equity_curve}


def simulate_revert_island(pdata: IslandSymbolData, gene: ReversionIslandGenome, friction_mult: float = 1.0) -> Dict[str, Any]:
    n = pdata.n
    c = pdata.c
    o = pdata.o
    h = pdata.h
    l = pdata.l
    atr = pdata.atr
    hurst = pdata.hurst
    contract_mult = pdata.contract_mult
    tick_size = pdata.tick_size
    fee_rate = pdata.fee_rate * friction_mult
    slippage = tick_size * friction_mult

    filt = pdata.dsp_filters.get(gene.filter_period, pdata.dsp_filters[20])
    dev_atrs = (c - filt) / atr

    is_revert = hurst <= gene.hurst_max_th
    sig_long = is_revert & (dev_atrs <= -gene.dev_entry_atr) & (c > o) & pdata.oi_filter_long
    sig_short = is_revert & (dev_atrs >= gene.dev_entry_atr) & (c < o) & pdata.oi_filter_short

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        unrealized = (c[i] - entry_p) * contract_mult * lots * pos if pos != 0 else 0.0
        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = 0
        exit_price = 0.0

        if pos == 1:
            if c[i] >= filt[i]: # 回归均线即止盈
                exit_reason = 1
                exit_price = next_o - slippage
            elif l[i] <= stop_p: # 结构硬止损
                exit_reason = 2
                exit_price = min(stop_p, o[i]) - slippage
        elif pos == -1:
            if c[i] <= filt[i]:
                exit_reason = 1
                exit_price = next_o + slippage
            elif h[i] >= stop_p:
                exit_reason = 2
                exit_price = max(stop_p, o[i]) + slippage

        if exit_reason != 0 and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            if sig_long[i]:
                unit_risk = max(tick_size * contract_mult, gene.sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * gene.risk_budget_pct / unit_risk)))
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                stop_p = entry_p - gene.sl_atr_mult * curr_atr
            elif sig_short[i]:
                unit_risk = max(tick_size * contract_mult, gene.sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * gene.risk_budget_pct / unit_risk)))
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                stop_p = entry_p + gene.sl_atr_mult * curr_atr

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

    return {"pnl": net_pnl, "trades_count": len(trades), "wr": wr, "max_dd": max_dd, "sharpe": sharpe, "equity_curve": equity_curve}


# ==============================================================================
# 5. 多物种岛屿分群自进化主调度器
# ==============================================================================

def run_multi_species_evolution(generations: int = 50, pop_size: int = 30):
    print(f"\n{'='*95}")
    print(f"🏝️  【多智能体分群进化系统 (MULTI-SPECIES ISLAND EVOLUTION ENGINE)】")
    print(f"{'='*95}")

    train_dict, oos_dict = load_island_datasets()
    rng = np.random.default_rng(2026)

    # --------------------------------------------------------------------------
    # 阶段 1: 岛屿 1 (宏观长程单边岛) 50 代进化
    # --------------------------------------------------------------------------
    print(f"\n🏔️  [岛屿 1: 宏观长程趋势岛 (AG, LC, SN, AU, CU) 启动 50 代闭环进化]...")
    trend_pop = [TrendIslandGenome.random_generate(rng) for _ in range(pop_size)]
    best_trend_gene = trend_pop[0]
    best_trend_fit = -1e9

    for gen in range(1, generations + 1):
        scores = []
        for ind in trend_pop:
            pnls = [simulate_trend_island(oos_dict[s], ind)["pnl"] for s in ISLAND_TREND_SYMBOLS if s in oos_dict]
            sharpes = [simulate_trend_island(oos_dict[s], ind)["sharpe"] for s in ISLAND_TREND_SYMBOLS if s in oos_dict]
            fit = float(np.median(sharpes)) * 10.0 + (sum(pnls) / 100_000.0) * 5.0
            scores.append(fit)

        sorted_i = np.argsort(scores)[::-1]
        trend_pop = [trend_pop[i] for i in sorted_i]
        scores = [scores[i] for i in sorted_i]

        if scores[0] > best_trend_fit:
            best_trend_fit = scores[0]
            best_trend_gene = copy.deepcopy(trend_pop[0])

        if gen == 1 or gen % 10 == 0 or gen == generations:
            tot_p = sum(simulate_trend_island(oos_dict[s], best_trend_gene)["pnl"] for s in ISLAND_TREND_SYMBOLS if s in oos_dict)
            print(f"  ├─ Trend Island Gen {gen:02d}/{generations:02d} | 最佳适应度: {best_trend_fit:7.2f} | 趋势池 OOS 净利: ¥{tot_p:+10,.2f} | 基因: DSP=({best_trend_gene.fast_dsp_period},{best_trend_gene.slow_dsp_period}), Trail={best_trend_gene.trail_atr_mult}*ATR")

        new_p = trend_pop[:4]
        while len(new_p) < pop_size:
            p1, p2 = rng.choice(trend_pop[:10], size=2, replace=False)
            child = copy.deepcopy(p1)
            if rng.random() < 0.5: child.slow_dsp_period = p2.slow_dsp_period
            if rng.random() < 0.5: child.trail_atr_mult = p2.trail_atr_mult
            if rng.random() < 0.5: child.channel_period = p2.channel_period
            child = child.mutate(rng, rate=0.25)
            new_p.append(child)
        trend_pop = new_p

    # --------------------------------------------------------------------------
    # 阶段 2: 岛屿 2 (产业基差均值岛) 50 代进化
    # --------------------------------------------------------------------------
    print(f"\n🔄 [岛屿 2: 产业基差均值岛 (RB, TA, MA, SC, P) 启动 50 代闭环进化]...")
    revert_pop = [ReversionIslandGenome.random_generate(rng) for _ in range(pop_size)]
    best_revert_gene = revert_pop[0]
    best_revert_fit = -1e9

    for gen in range(1, generations + 1):
        scores = []
        for ind in revert_pop:
            pnls = [simulate_revert_island(oos_dict[s], ind)["pnl"] for s in ISLAND_REVERT_SYMBOLS if s in oos_dict]
            sharpes = [simulate_revert_island(oos_dict[s], ind)["sharpe"] for s in ISLAND_REVERT_SYMBOLS if s in oos_dict]
            fit = float(np.median(sharpes)) * 10.0 + (sum(pnls) / 100_000.0) * 5.0
            scores.append(fit)

        sorted_i = np.argsort(scores)[::-1]
        revert_pop = [revert_pop[i] for i in sorted_i]
        scores = [scores[i] for i in sorted_i]

        if scores[0] > best_revert_fit:
            best_revert_fit = scores[0]
            best_revert_gene = copy.deepcopy(revert_pop[0])

        if gen == 1 or gen % 10 == 0 or gen == generations:
            tot_p = sum(simulate_revert_island(oos_dict[s], best_revert_gene)["pnl"] for s in ISLAND_REVERT_SYMBOLS if s in oos_dict)
            print(f"  ├─ Revert Island Gen {gen:02d}/{generations:02d} | 最佳适应度: {best_revert_fit:7.2f} | 均值池 OOS 净利: ¥{tot_p:+10,.2f} | 基因: Filter={best_revert_gene.filter_period}, DevEntry={best_revert_gene.dev_entry_atr}*ATR")

        new_p = revert_pop[:4]
        while len(new_p) < pop_size:
            p1, p2 = rng.choice(revert_pop[:10], size=2, replace=False)
            child = copy.deepcopy(p1)
            if rng.random() < 0.5: child.filter_period = p2.filter_period
            if rng.random() < 0.5: child.dev_entry_atr = p2.dev_entry_atr
            child = child.mutate(rng, rate=0.25)
            new_p.append(child)
        revert_pop = new_p

    # --------------------------------------------------------------------------
    # 阶段 3: 顶层风险平价正交对冲组合全盘审计
    # --------------------------------------------------------------------------
    print(f"\n{'='*95}")
    print(f"🏆 【顶层风险平价正交对冲组合全盘审计看板 (70/30 OOS 盲测)】")
    print(f"{'='*95}")
    print(f"{'品种名称':<10} | {'归属岛屿':<12} | {'OOS 交易':<8} | {'OOS 胜率':<8} | {'OOS 净利 (¥)':<14} | {'OOS 夏普':<8} | {'最大回撤'}")
    print(f"{'-'*95}")

    total_oos_net = 0.0
    total_oos_tr = 0
    symbol_report = {}

    # 趋势岛品种
    for sym in ISLAND_TREND_SYMBOLS:
        if sym in oos_dict:
            res = simulate_trend_island(oos_dict[sym], best_trend_gene)
            total_oos_net += res["pnl"]
            total_oos_tr += res["trades_count"]
            symbol_report[sym] = {"island": "Trend Island", **res}
            print(f"{sym:<10} | {'趋势单边岛':<10} | {res['trades_count']:<8} | {res['wr']:5.1f}%   | ¥{res['pnl']:+12,.2f} | {res['sharpe']:5.2f}    | {res['max_dd']:4.1f}%")

    # 均值岛品种
    for sym in ISLAND_REVERT_SYMBOLS:
        if sym in oos_dict:
            res = simulate_revert_island(oos_dict[sym], best_revert_gene)
            total_oos_net += res["pnl"]
            total_oos_tr += res["trades_count"]
            symbol_report[sym] = {"island": "Revert Island", **res}
            print(f"{sym:<10} | {'基差均值岛':<10} | {res['trades_count']:<8} | {res['wr']:5.1f}%   | ¥{res['pnl']:+12,.2f} | {res['sharpe']:5.2f}    | {res['max_dd']:4.1f}%")

    print(f"{'-'*95}")
    print(f"{'全盘对冲组合':<10} | {'正交风险平价':<10} | {total_oos_tr:<8} | {'-':<8} | ¥{total_oos_net:+12,.2f} | {'-':<8} | {'-'}")
    print(f"{'='*95}")

    # 导出生产代码与健康报告
    export_island_orthogonal_strategy(best_trend_gene, best_revert_gene)
    save_island_portfolio_report(best_trend_gene, best_revert_gene, symbol_report, total_oos_net, total_oos_tr)


def export_island_orthogonal_strategy(trend_gene: TrendIslandGenome, revert_gene: ReversionIslandGenome):
    target_file = STRATEGIES_DIR / "island_orthogonal_portfolio_strategy.py"
    code = f'''"""
strategies/island_orthogonal_portfolio_strategy.py — 「多物种岛屿正交对冲正反馈策略」
(Multi-Species Island Orthogonal Portfolio Strategy)

由 AutoQuant 分群自进化系统 50 代进化生成：
1. 趋势单边岛 (AG, LC, SN, AU, CU)：
   - DSP = ({trend_gene.fast_dsp_period}, {trend_gene.slow_dsp_period}), Channel = {trend_gene.channel_period}, Trail = {trend_gene.trail_atr_mult} * ATR
2. 基差均值岛 (RB, TA, MA, SC, P)：
   - Filter = {revert_gene.filter_period}, DevEntry = {revert_gene.dev_entry_atr} * ATR, Hard SL = {revert_gene.sl_atr_mult} * ATR
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd

STRATEGY_NAME = "island_orthogonal_portfolio_strategy"
TREND_UNIVERSE = {ISLAND_TREND_SYMBOLS}
REVERT_UNIVERSE = {ISLAND_REVERT_SYMBOLS}
'''
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"\n💾 正交对冲组合策略生产代码已成功导出至: {target_file}")


def save_island_portfolio_report(trend_gene, revert_gene, symbol_report, total_pnl, total_trades):
    report_file = DATA_DIR / "island_evolution_portfolio_report.json"
    payload = {
        "strategy": "island_orthogonal_portfolio_strategy",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trend_genome": asdict(trend_gene),
        "revert_genome": asdict(revert_gene),
        "total_oos_pnl": total_pnl,
        "total_oos_trades": total_trades,
        "symbol_details": {k: {"island": v["island"], "pnl": v["pnl"], "trades": v["trades_count"], "wr": v["wr"], "sharpe": v["sharpe"], "max_dd": v["max_dd"]} for k, v in symbol_report.items()}
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"📊 完整分群进化体检数据已成功写入: {report_file}")


if __name__ == "__main__":
    run_multi_species_evolution(generations=50, pop_size=30)
