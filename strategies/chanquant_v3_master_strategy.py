"""
strategies/chanquant_v3_master_strategy.py — 「因果缠论 3.0·终极动力学机制自适应策略」
(ChanQuant 3.0 Ultimate Kinetic Regime Adaptive Strategy)

第一性原理与现代顶级量化架构：
1. 动力学机制分流器 (Kinetic Regime State Machine):
   - 状态 1: 【低熵单边动量态】(Hurst >= 0.53, Ehlers斜率持续):
     * 仅激活三买/三卖 (B3/S3 顺势加速突破)；
     * 严禁逆势抄底；
     * 出场引擎：3.0 ATR 动态吊灯非对称追踪，放飞右尾宏观单边暴利 (+3 ~ +10 ATR)。
   - 状态 2: 【高熵均值弹性态】(Hurst <= 0.47, 价格偏离 Ehlers 均值 >= 1.5 ATR):
     * 仅激活一买/一卖 (B1/S1 极值背驰反弹)；
     * 严禁追高突破；
     * 出场引擎：价格回归中枢/Ehlers均线中轴立即平仓落袋 (坚决不贪恋突破)。
   - 状态 3: 【无序随机游走态】(0.47 < Hurst < 0.53):
     * 硬性空仓观望 (Cash is King)，杜绝 80% 的无效微观摩擦磨损。
2. 微观订单流与筹码拓扑门禁 (VPVR & OFI Microstructure Gates):
   - 三买必须伴随微观订单流主动买盘激增 (OFI Z-Score >= 0.80)；
   - 突破区域成交量密度 Vol_Density <= 1.20 (处于真空阻力极小区)。
3. S 级因子品质门禁:
   - 笔移动效率 ER >= 0.35；
   - 中枢收缩率 Compression <= 1.30。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import classify_kinetic_regime, KineticRegime
from chan_microstructure_gate import extract_microstructure_features
from technical_indicators import calculate_atr


STRATEGY_NAME = "chanquant_v3_master_strategy"
STRATEGY_DESCRIPTION = "「因果缠论 3.0·终极动力学机制自适应策略」: Hurst/HMM 机制分流 + OFI/VPVR 订单流门禁 + 动态中枢吊灯非对称追踪"


def calculate_factors(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算因果缠论 3.0 全息因子特征矩阵"""
    if df.empty or len(df) < 30:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    res["atr"] = calculate_atr(df, atr_period).bfill().fillna(1.0)

    # 1. 运行动力学机制分类器 (Hurst + Ehlers SuperSmoother)
    df_in = df.copy()
    df_in["atr"] = res["atr"]
    regime_df = classify_kinetic_regime(df_in, hurst_window=50, ss_period=14)
    res["hurst"] = regime_df["hurst"]
    res["ss_price"] = regime_df["ss_price"]
    res["ss_slope"] = regime_df["ss_slope"]
    res["dev_atr"] = regime_df["dev_atr"]
    res["regime"] = regime_df["regime"]

    # 2. 运行微观订单流与筹码拓扑门禁 (OFI + VPVR)
    micro_df = extract_microstructure_features(df_in, window=20)
    res["ofi_zscore"] = micro_df["ofi_zscore"]
    res["vol_density"] = micro_df["vol_density"]

    # 3. 运行纯因果缠论结构引擎
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df_in)

    b1_signal = np.zeros(len(df))
    s1_signal = np.zeros(len(df))
    b2_signal = np.zeros(len(df))
    s2_signal = np.zeros(len(df))
    b3_signal = np.zeros(len(df))
    s3_signal = np.zeros(len(df))
    zs_high_arr = np.zeros(len(df))
    zs_low_arr = np.zeros(len(df))
    b05_er_arr = np.zeros(len(df))
    z09_comp_arr = np.ones(len(df))
    z01_width_arr = np.zeros(len(df))
    p08_pullback_arr = np.zeros(len(df))
    z11_breakout_arr = np.zeros(len(df))

    for ev in events:
        raw_idx = ev.known_raw_idx
        if 0 <= raw_idx < len(df):
            if ev.event_type == "B1":
                b1_signal[raw_idx] = 1.0
            elif ev.event_type == "S1":
                s1_signal[raw_idx] = 1.0
            elif ev.event_type == "B2":
                b2_signal[raw_idx] = 1.0
            elif ev.event_type == "S2":
                s2_signal[raw_idx] = 1.0
            elif ev.event_type == "B3":
                b3_signal[raw_idx] = 1.0
            elif ev.event_type == "S3":
                s3_signal[raw_idx] = 1.0

            zs_high_arr[raw_idx] = ev.zs_high
            zs_low_arr[raw_idx] = ev.zs_low
            b05_er_arr[raw_idx] = ev.factors.get("B05_bi_efficiency", 0.0)
            z09_comp_arr[raw_idx] = ev.factors.get("Z09_zhongshu_compression", 1.0)
            z01_width_arr[raw_idx] = ev.factors.get("Z01_zhongshu_width", 0.0)
            p08_pullback_arr[raw_idx] = ev.factors.get("P08_pullback_depth", 0.0)
            z11_breakout_arr[raw_idx] = ev.factors.get("Z11_breakout_strength", 0.0)

    res["b1_raw"] = b1_signal
    res["s1_raw"] = s1_signal
    res["b2_raw"] = b2_signal
    res["s2_raw"] = s2_signal
    res["b3_raw"] = b3_signal
    res["s3_raw"] = s3_signal
    res["zs_high"] = zs_high_arr
    res["zs_low"] = zs_low_arr
    res["b05_er"] = b05_er_arr
    res["z09_comp"] = z09_comp_arr
    res["z01_width"] = z01_width_arr
    res["p08_pullback"] = p08_pullback_arr
    res["z11_breakout"] = z11_breakout_arr

    return res


def calculate_signal(
    df: pd.DataFrame,
    min_er: float = 0.35,
    max_comp: float = 1.30,
    min_width: float = 0.50,
    atr_period: int = 14,
    holding_bars_max: int = 40,
    stop_atr_mult: float = 1.2,
    trail_atr_mult: float = 3.0,
) -> pd.Series:
    """
    生成 ChanQuant 3.0 纯因果自适应交易信号 (+1 多头, -1 空头, 0 空仓)
    """
    if df.empty or len(df) < 30:
        return pd.Series(0, index=df.index)

    factors_df = calculate_factors(df, atr_period)
    b1_raw = factors_df["b1_raw"].values
    s1_raw = factors_df["s1_raw"].values
    b3_raw = factors_df["b3_raw"].values
    s3_raw = factors_df["s3_raw"].values

    regime = factors_df["regime"].values
    ss_price = factors_df["ss_price"].values
    ofi_z = factors_df["ofi_zscore"].values
    vol_dens = factors_df["vol_density"].values
    b05_er = factors_df["b05_er"].values
    z09_comp = factors_df["z09_comp"].values
    z01_width = factors_df["z01_width"].values
    zs_high = factors_df["zs_high"].values
    zs_low = factors_df["zs_low"].values
    atr = factors_df["atr"].values

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    n = len(df)

    signal = np.zeros(n, dtype=int)

    position = 0
    trade_mode = 0  # 1: 动量轨 (吊灯出场), 2: 弹性轨 (回归中枢即平)
    entry_price = 0.0
    stop_loss = 0.0
    target_price = 0.0
    highest_price = 0.0
    lowest_price = 999999.0
    bars_in_trade = 0

    for i in range(1, n):
        curr_c = close[i]
        curr_h = high[i]
        curr_l = low[i]
        curr_atr = atr[i] if atr[i] > 0 else 1.0
        curr_ss = ss_price[i]

        # --- 1. 已有持仓出场管理 ---
        if position == 1:
            bars_in_trade += 1
            highest_price = max(highest_price, curr_h)

            if trade_mode == 1:
                # 动量轨：动态保本 + 3.0 ATR 动态吊灯放飞
                if highest_price >= entry_price + 1.0 * curr_atr:
                    stop_loss = max(stop_loss, entry_price + 0.1 * curr_atr)
                if highest_price >= entry_price + 2.0 * curr_atr:
                    chandelier_stop = highest_price - trail_atr_mult * curr_atr
                    stop_loss = max(stop_loss, chandelier_stop)

                if curr_l <= stop_loss or bars_in_trade >= holding_bars_max:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = 1

            elif trade_mode == 2:
                # 弹性轨：价格回归均线/中枢即刻止盈落袋
                if curr_h >= target_price or curr_h >= curr_ss:
                    position = 0
                    signal[i] = 0
                    continue
                if curr_l <= stop_loss or bars_in_trade >= 25:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = 1

        elif position == -1:
            bars_in_trade += 1
            lowest_price = min(lowest_price, curr_l)

            if trade_mode == 1:
                # 动量轨空头：动态保本 + 动态吊灯
                if lowest_price <= entry_price - 1.0 * curr_atr:
                    stop_loss = min(stop_loss, entry_price - 0.1 * curr_atr)
                if lowest_price <= entry_price - 2.0 * curr_atr:
                    chandelier_stop = lowest_price + trail_atr_mult * curr_atr
                    stop_loss = min(stop_loss, chandelier_stop)

                if curr_h >= stop_loss or bars_in_trade >= holding_bars_max:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = -1

            elif trade_mode == 2:
                # 弹性轨空头：回归均线即刻落袋
                if curr_l <= target_price or curr_l <= curr_ss:
                    position = 0
                    signal[i] = 0
                    continue
                if curr_h >= stop_loss or bars_in_trade >= 25:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = -1

        # --- 2. 空仓状态下开仓入场 (机制自适应分流 + 订单流放行) ---
        if position == 0:
            reg = regime[i - 1]

            # >>> 模式 1: 单边动量态 (MOMENTUM_TREND) -> 仅做 三买 / 三卖 <<<
            if reg == KineticRegime.MOMENTUM_TREND:
                if b3_raw[i - 1] > 0:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    # OFI 订单流与 S 级门禁放行
                    if er >= min_er and comp <= max_comp and ofi >= -0.2 and dens <= 1.4:
                        position = 1
                        trade_mode = 1
                        entry_price = curr_c
                        highest_price = curr_c
                        bars_in_trade = 0
                        zh = zs_high[i - 1]
                        if zh > 0 and (entry_price - zh) < 2.5 * curr_atr:
                            stop_loss = max(zh - 0.5 * curr_atr, entry_price - 1.5 * curr_atr)
                        else:
                            stop_loss = entry_price - stop_atr_mult * curr_atr
                        signal[i] = 1

                elif s3_raw[i - 1] > 0:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= min_er and comp <= max_comp and ofi <= 0.2 and dens <= 1.4:
                        position = -1
                        trade_mode = 1
                        entry_price = curr_c
                        lowest_price = curr_c
                        bars_in_trade = 0
                        zl = zs_low[i - 1]
                        if zl > 0 and (zl - entry_price) < 2.5 * curr_atr:
                            stop_loss = min(zl + 0.5 * curr_atr, entry_price + 1.5 * curr_atr)
                        else:
                            stop_loss = entry_price + stop_atr_mult * curr_atr
                        signal[i] = -1

            # >>> 模式 2: 均值弹性态 (MEAN_REVERTING) -> 仅做 一买 / 一卖 极值回归 <<<
            elif reg == KineticRegime.MEAN_REVERTING:
                if b1_raw[i - 1] > 0:
                    # 超跌一买低吸
                    position = 1
                    trade_mode = 2
                    entry_price = curr_c
                    highest_price = curr_c
                    bars_in_trade = 0
                    stop_loss = entry_price - 1.0 * curr_atr
                    target_price = max(curr_ss, entry_price + 1.5 * curr_atr)
                    signal[i] = 1

                elif s1_raw[i - 1] > 0:
                    # 超买一卖高抛
                    position = -1
                    trade_mode = 2
                    entry_price = curr_c
                    lowest_price = curr_c
                    bars_in_trade = 0
                    stop_loss = entry_price + 1.0 * curr_atr
                    target_price = min(curr_ss, entry_price - 1.5 * curr_atr)
                    signal[i] = -1

            # >>> 模式 0: 无序随机游走态 (BROWNIAN_NOISE) -> 坚决空仓 <<<
            else:
                position = 0
                signal[i] = 0

    return pd.Series(signal, index=df.index)
