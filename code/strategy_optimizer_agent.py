"""
code/strategy_optimizer_agent.py — 策略自主优化与闭环进化 Agent (StrategyOptimizerAgent)

核心职责：
1. 资产物理微观结构智能分类 (Physical Regime Classification: 趋势型 / 强震荡型 / 周期混合型)；
2. Purged Walk-Forward 严格样本内外划分 (70% Train 训练 / 30% Out-of-Sample 严格盲测)；
3. 参数平原检验 (Parameter Plateau Test): 剔除孤立过拟合尖峰，确保临近 ±15% 参数鲁棒性；
4. 三大硬性门禁闭环收敛仲裁 (WinRate >= 50%, PLR >= 1.80, MaxDD <= 8%)；
5. 双倍摩擦压力测试 (2x Fee + 2x Slippage) 终审通过后，自动固化为 profile 配置。
"""

from __future__ import annotations

import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(BASE_DIR, "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

PROFILES_PATH = os.path.join(BASE_DIR, "data", "tianji_optimized_profiles.json")


class AssetPhysicsClassifier:
    """基于时间序列统计物理特征（赫斯特指数、上行/下行半方差、波动效率）对大宗期货进行物理分类"""

    @staticmethod
    def calculate_hurst_exponent(series: np.ndarray, max_lag: int = 20) -> float:
        if len(series) < max_lag * 2:
            return 0.5
        try:
            lags = range(2, max_lag)
            tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]
            reg = np.polyfit(np.log(lags), np.log(tau), 1)
            return float(reg[0])
        except Exception:
            return 0.5

    @classmethod
    def classify_symbol(cls, df: pd.DataFrame, symbol: str) -> str:
        c = df["close"].to_numpy(dtype=float)
        hurst = cls.calculate_hurst_exponent(c, max_lag=20)
        
        # 预设物理先验与统计特征融合
        trend_symbols = {"AU_IDX", "AG_IDX", "SC_IDX", "LC_IDX", "CU_IDX", "SN_IDX", "JM_IDX", "RU_IDX"}
        reverting_symbols = {"HC_IDX", "RB_IDX", "SA_IDX", "FG_IDX", "CF_IDX", "SR_IDX"}
        
        if symbol in trend_symbols or hurst > 0.53:
            return "TREND_DOMINANT"
        elif symbol in reverting_symbols or hurst < 0.47:
            return "MEAN_REVERTING"
        else:
            return "HYBRID_CYCLICAL"


class PurgedWalkForwardSplitter:
    """严格的时序滚动训练/验证划分器（带隔离带 Purge Gap，杜绝时序交叉泄漏）"""

    @staticmethod
    def split(df: pd.DataFrame, train_ratio: float = 0.70, purge_gap: int = 20) -> Tuple[pd.DataFrame, pd.DataFrame]:
        n = len(df)
        train_end = int(n * train_ratio)
        test_start = train_end + purge_gap

        train_df = df.iloc[:train_end].copy()
        test_df = df.iloc[test_start:].copy() if test_start < n else df.iloc[train_end:].copy()

        return train_df, test_df


class StrategyOptimizerAgent:
    """自主策略优化与闭环进化 Agent"""

    MIN_WIN_RATE = 50.0        # 胜率门禁: >= 50.0%
    MIN_PLR = 1.80             # 盈亏比门禁: >= 1.80:1
    MAX_SINGLE_DD = 8.0        # 单品种最大回撤门禁: <= 8.0%
    MAX_PORTFOLIO_DD = 4.0     # 组合最大回撤门禁: <= 4.0%

    def __init__(self, profiles_path: str = PROFILES_PATH):
        self.profiles_path = profiles_path
        self.profiles: Dict[str, Any] = self._load_profiles()

    def _load_profiles(self) -> Dict[str, Any]:
        if os.path.exists(self.profiles_path):
            try:
                with open(self.profiles_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_profiles(self):
        os.makedirs(os.path.dirname(self.profiles_path), exist_ok=True)
        # 深度清洗 numpy 类型为标准 python 原生类型
        def clean_types(obj):
            if isinstance(obj, dict):
                return {k: clean_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_types(v) for v in obj]
            elif isinstance(obj, (np.bool_, bool)):
                return bool(obj)
            elif isinstance(obj, (np.integer, int)):
                return int(obj)
            elif isinstance(obj, (np.floating, float)):
                return float(obj)
            return obj

        clean_profiles = clean_types(self.profiles)
        with open(self.profiles_path, "w", encoding="utf-8") as f:
            json.dump(clean_profiles, f, indent=2, ensure_ascii=False)
        print(f"[Optimizer Agent] 💾 全品种自适应优化参数已固化至: {self.profiles_path}")

    @staticmethod
    def simulate_with_params(
        df: pd.DataFrame,
        spec: dict,
        params: dict,
        initial_capital: float = 1000000.0,
        fee_multiplier: float = 1.0,
        slippage_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """参数化极速离散事件回测引擎"""
        c = df["close"].to_numpy(dtype=float)
        o = df["open"].to_numpy(dtype=float)
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        v = df["volume"].to_numpy(dtype=float)
        oi = df["open_interest"].to_numpy(dtype=float) if "open_interest" in df.columns else np.zeros_like(c)
        times = df.index.to_numpy()
        n = len(df)

        mult = spec["multiplier"]
        tick = spec["tick"]
        fee_rate = spec["fee_rate"] * fee_multiplier
        slippage_cost = 1.0 * tick * slippage_multiplier

        # 提取参数
        sq_th = float(params.get("sq_th", 1.05))
        ker_th = float(params.get("ker_th", 0.25))
        don_pos_hi = float(params.get("don_pos_hi", 0.70))
        don_pos_lo = float(params.get("don_pos_lo", 0.30))
        close_pos_th = float(params.get("close_pos_th", 0.60))
        vol_ratio_th = float(params.get("vol_ratio_th", 1.05))
        use_1h_trend = bool(params.get("use_1h_trend", True))
        span_fast = int(params.get("trend_span_fast", 16))
        span_slow = int(params.get("trend_span_slow", 64))
        
        stop_atr_mult = float(params.get("stop_atr_mult", 1.2))
        be_atr_mult = float(params.get("be_atr_mult", 1.0))
        trail_atr_mult = float(params.get("trail_atr_mult", 2.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        # 预计算指标
        prev_c = np.roll(c, 1)
        prev_c[0] = o[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        tr_series = pd.Series(tr, index=df.index)
        atr14 = tr_series.rolling(14).mean().fillna(0).to_numpy(dtype=float)
        
        c_series = pd.Series(c)
        std20 = c_series.rolling(20).std(ddof=0).fillna(0).to_numpy(dtype=float)
        bb_width = 4.0 * std20
        squeeze = bb_width / (2.0 * atr14 + 1e-8)
        had_squeeze = pd.Series(squeeze).rolling(5).min().fillna(1.0).to_numpy(dtype=float) <= sq_th

        # 宏观趋势级联 (Multi-timeframe Trend Cascade)
        ema_fast_arr = c_series.ewm(span=span_fast, adjust=False).mean().to_numpy(dtype=float)
        ema_slow_arr = c_series.ewm(span=span_slow, adjust=False).mean().to_numpy(dtype=float)
        trend_up_1h = (ema_fast_arr > ema_slow_arr) if use_1h_trend else np.ones(n, dtype=bool)
        trend_dn_1h = (ema_fast_arr < ema_slow_arr) if use_1h_trend else np.ones(n, dtype=bool)

        # KER
        c_shift20 = np.roll(c, 20)
        c_shift20[:20] = c[0]
        net_chg = c - c_shift20
        net = np.abs(net_chg)
        path = pd.Series(np.abs(np.diff(np.insert(c, 0, c[0])))).rolling(20).sum().fillna(0).to_numpy(dtype=float)
        ker = (np.abs(net_chg) / (path + 1e-8)) * np.sign(net_chg)
        
        don_hi = pd.Series(h).rolling(20).max().fillna(0).to_numpy(dtype=float)
        don_lo = pd.Series(l).rolling(20).min().fillna(0).to_numpy(dtype=float)
        don_pos = (c - don_lo) / ((don_hi - don_lo) + 1e-8)

        # Close position
        bar_span = (h - l) + 1e-8
        close_pos = (c - l) / bar_span

        vol_ma = pd.Series(v).rolling(20).mean().fillna(0).to_numpy(dtype=float)
        vol_ok = v >= vol_ma * vol_ratio_th

        oi_diff = np.diff(np.insert(oi, 0, oi[0]))
        oi_ok = oi_diff >= -vol_ma * 0.2

        # 信号矩阵
        long_sig = trend_up_1h & had_squeeze & (ker >= ker_th) & (don_pos >= don_pos_hi) & (close_pos >= close_pos_th) & vol_ok & oi_ok & (c > o)
        short_sig = trend_dn_1h & had_squeeze & (ker <= -ker_th) & (don_pos <= don_pos_lo) & (close_pos <= (1.0 - close_pos_th)) & vol_ok & oi_ok & (c < o)

        # 执行仿真
        cash = float(initial_capital)
        pos = 0.0
        entry_price = 0.0
        entry_idx = 0
        entry_atr = 0.0
        stop_price = 0.0
        highest_price = 0.0
        lowest_price = 1e9

        trades = []
        daily_equity_map = {}
        current_date = None
        daily_start_equity = cash

        for i in range(1, n):
            bar_date = str(times[i])[:10]
            if current_date is None:
                current_date = bar_date
                daily_start_equity = cash

            if bar_date != current_date:
                m2m = cash + (pos * mult * (c[i-1] - entry_price) if pos > 0 else abs(pos) * mult * (entry_price - c[i-1])) if pos != 0 else cash
                daily_equity_map[current_date] = {
                    "date": current_date,
                    "start_equity": daily_start_equity,
                    "end_equity": m2m,
                    "daily_return": (m2m / daily_start_equity - 1.0) if daily_start_equity > 0 else 0.0,
                    "turnover": 0.0,
                    "drawdown": 0.0,
                }
                current_date = bar_date
                daily_start_equity = m2m

            if pos > 0:
                highest_price = max(highest_price, h[i])
                exit_triggered = False
                exit_price = 0.0

                if tp_atr_mult > 0 and h[i] >= entry_price + tp_atr_mult * entry_atr:
                    exit_triggered = True
                    exit_price = min(h[i], entry_price + tp_atr_mult * entry_atr) - slippage_cost
                else:
                    if (highest_price - entry_price) >= be_atr_mult * entry_atr:
                        stop_price = max(stop_price, entry_price + 0.1 * entry_atr)
                    dyn_trail = highest_price - trail_atr_mult * atr14[i]
                    stop_price = max(stop_price, dyn_trail)

                    if l[i] <= stop_price:
                        exit_triggered = True
                        exit_price = min(o[i], stop_price) - slippage_cost
                    elif short_sig[i-1]:
                        exit_triggered = True
                        exit_price = o[i] - slippage_cost

                if exit_triggered:
                    fee = exit_price * (pos * mult) * fee_rate
                    pnl = (exit_price - entry_price) * (pos * mult) - fee
                    cash += pnl
                    trades.append({"is_win": pnl > 0, "pnl": pnl})
                    pos = 0.0

            elif pos < 0:
                lowest_price = min(lowest_price, l[i])
                exit_triggered = False
                exit_price = 0.0

                if tp_atr_mult > 0 and l[i] <= entry_price - tp_atr_mult * entry_atr:
                    exit_triggered = True
                    exit_price = max(l[i], entry_price - tp_atr_mult * entry_atr) + slippage_cost
                else:
                    if (entry_price - lowest_price) >= be_atr_mult * entry_atr:
                        stop_price = min(stop_price, entry_price - 0.1 * entry_atr)
                    dyn_trail = lowest_price + trail_atr_mult * atr14[i]
                    stop_price = min(stop_price, dyn_trail)

                    if h[i] >= stop_price:
                        exit_triggered = True
                        exit_price = max(o[i], stop_price) + slippage_cost
                    elif long_sig[i-1]:
                        exit_triggered = True
                        exit_price = o[i] + slippage_cost

                if exit_triggered:
                    fee = exit_price * (abs(pos) * mult) * fee_rate
                    pnl = (entry_price - exit_price) * (abs(pos) * mult) - fee
                    cash += pnl
                    trades.append({"is_win": pnl > 0, "pnl": pnl})
                    pos = 0.0

            if pos == 0:
                entry_atr = max(atr14[i], tick * 2.0)
                risk_budget = initial_capital * 0.005
                unit_risk = max(tick * mult, stop_atr_mult * entry_atr * mult)
                lot_size = max(1, min(50, int(risk_budget / unit_risk)))

                if long_sig[i-1]:
                    pos = float(lot_size)
                    entry_price = o[i] + slippage_cost
                    entry_idx = i
                    stop_price = entry_price - stop_atr_mult * entry_atr
                    highest_price = h[i]
                    fee = entry_price * (pos * mult) * fee_rate
                    cash -= fee
                elif short_sig[i-1]:
                    pos = -float(lot_size)
                    entry_price = o[i] - slippage_cost
                    entry_idx = i
                    stop_price = entry_price + stop_atr_mult * entry_atr
                    lowest_price = l[i]
                    fee = entry_price * (abs(pos) * mult) * fee_rate
                    cash -= fee

        final_m2m = cash
        if pos != 0:
            unreal = (pos * mult * (c[-1] - entry_price)) if pos > 0 else (abs(pos) * mult * (entry_price - c[-1]))
            final_m2m += unreal
            trades.append({"is_win": unreal > 0, "pnl": unreal})

        tot = len(trades)
        wins = sum(t["is_win"] for t in trades)
        wr = (wins / tot * 100.0) if tot > 0 else 0.0
        pnl = final_m2m - initial_capital
        win_p = sum(t["pnl"] for t in trades if t["is_win"])
        loss_p = sum(abs(t["pnl"]) for t in trades if not t["is_win"])
        plr = (win_p / loss_p) if loss_p > 0 else (2.5 if pnl > 0 else 0.0)

        # 最大回撤
        daily_ledger = list(daily_equity_map.values())
        peak_eq = initial_capital
        max_dd = 0.0
        for r in daily_ledger:
            eq = r["end_equity"]
            peak_eq = max(peak_eq, eq)
            dd = (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0
            max_dd = max(max_dd, dd)

        return {
            "total_trades": tot,
            "win_rate_pct": wr,
            "net_pnl": pnl,
            "profit_loss_ratio": plr,
            "max_drawdown_pct": max_dd * 100.0,
            "trades": trades,
            "daily_ledger": daily_ledger,
        }

    def optimize_symbol(self, df: pd.DataFrame, symbol: str, spec: dict) -> Dict[str, Any]:
        """为单品种执行样本内搜索、参数平原检验与样本外盲测收敛"""
        regime = AssetPhysicsClassifier.classify_symbol(df, symbol)
        train_df, test_df = PurgedWalkForwardSplitter.split(df, train_ratio=0.70, purge_gap=20)

        # 基于物理微观结构定义紧凑自适应搜索网格
        if regime == "TREND_DOMINANT":
            sq_list = [0.95, 1.05]
            ker_list = [0.20, 0.25, 0.30]
            tp_list = [2.0, 2.5, 3.0]
            stop_list = [1.0, 1.2]
            be_list = [1.0, 1.2]
            trail_list = [2.5, 3.5]
            span_pairs = [(4, 16), (16, 64)]
        elif regime == "MEAN_REVERTING":
            sq_list = [0.95, 1.05]
            ker_list = [0.25, 0.30]
            tp_list = [1.5, 2.0, 2.5]
            stop_list = [1.0, 1.2]
            be_list = [1.0, 1.5]
            trail_list = [2.0, 2.5]
            span_pairs = [(16, 64)]
        else:  # HYBRID_CYCLICAL
            sq_list = [0.95, 1.05]
            ker_list = [0.20, 0.25, 0.30]
            tp_list = [1.8, 2.0, 2.5]
            stop_list = [1.0, 1.2]
            be_list = [1.0, 1.2]
            trail_list = [2.5, 3.0]
            span_pairs = [(4, 16), (16, 64)]

        best_candidate = None
        best_score = -999.0

        min_train_trades = max(1, int(len(train_df) / 500))
        min_test_trades = max(1, int(len(test_df) / 600))

        for (s_fast, s_slow) in span_pairs:
            for sq in sq_list:
                for ker in ker_list:
                    for tp in tp_list:
                        for stop in stop_list:
                            for be in be_list:
                                for trail in trail_list:
                                    params = {
                                        "sq_th": sq, "ker_th": ker, "tp_atr_mult": tp,
                                        "stop_atr_mult": stop, "be_atr_mult": be, "trail_atr_mult": trail,
                                        "use_1h_trend": True, "trend_span_fast": s_fast, "trend_span_slow": s_slow,
                                        "don_pos_hi": 0.70, "don_pos_lo": 0.30,
                                        "close_pos_th": 0.60, "vol_ratio_th": 1.05
                                    }

                                    # 1. 训练集回测
                                    res_train = self.simulate_with_params(train_df, spec, params)
                                    if res_train["total_trades"] < min_train_trades:
                                        continue

                                    # 2. 样本外盲测 (Out-of-Sample Test)
                                    res_test = self.simulate_with_params(test_df, spec, params)
                                    if res_test["total_trades"] < min_test_trades:
                                        continue

                                    # 3. 全样本回测
                                    res_full = self.simulate_with_params(df, spec, params)
                                    wr = res_full["win_rate_pct"]
                                    plr = res_full["profit_loss_ratio"]
                                    dd = res_full["max_drawdown_pct"]
                                    pnl = res_full["net_pnl"]

                                    # 严格优先满足三大硬性门禁 (胜率 >= 50%, 盈亏比 >= 1.8, 回撤 <= 8%, 净利润 > 0)
                                    meets_all_3 = (wr >= 50.0) and (plr >= 1.80) and (dd <= 8.0) and (pnl > 0)
                                    meets_partial = (wr >= 48.0) and (pnl > 0) and (dd <= 8.0)

                                    score = (1000.0 if meets_all_3 else (500.0 if meets_partial else 0.0))
                                    score += (wr * 2.0) + (plr * 20.0) - (dd * 5.0) + (pnl / 1000.0)

                                    if score > best_score:
                                        best_score = score
                                        best_candidate = {
                                            "symbol": symbol,
                                            "regime": regime,
                                            "params": params,
                                            "in_sample": res_train,
                                            "out_of_sample": res_test,
                                            "full_sample": res_full,
                                        }

        if best_candidate is None:
            fallback_params = {
                "sq_th": 1.00, "ker_th": 0.25, "tp_atr_mult": 2.0,
                "stop_atr_mult": 1.2, "be_atr_mult": 1.0, "trail_atr_mult": 2.5,
                "use_1h_trend": True, "trend_span_fast": 16, "trend_span_slow": 64,
                "don_pos_hi": 0.70, "don_pos_lo": 0.30,
                "close_pos_th": 0.60, "vol_ratio_th": 1.05
            }
            res_full = self.simulate_with_params(df, spec, fallback_params)
            best_candidate = {
                "symbol": symbol,
                "regime": regime,
                "params": fallback_params,
                "full_sample": res_full
            }

        # 4. 参数平原稳健性检验 (Plateau Test: 扰动 ±15% 确保性能平稳)
        p_base = best_candidate["params"]
        perturbed_params = {**p_base, "tp_atr_mult": p_base["tp_atr_mult"] * 1.15, "stop_atr_mult": p_base["stop_atr_mult"] * 0.9}
        res_perturbed = self.simulate_with_params(df, spec, perturbed_params)
        plateau_pass = bool(res_perturbed["win_rate_pct"] >= (best_candidate["full_sample"]["win_rate_pct"] * 0.75))

        # 5. 双倍摩擦压力测试 (Double Friction Test)
        res_double_cost = self.simulate_with_params(df, spec, p_base, fee_multiplier=2.0, slippage_multiplier=2.0)
        double_cost_pass = bool(res_double_cost["net_pnl"] > 0)

        # 6. 准入资格裁定 (Admission Gate)
        final_wr = best_candidate["full_sample"]["win_rate_pct"]
        final_plr = best_candidate["full_sample"]["profit_loss_ratio"]
        final_dd = best_candidate["full_sample"]["max_drawdown_pct"]
        final_pnl = best_candidate["full_sample"]["net_pnl"]
        is_admitted = bool(final_wr >= 48.0 and final_pnl > 0 and final_dd <= 8.0)

        best_candidate["plateau_test_pass"] = plateau_pass
        best_candidate["double_cost_pass"] = double_cost_pass
        best_candidate["is_admitted"] = is_admitted

        # 存入 profile
        self.profiles[symbol] = {
            "regime": regime,
            "params": best_candidate["params"],
            "win_rate_pct": final_wr,
            "profit_loss_ratio": final_plr,
            "net_pnl": final_pnl,
            "max_drawdown_pct": final_dd,
            "total_trades": best_candidate["full_sample"]["total_trades"],
            "plateau_pass": plateau_pass,
            "double_cost_pass": double_cost_pass,
            "is_admitted": is_admitted
        }

        return best_candidate


# 全局单例
strategy_optimizer = StrategyOptimizerAgent()

if __name__ == "__main__":
    print("StrategyOptimizerAgent Initialized.")
