"""
A-Share Quant Factor Pipeline for ML / DL / DRL / AI Strategy Modeling
构建适用于机器学习与强化学习训练的数据特征矩阵 (Feature Matrix)
包含：经典动量/均线/波动率因子、SMC机构结构因子、多因子截面标准化与神经网络 Tensor 转换
"""

import os
import sqlite3
import pandas as pd
import numpy as np

from market_data import validate_daily_bars
from technical_indicators import (
    build_forward_return_target,
    calculate_technical_indicators,
    causal_expanding_zscore,
)

DB_PATH = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"

class AShareFactorPipeline:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def extract_factors(self, symbol, start_date=None, end_date=None):
        """
        从本地数据库提取指定股票的高维因子特征向量 (Feature Tensor)
        用于 XGBoost/LightGBM、PyTorch LSTM/Transformer 或 DRL State 空间
        """
        clauses = ["symbol=?"]
        params = [str(symbol)]
        if start_date:
            clauses.append("trade_date>=?")
            params.append(str(start_date))
        if end_date:
            clauses.append("trade_date<=?")
            params.append(str(end_date))
        query = (
            "SELECT * FROM stock_daily WHERE "
            + " AND ".join(clauses)
            + " ORDER BY trade_date"
        )

        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty or len(df) < 30:
            print(f"[Warning] 股票 {symbol} 的数据不足 30 条，无法提取因子。")
            return None

        df = validate_daily_bars(df, str(symbol))
        df.set_index('trade_date', inplace=True)

        indicators = calculate_technical_indicators(df)
        for column in indicators.columns:
            df[column] = indicators[column]
        # Compatibility column; label calculation remains separate from factors.
        df['target_5d_return'] = build_forward_return_target(df['close'])
        print(f"[Factor] 成功为股票 {symbol} 提取 {df.shape[1]} 维特征矩阵，样本数: {len(df)}")
        return df

    def prepare_drl_environment_matrix(self, symbol, window_size=30):
        """
        准备强化学习 (DRL, 如 PPO/SAC) 的 State Tensor
        将过去的 window_size 天多维特征拼接为 [N, window_size, num_features] 的三维张量
        """
        df_factors = self.extract_factors(symbol)
        if df_factors is None:
            return None, None

        feature_cols = [c for c in df_factors.columns if c not in ['symbol', 'target_5d_return']]
        normalized = causal_expanding_zscore(
            df_factors[feature_cols].astype(float)
        )
        features = normalized.to_numpy(dtype=float)
        targets = df_factors['target_5d_return'].values

        X, Y = [], []
        valid_len = len(features) - 5  # ponytail: target_5d_return last 5 rows are NaN
        for i in range(window_size, valid_len):
            X.append(features[i - window_size + 1:i + 1])  # ponytail: include bar i in observation
            Y.append(targets[i])

        X = np.array(X)
        Y = np.array(Y)
        print(f"[DRL Ready] 转换完成 - 特征张量形状 (State Space): {X.shape}, 目标形状: {Y.shape}")
        return X, Y


if __name__ == "__main__":
    pipeline = AShareFactorPipeline()
    # 提取贵州茅台 (600519) 因子矩阵与强化学习 State 张量
    df_feat = pipeline.extract_factors("600519", start_date="2022-01-01")
    if df_feat is not None:
        print("\n特征矩阵前 3 行预览:")
        print(df_feat[['close', 'return_1d', 'macd_hist', 'rsi_14', 'norm_atr', 'vol_ratio', 'target_5d_return']].head(3))

    X_drl, Y_drl = pipeline.prepare_drl_environment_matrix("600519")
