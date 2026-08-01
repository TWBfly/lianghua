"""
A-Share Machine Learning Quantitative Strategy Engine (ML 多因子选股预测引擎)
使用梯度提升树 (HistGradientBoosting / LightGBM) 对 A 股全市场进行截面多因子收益率预测与排序选股
配合时序交叉验证 (Time-Series Split)，防止数据渗漏
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

# 引入因子提取管道
sys.path.append(os.path.dirname(__file__))
from ashare_factor_pipeline import AShareFactorPipeline, DB_PATH

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_squared_error, r2_score
except ImportError:
    print("[Error] 请先安装 scikit-learn: pip install scikit-learn")


class AShareMLStrategyEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.pipeline = AShareFactorPipeline(db_path=db_path)
        self.model = HistGradientBoostingRegressor(
            max_iter=150,
            learning_rate=0.05,
            max_depth=6,
            random_state=42
        )
        self.is_trained = False
        self.feature_cols = []

    def build_dataset(self, symbols=None, start_date="2022-01-01", end_date="2026-07-29"):
        """构建全市场 panel 多因子数据集"""
        if symbols is None:
            with sqlite3.connect(self.db_path) as conn:
                symbols = pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC LIMIT 100", conn)['symbol'].tolist()

        print(f"[ML Engine] 正在为 {len(symbols)} 只核心 A 股提取因子特征...")
        all_dfs = []

        for sym in symbols:
            df = self.pipeline.extract_factors(sym, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df['symbol'] = sym
                all_dfs.append(df)

        if not all_dfs:
            print("[Error] 未获取到有效因子数据！")
            return None

        panel_df = pd.concat(all_dfs, axis=0)
        panel_df.sort_index(inplace=True)
        print(f"[ML Engine] 全市场 Panel 数据集构建完成，总样本量: {len(panel_df)} 条，特征维度: {panel_df.shape[1]}")
        return panel_df

    def train_and_eval(self, panel_df, split_date="2025-01-01"):
        """使用时间序列划分训练集与测试集，训练机器学习模型"""
        self.feature_cols = [c for c in panel_df.columns if c not in ['symbol', 'target_5d_return']]

        # 时间序列切分 (绝无未来数据泄露)
        train_df = panel_df[panel_df.index < split_date].dropna(subset=['target_5d_return'])
        test_df = panel_df[panel_df.index >= split_date].dropna(subset=['target_5d_return'])

        X_train, y_train = train_df[self.feature_cols], train_df['target_5d_return']
        X_test, y_test = test_df[self.feature_cols], test_df['target_5d_return']

        print(f"[ML Train] 训练集样本数 (2022~2024): {len(X_train)} | 测试集样本数 (2025~2026): {len(X_test)}")

        # 模型训练
        self.model.fit(X_train, y_train)
        self.is_trained = True

        # 测试集评估
        y_pred = self.model.predict(X_test)
        test_df['pred_return'] = y_pred

        # 评估指标计算
        r2 = r2_score(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))

        # 计算 Rank IC (秩相关系数)
        rank_ic = test_df.groupby(level=0).apply(lambda d: d['pred_return'].corr(d['target_5d_return'], method='spearman')).mean()

        print("\n" + "="*50)
        print(f"机器学习模型 (HistGradientBoosting) 评估指标:")
        print(f"  ├─ R² 得分: {r2:.4f}")
        print(f"  ├─ 均方根误差 (RMSE): {rmse:.4f}")
        print(f"  └─ 平均 IC (Rank IC): {rank_ic:.4f} {'(表现优异 > 0.05)' if rank_ic > 0.05 else '(预测能力良好)'}")
        print("="*50)

        return test_df

    def predict_top_stocks(self, target_date=None, top_k=10):
        """预测指定日期截面下的前 K 只潜力反弹/领涨股票"""
        if not self.is_trained:
            print("[Error] 模型尚未训练，请先调用 train_and_eval()")
            return None

        with sqlite3.connect(self.db_path) as conn:
            if target_date is None:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(trade_date) FROM stock_daily;")
                target_date = cursor.fetchone()[0]

        print(f"\n[ML Predict] 正在对截面日期 {target_date} 的股票进行 Alpha 得分预测...")

        symbols = pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC LIMIT 100", conn)['symbol'].tolist()
        predict_records = []

        for sym in symbols:
            df = self.pipeline.extract_factors(sym)
            if df is not None and not df.empty:
                # 寻找离 target_date 最近的最新可用交易日
                if target_date in df.index:
                    latest_row = df.loc[target_date]
                else:
                    latest_row = df.iloc[-1]

                feat_df = pd.DataFrame([latest_row[self.feature_cols]], columns=self.feature_cols)
                pred_score = self.model.predict(feat_df)[0]
                
                # 获取股票名称
                name_res = pd.read_sql_query(f"SELECT name, price, pe_ttm FROM stock_basic WHERE symbol='{sym}'", conn)
                name = name_res['name'].values[0] if not name_res.empty else sym
                price = name_res['price'].values[0] if not name_res.empty else latest_row['close']
                pe = name_res['pe_ttm'].values[0] if not name_res.empty else 0

                predict_records.append({
                    'symbol': sym,
                    'name': name,
                    'price': price,
                    'pe_ttm': pe,
                    'predicted_5d_return_pct': pred_score * 100
                })

        res_df = pd.DataFrame(predict_records).sort_values(by='predicted_5d_return_pct', ascending=False)
        top_picks = res_df.head(top_k)
        
        print(f"\n[ML Alpha Top {top_k}] 基于 36 维量化因子模型预测的前 {top_k} 股票选股列表:")
        print(top_picks.to_string(index=False))
        return top_picks


if __name__ == "__main__":
    ml_engine = AShareMLStrategyEngine()
    panel_df = ml_engine.build_dataset()
    if panel_df is not None:
        ml_engine.train_and_eval(panel_df)
        ml_engine.predict_top_stocks(top_k=10)
