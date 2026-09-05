"""
strategies/guiyuan_zscore_reversion.py — 「归元·条件均值回归」: 稳健极值偏离 + 真实Connors RSI + 动力学体制门禁 + 做市商吸收状态机 (CMR-V2.0)

核心架构与理论遵循《研究策略.md》第一性原理：
1. 均值回归第一性原理:
   - 核心不是“偏离多远”，而是“当前偏离是暂时性失衡还是结构性重新定价”。
   - 强单边趋势态 (phi >= 1, ER 接近 1, Hurst > 0.55) 严禁做均值回归！
2. 稳健多维极值偏离 (Multi-Dimensional Robust Deviation):
   - A01 Robust Z-Score: (Close - RollingMedian) / (1.4826 * MAD)，抗肥尾极端值；
   - A02 ATR Distance: (Close - EMA20) / ATR14；
   - 真正的 Larry Connors RSI (CRSI): 等权融合 Price RSI(3)、Streak RSI(2) 和 PercentRank(ROC, 100)。
3. 动力学体制门禁 (Regime Gatekeeper):
   - 考夫曼效率比率 (Kaufman Efficiency Ratio, ER <= 0.65)，噪声震荡时放行，单边趋势时休眠；
   - 局部方差比率赫斯特指数 (Variance Ratio Hurst Proxy <= 0.55)，长程记忆单边趋势态禁止逆势摸顶抄底。
4. 做市商微观吸收与筹码衰竭 (Microstructure Absorption & OI Unwinding):
   - 成交量脉冲但推进效率递减 (Effort vs Result)；
   - 探底长下影 (LWR >= 0.35) 与冲顶长上影 (UWR >= 0.35) 做市商拒斥吸收形态；
   - 期货持仓量增减过滤 (排除主力量化暴力加仓逼仓的单边行情)。
5. Setup -> Trigger 因果状态机 (Confirmed Reversion):
   - 极值偏离仅代表进入观察区 (Setup)，必须等待卖方衰竭并确认价格脱离极值区 (Trigger) 才在下一柱开盘撮合，杜绝猜底接飞刀。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "guiyuan_zscore_reversion"
STRATEGY_DESCRIPTION = "「归元·CMR-V2.0」: 稳健偏离 + 真实Connors RSI + 动力学体制门禁 + 做市商吸收状态机"


def calculate_true_connors_rsi(
    close: pd.Series,
    price_window: int = 3,
    streak_window: int = 2,
    rank_window: int = 100,
) -> pd.Series:
    """
    计算真正的 Larry Connors RSI (CRSI = (RSI(Price, 3) + RSI(Streak, 2) + PercentRank(ROC, 100)) / 3)
    纯因果时序，零前瞻，严格适配商品期货高灵敏度反转特征。
    """
    c = close.astype(float)
    n = len(c)
    if n < 10:
        return pd.Series(50.0, index=close.index)

    # 1. 价格短期 RSI (默认 3 周期)
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(price_window, min_periods=1).mean()
    avg_loss = loss.rolling(price_window, min_periods=1).mean() + 1e-8
    rs = avg_gain / avg_loss
    rsi_price = 100.0 - (100.0 / (1.0 + rs))

    # 2. 连续涨跌连击 Streak 计算与 Streak RSI (默认 2 周期)
    c_arr = c.values
    streak = np.zeros(n, dtype=float)
    for t in range(1, n):
        if c_arr[t] > c_arr[t - 1]:
            streak[t] = streak[t - 1] + 1.0 if streak[t - 1] > 0 else 1.0
        elif c_arr[t] < c_arr[t - 1]:
            streak[t] = streak[t - 1] - 1.0 if streak[t - 1] < 0 else -1.0
        else:
            streak[t] = 0.0

    streak_s = pd.Series(streak, index=close.index)
    s_delta = streak_s.diff()
    s_gain = s_delta.clip(lower=0.0)
    s_loss = (-s_delta).clip(lower=0.0)
    s_avg_gain = s_gain.rolling(streak_window, min_periods=1).mean()
    s_avg_loss = s_loss.rolling(streak_window, min_periods=1).mean() + 1e-8
    s_rs = s_avg_gain / s_avg_loss
    rsi_streak = 100.0 - (100.0 / (1.0 + s_rs))

    # 3. 单周期收益率在过去 100 周期内的分位数 PercentRank
    roc1 = c.pct_change(1).fillna(0.0)
    pct_rank = (
        roc1.rolling(rank_window, min_periods=20)
        .apply(lambda s: float((s < s.iloc[-1]).mean() * 100.0), raw=False)
        .fillna(50.0)
    )

    crsi = (rsi_price + rsi_streak + pct_rank) / 3.0
    return crsi.fillna(50.0)


def calculate_cmr_features(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """计算 CMR 全套因果特征拓扑矩阵"""
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)
    n = len(df)

    # 1. 真实波幅与因果 ATR (14 周期)
    c_arr = c.values
    prev_c = np.roll(c_arr, 1)
    prev_c[0] = c_arr[0]
    tr = np.maximum(h.values - l.values, np.maximum(np.abs(h.values - prev_c), np.abs(l.values - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=3).mean().bfill().values + 1e-8

    # 2. A01 稳健 Z-Score (Robust Z-Score) 基于中位数与 MAD，抗异常大阴/大阳肥尾干扰
    med20 = c.rolling(20, min_periods=5).median().bfill().values
    mad20 = (c - c.rolling(20, min_periods=5).median()).abs().rolling(20, min_periods=5).median().bfill().values
    mad20 = np.maximum(mad20 * 1.4826, 1e-6)
    robust_z = (c_arr - med20) / mad20

    # A02 波动调整偏离 ATR Distance
    ema20 = c.ewm(span=20, adjust=False).mean().values
    d_atr = (c_arr - ema20) / atr

    # 3. 真实 Connors RSI (3, 2, 100)
    crsi = calculate_true_connors_rsi(c, price_window=3, streak_window=2, rank_window=100).values

    # 4. 动力学体制门禁 (Regime Filters)
    # (1) 考夫曼效率比率 (Kaufman Efficiency Ratio, ER)
    net_diff = (c - c.shift(10)).abs()
    total_volatility = c.diff().abs().rolling(10, min_periods=1).sum() + 1e-8
    er = (net_diff / total_volatility).bfill().values

    # (2) 局部方差比率赫斯特指数 (Variance Ratio Hurst Proxy)
    c_diff2 = c.diff(2)
    c_diff8 = c.diff(8)
    tau2 = c_diff2.rolling(20, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(20, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

    # 5. 微观做市商吸收形态与筹码衰竭 (Microstructure Absorption & OI)
    bar_range = np.maximum(1e-8, h.values - l.values)
    body = np.abs(c_arr - o.values)
    lower_shadow = np.where(c_arr >= o.values, o.values - l.values, c_arr - l.values)
    upper_shadow = np.where(c_arr >= o.values, h.values - c_arr, h.values - o.values)
    lwr = lower_shadow / bar_range
    uwr = upper_shadow / bar_range

    # 量比 (Effort)
    vol_ma20 = v.rolling(20, min_periods=5).mean().bfill().values + 1e-8
    rel_vol = v.values / vol_ma20

    # 持仓量过滤 (OI Unwinding)
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        # 排除主力大幅单向主动加仓逼仓的破位走势 (Delta OI > 0.4 * VolMA)
        oi_filter_long = oi_diff <= vol_ma20 * 0.40
        oi_filter_short = oi_diff <= vol_ma20 * 0.40

    return {
        "close": c_arr,
        "open": o.values,
        "high": h.values,
        "low": l.values,
        "atr": atr,
        "robust_z": robust_z,
        "d_atr": d_atr,
        "crsi": crsi,
        "er": er,
        "hurst": hurst,
        "lwr": lwr,
        "uwr": uwr,
        "body": body,
        "rel_vol": rel_vol,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short,
        "ema20": ema20,
    }


def calculate_signal(df: pd.DataFrame, cooldown_bars: int = 4) -> pd.Series:
    """
    标准热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)

    严格时序语义:
    第 t 根 Bar 完结瞬间纯因果计算产生信号，严格在第 t+1 根 Bar 开盘撮合成交 (Next-Open Fill)。
    包含 Setup 观察区状态机与动态冷却机制，彻底消除死扛接飞刀与高频连续发单。
    """
    n = len(df)
    if n < 30:
        return pd.Series(0, index=df.index, dtype=int)

    feat = calculate_cmr_features(df)
    c = feat["close"]
    o = feat["open"]
    rz = feat["robust_z"]
    datr = feat["d_atr"]
    crsi = feat["crsi"]
    er = feat["er"]
    hurst = feat["hurst"]
    lwr = feat["lwr"]
    uwr = feat["uwr"]
    oi_long = feat["oi_filter_long"]
    oi_short = feat["oi_filter_short"]

    signals = np.zeros(n, dtype=int)

    # 状态机追踪: 记录 Setup 观察区的发生时间
    setup_long_bar = -999
    setup_short_bar = -999
    last_signal_bar = -999

    for i in range(20, n):
        # 1. 动力学体制门禁 (Regime Filter): 仅在非单边主浪状态下放行
        regime_mr_allowed = (er[i] <= 0.65) and (hurst[i] <= 0.55)

        # 2. 极值偏离进入观察区 (Setup Event)
        # 多头极值: 稳健 Z-Score <= -1.8 或 ATR偏离 <= -1.8, 且 Connors RSI <= 22
        if regime_mr_allowed and (rz[i] <= -1.8 or datr[i] <= -1.8) and (crsi[i] <= 22.0) and oi_long[i]:
            setup_long_bar = i

        # 空头极值: 稳健 Z-Score >= 1.8 或 ATR偏离 >= 1.8, 且 Connors RSI >= 78
        if regime_mr_allowed and (rz[i] >= 1.8 or datr[i] >= 1.8) and (crsi[i] >= 78.0) and oi_short[i]:
            setup_short_bar = i

        # 3. 拐点确认触发 (Trigger Confirmation: 离开极值区 + 做市商微观拒斥)
        if i - last_signal_bar >= cooldown_bars:
            # 多头触发条件:
            # (1) 在过去 4 根 Bar 内曾出现极值 Setup；
            # (2) 当前 Bar 呈现企稳反弹形态 (阳线 或 长下影探底拒斥 LWR >= 0.35)；
            # (3) Connors RSI 开始掉头向上 (脱离极度超卖区)
            if (
                (i - setup_long_bar <= 4)
                and ((c[i] > o[i]) or (lwr[i] >= 0.35))
                and (crsi[i] > crsi[i - 1])
            ):
                signals[i] = 1
                last_signal_bar = i
                setup_long_bar = -999  # 消耗 Setup 状态

            # 空头触发条件:
            # (1) 在过去 4 根 Bar 内曾出现极值 Setup；
            # (2) 当前 Bar 呈现冲顶回落形态 (阴线 或 长上影冲顶滞涨 UWR >= 0.35)；
            # (3) Connors RSI 开始掉头向下 (脱离极度超买区)
            elif (
                (i - setup_short_bar <= 4)
                and ((c[i] < o[i]) or (uwr[i] >= 0.35))
                and (crsi[i] < crsi[i - 1])
            ):
                signals[i] = -1
                last_signal_bar = i
                setup_short_bar = -999

    return pd.Series(signals, index=df.index, dtype=int)
