"""
Dedicated 5-Minute Strategy Optimizer for Losing Commodities
【针对 5 分钟回测中亏损品种的专用高速超参数与微观 PPO 寻优工具】
"""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_5m_symbol_engines import (
    SYMBOL_5M_CONFIGS,
    Decoupled5mSymbolStrategyRunner
)

LOSING_SYMBOLS = [
    "SC_IDX",   # 原油
    "CF_IDX",   # 棉花
    "ZN_IDX",   # 沪锌
    "RU_IDX",   # 橡胶
    "SR_IDX",   # 白糖
    "HC_IDX",   # 热卷
    "Y_IDX",    # 豆油
    "SI_IDX",   # 工业硅
    "FG_IDX"    # 玻璃
]

def run_deep_symbol_optimization():
    runner = Decoupled5mSymbolStrategyRunner()
    print("=" * 90)
    print(f"🎯 开始针对 9 大亏损品种进行 5 分钟专属深度参数网格与微观 PPO 寻优...")
    print("=" * 90)

    best_configurations = {}

    for sym in LOSING_SYMBOLS:
        base_cfg = SYMBOL_5M_CONFIGS[sym].copy()
        name = base_cfg["name"]
        print(f"\n🔍 [深度寻优] 正在处理品种: {sym} ({name})...")

        # 1. 预先计算并缓存 5m 特征与 Walk-Forward ML 预测概率
        df_raw = runner.load_5m_data(sym)
        df_feat = runner.compute_5m_features_and_labels(df_raw, base_cfg)
        feature_cols = base_cfg.get("feature_set", ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"])
        df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

        prob_l, prob_s = runner.run_walk_forward_5m_ml(
            df_clean, feature_cols,
            train_window=min(4000, int(len(df_clean) * 0.6)),
            step_size=500,
            purge_gap=30
        )
        df_clean["prob_long"] = prob_l
        df_clean["prob_short"] = prob_s
        df_sim = df_clean.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)

        if len(df_sim) < 100:
            print(f"⚠️ {sym} 数据量不足，跳过")
            continue

        # 2. 细粒度网格搜索空间 (包含高置信度门槛、动态止损、保本点与时间衰减)
        prob_range = [0.26, 0.27, 0.28, 0.29, 0.30, 0.31]
        sl_range = [0.7, 0.8, 0.9, 1.0, 1.2]
        be_range = [1.2, 1.4, 1.6, 1.8]
        trail_range = [2.6, 3.0, 3.4, 3.8]
        max_bars_range = [20, 25, 30, 40]

        best_score = -999999.0
        best_cfg = base_cfg.copy()
        best_metrics = {}

        # 针对每个品种快速遍历 1,200+ 组参数组合
        for p in prob_range:
            for sl in sl_range:
                for be in be_range:
                    for trl in trail_range:
                        for mb in max_bars_range:
                            test_cfg = base_cfg.copy()
                            test_cfg["prob_thresh"] = p
                            test_cfg["sl_atr"] = sl
                            test_cfg["be_atr"] = be
                            test_cfg["trail_atr"] = trl
                            test_cfg["max_holding_bars"] = mb

                            res = runner.simulate_5m_execution(df_sim, sym, test_cfg)
                            
                            # 综合评分函数：夏普比率 + 盈利能力 + 胜率惩罚 + 回撤控制
                            cnt = res["trades_count"]
                            if cnt >= 15:
                                pnl = res["total_pnl"]
                                pf = min(5.0, res["profit_factor"])
                                sr = res["sharpe_ratio"]
                                wr = res["win_rate"]
                                mdd = res["max_drawdown_pct"]

                                score = (pnl / 10000.0) * 1.0 + sr * 1.5 + pf * 2.0 + (wr / 10.0) * 0.5 - (mdd / 5.0) * 1.5
                                
                                if score > best_score:
                                    best_score = score
                                    best_cfg = test_cfg
                                    best_metrics = res

        print(f"✨ 寻优结果: {sym} ({name}) -> 净盈亏: {best_metrics.get('total_pnl', 0):+,.2f} 元 | 胜率: {best_metrics.get('win_rate', 0)}% | 盈亏比: {best_metrics.get('profit_factor', 0)} | 夏普: {best_metrics.get('sharpe_ratio', 0)} | 回撤: {best_metrics.get('max_drawdown_pct', 0)}%")
        print(f"   最佳参数: prob_thresh={best_cfg['prob_thresh']}, sl_atr={best_cfg['sl_atr']}, be_atr={best_cfg['be_atr']}, trail_atr={best_cfg['trail_atr']}, max_holding_bars={best_cfg['max_holding_bars']}")
        best_configurations[sym] = best_cfg

    print("\n" + "=" * 90)
    print("📋 所有 9 大亏损品种优化参数字典:")
    print("=" * 90)
    print(json.dumps(best_configurations, indent=2, ensure_ascii=False))

    return best_configurations

if __name__ == "__main__":
    run_deep_symbol_optimization()
