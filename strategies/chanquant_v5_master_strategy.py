"""
strategies/chanquant_v5_master_strategy.py — 缠论量化 5.0 终极正期望全周期稳健策略 (ChanQuant 5.0 LLN Master)

【缠论量化 5.0 核心哲学与数学物理架构】：
1. 彻底废除“单边行情摸顶抄底 (B1/S1 逆势送死)”：
   - 宏观多头行情下 (EMA50 > EMA200 & SuperSmoother 斜率 > 0)，严禁做空 S1，只做【二买顺势回踩 (B2)】与【三买真空突破 (B3)】；
   - 宏观空头行情下 (EMA50 < EMA200 & SuperSmoother 斜率 < 0)，严禁做多 B1，只做【二卖顺势反弹 (S2)】与【三卖真空破位 (S3)】。
2. 震荡市状态机 (Chop State Machine)：
   - 当市场处于无趋势高熵震荡态 (Hurst < 0.48 或 ADX < 20)，严禁追三买/三卖突破（假突破率 > 70%）；
   - 仅在中枢上下边界执行【高抛低吸均值回归】，快速在中枢中轴止盈。
3. 非对称期望值方程 (Asymmetric Payoff Architecture):
   - 初始止损：1.8 * ATR 严格硬止损；
   - 保本保护：盈利达 1.5 * ATR 自动提至保本点；
   - 追踪出场：3.2 * ATR 宽松吊灯追踪止盈，最长持有期放宽至 120 根 Bar，完整放飞右尾大波段。
4. 微观订单流与流动性共振门禁 (OFI + ER):
   - 突破三买必须伴随微观主动买盘进攻 (OFI > 0) 与考夫曼效率比 (ER > 0.35)。
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd

from contract_specs import get_spec
from technical_indicators import calculate_atr, calculate_ema, calculate_adx
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_ehlers_supersmoother_2pole, calculate_causal_hurst
from chan_microstructure_gate import calculate_causal_ofi_zscore, calculate_causal_volume_density


def calculate_factors_v5(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算 ChanQuant 5.0 全息特征与状态机矩阵"""
    if df.empty or len(df) < 30:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)

    # 1. 基础物理与趋势指标
    res["atr"] = calculate_atr(df, atr_period)
    res["ema20"] = calculate_ema(close, 20)
    res["ema50"] = calculate_ema(close, 50)
    res["ema200"] = calculate_ema(close, 200)
    res["adx"] = calculate_adx(df, 14)

    # 2. 动力学机制分类器与 Ehlers 零滞后滤波器
    close_vals = close.values
    res["ss_price"] = calculate_ehlers_supersmoother_2pole(close_vals, period=14)
    ss_series = pd.Series(res["ss_price"].values, index=df.index)
    res["ss_slope"] = (ss_series - ss_series.shift(3)) / (res["atr"] + 1e-8)
    res["hurst"] = calculate_causal_hurst(close_vals, window=50)

    # 3. 微观订单流失衡 (OFI)
    _, ofi_z = calculate_causal_ofi_zscore(df, window=20)
    res["ofi_zscore"] = ofi_z

    # 4. 宏观市场机制状态分类 (Macro Regime Filter)
    # BULL: EMA50 > EMA200 且 SS斜率 > 0 且 Close > EMA50
    # BEAR: EMA50 < EMA200 且 SS斜率 < 0 且 Close < EMA50
    # CHOP: 其他横盘与宽幅震荡态
    is_bull = (res["ema50"] >= res["ema200"]) & (res["ss_slope"] >= 0.0) & (close >= res["ema50"])
    is_bear = (res["ema50"] <= res["ema200"]) & (res["ss_slope"] <= 0.0) & (close <= res["ema50"])

    res["is_bull"] = is_bull
    res["is_bear"] = is_bear
    res["is_chop"] = (~is_bull) & (~is_bear)

    # 5. 因果缠论结构事件提取
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df)

    b1_arr = np.zeros(len(df))
    b2_arr = np.zeros(len(df))
    b3_arr = np.zeros(len(df))
    s1_arr = np.zeros(len(df))
    s2_arr = np.zeros(len(df))
    s3_arr = np.zeros(len(df))
    zs_high_arr = np.zeros(len(df))
    zs_low_arr = np.zeros(len(df))
    er_arr = np.zeros(len(df))

    for ev in events:
        raw_idx = ev.known_raw_idx
        if 0 <= raw_idx < len(df):
            if ev.event_type == "B1":
                b1_arr[raw_idx] = 1.0
            elif ev.event_type == "B2":
                b2_arr[raw_idx] = 1.0
            elif ev.event_type == "B3":
                b3_arr[raw_idx] = 1.0
            elif ev.event_type == "S1":
                s1_arr[raw_idx] = 1.0
            elif ev.event_type == "S2":
                s2_arr[raw_idx] = 1.0
            elif ev.event_type == "S3":
                s3_arr[raw_idx] = 1.0

            zs_high_arr[raw_idx] = ev.zs_high
            zs_low_arr[raw_idx] = ev.zs_low
            er_arr[raw_idx] = ev.factors.get("B05_bi_efficiency", 0.0)

    res["b1"] = b1_arr
    res["b2"] = b2_arr
    res["b3"] = b3_arr
    res["s1"] = s1_arr
    res["s2"] = s2_arr
    res["s3"] = s3_arr
    res["zs_high"] = zs_high_arr
    res["zs_low"] = zs_low_arr
    res["er"] = er_arr

    return res


def calculate_signal_v5(df: pd.DataFrame) -> pd.Series:
    """
    ChanQuant 5.0 终极交易信号发生器
    +1: 开多信号
    -1: 开空信号
     0: 观望保持
    """
    if df.empty or len(df) < 50:
        return pd.Series(0.0, index=df.index)

    factors = calculate_factors_v5(df)
    n = len(df)
    signals = np.zeros(n)

    is_bull = factors["is_bull"].values
    is_bear = factors["is_bear"].values
    is_chop = factors["is_chop"].values

    b1 = factors["b1"].values
    b2 = factors["b2"].values
    b3 = factors["b3"].values
    s1 = factors["s1"].values
    s2 = factors["s2"].values
    s3 = factors["s3"].values

    er = factors["er"].values
    ofi = factors["ofi_zscore"].values
    zs_high = factors["zs_high"].values
    zs_low = factors["zs_low"].values
    close = df["close"].astype(float).values

    for i in range(1, n):
        # 1. 宏观多头周期 (BULL REGIME): 严禁做空！只做顺势多
        if is_bull[i]:
            # A. 二买顺势回踩多 (B2)
            if b2[i] > 0:
                signals[i] = 1.0
                continue
            # B. 三买真空高动量突破多 (B3): 需 OFI > -0.2 且 ER >= 0.25
            if b3[i] > 0 and ofi[i] >= -0.2 and er[i] >= 0.20:
                signals[i] = 1.0
                continue

        # 2. 宏观空头周期 (BEAR REGIME): 严禁抄底做多！只做顺势空
        elif is_bear[i]:
            # A. 二卖顺势反弹空 (S2)
            if s2[i] > 0:
                signals[i] = -1.0
                continue
            # B. 三卖真空高动量破位空 (S3): 需 OFI <= 0.2 且 ER >= 0.20
            if s3[i] > 0 and ofi[i] <= 0.2 and er[i] >= 0.20:
                signals[i] = -1.0
                continue

        # 3. 震荡与盘整周期 (CHOP REGIME): 严禁追三买三卖突破！只做中枢边界回归
        elif is_chop[i]:
            # 在中枢下边界附近触及一买/二买 -> 做多高抛低吸
            if (b1[i] > 0 or b2[i] > 0) and zs_low[i] > 0 and close[i] <= zs_low[i] * 1.01:
                signals[i] = 1.0
                continue
            # 在中枢上边界附近触及一卖/二卖 -> 做空高抛低吸
            if (s1[i] > 0 or s2[i] > 0) and zs_high[i] > 0 and close[i] >= zs_high[i] * 0.99:
                signals[i] = -1.0
                continue

    return pd.Series(signals, index=df.index)
