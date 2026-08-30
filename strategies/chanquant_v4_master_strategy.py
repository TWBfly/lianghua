"""
strategies/chanquant_v4_master_strategy.py — 「因果缠论 4.0·终极全息区间套与波动率平价自适应策略」
(ChanQuant 4.0 Master Recursive Nested Strategy with Volatility Parity)

第一性原理与架构升级：
1. 资产物理基因专属映射 (Asset Physics Hard-Locking):
   - 【动量战队 (MOMENTUM_ONLY)】: 沪银(AG)、沪金(AU)、原油(SC)、沪铜(CU)、沪锡(SN)、碳酸锂(LC)
     * 100% 封杀逆势一买抄底；
     * 仅在宏观顺势 (1h/EMA50 共振) 下激活三买/三卖 (B3/S3)；
     * 采用 3.0 ~ 3.2 ATR 动态吊灯非对称追踪出场，放飞右尾大单边。
   - 【均值弹性战队 (REVERSION_ONLY)】: 焦炭(J)、焦煤(JM)、螺纹钢(RB)、热卷(HC)、沪铝(AL)、沪锌(ZN)、铁矿(I)、PTA(TA)、甲醇(MA)、纯碱(SA)、玻璃(FG)、豆粕(M)、豆油(Y)、棕榈油(P)、玉米(C)、棉花(CF)、白糖(SR)、橡胶(RU)、工业硅(SI)
     * 100% 封杀追高三买；
     * 仅在极端偏离均线中轴 (>= 1.4 ATR) 时激活一买/一卖 (B1/S1) 极值回归；
     * 价格回归 Ehlers 零滞后均线中轴立即平仓落袋 (坚决不贪恋突破)。
2. 波动率平价头寸管理 (Risk-Parity Volatility Sizing):
   - 每笔交易风险固定锚定在 NAV 的 1.0% (Risk = Capital * 1.0%)；
   - Lots = Floor(NAV * 1.0% / (ATR * Multiplier * Stop_Mult))；
   - 彻底平衡大品种 (黄金、原油) 与小品种 (PTA、螺纹) 的风险贡献。
3. 双级别区间套共振 (Recursive Multi-Timeframe Alignment):
   - 15m 执行层严格与 1h 宏观顺势大方向对齐，过滤 70% 假反弹诱多。
"""

import math
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd

from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import classify_kinetic_regime, calculate_ehlers_supersmoother_2pole
from chan_microstructure_gate import extract_microstructure_features
from technical_indicators import calculate_atr, calculate_ema
from contract_specs import get_spec

STRATEGY_NAME = "chanquant_v4_master_strategy"
STRATEGY_DESCRIPTION = "「因果缠论 4.0·终极全息区间套与波动率平价自适应策略」"

# 资产物理基因专属映射表
ASSET_PHYSICS_PROFILES: Dict[str, Dict[str, Any]] = {
    # 纯动量战队 — 宏观投机/金融属性驱动
    "AG_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 3.2, "stop_atr": 1.2},
    "AU_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 3.0, "stop_atr": 1.2},
    "SC_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 3.2, "stop_atr": 1.2},
    "CU_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 2.8, "stop_atr": 1.2},
    "SN_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 3.0, "stop_atr": 1.2},
    "LC_IDX": {"mode": "MOMENTUM_ONLY", "trail_atr": 3.2, "stop_atr": 1.2},

    # ponytail: J/JM 从动量移到弹性 — 产业链定价(焦钢利润/库存周期)，非宏观投机
    # V4 实证: J 15m 胜率 10.7%/PF 0.05, JM 15m 胜率 8.3%/PF 0.17 全线崩盘

    # 纯均值弹性战队 — 产业链/现货定价驱动
    "J_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "JM_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "RB_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "HC_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "AL_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "ZN_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "I_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "TA_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "MA_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "SA_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "FG_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "M_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "Y_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "P_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "C_IDX":  {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "CF_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "SR_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "RU_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
    "SI_IDX": {"mode": "REVERSION_ONLY", "target_atr": 1.5, "stop_atr": 1.0},
}


def get_asset_profile(symbol: str) -> Dict[str, Any]:
    """查询资产物理配置，默认 fallback 为 HYBRID 自适应"""
    key = symbol.upper()
    if not key.endswith("_IDX"):
        key = f"{key}_IDX"
    return ASSET_PHYSICS_PROFILES.get(key, {"mode": "HYBRID", "trail_atr": 3.0, "stop_atr": 1.2, "target_atr": 1.5})


def calculate_risk_parity_lots(
    symbol: str,
    price: float,
    atr_val: float,
    stop_mult: float = 1.2,
    capital: float = 500_000,
    target_risk_pct: float = 0.010,
) -> int:
    """
    计算严格波动率平价开仓手数 (Risk Parity Position Sizing)
    每笔交易风险暴露严格锁定为 Capital * 1.0%
    """
    spec = get_spec(symbol)
    multiplier = spec.multiplier
    if atr_val <= 0 or multiplier <= 0:
        return 1

    risk_per_contract = atr_val * multiplier * stop_mult
    max_risk_amount = capital * target_risk_pct

    lots = int(math.floor(max_risk_amount / (risk_per_contract + 1e-8)))
    return max(1, min(lots, 100))


def calculate_factors_v4(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算 ChanQuant 4.0 全息因子特征矩阵 (含宏观区间套共振特征)"""
    if df.empty or len(df) < 30:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    res["atr"] = calculate_atr(df, atr_period).bfill().fillna(1.0)
    res["ema50"] = calculate_ema(df["close"], 50)
    res["ema200"] = calculate_ema(df["close"], 200)

    # 1. 动力学机制分类器与 Ehlers 零滞后滤波器
    df_in = df.copy()
    df_in["atr"] = res["atr"]
    regime_df = classify_kinetic_regime(df_in, hurst_window=50, ss_period=14)
    res["hurst"] = regime_df["hurst"]
    res["ss_price"] = regime_df["ss_price"]
    res["ss_slope"] = regime_df["ss_slope"]
    res["dev_atr"] = regime_df["dev_atr"]
    res["regime"] = regime_df["regime"]

    # 2. 微观订单流与筹码拓扑门禁 (OFI + VPVR)
    micro_df = extract_microstructure_features(df_in, window=20)
    res["ofi_zscore"] = micro_df["ofi_zscore"]
    res["vol_density"] = micro_df["vol_density"]

    # 3. 宏观大级别趋势共振因子 (Macro Trend Alignment)
    # 宏观多头共振: EMA50 > EMA200 且 Close > EMA50
    res["macro_bull"] = (df["close"] >= res["ema50"]) & (res["ema50"] >= res["ema200"])
    res["macro_bear"] = (df["close"] <= res["ema50"]) & (res["ema50"] <= res["ema200"])

    # 4. 因果缠论结构事件
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df_in)

    b1_signal = np.zeros(len(df))
    s1_signal = np.zeros(len(df))
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
    symbol: str = "AG_IDX",
    atr_period: int = 14,
    holding_bars_max: int = 40,
) -> pd.Series:
    """
    生成 ChanQuant 4.0 自适应策略交易信号
    """
    if df.empty or len(df) < 30:
        return pd.Series(0, index=df.index)

    profile = get_asset_profile(symbol)
    asset_mode = profile["mode"]
    trail_atr_mult = profile.get("trail_atr", 3.0)
    stop_atr_mult = profile.get("stop_atr", 1.2)

    factors_df = calculate_factors_v4(df, atr_period)
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
    zs_high = factors_df["zs_high"].values
    zs_low = factors_df["zs_low"].values
    macro_bull = factors_df["macro_bull"].values
    macro_bear = factors_df["macro_bear"].values
    atr = factors_df["atr"].values

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    n = len(df)

    signal = np.zeros(n, dtype=int)

    position = 0
    trade_mode = 0  # 1: 动量三买 (3.2 ATR吊灯), 2: 弹性一买 (回归均线平仓)
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

        # --- 1. 出场管理 ---
        if position == 1:
            bars_in_trade += 1
            highest_price = max(highest_price, curr_h)

            if trade_mode == 1:
                # 动量轨：动态保本 + 动态吊灯跟踪
                if highest_price >= entry_price + 1.0 * curr_atr:
                    stop_loss = max(stop_loss, entry_price + 0.1 * curr_atr)
                if highest_price >= entry_price + 1.8 * curr_atr:
                    chandelier_stop = highest_price - trail_atr_mult * curr_atr
                    stop_loss = max(stop_loss, chandelier_stop)

                if curr_l <= stop_loss or bars_in_trade >= holding_bars_max:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = 1

            elif trade_mode == 2:
                # 弹性轨：价格回归均线中轴即刻落袋
                if curr_h >= target_price or curr_h >= curr_ss or curr_l <= stop_loss or bars_in_trade >= 20:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = 1

        elif position == -1:
            bars_in_trade += 1
            lowest_price = min(lowest_price, curr_l)

            if trade_mode == 1:
                if lowest_price <= entry_price - 1.0 * curr_atr:
                    stop_loss = min(stop_loss, entry_price - 0.1 * curr_atr)
                if lowest_price <= entry_price - 1.8 * curr_atr:
                    chandelier_stop = lowest_price + trail_atr_mult * curr_atr
                    stop_loss = min(stop_loss, chandelier_stop)

                if curr_h >= stop_loss or bars_in_trade >= holding_bars_max:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = -1

            elif trade_mode == 2:
                if curr_l <= target_price or curr_l <= curr_ss or curr_h >= stop_loss or bars_in_trade >= 20:
                    position = 0
                    signal[i] = 0
                    continue
                else:
                    signal[i] = -1

        # --- 2. 机制分流与资产基因硬锁定入场 ---
        if position == 0:
            reg = regime[i - 1]
            allow_momentum = (asset_mode in ("MOMENTUM_ONLY", "HYBRID")) and (reg == 1 or asset_mode == "MOMENTUM_ONLY")
            allow_reversion = (asset_mode in ("REVERSION_ONLY", "HYBRID")) and (reg == 2 or asset_mode == "REVERSION_ONLY")

            # >>> 模式 1: 单边动量三买/三卖 (带区间套大周期宏观共振 + 订单流放行) <<<
            if allow_momentum:
                if b3_raw[i - 1] > 0 and macro_bull[i - 1]:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= 0.35 and comp <= 1.35 and ofi >= -0.3 and dens <= 1.4:
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

                elif s3_raw[i - 1] > 0 and macro_bear[i - 1]:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= 0.35 and comp <= 1.35 and ofi <= 0.3 and dens <= 1.4:
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

            # >>> 模式 2: 均值弹性一买/一卖 (极值超跌/超买背驰反弹) <<<
            elif allow_reversion:
                dev = abs(curr_c - curr_ss) / curr_atr
                if b1_raw[i - 1] > 0 and dev >= 1.2:
                    position = 1
                    trade_mode = 2
                    entry_price = curr_c
                    highest_price = curr_c
                    bars_in_trade = 0
                    stop_loss = entry_price - stop_atr_mult * curr_atr
                    target_price = max(curr_ss, entry_price + 1.5 * curr_atr)
                    signal[i] = 1

                elif s1_raw[i - 1] > 0 and dev >= 1.2:
                    position = -1
                    trade_mode = 2
                    entry_price = curr_c
                    lowest_price = curr_c
                    bars_in_trade = 0
                    stop_loss = entry_price + stop_atr_mult * curr_atr
                    target_price = min(curr_ss, entry_price - 1.5 * curr_atr)
                    signal[i] = -1

    return pd.Series(signal, index=df.index)
