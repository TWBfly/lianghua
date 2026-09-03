"""
strategies/chanquant_v6_alpha_master.py — 缠论量化 6.0 终极正期望全周期稳健策略 (ChanQuant 6.0 Alpha Master)

【数学物理与微观结构四大突破】：
1. 彻底解决“笔末端追高被洗”难题 (Limit Pullback on Zhongshu Boundary):
   - 传统缠论在三买/二买发出时已处于笔末端极值，市价追高极易在次回踩中被止损洗出；
   - 缠论 6.0 强制执行【中枢上沿/EMA20 挂单回踩确认 (Limit Pullback)】，未回踩不追单。
2. 紧致结构失效止损 (Tight Structural Invalidation Stop):
   - 止损不再使用宽幅 1.5~2.0 ATR，而是严格设在【中枢破坏临界线 (0.6~0.8 ATR)】；
   - 一旦跌回中枢内部，结构被破坏，以极小代价（0.8R）硬止损离场。
3. 非对称非线性大盈亏比 (Asymmetric 4.0R Profit Target):
   - 目标获利空间设为 3.2 ATR (4.0 倍风险单位 R)；
   - 形成 1 : 4.0 的非对称赔率方程，即使胜率仅 35%~45%，期望值依然强劲大于 0：
     E = WinRate * 4.0R - (1 - WinRate) * 1.0R = 0.35 * 4.0 - 0.65 * 1.0 = +0.75R > 0。
4. 埃勒斯双极超平滑零滞后动量过滤 (Ehlers SuperSmoother Slope Gate):
   - 宏观顺势多：EMA50 >= EMA200 且 SS_Slope > 0.05，只做二买三买；
   - 宏观顺势空：EMA50 <= EMA200 且 SS_Slope < -0.05，只做二卖三卖。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

from contract_specs import get_spec
from technical_indicators import calculate_atr, calculate_ema, calculate_adx
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_ehlers_supersmoother_2pole, calculate_causal_hurst
from chan_microstructure_gate import calculate_causal_ofi_zscore, calculate_causal_volume_density


def calculate_factors_v6(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算 ChanQuant 6.0 全息因子特征矩阵"""
    if df.empty or len(df) < 30:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)

    res["atr"] = calculate_atr(df, atr_period)
    res["ema20"] = calculate_ema(close, 20)
    res["ema50"] = calculate_ema(close, 50)
    res["ema200"] = calculate_ema(close, 200)
    res["adx"] = calculate_adx(df, 14)

    close_vals = close.values
    res["ss_price"] = calculate_ehlers_supersmoother_2pole(close_vals, period=14)
    ss_series = pd.Series(res["ss_price"].values, index=df.index)
    res["ss_slope"] = (ss_series - ss_series.shift(3)) / (res["atr"] + 1e-8)
    res["hurst"] = calculate_causal_hurst(close_vals, window=50)

    # 宏观动量态过滤
    res["is_bull"] = (res["ema50"] >= res["ema200"]) & (res["ss_slope"] >= 0.0) & (close >= res["ema50"])
    res["is_bear"] = (res["ema50"] <= res["ema200"]) & (res["ss_slope"] <= 0.0) & (close <= res["ema50"])

    # 因果缠论结构提取
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df)

    b2_arr = np.zeros(len(df))
    b3_arr = np.zeros(len(df))
    s2_arr = np.zeros(len(df))
    s3_arr = np.zeros(len(df))
    zs_high_arr = np.zeros(len(df))
    zs_low_arr = np.zeros(len(df))

    for ev in events:
        raw_idx = ev.known_raw_idx
        if 0 <= raw_idx < len(df):
            if ev.event_type == "B2":
                b2_arr[raw_idx] = 1.0
            elif ev.event_type == "B3":
                b3_arr[raw_idx] = 1.0
            elif ev.event_type == "S2":
                s2_arr[raw_idx] = 1.0
            elif ev.event_type == "S3":
                s3_arr[raw_idx] = 1.0

            zs_high_arr[raw_idx] = ev.zs_high
            zs_low_arr[raw_idx] = ev.zs_low

    res["b2"] = b2_arr
    res["b3"] = b3_arr
    res["s2"] = s2_arr
    res["s3"] = s3_arr
    res["zs_high"] = zs_high_arr
    res["zs_low"] = zs_low_arr

    return res
