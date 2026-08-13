"""
A-Share Machine Learning Quantitative Strategy Engine (ML 多因子选股预测引擎)
使用梯度提升树 (HistGradientBoosting / LightGBM) 对 A 股全市场进行截面多因子收益率预测与排序选股
仅用于当前截面研究拟合；历史评估统一由滚动回测引擎处理
"""

import os
import sys
import sqlite3
import pandas as pd

# 引入因子提取管道
sys.path.append(os.path.dirname(__file__))
from ashare_factor_pipeline import AShareFactorPipeline, DB_PATH

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
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
    def get_pit_universe(self, conn, target_date=None, limit=100):
        """点位时间 (Point-In-Time) 无生存者偏差股票池提取"""
        try:
            if target_date is None:
                max_date_row = conn.execute("SELECT MAX(trade_date) FROM stock_daily;").fetchone()
                target_date = max_date_row[0] if max_date_row and max_date_row[0] else None
            if target_date:
                target_date = pd.Timestamp(target_date).strftime("%Y-%m-%d")
                query = """
                    SELECT DISTINCT d.symbol 
                    FROM stock_daily d
                    JOIN stock_basic b ON d.symbol = b.symbol
                    WHERE d.trade_date <= ? AND d.volume > 0
                    GROUP BY d.symbol
                    HAVING MAX(d.trade_date) >= date(?, '-30 days')
                    ORDER BY b.total_mv DESC
                    LIMIT ?
                """
                rows = conn.execute(query, (target_date, target_date, limit)).fetchall()
                if rows:
                    return [r[0] for r in rows]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass
        return pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC LIMIT ?", conn, params=(limit,))['symbol'].tolist()

    def build_dataset(self, symbols=None, start_date="2022-01-01", end_date="2026-07-29"):
        """构建全市场 panel 多因子数据集 (支持 PIT 无生存者偏差池)"""
        if symbols is None:
            with sqlite3.connect(self.db_path) as conn:
                symbols = self.get_pit_universe(conn, target_date=end_date, limit=100)

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

    def fit_current_model(self, panel_df):
        """拟合当前截面研究模型；不产生历史绩效结论。"""
        self.feature_cols = [
            column for column in panel_df.columns
            if column not in {"symbol", "target_5d_return"}
        ]
        training = panel_df.dropna(subset=["target_5d_return"])
        if training.empty:
            raise ValueError("no mature labels for current snapshot training")
        self.model.fit(
            training[self.feature_cols],
            training["target_5d_return"],
        )
        self.is_trained = True
        return {
            "scope": "CURRENT_SNAPSHOT_RESEARCH_ONLY",
            "historical_backtest": False,
            "point_in_time_universe": False,
            "training_samples": len(training),
        }

    def train_and_eval(self, panel_df, split_date="2025-01-01"):
        del panel_df, split_date
        raise RuntimeError(
            "legacy single-split historical evaluation is disabled; "
            "use KLineBacktestEngine"
        )

    def predict_top_stocks(self, target_date=None, top_k=10):
        """预测指定日期截面下的前 K 只潜力反弹/领涨股票 (Point-In-Time 选股)"""
        if not self.is_trained:
            print("[Error] 模型尚未训练，请先调用 fit_current_model()")
            return None

        with sqlite3.connect(self.db_path) as conn:
            if target_date is None:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(trade_date) FROM stock_daily;")
                target_date = cursor.fetchone()[0]
            target_date = pd.Timestamp(target_date).strftime("%Y-%m-%d")

            symbols = self.get_pit_universe(conn, target_date=target_date, limit=100)

            print(f"\n[ML Predict] 正在对截面日期 {target_date} 的股票进行 Alpha 得分预测...")
            predict_records = []

            for sym in symbols:
                df = self.pipeline.extract_factors(
                    sym, end_date=target_date
                )
                if df is None or df.empty:
                    continue
                prefix = df.loc[df.index <= pd.Timestamp(target_date)]
                if prefix.empty:
                    continue
                latest_row = prefix.iloc[-1]

                feat_df = pd.DataFrame([latest_row[self.feature_cols]], columns=self.feature_cols)
                pred_score = self.model.predict(feat_df)[0]
                
                # 获取股票名称
                name_res = pd.read_sql_query(
                    "SELECT name, price, pe_ttm FROM stock_basic "
                    "WHERE symbol=?",
                    conn,
                    params=(str(sym),),
                )
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

        res_df = pd.DataFrame(predict_records)
        if res_df.empty:
            return res_df
        res_df = res_df.sort_values(by='predicted_5d_return_pct', ascending=False)
        top_picks = res_df.head(top_k)
        
        print(f"\n[ML Alpha Top {top_k}] 基于 36 维量化因子模型预测的前 {top_k} 股票选股列表:")
        print(top_picks.to_string(index=False))
        return top_picks


if __name__ == "__main__":
    ml_engine = AShareMLStrategyEngine()
    panel_df = ml_engine.build_dataset()
    if panel_df is not None:
        print(ml_engine.fit_current_model(panel_df))
        ml_engine.predict_top_stocks(top_k=10)
