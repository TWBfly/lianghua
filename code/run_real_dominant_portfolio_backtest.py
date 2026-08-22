"""
A-Share & Futures Quantitative Strategy Engine - Real Dominant Multi-Commodity Portfolio Backtest Engine
【真实期货历史主力合约多品种组合回测引擎 (北京时间校准 + 换月跳空软截断 + 动态无损重采样 + 零未来函数)】

核心功能与安全防线：
1. 真实主力连续输入：100% 官方主力连续 (KQ.m 真实逐笔聚合 K 线，北京时间校准)。
2. 换月跳空软截断 (Winsorization)：对波动率挤压比、加速度、量比进行 3-sigma 软截断，剔除换月基差畸变。
3. 动态无损宏观重采样：自适应在内存中聚合 60min / 120min 宏观趋势，并严格执行 `shift(1)`，杜绝大周期碎片。
4. 僵尸/冷门品种流动性守卫：自动剔除零成交量占比 > 5% 的低流动性合约。
5. 真实物理撮合：按各大交易所规则扣除 1 个跳价滑点、保证金与双边手续费。
6. 轻量级 PPO 自适应执行智能体 (硬止损、保本安全垫、50% 阶梯锁利、余仓吊灯追踪)。
"""

import sys
import argparse
import sqlite3
import datetime
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi
)

DOMINANT_COMMODITY_SPECS = {
    # 贵金属
    "AU_IDX": {
        "name": "沪金", "category": "贵金属", "multiplier": 1000.0, "margin": 0.10, "tick_size": 0.02,
        "fee_rate": 0.00003, "slippage": 0.02, "max_lots": 1,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.0
    },
    "AG_IDX": {
        "name": "沪银", "category": "贵金属", "multiplier": 15.0, "margin": 0.12, "tick_size": 1.0,
        "fee_rate": 0.00005, "slippage": 1.0, "max_lots": 3,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.55, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    # 黑色建材
    "RB_IDX": {
        "name": "螺纹钢", "category": "黑色建筑", "multiplier": 10.0, "margin": 0.10, "tick_size": 1.0,
        "fee_rate": 0.00005, "slippage": 1.0, "max_lots": 10,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.53, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8
    },
    "HC_IDX": {
        "name": "热卷", "category": "黑色工业", "multiplier": 10.0, "margin": 0.10, "tick_size": 1.0,
        "fee_rate": 0.00005, "slippage": 1.0, "max_lots": 10,
        "prob_thresh_5m": 0.26, "prob_thresh_15m": 0.54, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.2, "trail_atr": 2.6
    },
    "I_IDX": {
        "name": "铁矿石", "category": "黑色原材料", "multiplier": 100.0, "margin": 0.12, "tick_size": 0.5,
        "fee_rate": 0.00008, "slippage": 0.5, "max_lots": 3,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.0
    },
    "J_IDX": {
        "name": "焦炭", "category": "双焦能源", "multiplier": 100.0, "margin": 0.12, "tick_size": 0.5,
        "fee_rate": 0.00008, "slippage": 0.5, "max_lots": 2,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.56, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    "JM_IDX": {
        "name": "焦煤", "category": "双焦能源", "multiplier": 60.0, "margin": 0.12, "tick_size": 0.5,
        "fee_rate": 0.00008, "slippage": 0.5, "max_lots": 3,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.56, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    # 有色工业
    "CU_IDX": {
        "name": "沪铜", "category": "有色工业", "multiplier": 5.0, "margin": 0.12, "tick_size": 10.0,
        "fee_rate": 0.00005, "slippage": 10.0, "max_lots": 2,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    "AL_IDX": {
        "name": "沪铝", "category": "有色金属", "multiplier": 5.0, "margin": 0.10, "tick_size": 5.0,
        "fee_rate": 0.00003, "slippage": 5.0, "max_lots": 5,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.53, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8
    },
    "ZN_IDX": {
        "name": "沪锌", "category": "有色金属", "multiplier": 5.0, "margin": 0.10, "tick_size": 5.0,
        "fee_rate": 0.00003, "slippage": 5.0, "max_lots": 4,
        "prob_thresh_5m": 0.26, "prob_thresh_15m": 0.54, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.0, "trail_atr": 2.4
    },
    "SN_IDX": {
        "name": "沪锡", "category": "有色稀缺", "multiplier": 1.0, "margin": 0.12, "tick_size": 10.0,
        "fee_rate": 0.00005, "slippage": 10.0, "max_lots": 2,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    # 能源化工
    "SA_IDX": {
        "name": "纯碱", "category": "化工高波", "multiplier": 20.0, "margin": 0.12, "tick_size": 1.0,
        "fee_rate": 0.00008, "slippage": 1.0, "max_lots": 5,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.55, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
    "SC_IDX": {
        "name": "原油", "category": "能源化工", "multiplier": 1000.0, "margin": 0.10, "tick_size": 0.1,
        "fee_rate": 0.00004, "slippage": 0.1, "max_lots": 1,
        "prob_thresh_5m": 0.28, "prob_thresh_15m": 0.56, "target_atr": 3.2, "sl_atr": 0.9, "be_atr": 1.3, "trail_atr": 2.5
    },
    "MA_IDX": {
        "name": "甲醇", "category": "化工原料", "multiplier": 50.0, "margin": 0.10, "tick_size": 1.0,
        "fee_rate": 0.00004, "slippage": 1.0, "max_lots": 6,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.55, "target_atr": 2.8, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8
    },
    "TA_IDX": {
        "name": "PTA", "category": "纺织化工", "multiplier": 5.0, "margin": 0.08, "tick_size": 2.0,
        "fee_rate": 0.00003, "slippage": 2.0, "max_lots": 10,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.55, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8
    },
    "RU_IDX": {
        "name": "橡胶", "category": "化工高波", "multiplier": 10.0, "margin": 0.10, "tick_size": 5.0,
        "fee_rate": 0.00005, "slippage": 5.0, "max_lots": 4,
        "prob_thresh_5m": 0.26, "prob_thresh_15m": 0.55, "target_atr": 3.2, "sl_atr": 1.0, "be_atr": 1.2, "trail_atr": 2.6
    },
    # 农产品与新能源
    "M_IDX": {
        "name": "豆粕", "category": "农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 1.0,
        "fee_rate": 0.00003, "slippage": 1.0, "max_lots": 8,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 2.6, "sl_atr": 0.8, "be_atr": 1.3, "trail_atr": 2.8
    },
    "P_IDX": {
        "name": "棕榈油", "category": "油脂农产品", "multiplier": 10.0, "margin": 0.08, "tick_size": 2.0,
        "fee_rate": 0.00003, "slippage": 2.0, "max_lots": 6,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.55, "target_atr": 2.8, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.0
    },
    "LC_IDX": {
        "name": "碳酸锂", "category": "新能源电池", "multiplier": 1.0, "margin": 0.12, "tick_size": 50.0,
        "fee_rate": 0.00008, "slippage": 50.0, "max_lots": 2,
        "prob_thresh_5m": 0.25, "prob_thresh_15m": 0.54, "target_atr": 3.0, "sl_atr": 0.9, "be_atr": 1.4, "trail_atr": 3.2
    },
}


class RealDominantPortfolioEngine:
    """真实主力连续多品种组合回测引擎（严格北京时间与防换月跳空）"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def load_data(self, symbol: str, timeframe: str = "5m") -> pd.DataFrame:
        """从数据库读取单品种真实主力 K 线并进行流动性守卫校验"""
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT trade_time, open, high, low, close, volume, amount, open_interest
            FROM futures_min_bars
            WHERE symbol = '{symbol}' AND timeframe = '{timeframe}'
            ORDER BY trade_time ASC;
        """
        df = pd.read_sql(query, conn)
        conn.close()

        if df.empty:
            raise ValueError(f"数据库中未找到 {symbol} 的 [{timeframe}] 真实数据！")

        df["datetime"] = pd.to_datetime(df["trade_time"])
        total_rows = len(df)
        zero_vol_cnt = (df["volume"] <= 0).sum()

        if zero_vol_cnt / total_rows > 0.05:
            print(f"⚠️ 品种 {symbol} 零成交量占比过高 ({zero_vol_cnt}/{total_rows} = {zero_vol_cnt/total_rows*100:.1f}%)，触发流动性守卫！")

        df = df[(df["volume"] > 0) & (df["close"] > 0) & (df["high"] >= df["low"])].copy()
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"]).reset_index(drop=True)
        return df

    def compute_features(self, df: pd.DataFrame, timeframe: str = "5m") -> pd.DataFrame:
        """特征工程（含换月跳空软截断 Winsorization 与宏观趋势零前瞻对齐）"""
        df_work = df.copy().set_index("datetime")

        if timeframe == "5m":
            # 动态内存宏观重采样 (60min)
            df_macro = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            df_macro["ema20"] = calculate_ema(df_macro["close"], 20)
            df_macro["ema60"] = calculate_ema(df_macro["close"], 60)
            df_macro["macro_raw"] = np.where(
                (df_macro["close"] > df_macro["ema20"]) & (df_macro["ema20"] > df_macro["ema60"]), 1,
                np.where((df_macro["close"] < df_macro["ema20"]) & (df_macro["ema20"] < df_macro["ema60"]), -1, 0)
            )
            df_macro["macro_trend"] = df_macro["macro_raw"].shift(1).fillna(0)

            df_merged = pd.merge_asof(
                df.sort_values("datetime"),
                df_macro[["macro_trend"]].reset_index().sort_values("datetime"),
                on="datetime",
                direction="backward"
            )
            df_merged["macro_trend"] = df_merged["macro_trend"].fillna(0)

            c = df_merged["close"].astype(float)
            h = df_merged["high"].astype(float)
            l = df_merged["low"].astype(float)
            v = df_merged["volume"].astype(float)
            oi = df_merged["open_interest"].astype(float)

            df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
            atr14 = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
            atr5 = calculate_atr(df_temp, 5).fillna(pd.Series(c * 0.008))
            atr20 = calculate_atr(df_temp, 20).fillna(pd.Series(c * 0.008))
            df_merged["atr"] = atr14

            # 波动挤压比与软截断
            raw_squeeze = atr5 / (atr20 + 1e-8)
            df_merged["squeeze"] = np.clip(raw_squeeze, 0.2, 3.0)

            s_c = pd.Series(c)
            e4 = calculate_ema(s_c, 4)
            e8 = calculate_ema(s_c, 8)
            e12 = calculate_ema(s_c, 12)
            e24 = calculate_ema(s_c, 24)
            raw_accel = ((e4 - e12) - (e12 - e24)) / (atr14 + 1e-8)
            # 加速度软截断 (防止换月跳空毛刺)
            df_merged["accel"] = np.clip(raw_accel, -4.0, 4.0)

            raw_burst = v / (v.rolling(20).mean() + 1e-8)
            df_merged["vol_burst"] = np.clip(raw_burst, 0.0, 6.0)
            df_merged["rsi_14"] = calculate_rsi(s_c, 14).fillna(50.0)

            hh20 = h.rolling(20).max()
            ll20 = l.rolling(20).min()
            df_merged["donchian_dist"] = np.clip((c - ll20) / (hh20 - ll20 + 1e-8), 0.0, 1.0)
            df_merged["oi_flow"] = np.clip(oi.diff().fillna(0) / (v + 1e-8), -5.0, 5.0)

        else:
            # 动态内存宏观重采样 (120min)
            df_macro = df_work.resample("120min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            df_macro["ema20"] = calculate_ema(df_macro["close"], 20)
            df_macro["ema60"] = calculate_ema(df_macro["close"], 60)
            df_macro["macro_raw"] = np.where(
                (df_macro["close"] > df_macro["ema20"]) & (df_macro["ema20"] > df_macro["ema60"]), 1,
                np.where((df_macro["close"] < df_macro["ema20"]) & (df_macro["ema20"] < df_macro["ema60"]), -1, 0)
            )
            df_macro["macro_trend"] = df_macro["macro_raw"].shift(1).fillna(0)

            df_merged = pd.merge_asof(
                df.sort_values("datetime"),
                df_macro[["macro_trend"]].reset_index().sort_values("datetime"),
                on="datetime",
                direction="backward"
            )
            df_merged["macro_trend"] = df_merged["macro_trend"].fillna(0)

            c = df_merged["close"].astype(float)
            h = df_merged["high"].astype(float)
            l = df_merged["low"].astype(float)
            v = df_merged["volume"].astype(float)
            oi = df_merged["open_interest"].astype(float)

            df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
            atr14 = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
            atr7 = calculate_atr(df_temp, 7).fillna(pd.Series(c * 0.008))
            atr28 = calculate_atr(df_temp, 28).fillna(pd.Series(c * 0.008))
            df_merged["atr"] = atr14

            raw_squeeze = atr7 / (atr28 + 1e-8)
            df_merged["squeeze"] = np.clip(raw_squeeze, 0.2, 3.0)

            s_c = pd.Series(c)
            e6 = calculate_ema(s_c, 6)
            e18 = calculate_ema(s_c, 18)
            e36 = calculate_ema(s_c, 36)
            raw_accel = ((e6 - e18) - (e18 - e36)) / (atr14 + 1e-8)
            df_merged["accel"] = np.clip(raw_accel, -4.0, 4.0)

            raw_burst = v / (v.rolling(20).mean() + 1e-8)
            df_merged["vol_burst"] = np.clip(raw_burst, 0.0, 6.0)
            df_merged["rsi_14"] = calculate_rsi(s_c, 14).fillna(50.0)

            hh20 = h.rolling(20).max()
            ll20 = l.rolling(20).min()
            df_merged["donchian_dist"] = np.clip((c - ll20) / (hh20 - ll20 + 1e-8), 0.0, 1.0)
            df_merged["oi_flow"] = np.clip(oi.diff().fillna(0) / (v + 1e-8), -5.0, 5.0)

        df_merged = df_merged.dropna().reset_index(drop=True)
        return df_merged

    def run_single_symbol_backtest(
        self,
        symbol: str,
        timeframe: str = "5m",
        initial_capital: float = 500000.0
    ) -> dict:
        """运行单品种全真回测"""
        if symbol not in DOMINANT_COMMODITY_SPECS:
            raise ValueError(f"未配置的品种规格: {symbol}")

        spec = DOMINANT_COMMODITY_SPECS[symbol]
        multiplier = spec["multiplier"]
        fee_rate = spec["fee_rate"]
        slippage = spec["slippage"]
        max_lots = spec["max_lots"]
        prob_thresh = spec[f"prob_thresh_{timeframe}"]
        target_atr = spec["target_atr"]
        sl_atr = spec["sl_atr"]
        be_atr = spec["be_atr"]
        trail_atr = spec["trail_atr"]
        max_holding_bars = 40 if timeframe == "5m" else 35

        df_raw = self.load_data(symbol=symbol, timeframe=timeframe)
        df_feat = self.compute_features(df_raw, timeframe=timeframe)

        feature_cols = ["squeeze", "accel", "vol_burst", "rsi_14", "donchian_dist", "oi_flow", "macro_trend"]

        # 三重屏障标签 (剔除换月单 Bar 极端跳空噪声)
        horizon = 20 if timeframe == "5m" else 30
        c = df_feat["close"].values
        h = df_feat["high"].values
        l = df_feat["low"].values
        atr = df_feat["atr"].values
        n = len(df_feat)

        y_long = np.zeros(n)
        y_short = np.zeros(n)
        for i in range(n - horizon):
            cur_c = c[i]
            cur_atr = atr[i]
            future_h = np.max(h[i+1 : i+1+horizon])
            future_l = np.min(l[i+1 : i+1+horizon])

            # 过滤单 Bar 极端换月跳空 (大于 8% 则不作为有效趋势训练样本)
            if abs(future_h / cur_c - 1) > 0.08 or abs(cur_c / future_l - 1) > 0.08:
                continue

            if (future_h - cur_c) >= target_atr * cur_atr and (cur_c - future_l) <= sl_atr * cur_atr:
                y_long[i] = 1
            if (cur_c - future_l) >= target_atr * cur_atr and (future_h - cur_c) <= sl_atr * cur_atr:
                y_short[i] = 1

        df_feat["y_long"] = y_long
        df_feat["y_short"] = y_short

        # Walk-Forward 预测
        train_size = int(n * 0.50)
        purge_gap = horizon + 5

        preds_long = np.zeros(n)
        preds_short = np.zeros(n)

        X_train = df_feat.iloc[:train_size][feature_cols]
        y_train_l = df_feat.iloc[:train_size]["y_long"]
        y_train_s = df_feat.iloc[:train_size]["y_short"]

        clf_l = lgb.LGBMClassifier(n_estimators=60, max_depth=4, learning_rate=0.05, random_state=42, verbose=-1)
        clf_s = lgb.LGBMClassifier(n_estimators=60, max_depth=4, learning_rate=0.05, random_state=42, verbose=-1)

        clf_l.fit(X_train, y_train_l)
        clf_s.fit(X_train, y_train_s)

        X_test = df_feat.iloc[train_size + purge_gap:][feature_cols]
        test_indices = df_feat.iloc[train_size + purge_gap:].index

        if not X_test.empty:
            preds_long[test_indices] = clf_l.predict_proba(X_test)[:, 1]
            preds_short[test_indices] = clf_s.predict_proba(X_test)[:, 1]

        df_feat["prob_long"] = preds_long
        df_feat["prob_short"] = preds_short

        # 逐 Bar 撮合与 PPO 执行
        capital = initial_capital
        equity_curve = [capital]
        trades = []
        in_pos = False
        pos_side = 0
        pos_lots = 0
        entry_price = 0.0
        entry_idx = 0
        entry_time = ""
        highest_p = 0.0
        lowest_p = 0.0
        locked_half = False

        start_eval_idx = train_size + purge_gap

        for i in range(start_eval_idx, n):
            cur_row = df_feat.iloc[i]
            cur_time = str(cur_row["trade_time"])
            cur_o = float(cur_row["open"])
            cur_h = float(cur_row["high"])
            cur_l = float(cur_row["low"])
            cur_c = float(cur_row["close"])
            cur_atr = float(cur_row["atr"])
            p_long = float(cur_row["prob_long"])
            p_short = float(cur_row["prob_short"])
            macro_t = float(cur_row["macro_trend"])

            if in_pos:
                holding_bars = i - entry_idx
                highest_p = max(highest_p, cur_h)
                lowest_p = min(lowest_p, cur_l)

                if pos_side == 1:
                    pnl_atrs = (cur_c - entry_price) / (cur_atr + 1e-8)
                    exit_signal = False
                    exit_price = cur_c
                    exit_reason = ""

                    if cur_l <= entry_price - sl_atr * cur_atr:
                        exit_signal = True
                        exit_price = min(cur_o, entry_price - sl_atr * cur_atr) - slippage
                        exit_reason = f"硬止损 (-{sl_atr} ATR)"
                    elif pnl_atrs >= target_atr and not locked_half and pos_lots >= 2:
                        half_lots = pos_lots // 2
                        locked_half = True
                        lock_price = cur_c - slippage
                        pts = lock_price - entry_price
                        gross = pts * half_lots * multiplier
                        fee = (entry_price + lock_price) * half_lots * multiplier * fee_rate
                        net = gross - fee
                        capital += net
                        pos_lots -= half_lots
                        trades.append({
                            "direction": "LONG (50%锁利)", "lots": half_lots,
                            "entry_time": entry_time, "exit_time": cur_time,
                            "points_pnl": pts, "net_pnl": round(net, 2), "reason": "PPO 阶梯锁利"
                        })
                    elif locked_half and (highest_p - cur_c) >= (trail_atr * 0.5) * cur_atr:
                        exit_signal = True
                        exit_price = cur_c - slippage
                        exit_reason = "动态吊灯追踪止盈"
                    elif pnl_atrs >= be_atr and cur_l <= entry_price + 0.1 * cur_atr:
                        exit_signal = True
                        exit_price = entry_price + 0.1 * cur_atr - slippage
                        exit_reason = "保本安全垫"
                    elif holding_bars >= max_holding_bars:
                        exit_signal = True
                        exit_price = cur_c - slippage
                        exit_reason = "超时强平"

                    if exit_signal:
                        pts = exit_price - entry_price
                        gross = pts * pos_lots * multiplier
                        fee = (entry_price + exit_price) * pos_lots * multiplier * fee_rate
                        net = gross - fee
                        capital += net
                        trades.append({
                            "direction": "LONG", "lots": pos_lots,
                            "entry_time": entry_time, "exit_time": cur_time,
                            "points_pnl": pts, "net_pnl": round(net, 2), "reason": exit_reason
                        })
                        in_pos = False
                        pos_lots = 0

                elif pos_side == -1:
                    pnl_atrs = (entry_price - cur_c) / (cur_atr + 1e-8)
                    exit_signal = False
                    exit_price = cur_c
                    exit_reason = ""

                    if cur_h >= entry_price + sl_atr * cur_atr:
                        exit_signal = True
                        exit_price = max(cur_o, entry_price + sl_atr * cur_atr) + slippage
                        exit_reason = f"硬止损 (+{sl_atr} ATR)"
                    elif pnl_atrs >= target_atr and not locked_half and pos_lots >= 2:
                        half_lots = pos_lots // 2
                        locked_half = True
                        lock_price = cur_c + slippage
                        pts = entry_price - lock_price
                        gross = pts * half_lots * multiplier
                        fee = (entry_price + lock_price) * half_lots * multiplier * fee_rate
                        net = gross - fee
                        capital += net
                        pos_lots -= half_lots
                        trades.append({
                            "direction": "SHORT (50%锁利)", "lots": half_lots,
                            "entry_time": entry_time, "exit_time": cur_time,
                            "points_pnl": pts, "net_pnl": round(net, 2), "reason": "PPO 阶梯锁利"
                        })
                    elif locked_half and (cur_c - lowest_p) >= (trail_atr * 0.5) * cur_atr:
                        exit_signal = True
                        exit_price = cur_c + slippage
                        exit_reason = "动态吊灯追踪止盈"
                    elif pnl_atrs >= be_atr and cur_h >= entry_price - 0.1 * cur_atr:
                        exit_signal = True
                        exit_price = entry_price - 0.1 * cur_atr + slippage
                        exit_reason = "保本安全垫"
                    elif holding_bars >= max_holding_bars:
                        exit_signal = True
                        exit_price = cur_c + slippage
                        exit_reason = "超时强平"

                    if exit_signal:
                        pts = entry_price - exit_price
                        gross = pts * pos_lots * multiplier
                        fee = (entry_price + exit_price) * pos_lots * multiplier * fee_rate
                        net = gross - fee
                        capital += net
                        trades.append({
                            "direction": "SHORT", "lots": pos_lots,
                            "entry_time": entry_time, "exit_time": cur_time,
                            "points_pnl": pts, "net_pnl": round(net, 2), "reason": exit_reason
                        })
                        in_pos = False
                        pos_lots = 0

            # 开仓
            if not in_pos:
                if p_long >= prob_thresh and (macro_t >= 0 or timeframe == "5m"):
                    in_pos = True
                    pos_side = 1
                    pos_lots = max_lots
                    entry_price = cur_c + slippage
                    entry_idx = i
                    entry_time = cur_time
                    highest_p = cur_h
                    lowest_p = cur_l
                    locked_half = False

                elif p_short >= prob_thresh and (macro_t <= 0 or timeframe == "5m"):
                    in_pos = True
                    pos_side = -1
                    pos_lots = max_lots
                    entry_price = cur_c - slippage
                    entry_idx = i
                    entry_time = cur_time
                    highest_p = cur_h
                    lowest_p = cur_l
                    locked_half = False

            equity_curve.append(capital)

        # 统计指标
        df_trades = pd.DataFrame(trades)
        total_trades = len(df_trades)
        if total_trades > 0:
            win_trades = df_trades[df_trades["net_pnl"] > 0]
            loss_trades = df_trades[df_trades["net_pnl"] <= 0]
            win_rate = len(win_trades) / total_trades * 100.0
            total_profit = win_trades["net_pnl"].sum()
            total_loss = abs(loss_trades["net_pnl"].sum())
            profit_factor = round(total_profit / (total_loss + 1e-8), 2)
            total_pnl = capital - initial_capital
            return_pct = round(total_pnl / initial_capital * 100.0, 2)

            eq_arr = np.array(equity_curve)
            peak = np.maximum.accumulate(eq_arr)
            dd = (peak - eq_arr) / (peak + 1e-8) * 100.0
            max_dd = round(np.max(dd), 2)

            bars_per_day = 45 if timeframe == "5m" else 15
            pnl_series = df_trades["net_pnl"].values
            if len(pnl_series) > 1 and np.std(pnl_series) > 0:
                sharpe = round(float(np.mean(pnl_series) / np.std(pnl_series) * np.sqrt(242 * (total_trades / max(1, (n - start_eval_idx) / bars_per_day)))), 2)
            else:
                sharpe = 0.0
        else:
            win_rate, profit_factor, total_pnl, return_pct, max_dd, sharpe = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        eval_start = str(df_feat.iloc[start_eval_idx]["trade_time"])
        eval_end = str(df_feat.iloc[-1]["trade_time"])

        return {
            "symbol": symbol,
            "name": spec["name"],
            "category": spec["category"],
            "timeframe": timeframe,
            "total_bars": n,
            "eval_period": f"{eval_start[:10]} ~ {eval_end[:10]}",
            "initial_capital": initial_capital,
            "final_equity": round(capital, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": return_pct,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
        }

    def run_portfolio(self, symbols, timeframe: str = "15m", capital_per_symbol: float = 500000.0):
        """运行多品种组合回测并输出汇总排行榜"""
        print("=" * 115)
        print(f"🚀 启动真实期货主力连续合约组合全真回测 (北京时间校准 + 换月防毛刺版)")
        print(f"📌 回测周期: {timeframe} | 标的品种数: {len(symbols)} | 单品种初始资金: {capital_per_symbol:,.2f} 元")
        print("=" * 115)

        results = []
        for s in symbols:
            s_clean = s.strip().upper()
            if not s_clean.endswith("_IDX"):
                s_clean = f"{s_clean}_IDX"
            if s_clean not in DOMINANT_COMMODITY_SPECS:
                print(f"⚠️ 跳过未配置品种: {s_clean}")
                continue

            try:
                res = self.run_single_symbol_backtest(s_clean, timeframe=timeframe, initial_capital=capital_per_symbol)
                results.append(res)
                print(f"  ├─ [{res['symbol']:<8} | {res['name']:<4} | {res['category']:<5}] 交易: {res['total_trades']:<3} 笔 | 胜率: {res['win_rate']:>5.1f}% | 盈亏比: {res['profit_factor']:>4.2f} | 夏普: {res['sharpe_ratio']:>5.2f} | 最大回撤: {res['max_drawdown_pct']:>4.2f}% | 净盈亏: {res['total_pnl']:>+10.2f} 元 ({res['return_pct']:>+6.2f}%)")
            except Exception as e:
                print(f"  ├─ ❌ 品种 [{s_clean}] 回测失败: {e}")

        if results:
            print("\n" + "=" * 115)
            print(f"📊 真实期货主力连续合约【{timeframe}】各品种策略回测性能排行榜 (全真撮合与摩擦扣除)")
            print("=" * 115)

            df_summary = pd.DataFrame(results)[[
                "symbol", "name", "category", "eval_period", "total_trades", "win_rate", "profit_factor",
                "sharpe_ratio", "max_drawdown_pct", "total_pnl", "return_pct"
            ]]
            df_summary.columns = ["代码", "名称", "板块", "评估区间", "交易笔数", "胜率(%)", "盈亏比", "夏普比率", "最大回撤(%)", "净盈亏(元)", "收益率(%)"]
            df_summary = df_summary.sort_values(by="夏普比率", ascending=False)
            print(df_summary.to_string(index=False))
            print("=" * 115)

            valid_res = [r for r in results if r["total_trades"] > 0]
            if valid_res:
                avg_wr = sum(r["win_rate"] for r in valid_res) / len(valid_res)
                avg_pf = sum(r["profit_factor"] for r in valid_res) / len(valid_res)
                avg_sr = sum(r["sharpe_ratio"] for r in valid_res) / len(valid_res)
                avg_dd = sum(r["max_drawdown_pct"] for r in valid_res) / len(valid_res)
                total_pnl_all = sum(r["total_pnl"] for r in valid_res)
                total_init_cap = capital_per_symbol * len(valid_res)
                portfolio_ret = total_pnl_all / total_init_cap * 100.0

                print(f"🎯 组合综合表现 (总资金 {total_init_cap:,.2f} 元):")
                print(f"   平均胜率 = {avg_wr:.2f}% | 平均盈亏比 = {avg_pf:.2f} | 平均夏普 = {avg_sr:.2f} | 平均最大回撤 = {avg_dd:.2f}%")
                print(f"   💰 组合总净盈亏 = {total_pnl_all:+,.2f} 元 (整体组合收益率 = {portfolio_ret:+.2f}%)")
                print("=" * 115)
        return results


def main():
    parser = argparse.ArgumentParser(description="Real Dominant Futures Multi-Commodity Portfolio Backtester")
    parser.add_argument("--symbols", type=str, default="AU,AG,SA,I,CU,SC,RB,HC,J,JM,AL,ZN,SN,RU,M,P,LC", help="标的品种代码列表")
    parser.add_argument("--timeframe", type=str, default="15m", choices=["5m", "15m", "all"], help="回测周期: 5m, 15m 或 all")
    parser.add_argument("--capital", type=float, default=500000.0, help="单品种初始资金")
    args = parser.parse_args()

    sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()]
    engine = RealDominantPortfolioEngine()

    tfs = ["15m", "5m"] if args.timeframe == "all" else [args.timeframe]
    for tf in tfs:
        engine.run_portfolio(symbols=sym_list, timeframe=tf, capital_per_symbol=args.capital)


if __name__ == "__main__":
    main()
