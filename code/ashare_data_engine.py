"""
A-Share Data Engine & Local SQLite Database Manager
针对 AI (机器学习/深度学习/深度强化学习/大模型因子) 打造的 A 股量化数据引擎
数据源: AKShare (公开免费API)
数据库: SQLite3 (/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db)
"""

import os
import time
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import akshare as ak

from market_data import MarketDataError, validate_daily_bars

# 数据库文件保存路径
DB_DIR = "/Users/tang/PycharmProjects/pythonProject/lianghua/data"
DB_PATH = os.path.join(DB_DIR, "ashare_quant.db")


class AShareDataEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """初始化数据库表结构与索引"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 股票元数据表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_basic (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                pe_ttm REAL,
                pb REAL,
                total_mv REAL,
                circ_mv REAL,
                updated_at TEXT
            );
            """)

            # 2. 个股历史日线表 (前复权)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                symbol TEXT,
                trade_date TEXT,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                amplitude REAL,
                pct_chg REAL,
                change_amount REAL,
                turnover_rate REAL,
                PRIMARY KEY (symbol, trade_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_date ON stock_daily(symbol, trade_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily(trade_date);")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily_catalog (
                symbol TEXT PRIMARY KEY,
                price_mode TEXT NOT NULL,
                source TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 3. 大盘指数日线表 (沪深300, 中证500, 上证指数等)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_daily (
                index_code TEXT,
                trade_date TEXT,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                pct_chg REAL,
                PRIMARY KEY (index_code, trade_date)
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_index_daily_code_date ON index_daily(index_code, trade_date);")

            conn.commit()
            print(f"[DB] 数据库已就绪: {self.db_path}")

    def sync_stock_basic(self):
        """同步 A 股全市场股票基础信息与实时估值"""
        print("[Sync] 正在获取 A 股全市场股票列表与实时估值...")
        try:
            df = ak.stock_zh_a_spot_em()
            # 字段映射
            rename_map = {
                '代码': 'symbol',
                '名称': 'name',
                '最新价': 'price',
                '市盈率-动态': 'pe_ttm',
                '市净率': 'pb',
                '总市值': 'total_mv',
                '流通市值': 'circ_mv'
            }
            df_clean = df[list(rename_map.keys())].rename(columns=rename_map)
            df_clean['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with self.get_connection() as conn:
                df_clean.to_sql('stock_basic', conn, if_exists='replace', index=False)
            print(f"[Sync] 成功同步 {len(df_clean)} 只 A 股基本信息到数据库。")
            return df_clean
        except Exception as e:
            print(f"[Sync Error] 获取股票列表失败: {e}")
            return None

    def sync_index_daily(self, index_codes=None, start_date="20200101"):
        """同步基准指数数据 (沪深300、中证500、上证指数、创业板指等)"""
        if index_codes is None:
            index_codes = {
                "000001": "sh000001",  # 上证指数
                "399001": "sz399001",  # 深证成指
                "000300": "sh000300",  # 沪深300
                "000905": "sh000905",  # 中证500
                "399006": "sz399006",  # 创业板指
            }

        print("[Sync] 开始同步基准大盘指数数据...")
        for name_code, query_code in index_codes.items():
            try:
                # 获取数据库中该指数的最大交易日
                latest_date = self.get_latest_date('index_daily', 'trade_date', f"index_code='{name_code}'")
                s_date = (datetime.strptime(latest_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y%m%d') if latest_date else start_date
                
                today_str = datetime.now().strftime('%Y%m%d')
                if s_date > today_str:
                    print(f"   └─ 指数 {name_code} 已是最新数据 ({latest_date})")
                    continue

                df_idx = ak.stock_zh_index_daily_em(symbol=query_code, start_date=s_date, end_date=today_str)
                if df_idx is not None and not df_idx.empty:
                    df_idx['index_code'] = name_code
                    rename_map = {
                        'date': 'trade_date',
                        'open': 'open',
                        'close': 'close',
                        'high': 'high',
                        'low': 'low',
                        'volume': 'volume',
                        'amount': 'amount',
                    }
                    df_clean = df_idx.rename(columns=rename_map)
                    df_clean['pct_chg'] = df_clean['close'].pct_change() * 100
                    df_clean = df_clean[['index_code', 'trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'pct_chg']]

                    with self.get_connection() as conn:
                        df_clean.to_sql('index_daily', conn, if_exists='append', index=False)
                    print(f"   └─ 指数 {name_code} 成功更新 {len(df_clean)} 条记录 ({s_date} -> {today_str})")
            except Exception as e:
                print(f"   └─ 指数 {name_code} 更新失败: {e}")

    def sync_stock_daily(self, symbols=None, start_date="20200101", end_date=None, batch_size=50):
        """
        同步个股日线历史数据 (前复权 qfq)
        symbols: 股票代码列表，若为 None 则默认更新全市场或主要沪深300/中证500成分股
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        if symbols is None:
            # 默认抓取前 300 只市值最大的优质标的或全部
            with self.get_connection() as conn:
                df_basic = pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC", conn)
                if df_basic.empty:
                    self.sync_stock_basic()
                    df_basic = pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC", conn)
                symbols = df_basic['symbol'].tolist()

        print(f"[Sync] 开始同步 {len(symbols)} 只股票的日线行情数据 ({start_date} 至 {end_date})...")

        total = len(symbols)
        success_count = 0
        
        for i, sym in enumerate(symbols, 1):
            try:
                with self.get_connection() as conn:
                    existing_dates = {
                        row[0] for row in conn.execute(
                        "SELECT trade_date FROM stock_daily WHERE symbol=?",
                        (sym,),
                    )}
                earliest_date = min(existing_dates, default=None)
                latest_date = max(existing_dates, default=None)
                requested_start = start_date.replace('-', '')
                requested_end = end_date.replace('-', '')
                if (
                    latest_date
                    and latest_date.replace('-', '') >= requested_end
                    and earliest_date
                    and earliest_date.replace('-', '') <= requested_start
                ):
                    success_count += 1
                    continue
                refresh_start = min(
                    requested_start,
                    earliest_date.replace('-', '')
                    if earliest_date else requested_start,
                )
                refresh_end = max(
                    requested_end,
                    latest_date.replace('-', '')
                    if latest_date else requested_end,
                )

                # ponytail: qfq history is mutable; refresh the symbol until
                # adjustment factors are stored separately.
                df_hist = ak.stock_zh_a_hist(
                    symbol=sym,
                    period="daily",
                    start_date=refresh_start,
                    end_date=refresh_end,
                    adjust="qfq"
                )

                if df_hist is not None and not df_hist.empty:
                    rename_map = {
                        '股票代码': 'symbol',
                        '日期': 'trade_date',
                        '开盘': 'open',
                        '收盘': 'close',
                        '最高': 'high',
                        '最低': 'low',
                        '成交量': 'volume',
                        '成交额': 'amount',
                        '振幅': 'amplitude',
                        '涨跌幅': 'pct_chg',
                        '涨跌额': 'change_amount',
                        '换手率': 'turnover_rate'
                    }
                    df_clean = df_hist.rename(columns=rename_map)
                    df_clean['symbol'] = sym
                    cols = ['symbol', 'trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'pct_chg', 'change_amount', 'turnover_rate']
                    df_clean = df_clean[cols]
                    df_clean['trade_date'] = pd.to_datetime(
                        df_clean['trade_date']
                    )
                    df_clean = validate_daily_bars(df_clean, sym)
                    df_clean['trade_date'] = df_clean[
                        'trade_date'
                    ].dt.strftime('%Y-%m-%d')
                    returned_dates = set(df_clean['trade_date'])
                    missing_existing = sorted(
                        existing_dates - returned_dates
                    )
                    if missing_existing:
                        raise MarketDataError(
                            f"{sym} 前复权刷新数据不完整: "
                            f"缺少现有交易日 {missing_existing[0]} "
                            f"等 {len(missing_existing)} 天"
                        )
                    rows = [
                        tuple(
                            value.item()
                            if hasattr(value, 'item') else value
                            for value in row
                        )
                        for row in df_clean.itertuples(
                            index=False, name=None
                        )
                    ]

                    with self.get_connection() as conn:
                        conn.execute(
                            "DELETE FROM stock_daily WHERE symbol=?",
                            (sym,),
                        )
                        conn.executemany(
                            "INSERT INTO stock_daily VALUES "
                            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            rows,
                        )
                        conn.execute("""
                            INSERT INTO stock_daily_catalog (
                                symbol, price_mode, source, start_date,
                                end_date, row_count, updated_at
                            ) VALUES (
                                ?, 'QFQ', 'AKSHARE_STOCK_ZH_A_HIST',
                                ?, ?, ?, CURRENT_TIMESTAMP
                            )
                            ON CONFLICT(symbol) DO UPDATE SET
                                price_mode=excluded.price_mode,
                                source=excluded.source,
                                start_date=excluded.start_date,
                                end_date=excluded.end_date,
                                row_count=excluded.row_count,
                                updated_at=CURRENT_TIMESTAMP
                        """, (
                            sym,
                            df_clean['trade_date'].min(),
                            df_clean['trade_date'].max(),
                            len(df_clean),
                        ))

                success_count += 1
                if i % 20 == 0 or i == total:
                    print(f"   ├─ 进度: [{i}/{total}] (已成功: {success_count}) 当前处理: {sym}")

                # 避免频繁请求 API 限制
                time.sleep(0.05)

            except Exception as e:
                print(f"   └─ 股票 {sym} 同步失败: {e}")

        print(f"[Sync] 股票日线数据同步结束！成功率: {success_count}/{total}")

    def get_stock_daily_provenance(self, symbol):
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT symbol, price_mode, source, start_date, end_date,
                       row_count, updated_at
                FROM stock_daily_catalog WHERE symbol=?
            """, (str(symbol),)).fetchone()
        if row is None:
            return None
        keys = (
            'symbol', 'price_mode', 'source', 'start_date', 'end_date',
            'row_count', 'updated_at',
        )
        return dict(zip(keys, row))

    def get_latest_date(self, table_name, date_col, condition=None):
        """查询指定表记录的最新日期"""
        where_clause = f"WHERE {condition}" if condition else ""
        query = f"SELECT MAX({date_col}) FROM {table_name} {where_clause};"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            res = cursor.fetchone()
            return res[0] if res and res[0] else None

    def load_stock_data(self, symbol, start_date=None, end_date=None):
        """为 ML / DL / DRL 模型导出清洗好的 Pandas DataFrame"""
        where_clauses = [f"symbol = '{symbol}'"]
        if start_date:
            where_clauses.append(f"trade_date >= '{start_date}'")
        if end_date:
            where_clauses.append(f"trade_date <= '{end_date}'")
            
        where_str = " AND ".join(where_clauses)
        query = f"SELECT * FROM stock_daily WHERE {where_str} ORDER BY trade_date ASC;"
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn)
            
        if df.empty:
            return df

        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        return df


if __name__ == "__main__":
    engine = AShareDataEngine()
    
    # 1. 同步股票基本信息列表
    engine.sync_stock_basic()
    
    # 2. 同步核心大盘指数
    engine.sync_index_daily()
    
    # 3. 示例测试：同步市值前 50 核心股票近 3 年日线数据用于 ML 训练
    with engine.get_connection() as conn:
        top50_symbols = pd.read_sql_query("SELECT symbol FROM stock_basic ORDER BY total_mv DESC LIMIT 50", conn)['symbol'].tolist()
    
    print("\n[Demo] 优先同步沪深核心市值 Top 50 标的数据...")
    engine.sync_stock_daily(symbols=top50_symbols, start_date="20220101")
    
    # 4. 加载测试 (贵州茅台 600519)
    df_maotai = engine.load_stock_data("600519", start_date="2023-01-01")
    print(f"\n[Test Load] 贵州茅台 (600519) 成功从本地 SQLite 数据库加载 {len(df_maotai)} 条日线记录:")
    print(df_maotai.tail(5))
