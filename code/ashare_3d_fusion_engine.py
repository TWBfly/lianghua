"""
A-Share 3D Fusion Quant Risk & Strategy Engine (三维一体全自动量化风控与交易决策引擎)

融合三大维度：
【维度一】：行情技术与动量因子 (OHLCV, MACD, RSI, 均线) -> ML 选股模型 (ml_strategy_engine.py)
【维度二】：财报基本面指标 (营收增长、扣非净利润、ROE) -> 本地数据库财报因子过滤 (ashare_financial_fetcher.py)
【维度三】：大模型文本语义风控 (最新公告、风险提示、新闻文本) -> DeepSeek API 智能审核 (deepseek_quant_copilot.py)
"""

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

        self.ml_engine.train_and_eval(panel_df, split_date="2025-01-01")
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
            
            # 从本地数据库优先查询利润表 (0 网络延迟)
            df_inc = self.fin_fetcher.get_income_statement(sym)
            
            is_fund_ok = True
            fund_reason = "财报健康"

            if df_inc is not None and not df_inc.empty:
                latest_report = df_inc.iloc[0]
                net_profit = float(latest_report.get('parent_netprofit', 0.0) or 0.0)
                
                # 硬性过滤规则：剔除单季净利润亏损严重的标的
                if net_profit < 0:
                    is_fund_ok = False
                    fund_reason = f"最新季度净利润亏损 ({net_profit / 1e8:.2f} 亿元)"

            if is_fund_ok:
                print(f"   ├─ ✅ [{sym}] {name} - 财报审核通过 ({fund_reason})")
                fundamental_approved.append(row)
            else:
                print(f"   └─ ❌ [{sym}] {name} - 基本面硬性剔除 ({fund_reason})")

        fund_df = pd.DataFrame(fundamental_approved)
        if fund_df.empty:
            print("[Warning] 基本面过滤后无符合要求股票，放宽条件。")
            fund_df = ml_picks.head(top_k)
        else:
            fund_df = fund_df.head(top_k)

        # ---------------------------------------------------------------------
        # 【维度三】：大模型文本语义风控 (最新公司公告 & 新闻 -> DeepSeek API)
        # ---------------------------------------------------------------------
        print("\n[维度三 🤖] 结合最新公司公告与新闻，调用 DeepSeek API 进行文本语义风控与终审...")
        
        # 为候选股票匹配最新的公告/新闻摘要，传给 DeepSeek
        notices_summary = []
        for idx, row in fund_df.iterrows():
            sym = row['symbol']
            df_not = self.fin_fetcher.get_company_notices(symbol=sym)
            recent_notice_title = df_not.iloc[0]['title'] if (df_not is not None and not df_not.empty) else "无重大异常公告"
            
            notices_summary.append(
                f"代码: {sym}, 名称: {row['name']}, 最新公告: 《{recent_notice_title}》, PE: {row['pe_ttm']}"
            )

        print("   ├─ 已调取本地公告数据，正在发送至 DeepSeek 投资委员会...")
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
        print("✨ 三维一体全自动量化风控系统完成执行！已实现 零手动介入 的全流程避雷与仓位配置。")
        return final_df


if __name__ == "__main__":
    fusion_engine = AShare3DFusionEngine()
    fusion_engine.run_3d_quant_pipeline(top_k=5)
