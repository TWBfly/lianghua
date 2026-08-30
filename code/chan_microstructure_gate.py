"""
code/chan_microstructure_gate.py — 微观订单流与成交量分布拓扑门禁 (VPVR & OFI Microstructure Gate)

核心微观物理机制：
1. 动态成交量价格分布拓扑剖面 (Volume Profile VPVR & Liquidity Topology):
   - 高换手密集区 (High Volume Node, HVN): 价格存在强吸附势阱 (中枢核心换手带)；
   - 低成交真空区 (Low Volume Node, LVN): 价格阻力极小，突破后极易引发极速跃迁；
   - 因果计算当前价格所在分区的成交量密度 (Volume Density)。当 Vol_Density <= 0.60 且价格突破 VAH/VAL 时，确认为有效真空跃迁。
2. 订单流微观失衡 (Order Flow Imbalance, OFI Z-Score):
   - 基于主动量价推动力 (Volume * Sign(Close - Open)) 与持仓量增减 (Delta OI) 构造微观 OFI；
   - 当 OFI Z-Score >= 1.0 时，确认主力机构真金白银主动进攻；
   - 彻底拦截散户假突破与诱多假三买。
"""

from __future__ import annotations

import math
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd


def calculate_causal_ofi_zscore(df: pd.DataFrame, window: int = 20) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算因果微观订单流失衡 (OFI) 与 Z-Score
    OFI = Volume * sign(Close - Open) + 0.5 * Delta_OI * sign(Close - Close_{t-1})
    """
    close = df["close"].astype(float).values
    open_p = df["open"].astype(float).values
    vol = df.get("volume", pd.Series(np.zeros(len(df)))).astype(float).values
    oi = df.get("open_interest", pd.Series(np.zeros(len(df)))).astype(float).values
    n = len(df)

    ofi_raw = np.zeros(n)
    for t in range(1, n):
        c_dir = 1.0 if close[t] > open_p[t] else (-1.0 if close[t] < open_p[t] else 0.0)
        p_dir = 1.0 if close[t] > close[t - 1] else (-1.0 if close[t] < close[t - 1] else 0.0)
        delta_oi = oi[t] - oi[t - 1]

        # 主动进攻力量估算
        ofi_raw[t] = vol[t] * c_dir + 0.3 * delta_oi * p_dir

    # 计算因果滑动 Z-Score
    ofi_zscore = np.zeros(n)
    for t in range(window, n):
        w = ofi_raw[t - window + 1:t + 1]
        mean_w = np.mean(w)
        std_w = np.std(w, ddof=1)
        if std_w > 1e-6:
            ofi_zscore[t] = (ofi_raw[t] - mean_w) / std_w
        else:
            ofi_zscore[t] = 0.0

    return ofi_raw, ofi_zscore


def calculate_causal_volume_density(df: pd.DataFrame, window: int = 40, n_bins: int = 15) -> np.ndarray:
    """
    计算当前价格所处局部成交量分布拓扑的相对密度 (Volume Density)
    低密度 (<= 0.55): 处于真空区 (LVN)，阻力极小，适合动量加速；
    高密度 (>= 1.20): 处于势阱区 (HVN)，阻力巨大，适合震荡落袋。
    """
    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    vol = df.get("volume", pd.Series(np.ones(len(df)))).astype(float).values
    n = len(df)

    vol_density = np.ones(n)

    for t in range(window, n):
        w_high = high[t - window + 1:t + 1]
        w_low = low[t - window + 1:t + 1]
        w_vol = vol[t - window + 1:t + 1]

        min_p = np.min(w_low)
        max_p = np.max(w_high)
        if max_p - min_p < 1e-6:
            vol_density[t] = 1.0
            continue

        bin_width = (max_p - min_p) / n_bins
        bin_vols = np.zeros(n_bins)

        for i in range(window):
            # 将每根 Bar 的成交量均匀投影至其高低跨越的 bin 中
            b_low = w_low[i]
            b_high = w_high[i]
            v = w_vol[i]

            idx_low = int(np.clip((b_low - min_p) / bin_width, 0, n_bins - 1))
            idx_high = int(np.clip((b_high - min_p) / bin_width, 0, n_bins - 1))

            span = max(1, idx_high - idx_low + 1)
            bin_vols[idx_low:idx_high + 1] += v / span

        # 计算当前最新价格所在的 bin 密度相对平均密度的比率
        curr_p = close[t]
        curr_bin_idx = int(np.clip((curr_p - min_p) / bin_width, 0, n_bins - 1))
        avg_vol = np.mean(bin_vols)
        if avg_vol > 1e-6:
            vol_density[t] = float(bin_vols[curr_bin_idx] / avg_vol)
        else:
            vol_density[t] = 1.0

    return vol_density


def extract_microstructure_features(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """提取微观结构完整特征矩阵"""
    res = pd.DataFrame(index=df.index)
    _, ofi_z = calculate_causal_ofi_zscore(df, window=window)
    vol_dens = calculate_causal_volume_density(df, window=window * 2)

    res["ofi_zscore"] = ofi_z
    res["vol_density"] = vol_dens
    return res
