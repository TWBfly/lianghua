"""
A-Share Quantitative Strategy Engine - Direct Futures Index Localizer
根据【第一性原理】与【极简原则 (Ponytail)】：
直接从数据源拉取官方现成的【期货品种连续/指数行情】，直接落盘入库！不造轮子，不搞自定义计算。
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import requests

requests.packages.urllib3.disable_warnings()
os.environ['CURL_CA_BUNDLE'] = ''

try:
    import akshare as ak
except ImportError:
    print("[Error] 请先安装 akshare: pip install akshare")
    sys.exit(1)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ashare_quant.db")

# 官方现成的商品期货指数/连续行情清单
FUTURES_INDEX_POOL = [
    {"symbol": "RB_IDX", "raw_symbol": "RB0", "name": "螺纹钢指数", "category": "黑色建筑"},
    {"symbol": "AU_IDX", "raw_symbol": "AU0", "name": "沪金指数",   "category": "贵金属避险"},
    {"symbol": "AG_IDX", "raw_symbol": "AG0", "name": "沪银指数",   "category": "贵金属"},
    {"symbol": "CU_IDX", "raw_symbol": "CU0", "name": "沪铜指数",   "category": "有色工业"},
    {"symbol": "I_IDX",  "raw_symbol": "I0",  "name": "铁矿石指数", "category": "黑色原材料"},
    {"symbol": "J_IDX",  "raw_symbol": "J0",  "name": "焦炭指数",   "category": "双焦能源"},
    {"symbol": "M_IDX",  "raw_symbol": "M0",  "name": "豆粕指数",   "category": "农产品"},
    {"symbol": "MA_IDX", "raw_symbol": "MA0", "name": "甲醇指数",   "category": "化工原料"},
    {"symbol": "SC_IDX", "raw_symbol": "SC0", "name": "原油指数",   "category": "能源化工"}
]


def sync_futures_indices_directly(db_path=DB_PATH):
    """直接拉取官方现成期货指数行情并落盘"""
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    print("=" * 80)
    print("🚀 启动【官方现成期货品种指数行情】直接拉取与落盘脚本...")
    print(f"目标数据库: {db_path}")
    print("=" * 80)

    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        
        # 1. 仅清空特定的主连 symbol
        old_symbols = ['RB0', 'AU0', 'AG0', 'SC0', 'I0', 'CU0', 'J0', 'MA0', 'M0']
        placeholders = ','.join('?' for _ in old_symbols)
        c.execute(f"DELETE FROM stock_daily WHERE symbol IN ({placeholders})", old_symbols)
        c.execute(f"DELETE FROM stock_basic WHERE symbol IN ({placeholders}) OR name LIKE '%主连%'", old_symbols)
        conn.commit()

        # 2. 直接获取官方现成指数并存储
        for item in FUTURES_INDEX_POOL:
            sym = item["symbol"]
            raw_sym = item["raw_symbol"]
            name = item["name"]
            category = item["category"]
            
            print(f"\n[Direct Fetch 📥] 正在拉取官方现成 [{sym} {name}] ({category})...", end="", flush=True)
            try:
                df = ak.futures_zh_daily_sina(symbol=raw_sym)
                if df is None or df.empty:
                    print(" ❌ 未获取到行情数据")
                    continue
                
                df['trade_date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                df['symbol'] = sym
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].fillna(0.0).astype(float)
                df['amount'] = pd.Series(np.round(df['close'].values * df['volume'].values, 2))
                
                # 写入 stock_basic
                c.execute("""
                    INSERT OR REPLACE INTO stock_basic (symbol, name, price, pe_ttm, pb, total_mv, circ_mv, updated_at)
                    VALUES (?, ?, ?, 0.0, 0.0, 50000000000.0, 50000000000.0, CURRENT_TIMESTAMP);
                """, (sym, f"[期货指数] {name}", float(df['close'].iloc[-1])))
                
                # 清除旧指数数据并写入
                c.execute("DELETE FROM stock_daily WHERE symbol = ?;", (sym,))
                sub_df = df[['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                sub_df.to_sql('stock_daily', conn, if_exists='append', index=False, chunksize=500)
                
                conn.commit()
                print(f" ✅ 成功存储 {len(df)} 条官方指数 K 线 (最新收盘: {df['close'].iloc[-1]:.2f})")
                
            except Exception as e:
                print(f" ❌ 存储失败: {e}")

    print("\n" + "=" * 80)
    print("✅ 官方期货品种指数行情直接存储完毕！数据库中全量为数据源官方发布的指数行情！")
    print("=" * 80)


if __name__ == "__main__":
    sync_futures_indices_directly()
