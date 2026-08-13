"""
A-Share Excellent Companies Data Localizer (优质公司数据本地化落盘引擎)
功能：
1. 刷新全市场股票估值快照 (stock_basic)。
2. 根据精准规则筛选优质公司：
   - 过滤 PE <= 0 (剔除亏损企业)
   - 过滤 PE 过高 (pe_ttm <= max_pe，默认 50)
   - 过滤 PB <= 0
   - 过滤 ST / *ST / 退市公司
   - 市值门槛 (total_mv >= min_mv，默认 100 亿)
3. 本地化持久化存储优质公司的全部核心数据：
   - 个股历史 K 线行情 (stock_daily)
   - 财报利润表 (stock_income_statement)
"""

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from ashare_data_engine import AShareDataEngine, DB_PATH
from ashare_financial_fetcher import AShareFinancialFetcher


class ExcellentCompaniesLocalizer:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.data_engine = AShareDataEngine(db_path=db_path)
        self.fin_fetcher = AShareFinancialFetcher(db_path=db_path)

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def screen_excellent_companies(self, max_pe=50.0, min_mv=10_000_000_000):
        """
        严苛筛选优质公司：
        1. PE > 0 且 PE <= max_pe
        2. PB > 0
        3. 剔除所有 ST、*ST 和退市公司
        4. 市值 >= min_mv
        """
        print(f"\n[Screen 🔍] 正在按规则筛选优质公司 (0 < PE <= {max_pe}, 市值 >= {min_mv/1e8:.0f}亿, 非 ST)...")
        with self.get_connection() as conn:
            query = """
            SELECT symbol, name, price, pe_ttm, pb, total_mv, circ_mv 
            FROM stock_basic 
            WHERE pe_ttm > 0 AND pe_ttm <= ? AND pb > 0
                  AND total_mv >= ?
                  AND UPPER(name) NOT LIKE '%ST%'
                  AND name NOT LIKE '%退%'
            ORDER BY total_mv DESC
            """
            df_excellent = pd.read_sql_query(query, conn, params=(max_pe, min_mv))
        print(f"[Screen ✅] 成功筛选出 {len(df_excellent)} 只符合条件的优秀标的公司。")
        return df_excellent

    def sync_all(self, max_pe=50.0, min_mv=10_000_000_000, start_date="20220101", force_update=False):
        """执行完整数据本地化落盘流水线"""
        print("=" * 80)
        print("🚀 启动【优质公司数据本地化落盘】流程...")
        print("=" * 80)

        # 1. 刷新股票基本表
        self.data_engine.sync_stock_basic()

        # 2. 筛选优质公司
        df_excellent = self.screen_excellent_companies(max_pe=max_pe, min_mv=min_mv)
        if df_excellent.empty:
            print("[Stop] 未筛选到符合条件的股票。")
            return

        symbols = df_excellent['symbol'].tolist()

        # 3. 本地化存储 K 线行情数据 (stock_daily)
        print(f"\n[Step 1/2 📈] 正在落盘 {len(symbols)} 只优质公司的日线 K 线行情 ({start_date} 起)...")
        daily_res = self.data_engine.sync_stock_daily(symbols=symbols, start_date=start_date)

        # 4. 本地化存储三大财报 (利润表 + 资产负债表 + 现金流量表)
        print(f"\n[Step 2/2 📊] 正在落盘 {len(symbols)} 只优质公司的四大财报数据...")
        inc_res = self.fin_fetcher.sync_all_financial_reports(symbols=symbols, force_update=force_update)

        # 5. 校验与诊断报告
        self.audit_localization_status(symbols)

    def audit_localization_status(self, symbols):
        """审计落盘后的本地数据完整度"""
        print("\n" + "=" * 80)
        print("📊 优质公司数据本地化审计报告:")
        print("=" * 80)

        with self.get_connection() as conn:
            placeholder = ','.join(['?'] * len(symbols))
            df_daily_counts = pd.read_sql_query(f"SELECT symbol, COUNT(*) as count FROM stock_daily WHERE symbol IN ({placeholder}) GROUP BY symbol", conn, params=symbols)
            df_inc_counts = pd.read_sql_query(f"SELECT symbol, COUNT(*) as count FROM stock_income_statement WHERE symbol IN ({placeholder}) GROUP BY symbol", conn, params=symbols)
            df_bal_counts = pd.read_sql_query(f"SELECT symbol, COUNT(*) as count FROM stock_balance_sheet WHERE symbol IN ({placeholder}) GROUP BY symbol", conn, params=symbols)
            df_cf_counts = pd.read_sql_query(f"SELECT symbol, COUNT(*) as count FROM stock_cash_flow WHERE symbol IN ({placeholder}) GROUP BY symbol", conn, params=symbols)

        has_daily = len(df_daily_counts)
        has_inc = len(df_inc_counts)
        has_bal = len(df_bal_counts)
        has_cf = len(df_cf_counts)
        total = len(symbols)

        print(f"目标优质公司总数: {total} 只")
        print(f" - 本地完整拥有 K 线行情: {has_daily} / {total} (覆盖率: {has_daily/total:.1%})")
        print(f" - 本地完整拥有利润表数据: {has_inc} / {total} (覆盖率: {has_inc/total:.1%})")
        print(f" - 本地完整拥有资产负债表: {has_bal} / {total} (覆盖率: {has_bal/total:.1%})")
        print(f" - 本地完整拥有现金流量表: {has_cf} / {total} (覆盖率: {has_cf/total:.1%})")
        print("=" * 80)



if __name__ == "__main__":
    localizer = ExcellentCompaniesLocalizer()
    localizer.sync_all(max_pe=50.0, min_mv=10_000_000_000, start_date="20220101")
