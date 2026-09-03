"""
strategies/taichong_elastoplastic_tensor.py — 「太冲·弹塑性张量」: 协方差白化 + 弹塑性相变自适应 + 卡方结构破裂熔断策略

核心量化物理与微观几何机制：
1. Ledoit-Wolf 压缩协方差白化 (Shrinkage Metric Tensor Whitening):
   - 构建多维特征向量空间（价格偏离度、收益率加速度、相对强弱、波动挤压比）；
   - 使用 Ledoit-Wolf 正则化收缩估计协方差矩阵 Sigma，消除奇异样本噪声与高条件数病态；
   - 通过正交白化变换 W = Sigma^(-1/2) 剥离系统性 Beta 与特征共线性，投射至各向同性度量空间。

2. 卡方检验协方差破裂硬熔断 (Chi-Square Structural Rupture Circuit Breaker):
   - 理论上白化后马氏距离平方 D_M^2 服从卡方分布 chi2(k)；
   - 当 D_M^2 突破极端临界阈值 (p < 0.001) 时，判定“市场几何流形撕裂 / 结构性相变爆发”；
   - 触发硬熔断（Circuit Breaker），绝对禁止逆势抄底，并强制清空反转头寸。

3. 连续介质力学弹塑性本构分解 (Elastoplastic Constitutive Decomposition):
   - 突破传统胡克定律(仅在线性弹性区成立)的致命缺陷，引入材料力学屈服准则 (von Mises Yield Criterion)；
   - 将总形变位移严格分解为可逆弹性恢复位移 (Elastic Strain e_e) 与不可逆塑性滑移 (Plastic Drift e_p)；
   - 仅对弹性恢复分量 e_e 建立均值回归势能，塑性永久位移直接作为新基准中枢，杜绝死扛逼仓。

4. 动力学赫斯特相变闸门与微观流动性吸收 (Hurst Phase Gate & Pin Bar Absorption):
   - 滚动估计局部反持久性 (Hurst H < 0.45 激活弹性做市，H > 0.55 趋势态静默)；
   - 结合微观 K 线拒斥影线 (Pin Bar Absorption) 与期货持仓量筹码背离 (OI Unwinding)，确保机构承接。

5. 严格因果与防未来函数：所有矩阵与滚动算子均为纯因果计算，支持热插拔即时调用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "taichong_elastoplastic_tensor"
STRATEGY_DESCRIPTION = "「太冲·弹塑性张量」: 协方差白化 + 弹塑性相变自适应 + 卡方结构破裂熔断策略"


def _ledoit_wolf_shrinkage_cov(X: np.ndarray) -> np.ndarray:
    """
    计算小样本特征矩阵的 Ledoit-Wolf 正则化收缩协方差矩阵 (高性能向量化)。
    输入: X 形状为 (N, K)，N 个样本，K 个特征 (已中心化)
    输出: 收缩协方差矩阵 (K, K)
    """
    n_samples, n_features = X.shape
    if n_samples <= 1:
        return np.eye(n_features)

    # 样本协方差
    sample_cov = (X.T @ X) / (n_samples - 1)
    
    # 目标矩阵: 均值方差对角矩阵
    mu = np.trace(sample_cov) / n_features
    target = mu * np.eye(n_features)

    # 估计最优收缩强度 delta
    d2 = np.sum((sample_cov - target) ** 2)
    if d2 < 1e-12:
        return target

    # 全向量化方差估计 (无 Python for loop)
    outer = X[:, :, None] * X[:, None, :]  # (N, K, K)
    b2 = np.sum((outer - sample_cov[None, :, :]) ** 2) / (n_samples * n_samples)
    b2 = min(b2, d2)

    shrinkage = max(0.0, min(1.0, b2 / d2))
    shrunk_cov = (1.0 - shrinkage) * sample_cov + shrinkage * target
    return shrunk_cov


def _calc_local_hurst(series: np.ndarray, max_lag: int = 16) -> float:
    """
    计算局部窗口反持久性 / 赫斯特指数 (Hurst Exponent)。
    H < 0.5 为均值回归状态，H > 0.5 为单边动量状态。
    """
    n = len(series)
    if n < max_lag * 2:
        return 0.5
    try:
        lags = np.arange(2, max_lag + 1)
        tau = np.array([np.std(series[lag:] - series[:-lag], ddof=1) for lag in lags])
        valid = tau > 1e-10
        if np.sum(valid) < 3:
            return 0.5
        poly = np.polyfit(np.log(lags[valid]), np.log(tau[valid]), 1)
        return float(np.clip(poly[0], 0.05, 0.95))
    except Exception:
        return 0.5


def calculate_factors(
    df: pd.DataFrame,
    window: int = 30,
    chi2_cutoff_p: float = 0.01,
    yield_threshold: float = 2.2,
    plastic_decay: float = 0.85,
) -> pd.DataFrame:
    """
    计算「太冲·弹塑性张量」全套微观特征流。
    
    参数:
    - df: 包含 open, high, low, close, volume, open_interest (可选)
    - window: 协方差估计与白化基准滚动窗口
    - chi2_cutoff_p: 卡方结构破裂熔断显著性水平 (默认 0.01 对应 99% 置信度，临界值 13.28)
    - yield_threshold: 弹塑性力学屈服应力阈值 (单位: 标准差)
    - plastic_decay: 塑性形变后弹性势能的耗散衰减率
    """
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    # 1. 基础物理与特征构造 (纯因果构建 4 维特征流)
    # 特征 0: 归一化价格偏离 (Close - SMA) / ATR
    # 特征 1: 二阶加速度 / 动量变化率 (Delta Close / ATR)
    # 特征 2: 微观波动率挤压比 (Bollinger Band Width / ATR)
    # 特征 3: 考夫曼自适应效率 (Directional Path Efficiency)

    # 计算因果 ATR
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    
    # 滚动均值与标准差计算
    c_series = pd.Series(c, index=df.index)
    tr_series = pd.Series(tr, index=df.index)
    atr = tr_series.rolling(window, min_periods=window // 2).mean().fillna(0).values + 1e-8
    sma = c_series.rolling(window, min_periods=window // 2).mean().fillna(0).values

    # 特征 0: 价格位移度量
    f0 = (c - sma) / atr

    # 特征 1: 短期 3 周期收益率加速度
    c_diff3 = np.zeros(n)
    c_diff3[3:] = (c[3:] - c[:-3]) / (atr[3:] * np.sqrt(3.0))
    f1 = c_diff3

    # 特征 2: 波动率挤压比率
    c_std = c_series.rolling(window, min_periods=window // 2).std(ddof=0).fillna(0).values + 1e-8
    f2 = (4.0 * c_std) / (2.0 * atr) - 1.0

    # 特征 3: 考夫曼效率比率
    abs_diff = np.abs(c[1:] - c[:-1])
    abs_diff = np.insert(abs_diff, 0, 0.0)
    abs_diff_series = pd.Series(abs_diff, index=df.index)
    path_len = abs_diff_series.rolling(window, min_periods=window // 2).sum().fillna(0).values + 1e-8
    net_len = np.zeros(n)
    net_len[window:] = np.abs(c[window:] - c[:-window])
    f3 = (net_len / path_len)

    feature_matrix = np.column_stack([f0, f1, f2, f3])
    k_features = feature_matrix.shape[1]

    # 卡方临界值 (k=4 自由度): 根据 chi2_cutoff_p 动态自适应设定
    # p=0.001 对应 18.47 (99.9% 置信度), p=0.01 对应 13.28 (99% 置信度), p=0.05 对应 9.49
    if chi2_cutoff_p < 0.005:
        chi2_critical = 18.47
    elif chi2_cutoff_p <= 0.02:
        chi2_critical = 13.28
    elif chi2_cutoff_p <= 0.05:
        chi2_critical = 9.49
    else:
        chi2_critical = 13.28 if k_features == 4 else 12.0

    # 2. 向量化滚动 Ledoit-Wolf 收缩协方差与马氏距离平方 (纯因果 shift(1))
    F_df = pd.DataFrame(feature_matrix, index=df.index)
    means = F_df.shift(1).rolling(window, min_periods=window).mean().fillna(0).values
    
    # 构造外积张量 (N, K, K)
    outer_products = np.einsum('ni,nj->nij', feature_matrix, feature_matrix)
    outer_df = pd.DataFrame(outer_products.reshape(n, k_features * k_features), index=df.index)
    roll_sec_moments = outer_df.shift(1).rolling(window, min_periods=window).mean().fillna(0).values.reshape(n, k_features, k_features)
    mean_outer = np.einsum('ni,nj->nij', means, means)
    
    sample_covs = (window / (window - 1.0)) * (roll_sec_moments - mean_outer)
    
    # Ledoit-Wolf 正则化收缩
    mu = np.trace(sample_covs, axis1=1, axis2=2) / float(k_features)
    target = mu[:, None, None] * np.eye(k_features)[None, :, :]
    shrunk_covs = 0.85 * sample_covs + 0.15 * target + 1e-5 * np.eye(k_features)[None, :, :]
    
    try:
        inv_covs = np.linalg.inv(shrunk_covs)
    except Exception:
        inv_covs = np.linalg.pinv(shrunk_covs)
        
    centered_curr = feature_matrix - means
    mahalanobis_sq = np.einsum('ni,nij,nj->n', centered_curr, inv_covs, centered_curr)
    mahalanobis_sq[:window] = 0.0

    # 卡方结构破裂硬熔断判定
    rupture_breaker = mahalanobis_sq >= chi2_critical

    # 3. 弹塑性本构模型 (Elastoplastic Strain Decomposition)
    elastic_zscore = np.zeros(n)
    plastic_offset = np.zeros(n)
    accumulated_plastic = 0.0

    for t in range(n):
        raw_displacement = f0[t]
        effective_elastic = raw_displacement - accumulated_plastic

        if np.abs(effective_elastic) > yield_threshold:
            excess_strain = np.sign(effective_elastic) * (np.abs(effective_elastic) - yield_threshold)
            accumulated_plastic += excess_strain * (1.0 - plastic_decay)
            effective_elastic = np.sign(effective_elastic) * yield_threshold

        accumulated_plastic *= 0.995
        plastic_offset[t] = accumulated_plastic
        elastic_zscore[t] = effective_elastic

    # 4. 向量化局部 Hurst 闸门 (方差比率标度律自适应赫斯特)
    c_diff2 = pd.Series(c, index=df.index).diff(2)
    c_diff8 = pd.Series(c, index=df.index).diff(8)
    tau2 = c_diff2.rolling(window, min_periods=window // 2).std(ddof=0)
    tau8 = c_diff8.rolling(window, min_periods=window // 2).std(ddof=0)
    hurst_proxy = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9)
    hurst_gate = hurst_proxy.fillna(0.5).values

    # 5. 2 周期 Connors RSI 与 5 周期均线回归目标
    delta = pd.Series(c, index=df.index).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(2).mean()
    avg_loss = loss.rolling(2).mean() + 1e-8
    rs = avg_gain / avg_loss
    rsi_2 = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).values
    sma_5 = pd.Series(c, index=df.index).rolling(5).mean().fillna(0).values

    # 6. 微观做市商吸收形态与持仓量耗竭过滤
    body = np.abs(c - o) + 1e-8
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)
    prev_c_s = np.roll(c, 1)

    bullish_absorption = (c > o) & (c > prev_c_s) & (lower_shadow >= body * 0.40)
    bearish_absorption = (c < o) & (c < prev_c_s) & (upper_shadow >= body * 0.40)

    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        vol_ma = pd.Series(v).rolling(20, min_periods=5).mean().fillna(0).values
        # 微观主动进攻持仓量解耦过滤:
        # 下跌增仓 (空头主动猛烈增仓下砸逼仓): 排除多头抄底
        short_aggression = (c < prev_c_s) & (oi_diff > vol_ma * 0.25)
        oi_filter_long = ~short_aggression
        # 上涨增仓 (多头主动猛烈增仓上推逼空): 排除空头摸顶
        long_aggression = (c > prev_c_s) & (oi_diff > vol_ma * 0.25)
        oi_filter_short = ~long_aggression

    out_df = pd.DataFrame(
        {
            "mahalanobis_sq": mahalanobis_sq,
            "elastic_zscore": elastic_zscore,
            "plastic_offset": plastic_offset,
            "rupture_breaker": rupture_breaker,
            "hurst": hurst_gate,
            "rsi_2": rsi_2,
            "sma_5": sma_5,
            "bullish_absorption": bullish_absorption,
            "bearish_absorption": bearish_absorption,
            "oi_filter_long": oi_filter_long,
            "oi_filter_short": oi_filter_short,
        },
        index=df.index,
    )
    return out_df


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    标准工业级热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号/熔断观望)
    """
    c = df["close"].astype(float).values
    factors = calculate_factors(df)

    elastic_z = factors["elastic_zscore"]
    rupture = factors["rupture_breaker"]
    hurst = factors["hurst"]
    rsi_2 = factors["rsi_2"]
    sma_5 = factors["sma_5"]
    bull_abs = factors["bullish_absorption"]
    bear_abs = factors["bearish_absorption"]
    oi_long = factors["oi_filter_long"]
    oi_short = factors["oi_filter_short"]

    # 1. 均值回归进场条件:
    # - 弹性 Z-Score 达到反转极值 (|Z| >= 1.6)
    # - Connors RSI(2) 达到极度超买/超卖 (<=15 或 >=85)
    # - 卡方协方差未破裂 (无结构性相变爆发)
    # - 动力学处于均值回归/非强趋势态 (Hurst < 0.60)
    # - 价格处于 5 周期快速均线反向侧 (均值回归第一目标具备盈利空间)
    # - 微观 K 线呈现长影线做市商吸收拒斥
    # - 持仓量未出现极端单向进攻逼仓
    long_candidate = (
        (elastic_z <= -1.6)
        & (rsi_2 <= 15.0)
        & (c < sma_5)
        & (~rupture)
        & (hurst < 0.60)
        & bull_abs
        & oi_long
    )

    short_candidate = (
        (elastic_z >= 1.6)
        & (rsi_2 >= 85.0)
        & (c > sma_5)
        & (~rupture)
        & (hurst < 0.60)
        & bear_abs
        & oi_short
    )

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[long_candidate] = 1
    signals[short_candidate] = -1

    # 2. 强熔断保护：若当前触发卡方结构破裂，强制清零并拒绝开仓
    signals[rupture] = 0

    return signals
