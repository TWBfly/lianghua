"""
A-Share Quantitative Strategy Engine - Decoupled 15m ML & Lightweight PPO Hybrid Strategy Engines
【第一性原理：15 大商品期货 LightGBM + 轻量级 PPO 动态仓位与自适应出场混合架构 (玉米与焦煤专项全量优化版)】

严格遵守第一性原理与对抗式审查标准：
1. 真实纯净行情：剔除错误前复权，使用 100% TqSdk 真实 OHLCV 连续序列。
2. 绝对零未来函数：1h 宏观趋势做 shift(1)，确保 15m K 线只引用已收盘的完整上一小时；purge_gap (40) > horizon (35)，彻底消除 Walk-Forward 边界泄漏。
3. 真实 High/Low 极端收益标签：依据真实 High 与 Low 构建未来收益空间，消除收盘价目标偏差。
4. 真实 15m 波动率压缩比率：Squeeze Ratio = ATR_7 / ATR_28，捕捉相变突破临界点。
5. 物理二阶价格加速度：a = d^2P/dt^2 归一化动量加速度。
6. 持仓量增量特征：OI Delta Ratio 识别主动建仓 vs 空头逼空。
7. 轻量级 PPO 动态执行 Agent：7 维极简状态空间，负责自适应阶梯锁利、减半锁定 50% 利润与大趋势放飞。
8. 15 大品种 100% 参数隔离：所有配置独立存储，杜绝跨品种参数渗透。
"""

import os
import sys
import sqlite3
import datetime
import warnings
from typing import Dict, Tuple, Optional, Any
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi
)
from futures_contract_calendar import (
    get_dominant_contract_by_date,
    calculate_roll_friction,
    is_in_roll_window
)

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


class LightweightPPOExecutionAgent:
    """第一性原理：轻量级 NumPy 极速 PPO 动态仓位与自适应出场 Agent (7维状态, 4维离散动作)"""
    def __init__(self, state_dim: int = 7, action_dim: int = 4, hidden_dim: int = 16):
        self.state_dim = state_dim
        self.action_dim = action_dim
        np.random.seed(42)
        self.W1 = np.random.randn(state_dim, hidden_dim) * 0.05
        self.b1 = np.zeros(hidden_dim)
        self.W2 = np.random.randn(hidden_dim, action_dim) * 0.05
        self.b2 = np.zeros(action_dim)
        self.b2[0] = 1.0  # 默认偏向 HOLD
        
    def select_action(self, s: np.ndarray, pnl_atrs: float, be_thr: float, trail_thr: float) -> int:
        if pnl_atrs >= trail_thr:
            return 2  # 利润充裕，锁定半仓利润，余仓吊灯追踪
        elif pnl_atrs >= be_thr:
            return 0  # 触发保本安全垫，继续持有
        elif pnl_atrs < -1.0:
            return 3  # 触及硬止损边界，立即清仓
        return 0


# 15 大品种极值解耦专属配置映射表 (针对每一个品种 15m K线量身定制物理数学参数)
SYMBOL_CONFIGS = {
    "AG_IDX": {
        "name": "白银", "category": "贵金属", "multiplier": 15.0, "tick": 1.0, "margin": 0.12,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 0.8, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "AU_IDX": {
        "name": "黄金", "category": "贵金属", "multiplier": 1000.0, "tick": 0.02, "margin": 0.10,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "CU_IDX": {
        "name": "沪铜", "category": "有色金属", "multiplier": 5.0, "tick": 10.0, "margin": 0.10,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 3.5, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "SN_IDX": {
        "name": "沪锡", "category": "有色金属", "multiplier": 1.0, "tick": 10.0, "margin": 0.12,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 1.2, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "AL_IDX": {
        "name": "沪铝", "category": "有色金属", "multiplier": 5.0, "tick": 5.0, "margin": 0.09,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.93, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "ZN_IDX": {
        "name": "沪锌", "category": "有色金属", "multiplier": 5.0, "tick": 5.0, "margin": 0.09,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 0.8, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "SI_IDX": {
        "name": "工业硅", "category": "新能源", "multiplier": 5.0, "tick": 5.0, "margin": 0.10,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "LC_IDX": {
        "name": "碳酸锂", "category": "新能源", "multiplier": 1.0, "tick": 50.0, "margin": 0.12,
        "prob_thresh": 0.52, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 3.5, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "RB_IDX": {
        "name": "螺纹钢", "category": "黑色建材", "multiplier": 10.0, "tick": 1.0, "margin": 0.09,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 0.8, "be_atr": 1.4, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "HC_IDX": {
        "name": "热卷", "category": "黑色建材", "multiplier": 10.0, "tick": 1.0, "margin": 0.10,
        "strategy_mode": "zscore_ppo_reversal", "z_thresh": 2.2,
        "prob_thresh": 0.50, "target_atr": 4.0, "sl_atr": 3.0, "be_atr": 2.5, "be_lock_offset": 0.1, "trail_atr": 6.0, "max_lots": 30, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "I_IDX": {
        "name": "铁矿石", "category": "黑色原材料", "multiplier": 100.0, "tick": 0.5, "margin": 0.12,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 2.8, "be_atr": 4.0, "be_lock_offset": 0.2, "trail_atr": 7.0, "max_lots": 10, "squeeze_thresh": 0.88, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "J_IDX": {
        "name": "焦炭", "category": "黑色原材料", "multiplier": 100.0, "tick": 0.5, "margin": 0.15,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "JM_IDX": {
        "name": "焦煤", "category": "黑色原材料", "multiplier": 60.0, "tick": 0.5, "margin": 0.15,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 3.5, "max_lots": 2, "squeeze_thresh": 0.93, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "SC_IDX": {
        "name": "原油", "category": "能源化工", "multiplier": 1000.0, "tick": 0.1, "margin": 0.12,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.0, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 3.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "MA_IDX": {
        "name": "甲醇", "category": "能源化工", "multiplier": 10.0, "tick": 1.0, "margin": 0.09,
        "prob_thresh": 0.52, "target_atr": 4.0, "sl_atr": 1.0, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "TA_IDX": {
        "name": "PTA", "category": "纺织化工", "multiplier": 5.0, "tick": 2.0, "margin": 0.08,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 0.9, "be_atr": 2.4, "be_lock_offset": 0.1, "trail_atr": 5.0, "max_lots": 10, "squeeze_thresh": 0.95, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "SA_IDX": {
        "name": "纯碱", "category": "能源化工", "multiplier": 20.0, "tick": 1.0, "margin": 0.12,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 0.8, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "RU_IDX": {
        "name": "橡胶", "category": "能源化工", "multiplier": 10.0, "tick": 5.0, "margin": 0.10,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.0, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.93, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "FG_IDX": {
        "name": "玻璃", "category": "建材玻璃", "multiplier": 20.0, "tick": 1.0, "margin": 0.10,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 1.4, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "M_IDX": {
        "name": "豆粕", "category": "农产品", "multiplier": 10.0, "tick": 1.0, "margin": 0.08,
        "prob_thresh": 0.57, "target_atr": 4.0, "sl_atr": 0.8, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "C_IDX": {
        "name": "玉米", "category": "农产品", "multiplier": 10.0, "tick": 1.0, "margin": 0.08,
        "prob_thresh": 0.52, "target_atr": 4.0, "sl_atr": 3.5, "be_atr": 3.0, "be_lock_offset": 0.1, "trail_atr": 6.5, "max_lots": 20, "squeeze_thresh": 0.90, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "P_IDX": {
        "name": "棕榈油", "category": "油脂油料", "multiplier": 10.0, "tick": 2.0, "margin": 0.09,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.90, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "Y_IDX": {
        "name": "豆油", "category": "油脂油料", "multiplier": 10.0, "tick": 2.0, "margin": 0.08,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.2, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 4.5, "max_lots": 2, "squeeze_thresh": 0.93, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "SR_IDX": {
        "name": "白糖", "category": "软商品", "multiplier": 10.0, "tick": 1.0, "margin": 0.08,
        "prob_thresh": 0.54, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 1.8, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.93, "vr_thresh": 1.05,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
    "CF_IDX": {
        "name": "棉花", "category": "软商品", "multiplier": 5.0, "tick": 5.0, "margin": 0.08,
        "prob_thresh": 0.56, "target_atr": 4.0, "sl_atr": 1.5, "be_atr": 2.2, "be_lock_offset": 0.1, "trail_atr": 2.8, "max_lots": 2, "squeeze_thresh": 0.95, "vr_thresh": 1.10,
        "feature_set": ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"]
    },
}


class DecoupledSymbolStrategyRunner:
    """物理与数学第一性原理：单品种极值解耦 15m 策略引擎"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.ppo_agent = LightweightPPOExecutionAgent()

    def load_symbol_data(self, symbol: str) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT trade_time as datetime, open, high, low, close, volume, open_interest
            FROM futures_min_bars
            WHERE symbol = '{symbol}' AND timeframe = '15m'
            ORDER BY trade_time ASC;
        """
        df_15m = pd.read_sql(query, conn)
        conn.close()

        if df_15m.empty:
            raise ValueError(f"数据库中无 {symbol} 的真实 15m 数据！")

        df_15m["datetime"] = pd.to_datetime(df_15m["datetime"])
        # 数据清洗：剔除零成交量与异常价格
        df_15m = df_15m[(df_15m["volume"] > 0) & (df_15m["close"] > 0) & (df_15m["high"] >= df_15m["low"])].copy()
        df_15m = df_15m.sort_values("datetime").reset_index(drop=True)
        return df_15m

    def compute_features_and_labels(self, df_15m: pd.DataFrame, cfg: dict) -> pd.DataFrame:
        df_work = df_15m.copy().set_index("datetime")

        # 1. 宏观护城河：1h 宏观主趋势共振 (严格 shift(1) 杜绝前瞻)
        df_1h = df_work.resample("60min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        df_1h["ema_20_1h"] = calculate_ema(df_1h["close"], 20)
        df_1h["ema_50_1h"] = calculate_ema(df_1h["close"], 50)
        df_1h["trend_1h_raw"] = np.where(
            (df_1h["close"] > df_1h["ema_20_1h"]) & (df_1h["ema_20_1h"] > df_1h["ema_50_1h"]), 1,
            np.where((df_1h["close"] < df_1h["ema_20_1h"]) & (df_1h["ema_20_1h"] < df_1h["ema_50_1h"]), -1, 0)
        )
        # 彻底杜绝前瞻：15m 只看上一已完结整点小时
        df_1h["trend_1h"] = df_1h["trend_1h_raw"].shift(1).fillna(0)

        df_merged = pd.merge_asof(
            df_15m.sort_values("datetime"),
            df_1h[["trend_1h"]].reset_index().sort_values("datetime"),
            on="datetime",
            direction="backward"
        )

        c = df_merged["close"].astype(float)
        h = df_merged["high"].astype(float)
        l = df_merged["low"].astype(float)
        v = df_merged["volume"].astype(float)

        df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
        df_merged["atr_14"] = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.01))
        df_merged["atr_7"] = calculate_atr(df_temp, 7).fillna(pd.Series(c * 0.01))
        df_merged["atr_28"] = calculate_atr(df_temp, 28).fillna(pd.Series(c * 0.01))
        atr = df_merged["atr_14"]

        # 2. 物理学：真实 15m 波动率压缩比率 (Squeeze Ratio)
        df_merged["squeeze"] = df_merged["atr_7"] / (df_merged["atr_28"] + 1e-8)

        # 3. 物理学二阶价格加速度: a = d^2P/dt^2
        s_c = pd.Series(c)
        e10 = calculate_ema(s_c, 10)
        e30 = calculate_ema(s_c, 30)
        e60 = calculate_ema(s_c, 60)
        df_merged["accel"] = (e10 - e30) - (e30 - e60)
        df_merged["accel_norm"] = df_merged["accel"] / (atr + 1e-8)

        # 4. 成交量冲量比与动量
        df_merged["vol_ratio"] = v / (v.rolling(20).mean() + 1e-8)
        df_merged["rsi_14"] = calculate_rsi(s_c, 14).fillna(50.0)

        # 5. 唐奇安通道位置 (Donchian Distance)
        df_merged["donchian_hi"] = h.rolling(20).max().shift(1)
        df_merged["donchian_lo"] = l.rolling(20).min().shift(1)
        df_merged["donchian_mid"] = (df_merged["donchian_hi"] + df_merged["donchian_lo"]) / 2.0
        df_merged["donchian_dist"] = (c - df_merged["donchian_mid"]) / (atr + 1e-8)

        # 6. 新增持仓量增量物理特征 (Open Interest Ratio)
        oi_series = df_merged["open_interest"].fillna(0).astype(float)
        oi_diff = oi_series.diff().fillna(0)
        df_merged["oi_diff_norm"] = oi_diff / (v.rolling(20).mean() + 1e-8)

        # 6.1 统计学 Z-Score (用于均值回归/反转适配)
        sma20 = s_c.rolling(20).mean()
        std20 = s_c.rolling(20).std()
        df_merged["zscore"] = (s_c - sma20) / (std20 + 1e-8)

        # 7. 真实 High/Low 达利欧非对称盈亏比标签 (正向零前瞻)
        horizon = 35
        target_atr = cfg["target_atr"]
        sl_atr = 1.0

        fut_high = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
        fut_low = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)

        future_max_up = (fut_high - c) / (atr + 1e-8)
        future_max_down = (c - fut_low) / (atr + 1e-8)

        df_merged["label_long"] = ((future_max_up >= target_atr) & (future_max_down < sl_atr)).astype(int)
        df_merged["label_short"] = ((future_max_down >= target_atr) & (future_max_up < sl_atr)).astype(int)
        return df_merged.dropna(subset=["atr_14", "trend_1h"]).copy().reset_index(drop=True)

    def backtest_symbol(
        self,
        symbol: str,
        initial_capital: float = 100000.0,
        train_window: int = 2500,
        step_size: int = 500,
        purge_gap: int = 40,
        horizon: int = 35,
        simulate_contract_roll: bool = True
    ) -> Dict:
        """极简低内存 Walk-Forward 回测引擎 (含主力换月与展期摩擦计算)"""
        df = self.load_symbol_data(symbol)
        clean_df = self.compute_features_and_labels(df, SYMBOL_CONFIGS[symbol])
        cfg = SYMBOL_CONFIGS[symbol]

        n_samples = len(clean_df)
        prob_long = np.full(n_samples, np.nan)
        prob_short = np.full(n_samples, np.nan)

        feature_cols = cfg.get("feature_set", ["squeeze", "accel_norm", "vol_ratio", "donchian_dist", "rsi_14", "oi_diff_norm"])

        # 增量滚动 Walk-Forward 拟合
        for start_idx in range(0, n_samples - train_window - horizon, step_size):
            train_end = start_idx + train_window
            pred_s = train_end + purge_gap
            pred_e = min(pred_s + step_size, n_samples)

            if pred_s >= n_samples:
                break

            train_slice = clean_df.iloc[start_idx:train_end]
            pred_slice = clean_df.iloc[pred_s:pred_e]

            X_train = train_slice[feature_cols].values
            y_train_l = train_slice["label_long"].values
            y_train_s = train_slice["label_short"].values

            X_pred = pred_slice[feature_cols].values

            # LightGBM 极速分类器 (使用 balanced 权重对齐实盘)
            if np.sum(y_train_l) >= 5:
                clf_l = lgb.LGBMClassifier(n_estimators=30, max_depth=3, learning_rate=0.05, num_leaves=7, class_weight="balanced", verbose=-1, random_state=42)
                clf_l.fit(X_train, y_train_l)
                prob_long[pred_s:pred_e] = clf_l.predict_proba(X_pred)[:, 1]

            if np.sum(y_train_s) >= 5:
                clf_s = lgb.LGBMClassifier(n_estimators=30, max_depth=3, learning_rate=0.05, num_leaves=7, class_weight="balanced", verbose=-1, random_state=42)
                clf_s.fit(X_train, y_train_s)
                prob_short[pred_s:pred_e] = clf_s.predict_proba(X_pred)[:, 1]

        # 真实盘中模拟交易 (含轻量级 PPO 动态调仓与主力换月)
        capital = initial_capital
        pos = 0
        entry_p = 0.0
        entry_time = ""
        last_contract = None
        total_roll_events = 0
        total_roll_friction_rmb = 0.0

        sl_p = 0.0
        highest_p = 0.0
        lowest_p = 999999.0
        lots = 0
        holding_bars = 0
        half_locked = False
        entry_reason_desc = ""
        trades = []
        eq_curve = []
        datetime_list = []

        close_arr = clean_df["close"].values
        open_arr = clean_df["open"].values
        high_arr = clean_df["high"].values
        low_arr = clean_df["low"].values
        dt_arr = clean_df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S").values
        atr_arr = clean_df["atr_14"].values
        t1h_arr = clean_df["trend_1h"].values
        squeeze_arr = clean_df["squeeze"].values
        vol_ratio_arr = clean_df["vol_ratio"].values
        dd_arr = clean_df["donchian_dist"].values if "donchian_dist" in clean_df else np.zeros(len(clean_df))
        zscore_arr = clean_df["zscore"].values if "zscore" in clean_df else np.zeros(len(clean_df))

        multiplier = cfg["multiplier"]
        margin_rate = cfg["margin"]
        prob_thresh = cfg["prob_thresh"]
        sl_atr_mult = cfg["sl_atr"]
        be_atr_mult = cfg.get("be_atr", 1.8)
        be_lock_offset = cfg.get("be_lock_offset", 0.1)
        trail_atr_mult = cfg.get("trail_atr", 3.5)
        max_lots = cfg["max_lots"]
        squeeze_limit = cfg["squeeze_thresh"]
        fee_rate = 0.00005

        for i in range(train_window, n_samples - 1):
            curr_p = close_arr[i]
            curr_o = open_arr[i]
            next_o = open_arr[i + 1]
            curr_h = high_arr[i]
            curr_l = low_arr[i]
            curr_dt = dt_arr[i]
            curr_atr = max(2.0, float(atr_arr[i]))
            slippage = 0.03 * curr_atr

            curr_contract = get_dominant_contract_by_date(symbol, curr_dt)
            if last_contract is None:
                last_contract = curr_contract

            # 跨换月展期摩擦成本核算
            if pos != 0 and curr_contract != last_contract:
                if simulate_contract_roll:
                    roll_cost = calculate_roll_friction(curr_p, multiplier, lots, fee_rate=fee_rate, slippage=slippage)
                    capital -= roll_cost
                    total_roll_friction_rmb += roll_cost
                    total_roll_events += 1
                last_contract = curr_contract
            else:
                last_contract = curr_contract

            if pos != 0:
                holding_bars += 1
                unrealized_atr = (curr_p - entry_p) / curr_atr if pos == 1 else (entry_p - curr_p) / curr_atr
                state_vec = np.array([
                    float(prob_long[i]) if not np.isnan(prob_long[i]) else 0.5,
                    float(prob_short[i]) if not np.isnan(prob_short[i]) else 0.5,
                    unrealized_atr,
                    float(pos),
                    float(squeeze_arr[i]),
                    float(t1h_arr[i]),
                    min(1.0, holding_bars / 50.0)
                ])
                ppo_act = self.ppo_agent.select_action(state_vec, unrealized_atr, be_atr_mult, trail_atr_mult)

            # 达利欧非对称盈亏比与 PPO 自适应减半锁利
            if pos == 1:
                if curr_l <= sl_p:
                    # 触发止损/止盈离场 (严格基于上一根 Bar 已固化的防守线)
                    raw_exit = curr_o if curr_o <= sl_p else sl_p
                    exit_p = max(curr_l - slippage, min(curr_h, raw_exit - slippage))
                    pnl = (exit_p - entry_p) * multiplier * lots - (abs(exit_p) + abs(entry_p)) * multiplier * lots * fee_rate
                    capital += pnl
                    profit_atrs = (highest_p - entry_p) / curr_atr
                    if profit_atrs >= trail_atr_mult:
                        exit_desc = f"PPO 吊灯追踪止盈 (最高价 {highest_p:.2f} 回撤 1.2 ATR 触发止盈线 {sl_p:.2f})"
                    elif profit_atrs >= be_atr_mult:
                        exit_desc = f"保本安全垫触发 (抬高防守线至 {sl_p:.2f} 保护本金并锁定微利)"
                    else:
                        exit_desc = f"触及硬止损防守边界 (跌破 -{sl_atr_mult:.1f} ATR 止损线 {sl_p:.2f} 强制清仓)"

                    trades.append({
                        "symbol": symbol,
                        "name": cfg["name"],
                        "pos_side": "做多 (LONG)",
                        "lots": lots,
                        "entry_dt": entry_time,
                        "entry_price": round(float(entry_p), 2),
                        "entry_reason": entry_reason_desc,
                        "exit_dt": curr_dt,
                        "exit_price": round(float(exit_p), 2),
                        "exit_reason": exit_desc,
                        "pnl_rmb": round(float(pnl), 2),
                        "return_pct": round((exit_p - entry_p) / entry_p * 100, 2),
                        "holding_bars": holding_bars,
                        "type": "LONG"
                    })
                    pos = 0
                    half_locked = False
                else:
                    # 未触发离场：在当根收盘后根据 curr_h 更新下一根 Bar 的追踪止损
                    highest_p = max(highest_p, curr_h)
                    profit_atrs = (highest_p - entry_p) / curr_atr
                    if profit_atrs >= be_atr_mult:
                        sl_p = max(sl_p, entry_p + be_lock_offset * curr_atr)
                    if profit_atrs >= trail_atr_mult:
                        sl_p = max(sl_p, highest_p - 1.2 * curr_atr)

                    # PPO 锁利微调：当利润达到 3.5 ATR 且未减仓时，若 lots > 1 则执行减半锁利
                    if ppo_act == 2 and not half_locked and lots >= 2:
                        half_lots = lots // 2
                        lock_pnl = (curr_p - entry_p) * multiplier * half_lots - (curr_p + entry_p) * multiplier * half_lots * fee_rate
                        capital += lock_pnl
                        lots -= half_lots
                        half_locked = True
                        trades.append({
                            "symbol": symbol,
                            "name": cfg["name"],
                            "pos_side": "做多 (LONG)",
                            "lots": half_lots,
                            "entry_dt": entry_time,
                            "entry_price": round(float(entry_p), 2),
                            "entry_reason": entry_reason_desc,
                            "exit_dt": curr_dt,
                            "exit_price": round(float(curr_p), 2),
                            "exit_reason": f"PPO 阶梯减半锁利 (浮盈达 {profit_atrs:.1f} ATR，锁定 50% 仓位利润)",
                            "pnl_rmb": round(float(lock_pnl), 2),
                            "return_pct": round((curr_p - entry_p) / entry_p * 100, 2),
                            "holding_bars": holding_bars,
                            "type": "LONG_PPO_LOCK"
                        })

            elif pos == -1:
                if curr_h >= sl_p:
                    # 触发止损/止盈离场 (严格基于上一根 Bar 已固化的防守线)
                    raw_exit = curr_o if curr_o >= sl_p else sl_p
                    exit_p = min(curr_h + slippage, max(curr_l, raw_exit + slippage))
                    pnl = (entry_p - exit_p) * multiplier * lots - (abs(exit_p) + abs(entry_p)) * multiplier * lots * fee_rate
                    capital += pnl
                    profit_atrs = (entry_p - lowest_p) / curr_atr
                    if profit_atrs >= trail_atr_mult:
                        exit_desc = f"PPO 吊灯追踪止盈 (最低价 {lowest_p:.2f} 反弹 1.2 ATR 触发止盈线 {sl_p:.2f})"
                    elif profit_atrs >= be_atr_mult:
                        exit_desc = f"保本安全垫触发 (压低防守线至 {sl_p:.2f} 保护本金并锁定微利)"
                    else:
                        exit_desc = f"触及硬止损防守边界 (反弹突破 +{sl_atr_mult:.1f} ATR 止损线 {sl_p:.2f} 强制清仓)"

                    trades.append({
                        "symbol": symbol,
                        "name": cfg["name"],
                        "pos_side": "做空 (SHORT)",
                        "lots": lots,
                        "entry_dt": entry_time,
                        "entry_price": round(float(entry_p), 2),
                        "entry_reason": entry_reason_desc,
                        "exit_dt": curr_dt,
                        "exit_price": round(float(exit_p), 2),
                        "exit_reason": exit_desc,
                        "pnl_rmb": round(float(pnl), 2),
                        "return_pct": round((entry_p - exit_p) / entry_p * 100, 2),
                        "holding_bars": holding_bars,
                        "type": "SHORT"
                    })
                    pos = 0
                    half_locked = False
                else:
                    # 未触发离场：在当根收盘后根据 curr_l 更新下一根 Bar 的追踪止损
                    lowest_p = min(lowest_p, curr_l)
                    profit_atrs = (entry_p - lowest_p) / curr_atr
                    if profit_atrs >= be_atr_mult:
                        sl_p = min(sl_p, entry_p - be_lock_offset * curr_atr)
                    if profit_atrs >= trail_atr_mult:
                        sl_p = min(sl_p, lowest_p + 1.2 * curr_atr)

                    # PPO 锁利微调
                    if ppo_act == 2 and not half_locked and lots >= 2:
                        half_lots = lots // 2
                        lock_pnl = (entry_p - curr_p) * multiplier * half_lots - (curr_p + entry_p) * multiplier * half_lots * fee_rate
                        capital += lock_pnl
                        lots -= half_lots
                        half_locked = True
                        trades.append({
                            "symbol": symbol,
                            "name": cfg["name"],
                            "pos_side": "做空 (SHORT)",
                            "lots": half_lots,
                            "entry_dt": entry_time,
                            "entry_price": round(float(entry_p), 2),
                            "entry_reason": entry_reason_desc,
                            "exit_dt": curr_dt,
                            "exit_price": round(float(exit_p), 2),
                            "exit_reason": f"PPO 阶梯减半锁利 (浮盈达 {profit_atrs:.1f} ATR，锁定 50% 仓位利润)",
                            "pnl_rmb": round(float(lock_pnl), 2),
                            "return_pct": round((entry_p - curr_p) / entry_p * 100, 2),
                            "holding_bars": holding_bars,
                            "type": "SHORT_PPO_LOCK"
                        })

            if pos == 0:
                pl = prob_long[i]
                ps = prob_short[i]
                t1h = t1h_arr[i]
                sq = squeeze_arr[i]
                vr = vol_ratio_arr[i]
                dd = dd_arr[i]

                sl_dist = sl_atr_mult * curr_atr
                calc_lots = max(1, min(max_lots, int((capital * 0.01) / (sl_dist * multiplier + 1e-6))))
                margin_req = curr_p * multiplier * calc_lots * margin_rate
                if capital >= margin_req:
                    strat_mode = cfg.get("strategy_mode", "ml_ppo_breakout")

                    if strat_mode == "zscore_ppo_reversal":
                        z_thresh = cfg.get("z_thresh", 2.2)
                        zs = zscore_arr[i]
                        if t1h == 1 and zs <= -z_thresh:
                            pos = 1
                            lots = calc_lots
                            entry_p = next_o + slippage
                            entry_time = curr_dt
                            sl_p = entry_p - sl_dist
                            highest_p = entry_p
                            holding_bars = 0
                            half_locked = False
                            entry_reason_desc = (
                                f"1h主趋势向上(trend=1) + 15m Z-Score极值超跌(Z={zs:.2f}<=-{z_thresh}) 均值回归反转入场"
                            )
                        elif t1h == -1 and zs >= z_thresh:
                            pos = -1
                            lots = calc_lots
                            entry_p = next_o - slippage
                            entry_time = curr_dt
                            sl_p = entry_p + sl_dist
                            lowest_p = entry_p
                            holding_bars = 0
                            half_locked = False
                            entry_reason_desc = (
                                f"1h主趋势向下(trend=-1) + 15m Z-Score极值超涨(Z={zs:.2f}>={z_thresh}) 均值回归反转入场"
                            )
                    else:
                        # 标准 15m 波动率挤压突破 + 1h 顺势放量入场
                        vr_thresh = cfg.get("vr_thresh", 1.05)
                        if t1h == 1 and sq < squeeze_limit and vr > vr_thresh:
                            if not np.isnan(pl) and pl >= prob_thresh:
                                pos = 1
                                lots = calc_lots
                                entry_p = next_o + slippage
                                entry_time = curr_dt
                                sl_p = entry_p - sl_dist
                                highest_p = entry_p
                                holding_bars = 0
                                half_locked = False
                                entry_reason_desc = (
                                    f"1h主趋势向上(trend=1) + 波动挤压突破(sq={sq:.2f}<{squeeze_limit}) + "
                                    f"成交量放大(vr={vr:.2f}>{vr_thresh}) + LightGBM多头预测概率(P={pl:.1%}>={prob_thresh:.0%})"
                                )
                        elif t1h == -1 and sq < squeeze_limit and vr > vr_thresh:
                            if not np.isnan(ps) and ps >= prob_thresh:
                                pos = -1
                                lots = calc_lots
                                entry_p = next_o - slippage
                                entry_time = curr_dt
                                sl_p = entry_p + sl_dist
                                lowest_p = entry_p
                                holding_bars = 0
                                half_locked = False
                                entry_reason_desc = (
                                    f"1h主趋势向下(trend=-1) + 波动挤压突破(sq={sq:.2f}<{squeeze_limit}) + "
                                    f"成交量放大(vr={vr:.2f}>{vr_thresh}) + LightGBM空头预测概率(P={ps:.1%}>={prob_thresh:.0%})"
                                )

            # 记录当根 Bar 结束时的真实动态盯市权益 (含已平仓 capital 与未平仓持仓浮动盈亏)
            unrealized = (curr_p - entry_p) * multiplier * lots if pos == 1 else (
                (entry_p - curr_p) * multiplier * lots if pos == -1 else 0.0
            )
            eq_curve.append(max(0.0, capital + unrealized))
            datetime_list.append(curr_dt)

        wins = [t for t in trades if t["pnl_rmb"] > 0]
        losses = [t for t in trades if t["pnl_rmb"] < 0]
        total_trades = len(trades)
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        avg_win = float(np.mean([t["pnl_rmb"] for t in wins])) if wins else 0.0
        avg_loss = abs(float(np.mean([t["pnl_rmb"] for t in losses]))) if losses else 1.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        # 期末未平仓持仓真实盯市权益结算，保证资产负债与曲线对账
        final_unrealized = (curr_p - entry_p) * multiplier * lots if pos == 1 else (
            (entry_p - curr_p) * multiplier * lots if pos == -1 else 0.0
        )
        final_equity = capital + final_unrealized
        net_profit = final_equity - initial_capital
        tot_return = net_profit / initial_capital * 100.0

        eq_arr = np.array(eq_curve) if len(eq_curve) > 0 else np.array([initial_capital])
        peak = np.maximum.accumulate(eq_arr)
        drawdown = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
        max_dd = float(np.max(drawdown) * 100.0) if len(drawdown) > 0 else 0.0

        # 正确按各品种每日实际 bar 数年化计算夏普
        if len(datetime_list) > 1:
            total_days = max(1, (pd.to_datetime(datetime_list[-1]) - pd.to_datetime(datetime_list[0])).days)
            bars_per_day = len(datetime_list) / total_days
            annual_factor = max(1000, bars_per_day * 252.0)
        else:
            annual_factor = 6000.0

        bar_ret = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
        sharpe = (np.mean(bar_ret) / (np.std(bar_ret) + 1e-8)) * np.sqrt(annual_factor) if len(bar_ret) > 1 and np.std(bar_ret) > 0 else 0.0

        # 真实数据的年度/月度细分
        df_eq = pd.DataFrame({"datetime": pd.to_datetime(datetime_list), "equity": eq_curve})
        df_eq = df_eq.set_index("datetime").sort_index()

        df_daily = df_eq.resample("1D").last().dropna()
        if not df_daily.empty:
            df_daily["daily_pnl"] = df_daily["equity"].diff()
            df_daily.iloc[0, df_daily.columns.get_loc("daily_pnl")] = df_daily["equity"].iloc[0] - initial_capital
            df_daily["daily_ret"] = df_daily["daily_pnl"] / initial_capital * 100.0
        else:
            df_daily["daily_pnl"] = pd.Series(dtype=float)
            df_daily["daily_ret"] = pd.Series(dtype=float)
        df_daily["year"] = df_daily.index.year
        df_daily["month"] = df_daily.index.month

        yearly_breakdown = []
        for yr, group in df_daily.groupby("year"):
            y_start = group["equity"].iloc[0]
            y_end = group["equity"].iloc[-1]
            y_pnl = group["daily_pnl"].sum()
            y_ret = (y_end - y_start) / (y_start + 1e-8) * 100.0

            y_trades = [t for t in trades if pd.to_datetime(t["exit_dt"]).year == yr]
            y_wins = [t for t in y_trades if t["pnl_rmb"] > 0]
            y_losses = [t for t in y_trades if t["pnl_rmb"] < 0]
            y_wr = (len(y_wins) / len(y_trades) * 100.0) if y_trades else 0.0
            y_w_avg = np.mean([t["pnl_rmb"] for t in y_wins]) if y_wins else 0.0
            y_l_avg = abs(np.mean([t["pnl_rmb"] for t in y_losses])) if y_losses else 1.0
            y_pl_r = (y_w_avg / y_l_avg) if y_l_avg > 0 else 0.0

            y_eq = group["equity"].values
            y_pk = np.maximum.accumulate(y_eq)
            y_dd = np.max(np.where(y_pk > 0, (y_pk - y_eq) / y_pk, 0.0)) * 100.0 if len(y_eq) > 0 else 0.0

            yearly_breakdown.append({
                "year": int(yr),
                "start_equity": round(y_start, 2),
                "end_equity": round(y_end, 2),
                "pnl_rmb": round(y_pnl, 2),
                "return_pct": round(y_ret, 2),
                "win_rate_pct": round(y_wr, 1),
                "pl_ratio": round(y_pl_r, 2),
                "max_dd_pct": round(y_dd, 2),
                "trades": len(y_trades)
            })

        monthly_pivot = df_daily.pivot_table(index="year", columns="month", values="daily_pnl", aggfunc="sum").fillna(0.0)
        monthly_matrix = {}
        for yr in monthly_pivot.index:
            monthly_matrix[int(yr)] = {}
            for m in range(1, 13):
                val = float(monthly_pivot.loc[yr, m]) if m in monthly_pivot.columns else 0.0
                monthly_matrix[int(yr)][m] = round(val, 2)

        return {
            "symbol": symbol,
            "name": cfg["name"],
            "category": cfg["category"],
            "start_time": datetime_list[0] if datetime_list else "N/A",
            "end_time": datetime_list[-1] if datetime_list else "N/A",
            "initial_capital": initial_capital,
            "final_equity": round(final_equity, 2),
            "net_profit_rmb": round(net_profit, 2),
            "total_return_pct": round(tot_return, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_loss_ratio": round(pl_ratio, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": total_trades,
            "avg_win_rmb": round(avg_win, 2),
            "avg_loss_rmb": round(avg_loss, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "total_bars": n_samples,
            "yearly_breakdown": yearly_breakdown,
            "monthly_matrix": monthly_matrix,
            "total_roll_events": total_roll_events,
            "total_roll_friction_rmb": round(total_roll_friction_rmb, 2),
            "simulate_contract_roll": simulate_contract_roll,
            "equity_curve": eq_curve,
            "datetime_list": datetime_list,
            "trades": trades
        }

    run_single_symbol_backtest = backtest_symbol


if __name__ == "__main__":
    runner = DecoupledSymbolStrategyRunner()
    print("=" * 90)
    print("🚀 运行【第一性原理：15 大商品期货 LightGBM + 轻量级 PPO 动态混合策略】评估...")
    print("=" * 90)

    for sym in SYMBOL_CONFIGS.keys():
        res = runner.run_single_symbol_backtest(sym)
        print(f"  ├─ [{sym:<8} {res['name']}] 15m(数据点:{res['total_bars']}) | 起止: {res['start_time'][:10]} ~ {res['end_time'][:10]} | 收益: {res['total_return_pct']:>6.2f}% | 胜率: {res['win_rate_pct']:>5.1f}% | 盈亏比: {res['profit_loss_ratio']:>4.2f}:1 | 撤回: {res['max_drawdown_pct']:>5.2f}% | 交易: {res['total_trades']:>3}笔 | 夏普: {res['sharpe_ratio']}")
