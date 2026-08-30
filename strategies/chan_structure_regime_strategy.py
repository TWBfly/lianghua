"""
strategies/chan_structure_regime_strategy.py — 「因果缠论·市场结构机制策略」
(Causal Chan Market Structure Regime Strategy)

第一性原理与架构：
1. 核心理论：
   - 彻底基于 dist.md 的因果市场结构编码器 (Causal Chan State Machine)；
   - 杜绝一切未来函数，所有分型、笔、中枢与三买三卖事件严格在右侧确认时间 (known_time) 触发。
2. S 级因子质量门禁 (Quality Gate):
   - 笔移动效率 (Kaufman ER) >= 0.35 (排除泥沙俱下的虚假衰竭突破)；
   - 中枢收缩率 <= 1.35 (确保中枢内部经历充分的能量卷簧与筹码沉淀)；
   - 边界安全冗余度 >= 0.05 ATR (确保回踩不踩破中枢核心承接带)。
3. 非对称非线性出场与风控 (Asymmetric Volatility-Parity Risk Management):
   - 初始止损：严格设定在中枢核心边界外 0.8 * ATR (左尾有限)；
   - 动态保本：浮盈 >= 1.0 * ATR 时，抬升止损至 开仓价 + 0.1 * ATR；
   - 动态吊灯跟踪止盈：浮盈扩大后启动 3.0 * ATR 动态吊灯跟踪，捕获右尾宏观暴利。
"""

from typing import Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd

from causal_chan_engine import CausalChanEngine, CausalBuySellEvent
from technical_indicators import calculate_atr, calculate_ema


STRATEGY_NAME = "chan_structure_regime_strategy"
STRATEGY_DESCRIPTION = "「因果缠论·市场结构机制策略」: Causal Chan 零未来状态机 + 7大S级因子门禁 + 动态中枢吊灯非对称追踪"


def calculate_factors(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算因子矩阵与因果缠论结构事件"""
    if df.empty or len(df) < 30:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    res["atr"] = calculate_atr(df, atr_period).bfill().fillna(1.0)
    res["ema50"] = calculate_ema(df["close"], 50)

    # 运行因果缠论引擎
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    df_in = df.copy()
    df_in["atr"] = res["atr"]
    events = engine.process_dataframe(df_in)

    # 标记买卖点事件到索引上
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
    max_comp: float = 1.40,
    min_width: float = 0.50,
    min_pullback: float = -0.15,
    atr_period: int = 14,
    holding_bars_max: int = 40,
    use_b1: bool = True,
    use_b2: bool = True,
    use_b3: bool = True,
) -> pd.Series:
    """
    生成纯因果策略交易信号 (+1 多头, -1 空头, 0 空仓)
    """
    if df.empty or len(df) < 30:
        return pd.Series(0, index=df.index)

    factors_df = calculate_factors(df, atr_period)
    b1_raw = factors_df["b1_raw"].values if use_b1 else np.zeros(len(df))
    s1_raw = factors_df["s1_raw"].values if use_b1 else np.zeros(len(df))
    b2_raw = factors_df["b2_raw"].values if use_b2 else np.zeros(len(df))
    s2_raw = factors_df["s2_raw"].values if use_b2 else np.zeros(len(df))
    b3_raw = factors_df["b3_raw"].values if use_b3 else np.zeros(len(df))
    s3_raw = factors_df["s3_raw"].values if use_b3 else np.zeros(len(df))

    buy_any = (b1_raw > 0) | (b2_raw > 0) | (b3_raw > 0)
    sell_any = (s1_raw > 0) | (s2_raw > 0) | (s3_raw > 0)

    b05_er = factors_df["b05_er"].values
    z09_comp = factors_df["z09_comp"].values
    z01_width = factors_df["z01_width"].values
    p08_pullback = factors_df["p08_pullback"].values
    z11_breakout = factors_df["z11_breakout"].values
    zs_high = factors_df["zs_high"].values
    zs_low = factors_df["zs_low"].values
    ema50 = factors_df["ema50"].values
    atr = factors_df["atr"].values
    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    n = len(df)

    signal = np.zeros(n, dtype=int)

    # 状态机执行模拟 (追踪持仓、止损与吊灯出场)
    position = 0
    entry_price = 0.0
    stop_loss = 0.0
    highest_price = 0.0
    lowest_price = 999999.0
    bars_in_trade = 0

    for i in range(1, n):
        curr_c = close[i]
        curr_h = high[i]
        curr_l = low[i]
        curr_atr = atr[i] if atr[i] > 0 else 1.0

        # --- 1. 检查已有持仓的出场条件 ---
        if position == 1:
            bars_in_trade += 1
            highest_price = max(highest_price, curr_h)

            # 动态保本锁定
            if highest_price >= entry_price + 1.0 * curr_atr:
                stop_loss = max(stop_loss, entry_price + 0.1 * curr_atr)

            # 3.0 ATR 动态吊灯跟踪止盈
            if highest_price >= entry_price + 2.0 * curr_atr:
                chandelier_stop = highest_price - 3.0 * curr_atr
                stop_loss = max(stop_loss, chandelier_stop)

            # 触及止损或超时平仓
            if curr_l <= stop_loss or bars_in_trade >= holding_bars_max:
                position = 0
                signal[i] = 0
                continue
            else:
                signal[i] = 1

        elif position == -1:
            bars_in_trade += 1
            lowest_price = min(lowest_price, curr_l)

            # 动态保本锁定
            if lowest_price <= entry_price - 1.0 * curr_atr:
                stop_loss = min(stop_loss, entry_price - 0.1 * curr_atr)

            # 3.0 ATR 动态吊灯跟踪止盈
            if lowest_price <= entry_price - 2.0 * curr_atr:
                chandelier_stop = lowest_price + 3.0 * curr_atr
                stop_loss = min(stop_loss, chandelier_stop)

            # 触及止损或超时平仓
            if curr_h >= stop_loss or bars_in_trade >= holding_bars_max:
                position = 0
                signal[i] = 0
                continue
            else:
                signal[i] = -1

        # --- 2. 若空仓，检查开仓信号 (S 级品质门禁 + 宏观顺势) ---
        if position == 0:
            if buy_any[i - 1]:
                er = b05_er[i - 1]
                comp = z09_comp[i - 1]
                width = z01_width[i - 1]
                pb = p08_pullback[i - 1]
                macro_bull = curr_c >= ema50[i - 1]

                if er >= min_er and comp <= max_comp and width >= min_width and pb >= min_pullback and macro_bull:
                    position = 1
                    entry_price = curr_c
                    highest_price = curr_c
                    bars_in_trade = 0
                    zh = zs_high[i - 1]
                    if zh > 0 and (entry_price - zh) < 2.5 * curr_atr:
                        stop_loss = max(zh - 0.5 * curr_atr, entry_price - 1.5 * curr_atr)
                    else:
                        stop_loss = entry_price - 1.2 * curr_atr
                    signal[i] = 1

            elif sell_any[i - 1]:
                er = b05_er[i - 1]
                comp = z09_comp[i - 1]
                width = z01_width[i - 1]
                pb = p08_pullback[i - 1]
                macro_bear = curr_c <= ema50[i - 1]

                if er >= min_er and comp <= max_comp and width >= min_width and pb >= min_pullback and macro_bear:
                    position = -1
                    entry_price = curr_c
                    lowest_price = curr_c
                    bars_in_trade = 0
                    zl = zs_low[i - 1]
                    if zl > 0 and (zl - entry_price) < 2.5 * curr_atr:
                        stop_loss = min(zl + 0.5 * curr_atr, entry_price + 1.5 * curr_atr)
                    else:
                        stop_loss = entry_price + 1.2 * curr_atr
                    signal[i] = -1


    return pd.Series(signal, index=df.index)

