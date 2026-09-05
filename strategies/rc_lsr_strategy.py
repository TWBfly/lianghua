"""
strategies/rc_lsr_strategy.py — 「RC-LSR·市场状态条件化流动性冲击反转策略」
Regime-Conditioned Liquidity Shock Reversal (RC-LSR 30m Production Core)

核心第一原理与物理机制（遵循《研究策略.md》最新架构规范）：
1. 为什么做反转：赚取无弹性踩踏平仓盘（Forced Liquidation）耗尽后的流动性供给溢价（Liquidity Provision Alpha）。
2. 状态机两级漏斗 (Two-Stage Causal Funnel):
   - Setup Gate: 盘中出现极端物理下潜 (DownExcursion >= 2.0 ATR) 且同时段放量 (RVOL >= 1.5)，
     但单边趋势比率安全 (ER <= 0.35)、波动状态未暴走 (VR <= 1.8)、全市场宏观暴跌广度安全 (Breadth <= 0.35)；
   - Trigger Gate: 边际冲击显著衰竭 (ImpactDecay <= 0.65 或 支撑刺穿收复 FailedBreak) 且价格脱离极值区 (ReEntry 调头)，
     且持仓量无主力逼仓单边暴增 (Delta OI 过滤)。
3. 严格因果语义 (Strict Causality):
   - 所有特征在第 t 根 Bar 收盘闭合时刻计算锁定；
   - 信号于第 t 根 Bar 收盘生成，严格在第 t+1 根 Bar 开盘价 (Next-Open) 以市价撮合成交；
   - 包含动态冷却窗口 (Cooldown = 8 根 Bar)，杜绝单边连续左侧摸底。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

STRATEGY_NAME = "rc_lsr_strategy"
STRATEGY_DESCRIPTION = "「RC-LSR」市场状态条件化流动性冲击反转策略 (30m): 微观冲击吸收 + 截面广度门禁 + 因果两级状态机"

# 截面广度缓存单例 (全局只读加载，避免重复磁盘 I/O)
_CACHED_BREADTH_DF: Optional[pd.DataFrame] = None


def _get_breadth_series(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """尝试加载预计算的截面广度，无匹配时因果回退为零"""
    global _CACHED_BREADTH_DF
    if _CACHED_BREADTH_DF is None:
        breadth_path = Path(__file__).resolve().parent.parent / "data" / "futures_breadth_30m.csv"
        if breadth_path.exists():
            try:
                b_df = pd.read_csv(breadth_path, parse_dates=["trade_time"], index_col="trade_time")
                _CACHED_BREADTH_DF = b_df
            except Exception:
                _CACHED_BREADTH_DF = pd.DataFrame()
        else:
            _CACHED_BREADTH_DF = pd.DataFrame()

    n = len(index)
    if _CACHED_BREADTH_DF is not None and not _CACHED_BREADTH_DF.empty:
        # 纯因果对齐 (left join)，缺失时 Fail-Closed 兜底 1.0 (全市场恐慌禁止开仓)
        matched = pd.DataFrame(index=index).join(_CACHED_BREADTH_DF, how="left")
        down_b = matched["down_breadth"].fillna(1.0).values
        up_b = matched["up_breadth"].fillna(1.0).values
        return down_b, up_b

    return np.ones(n, dtype=float), np.ones(n, dtype=float)


def calculate_factors(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    计算 RC-LSR 7 维微观物理因子因果矩阵。
    输入必须包含: open, high, low, close, volume (open_interest 可选)
    """
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    # 1. 稳健 True Range 与 ATR (滚动中位数，抗肥尾孤立脉冲)
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr_s = pd.Series(tr, index=df.index)
    atr_robust = tr_s.rolling(window, min_periods=5).median().ffill().fillna(1.0).values + 1e-8

    # 2. 局部公平价值中枢基准 EMA 与 宏观长波趋势 EMA (120周期)
    c_s = pd.Series(c, index=df.index)
    ema_base = c_s.ewm(span=window, adjust=False).mean().values
    ema_macro = c_s.ewm(span=120, adjust=False).mean().values

    # 3. Family A: 极端盘中位移 (Extreme Excursion) 与 收盘偏离 (Close Deviation)
    down_excursion = (ema_base - l) / atr_robust  # 盘中向下最大撕裂深度 (>= 2.0 代表流动性蒸发)
    up_excursion = (h - ema_base) / atr_robust    # 盘中向上最大挤压深度 (>= 2.0 代表空头踩踏)
    close_deviation = (c - ema_base) / atr_robust

    # 4. Family B: 趋势状态门禁 (Efficiency Ratio) & 波动重定价比率 (Volatility Ratio)
    # ER = 净位移 / 总路径 (Kaufman 效率比)
    net_path = (c_s - c_s.shift(window)).abs()
    total_path = c_s.diff().abs().rolling(window, min_periods=5).sum().replace(0, np.nan)
    er = (net_path / total_path).ffill().fillna(0.0).values

    # VR = 短期真实波动率 / 长期真实波动率
    atr_5 = tr_s.rolling(5, min_periods=2).mean()
    atr_60 = tr_s.rolling(60, min_periods=10).mean().replace(0, np.nan)
    vr = (atr_5 / atr_60).ffill().fillna(1.0).values

    # 5. Family C: 时段去季节化相对成交量 (Session-Detrended RVOL)
    v_s = pd.Series(v, index=df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.has_duplicates is False:
        # ponytail: 按时间槽位计算中位数消除夜盘与早盘天然高成交量偏差
        expected_vol = v_s.groupby(df.index.time).transform(
            lambda s: s.rolling(30, min_periods=5).median().ffill()
        ).fillna(v_s.rolling(window, min_periods=5).median()).values + 1e-8
    else:
        expected_vol = v_s.rolling(window, min_periods=5).median().ffill().fillna(1.0).values + 1e-8
    rvol = v / expected_vol

    # 6. Family D: 边际价格推进与冲击衰减率 (Marginal Impact Decay)
    prev_l = np.roll(l, 1); prev_l[0] = l[0]
    prev_h = np.roll(h, 1); prev_h[0] = h[0]
    marginal_down = np.maximum(prev_l - l, 0.0) / atr_robust
    marginal_up = np.maximum(h - prev_h, 0.0) / atr_robust

    impact_down = marginal_down / (np.sqrt(np.maximum(rvol, 0.1)))
    prev_impact_down = np.roll(impact_down, 1); prev_impact_down[0] = impact_down[0]
    # 若上一根并无实质下探 (prev_impact <= 0.02)，衰减率置为 1.0 (未衰减)，防止无实质下探时分子为0自动判定吸收
    impact_decay_down = np.where(prev_impact_down > 0.02, impact_down / (prev_impact_down + 1e-6), 1.0)

    impact_up = marginal_up / (np.sqrt(np.maximum(rvol, 0.1)))
    prev_impact_up = np.roll(impact_up, 1); prev_impact_up[0] = impact_up[0]
    impact_decay_up = np.where(prev_impact_up > 0.02, impact_up / (prev_impact_up + 1e-6), 1.0)

    # 7. Family E: 关键支撑/阻力刺穿收复 (Failed Breakdown & Failed Breakout)
    l_s = pd.Series(l, index=df.index)
    h_s = pd.Series(h, index=df.index)
    roll_low_20 = l_s.shift(1).rolling(window, min_periods=5).min().values
    roll_high_20 = h_s.shift(1).rolling(window, min_periods=5).max().values
    failed_breakdown = (l < roll_low_20) & (c > roll_low_20)
    failed_breakout = (h > roll_high_20) & (c < roll_high_20)

    # Close Location Value (收在 K 线哪个位置: -1 最低, +1 最高)
    bar_range = np.maximum(h - l, 1e-8)
    clv = (2.0 * c - h - l) / bar_range

    # 下影线 / 上影线做市商微观吸收形态 (Pin Bar: 影线占比 >= 28% 且实体企稳)
    pinbar_long = ((np.minimum(o, c) - l) / bar_range >= 0.28) & (c >= o)
    pinbar_short = ((h - np.maximum(o, c)) / bar_range >= 0.28) & (c <= o)

    # 8. Family G: 截面系统性广度 (Cross-Sectional Breadth, 缺失时 Fail-Closed)
    if "down_breadth" in df.columns and "up_breadth" in df.columns:
        down_breadth = df["down_breadth"].astype(float).fillna(1.0).values
        up_breadth = df["up_breadth"].astype(float).fillna(1.0).values
    elif isinstance(df.index, pd.DatetimeIndex):
        down_breadth, up_breadth = _get_breadth_series(df.index)
    else:
        down_breadth = np.ones(n, dtype=float)
        up_breadth = np.ones(n, dtype=float)

    # 8.5 趋势状态门禁 (Wilder's ADX 14 与 120 均线倾角，与 Rust 引擎对齐)
    up_move = h - prev_h
    down_move = prev_l - l
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_s = pd.Series(tr, index=df.index)
    tr_smooth = tr_s.ewm(alpha=1.0 / 14, adjust=False).mean()
    pdm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / 14, adjust=False).mean()
    mdm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / 14, adjust=False).mean()

    pdi = 100.0 * pdm_smooth / (tr_smooth + 1e-8)
    mdi = 100.0 * mdm_smooth / (tr_smooth + 1e-8)
    dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi + 1e-8)
    adx = dx.ewm(alpha=1.0 / 14, adjust=False).mean().fillna(20.0).values

    ema_macro_s = pd.Series(ema_macro, index=df.index)
    slope_120 = ((ema_macro_s - ema_macro_s.shift(20)) / (20.0 * atr_robust)).fillna(0.0).values

    # 9. 持仓量过滤 (Open Interest Unwinding Filter)
    oi_safe_long = np.ones(n, dtype=bool)
    oi_safe_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        v_ma20 = v_s.rolling(window, min_periods=5).mean().ffill().fillna(1.0).values
        # 暴跌时若持仓量暴增 (>0.4 * 均量)，判定为主力机构携新资金重定价真突破，禁止做多反转
        oi_safe_long = oi_diff <= (v_ma20 * 0.40)
        oi_safe_short = oi_diff <= (v_ma20 * 0.40)

    return pd.DataFrame({
        "atr": atr_robust,
        "ema_base": ema_base,
        "ema_macro": ema_macro,
        "down_excursion": down_excursion,
        "up_excursion": up_excursion,
        "close_deviation": close_deviation,
        "er": er,
        "vr": vr,
        "rvol": rvol,
        "impact_decay_down": impact_decay_down,
        "impact_decay_up": impact_decay_up,
        "failed_breakdown": failed_breakdown,
        "failed_breakout": failed_breakout,
        "clv": clv,
        "pinbar_long": pinbar_long,
        "pinbar_short": pinbar_short,
        "down_breadth": down_breadth,
        "up_breadth": up_breadth,
        "adx": adx,
        "slope_120": slope_120,
        "oi_safe_long": oi_safe_long,
        "oi_safe_short": oi_safe_short,
    }, index=df.index)


def calculate_signal(df: pd.DataFrame, cooldown_bars: int = 8) -> pd.Series:
    """
    RC-LSR 策略标准热插拔信号生成入口:
    输入: df (具有 open, high, low, close, volume)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)

    严格时间因果与两级状态机:
    第 t 根 Bar 收盘计算产生意图，严格在第 t+1 根 Bar 开盘撮合成交。
    """
    n = len(df)
    if n < 40:
        return pd.Series(0, index=df.index, dtype=int)

    f = calculate_factors(df)
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    ema_macro = f["ema_macro"].values
    down_exc = f["down_excursion"].values
    up_exc = f["up_excursion"].values
    c_dev = f["close_deviation"].values
    er = f["er"].values
    vr = f["vr"].values
    rvol = f["rvol"].values
    decay_dn = f["impact_decay_down"].values
    decay_up = f["impact_decay_up"].values
    failed_dn = f["failed_breakdown"].values
    failed_up = f["failed_breakout"].values
    pinbar_long = f["pinbar_long"].values
    pinbar_short = f["pinbar_short"].values
    clv = f["clv"].values
    d_breadth = f["down_breadth"].values
    u_breadth = f["up_breadth"].values
    adx = f["adx"].values
    slope_120 = f["slope_120"].values
    oi_long = f["oi_safe_long"].values
    oi_short = f["oi_safe_short"].values

    signals = np.zeros(n, dtype=int)

    # 状态机：0=IDLE, 1=LONG_SETUP, -1=SHORT_SETUP
    long_state = 0
    short_state = 0
    long_setup_idx = -999
    short_setup_idx = -999
    last_signal_idx = -999

    for t in range(1, n):
        # 冷却期保护：避免连续左侧摸底
        if t - last_signal_idx < cooldown_bars:
            continue

        # ======================================================================
        # 做多分支 (Long Reversal)
        # ======================================================================
        # Stage 1: Setup 门禁
        if long_state == 0:
            # 物理冲击发生：盘中下潜深度达到极端位移 (>= 2.5 ATR)，放量克制 (1.3~3.2倍，避开极端信息重定价)
            is_shock = (down_exc[t] >= 2.5) and (1.3 <= rvol[t] <= 3.2)
            macro_safe = c[t] >= (ema_macro[t] * 0.96)  # 宏观长波过滤：避免在加速下跌大熊市盲目接飞刀
            # 趋势状态门禁 (ADX 暴走趋势过滤 + 120 均线倾角对冲门禁)
            is_regime_safe = (
                (er[t] <= 0.28)
                and (vr[t] <= 1.8)
                and (d_breadth[t] <= 0.35)
                and macro_safe
                and (adx[t] <= 28.0)
                and (slope_120[t] >= -0.04)
            )
            if is_shock and is_regime_safe:
                # 若当前柱收盘已完成吸收调头 (单柱锤头线下影线承接 / 假突破收复 / 阳线企稳衰减)
                absorption_now = failed_dn[t] or pinbar_long[t] or (decay_dn[t] <= 0.55 and c[t] > o[t])
                turning_now = c_dev[t] > c_dev[t - 1]
                if absorption_now and turning_now and oi_long[t]:
                    signals[t] = 1
                    last_signal_idx = t
                    continue
                long_state = 1
                long_setup_idx = t

        # Stage 2: Trigger 触发
        elif long_state == 1:
            # 持续复核市场状态：如果后续几根 Bar 市场恶化转为暴跌或暴走趋势，立刻作废 Setup！
            macro_safe = c[t] >= (ema_macro[t] * 0.96)
            is_regime_safe = (
                (er[t] <= 0.28)
                and (vr[t] <= 1.8)
                and (d_breadth[t] <= 0.35)
                and macro_safe
                and (adx[t] <= 28.0)
                and (slope_120[t] >= -0.04)
            )
            if not is_regime_safe or (t - long_setup_idx > 4):
                long_state = 0
            else:
                # 吸收确认：下影线承接 / 假突破收复 / 阳线企稳
                absorption_confirmed = failed_dn[t] or pinbar_long[t] or (decay_dn[t] <= 0.55 and c[t] > o[t])
                price_turning = c_dev[t] > c_dev[t - 1]

                if absorption_confirmed and price_turning and oi_long[t]:
                    signals[t] = 1
                    last_signal_idx = t
                    long_state = 0
                    continue

        # ======================================================================
        # 做空分支 (Short Reversal)
        # ======================================================================
        # Stage 1: Setup 门禁
        if short_state == 0:
            is_shock_up = (up_exc[t] >= 2.5) and (1.3 <= rvol[t] <= 3.2)
            macro_safe_up = c[t] <= (ema_macro[t] * 1.04)  # 宏观长波过滤：避免在单边疯牛主升浪左侧做空
            is_regime_safe_up = (
                (er[t] <= 0.28)
                and (vr[t] <= 1.8)
                and (u_breadth[t] <= 0.35)
                and macro_safe_up
                and (adx[t] <= 28.0)
                and (slope_120[t] <= 0.04)
            )
            if is_shock_up and is_regime_safe_up:
                absorption_now_up = failed_up[t] or pinbar_short[t] or (decay_up[t] <= 0.55 and c[t] < o[t])
                turning_now_up = c_dev[t] < c_dev[t - 1]
                if absorption_now_up and turning_now_up and oi_short[t]:
                    signals[t] = -1
                    last_signal_idx = t
                    continue
                short_state = 1
                short_setup_idx = t

        # Stage 2: Trigger 触发
        elif short_state == 1:
            macro_safe_up = c[t] <= (ema_macro[t] * 1.04)
            is_regime_safe_up = (
                (er[t] <= 0.28)
                and (vr[t] <= 1.8)
                and (u_breadth[t] <= 0.35)
                and macro_safe_up
                and (adx[t] <= 28.0)
                and (slope_120[t] <= 0.04)
            )
            if not is_regime_safe_up or (t - short_setup_idx > 4):
                short_state = 0
            else:
                absorption_confirmed_up = failed_up[t] or pinbar_short[t] or (decay_up[t] <= 0.55 and c[t] < o[t])
                price_turning_dn = c_dev[t] < c_dev[t - 1]

                if absorption_confirmed_up and price_turning_dn and oi_short[t]:
                    signals[t] = -1
                    last_signal_idx = t
                    short_state = 0

    return pd.Series(signals, index=df.index, dtype=int)
