"""Legacy fusion entry point with fail-closed data checks."""

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from ml_strategy_engine import AShareMLStrategyEngine
from ashare_financial_fetcher import AShareFinancialFetcher
from deepseek_quant_copilot import DeepSeekQuantCopilot
from ashare_factor_pipeline import DB_PATH


class AShare3DFusionEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.ml_engine = AShareMLStrategyEngine(db_path=db_path)
        self.fin_fetcher = AShareFinancialFetcher(db_path=db_path)
        self.copilot = DeepSeekQuantCopilot()

    def run_3d_quant_pipeline(self, top_k=5, initial_capital=1000000.0):
        """执行三维一体全自动风控与决策完整流水线"""
        print("\n" + "="*80)
        print("🌐 启动 A 股三维一体 (行情技术 + 财报基本面 + 大模型公告) 全自动量化风控策略...")
        print("="*80)

        # ---------------------------------------------------------------------
        # 【维度一】：行情技术与动量机器学习选股
        # ---------------------------------------------------------------------
        print("\n[维度一 📈] 正在提取全市场 OHLCV 动量/波动率/均线因子，运行机器学习选股...")
        panel_df = self.ml_engine.build_dataset()
        if panel_df is None:
            print("[Error] 数据不足，退出。")
            return

        print(self.ml_engine.fit_current_model(panel_df))
        ml_picks = self.ml_engine.predict_top_stocks(top_k=top_k * 2)  # 多选候选供后置维度过滤

        if ml_picks is None or ml_picks.empty:
            print("[Error] ML 选股列表为空。")
            return

        # ---------------------------------------------------------------------
        # 【维度二】：财报基本面数据硬性因子过滤 (本地数据库查询)
        # ---------------------------------------------------------------------
        print("\n[维度二 📊] 正在从本地数据库调取候选股票财报数据，进行基本面因硬性过滤...")
        fundamental_approved = []

        for idx, row in ml_picks.iterrows():
            sym = row['symbol']
            name = row['name']
            
            audit = self.fin_fetcher.audit_financial_quality(sym)
            is_fund_ok = audit["is_passed"]
            fund_reason = audit["status"]

            if is_fund_ok:
                print(f"   ├─ ✅ [{sym}] {name} - 财报审核通过 ({fund_reason})")
                fundamental_approved.append(row)
            else:
                print(f"   └─ ❌ [{sym}] {name} - 基本面硬性剔除 ({fund_reason})")

        fund_df = pd.DataFrame(fundamental_approved)
        if fund_df.empty:
            print("[Stop] 缺少可验证基本面数据，不生成候选组合。")
            return pd.DataFrame()
        fund_df = fund_df.head(top_k)

        # ---------------------------------------------------------------------
        # 【维度三】：大模型文本语义风控 (最新公司公告 & 新闻 -> DeepSeek API)
        # ---------------------------------------------------------------------
        print("\n[AI] 缺少带来源与时点的文档，审核结果将为 UNAVAILABLE。")
        audit_res = self.copilot.audit_top_stocks(fund_df)

        # ---------------------------------------------------------------------
        # 最终三维融合成果与建仓输出
        # ---------------------------------------------------------------------
        print("\n" + "="*80)
        print("🎯 三维一体全自动量化风控策略 - 最终资产配置决策:")
        print("="*80)

        final_portfolio = []
        total_alloc = 0.0

        if isinstance(audit_res, pd.DataFrame) and 'decision' in audit_res.columns:
            for idx, row in audit_res.iterrows():
                sym = row['symbol']
                decision = row['decision']
                pos_pct = float(row.get('suggested_position_pct', 0.0))
                
                if decision == 'APPROVED' and pos_pct > 0:
                    val = initial_capital * (pos_pct / 100.0)
                    final_portfolio.append({
                        'symbol': sym,
                        'name': row.get('name', sym),
                        'decision': decision,
                        'suggested_position_pct': pos_pct,
                        'target_amount_cny': val,
                        'risk_level': row.get('risk_level', 'LOW')
                    })
                    total_alloc += pos_pct

        final_df = pd.DataFrame(final_portfolio)
        print(final_df.to_string(index=False))
        print(f"\n现金保留额度: ¥{initial_capital * (1 - total_alloc/100.0):,.2f} (占比 {(100 - total_alloc):.1f}%)")
        print("="*80)
        print("流程结束；仅输出通过可验证检查的结果。")
        return final_df


if __name__ == "__main__":
    fusion_engine = AShare3DFusionEngine()
    fusion_engine.run_3d_quant_pipeline(top_k=5)
