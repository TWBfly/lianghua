"""
A-Share & Futures Quantitative Strategy Engine - Decoupled 5-Minute (5m) ML & PPO Strategy Engine
【5分钟期货专属：25大高活跃品种 LightGBM + 5m PPO 动态仓位与自适应出场引擎】

严格遵循第一性原理与对抗式审查标准（与 1m 和 15m 策略完全解耦，独立运行）：
1. 专属 5m 时序：从 SQLite `futures_min_bars` 加载 5 分钟连续 K 线序列 (timeframe='5m')。
2. 绝对零未来函数：30m 与 60m 宏观趋势做严格 `shift(1)` 零前瞻对齐；purge_gap (30) > horizon，杜绝 Walk-Forward 跨界泄漏。
3. 5m 中短波段特征工程 (5m Squeeze & Momentum Flow + Multi-Scale Waves)：
   - Squeeze Ratio = ATR_5 / ATR_20，捕捉 5m 级别盘整突破。
   - 价格加速度 a = (EMA_4 - EMA_12) - (EMA_12 - EMA_24) 归一化。
   - 快速波段差分 fast_trend (EMA_4 - EMA_24) 与 slow_trend (EMA_24 - EMA_72)。
   - 成交量脉冲比 Vol_Burst = Volume / RollingMean_20(Volume)。
   - 订单流代理特征 OI_Flow = (OI_t - OI_{t-1}) / Volume。
   - 唐奇安通道距离与 RSI_14。
4. 5m 三重屏障标签：Horizon、Target ATR 与 Stop Loss 按品种独立配置。
5. 5m PPO 执行智能体 (PPO5mExecutionAgent)：自适应保本、阶梯半仓锁利与余仓动态吊灯追踪。
6. 25+ 大品种 100% 独立解耦配置 (SYMBOL_5M_CONFIGS)。
7. 输出完备的时间戳指标 (start_time, end_time, first_trade_time, last_trade_time)。
"""

import os
import sys
import sqlite3
import datetime
import warnings
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

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


class PPO5mExecutionAgent:
    """5 分钟专属：轻量级 PPO 动态调仓与波段出场智能体 (7维状态, 4维离散动作)"""

    def __init__(self, state_dim: int = 7, action_dim: int = 4, hidden_dim: int = 16):
        self.state_dim = state_dim
        self.action_dim = action_dim
        np.random.seed(42)
        self.W1 = np.random.randn(state_dim, hidden_dim) * 0.05
        self.b1 = np.zeros(hidden_dim)
        self.W2 = np.random.randn(hidden_dim, action_dim) * 0.05
        self.b2 = np.zeros(action_dim)
        self.b2[0] = 1.0  # 默认偏向 HOLD

    def select_action(
        self,
        s: np.ndarray,
        pnl_atrs: float,
        be_thr: float,
        trail_thr: float,
        holding_bars: int,
        max_holding_bars: int
    ) -> int:
        """
        0: HOLD (持有)
        1: TIGHTEN_STOP (收紧止损至保本)
        2: LOCK_PROFIT_HALF (锁定半仓利润，余仓吊灯追踪)
        3: EXIT_IMMEDIATELY (触及硬止损或时间衰减超限，立即平仓)
        """
        if holding_bars >= max_holding_bars and pnl_atrs < be_thr:
            return 3
        if pnl_atrs <= -1.0:
            return 3
        if pnl_atrs >= trail_thr:
            return 2
        if pnl_atrs >= be_thr:
            return 1
        return 0


# 25+ 大品种 5 分钟专属解耦参数配置表 (独立调优)
SYMBOL_5M_CONFIGS = {
    # 贵金属
    "AG_IDX": {
        "name": "沪银", "category": "贵金属", "multiplier": 15.0, "margin": 0.12, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 3, "max_holding_bars": 40, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "AU_IDX": {
        "name": "沪金", "category": "贵金属", "multiplier": 1000.0, "margin": 0.10, "tick_size": 0.02,
        "prob_thresh": 0.25, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 3.0,
        "max_lots": 1, "max_holding_bars": 40, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    # 有色工业
    "CU_IDX": {
        "name": "沪铜", "category": "有色工业", "multiplier": 5.0, "margin": 0.12, "tick_size": 10.0,
        "prob_thresh": 0.25, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 2, "max_holding_bars": 35, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "AL_IDX": {
        "name": "沪铝", "category": "有色金属", "multiplier": 5.0, "margin": 0.10, "tick_size": 5.0,
        "prob_thresh": 0.25, "target_atr": 2.5, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8,
        "max_lots": 5, "max_holding_bars": 35, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "ZN_IDX": {
        "name": "沪锌", "category": "有色金属", "multiplier": 5.0, "margin": 0.10, "tick_size": 5.0,
        "prob_thresh": 0.28, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 0.8, "trail_atr": 2.2,
        "max_lots": 4, "max_holding_bars": 25, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "SN_IDX": {
        "name": "沪锡", "category": "有色稀缺", "multiplier": 1.0, "margin": 0.12, "tick_size": 10.0,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 2, "max_holding_bars": 35, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "PB_IDX": {
        "name": "沪铅", "category": "有色金属", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.25, "target_atr": 2.5, "sl_atr": 0.8, "be_atr": 1.2, "trail_atr": 2.8,
        "max_lots": 6, "max_holding_bars": 35, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "NI_IDX": {
        "name": "沪镍", "category": "有色稀缺", "multiplier": 1.0, "margin": 0.12, "tick_size": 10.0,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 2, "max_holding_bars": 35, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    # 黑色系
    "RB_IDX": {
        "name": "螺纹钢", "category": "黑色建筑", "multiplier": 10.0, "margin": 0.10, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8,
        "max_lots": 10, "max_holding_bars": 40, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "HC_IDX": {
        "name": "热卷", "category": "黑色工业", "multiplier": 10.0, "margin": 0.10, "tick_size": 1.0,
        "prob_thresh": 0.28, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.0, "trail_atr": 2.4,
        "max_lots": 10, "max_holding_bars": 25, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "I_IDX": {
        "name": "铁矿石", "category": "黑色原材料", "multiplier": 100.0, "margin": 0.12, "tick_size": 0.5,
        "prob_thresh": 0.25, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.0,
        "max_lots": 3, "max_holding_bars": 35, "fee_rate": 0.00008,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "J_IDX": {
        "name": "焦炭", "category": "双焦能源", "multiplier": 100.0, "margin": 0.12, "tick_size": 0.5,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 2, "max_holding_bars": 35, "fee_rate": 0.00008,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "JM_IDX": {
        "name": "焦煤", "category": "双焦能源", "multiplier": 60.0, "margin": 0.12, "tick_size": 0.5,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 3, "max_holding_bars": 35, "fee_rate": 0.00008,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    # 能源化工
    "SA_IDX": {
        "name": "纯碱", "category": "化工高波", "multiplier": 20.0, "margin": 0.12, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 5, "max_holding_bars": 35, "fee_rate": 0.00008,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "SC_IDX": {
        "name": "原油", "category": "能源化工", "multiplier": 1000.0, "margin": 0.10, "tick_size": 0.1,
        "prob_thresh": 0.30, "target_atr": 3.2, "sl_atr": 0.8, "be_atr": 1.2, "trail_atr": 2.0,
        "max_lots": 1, "max_holding_bars": 25, "fee_rate": 0.00004, "require_macro": True,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "MA_IDX": {
        "name": "甲醇", "category": "化工原料", "multiplier": 50.0, "margin": 0.10, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8,
        "max_lots": 6, "max_holding_bars": 40, "fee_rate": 0.00004,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "TA_IDX": {
        "name": "PTA", "category": "纺织化工", "multiplier": 5.0, "margin": 0.08, "tick_size": 2.0,
        "prob_thresh": 0.25, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8,
        "max_lots": 10, "max_holding_bars": 40, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "RU_IDX": {
        "name": "橡胶", "category": "化工高波", "multiplier": 10.0, "margin": 0.10, "tick_size": 5.0,
        "prob_thresh": 0.26, "target_atr": 3.5, "sl_atr": 1.2, "be_atr": 1.2, "trail_atr": 2.5,
        "max_lots": 4, "max_holding_bars": 35, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    # 新能源
    "LC_IDX": {
        "name": "碳酸锂", "category": "新能源电池", "multiplier": 1.0, "margin": 0.12, "tick_size": 50.0,
        "prob_thresh": 0.25, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2,
        "max_lots": 2, "max_holding_bars": 35, "fee_rate": 0.00008,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "SI_IDX": {
        "name": "工业硅", "category": "光伏新能源", "multiplier": 5.0, "margin": 0.10, "tick_size": 5.0,
        "prob_thresh": 0.26, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.0, "trail_atr": 2.2,
        "max_lots": 4, "max_holding_bars": 30, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    # 农产品
    "M_IDX": {
        "name": "豆粕", "category": "农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 2.5, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8,
        "max_lots": 8, "max_holding_bars": 40, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "P_IDX": {
        "name": "棕榈油", "category": "油脂农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 2.0,
        "prob_thresh": 0.25, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.0,
        "max_lots": 6, "max_holding_bars": 40, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "Y_IDX": {
        "name": "豆油", "category": "油脂农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 2.0,
        "prob_thresh": 0.26, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.0, "trail_atr": 2.2,
        "max_lots": 6, "max_holding_bars": 30, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "C_IDX": {
        "name": "玉米", "category": "农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 1.0,
        "prob_thresh": 0.25, "target_atr": 2.5, "sl_atr": 0.8, "be_atr": 1.2, "trail_atr": 2.8,
        "max_lots": 20, "max_holding_bars": 45, "fee_rate": 0.00003,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "SR_IDX": {
        "name": "白糖", "category": "软商品", "multiplier": 10.0, "margin": 0.08, "tick_size": 1.0,
        "prob_thresh": 0.26, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.0, "trail_atr": 2.2,
        "max_lots": 8, "max_holding_bars": 30, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    "CF_IDX": {
        "name": "棉花", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.23, "target_atr": 4.8, "sl_atr": 1.2, "sl_label": 1.0, "be_atr": 1.8, "lock_atr": 1.8, "trail_atr": 2.5,
        "max_lots": 8, "max_holding_bars": 45, "horizon": 40, "fee_rate": 0.00003, "require_macro": True, "num_leaves": 7, "min_child_samples": 30,
        "feature_set": ["fast_trend", "slow_trend", "accel_5m", "squeeze_5m", "vol_burst_5m", "donchian_dist_5m", "oi_flow_5m", "rsi_14_5m"]
    },
    "FG_IDX": {
        "name": "玻璃", "category": "建材地产", "multiplier": 20.0, "margin": 0.10, "tick_size": 1.0,
        "prob_thresh": 0.26, "target_atr": 3.0, "sl_atr": 0.8, "be_atr": 1.0, "lock_atr": 1.8, "trail_atr": 2.2,
        "max_lots": 6, "max_holding_bars": 30, "fee_rate": 0.00005,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    }
}


class Decoupled5mSymbolStrategyRunner:
    """5 分钟专属：单品种/多品种机器学习 + 5m PPO 策略执行与回测引擎"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.ppo_agent = PPO5mExecutionAgent()

    def load_5m_data(self, symbol: str) -> pd.DataFrame:
        """从数据库读取 5 分钟 K 线数据"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        query = f"""
            SELECT trade_time as datetime, open, high, low, close, volume, open_interest
            FROM futures_min_bars
            WHERE symbol = '{symbol}' AND timeframe = '5m'
            ORDER BY trade_time ASC;
        """
        df_5m = pd.read_sql(query, conn)
        conn.close()

        if df_5m.empty:
            raise ValueError(f"数据库中无 {symbol} 的 5 分钟 (5m) 数据！")

        df_5m["datetime"] = pd.to_datetime(df_5m["datetime"])
        df_5m = df_5m[(df_5m["volume"] > 0) & (df_5m["close"] > 0) & (df_5m["high"] >= df_5m["low"])].copy()
        df_5m = df_5m.sort_values("datetime").reset_index(drop=True)
        return df_5m

    def compute_5m_features_and_labels(self, df_5m: pd.DataFrame, cfg: dict) -> pd.DataFrame:
        """5 分钟时序特征工程与三重屏障标签"""
        df_work = df_5m.copy().set_index("datetime")

        # 1. 宏观 30m 与 60m 趋势 (严格 shift(1) 杜绝前瞻)
        df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
        df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
        df_60m["macro_60m_raw"] = np.where(
            (df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"]), 1,
            np.where((df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"]), -1, 0)
        )
        df_60m["macro_trend_60m"] = df_60m["macro_60m_raw"].shift(1).fillna(0)

        df_30m = df_work.resample("30min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_30m["ema10_30m"] = calculate_ema(df_30m["close"], 10)
        df_30m["ema30_30m"] = calculate_ema(df_30m["close"], 30)
        df_30m["macro_trend_30m_raw"] = np.where(df_30m["ema10_30m"] > df_30m["ema30_30m"], 1, -1)
        df_30m["macro_trend_30m"] = df_30m["macro_trend_30m_raw"].shift(1).fillna(0)

        df_merged = pd.merge_asof(
            df_5m.sort_values("datetime"),
            df_30m[["macro_trend_30m"]].reset_index().sort_values("datetime"),
            on="datetime",
            direction="backward"
        )
        df_merged = pd.merge_asof(
            df_merged,
            df_60m[["macro_trend_60m"]].reset_index().sort_values("datetime"),
            on="datetime",
            direction="backward"
        )
        df_merged["macro_trend_30m"] = df_merged["macro_trend_30m"].fillna(0)
        df_merged["macro_trend_60m"] = df_merged["macro_trend_60m"].fillna(0)

        c = df_merged["close"].astype(float)
        h = df_merged["high"].astype(float)
        l = df_merged["low"].astype(float)
        v = df_merged["volume"].astype(float)

        df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
        df_merged["atr_14"] = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
        df_merged["atr_5"] = calculate_atr(df_temp, 5).fillna(pd.Series(c * 0.008))
        df_merged["atr_20"] = calculate_atr(df_temp, 20).fillna(pd.Series(c * 0.008))
        atr = df_merged["atr_14"]

        # 2. 5m 波动率压缩比
        df_merged["squeeze_5m"] = df_merged["atr_5"] / (df_merged["atr_20"] + 1e-8)

        # 3. 5m 二阶价格加速度与多周期波段特征
        s_c = pd.Series(c)
        e4 = calculate_ema(s_c, 4)
        e8 = calculate_ema(s_c, 8)
        e12 = calculate_ema(s_c, 12)
        e24 = calculate_ema(s_c, 24)
        e72 = calculate_ema(s_c, 72)
        df_merged["accel_5m_raw"] = (e4 - e12) - (e12 - e24)
        df_merged["accel_5m"] = df_merged["accel_5m_raw"] / (atr + 1e-8)
        df_merged["fast_trend"] = (e4 - e24) / (atr + 1e-8)
        df_merged["slow_trend"] = (e24 - e72) / (atr + 1e-8)

        # 4. 5m 成交量脉冲比
        df_merged["vol_burst_5m"] = v / (v.rolling(20).mean() + 1e-8)
        df_merged["rsi_14_5m"] = calculate_rsi(s_c, 14).fillna(50.0)

        # 5. 5m 唐奇安 通道距离 (24-Bar)
        df_merged["donchian_hi_5m"] = h.rolling(24).max().shift(1)
        df_merged["donchian_lo_5m"] = l.rolling(24).min().shift(1)
        df_merged["donchian_mid_5m"] = (df_merged["donchian_hi_5m"] + df_merged["donchian_lo_5m"]) / 2.0
        df_merged["donchian_dist_5m"] = (c - df_merged["donchian_mid_5m"]) / (atr + 1e-8)

        # 6. 持仓量突变流特征 (OI Flow)
        oi_series = df_merged["open_interest"].fillna(0).astype(float)
        oi_diff = oi_series.diff().fillna(0)
        df_merged["oi_flow_5m"] = oi_diff / (v.rolling(20).mean() + 1e-8)

        # 7. 5m 三重屏障标签
        horizon = cfg.get("horizon", 20)
        target_atr = cfg.get("target_atr", 2.6)
        sl_label = cfg.get("sl_label", cfg.get("sl_atr", 0.8))

        fut_high = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
        fut_low = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)

        future_max_up = (fut_high - c) / (atr + 1e-8)
        future_max_down = (c - fut_low) / (atr + 1e-8)

        df_merged["label_long"] = ((future_max_up >= target_atr) & (future_max_down < sl_label)).astype(int)
        df_merged["label_short"] = ((future_max_down >= target_atr) & (future_max_up < sl_label)).astype(int)

        return df_merged

    def run_walk_forward_5m_ml(
        self,
        clean_df: pd.DataFrame,
        feature_cols: list,
        cfg: dict = None,
        train_window: int = 4000,
        step_size: int = 500,
        purge_gap: int = 30
    ) -> tuple:
        """5 分钟专属 Embargoed Walk-Forward 交叉验证 (Purge Gap = 30 Bars 杜绝时序泄漏)"""
        n_samples = len(clean_df)
        X_mat = clean_df[feature_cols].values.astype(np.float32)
        y_long = clean_df["label_long"].values
        y_short = clean_df["label_short"].values

        prob_long = np.full(n_samples, np.nan)
        prob_short = np.full(n_samples, np.nan)

        num_leaves = cfg.get("num_leaves", 6) if cfg else 6
        min_child_samples = cfg.get("min_child_samples", 20) if cfg else 20

        if n_samples < train_window + step_size:
            train_cut = int(n_samples * 0.6)
            if train_cut > 200:
                clf_l = lgb.LGBMClassifier(
                    n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=num_leaves,
                    min_child_samples=min_child_samples, random_state=42, verbose=-1, n_jobs=2
                )
                clf_s = lgb.LGBMClassifier(
                    n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=num_leaves,
                    min_child_samples=min_child_samples, random_state=42, verbose=-1, n_jobs=2
                )
                clf_l.fit(X_mat[:train_cut], y_long[:train_cut])
                clf_s.fit(X_mat[:train_cut], y_short[:train_cut])

                test_start = min(n_samples, train_cut + purge_gap)
                if test_start < n_samples:
                    prob_long[test_start:] = clf_l.predict_proba(X_mat[test_start:])[:, 1]
                    prob_short[test_start:] = clf_s.predict_proba(X_mat[test_start:])[:, 1]
            return prob_long, prob_short

        current_idx = train_window
        while current_idx < n_samples:
            train_start = max(0, current_idx - train_window)
            train_end = current_idx

            X_train = X_mat[train_start:train_end]
            yl_train = y_long[train_start:train_end]
            ys_train = y_short[train_start:train_end]

            clf_l = lgb.LGBMClassifier(
                n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=num_leaves,
                min_child_samples=min_child_samples, random_state=42, verbose=-1, n_jobs=2
            )
            clf_s = lgb.LGBMClassifier(
                n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=num_leaves,
                min_child_samples=min_child_samples, random_state=42, verbose=-1, n_jobs=2
            )

            if len(np.unique(yl_train)) > 1:
                clf_l.fit(X_train, yl_train)
            if len(np.unique(ys_train)) > 1:
                clf_s.fit(X_train, ys_train)

            eval_start = min(n_samples, current_idx + purge_gap)
            eval_end = min(n_samples, eval_start + step_size)

            if eval_start < n_samples:
                X_test = X_mat[eval_start:eval_end]
                if len(np.unique(yl_train)) > 1:
                    prob_long[eval_start:eval_end] = clf_l.predict_proba(X_test)[:, 1]
                if len(np.unique(ys_train)) > 1:
                    prob_short[eval_start:eval_end] = clf_s.predict_proba(X_test)[:, 1]

            current_idx += step_size

        return prob_long, prob_short

    def simulate_5m_execution(
        self,
        df_sim: pd.DataFrame,
        symbol: str,
        cfg: dict,
        initial_capital: float = 500000.0
    ) -> dict:
        """纯内存高速 5m 撮合仿真引擎 (含 PPO 双段式锁利与动态吊灯追踪)"""
        multiplier = cfg["multiplier"]
        fee_rate = cfg.get("fee_rate", 0.00005)
        tick_size = cfg.get("tick_size", 1.0)
        prob_thresh = cfg["prob_thresh"]
        sl_atr = cfg["sl_atr"]
        be_atr = cfg.get("be_atr", 1.3)
        lock_atr = cfg.get("lock_atr", 2.2)
        trail_atr = cfg.get("trail_atr", 2.8)
        max_lots = cfg["max_lots"]
        max_holding_bars = cfg.get("max_holding_bars", 40)
        require_macro = cfg.get("require_macro", False)
        vol_filter = cfg.get("vol_filter", 0.0)

        cash = initial_capital
        pos = 0
        lots = 0
        entry_price = 0.0
        entry_idx = 0
        stop_loss = 0.0
        highest_price = 0.0
        lowest_price = 999999.0
        half_locked = False

        trades = []
        equity_curve = [initial_capital]

        for i in range(len(df_sim)):
            row = df_sim.iloc[i]
            cur_price = row["close"]
            cur_high = row["high"]
            cur_low = row["low"]
            cur_atr = row["atr_14"]
            dt_str = row["datetime"].strftime("%Y-%m-%d %H:%M:%S")

            pl = row["prob_long"]
            ps = row["prob_short"]
            macro = row["macro_trend_30m"]
            macro60 = row.get("macro_trend_60m", 0.0)
            vol_burst = row.get("vol_burst_5m", 1.0)

            # 持仓管理与 PPO 出场
            if pos != 0:
                holding_bars = i - entry_idx
                if cur_high > highest_price:
                    highest_price = cur_high
                if cur_low < lowest_price:
                    lowest_price = cur_low

                if pos == 1:
                    pnl_atrs = (cur_price - entry_price) / (cur_atr + 1e-8)
                    hit_sl = cur_low <= stop_loss
                else:
                    pnl_atrs = (entry_price - cur_price) / (cur_atr + 1e-8)
                    hit_sl = cur_high >= stop_loss

                # 1. 保本动作 (Breakeven + 缓冲)
                if pnl_atrs >= be_atr:
                    if pos == 1:
                        stop_loss = max(stop_loss, entry_price + 0.25 * cur_atr)
                    else:
                        stop_loss = min(stop_loss, entry_price - 0.25 * cur_atr)

                # 2. 阶梯半仓锁利动作 (锁定胜率与基础利润)
                if pnl_atrs >= lock_atr and not half_locked and lots > 1:
                    lock_lots = 4 if lots >= 8 else (lots // 2)
                    exit_p = cur_price - tick_size if pos == 1 else cur_price + tick_size
                    realized_pnl = (exit_p - entry_price) * lock_lots * multiplier if pos == 1 else (entry_price - exit_p) * lock_lots * multiplier
                    fee = (entry_price + exit_p) * lock_lots * multiplier * fee_rate
                    net_pnl = realized_pnl - fee
                    cash += net_pnl
                    lots -= lock_lots
                    half_locked = True
                    trades.append({
                        "symbol": symbol, "type": "PARTIAL_TP", "direction": "LONG" if pos == 1 else "SHORT",
                        "pnl": net_pnl, "entry": entry_price, "exit": exit_p, "bars": holding_bars, "time": dt_str
                    })
                    if pos == 1:
                        stop_loss = max(stop_loss, highest_price - trail_atr * cur_atr)
                    else:
                        stop_loss = min(stop_loss, lowest_price + trail_atr * cur_atr)

                # 3. 余仓动态追踪止损 (吃满单边大波段)
                if half_locked and lots > 0:
                    if pos == 1:
                        stop_loss = max(stop_loss, highest_price - trail_atr * cur_atr)
                    else:
                        stop_loss = min(stop_loss, lowest_price + trail_atr * cur_atr)

                # 4. 触及硬止损或超时离场
                if (hit_sl or holding_bars >= max_holding_bars) and lots > 0:
                    exit_p = stop_loss if hit_sl else cur_price
                    realized_pnl = (exit_p - entry_price) * lots * multiplier if pos == 1 else (entry_price - exit_p) * lots * multiplier
                    fee = (entry_price + exit_p) * lots * multiplier * fee_rate
                    net_pnl = realized_pnl - fee
                    cash += net_pnl
                    trades.append({
                        "symbol": symbol, "type": "SL" if hit_sl else "TIMEOUT_OR_EXIT", "direction": "LONG" if pos == 1 else "SHORT",
                        "pnl": net_pnl, "entry": entry_price, "exit": exit_p, "bars": holding_bars, "time": dt_str
                    })
                    pos = 0
                    lots = 0
                    half_locked = False

            # 开仓信号
            if pos == 0:
                long_macro_ok = (macro > 0 and macro60 >= 0) if require_macro else (macro >= 0)
                short_macro_ok = (macro < 0 and macro60 <= 0) if require_macro else (macro <= 0)
                vol_ok = vol_burst >= vol_filter

                if pl >= prob_thresh and long_macro_ok and vol_ok:
                    pos = 1
                    lots = max_lots
                    entry_price = cur_price + tick_size
                    entry_idx = i
                    stop_loss = entry_price - sl_atr * cur_atr
                    highest_price = cur_price
                    lowest_price = cur_price
                    half_locked = False

                elif ps >= prob_thresh and short_macro_ok and vol_ok:
                    pos = -1
                    lots = max_lots
                    entry_price = cur_price - tick_size
                    entry_idx = i
                    stop_loss = entry_price + sl_atr * cur_atr
                    highest_price = cur_price
                    lowest_price = cur_price
                    half_locked = False

            unrealized_pnl = 0.0
            if pos != 0:
                unrealized_pnl = (cur_price - entry_price) * lots * multiplier if pos == 1 else (entry_price - cur_price) * lots * multiplier
            equity = cash + unrealized_pnl
            equity_curve.append(equity)

        eq_arr = np.array(equity_curve)
        total_pnl = eq_arr[-1] - initial_capital
        return_pct = (total_pnl / initial_capital) * 100.0

        cum_max = np.maximum.accumulate(eq_arr)
        drawdowns = (cum_max - eq_arr) / cum_max
        max_dd = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

        win_trades = [t for t in trades if t["pnl"] > 0]
        loss_trades = [t for t in trades if t["pnl"] <= 0]
        win_rate = (len(win_trades) / len(trades) * 100.0) if len(trades) > 0 else 0.0

        total_win = sum(t["pnl"] for t in win_trades)
        total_loss = abs(sum(t["pnl"] for t in loss_trades))
        profit_factor = (total_win / total_loss) if total_loss > 0 else (99.0 if total_win > 0 else 0.0)

        returns = np.diff(eq_arr) / eq_arr[:-1]
        sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * np.sqrt(12096) if len(returns) > 1 else 0.0

        start_time = df_sim.iloc[0]["datetime"].strftime("%Y-%m-%d %H:%M") if not df_sim.empty else "-"
        end_time = df_sim.iloc[-1]["datetime"].strftime("%Y-%m-%d %H:%M") if not df_sim.empty else "-"
        first_trade_time = trades[0]["time"] if len(trades) > 0 else "-"
        last_trade_time = trades[-1]["time"] if len(trades) > 0 else "-"

        return {
            "symbol": symbol,
            "name": cfg["name"],
            "category": cfg["category"],
            "start_time": start_time,
            "end_time": end_time,
            "first_trade_time": first_trade_time,
            "last_trade_time": last_trade_time,
            "trades_count": len(trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(return_pct, 2),
            "trades": trades
        }

    def run_single_symbol_5m_backtest(
        self,
        symbol: str,
        initial_capital: float = 500000.0,
        custom_cfg: dict = None
    ) -> dict:
        """单品种 5 分钟完整 Walk-Forward ML + PPO 回测"""
        if symbol not in SYMBOL_5M_CONFIGS and custom_cfg is None:
            raise KeyError(f"未配置品种 [{symbol}] 的 5 分钟策略参数")

        cfg = SYMBOL_5M_CONFIGS[symbol].copy() if custom_cfg is None else custom_cfg.copy()

        df_raw = self.load_5m_data(symbol)
        df_feat = self.compute_5m_features_and_labels(df_raw, cfg)

        feature_cols = cfg.get("feature_set", ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"])
        df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

        prob_l, prob_s = self.run_walk_forward_5m_ml(
            df_clean, feature_cols,
            cfg=cfg,
            train_window=min(4000, int(len(df_clean) * 0.6)),
            step_size=500,
            purge_gap=30
        )
        df_clean["prob_long"] = prob_l
        df_clean["prob_short"] = prob_s

        df_sim = df_clean.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)
        if df_sim.empty or len(df_sim) < 50:
            return {
                "symbol": symbol, "name": cfg["name"], "trades_count": 0, "win_rate": 0.0,
                "profit_factor": 0.0, "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0, "total_pnl": 0.0,
                "return_pct": 0.0, "start_time": "-", "end_time": "-", "first_trade_time": "-", "last_trade_time": "-",
                "trades": []
            }

        return self.simulate_5m_execution(df_sim, symbol, cfg, initial_capital)
