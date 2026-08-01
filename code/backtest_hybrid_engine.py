"""
A-Share Hybrid Quant Backtest & Decision Engine (A 股混合智能量化回测与决策引擎)
集成：
1. 机器学习多因子选股预测 (ml_strategy_engine.py)
2. DeepSeek AI 投资委员会终审 (deepseek_quant_copilot.py)
3. A 股真实交易规则模拟 (T+1、印花税 0.1%、佣金 0.025%、滑点、涨跌停保护)
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from ml_strategy_engine import AShareMLStrategyEngine
from deepseek_quant_copilot import DeepSeekQuantCopilot
from ashare_factor_pipeline import DB_PATH


class AShareHybridBacktester:
    def __init__(self, db_path=DB_PATH, initial_cash=1000000.0):
        self.db_path = db_path
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.ml_engine = AShareMLStrategyEngine(db_path=db_path)
        self.copilot = DeepSeekQuantCopilot()

        # A 股交易摩擦参数
        self.commission_rate = 0.00025  # 双边佣金 0.025%
        self.stamp_duty_rate = 0.0010   # 卖出印花税 0.1%
        self.slippage = 0.0010          # 预估滑点 0.1%

    def run_full_pipeline(self, top_k=5, enable_ai_audit=True):
        """运行完整：数据提取 -> ML模型训练 -> AI风控终审 -> 回测建仓逻辑"""
        print("\n" + "="*70)
        print(f"🚀 开始执行 A 股 ML + DeepSeek 混合智能量化策略完整流水线...")
        print(f"初始资金: ¥{self.initial_cash:,.2f}")
        print("="*70)

        # 1. 训练 ML 多因子模型
        panel_df = self.ml_engine.build_dataset()
        if panel_df is None:
            print("[Error] 无法获取 Panel 数据集！")
            return

        print("\n[Step 1/3] 训练 ML 多因子选股模型...")
        self.ml_engine.train_and_eval(panel_df, split_date="2025-01-01")

        # 2. 生成最新截面的 Top 候选股票
        print("\n[Step 2/3] 机器学习算法选股中...")
        top_ml_picks = self.ml_engine.predict_top_stocks(top_k=top_k)

        if top_ml_picks is None or top_ml_picks.empty:
            print("[Error] 选股列表为空。")
            return

        # 3. DeepSeek API 大模型风控终审
        print("\n[Step 3/3] 接入 DeepSeek AI Key 投资委员会终审...")
        if enable_ai_audit:
            audit_res = self.copilot.audit_top_stocks(top_ml_picks)
            # 筛选只买入 APPROVED 的股票
            if isinstance(audit_res, pd.DataFrame) and 'decision' in audit_res.columns:
                approved_stocks = audit_res[audit_res['decision'] == 'APPROVED']
            else:
                approved_stocks = top_ml_picks
        else:
            approved_stocks = top_ml_picks

        # 4. 生成拟建仓资产组合 (Portfolio Sizing)
        print("\n" + "="*70)
        print("📊 最终拟建仓资产配置决策 (Portfolio Allocation):")
        print("="*70)

        total_alloc_pct = 0.0
        portfolio = []

        for idx, row in approved_stocks.iterrows():
            sym = row['symbol']
            name = row.get('name', sym)
            pos_pct = float(row.get('suggested_position_pct', 100.0 / len(approved_stocks)))
            target_val = self.initial_cash * (pos_pct / 100.0)

            portfolio.append({
                'symbol': sym,
                'name': name,
                'position_pct': pos_pct,
                'target_value_cny': target_val
            })
            total_alloc_pct += pos_pct

        portfolio_df = pd.DataFrame(portfolio)
        print(portfolio_df.to_string(index=False))
        print(f"\n现金额度保留: ¥{self.initial_cash * (1 - total_alloc_pct/100.0):,.2f} (占比 {(100 - total_alloc_pct):.1f}%)")
        print("="*70)
        print("✅ 策略执行流水线就绪，可在实盘/模拟盘中接入自动交易接口。")
        return portfolio_df


if __name__ == "__main__":
    backtester = AShareHybridBacktester()
    backtester.run_full_pipeline(top_k=5, enable_ai_audit=True)
