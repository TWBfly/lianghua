"""
A-Share Quantitative Strategy Engine - Base Class for Symbol-Specific 15m ML Engines
【各品种独立机器学习策略引擎基类】
"""

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
    calculate_rsi,
    calculate_yang_zhang_volatility,
    calculate_volatility_scaled_ma_distance,
    calculate_skip_momentum
)

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


class BaseSymbolEngine:
    """各期货品种独立 15m 策略引擎抽象基类"""

    def __init__(self, symbol: str, name: str, category: str, contract_multiplier: float, margin_rate: float, db_path: str = DB_PATH):
        self.symbol = symbol
        self.name = name
        self.category = category
        self.contract_multiplier = contract_multiplier
        self.margin_rate = margin_rate
        self.fee_rate = 0.00005  # 单边万分之0.5
        self.db_path = db_path

    def load_15m_data(self) -> pd.DataFrame:
        """从 SQLite 加载 5 年全量 15m K 线"""
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT trade_time as datetime, open, high, low, close, volume, amount
            FROM futures_min_bars
            WHERE symbol = '{self.symbol}' AND timeframe = '15m'
            ORDER BY trade_time ASC;
        """
        df_15m = pd.read_sql(query, conn)
        conn.close()

        if df_15m.empty:
            raise ValueError(f"未能在数据库中查找到 {self.symbol} 的 15m 数据！")

        df_15m["datetime"] = pd.to_datetime(df_15m["datetime"])
        df_15m = df_15m.sort_values("datetime").reset_index(drop=True)
        return df_15m

    def build_macro_trend(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """计算 1h 宏观趋势护城河"""
        df_work = df_15m.copy().set_index("datetime")
        df_1h = df_work.resample("60min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        df_1h["ema_20_1h"] = calculate_ema(df_1h["close"], 20)
        df_1h["ema_50_1h"] = calculate_ema(df_1h["close"], 50)
        df_1h["trend_1h"] = np.where(df_1h["ema_20_1h"] > df_1h["ema_50_1h"], 1, -1)
        df_1h["macro_slope_1h"] = (df_1h["ema_20_1h"] - df_1h["ema_50_1h"]) / (df_1h["ema_50_1h"] + 1e-8)

        df_merged = pd.merge_asof(
            df_15m.sort_values("datetime"),
            df_1h[["trend_1h", "macro_slope_1h"]].reset_index().sort_values("datetime"),
            on="datetime",
            direction="backward"
        )
        df_merged["trend_1h"] = df_merged["trend_1h"].fillna(0)
        df_merged["macro_slope_1h"] = df_merged["macro_slope_1h"].fillna(0.0)
        return df_merged

    def run_walk_forward_ml(
        self,
        clean_df: pd.DataFrame,
        feature_cols: list,
        train_window: int = 2400,
        step_size: int = 300,
        purge_gap: int = 20
    ) -> tuple:
        """运行 Embargoed Walk-Forward 绝对防泄漏机器学习模型训练与预测"""
        n_samples = len(clean_df)
        X_mat = clean_df[feature_cols].values.astype(np.float32)
        y_long = clean_df["label_long"].values
        y_short = clean_df["label_short"].values

        prob_long = np.full(n_samples, np.nan)
        prob_short = np.full(n_samples, np.nan)

        model_params = dict(
            n_estimators=50,
            learning_rate=0.03,
            max_depth=3,
            num_leaves=6,
            min_child_samples=25,
            subsample=0.7,
            colsample_bytree=0.6,
            reg_alpha=0.5,
            reg_lambda=2.0,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
            n_jobs=1
        )

        for end_idx in range(train_window + purge_gap, n_samples, step_size):
            train_s = max(0, end_idx - train_window - purge_gap)
            train_e = end_idx - purge_gap
            pred_s = end_idx
            pred_e = min(end_idx + step_size, n_samples)

            if train_e - train_s < 150:
                continue

            X_tr = X_mat[train_s:train_e]
            y_tr_l = y_long[train_s:train_e]
            y_tr_s = y_short[train_s:train_e]
            X_pred = X_mat[pred_s:pred_e]

            if y_tr_l.sum() >= 8:
                clf_l = lgb.LGBMClassifier(**model_params).fit(X_tr, y_tr_l)
                prob_long[pred_s:pred_e] = clf_l.predict_proba(X_pred)[:, 1]

            if y_tr_s.sum() >= 8:
                clf_s = lgb.LGBMClassifier(**model_params).fit(X_tr, y_tr_s)
                prob_short[pred_s:pred_e] = clf_s.predict_proba(X_pred)[:, 1]

        return prob_long, prob_short
