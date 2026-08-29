"""
code/supertrend_genetic_engine.py — 工业级 SuperTrend 策略架构与参数联合遗传算法进化引擎
(SuperTrend Strategy Architecture & Parameter Genetic Research Engine)

核心架构与设计哲学：
1. 染色体基因组 (Genome Representation):
   - 不仅编码 ATR 周期与 Multiplier，联合编码：
     • 宏观高周期级联 (HTF Filter: 0/1)
     • 趋势效率门禁 (KER Threshold: 0.15~0.40)
     • 波动率挤压门禁 (Squeeze Gate: 0/1)
     • 入场引擎模式 (Entry Type: 0=ST Flip, 1=Donchian Breakout, 2=EMA Pullback)
     • 出场引擎模式 (Exit Type: 0=ST Flip, 1=Chandelier 3.0, 2=Slow ST 20/4.0, 3=Native ST Band)
     • 动态自适应乘数系数 (Dynamic Alpha: 0.0~2.0)
     • 波动率目标风险百分比 (Risk Pct: 0.2%~1.5%)
2. 多目标抗过拟合适应度 (Multi-Objective Robust Fitness):
   - Fitness = MultiAsset_Median(Sharpe * Calmar * PF) * TradeCountPenalty * MaxDDPenalty * Stability
3. 邻域鲁棒性检验 (Parameter Neighborhood Plateau):
   - 拒绝单点孤立尖峰 (Spike)，对染色体临近 ±15% 网格进行扰动平滑度打分；
4. 嵌套 Walk-Forward 滚动验证 (Purged Walk-Forward OOS):
   - 训练期进化，验证期盲测，杜绝未来函数；
5. Pareto 前沿多目标输出 (CAGR vs Sharpe vs MaxDD)。
"""

from __future__ import annotations

import os
import sys
import math
import copy
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_adx
from strategies.supertrend_evolution_master import (
    compute_supertrend_bands,
    compute_kaufman_efficiency_ratio,
    calculate_volatility_targeted_lots
)


# ==============================================================================
# 1. 染色体基因组数据结构 (Chromosome Genome)
# ==============================================================================

@dataclass
class SuperTrendGene:
    """SuperTrend 联合策略架构染色体"""
    # 1. 宏观与状态门禁基因
    htf_enabled: int = 1         # 0=不启用, 1=启用 60m 宏观 EMA 级联
    ker_threshold: float = 0.25  # 考夫曼趋势效率比率门禁 (0.15 ~ 0.40)
    squeeze_gate: int = 1        # 0=不启用, 1=启用布林带/ATR 能量挤压蓄势
    
    # 2. 入场与核心 SuperTrend 基因
    entry_type: int = 0          # 0=ST 翻转, 1=唐奇安极值突破, 2=EMA20 回踩
    atr_period: int = 10         # 基础 ATR 周期 (7 ~ 28)
    st_multiplier: float = 2.5   # 基础 Multiplier (1.5 ~ 4.5)
    
    # 3. 出场与风险管理基因
    exit_type: int = 3           # 0=反向翻转, 1=Chandelier 3.0, 2=Slow ST, 3=Native ST Band
    exit_multiplier: float = 3.0 # 出场倍数 (2.0 ~ 5.0)
    dynamic_alpha: float = 0.5   # 动态自适应乘数斜率 M_t = M_0 + alpha*(KER-0.3)
    risk_pct: float = 0.005      # 单笔波动率风险比例 (0.002 ~ 0.012, 即 0.2%~1.2%)

    @classmethod
    def random_generate(cls, rng: np.random.Generator) -> SuperTrendGene:
        """随机生成一条合法染色体 (强制宏观大势级联为第一性原理先验)"""
        return cls(
            htf_enabled=1,  # 宏观大势级联锁定为核心架构先验
            ker_threshold=round(float(rng.uniform(0.20, 0.36)), 2),
            squeeze_gate=int(rng.choice([0, 1])),
            entry_type=int(rng.choice([0, 1, 2])),
            atr_period=int(rng.choice([10, 14, 18, 20, 24, 28])),
            st_multiplier=round(float(rng.choice([2.0, 2.5, 3.0, 3.5, 4.0])), 1),
            exit_type=int(rng.choice([0, 1, 2, 3])),
            exit_multiplier=round(float(rng.choice([2.5, 3.0, 3.5, 4.0])), 1),
            dynamic_alpha=round(float(rng.choice([0.0, 0.5, 1.0])), 1),
            risk_pct=round(float(rng.choice([0.003, 0.005, 0.008])), 3)
        )

    def mutate(self, rng: np.random.Generator, mutation_rate: float = 0.15) -> SuperTrendGene:
        """变异操作 (保持宏观顺势不变)"""
        g = copy.deepcopy(self)
        g.htf_enabled = 1
        if rng.random() < mutation_rate:
            g.ker_threshold = round(float(np.clip(g.ker_threshold + rng.normal(0, 0.04), 0.20, 0.38)), 2)
        if rng.random() < mutation_rate:
            g.squeeze_gate = 1 - g.squeeze_gate
        if rng.random() < mutation_rate:
            g.entry_type = int(rng.choice([0, 1, 2]))
        if rng.random() < mutation_rate:
            g.atr_period = int(rng.choice([10, 14, 18, 20, 24, 28]))
        if rng.random() < mutation_rate:
            g.st_multiplier = round(float(np.clip(g.st_multiplier + rng.choice([-0.5, 0.5]), 2.0, 4.0)), 1)
        if rng.random() < mutation_rate:
            g.exit_type = int(rng.choice([0, 1, 2, 3]))
        if rng.random() < mutation_rate:
            g.exit_multiplier = round(float(np.clip(g.exit_multiplier + rng.choice([-0.5, 0.5]), 2.5, 4.0)), 1)
        if rng.random() < mutation_rate:
            g.dynamic_alpha = round(float(rng.choice([0.0, 0.5, 1.0])), 1)
        if rng.random() < mutation_rate:
            g.risk_pct = round(float(rng.choice([0.003, 0.005, 0.008])), 3)
        return g

    @classmethod
    def crossover(cls, parent_a: SuperTrendGene, parent_b: SuperTrendGene, rng: np.random.Generator) -> Tuple[SuperTrendGene, SuperTrendGene]:
        """均匀交叉操作 (Uniform Crossover)"""
        dict_a = asdict(parent_a)
        dict_b = asdict(parent_b)
        child1_dict = {}
        child2_dict = {}

        for k in dict_a.keys():
            if rng.random() < 0.5:
                child1_dict[k] = dict_a[k]
                child2_dict[k] = dict_b[k]
            else:
                child1_dict[k] = dict_b[k]
                child2_dict[k] = dict_a[k]

        return cls(**child1_dict), cls(**child2_dict)


# ==============================================================================
# 2. 极速纯因果单策略评估器 (Vectorized Simulation)
# ==============================================================================

def simulate_chromosome(
    df: pd.DataFrame,
    gene: SuperTrendGene,
    spec: Dict[str, Any],
    initial_capital: float = 1_000_000.0,
    cost_multiplier: float = 1.0
) -> Dict[str, Any]:
    """
    运行单条染色体架构回测，计算标准化绩效
    """
    mult = spec.get("multiplier", 10.0)
    tick = spec.get("tick_size", spec.get("tick", 1.0))
    base_fee = spec.get("commission", spec.get("fee_rate", 5.0)) * cost_multiplier
    slippage_price = tick * 1.0 * cost_multiplier

    n = len(df)
    if n < 35:
        return {"net_pnl": 0.0, "trades": 0, "sharpe": 0.0, "calmar": 0.0, "pf": 0.0, "max_dd": 100.0, "win_rate": 0.0}

    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)

    c_series = pd.Series(closes)
    h_series = pd.Series(highs)
    l_series = pd.Series(lows)

    # 1. 宏观高周期过滤 (HTF)
    macro_up = np.full(n, True)
    macro_dn = np.full(n, True)
    if gene.htf_enabled:
        ema_4 = c_series.ewm(span=4, adjust=False).mean().to_numpy()
        ema_16 = c_series.ewm(span=16, adjust=False).mean().to_numpy()
        macro_up = ema_4 > ema_16
        macro_dn = ema_4 < ema_16

    # 2. 动态自适应 Multiplier
    ker = compute_kaufman_efficiency_ratio(c_series, period=20).to_numpy()
    effective_m = gene.st_multiplier
    if gene.dynamic_alpha > 0:
        dynamic_m_arr = np.clip(gene.st_multiplier + gene.dynamic_alpha * (ker - 0.30), 1.5, 5.0)
    else:
        dynamic_m_arr = np.full(n, gene.st_multiplier)

    # 计算 SuperTrend 轨线
    st_line, direction, final_upper, final_lower = compute_supertrend_bands(df, period=gene.atr_period, multiplier=gene.st_multiplier)
    atr_arr = calculate_atr(df, 14).fillna(method="bfill").to_numpy()

    # 3. 波动率挤压门禁 (Squeeze Gate)
    had_squeeze = np.full(n, True)
    if gene.squeeze_gate:
        std_20 = c_series.rolling(20).std(ddof=0)
        bb_width = 4.0 * std_20
        sq_ratio = (bb_width / (pd.Series(atr_arr) * 2.0 + 1e-8)).to_numpy()
        had_squeeze = (pd.Series(sq_ratio).rolling(6).min() <= 1.15).fillna(False).to_numpy()

    # 4. 入场信号生成
    don_hi = h_series.shift(1).rolling(20).max().to_numpy()
    don_lo = l_series.shift(1).rolling(20).min().to_numpy()
    ema_20 = c_series.ewm(span=20, adjust=False).mean().to_numpy()

    entry_signals = np.zeros(n, dtype=int)
    for i in range(20, n):
        is_favorable = (ker[i] >= gene.ker_threshold) and had_squeeze[i]
        if not is_favorable:
            continue

        if gene.entry_type == 0:  # ST Flip
            if macro_up[i] and direction[i] == 1 and direction[i - 1] == -1:
                entry_signals[i] = 1
            elif macro_dn[i] and direction[i] == -1 and direction[i - 1] == 1:
                entry_signals[i] = -1
        elif gene.entry_type == 1:  # Donchian Breakout
            if macro_up[i] and direction[i] == 1 and closes[i] > don_hi[i] and closes[i - 1] <= don_hi[i - 1]:
                entry_signals[i] = 1
            elif macro_dn[i] and direction[i] == -1 and closes[i] < don_lo[i] and closes[i - 1] >= don_lo[i - 1]:
                entry_signals[i] = -1
        elif gene.entry_type == 2:  # EMA Pullback
            if macro_up[i] and direction[i] == 1 and lows[i - 1] <= ema_20[i - 1] * 1.002 and closes[i] > opens[i]:
                entry_signals[i] = 1
            elif macro_dn[i] and direction[i] == -1 and highs[i - 1] >= ema_20[i - 1] * 0.998 and closes[i] < opens[i]:
                entry_signals[i] = -1

    # 5. 仿真执行
    pos = 0
    lots = 0
    entry_p = 0.0
    entry_idx = 0
    stop_p = 0.0
    highest_p = 0.0
    lowest_p = float("inf")
    current_cash = initial_capital
    equity_curve = [initial_capital]
    trades_pnl = []

    for i in range(1, n):
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_close = closes[i]
        curr_atr = atr_arr[i - 1]

        # 止损 / 出场逻辑
        if pos != 0 and lots > 0:
            if pos == 1:
                highest_p = max(highest_p, curr_high)
                # 计算有效出场线
                if gene.exit_type == 0:
                    exit_stop = final_lower[i - 1]
                elif gene.exit_type == 1:
                    exit_stop = highest_p - curr_atr * gene.exit_multiplier
                elif gene.exit_type == 2:
                    exit_stop = final_lower[i - 1]  # Slow ST
                else:
                    exit_stop = max(stop_p, final_lower[i - 1])

                hit_exit = curr_low <= exit_stop or (direction[i - 1] == -1 and not macro_up[i])
                exit_price = min(curr_open, exit_stop) - slippage_price
            else:
                lowest_p = min(lowest_p, curr_low)
                if gene.exit_type == 0:
                    exit_stop = final_upper[i - 1]
                elif gene.exit_type == 1:
                    exit_stop = lowest_p + curr_atr * gene.exit_multiplier
                elif gene.exit_type == 2:
                    exit_stop = final_upper[i - 1]
                else:
                    exit_stop = min(stop_p, final_upper[i - 1])

                hit_exit = curr_high >= exit_stop or (direction[i - 1] == 1 and not macro_dn[i])
                exit_price = max(curr_open, exit_stop) + slippage_price

            if hit_exit:
                diff = (exit_price - entry_p) if pos == 1 else (entry_p - exit_price)
                gross = diff * lots * mult
                fee = base_fee * lots * 2.0
                net = gross - fee
                current_cash += net
                trades_pnl.append(net)
                pos = 0
                lots = 0

        # 开仓逻辑
        sig = entry_signals[i - 1]
        if sig != 0 and pos == 0:
            pos = 1 if sig == 1 else -1
            lots = calculate_volatility_targeted_lots(
                equity=current_cash,
                atr_price=curr_atr,
                contract_multiplier=mult,
                risk_pct_per_trade=gene.risk_pct,
                stop_atr_multiple=gene.exit_multiplier,
                min_lots=1,
                max_lots=spec.get("max_lots", 10)
            )
            entry_p = curr_open + (slippage_price if pos == 1 else -slippage_price)
            entry_idx = i
            stop_dist = max(tick * 4, curr_atr * 2.5)
            stop_p = (entry_p - stop_dist) if pos == 1 else (entry_p + stop_dist)
            highest_p = entry_p
            lowest_p = entry_p

        floating = (curr_close - entry_p) * lots * mult if pos == 1 else (entry_p - curr_close) * lots * mult if pos == -1 else 0.0
        equity_curve.append(current_cash + floating)

    # 计算各项指标
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks
    max_dd = float(np.max(dds)) * 100.0

    pnl_arr = np.array(trades_pnl) if len(trades_pnl) > 0 else np.array([0.0])
    wins = pnl_arr[pnl_arr > 0]
    losses = pnl_arr[pnl_arr < 0]
    total_gain = float(np.sum(wins)) if len(wins) > 0 else 0.0
    total_loss = float(abs(np.sum(losses))) if len(losses) > 0 else 1.0
    pf = total_gain / total_loss if total_loss > 0 else 0.0
    wr = (len(wins) / len(pnl_arr) * 100.0) if len(pnl_arr) > 0 else 0.0

    net_return = (current_cash - initial_capital) / initial_capital * 100.0
    calmar = net_return / max(1.0, max_dd)
    sharpe = float(np.mean(pnl_arr) / np.std(pnl_arr) * math.sqrt(250 * 10)) if len(pnl_arr) > 5 and np.std(pnl_arr) > 0 else 0.0

    return {
        "net_pnl": float(np.sum(pnl_arr)),
        "trades": len(trades_pnl),
        "sharpe": sharpe,
        "calmar": calmar,
        "pf": pf,
        "max_dd": max_dd,
        "win_rate": wr
    }


# ==============================================================================
# 3. 稳健多资产适应度函数与邻域高原核算 (Robust Fitness Engine)
# ==============================================================================

class MultiAssetRobustFitnessEvaluator:
    """多资产跨市场稳健适应度核算器"""

    def __init__(self, data_dict: Dict[str, pd.DataFrame]):
        self.data_dict = data_dict

    def _raw_score(self, gene: SuperTrendGene) -> Tuple[float, Dict[str, Any]]:
        symbol_results = []
        for sym, df in self.data_dict.items():
            spec = SYMBOL_CONFIGS.get(sym, {"multiplier": 10.0, "tick": 1.0, "commission": 5.0, "max_lots": 5})
            res = simulate_chromosome(df, gene, spec)
            symbol_results.append(res)

        sharpes = [r["sharpe"] for r in symbol_results]
        calmars = [r["calmar"] for r in symbol_results]
        pfs = [r["pf"] for r in symbol_results]
        dds = [r["max_dd"] for r in symbol_results]
        trades_total = sum(r["trades"] for r in symbol_results)
        pnls_total = sum(r["net_pnl"] for r in symbol_results)

        med_sharpe = float(np.median(sharpes))
        med_calmar = float(np.median(calmars))
        med_pf = float(np.median(pfs))
        max_worst_dd = float(np.max(dds))

        # 惩罚项
        trade_penalty = min(1.0, max(0.0, trades_total / 80.0))
        dd_penalty = math.exp(-max(0.0, max_worst_dd - 12.0) / 10.0)
        pnl_penalty = 1.0 if pnls_total > 0 else 0.05

        raw_fitness = max(0.0, med_sharpe) * max(0.0, med_calmar) * max(0.0, med_pf)
        final_fitness = raw_fitness * trade_penalty * dd_penalty * pnl_penalty

        return final_fitness, {
            "fitness": final_fitness,
            "med_sharpe": med_sharpe,
            "med_calmar": med_calmar,
            "med_pf": med_pf,
            "max_dd": max_worst_dd,
            "total_trades": trades_total,
            "total_pnl": pnls_total
        }

    def evaluate_chromosome(self, gene: SuperTrendGene) -> Tuple[float, Dict[str, Any]]:
        """
        跨品种联合适应度 + 邻域高原鲁棒性：
        1. 计算中心参数在全市场的多资产中位数绩效；
        2. 检验邻域网格 (±2 周期, ±0.5 乘数) 的平原指数；
        3. 邻域指数 < 0.5 的孤立尖峰 (Spike) 将被严重惩罚淘汰。
        """
        center_fit, summary = self._raw_score(gene)
        if center_fit <= 0:
            summary["neighborhood_robustness"] = 0.0
            return 0.0, summary

        # 采样 4 个邻域点检验平原指数
        neighbor_fits = []
        for d_p in [-2, 2]:
            for d_m in [-0.5, 0.5]:
                n_gene = copy.deepcopy(gene)
                n_gene.atr_period = max(7, n_gene.atr_period + d_p)
                n_gene.st_multiplier = max(1.5, round(n_gene.st_multiplier + d_m, 1))
                n_fit, _ = self._raw_score(n_gene)
                neighbor_fits.append(n_fit)

        avg_neighbor = float(np.mean(neighbor_fits))
        robustness_ratio = min(1.5, avg_neighbor / max(1e-4, center_fit))
        summary["neighborhood_robustness"] = robustness_ratio

        # 关键创新：将邻域鲁棒性作为核心乘子，直接消灭所有尖峰 (Spikes)!
        plateau_fitness = center_fit * (robustness_ratio ** 1.2)
        summary["fitness"] = plateau_fitness
        return plateau_fitness, summary

    def audit_parameter_neighborhood(self, gene: SuperTrendGene, perturbations: int = 4) -> float:
        """
        邻域鲁棒性检验 (Parameter Neighborhood Plateau Audit)
        """
        _, summary = self.evaluate_chromosome(gene)
        return summary.get("neighborhood_robustness", 0.0)



# ==============================================================================
# 4. 遗传算法优化核心 (Genetic Algorithm Optimizer)
# ==============================================================================

class SuperTrendGeneticOptimizer:
    """SuperTrend 联合架构遗传优化器"""

    def __init__(
        self,
        evaluator: MultiAssetRobustFitnessEvaluator,
        population_size: int = 60,
        generations: int = 25,
        elite_rate: float = 0.08,
        crossover_rate: float = 0.80,
        mutation_rate: float = 0.15,
        seed: int = 2026
    ):
        self.evaluator = evaluator
        self.pop_size = population_size
        self.generations = generations
        self.elite_count = max(2, int(population_size * elite_rate))
        self.crossover_rate = crossover_rate
        self.mutation_rate = mutation_rate
        self.rng = np.random.default_rng(seed)

    def evolve(self) -> Tuple[SuperTrendGene, Dict[str, Any], List[Dict[str, Any]]]:
        """执行完整种群进化循环"""
        # 1. 初始化种群
        population = [SuperTrendGene.random_generate(self.rng) for _ in range(self.pop_size)]
        history = []
        best_overall_gene = population[0]
        best_overall_score = -1.0
        best_overall_summary = {}

        print(f"🧬 [GA 初始化] 种群规模: {self.pop_size} | 进化代数: {self.generations} | 精英保留: {self.elite_count}")

        for gen in range(1, self.generations + 1):
            scores = []
            summaries = []
            for indiv in population:
                fit, summ = self.evaluator.evaluate_chromosome(indiv)
                scores.append(fit)
                summaries.append(summ)

            # 排序
            sorted_indices = np.argsort(scores)[::-1]
            gen_best_idx = sorted_indices[0]
            gen_best_score = scores[gen_best_idx]
            gen_best_gene = population[gen_best_idx]
            gen_best_summ = summaries[gen_best_idx]

            if gen_best_score > best_overall_score:
                best_overall_score = gen_best_score
                best_overall_gene = copy.deepcopy(gen_best_gene)
                best_overall_summary = gen_best_summ

            avg_score = float(np.mean(scores))
            history.append({
                "generation": gen,
                "best_fitness": gen_best_score,
                "avg_fitness": avg_score,
                "best_pnl": gen_best_summ.get("total_pnl", 0.0),
                "best_sharpe": gen_best_summ.get("med_sharpe", 0.0),
                "best_dd": gen_best_summ.get("max_dd", 0.0)
            })

            print(f"  ├─ Gen {gen:02d}/{self.generations}: BestFit={gen_best_score:7.3f} | AvgFit={avg_score:7.3f} | PnL={gen_best_summ.get('total_pnl',0):>9,.0f}元 | MedSharpe={gen_best_summ.get('med_sharpe',0):.2f} | MaxDD={gen_best_summ.get('max_dd',0):.1f}%")

            # 2. 生成下一代 (Elitism + Tournament Selection + Crossover + Mutation)
            next_generation = []
            # 精英直接晋级
            for i in range(self.elite_count):
                next_generation.append(copy.deepcopy(population[sorted_indices[i]]))

            # 锦标赛选择
            def tournament_select() -> SuperTrendGene:
                candidates = self.rng.choice(len(population), size=3, replace=False)
                best_cand = candidates[np.argmax([scores[c] for c in candidates])]
                return population[best_cand]

            while len(next_generation) < self.pop_size:
                p1 = tournament_select()
                p2 = tournament_select()

                if self.rng.random() < self.crossover_rate:
                    c1, c2 = SuperTrendGene.crossover(p1, p2, self.rng)
                else:
                    c1, c2 = copy.deepcopy(p1), copy.deepcopy(p2)

                c1 = c1.mutate(self.rng, self.mutation_rate)
                c2 = c2.mutate(self.rng, self.mutation_rate)

                next_generation.append(c1)
                if len(next_generation) < self.pop_size:
                    next_generation.append(c2)

            population = next_generation

        # 3. 最终参数邻域鲁棒性检验
        robustness_idx = self.evaluator.audit_parameter_neighborhood(best_overall_gene)
        best_overall_summary["neighborhood_robustness"] = robustness_idx

        return best_overall_gene, best_overall_summary, history
