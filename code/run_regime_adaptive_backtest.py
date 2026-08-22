"""
code/run_regime_adaptive_backtest.py — 市场机制识别 (Regime Shift) 与离散状态自适应科学回测引擎

核心量化物理与科学架构：
1. 机制识别维度 (Multi-Dimensional Regime Quantization):
   - 分形维数/记忆性: Variance Ratio proxy for Hurst Exponent (H > 0.52 趋势, H < 0.48 均值回归)
   - 效率比率 (Kaufman ER): 方向位移 / 路径总长 (ER >= 0.28 高效单边, ER <= 0.18 杂乱震荡)
   - 波动率分布 (ATR Squeeze/Expansion): ATR(7)/ATR(28) 动态局部能量释放
   - 趋向强度 (ADX): ADX(14) >= 22 强方向性
   - 成交量聚集 (Volume Clustering): Volume / SMA(Volume, 20) 与持仓筹码流 (OI Flow)

2. 离散固化三态状态机 (3-State Discrete State Machine):
   - 状态 1 [STRONG_TREND]: 趋势爆发态 -> 自动激活 SuperTrend/AlphaTrend 顺势跟踪 + Chandelier Exit
   - 状态 2 [MEAN_REVERSION]: 极值震荡态 -> 自动激活 Z-Score 极值反包 + SMA(5) 极速止盈与保本锁
   - 状态 0 [DORMANT_CHAOS]: 低波挤压/无序混沌态 -> 强制休眠观望，零开仓避免无谓磨损

3. 机器学习智能门控 (ML Meta-Router):
   - 使用 Walk-Forward LightGBM 预测一阶状态机信号在当前微观结构下的真实条件胜率 P(Success | Regime, Micro)
   - 假机制破位拦截 + Lopez de Prado 置信度仓位缩放 (Bet Sizing)

4. 对照组实证实验设计:
   - 对照 A: 单一纯趋势策略 (Pure Trend - SuperTrend V2)
   - 对照 B: 单一纯均值回归策略 (Pure Reversion - Z-Score V2)
   - 实验 C: 纯物理规则离散状态机自适应 (Regime State Machine V1)
   - 实验 D: 机器学习增强型自适应状态机 (Regime State Machine + ML Meta Router V2)
"""

import sys
import sqlite3
import argparse
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_adx, calculate_rsi
from strategies.supertrend_strategy import calculate_signal as calc_supertrend_sig
from strategies.alphatrend_strategy import calculate_signal as calc_alphatrend_sig

COMMODITY_UNIVERSE = [
    "AU_IDX", "AG_IDX", "SC_IDX", "TA_IDX", "CU_IDX", "RB_IDX", "HC_IDX", "I_IDX",
    "SA_IDX", "MA_IDX", "J_IDX",  "JM_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "RU_IDX",
    "M_IDX",  "P_IDX",  "LC_IDX", "SR_IDX", "CF_IDX", "FG_IDX", "SI_IDX", "C_IDX",  "Y_IDX"
]


def load_symbol_data(symbol: str, timeframe: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
            conn, params=(symbol, timeframe)
        )
    if len(df) > 0:
        df["datetime"] = pd.to_datetime(df["trade_time"])
        for col in ["open", "high", "low", "close", "volume", "open_interest"]:
            df[col] = df[col].astype(float)
    return df


def compute_market_regimes_and_features(df: pd.DataFrame, macro_freq: str = "60min") -> pd.DataFrame:
    """计算多维物理机制指标，并构建离散状态机标签与微观特征矩阵"""
    df_feat = df.copy()
    c = df_feat["close"].values
    o = df_feat["open"].values
    h = df_feat["high"].values
    l = df_feat["low"].values
    v = df_feat["volume"].values
    n = len(df_feat)

    # 1. Kaufman Efficiency Ratio (ER: 20-period)
    change = np.abs(c - np.roll(c, 20))
    diffs = np.abs(c - np.roll(c, 1))
    path = pd.Series(diffs).rolling(20).sum().fillna(1e-5).values
    er = np.where(path > 1e-5, change / path, 0.0)
    er[:20] = 0.25
    df_feat["er"] = er

    # 2. Variance Ratio proxy for Hurst Exponent (30-period window)
    ret1 = pd.Series(c).pct_change(1)
    ret5 = pd.Series(c).pct_change(5)
    var1 = ret1.rolling(30).var().fillna(1e-6).values
    var5 = ret5.rolling(30).var().fillna(1e-6).values
    vr_5 = np.where(var1 > 1e-8, var5 / (5.0 * var1 + 1e-8), 1.0)
    hurst_proxy = 0.5 * (1.0 + np.log(np.clip(vr_5, 0.1, 10.0)) / np.log(5.0))
    hurst_proxy = np.nan_to_num(hurst_proxy, nan=0.5)
    df_feat["hurst"] = hurst_proxy

    # 3. ATR Squeeze / Expansion Ratio
    atr_7 = calculate_atr(df_feat, 7).fillna(method="bfill").values
    atr_14 = calculate_atr(df_feat, 14).fillna(method="bfill").values
    atr_28 = calculate_atr(df_feat, 28).fillna(method="bfill").values
    squeeze_ratio = np.where(atr_28 > 0, atr_7 / (atr_28 + 1e-8), 1.0)
    df_feat["atr_14"] = atr_14
    df_feat["squeeze"] = squeeze_ratio

    # 4. ADX (14) Trend Strength
    adx_arr = calculate_adx(df_feat, 14).fillna(0).values
    df_feat["adx"] = adx_arr

    # 5. Volume Clustering & Open Interest Flow
    vol_ma20 = pd.Series(v).rolling(20).mean().fillna(method="bfill").values
    vol_ratio = np.where(vol_ma20 > 0, v / (vol_ma20 + 1e-8), 1.0)
    df_feat["vol_ratio"] = vol_ratio

    oi = df_feat["open_interest"].values
    oi_diff = np.diff(oi, prepend=oi[0])
    df_feat["oi_flow"] = np.where(vol_ma20 > 0, oi_diff / (vol_ma20 + 1e-8), 0.0)

    # 6. Z-Score (20) & RSI (2)
    sma_20 = pd.Series(c).rolling(20).mean().values
    std_20 = pd.Series(c).rolling(20).std().fillna(1e-4).values
    zscore = np.where(std_20 > 1e-6, (c - sma_20) / std_20, 0.0)
    df_feat["zscore"] = zscore
    df_feat["sma_20"] = sma_20
    df_feat["sma_5"] = pd.Series(c).rolling(5).mean().values

    # RSI(2)
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).rolling(2).mean().values
    avg_loss = pd.Series(loss).rolling(2).mean().values + 1e-8
    df_feat["rsi_2"] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    # 7. Micro Pin Bar Absorption
    body = np.abs(c - o)
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)
    df_feat["pin_long"] = np.where(body > 0, lower_shadow / (body + 1e-8), 0.0)
    df_feat["pin_short"] = np.where(body > 0, upper_shadow / (body + 1e-8), 0.0)

    # 8. 宏观跨周期趋势对齐 (Macro Trend Alignment)
    df_ts = df_feat.set_index("datetime").copy()
    df_macro = df_ts.resample(macro_freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()
    c_macro = df_macro["close"]
    ema20 = calculate_ema(c_macro, 20)
    macro_dir = np.where(c_macro > ema20, 1, np.where(c_macro < ema20, -1, 0))
    df_macro["macro_trend"] = pd.Series(macro_dir, index=df_macro.index).shift(1)
    df_aligned = pd.merge_asof(
        df_feat[["datetime"]].copy(), df_macro[["macro_trend"]].reset_index().rename(columns={"index": "datetime"}),
        on="datetime", direction="backward"
    )
    df_feat["macro_trend"] = df_aligned["macro_trend"].fillna(0).values.astype(int)

    # 9. 离散物理状态机核心判别逻辑 (Regime State Machine):
    # 状态 1 (TREND): Hurst >= 0.52 或 ER >= 0.28, 且 ADX >= 22, 且 Squeeze >= 0.70
    # 状态 2 (REVERSION): Hurst <= 0.48 或 ER <= 0.20, 且 ADX < 22
    # 状态 0 (DORMANT): 极低挤压 Squeeze < 0.65 或 不满足上述两者的混沌过渡态
    regimes = np.zeros(n, dtype=int)
    for i in range(30, n):
        h_val = hurst_proxy[i]
        er_val = er[i]
        adx_val = adx_arr[i]
        sq_val = squeeze_ratio[i]

        is_trend = (h_val >= 0.52 or er_val >= 0.28) and (adx_val >= 22) and (sq_val >= 0.70)
        is_revert = (h_val <= 0.48 or er_val <= 0.20) and (adx_val < 22)

        if sq_val < 0.65:
            regimes[i] = 0  # 强制休眠，规避低波变盘与假突破
        elif is_trend:
            regimes[i] = 1  # 趋势爆发态
        elif is_revert:
            regimes[i] = 2  # 震荡回归态
        else:
            regimes[i] = 0  # 混沌中性态休眠

    df_feat["regime"] = regimes
    return df_feat


def generate_adaptive_signals(df_feat: pd.DataFrame) -> pd.DataFrame:
    """根据离散市场机制分发自适应策略信号与意图元标签"""
    df_res = df_feat.copy()
    n = len(df_res)

    c = df_res["close"].values
    o = df_res["open"].values
    sma_5 = df_res["sma_5"].values
    zscore = df_res["zscore"].values
    rsi_2 = df_res["rsi_2"].values
    pin_l = df_res["pin_long"].values
    pin_s = df_res["pin_short"].values
    oi_flow = df_res["oi_flow"].values
    macro_t = df_res["macro_trend"].values
    regimes = df_res["regime"].values

    # 1. 趋势原始信号 (SuperTrend)
    st_sig = calc_supertrend_sig(df_res, period=10, multiplier=3.0).values

    # 2. 均值回归原始信号 (Z-Score + PinBar + OI)
    revert_long = (zscore <= -2.0) & (rsi_2 <= 15.0) & (c > o) & (pin_l >= 0.5) & (c < sma_5) & (oi_flow <= 0.5)
    revert_short = (zscore >= 2.0) & (rsi_2 >= 85.0) & (c < o) & (pin_s >= 0.5) & (c > sma_5) & (oi_flow <= 0.5)

    # 3. 机制分发信号
    adaptive_sig = np.zeros(n, dtype=int)
    signal_source = np.zeros(n, dtype=int)  # 1: Trend, 2: Mean Reversion, 0: None

    for i in range(1, n):
        r = regimes[i - 1]  # 严格使用上一根 Bar 判定当前机制
        if r == 1:
            # 趋势态: 仅接受顺宏观趋势的 SuperTrend 信号
            sig = st_sig[i]
            if (sig == 1 and macro_t[i - 1] >= 0) or (sig == -1 and macro_t[i - 1] <= 0):
                adaptive_sig[i] = sig
                signal_source[i] = 1
        elif r == 2:
            # 震荡态: 仅接受 Z-Score 极值回归信号
            if revert_long[i]:
                adaptive_sig[i] = 1
                signal_source[i] = 2
            elif revert_short[i]:
                adaptive_sig[i] = -1
                signal_source[i] = 2
        # r == 0: 休眠态，不发出任何开仓信号

    df_res["adaptive_sig"] = adaptive_sig
    df_res["signal_source"] = signal_source

    # 4. 生成二阶 Meta-Labeling 标签 (用于训练 ML Meta Router)
    meta_labels = np.full(n, np.nan)
    high_arr = df_res["high"].values
    low_arr = df_res["low"].values
    atr_arr = df_res["atr_14"].values

    for i in range(n - 10):
        sig = adaptive_sig[i]
        src = signal_source[i]
        if sig == 0:
            continue

        p0 = c[i]
        atr = max(2.0, float(atr_arr[i]))

        if src == 1:
            # 趋势目标: 3.0 ATR 跟踪或盈亏比 >= 1.5 为正样本
            sl = p0 - 2.5 * atr if sig == 1 else p0 + 2.5 * atr
            hit = 0
            for b in range(1, 10):
                h_b, l_b = high_arr[i + b], low_arr[i + b]
                if sig == 1:
                    if l_b <= sl:
                        hit = 0
                        break
                    if h_b >= p0 + 3.0 * atr:
                        hit = 1
                        break
                else:
                    if h_b >= sl:
                        hit = 0
                        break
                    if l_b <= p0 - 3.0 * atr:
                        hit = 1
                        break
            meta_labels[i] = hit

        elif src == 2:
            # 均值回归目标: 回归 SMA(5) 为正样本，触及 1.2 ATR 止损为负样本
            sl = p0 - 1.2 * atr if sig == 1 else p0 + 1.2 * atr
            hit = 0
            for b in range(1, 6):
                h_b, l_b = high_arr[i + b], low_arr[i + b]
                target_sma5 = sma_5[i + b]
                if sig == 1:
                    if l_b <= sl:
                        hit = 0
                        break
                    if h_b >= target_sma5:
                        hit = 1
                        break
                else:
                    if h_b >= sl:
                        hit = 0
                        break
                    if l_b <= target_sma5:
                        hit = 1
                        break
            meta_labels[i] = hit

    df_res["meta_label"] = meta_labels
    return df_res


def train_walk_forward_meta_router(df_feat: pd.DataFrame, feature_cols: list, train_window: int = 2500, step_size: int = 500) -> np.ndarray:
    """Walk-Forward 滚动增量训练 ML Meta-Router 机制概率门控"""
    n = len(df_feat)
    prob_meta = np.full(n, np.nan)
    valid_idx = np.where(~np.isnan(df_feat["meta_label"].values))[0]

    if len(valid_idx) < 10:
        prob_meta[valid_idx] = 0.50
        return prob_meta

    X_all = df_feat[feature_cols].values.astype(np.float32)
    y_all = df_feat["meta_label"].values

    current_idx = train_window
    while current_idx < n:
        train_mask = (valid_idx < current_idx)
        train_sample_idx = valid_idx[train_mask]

        if len(train_sample_idx) >= 10 and len(np.unique(y_all[train_sample_idx])) > 1:
            X_tr = X_all[train_sample_idx]
            y_tr = y_all[train_sample_idx].astype(int)

            clf = lgb.LGBMClassifier(
                n_estimators=35, learning_rate=0.03, max_depth=3, num_leaves=6,
                min_child_samples=4, class_weight="balanced", random_state=42, verbose=-1, n_jobs=1
            )
            clf.fit(X_tr, y_tr)

            test_start = current_idx
            test_end = min(n, current_idx + step_size)
            test_mask = (valid_idx >= test_start) & (valid_idx < test_end)
            test_sample_idx = valid_idx[test_mask]

            if len(test_sample_idx) > 0:
                prob_meta[test_sample_idx] = clf.predict_proba(X_all[test_sample_idx])[:, 1]

        current_idx += step_size

    prob_meta[np.isnan(prob_meta) & ~np.isnan(df_feat["meta_label"].values)] = 0.50
    return prob_meta


def simulate_adaptive_engine(
    df: pd.DataFrame, cfg: dict,
    use_ml_meta: bool = False,
    meta_thresh: float = 0.52,
    initial_balance: float = 1000000.0
) -> dict:
    """真实逐 Bar 机制自适应混合撮合回测仿真器 (动态兼容趋势与均值回归双模出场)"""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": [], "regime_dist": {}, "filtered_by_ml": 0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    sig_vals = df["adaptive_sig"].values
    source_vals = df["signal_source"].values
    prob_vals = df["meta_prob"].values if "meta_prob" in df.columns else np.full(n, 1.0)
    sma5_vals = df["sma_5"].values
    atr_vals = df["atr_14"].values
    regime_vals = df["regime"].values

    pos = 0  # 1=Long, -1=Short, 0=Flat
    current_source = 0  # 1=Trend, 2=Mean Reversion
    lots = 0
    entry_p = 0.0
    entry_dt = ""
    holding_bars = 0
    trailing_stop = 0.0
    highest_p = 0.0
    lowest_p = float("inf")

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance
    filtered_by_ml = 0

    for i in range(1, n):
        curr_sig = sig_vals[i - 1]
        curr_src = source_vals[i - 1]
        curr_prob = prob_vals[i - 1]
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(2.0, atr_vals[i - 1])

        # 1. 持仓出场与动态防守 (根据持仓类型执行专属出场机制)
        if pos != 0:
            holding_bars += 1
            exit_hit = False
            exit_p = curr_open
            exit_reason = ""

            if current_source == 1:
                # --- 趋势仓位出场: Chandelier Exit 3.0 ATR 动态锁利跟踪 ---
                if pos == 1:
                    highest_p = max(highest_p, curr_high)
                    new_stop = highest_p - 3.0 * curr_atr
                    trailing_stop = max(trailing_stop, new_stop)
                    if curr_low <= trailing_stop:
                        exit_hit = True
                        exit_p = min(curr_open, trailing_stop)
                        exit_reason = "趋势仓位 Chandelier 跟踪止损"
                elif pos == -1:
                    lowest_p = min(lowest_p, curr_low)
                    new_stop = lowest_p + 3.0 * curr_atr
                    trailing_stop = min(trailing_stop, new_stop)
                    if curr_high >= trailing_stop:
                        exit_hit = True
                        exit_p = max(curr_open, trailing_stop)
                        exit_reason = "趋势仓位 Chandelier 跟踪止损"

            elif current_source == 2:
                # --- 均值回归仓位出场: SMA(5) 极速止盈 vs 1.2 ATR 硬止损 vs 5 Bar 超时 ---
                target_sma5 = sma5_vals[i]
                if pos == 1:
                    if curr_high >= target_sma5:
                        exit_hit = True
                        exit_p = target_sma5
                        exit_reason = "均值回归 SMA(5) 极速止盈"
                    elif curr_low <= trailing_stop:
                        exit_hit = True
                        exit_p = min(curr_open, trailing_stop)
                        exit_reason = "均值回归防守止损"
                    elif holding_bars >= 5:
                        exit_hit = True
                        exit_p = curr_open
                        exit_reason = "均值回归 5 Bar 超时平仓"
                    # 动态保本
                    elif curr_high >= entry_p + 0.4 * curr_atr:
                        trailing_stop = max(trailing_stop, entry_p + 0.05 * curr_atr)

                elif pos == -1:
                    if curr_low <= target_sma5:
                        exit_hit = True
                        exit_p = target_sma5
                        exit_reason = "均值回归 SMA(5) 极速止盈"
                    elif curr_high >= trailing_stop:
                        exit_hit = True
                        exit_p = max(curr_open, trailing_stop)
                        exit_reason = "均值回归防守止损"
                    elif holding_bars >= 5:
                        exit_hit = True
                        exit_p = curr_open
                        exit_reason = "均值回归 5 Bar 超时平仓"
                    # 动态保本
                    elif curr_low <= entry_p - 0.4 * curr_atr:
                        trailing_stop = min(trailing_stop, entry_p - 0.05 * curr_atr)

            if exit_hit:
                pnl = (exit_p - entry_p) * multiplier * lots if pos == 1 else (entry_p - exit_p) * multiplier * lots
                pnl -= (commission * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                    "source": "TREND" if current_source == 1 else "REVERT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": exit_reason
                })
                pos = 0
                lots = 0
                current_source = 0

        # 2. 开仓与信号翻转逻辑
        if curr_sig != 0 and ((curr_sig == 1 and pos != 1) or (curr_sig == -1 and pos != -1)):
            # ML Meta-Router 过滤拦截
            if use_ml_meta and (np.isnan(curr_prob) or curr_prob < meta_thresh):
                filtered_by_ml += 1
            else:
                # 平掉旧仓位 (如果有)
                if pos != 0:
                    exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                    pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * lots
                    pnl -= (commission * lots + tick_size * multiplier * lots)
                    current_equity += pnl
                    trades.append({
                        "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                        "source": "TREND" if current_source == 1 else "REVERT",
                        "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": "信号翻转平仓"
                    })

                # 计算开仓头寸与置信度缩放
                entry_p = curr_open + (tick_size if curr_sig == 1 else -tick_size)
                stop_dist = (3.0 * curr_atr) if curr_src == 1 else (1.2 * curr_atr)
                base_lots = max(1, min(max_lots, int((initial_balance * 0.01) / (stop_dist * multiplier + 1e-6))))

                if use_ml_meta and not np.isnan(curr_prob):
                    bet_scale = max(1.0, min(1.8, 1.0 + (curr_prob - 0.5) * 3.0))
                    calc_lots = max(1, int(base_lots * bet_scale))
                else:
                    calc_lots = base_lots

                pos = curr_sig
                lots = calc_lots
                current_source = curr_src
                entry_dt = dts[i]
                holding_bars = 0
                highest_p = curr_high if curr_sig == 1 else 0.0
                lowest_p = curr_low if curr_sig == -1 else float("inf")
                trailing_stop = entry_p - stop_dist if curr_sig == 1 else entry_p + stop_dist

        # 记录资金曲线
        unrealized = 0.0
        if pos == 1:
            unrealized = (closes[i] - entry_p) * multiplier * lots
        elif pos == -1:
            unrealized = (entry_p - closes[i]) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    # 统计核心指标
    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": [], "regime_dist": {}, "filtered_by_ml": filtered_by_ml}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100.0
    net_profit = sum(t["pnl"] for t in trades)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 99.0

    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks * 100.0
    max_dd = np.max(dds) if len(dds) > 0 else 0.0

    returns = np.diff(eq_arr) / eq_arr[:-1]
    sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * np.sqrt(252 * 16) if len(returns) > 10 else 0.0

    # 统计机制分布
    r_counts = pd.Series(regime_vals).value_counts(normalize=True).to_dict()
    regime_dist = {
        "Dormant (休眠)": f"{r_counts.get(0, 0)*100:.1f}%",
        "Trend (趋势)": f"{r_counts.get(1, 0)*100:.1f}%",
        "Reversion (震荡)": f"{r_counts.get(2, 0)*100:.1f}%"
    }

    return {
        "net_profit": round(net_profit, 2),
        "trades_count": total_trades,
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl_ratio, 2),
        "max_dd": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "filtered_by_ml": filtered_by_ml,
        "regime_dist": regime_dist,
        "trades": trades
    }


def run_regime_shift_benchmark(timeframe: str):
    macro_freq = "120min" if timeframe == "30m" else "60min"
    print("\n" + "=" * 145)
    print(f"🌌 【市场机制识别与离散状态自适应】全量实证对照大盘 —— 周期: {timeframe} | 宏观对齐: {macro_freq}")
    print("=" * 145)
    print(f"{'品种':<10} | {'-- 纯趋势 (ST V2) --':<24} | {'- 纯均值回归 (Z V2) -':<24} | {'- 物理状态机 (V1) -':<24} | {'- ML自适应状态机 (V2) -':<26}")
    print(f"{'':10} | {'净利':>10} {'胜率':>6} {'笔数':>5} | {'净利':>10} {'胜率':>6} {'笔数':>5} | {'净利':>10} {'胜率':>6} {'笔数':>5} | {'净利':>10} {'胜率':>6} {'笔数':>5} {'过滤':>4}")
    print("-" * 145)

    totals = {"st": 0.0, "zr": 0.0, "sm_v1": 0.0, "sm_v2": 0.0}
    trade_counts = {"st": 0, "zr": 0, "sm_v1": 0, "sm_v2": 0}
    ml_filtered_total = 0

    feature_cols = [
        "er", "hurst", "squeeze", "adx", "vol_ratio", "oi_flow", "zscore", "rsi_2", "pin_long", "pin_short", "macro_trend"
    ]

    for sym in COMMODITY_UNIVERSE:
        df_raw = load_symbol_data(sym, timeframe)
        if len(df_raw) < 100:
            continue

        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        # 1. 计算多维机制与特征
        df_feat = compute_market_regimes_and_features(df_raw, macro_freq)
        df_feat = generate_adaptive_signals(df_feat)

        # 2. 训练 ML Meta-Router
        prob_meta = train_walk_forward_meta_router(df_feat, feature_cols, train_window=2500, step_size=500)
        df_feat["meta_prob"] = prob_meta

        # 3. 运行 4 大模式回测
        # 模式 A: 纯趋势 (SuperTrend V2)
        from run_alphatrend_supertrend_backtest import simulate_trend_strategy_v2, compute_macro_trend, compute_filters
        macro_t = compute_macro_trend(df_raw, macro_freq)
        sq, adx_val = compute_filters(df_raw)
        st_sig = calc_supertrend_sig(df_raw, period=10, multiplier=3.0)
        res_st = simulate_trend_strategy_v2(df_raw, st_sig, cfg, macro_t, sq, adx_val)

        # 模式 B: 纯均值回归 (Z-Score V2)
        from run_zscore_meta_backtest import compute_zscore_features_and_meta_labels, run_walk_forward_meta_classifier, simulate_mean_reversion_execution
        df_z = compute_zscore_features_and_meta_labels(df_raw, multiplier=cfg["multiplier"], macro_freq=macro_freq)
        prob_z = run_walk_forward_meta_classifier(df_z, ["zscore", "rsi_2", "squeeze", "accel_norm", "vol_ratio", "vol_climax", "rsi_14", "shadow_rejection_long", "shadow_rejection_short", "donchian_dist", "oi_flow", "oi_unwinding", "trend_1h"], train_window=2500, step_size=500)
        df_z["meta_prob"] = prob_z
        res_zr = simulate_mean_reversion_execution(df_z, cfg, sym, use_meta_filter=True, meta_prob_thresh=0.52)

        # 模式 C: 物理状态机自适应 (Regime State Machine V1)
        res_v1 = simulate_adaptive_engine(df_feat, cfg, use_ml_meta=False)

        # 模式 D: ML 增强自适应状态机 (Regime State Machine + ML Meta Router V2)
        res_v2 = simulate_adaptive_engine(df_feat, cfg, use_ml_meta=True, meta_thresh=0.52)

        totals["st"] += res_st["net_profit"]
        totals["zr"] += res_zr["net_profit_rmb"]
        totals["sm_v1"] += res_v1["net_profit"]
        totals["sm_v2"] += res_v2["net_profit"]

        trade_counts["st"] += res_st["trades_count"]
        trade_counts["zr"] += res_zr["total_trades"]
        trade_counts["sm_v1"] += res_v1["trades_count"]
        trade_counts["sm_v2"] += res_v2["trades_count"]
        ml_filtered_total += res_v2.get("filtered_by_ml", 0)

        sym_str = f"{name}({sym[:2]})"
        fmt_st = f"¥{res_st['net_profit']:>+8,.0f} {res_st['win_rate']:>5.1f}% {res_st['trades_count']:>4d}"
        fmt_zr = f"¥{res_zr['net_profit_rmb']:>+8,.0f} {res_zr['win_rate_pct']:>5.1f}% {res_zr['total_trades']:>4d}"
        fmt_v1 = f"¥{res_v1['net_profit']:>+8,.0f} {res_v1['win_rate']:>5.1f}% {res_v1['trades_count']:>4d}"
        fmt_v2 = f"¥{res_v2['net_profit']:>+8,.0f} {res_v2['win_rate']:>5.1f}% {res_v2['trades_count']:>4d} {res_v2['filtered_by_ml']:>4d}"

        print(f"{sym_str:<10} | {fmt_st} | {fmt_zr} | {fmt_v1} | {fmt_v2}")

    print("=" * 145)
    print(f"🏆 【{timeframe} 机制自适应系统大盘汇总】:")
    print(f"  1. 纯趋势基线 (SuperTrend V2)      : 总净利 ¥{totals['st']:>+12,.2f} | 交易 {trade_counts['st']:>4d} 笔")
    print(f"  2. 纯均值回归基线 (Z-Score V2)     : 总净利 ¥{totals['zr']:>+12,.2f} | 交易 {trade_counts['zr']:>4d} 笔")
    print(f"  3. 物理规则状态机 (Regime Switch V1): 总净利 ¥{totals['sm_v1']:>+12,.2f} | 交易 {trade_counts['sm_v1']:>4d} 笔")
    print(f"  4. ML增强自适应状态机 (Regime+ML V2): 总净利 ¥{totals['sm_v2']:>+12,.2f} | 交易 {trade_counts['sm_v2']:>4d} 笔 | ML过滤 {ml_filtered_total} 笔")
    print("=" * 145)

    return {
        "timeframe": timeframe,
        "st_pnl": totals["st"], "zr_pnl": totals["zr"],
        "v1_pnl": totals["sm_v1"], "v2_pnl": totals["sm_v2"]
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="all", choices=["10m", "15m", "30m", "all"])
    args = parser.parse_args()

    if args.timeframe == "all":
        results = {}
        for tf in ["10m", "15m", "30m"]:
            results[tf] = run_regime_shift_benchmark(tf)

        print("\n" + "🔥" * 38)
        print("📊 跨周期全矩阵机制自适应终极对比:")
        for tf, r in results.items():
            print(f"  • {tf:4s}: 纯趋势 ¥{r['st_pnl']:>+11,.0f} | 纯均值 ¥{r['zr_pnl']:>+10,.0f} | 状态机V1 ¥{r['v1_pnl']:>+11,.0f} | ML状态机V2 ¥{r['v2_pnl']:>+11,.0f}")
        print("🔥" * 38)
    else:
        run_regime_shift_benchmark(args.timeframe)
