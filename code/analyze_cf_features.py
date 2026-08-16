"""
Feature Importance & Trade Profiling for Cotton (CF_IDX) 5m
"""

import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


def analyze_cf():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    query = """
        SELECT trade_time as datetime, open, high, low, close, volume, open_interest
        FROM futures_min_bars
        WHERE symbol = 'CF_IDX' AND timeframe = '5m'
        ORDER BY trade_time ASC;
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[(df["volume"] > 0) & (df["close"] > 0) & (df["high"] >= df["low"])].copy()
    df = df.sort_values("datetime").reset_index(drop=True)

    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)
    oi = df["open_interest"].fillna(0).astype(float)

    df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    atr14 = calculate_atr(df_temp, 14).fillna(c * 0.008)
    atr5 = calculate_atr(df_temp, 5).fillna(c * 0.008)
    atr20 = calculate_atr(df_temp, 20).fillna(c * 0.008)
    df["atr_14"] = atr14

    # 宏观 30m / 60m / 120m 趋势 (严格 shift 1)
    df_work = df.copy().set_index("datetime")
    df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
    df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
    df_60m["macro_60m"] = np.where((df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"]), 1,
                           np.where((df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"]), -1, 0))
    df_60m["macro_trend_60m"] = df_60m["macro_60m"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_60m[["macro_trend_60m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 1. 动量与多尺度均线偏离
    for period in [5, 10, 20, 40, 80]:
        ema_p = calculate_ema(pd.Series(c), period)
        df[f"dist_ema_{period}"] = (c - ema_p) / (atr14 + 1e-8)

    # 2. 真实波动幅度通道
    df["squeeze_5m"] = atr5 / (atr20 + 1e-8)
    df["accel_5m"] = ((calculate_ema(pd.Series(c), 4) - calculate_ema(pd.Series(c), 12)) - (calculate_ema(pd.Series(c), 12) - calculate_ema(pd.Series(c), 24))) / (atr14 + 1e-8)
    df["fast_trend"] = (calculate_ema(pd.Series(c), 8) - calculate_ema(pd.Series(c), 24)) / (atr14 + 1e-8)
    df["slow_trend"] = (calculate_ema(pd.Series(c), 24) - calculate_ema(pd.Series(c), 72)) / (atr14 + 1e-8)

    # 3. 量价与持仓
    v_ma = v.rolling(20).mean() + 1e-8
    df["vol_burst_5m"] = v / v_ma
    df["oi_flow_5m"] = oi.diff().fillna(0) / v_ma
    df["rsi_14_5m"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

    # 唐奇安
    donch_hi = h.rolling(24).max().shift(1)
    donch_lo = l.rolling(24).min().shift(1)
    df["donchian_dist_5m"] = (c - (donch_hi + donch_lo) / 2.0) / (atr14 + 1e-8)

    feature_cols = [
        "fast_trend", "slow_trend", "accel_5m", "squeeze_5m",
        "vol_burst_5m", "donchian_dist_5m", "oi_flow_5m", "rsi_14_5m",
        "dist_ema_5", "dist_ema_10", "dist_ema_20", "dist_ema_40", "dist_ema_80"
    ]
    df_clean = df.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

    print(f"Features ready. Shape: {df_clean.shape}")

    # 训练模型并查看特征重要性
    horizon = 36
    target_atr = 3.8
    sl_label = 0.9

    fut_h = pd.Series(df_clean["high"])[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1).values
    fut_l = pd.Series(df_clean["low"])[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1).values
    c_vals = df_clean["close"].values
    atr_vals = df_clean["atr_14"].values

    label_l = (((fut_h - c_vals) / (atr_vals + 1e-8) >= target_atr) & ((c_vals - fut_l) / (atr_vals + 1e-8) < sl_label)).astype(int)
    label_s = (((c_vals - fut_l) / (atr_vals + 1e-8) >= target_atr) & ((fut_h - c_vals) / (atr_vals + 1e-8) < sl_label)).astype(int)

    clf = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.03, max_depth=4, num_leaves=10, random_state=42, verbose=-1)
    clf.fit(df_clean[feature_cols].values, label_l)
    imp = pd.Series(clf.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\nFeature Importance for Label Long:")
    print(imp)


if __name__ == "__main__":
    analyze_cf()
