"""
code/chan_factor_pipeline.py — 因果缠论 7 大 S 级核心因子与特征管道 (Chan S-Tier Factor Pipeline)

基于 dist.md 的 S 级精简因子集与方向标准化坐标系统：
1. 方向坐标统一:
   s = +1 (多头事件 B3) / -1 (空头事件 S3)
2. S 级核心因子集:
   - B05_bi_efficiency: 笔移动效率 (Kaufman Efficiency Ratio, ER)
   - B10_same_dir_amp_ratio: 同向振幅比 (离开段 vs 进入段动能耗散)
   - Z01_zhongshu_width: 中枢标准化宽度 (Width / ATR)
   - Z09_zhongshu_compression: 中枢收缩率 (Amp(Bi3) / Amp(Bi1))
   - Z11_breakout_strength: 突破强度 (Breakout Distance / ATR)
   - P08_pullback_depth: 三买回踩深度 (Pullback Distance / ATR)
   - P09_edge_clearance: 边界安全冗余度 (Clearance / ATR)
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd

from causal_chan_engine import CausalBuySellEvent, CausalChanEngine


S_TIER_FACTORS = [
    "B05_bi_efficiency",
    "B10_same_dir_amp_ratio",
    "Z01_zhongshu_width",
    "Z09_zhongshu_compression",
    "Z11_breakout_strength",
    "P08_pullback_depth",
    "P09_edge_clearance",
]


def extract_event_factors_dataframe(events: List[CausalBuySellEvent]) -> pd.DataFrame:
    """将因果买卖点事件列表转换为标准特征 DataFrame"""
    if not events:
        cols = ["event_id", "event_type", "side", "known_time", "known_raw_idx", "trigger_price", "zs_high", "zs_low", "zs_id"] + S_TIER_FACTORS
        return pd.DataFrame(columns=cols)

    records = []
    for ev in events:
        row = {
            "event_id": ev.event_id,
            "event_type": ev.event_type,
            "side": ev.side,
            "known_time": ev.known_time,
            "known_raw_idx": ev.known_raw_idx,
            "trigger_price": ev.trigger_price,
            "zs_high": ev.zs_high,
            "zs_low": ev.zs_low,
            "zs_id": ev.zs_id,
        }
        for k in S_TIER_FACTORS:
            row[k] = ev.factors.get(k, 0.0)
        records.append(row)

    return pd.DataFrame(records)


def compute_directional_forward_returns(
    df: pd.DataFrame,
    events: List[CausalBuySellEvent],
    horizons: Tuple[int, ...] = (5, 10, 20, 40)
) -> pd.DataFrame:
    """
    计算基于统一方向坐标的样本外向前收益:
    R_{t, h}^{side} = s * (P_{t+h} - P_t) / ATR_t
    """
    if not events or df.empty:
        return pd.DataFrame()

    c = df["close"].astype(float).values
    atr = df.get("atr", df.get("atr_14", pd.Series(np.ones(len(df))))).astype(float).values
    n = len(c)

    ev_df = extract_event_factors_dataframe(events)
    for h in horizons:
        labels = []
        for _, row in ev_df.iterrows():
            idx = int(row["known_raw_idx"])
            side = int(row["side"])
            curr_p = c[idx]
            curr_atr = atr[idx] if atr[idx] > 0 else 1.0

            if idx + h < n:
                future_p = c[idx + h]
                ret_atr = side * (future_p - curr_p) / curr_atr
            else:
                ret_atr = np.nan
            labels.append(ret_atr)

        ev_df[f"fwd_ret_{h}"] = labels

    return ev_df


def filter_quality_events(
    events: List[CausalBuySellEvent],
    min_bi_efficiency: float = 0.35,
    max_compression: float = 1.35,
    min_pullback_depth: float = -0.15,
    min_edge_clearance: float = 0.05,
) -> List[CausalBuySellEvent]:
    """
    根据 S 级因子的品质门禁筛选高质量三买/三卖事件
    """
    filtered = []
    for ev in events:
        f = ev.factors
        er = f.get("B05_bi_efficiency", 0.0)
        comp = f.get("Z09_zhongshu_compression", 1.0)
        p_depth = f.get("P08_pullback_depth", 0.0)
        p_clear = f.get("P09_edge_clearance", 0.0)

        if er >= min_bi_efficiency and comp <= max_compression and p_depth >= min_pullback_depth and p_clear >= min_edge_clearance:
            filtered.append(ev)

    return filtered
