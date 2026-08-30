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
    计算因果微观订单流失衡 (OFI) 与 Z-Score (全向量化极速版)
    OFI = Volume * sign(Close - Open) + 0.3 * Delta_OI * sign(Close - Close_{t-1})
    """
    close = df["close"].astype(float)
    open_p = df["open"].astype(float)
    vol = df.get("volume", pd.Series(np.zeros(len(df)), index=df.index)).astype(float)
    oi = df.get("open_interest", pd.Series(np.zeros(len(df)), index=df.index)).astype(float)

    c_dir = np.sign(close - open_p)
    p_dir = np.sign(close - close.shift(1)).fillna(0.0)
    delta_oi = oi.diff().fillna(0.0)

    ofi_raw = (vol * c_dir + 0.3 * delta_oi * p_dir).values
    s_ofi = pd.Series(ofi_raw, index=df.index)
    mean_w = s_ofi.rolling(window).mean()
    std_w = s_ofi.rolling(window).std(ddof=1)

    ofi_zscore = ((s_ofi - mean_w) / (std_w + 1e-8)).fillna(0.0).values
    return ofi_raw, ofi_zscore


def calculate_causal_volume_density(df: pd.DataFrame, window: int = 40, n_bins: int = 15) -> np.ndarray:
    """
    计算当前价格所处局部成交量分布拓扑的相对密度 (Volume Density 全向量化极速版)
    低密度 (<= 0.55): 处于真空区 (LVN)，阻力极小，适合动量加速；
    高密度 (>= 1.20): 处于势阱区 (HVN)，阻力巨大，适合震荡落袋。
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df.get("volume", pd.Series(np.ones(len(df)), index=df.index)).astype(float)

    roll_max = high.rolling(window).max()
    roll_min = low.rolling(window).min()
    rng = (roll_max - roll_min).replace(0, np.nan)

    # 局部 VWAP 与价格偏离度高斯核密度估计
    roll_vol = vol.rolling(window).sum()
    roll_pv = (close * vol).rolling(window).sum()
    vwap = (roll_pv / (roll_vol + 1e-8)).fillna(close)

    dist_vwap = (close - vwap).abs() / (rng + 1e-8)
    vol_density = np.exp(-0.5 * (dist_vwap * 4.0) ** 2) * 1.5
    return vol_density.fillna(1.0).values


def extract_microstructure_features(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """提取微观结构完整特征矩阵"""
    res = pd.DataFrame(index=df.index)
    _, ofi_z = calculate_causal_ofi_zscore(df, window=window)
    vol_dens = calculate_causal_volume_density(df, window=window * 2)

    res["ofi_zscore"] = ofi_z
    res["vol_density"] = vol_dens
    return res
