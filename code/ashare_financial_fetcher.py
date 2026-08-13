"""
A-Share Financial & Notice Database Caching Engine (财报与公告本地持久化缓存引擎)
设计理念：
1. 数据库优先 (DB-First)：每次请求时先查询本地 SQLite 数据库 ashare_quant.db。
2. 缓存命中 (Cache Hit)：若本地数据库已有历史财报/公告数据，直接毫秒级返回，0 次 API 接口调用。
3. 增量更新 (Incremental Sync)：若本地缺失或强制更新，才调用 API 获取并自动持久化写入数据库。
"""

import os
import time
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

            # 2. 资产负债表缓存表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_balance_sheet (
                symbol TEXT,
                report_date TEXT,
                security_name TEXT,
                total_assets REAL,
                total_liabilities REAL,
                goodwill REAL,
                monetary_funds REAL,
                updated_at TEXT,
                PRIMARY KEY (symbol, report_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bal_sym_date ON stock_balance_sheet(symbol, report_date);")

            # 3. 现金流量表缓存表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_cash_flow (
                symbol TEXT,
                report_date TEXT,
                security_name TEXT,
                operating_cash_flow REAL,
                investment_cash_flow REAL,
                financing_cash_flow REAL,
                updated_at TEXT,
                PRIMARY KEY (symbol, report_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cf_sym_date ON stock_cash_flow(symbol, report_date);")

            # 4. 财务指标表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_financial_indicators (
                symbol TEXT,
                report_date TEXT,
                eps REAL,
                roe REAL,
                bps REAL,
                cfo_per_share REAL,
                gross_margin REAL,
                net_profit_growth REAL,
                revenue_growth REAL,
                updated_at TEXT,
                PRIMARY KEY (symbol, report_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ind_sym_date ON stock_financial_indicators(symbol, report_date);")

            # 5. 公司公告缓存表
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

            # 6. 公司新闻与舆情缓存表

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

    def sync_income_statements(self, symbols=None, force_update=False):
        """批量同步并本地化存储指定股票（或已选优秀公司）的财报利润表数据"""
        if symbols is None:
            with self.get_connection() as conn:
                df_basic = pd.read_sql_query("SELECT symbol FROM stock_basic", conn)
                symbols = df_basic['symbol'].tolist()

        symbols = [str(sym).replace("SH", "").replace("SZ", "").replace("BJ", "") for sym in symbols]
        total = len(symbols)
        print(f"[Sync] 开始批量同步 {total} 只股票的财报利润表...")

        committed, unchanged, failed = [], [], []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            for i, sym in enumerate(symbols, 1):
                try:
                    if not force_update:
                        existing = conn.execute(
                            "SELECT COUNT(*) FROM stock_income_statement WHERE symbol=?",
                            (sym,)
                        ).fetchone()[0]
                        if existing > 0:
                            unchanged.append(sym)
                            continue

                    formatted_sym = f"SH{sym}" if sym.startswith("6") else f"SZ{sym}"
                    df_api = ak.stock_profit_sheet_by_report_em(symbol=formatted_sym)
                    if df_api is not None and not df_api.empty:
                        cursor = conn.cursor()
                        for _, row in df_api.iterrows():
                            cursor.execute("""
                            INSERT OR REPLACE INTO stock_income_statement 
                            (symbol, report_date, security_name, total_revenue, parent_netprofit, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?);
                            """, (
                                sym,
                                str(row.get('REPORT_DATE', '')),
                                row.get('SECURITY_NAME_ABBR', sym),
                                float(row.get('TOTAL_OPERATE_INCOME', row.get('TOTAL_OPERATE_TURNOVER', 0.0)) or 0.0),
                                float(row.get('PARENT_NETPROFIT', 0.0) or 0.0),
                                now_str
                            ))
                        conn.commit()
                        committed.append(sym)
                    else:
                        failed.append({"symbol": sym, "error": "API 返回空数据"})
                except Exception as e:
                    failed.append({"symbol": sym, "error": str(e)})

                if i % 50 == 0 or i == total:
                    print(f"   ├─ 财报利润表进度: [{i}/{total}] (已入库: {len(committed)}, 本地已有: {len(unchanged)}, 失败: {len(failed)})")

        print(f"[Sync] 财报利润表同步结束！提交新入库: {len(committed)}, 本地未变: {len(unchanged)}, 失败/空: {len(failed)}")
        return {"committed": committed, "unchanged": unchanged, "failed": failed}

    def sync_balance_sheets(self, symbols=None, force_update=False):
        """批量同步并本地化存储指定股票的资产负债表"""
        if symbols is None:
            with self.get_connection() as conn:
                symbols = pd.read_sql_query("SELECT symbol FROM stock_basic", conn)['symbol'].tolist()
        symbols = [str(sym).replace("SH", "").replace("SZ", "").replace("BJ", "") for sym in symbols]
        total = len(symbols)
        committed, unchanged, failed = [], [], []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            for i, sym in enumerate(symbols, 1):
                try:
                    if not force_update:
                        existing = conn.execute("SELECT COUNT(*) FROM stock_balance_sheet WHERE symbol=?", (sym,)).fetchone()[0]
                        if existing > 0:
                            unchanged.append(sym)
                            continue

                    formatted_sym = f"SH{sym}" if sym.startswith("6") else f"SZ{sym}"
                    df_api = ak.stock_balance_sheet_by_report_em(symbol=formatted_sym)
                    if df_api is not None and not df_api.empty:
                        cursor = conn.cursor()
                        for _, row in df_api.iterrows():
                            cursor.execute("""
                            INSERT OR REPLACE INTO stock_balance_sheet 
                            (symbol, report_date, security_name, total_assets, total_liabilities, goodwill, monetary_funds, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                sym,
                                str(row.get('REPORT_DATE', '')),
                                row.get('SECURITY_NAME_ABBR', sym),
                                float(row.get('TOTAL_ASSETS', 0.0) or 0.0),
                                float(row.get('TOTAL_LIABILITIES', 0.0) or 0.0),
                                float(row.get('GOODWILL', 0.0) or 0.0),
                                float(row.get('MONETARYFUNDS', 0.0) or 0.0),
                                now_str
                            ))
                        conn.commit()
                        committed.append(sym)
                    else:
                        failed.append({"symbol": sym, "error": "API 返回空数据"})
                except Exception as e:
                    failed.append({"symbol": sym, "error": str(e)})

                if i % 50 == 0 or i == total:
                    print(f"   ├─ 资产负债表进度: [{i}/{total}] (已入库: {len(committed)}, 本地已有: {len(unchanged)}, 失败: {len(failed)})")

        return {"committed": committed, "unchanged": unchanged, "failed": failed}

    def sync_cash_flows(self, symbols=None, force_update=False):
        """批量同步并本地化存储指定股票的现金流量表"""
        if symbols is None:
            with self.get_connection() as conn:
                symbols = pd.read_sql_query("SELECT symbol FROM stock_basic", conn)['symbol'].tolist()
        symbols = [str(sym).replace("SH", "").replace("SZ", "").replace("BJ", "") for sym in symbols]
        total = len(symbols)
        committed, unchanged, failed = [], [], []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            for i, sym in enumerate(symbols, 1):
                try:
                    if not force_update:
                        existing = conn.execute("SELECT COUNT(*) FROM stock_cash_flow WHERE symbol=?", (sym,)).fetchone()[0]
                        if existing > 0:
                            unchanged.append(sym)
                            continue

                    formatted_sym = f"SH{sym}" if sym.startswith("6") else f"SZ{sym}"
                    df_api = ak.stock_cash_flow_sheet_by_report_em(symbol=formatted_sym)
                    if df_api is not None and not df_api.empty:
                        cursor = conn.cursor()
                        for _, row in df_api.iterrows():
                            cursor.execute("""
                            INSERT OR REPLACE INTO stock_cash_flow 
                            (symbol, report_date, security_name, operating_cash_flow, investment_cash_flow, financing_cash_flow, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?);
                            """, (
                                sym,
                                str(row.get('REPORT_DATE', '')),
                                row.get('SECURITY_NAME_ABBR', sym),
                                float(row.get('NETCASH_OPERATE', 0.0) or 0.0),
                                float(row.get('NETCASH_INVEST', 0.0) or 0.0),
                                float(row.get('NETCASH_FINANCE', 0.0) or 0.0),
                                now_str
                            ))
                        conn.commit()
                        committed.append(sym)
                    else:
                        failed.append({"symbol": sym, "error": "API 返回空数据"})
                except Exception as e:
                    failed.append({"symbol": sym, "error": str(e)})

                if i % 50 == 0 or i == total:
                    print(f"   ├─ 现金流量表进度: [{i}/{total}] (已入库: {len(committed)}, 本地已有: {len(unchanged)}, 失败: {len(failed)})")

        return {"committed": committed, "unchanged": unchanged, "failed": failed}

    def sync_all_financial_reports(self, symbols=None, force_update=False):
        """一键全量同步指定股票的三大财报（利润表 + 资产负债表 + 现金流量表）"""
        print(f"\n[Sync 📊] 开始一键同步四大财报与指标表...")
        r1 = self.sync_income_statements(symbols=symbols, force_update=force_update)
        r2 = self.sync_balance_sheets(symbols=symbols, force_update=force_update)
        r3 = self.sync_cash_flows(symbols=symbols, force_update=force_update)
        return {"income": r1, "balance": r2, "cash_flow": r3}


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

        def result(status="UNKNOWN", latest_profit_yi=None, roe_est=None, cfo_ratio=None):
            return {
                "status": status,
                "is_passed": status == "PASS",
                "quality_score": None,
                "cfo_ratio": cfo_ratio,
                "roe_est": roe_est,
                "latest_profit_yi": latest_profit_yi,
                "checks": checks,
                "reasons": [
                    f"{name}: {check['status']} - {check['detail']}"
                    for name, check in checks.items()
                ],
                "badge": (
                    "基本面存在已确认风险"
                    if status == "FAIL" else "基本面数据不足" if status == "UNKNOWN" else "基本面优良"
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
                rep_date = latest.get("report_date")



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

                latest_date_str = str(rep_date or '')
                same_period_rows = [
                    row for idx, row in inc_df.iloc[1:].iterrows()
                    if str(row.get('report_date', ''))[5:10] == latest_date_str[5:10]
                ]
                if same_period_rows:
                    prev_profit = float(same_period_rows[0].get("parent_netprofit") or 0.0)
                    if profit >= prev_profit:
                        checks["profit_growth"] = {
                            "status": "PASS",
                            "detail": f"净利润同比增长 ({profit/1e8:.2f}亿 vs 同期{prev_profit/1e8:.2f}亿)",
                        }
                    else:
                        checks["profit_growth"] = {
                            "status": "FAIL",
                            "detail": f"净利润同比下降 ({profit/1e8:.2f}亿 vs 同期{prev_profit/1e8:.2f}亿)",
                        }
                elif len(inc_df) >= 2:
                    checks["profit_growth"] = {
                        "status": "PASS" if profit > 0 else "FAIL",
                        "detail": f"当期净利润={profit/1e8:.2f}亿",
                    }

            # 资产负债表审计
            bal_df = pd.read_sql_query(
                "SELECT * FROM stock_balance_sheet WHERE symbol=? ORDER BY report_date DESC",
                db_conn,
                params=(clean_sym,),
            )
            roe_est = None
            if not bal_df.empty:
                b_latest = bal_df.iloc[0]
                t_assets = float(b_latest.get("total_assets") or 0.0)
                t_liab = float(b_latest.get("total_liabilities") or 0.0)
                goodwill = float(b_latest.get("goodwill") or 0.0)
                equity = t_assets - t_liab

                if t_assets > 0:
                    debt_ratio = t_liab / t_assets
                    gw_ratio = goodwill / t_assets
                    if debt_ratio < 0.85 and gw_ratio < 0.20:
                        checks["leverage_goodwill"] = {
                            "status": "PASS",
                            "detail": f"负债率={debt_ratio:.1%}, 商誉占比={gw_ratio:.1%}",
                        }
                    else:
                        checks["leverage_goodwill"] = {
                            "status": "FAIL",
                            "detail": f"负债率={debt_ratio:.1%}, 商誉占比={gw_ratio:.1%}",
                        }

                if equity > 0 and latest_profit_yi is not None and latest_profit_yi > 0:
                    latest_date_str = str(inc_df.iloc[0].get('report_date', '')) if inc_df is not None and not inc_df.empty else ''
                    month_str = latest_date_str[5:7]
                    annual_multiplier = 4.0 if month_str == '03' else 2.0 if month_str == '06' else (4.0/3.0) if month_str == '09' else 1.0
                    annualized_profit = (latest_profit_yi * 1e8) * annual_multiplier
                    roe_est = round((annualized_profit / equity) * 100.0, 2)
                    checks["roe"] = {
                        "status": "PASS" if roe_est >= 10.0 else "FAIL",
                        "detail": f"年化 ROE={roe_est:.2f}% (最新期ROE={((latest_profit_yi*1e8)/equity*100.0):.2f}%)",
                    }

            # 现金流量表审计
            cf_df = pd.read_sql_query(
                "SELECT * FROM stock_cash_flow WHERE symbol=? ORDER BY report_date DESC",
                db_conn,
                params=(clean_sym,),
            )
            cfo_ratio = None
            if not cf_df.empty:
                cf_latest = cf_df.iloc[0]
                cfo = float(cf_latest.get("operating_cash_flow") or 0.0)
                if latest_profit_yi and latest_profit_yi > 0:
                    cfo_ratio = round(cfo / (latest_profit_yi * 1e8), 2)
                    checks["cash_flow"] = {
                        "status": "PASS" if cfo > 0 and cfo_ratio >= 0.5 else "FAIL",
                        "detail": f"经营现金流={cfo/1e8:.2f}亿, CFO/净利润={cfo_ratio:.2f}",
                    }

            if checks["roe"]["status"] != "UNKNOWN" and checks["cash_flow"]["status"] != "UNKNOWN":
                rep_date = inc_df.iloc[0].get("report_date") if inc_df is not None and not inc_df.empty else None
                if rep_date:
                    checks["point_in_time"] = {
                        "status": "PASS",
                        "detail": f"最新财报报告期={rep_date}",
                    }


            statuses = {check["status"] for check in checks.values()}
            status = (
                "FAIL" if "FAIL" in statuses
                else "UNKNOWN" if "UNKNOWN" in statuses
                else "PASS"
            )
            return result(status, latest_profit_yi, roe_est, cfo_ratio)

        except Exception as exc:
            checks["point_in_time"]["detail"] = f"数据库读取失败: {exc}"
            return result()
        finally:
            if conn is None:
                db_conn.close()

    def sync_financial_indicators(self, symbols=None, force_update=False):
        """批量同步并本地化存储指定股票的财务指标表 (stock_financial_indicators)"""
        if symbols is None:
            with self.get_connection() as conn:
                symbols = pd.read_sql_query("SELECT symbol FROM stock_basic", conn)['symbol'].tolist()
        symbols = [str(sym).replace("SH", "").replace("SZ", "").replace("BJ", "") for sym in symbols]
        total = len(symbols)
        committed, unchanged, failed = [], [], []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            for i, sym in enumerate(symbols, 1):
                try:
                    if not force_update:
                        existing = conn.execute(
                            "SELECT COUNT(*) FROM stock_financial_indicators WHERE symbol=?",
                            (sym,)
                        ).fetchone()[0]
                        if existing > 0:
                            unchanged.append(sym)
                            continue

                    df_api = None
                    try:
                        df_api = ak.stock_financial_analysis_indicator(symbol=sym)
                    except Exception:
                        pass
                    if df_api is not None and not df_api.empty:
                        cursor = conn.cursor()
                        for _, row in df_api.iterrows():
                            report_date = str(row.get('日期', row.get('REPORT_DATE', '')))
                            if not report_date:
                                continue
                            cursor.execute("""
                            INSERT OR REPLACE INTO stock_financial_indicators 
                            (symbol, report_date, eps, roe, bps, cfo_per_share, gross_margin, net_profit_growth, revenue_growth, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                sym,
                                report_date,
                                float(row.get('摊薄每股收益(元)', row.get('EPS', 0.0)) or 0.0),
                                float(row.get('净资产收益率(%)', row.get('ROE', 0.0)) or 0.0),
                                float(row.get('每股净资产(元)', row.get('BPS', 0.0)) or 0.0),
                                float(row.get('每股经营现金流(元)', row.get('CFO_PER_SHARE', 0.0)) or 0.0),
                                float(row.get('销售毛利率(%)', row.get('GROSS_MARGIN', 0.0)) or 0.0),
                                float(row.get('净利润同比增长率(%)', row.get('NET_PROFIT_GROWTH', 0.0)) or 0.0),
                                float(row.get('主营业务收入同比增长率(%)', row.get('REVENUE_GROWTH', 0.0)) or 0.0),
                                now_str
                            ))
                        conn.commit()
                        committed.append(sym)
                    else:
                        failed.append({"symbol": sym, "error": "API 返回空数据"})
                except Exception as e:
                    failed.append({"symbol": sym, "error": str(e)})

                time.sleep(0.1)
                if i % 50 == 0 or i == total:
                    print(f"   ├─ 财务指标表进度: [{i}/{total}] (已入库: {len(committed)}, 本地已有: {len(unchanged)}, 失败: {len(failed)})")

        return {"committed": committed, "unchanged": unchanged, "failed": failed}


if __name__ == "__main__":
    engine = AShareFinancialFetcher()

    print("--- 第一次调用 (本地无数据，触发网络 API 抓取并自动入库) ---")
    df1 = engine.get_income_statement("600519", force_update=True)

    print("\n--- 第二次调用 (触发本地数据库缓存命中 Cache Hit，0 秒连接 API) ---")
    df2 = engine.get_income_statement("600519")

    print("\n--- 公告数据测试 (走数据库缓存 ⚡) ---")
    n1 = engine.get_company_notices(category="风险提示")
