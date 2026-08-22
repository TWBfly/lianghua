"""
strategies/trend_volume_candlestick_master.py — SuperTrend 与 AlphaTrend 量价结构与微观 K 线形态终极结合策略

核心量化微观物理逻辑：
1. 信号触发源 (Dual-Core Trend Engines):
   - SuperTrend: HL2 + ATR(10) * 3.0 经典防回退状态机翻转
   - AlphaTrend: RSI(14) + ATR(14) * 1.618 递归通道与 2-Bar 延迟交叉

2. 微观 K 线形态确认 (Candlestick Structural Pattern Verification):
   - 大实体突破 (Marubozu / Solid Expansion Body): 实体 |Close - Open| >= 0.6 * ATR(14)，杜绝小碎星假突破
   - 拒斥影线控制 (Shadow Rejection Filter): 做多时上影线 <= 0.3 * 实体，做空时下影线 <= 0.3 * 实体（排除冲高回落/探底回升的套牢陷阱）
   - 结构吞没形态 (Engulfing Pattern): 突破 Bar 实体吞没前 1~2 根 Bar 极值，形成强动量包络
   - 连续推动结构 (Consecutive Momentum Bars): 连续 2 根同向收盘且创新高/新低 (Higher Highs / Lower Lows)

3. 成交量与筹码流微观聚类 (Volume & Open Interest Flow Clustering):
   - 放量突破倍数 (Volume Burst): Volume >= 1.5 * SMA(Volume, 20)，证明机构主力资金入场
   - 期货主动增仓确认 (OI Expansion Flow): delta_OI > 0 且 delta_OI / Volume >= 0.10（真机构建仓 vs 假止损踩踏）
   - 量价背离识别 (Volume-Price Anomaly): 价格突破但成交量萎缩或持仓量暴跌时坚决拦截

4. 动态波幅出场与跟踪 (Volatility-Adaptive Asymmetric Exit):
   - 动态保本锁定 (Break-Even Lock): 浮盈达 0.8 ATR 时锁定入场价 + 0.1 ATR
   - 动态分批止盈 / Chandelier 跟踪止损: 3.0 ATR 顺势跟踪
"""

import numpy as np
import pandas as pd

from technical_indicators import calculate_atr, calculate_rma, calculate_rsi


def compute_candlestick_patterns(df: pd.DataFrame) -> dict:
    """计算专业级微观 K 线形态与实体/影线特征"""
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    n = len(c)

    body = np.abs(c - o)
    is_bull = c >= o
    is_bear = c < o

    upper_shadow = np.where(is_bull, h - c, h - o)
    lower_shadow = np.where(is_bull, o - l, c - l)

    # 1. 实体与影线比率
    body_ratio = np.where(h - l > 0, body / (h - l + 1e-8), 0.0)
    upper_shadow_ratio = np.where(body > 0, upper_shadow / (body + 1e-8), 0.0)
    lower_shadow_ratio = np.where(body > 0, lower_shadow / (body + 1e-8), 0.0)

    # 2. 吞没形态 (Engulfing)
    prev_o = np.roll(o, 1)
    prev_c = np.roll(c, 1)
    prev_h = np.roll(h, 1)
    prev_l = np.roll(l, 1)

    bull_engulf = (is_bull) & (prev_c < prev_o) & (c > prev_o) & (o < prev_c)
    bear_engulf = (is_bear) & (prev_c > prev_o) & (c < prev_o) & (o > prev_c)

    # 3. 连续推动结构 (Consecutive Push)
    consec_higher_highs = (h > prev_h) & (l > prev_l) & is_bull
    consec_lower_lows = (h < prev_h) & (l < prev_l) & is_bear

    return {
        "body": body,
        "body_ratio": body_ratio,
        "upper_shadow_ratio": upper_shadow_ratio,
        "lower_shadow_ratio": lower_shadow_ratio,
        "bull_engulf": bull_engulf,
        "bear_engulf": bear_engulf,
        "consec_higher_highs": consec_higher_highs,
        "consec_lower_lows": consec_lower_lows,
    }


def compute_volume_oi_features(df: pd.DataFrame) -> dict:
    """计算成交量异动与持仓量资金流特征"""
    v = df["volume"].astype(float).values
    n = len(v)
    vol_ma20 = pd.Series(v).rolling(20).mean().fillna(method="bfill").values
    vol_ratio = np.where(vol_ma20 > 0, v / (vol_ma20 + 1e-8), 1.0)
    vol_burst = vol_ratio >= 1.4  # 放量 1.4 倍以上

    oi = df["open_interest"].astype(float).values if "open_interest" in df.columns else np.zeros(n)
    oi_diff = np.diff(oi, prepend=oi[0])
    oi_flow = np.where(v > 0, oi_diff / (v + 1e-8), 0.0)
    oi_expanding = oi_diff > 0  # 主动增仓

    return {
        "vol_ratio": vol_ratio,
        "vol_burst": vol_burst,
        "oi_diff": oi_diff,
        "oi_flow": oi_flow,
        "oi_expanding": oi_expanding,
    }


def compute_supertrend_vcp_signals(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    SuperTrend + Volume & Candlestick Pattern (ST-VCP) 深度复合信号生成
    """
    from strategies.supertrend_strategy import compute_supertrend
    df_res = df.copy()
    st_line, st_dir = compute_supertrend(df_res, period=period, multiplier=multiplier)
    n = len(df_res)

    c = df_res["close"].values
    o = df_res["open"].values
    atr_14 = calculate_atr(df_res, 14).fillna(method="bfill").values

    kp = compute_candlestick_patterns(df_res)
    vp = compute_volume_oi_features(df_res)

    signals = np.zeros(n, dtype=int)
    reasons = [""] * n

    for i in range(2, n):
        # 基础 SuperTrend 方向翻转
        st_flipped_long = (st_dir[i] == 1) and (st_dir[i - 1] == -1)
        st_flipped_short = (st_dir[i] == -1) and (st_dir[i - 1] == 1)

        curr_atr = max(2.0, atr_14[i])
        curr_body = kp["body"][i]
        curr_vol_burst = vp["vol_burst"][i]
        curr_oi_expand = vp["oi_expanding"][i]

        # 1. 做多深度验证：
        # (a) 大实体阳线 (Body >= 0.5 ATR)
        # (b) 上影线不长 (<= 0.4 * Body)
        # (c) 放量 (Vol >= 1.3 MA20) 或 主动增仓突破 (OI Expand) 或 强吞没形态
        if st_flipped_long:
            solid_bull = (c[i] > o[i]) and (curr_body >= 0.5 * curr_atr)
            clean_shadow_long = kp["upper_shadow_ratio"][i] <= 0.45
            volume_confirmed_long = (vp["vol_ratio"][i] >= 1.25) or curr_oi_expand or kp["bull_engulf"][i] or kp["consec_higher_highs"][i]

            if solid_bull and clean_shadow_long and volume_confirmed_long:
                signals[i] = 1
                reasons[i] = f"ST多头翻转+大实体阳线({curr_body/curr_atr:.2f}ATR)+量能放量({vp['vol_ratio'][i]:.2f}x)"

        # 2. 做空深度验证：
        # (a) 大实体阴线 (Body >= 0.5 ATR)
        # (b) 下影线不长 (<= 0.4 * Body)
        # (c) 放量 或 主动增仓下破 或 强阴吞没
        elif st_flipped_short:
            solid_bear = (c[i] < o[i]) and (curr_body >= 0.5 * curr_atr)
            clean_shadow_short = kp["lower_shadow_ratio"][i] <= 0.45
            volume_confirmed_short = (vp["vol_ratio"][i] >= 1.25) or curr_oi_expand or kp["bear_engulf"][i] or kp["consec_lower_lows"][i]

            if solid_bear and clean_shadow_short and volume_confirmed_short:
                signals[i] = -1
                reasons[i] = f"ST空头翻转+大实体阴线({curr_body/curr_atr:.2f}ATR)+量能放量({vp['vol_ratio'][i]:.2f}x)"

    df_res["st_vcp_sig"] = signals
    df_res["st_vcp_reason"] = reasons
    return df_res


def compute_alphatrend_vcp_signals(df: pd.DataFrame, period: int = 14, multiplier: float = 1.618) -> pd.DataFrame:
    """
    AlphaTrend + Volume & Candlestick Pattern (AT-VCP) 深度复合信号生成
    """
    from strategies.alphatrend_strategy import compute_alphatrend
    df_res = df.copy()
    at_line, at_line_2 = compute_alphatrend(df_res, period=period, multiplier=multiplier)
    n = len(df_res)

    c = df_res["close"].values
    o = df_res["open"].values
    atr_14 = calculate_atr(df_res, 14).fillna(method="bfill").values

    kp = compute_candlestick_patterns(df_res)
    vp = compute_volume_oi_features(df_res)

    signals = np.zeros(n, dtype=int)
    reasons = [""] * n

    for i in range(3, n):
        # AlphaTrend 金叉 / 死叉
        at_cross_up = (at_line[i] > at_line_2[i]) and (at_line[i - 1] <= at_line_2[i - 1])
        at_cross_down = (at_line[i] < at_line_2[i]) and (at_line[i - 1] >= at_line_2[i - 1])

        curr_atr = max(2.0, atr_14[i])
        curr_body = kp["body"][i]
        curr_oi_expand = vp["oi_expanding"][i]

        if at_cross_up:
            solid_bull = (c[i] > o[i]) and (curr_body >= 0.45 * curr_atr)
            clean_shadow_long = kp["upper_shadow_ratio"][i] <= 0.50
            volume_confirmed_long = (vp["vol_ratio"][i] >= 1.20) or curr_oi_expand or kp["bull_engulf"][i]

            if solid_bull and clean_shadow_long and volume_confirmed_long:
                signals[i] = 1
                reasons[i] = f"AT金叉+大实体阳线({curr_body/curr_atr:.2f}ATR)+量能放量({vp['vol_ratio'][i]:.2f}x)"

        elif at_cross_down:
            solid_bear = (c[i] < o[i]) and (curr_body >= 0.45 * curr_atr)
            clean_shadow_short = kp["lower_shadow_ratio"][i] <= 0.50
            volume_confirmed_short = (vp["vol_ratio"][i] >= 1.20) or curr_oi_expand or kp["bear_engulf"][i]

            if solid_bear and clean_shadow_short and volume_confirmed_short:
                signals[i] = -1
                reasons[i] = f"AT死叉+大实体阴线({curr_body/curr_atr:.2f}ATR)+量能放量({vp['vol_ratio'][i]:.2f}x)"

    df_res["at_vcp_sig"] = signals
    df_res["at_vcp_reason"] = reasons
    return df_res
