"""
strategies/adaptive_regime_evolution_strategy.py — 「自适应三阶演化策略」(Adaptive Tri-Stage Regime Evolution Strategy)

基于《研究策略.md》与量化第一性原理架构：
第一步 (当前状态识别):
  - Ehlers 2-Pole SuperSmoother 趋势滤波 + 60m 宏观大势级联
  - Normalized Slope (线性回归斜率 / ATR)
  - Kaufman Directional Efficiency Ratio (DER = ER * sign(ΔP))
  - Range Position Centered (相对区间位置映射至 [-1, 1])
  - Crossing Frequency (价格穿越均线频度，识别震荡)
  - 迟滞机制 (Hysteresis) 稳定输出状态: UPTREND (1), DOWNTREND (-1), RANGE (0), TRANSITION (2)

第二步 (未来趋势预测):
  - 波动率压缩比 (ATR10 / ATR60) 与布林挤压 (Squeeze)
  - 动量加速度 (MOMACC) 与斜率变化率
  - 相对成交量 (RVOL) 与量价顺逆确认
  - 隐性减速诊断与回撤质量
  - 概率输出: P(Continue), P(Transition), P(Reversal)

第三步 (自适应元策略路由器与非对称风控):
  - 策略路由:
    * 顺势通道: 强趋势态且 P(Continue) >= 0.50 且顺宏观大势 -> 动量突破与浅回踩反弹 (Chandelier 2.8*ATR 追踪)
    * 震荡通道: 震荡态且 TS <= 35 -> 稳健 Z-Score 极值回归 (中枢均线极速止盈，硬止损 1.2*ATR)
    * 转换/不确定态 -> 强制观望休眠 (No Trade)，杜绝无谓磨损
  - 波动率等权与置信度风险预算 (Volatility-Targeted Risk Budgeting)
  - 出场后 3 根 Bar 冷却期，杜绝假突破连续受洗
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "code") not in sys.path:
    sys.path.append(str(_PROJECT_ROOT / "code"))

from regime_trend_evolution_engine import (
    CurrentTrendDetector,
    FutureTrendForecaster,
    calculate_ehlers_supersmoother_2pole,
    compute_normalized_slope,
    compute_kaufman_efficiency_ratio,
    compute_crossing_frequency,
    compute_range_position,
)

STRATEGY_NAME = "adaptive_regime_evolution"
STRATEGY_DESCRIPTION = "「自适应三阶演化策略」: 状态空间识别 + 未来延续前驱预测 + 动态路由与非对称吊灯追踪"


def compute_macro_regime_multiscale(
    df: pd.DataFrame,
    macro_period: int = 48,
    macro_window: int = 60,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    基于连续 15m K 线运行等效 48 周期 (等效 12 小时) 2-Pole SuperSmoother 与 60 周期宏观特征。
    彻底消除 resample('60min') 日历时钟断点扭曲与 merge_asof 阶梯时滞。
    严格单向因果，无任何未来函数。
    返回:
      - macro_state: 1 (Macro Trend Up), -1 (Macro Trend Down), 0 (Macro Range/Chop), 2 (Transition)
      - macro_ts: 宏观趋势强度 (0 ~ 100)
      - macro_der: 宏观带方向效率比 (-1.0 ~ +1.0)
      - macro_pos_cen: 宏观区间居中位置 (-1.0 ~ +1.0)
    """
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    atr = df["atr"].values if "atr" in df.columns else np.maximum(h - l, 1e-4)
    n = len(c)

    filt_macro = calculate_ehlers_supersmoother_2pole(c, period=macro_period)
    macro_er, macro_der = compute_kaufman_efficiency_ratio(c, window=macro_window)
    macro_slope = compute_normalized_slope(c, atr, window=macro_window)
    macro_cf = compute_crossing_frequency(c, filt_macro, window=macro_window)
    _, macro_pos_cen = compute_range_position(c, h, l, window=macro_window)

    norm_macro_slope = np.clip(np.abs(macro_slope) / 0.06, 0.0, 1.0)
    macro_chop_pen = np.clip(1.0 - 2.5 * macro_cf, 0.0, 1.0)
    macro_ts = np.clip((0.40 * macro_er + 0.35 * norm_macro_slope + 0.25 * macro_chop_pen) * 100.0, 0.0, 100.0)

    # 宏观迟滞状态机 (Hysteresis Machine)
    macro_state = np.zeros(n, dtype=int)
    curr_mstate = 0
    for i in range(macro_window, n):
        d_val = macro_der[i]
        t_val = macro_ts[i]
        if curr_mstate == 1:
            if d_val <= -0.15 or t_val < 30.0:
                curr_mstate = 0 if t_val < 28.0 else (-1 if d_val <= -0.25 else 2)
        elif curr_mstate == -1:
            if d_val >= 0.15 or t_val < 30.0:
                curr_mstate = 0 if t_val < 28.0 else (1 if d_val >= 0.25 else 2)
        else:
            if t_val >= 36.0 and d_val >= 0.18:
                curr_mstate = 1
            elif t_val >= 36.0 and d_val <= -0.18:
                curr_mstate = -1
            elif t_val <= 28.0:
                curr_mstate = 0
            else:
                curr_mstate = 2
        macro_state[i] = curr_mstate

    return macro_state, macro_ts, macro_der, macro_pos_cen


def compute_macro_ehlers_trend(df: pd.DataFrame, macro_freq: str = "60min") -> np.ndarray:
    """向后兼容接口：返回宏观状态方向."""
    macro_state, _, _, _ = compute_macro_regime_multiscale(df)
    return macro_state


def generate_regime_evolution_signals(
    df: pd.DataFrame,
    p_cont_threshold: float = 0.58,
    chandelier_mult: float = 2.8,
    reversion_stop_mult: float = 1.2,
) -> pd.DataFrame:
    """
    运行第一步微观状态识别与宏观拓扑流形，结合第二步前驱预测，由第三步自适应元路由器分发信号与元风控参数。
    严格因果，无任何未来函数。
    """
    # 1. 第一步：当前趋势状态识别 (微观 15m)
    detector = CurrentTrendDetector(fast_period=8, slow_period=24, er_window=20)
    df_step1 = detector.analyze(df)

    # 2. 第二步：未来趋势延续概率与前驱预测
    forecaster = FutureTrendForecaster(lookback=20)
    df_signals = forecaster.analyze(df_step1)

    n = len(df_signals)
    c = df_signals["close"].values
    o = df_signals["open"].values
    h = df_signals["high"].values
    l = df_signals["low"].values
    atr = df_signals["atr"].values
    state = df_signals["market_state"].values
    ts = df_signals["trend_strength"].values
    ds = df_signals["direction_score"].values
    p_cont = df_signals["p_continue"].values
    ss_fast = df_signals["ss_fast"].values
    ss_slow = df_signals["ss_slow"].values
    ext = df_signals["extension"].values
    body_ratio = np.abs(c - o) / np.maximum(1e-6, h - l)

    # 3. 宏观跨周期拓扑状态空间 (连续多尺度 DSP 滤波)
    macro_state, macro_ts, macro_der, macro_pos_cen = compute_macro_regime_multiscale(df_signals)
    df_signals["macro_state"] = macro_state
    df_signals["macro_dir"] = macro_state  # 兼容旧字段名
    df_signals["macro_ts"] = macro_ts
    df_signals["macro_der"] = macro_der
    df_signals["macro_pos_cen"] = macro_pos_cen

    # 宏观多尺度特征
    macro_strong_bull = (macro_state == 1) | (macro_der >= 0.15)
    macro_strong_bear = (macro_state == -1) | (macro_der <= -0.15)
    # 仅在微观动力学未形成强突破 (|ds| < 0.35) 时进行弱势过滤，杜绝暴跌暴涨被误压制为横盘
    state = np.where(macro_strong_bull & (state == -1) & (ds > -0.35), 0, state)
    state = np.where(macro_strong_bear & (state == 1) & (ds < 0.35), 0, state)
    df_signals["market_state"] = state

    # 4. 局部通道与能量挤压 (严格因果 ffill, 消除 bfill)
    h20 = pd.Series(h).rolling(20, min_periods=5).max().shift(1).ffill().fillna(c[0]).values
    l20 = pd.Series(l).rolling(20, min_periods=5).min().shift(1).ffill().fillna(c[0]).values
    df_signals["h20"] = h20
    df_signals["l20"] = l20

    c_s = pd.Series(c)
    c_std = c_s.rolling(20, min_periods=5).std(ddof=0).ffill().fillna(1e-4).values + 1e-8
    squeeze_ratio = (4.0 * c_std) / (2.0 * atr)
    had_squeeze = pd.Series(squeeze_ratio).rolling(10, min_periods=1).min().values <= 1.45
    df_signals["had_squeeze"] = had_squeeze

    # 动态 65% 分位数门禁 (遵循《研究策略.md》跨品种自适应分布)
    ts_q65 = pd.Series(ts).rolling(500, min_periods=50).quantile(0.65).ffill().fillna(50.0).values
    df_signals["ts_q65"] = ts_q65

    # 均值回归中枢与稳健 Z-Score
    filt_mean = calculate_ehlers_supersmoother_2pole(c, period=20)
    roll_med = c_s.rolling(30, min_periods=5).median().ffill().fillna(c[0]).values
    mad = c_s.rolling(30, min_periods=5).apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True).ffill().fillna(1e-4).values + 1e-6
    robust_z = (c - roll_med) / (1.4826 * mad)
    df_signals["filt_mean"] = filt_mean
    df_signals["robust_z"] = robust_z

    mom_acc = df_signals["mom_acc"].values
    causal_hurst = df_signals["causal_hurst"].values if "causal_hurst" in df_signals else np.full(n, 0.5)
    perm_entropy = df_signals["perm_entropy"].values if "perm_entropy" in df_signals else np.full(n, 0.85)
    physics_trend = df_signals["physics_trend"].values if "physics_trend" in df_signals else np.full(n, 0.5)

    # 5. 第三步双周期自适应路由器 (Adaptive Multi-Scale Meta-Router)
    raw_signals = np.zeros(n, dtype=int)
    signal_sources = np.zeros(n, dtype=int)  # 1: Trend, 2: Reversion, 0: None
    confidence = np.zeros(n, dtype=float)

    bars_since_pb_up = 99
    bars_since_pb_down = 99
    bars_in_state = 0
    regime_start_price = c[0]
    recent_box_high = -np.inf
    recent_box_low = np.inf
    prev_non_zero_regime = 0

    for i in range(65, n):
        st = state[i]
        pc = p_cont[i]
        curr_ds = ds[i]
        curr_ts = ts[i]
        q_ts = ts_q65[i]
        mst = macro_state[i]
        mder = macro_der[i]
        mpos = macro_pos_cen[i]

        # 状态化回抽记忆追踪 (Stateful Pullback Memory) 与 箱体极值追踪
        if i > 65 and state[i] != state[i - 1]:
            bars_in_state = 0
            regime_start_price = c[i]
            bars_since_pb_up = 99  # 翻转趋势时彻底重置回踩记忆，杜绝继承旧周期的伪回踩
            bars_since_pb_down = 99
            if state[i] == 0:
                if state[i - 1] != 0:
                    prev_non_zero_regime = state[i - 1]
                recent_box_high = h[i]
                recent_box_low = l[i]
            else:
                if prev_non_zero_regime != 0 and state[i] != prev_non_zero_regime:
                    recent_box_high = -np.inf
                    recent_box_low = np.inf
        else:
            bars_in_state += 1

        if state[i] == 0:
            recent_box_high = max(recent_box_high, h[i])
            recent_box_low = min(recent_box_low, l[i])

        cumulative_move_down = (regime_start_price - c[i]) / atr[i] if st == -1 else 0.0
        cumulative_move_up = (c[i] - regime_start_price) / atr[i] if st == 1 else 0.0

        if l[i] <= ss_fast[i] + 0.35 * atr[i] and c[i] >= ss_fast[i] - 0.25 * atr[i]:
            bars_since_pb_up = 0
        else:
            bars_since_pb_up += 1

        if h[i] >= ss_fast[i] - 0.35 * atr[i] and c[i] <= ss_fast[i] + 0.25 * atr[i]:
            bars_since_pb_down = 0
        else:
            bars_since_pb_down += 1

        pb_ready_up = (bars_since_pb_up <= 4)
        pb_ready_down = (bars_since_pb_down <= 4)

        # 宏观顺势与初生过渡态 (Emerging Trend) 判定
        # 增加动力学有序度与反持续高熵噪声门禁 (Anti-Chop Gate)
        cf_20 = df_signals["cross_freq_20"].values[i] if "cross_freq_20" in df_signals else 0.1
        er_20_val = df_signals["er_20"].values[i] if "er_20" in df_signals else 0.3
        is_anti_persistent = (causal_hurst[i] <= 0.50 and perm_entropy[i] >= 0.88) or (cf_20 >= 0.25 and er_20_val < 0.20) or (physics_trend[i] < 0.08 and abs(mder) < 0.15)
        trend_qual = (pc >= p_cont_threshold) and (curr_ts >= 28.0) and not is_anti_persistent and (physics_trend[i] >= 0.12 or abs(mder) >= 0.15)
        trend_qual_short = trend_qual
        trend_qual_long = trend_qual

        # Q10 修复: 宏观状态显式集合判断，消除 mst=2 (TRANSITION) 比较大小时多头放行空头被拒的不对称偏置
        mst_short_ok = mst in (-1, 0)
        mst_long_ok = mst in (1, 0)

        can_trend_short = (
            trend_qual_short
            and (st == -1)
            and (c[i] < ss_fast[i])
            and (
                (mst == -1 and mder <= 0.0)
                or (mst == 0 and curr_ds <= -0.30 and mder <= 0.10)
                or (curr_ds <= -0.45 and mst_short_ok)
            )
        )
        can_trend_long = (
            trend_qual_long
            and (st == 1)
            and (c[i] > ss_fast[i])
            and (
                (mst == 1 and mder >= 0.0)
                or (mst == 0 and curr_ds >= 0.30 and mder >= -0.10)
                or (curr_ds >= 0.45 and mst_long_ok)
            )
        )

        dist_up = (c[i] - ss_fast[i]) / atr[i]
        dist_down = (ss_fast[i] - c[i]) / atr[i]

        # 波浪中继箱体真突破准则
        box_break_down = (c[i] < recent_box_low) if (prev_non_zero_regime == -1 and np.isfinite(recent_box_low) and bars_in_state <= 5) else True
        box_break_up = (c[i] > recent_box_high) if (prev_non_zero_regime == 1 and np.isfinite(recent_box_high) and bars_in_state <= 5) else True

        # ====== 分支 A: 顺势动量通道 (Trend Springboard Mode) ======
        # 0. 趋势初生破位启动触发 (Kickoff Channel)
        max_kickoff_dist = 2.8 if abs(curr_ds) >= 0.50 else 2.2
        kickoff_down = (bars_in_state <= 2) and box_break_down and (c[i] < ss_fast[i]) and (c[i] < o[i]) and (body_ratio[i] >= 0.35) and (o[i] - c[i] >= 0.30 * atr[i]) and (0.0 <= dist_down <= max_kickoff_dist) and (curr_ds <= -0.30) and (curr_ts >= 32.0)
        kickoff_up = (bars_in_state <= 2) and box_break_up and (c[i] > ss_fast[i]) and (c[i] > o[i]) and (body_ratio[i] >= 0.35) and (c[i] - o[i] >= 0.30 * atr[i]) and (0.0 <= dist_up <= max_kickoff_dist) and (curr_ds >= 0.30) and (curr_ts >= 32.0)

        # 1. 记忆回抽恢复触发 (依赖 dist <= 1.8 ATR 与 pb_ready 特征防追高，允许健康波段中继回踩持续上车)
        resume_down = (
            pb_ready_down
            and box_break_down
            and (c[i] < o[i])
            and (body_ratio[i] >= 0.30)
            and (i > 0 and c[i] < l[i - 1])
            and (c[i] < ss_fast[i])
            and (0.0 <= dist_down <= 1.8)
            and (ext[i] > -2.5)
        )
        resume_up = (
            pb_ready_up
            and box_break_up
            and (c[i] > o[i])
            and (body_ratio[i] >= 0.30)
            and (i > 0 and c[i] > h[i - 1])
            and (c[i] > ss_fast[i])
            and (0.0 <= dist_up <= 1.8)
            and (ext[i] < 2.5)
        )

        # 2. 动量突破触发 (急跌/急涨主浪: 限制在前期 bars_in_state <= 5，且排除恐慌耗竭巨阴线 <= 1.8 ATR，且顺应宏观大势)
        breakout_down = (
            mst_short_ok
            and (had_squeeze[i] or curr_ts >= 40.0)
            and (bars_in_state <= 5)
            and box_break_down
            and (cumulative_move_down <= 2.5)
            and (o[i] - c[i] <= 1.8 * atr[i])
            and (c[i] < l20[i])
            and (c[i] < ss_fast[i])
            and (c[i] < o[i])
            and (body_ratio[i] >= 0.38)
            and (o[i] - c[i] >= 0.35 * atr[i])
            and (dist_down <= 2.2)
        )
        breakout_up = (
            mst_long_ok
            and (had_squeeze[i] or curr_ts >= 40.0)
            and (bars_in_state <= 5)
            and box_break_up
            and (cumulative_move_up <= 2.5)
            and (c[i] - o[i] <= 1.8 * atr[i])
            and (c[i] > h20[i])
            and (c[i] > ss_fast[i])
            and (c[i] > o[i])
            and (body_ratio[i] >= 0.38)
            and (c[i] - o[i] >= 0.35 * atr[i])
            and (dist_up <= 2.2)
        )

        squeeze_impulse_up = had_squeeze[i] and (c[i] - o[i] >= 0.45 * atr[i]) and (body_ratio[i] >= 0.40) and (0.0 <= dist_up <= 1.2)
        squeeze_impulse_down = had_squeeze[i] and (o[i] - c[i] >= 0.45 * atr[i]) and (body_ratio[i] >= 0.40) and (0.0 <= dist_down <= 1.2)

        if can_trend_short and (kickoff_down or resume_down or squeeze_impulse_down or breakout_down):
            raw_signals[i] = -1
            signal_sources[i] = 1
            confidence[i] = np.clip(pc, 0.50, 0.95)
        elif can_trend_long and (kickoff_up or resume_up or squeeze_impulse_up or breakout_up):
            raw_signals[i] = 1
            signal_sources[i] = 1
            confidence[i] = np.clip(pc, 0.50, 0.95)

        # ====== 分支 B: 震荡箱体边界极值均值回归通道 (Confirmed Ranging Box Mode) ======
        # ponytail: 严格隔离中性过渡态(Transition)与箱体震荡。只有当微观/宏观双中性、DER绝对值<0.10且Hurst<=0.52具备均值回复特征时才开放回归通道
        elif (mst == 0) and (st == 0) and (abs(mder) < 0.10) and (df_signals["causal_hurst"].values[i] <= 0.52):
            target_dist_up = (filt_mean[i] - c[i]) / atr[i]
            target_dist_down = (c[i] - filt_mean[i]) / atr[i]
            kalman_vel = df_signals["kalman_norm_vel"].values[i]
            # 箱体下沿极值做多 (强化 st != -1 与防跌门禁，杜绝顺势暴跌中左侧接飞刀)
            if mpos <= -0.65 and st != -1 and kalman_vel >= -0.10 and curr_ds >= -0.15 and robust_z[i] <= -1.60 and target_dist_up >= 1.2 and c[i] > o[i] and body_ratio[i] >= 0.35:
                raw_signals[i] = 1
                signal_sources[i] = 2
                confidence[i] = 0.65
            # 箱体上沿极值做空 (强化 st != 1 与防涨门禁，杜绝主升浪中逆势摸顶)
            elif mpos >= 0.65 and st != 1 and kalman_vel <= 0.10 and curr_ds <= 0.15 and robust_z[i] >= 1.60 and target_dist_down >= 1.2 and c[i] < o[i] and body_ratio[i] >= 0.35:
                raw_signals[i] = -1
                signal_sources[i] = 2
                confidence[i] = 0.65

    df_signals["raw_signal"] = raw_signals
    df_signals["signal_source"] = signal_sources
    df_signals["confidence"] = confidence

    df_signals.attrs["chandelier_mult"] = chandelier_mult
    df_signals.attrs["reversion_stop_mult"] = reversion_stop_mult
    return df_signals
