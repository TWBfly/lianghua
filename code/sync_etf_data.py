"""
A-Share Quantitative Strategy Engine - ETF Data Ingestion & Localizer
同步全市场主流 ETF (股票型、行业主题型、跨境型、商品型 ETF) 日 K 线数据至 SQLite 数据库
"""

import os
import sys
import sqlite3
import pandas as pd
import requests

# 禁用 urllib3 警告
requests.packages.urllib3.disable_warnings()
os.environ['CURL_CA_BUNDLE'] = ''

try:
    import akshare as ak
except ImportError:
    print("[Error] 请先安装 akshare: pip install akshare")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ashare_quant.db")

# 核心主流 ETF 清单
POPULAR_ETFS = [
    {"symbol": "510300", "sina_symbol": "sh510300", "name": "沪深300ETF", "category": "宽基龙头"},
    {"symbol": "159915", "sina_symbol": "sz159915", "name": "创业板ETF", "category": "成长成长"},
    {"symbol": "510500", "sina_symbol": "sh510500", "name": "中证500ETF", "category": "中盘弹性"},
    {"symbol": "588000", "sina_symbol": "sh588000", "name": "科创50ETF", "category": "硬科技"},
    {"symbol": "512880", "sina_symbol": "sh512880", "name": "证券ETF", "category": "金融龙头"},
    {"symbol": "515050", "sina_symbol": "sh515050", "name": "5GETF", "category": "科技通信"},
    {"symbol": "159995", "sina_symbol": "sz159995", "name": "芯片ETF", "category": "半导体"},
    {"symbol": "518880", "sina_symbol": "sh518880", "name": "黄金ETF", "category": "避险商品"},
    {"symbol": "513050", "sina_symbol": "sh513050", "name": "中概互联ETF", "category": "跨境互联网"},
    {"symbol": "512010", "sina_symbol": "sh512010", "name": "医药ETF", "category": "医疗健康"},
    {"symbol": "512690", "sina_symbol": "sh512690", "name": "酒ETF", "category": "大消费"},
    {"symbol": "512760", "sina_symbol": "sh512760", "name": "半导体ETF", "category": "芯片半导体"},
    {"symbol": "159928", "sina_symbol": "sz159928", "name": "消费ETF", "category": "必选消费"},
    {"symbol": "512480", "sina_symbol": "sh512480", "name": "半导体设备ETF", "category": "高端制造"},
    {"symbol": "511010", "sina_symbol": "sh511010", "name": "国债ETF", "category": "固定收益"}
]


def sync_all_etfs(db_path=DB_PATH):
    """同步核心 ETF 历史日 K 线至数据库 `stock_daily` 与 `stock_basic`"""
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    print("=" * 80)
    print("🚀 启动 A 股主流 ETF 历史行情数据提取与同步脚本...")
    print(f"目标数据库: {db_path}")
    print("=" * 80)

    with sqlite3.connect(db_path) as conn:
        for etf in POPULAR_ETFS:
            sym = etf["symbol"]
            sina_sym = etf["sina_symbol"]
            name = etf["name"]
            
            print(f"\n[ETF Sync] 正在提取 [{sym} {name}] ({etf['category']}) 历史数据...", end="", flush=True)
            try:
                df = ak.fund_etf_hist_sina(symbol=sina_sym)
                if df is None or df.empty:
                    print(" ❌ 未获取到数据")
                    continue
                
                # 标准化列名
                df['trade_date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                df['symbol'] = sym
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['amount'] = df['amount'].astype(float) if 'amount' in df.columns and df['amount'].notna().all() else (df['close'] * df['volume'])
                
                # 插入/更新 stock_basic 标记为 ETF
                conn.execute("""
                    INSERT OR REPLACE INTO stock_basic (symbol, name, price, pe_ttm, pb, total_mv, circ_mv, updated_at)
                    VALUES (?, ?, ?, 0.0, 0.0, 100000000000.0, 100000000000.0, CURRENT_TIMESTAMP);
                """, (sym, f"[ETF] {name}", df['close'].iloc[-1]))
                
                # 插入/覆盖 stock_daily 历史行情
                sub_df = df[['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                sub_df.to_sql('stock_daily', conn, if_exists='append', index=False, method='multi')
                
                # 执行去重与补全 amount
                conn.execute("""
                    DELETE FROM stock_daily
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM stock_daily
                        GROUP BY symbol, trade_date
                    );
                """)
                conn.execute("UPDATE stock_daily SET amount = close * volume WHERE amount IS NULL OR amount = 0;")
                conn.commit()
                print(f" ✅ 成功写入 {len(df)} 条 K 线 (最新收盘: ¥{df['close'].iloc[-1]:.3f})")
                
            except Exception as e:
                print(f" ❌ 提取失败: {e}")
                
    print("\n" + "=" * 80)
    print("✅ ETF 历史行情数据同步完成！可以在回测引擎与 Web 端直接调用 ETF 代码进行回测！")
    print("=" * 80)


if __name__ == "__main__":
    sync_all_etfs()
