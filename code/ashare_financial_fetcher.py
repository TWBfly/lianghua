"""
A-Share Financial & Notice Database Caching Engine (财报与公告本地持久化缓存引擎)
设计理念：
1. 数据库优先 (DB-First)：每次请求时先查询本地 SQLite 数据库 ashare_quant.db。
2. 缓存命中 (Cache Hit)：若本地数据库已有历史财报/公告数据，直接毫秒级返回，0 次 API 接口调用。
3. 增量更新 (Incremental Sync)：若本地缺失或强制更新，才调用 API 获取并自动持久化写入数据库。
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime
import akshare as ak

DB_PATH = "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db"


class AShareFinancialFetcher:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db_tables()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db_tables(self):
        """初始化财报与公告数据库表结构与索引"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. 利润表缓存表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_income_statement (
                symbol TEXT,
                report_date TEXT,
                security_name TEXT,
                total_revenue REAL,
                parent_netprofit REAL,
                updated_at TEXT,
                PRIMARY KEY (symbol, report_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_income_sym_date ON stock_income_statement(symbol, report_date);")

            # 2. 公司公告缓存表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_notices (
                symbol TEXT,
                name TEXT,
                title TEXT,
                category TEXT,
                notice_date TEXT,
                updated_at TEXT,
                PRIMARY KEY (symbol, notice_date, title)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notice_sym_date ON stock_notices(symbol, notice_date);")

            # 3. 公司新闻与舆情缓存表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_news (
                symbol TEXT,
                title TEXT,
                publish_time TEXT,
                content TEXT,
                updated_at TEXT,
                PRIMARY KEY (symbol, publish_time, title)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_sym_time ON stock_news(symbol, publish_time);")

            conn.commit()

    # =========================================================================
    # 1. 财报利润表 (数据库优先 + API 补抓缓存)
    # =========================================================================
    def get_income_statement(self, symbol="600519", force_update=False, conn=None):
        """优先从数据库查利润表，若本地无记录或 force_update=True 则调用 API 并写入本地库"""
        clean_sym = str(symbol).replace("SH", "").replace("SZ", "").replace("BJ", "")

        if not force_update:
            db_conn = conn if conn is not None else self.get_connection()
            df_cached = pd.read_sql_query(
                "SELECT * FROM stock_income_statement "
                "WHERE symbol=? ORDER BY report_date DESC",
                db_conn,
                params=(clean_sym,),
            )
            if conn is None:
                db_conn.close()
            if not df_cached.empty:
                return df_cached
            if conn is not None:
                return df_cached
        elif conn is not None:
            return pd.DataFrame()

        # 本地数据库未命中，调用网络 API 抓取
        print(f"[API Fetch 🌐] 本地无 {clean_sym} 财报数据，正在调用网络 API 抓取...")
        formatted_sym = f"SH{clean_sym}" if clean_sym.startswith("6") else f"SZ{clean_sym}"

        try:
            df_api = ak.stock_profit_sheet_by_report_em(symbol=formatted_sym)
            if df_api is not None and not df_api.empty:
                records = []
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for idx, row in df_api.iterrows():
                    records.append({
                        'symbol': clean_sym,
                        'report_date': str(row.get('REPORT_DATE', '')),
                        'security_name': row.get('SECURITY_NAME_ABBR', clean_sym),
                        'total_revenue': float(row.get('TOTAL_OPERATE_INCOME', row.get('TOTAL_OPERATE_TURNOVER', 0.0)) or 0.0),
                        'parent_netprofit': float(row.get('PARENT_NETPROFIT', 0.0) or 0.0),
                        'updated_at': now_str
                    })

                df_to_save = pd.DataFrame(records)

                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    for item in records:
                        cursor.execute("""
                        INSERT OR REPLACE INTO stock_income_statement (symbol, report_date, security_name, total_revenue, parent_netprofit, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """, (item['symbol'], item['report_date'], item['security_name'], item['total_revenue'], item['parent_netprofit'], item['updated_at']))
                    conn.commit()

                print(f"[Cache Save 💾] 已将 {clean_sym} 的 {len(df_to_save)} 期利润表数据存入本地 SQLite 数据库。")
                return df_to_save
        except Exception as e:
            print(f"[Fetch Error] 抓取利润表失败: {e}")

        return None

    # =========================================================================
    # 2. 公司公告数据 (数据库优先 + API 补抓缓存)
    # =========================================================================
    def get_company_notices(self, symbol=None, category="全部",
                            force_update=False, conn=None):
        """优先从本地数据库查询公告，无数据时调用 API 并存库"""
        clean_sym = str(symbol).replace("SH", "").replace("SZ", "").replace("BJ", "") if symbol else None

        if not force_update:
            db_conn = conn if conn is not None else self.get_connection()
            query = "SELECT * FROM stock_notices"
            params = None
            if clean_sym:
                query += " WHERE symbol=?"
                params = (clean_sym,)
            query += " ORDER BY notice_date DESC"
            df_cached = pd.read_sql_query(query, db_conn, params=params)
            if conn is None:
                db_conn.close()
            if not df_cached.empty:
                print(f"[Cache Hit ⚡] 成功从本地数据库读取 {len(df_cached)} 条公司公告 (0 网络请求)")
                return df_cached
            if conn is not None:
                return df_cached
        elif conn is not None:
            return pd.DataFrame()

        print(f"[API Fetch 🌐] 本地无公告记录，正在从线上 API 拉取公告数据...")
        try:
            df_api = ak.stock_notice_report(symbol=category)
            if df_api is not None and not df_api.empty:
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                records = []
                for idx, row in df_api.iterrows():
                    records.append({
                        'symbol': str(row.get('代码', '')),
                        'name': str(row.get('名称', '')),
                        'title': str(row.get('公告标题', '')),
                        'category': str(row.get('公告类型', '')),
                        'notice_date': str(row.get('公告日期', '')),
                        'updated_at': now_str
                    })

                df_to_save = pd.DataFrame(records)

                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    for item in records:
                        cursor.execute("""
                        INSERT OR IGNORE INTO stock_notices (symbol, name, title, category, notice_date, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """, (item['symbol'], item['name'], item['title'], item['category'], item['notice_date'], item['updated_at']))
                    conn.commit()

                print(f"[Cache Save 💾] 已成功同步并缓存 {len(df_to_save)} 条公告数据到本地数据库。")

                if clean_sym:
                    with self.get_connection() as conn:
                        return pd.read_sql_query(
                            "SELECT * FROM stock_notices WHERE symbol=?",
                            conn,
                            params=(clean_sym,),
                        )
                return df_to_save

        except Exception as e:
            print(f"[Fetch Error] 抓取公告失败: {e}")

        return None


    # =========================================================================
    # 3. 瑞达利欧五维基本面硬核风控审计 (Multi-Factor Financial Quality Audit)
    # =========================================================================
    def audit_financial_quality(self, symbol="600519", conn=None):
        """Audit only fields actually stored in the local database."""
        clean_sym = str(symbol).replace("SH", "").replace("SZ", "").replace("BJ", "")
        db_conn = conn if conn is not None else self.get_connection()
        checks = {
            name: {"status": "UNKNOWN", "detail": "数据不可用"}
            for name in (
                "valuation",
                "reported_profit",
                "reported_revenue",
                "roe",
                "cash_flow",
                "leverage_goodwill",
                "profit_growth",
                "point_in_time",
            )
        }

        def result(status="UNKNOWN", latest_profit_yi=None):
            return {
                "status": status,
                "is_passed": status == "PASS",
                "quality_score": None,
                "cfo_ratio": None,
                "roe_est": None,
                "latest_profit_yi": latest_profit_yi,
                "checks": checks,
                "reasons": [
                    f"{name}: {check['status']} - {check['detail']}"
                    for name, check in checks.items()
                ],
                "badge": (
                    "基本面存在已确认风险"
                    if status == "FAIL" else "基本面数据不足"
                ),
            }

        try:
            p_df = pd.read_sql_query(
                "SELECT name, price, pe_ttm, pb, total_mv "
                "FROM stock_basic WHERE symbol=?",
                db_conn,
                params=(clean_sym,),
            )
            if p_df.empty:
                return result()

            row = p_df.iloc[0]
            pe = row.get('pe_ttm')
            pb = row.get('pb')
            if pd.isna(pe) or pd.isna(pb):
                checks["valuation"]["detail"] = "PE 或 PB 缺失"
            elif float(pe) > 0 and float(pe) <= 60 and float(pb) > 0:
                checks["valuation"] = {
                    "status": "PASS",
                    "detail": f"PE={float(pe):.2f}, PB={float(pb):.2f}",
                }
            else:
                checks["valuation"] = {
                    "status": "FAIL",
                    "detail": f"PE={float(pe):.2f}, PB={float(pb):.2f}",
                }

            inc_df = self.get_income_statement(clean_sym, conn=db_conn)
            latest_profit_yi = None
            if inc_df is not None and not inc_df.empty:
                latest = inc_df.iloc[0]
                profit = latest.get("parent_netprofit")
                revenue = latest.get("total_revenue")
                if not pd.isna(profit):
                    profit = float(profit)
                    latest_profit_yi = round(profit / 1e8, 2)
                    checks["reported_profit"] = {
                        "status": "PASS" if profit > 0 else "FAIL",
                        "detail": f"归母净利润={profit:.2f}",
                    }
                if not pd.isna(revenue):
                    revenue = float(revenue)
                    checks["reported_revenue"] = {
                        "status": "PASS" if revenue > 0 else "FAIL",
                        "detail": f"营业收入={revenue:.2f}",
                    }

            statuses = {check["status"] for check in checks.values()}
            status = (
                "FAIL" if "FAIL" in statuses
                else "UNKNOWN" if "UNKNOWN" in statuses
                else "PASS"
            )
            return result(status, latest_profit_yi)
        except Exception as exc:
            checks["point_in_time"]["detail"] = f"数据库读取失败: {exc}"
            return result()
        finally:
            if conn is None:
                db_conn.close()


if __name__ == "__main__":
    engine = AShareFinancialFetcher()

    print("--- 第一次调用 (本地无数据，触发网络 API 抓取并自动入库) ---")
    df1 = engine.get_income_statement("600519", force_update=True)

    print("\n--- 第二次调用 (触发本地数据库缓存命中 Cache Hit，0 秒连接 API) ---")
    df2 = engine.get_income_statement("600519")

    print("\n--- 公告数据测试 (走数据库缓存 ⚡) ---")
    n1 = engine.get_company_notices(category="风险提示")
