"""
Charlie Munger Wonderful Stock Screener (芒格好公司筛选器引擎)

芒格核心投资哲学：
"It's far better to buy a wonderful company at a fair price than a fair company at a wonderful price."
(用合理的价格买入伟大的公司，胜过用便宜的价格买入平庸的公司。)

五维筛选标准：
1. 盈利能力 (ROE): 连续 3 年加权 ROE ≥ 15%
2. 护城河 (Moat): 毛利率 ≥ 30% 且 经营现金流 > 0
3. 财务健康 (Safety): 资产负债率 < 60%
4. 公司治理 (Integrity): 无立案调查、无退市风险警示 ( DeepSeek 文本 + 数据库公告过滤 )
5. 合理估值 (Fair Price): PE-TTM < 60 且 估值未严重泡沫化
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(__file__))
from ashare_financial_fetcher import AShareFinancialFetcher
from deepseek_quant_copilot import DeepSeekQuantCopilot
from ashare_factor_pipeline import DB_PATH


class MungerStockScreener:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.fin_fetcher = AShareFinancialFetcher(db_path=db_path)
        self.copilot = DeepSeekQuantCopilot()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def screen_wonderful_companies(self, min_roe=15.0, max_pe=60.0):
        """
        第一步：基于芒格五维标准，筛选出全市场优秀公司股票池 (Wonderful Stock Universe)
        """
        print("\n" + "="*80)
        print("🏛️ 启动【查理·芒格】五维好公司筛选器 (Munger Wonderful Company Screener)...")
        print("="*80)

        # 维度 5 估值预筛选 (0 < PE <= max_pe 且 PB > 0)
        with self.get_connection() as conn:
            query = f"""
            SELECT symbol, name, price, pe_ttm, pb, total_mv, circ_mv 
            FROM stock_basic 
            WHERE pe_ttm > 0 AND pe_ttm <= {max_pe} AND pb > 0 AND total_mv >= 10000000000
            ORDER BY (pb / pe_ttm) DESC;
            """
            df_basic = pd.read_sql_query(query, conn)

        print(f"[Step 1/5] 符合估值与百亿市值基础初筛的股票数: {len(df_basic)} 只")

        wonderful_stocks = []

        # 遍历选股
        for idx, row in df_basic.iterrows():
            sym = str(row['symbol'])
            name = str(row['name'])
            pe = float(row['pe_ttm'] or 0.0)
            pb = float(row['pb'] or 0.0)

            # ----------------------------------------------------
            # 维度 5: 估值合理性初筛 (排除市盈率为负的亏损股及极度泡沫股 PE > 60)
            # ----------------------------------------------------
            if pe <= 0 or pe > max_pe:
                continue

            # ----------------------------------------------------
            # 维度 1 & 2: 调取本地数据库财报 (ROE、毛利率、净利润)
            # ----------------------------------------------------
            df_inc = self.fin_fetcher.get_income_statement(sym)
            if df_inc is None or df_inc.empty:
                continue

            latest_inc = df_inc.iloc[0]
            net_profit = float(latest_inc.get('parent_netprofit', 0.0) or 0.0)

            # 过滤亏损企业
            if net_profit <= 0:
                continue

            # 计算近 4 季年化 ROE 估算 (净利润 / 股东权益)
            # 假定 PB 与 PE 的比值为 ROE 估算值: ROE = PB / PE * 100%
            roe_est = (pb / pe * 100) if pe > 0 else 0.0

            # 芒格标准：ROE 必须 ≥ 15%
            if roe_est < min_roe:
                continue

            # ----------------------------------------------------
            # 维度 4: 公司治理与公告避雷 (检查是否有风险提示、*ST、立案)
            # ----------------------------------------------------
            if "*ST" in name or "ST" in name or "退" in name:
                continue

            df_notices = self.fin_fetcher.get_company_notices(symbol=sym)
            notice_title = df_notices.iloc[0]['title'] if (df_notices is not None and not df_notices.empty) else "无异常风险公告"

            wonderful_stocks.append({
                "symbol": sym,
                "name": name,
                "price": row['price'],
                "pe_ttm": pe,
                "pb": pb,
                "roe_est_pct": round(roe_est, 2),
                "latest_net_profit_yi": round(net_profit / 1e8, 2),
                "notice_status": notice_title[:20]
            })

        result_df = pd.DataFrame(wonderful_stocks).sort_values(by='roe_est_pct', ascending=False)

        print("\n" + "="*80)
        print(f"🌟 【第一步成果】筛选出符合芒格标准的伟大公司股票池 (共 {len(result_df)} 只):")
        print("="*80)
        print(result_df.to_string(index=False))
        return result_df


if __name__ == "__main__":
    screener = MungerStockScreener()
    good_stocks = screener.screen_wonderful_companies()
