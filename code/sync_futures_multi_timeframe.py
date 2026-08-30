"""
A-Share Quantitative Strategy Engine - Multi-Timeframe High-Activity Futures Localizer
支持存储高活跃度期货品种（如沪锡 SN、沪金 AU、沪铜 CU、碳酸锂 LC、纯碱 SA 等）的 8 大全周期 K 线数据：
【5分钟、15分钟、30分钟、1小时、2小时、3小时、4小时、日K】
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

# 高活跃度热门期货资产池
HIGH_ACTIVITY_FUTURES = [
    {"symbol": "SN_IDX", "raw_code": "SN0", "name": "沪锡指数",   "category": "有色稀缺"},
    {"symbol": "AU_IDX", "raw_code": "AU0", "name": "沪金指数",   "category": "贵金属避险"},
    {"symbol": "AG_IDX", "raw_code": "AG0", "name": "沪银指数",   "category": "贵金属"},
    {"symbol": "CU_IDX", "raw_code": "CU0", "name": "沪铜指数",   "category": "有色工业"},
    {"symbol": "LC_IDX", "raw_code": "LC0", "name": "碳酸锂指数", "category": "新能源电池"},
    {"symbol": "SA_IDX", "raw_code": "SA0", "name": "纯碱指数",   "category": "化工高波"},
    {"symbol": "SI_IDX", "raw_code": "SI0", "name": "工业硅指数", "category": "光伏新能源"},
    {"symbol": "RB_IDX", "raw_code": "RB0", "name": "螺纹钢指数", "category": "黑色建筑"},
    {"symbol": "I_IDX",  "raw_code": "I0",  "name": "铁矿石指数", "category": "黑色原材料"},
    {"symbol": "SC_IDX", "raw_code": "SC0", "name": "原油指数",   "category": "能源化工"},
    {"symbol": "J_IDX",  "raw_code": "J0",  "name": "焦炭指数",   "category": "双焦能源"},
    {"symbol": "MA_IDX", "raw_code": "MA0", "name": "甲醇指数",   "category": "化工原料"},
    {"symbol": "M_IDX",  "raw_code": "M0",  "name": "豆粕指数",   "category": "农产品"},
    {"symbol": "FG_IDX", "raw_code": "FG0", "name": "玻璃指数",   "category": "建材地产"},
    {"symbol": "TA_IDX", "raw_code": "TA0", "name": "PTA指数",    "category": "纺织化工"}
]

# 8 大时间周期配置映射
RESAMPLE_MAP = {
    "15m": "15min",
    "30m": "30min",
    "1h":  "60min",
    "2h":  "120min",
    "3h":  "180min",
    "4h":  "240min"
}


def init_futures_tables(conn):
    """初始化多周期期货分钟/小时 K 线数据表 `futures_min_bars`"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_min_bars (
            symbol TEXT,
            timeframe TEXT,
            trade_time TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            CHECK (open > 0 AND high >= low AND close > 0 AND volume >= 0),
            PRIMARY KEY (symbol, timeframe, trade_time)
        );
    """)
    conn.commit()


def sync_high_activity_futures(db_path=DB_PATH):
    """提取高活跃期货 5m K 线并重采样生成 8 大周期 K 线落盘数据库"""
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    print("=" * 80)
    print("🚀 启动高活跃度期货品种 (如沪锡 SN 等) 8 大多周期 K 线同步落盘程序...")
    print(f"涵盖周期: 5m, 15m, 30m, 1h, 2h, 3h, 4h, 1d")
    print(f"目标数据库: {db_path}")
    print("=" * 80)

    with sqlite3.connect(db_path) as conn:
        init_futures_tables(conn)
        c = conn.cursor()

        for item in HIGH_ACTIVITY_FUTURES:
            sym = item["symbol"]
            raw_code = item["raw_code"]
            name = item["name"]
            category = item["category"]
            
            print(f"\n[Multi-TF Sync 📊] 正在处理高活跃品种 [{sym} {name}] ({category})...", flush=True)
            try:
                # 1. 获取 5m 基础 K 线
                df_5m_raw = ak.futures_zh_minute_sina(symbol=raw_code, period='5')
                if df_5m_raw is None or df_5m_raw.empty:
                    print(f"  ❌ 未获取到 {raw_code} 5m K 线数据")
                    continue
                
                df_5m = df_5m_raw.copy()
                df_5m['datetime'] = pd.to_datetime(df_5m['datetime'])
                df_5m = df_5m.set_index('datetime').sort_index()
                
                df_5m['open'] = df_5m['open'].astype(float)
                df_5m['high'] = df_5m['high'].astype(float)
                df_5m['low'] = df_5m['low'].astype(float)
                df_5m['close'] = df_5m['close'].astype(float)
                df_5m['volume'] = df_5m['volume'].fillna(0.0).astype(float)
                df_5m['amount'] = np.round(df_5m['close'] * df_5m['volume'], 2)
                
                # 存入 5m 到 futures_min_bars
                df_5m_save = df_5m.reset_index()
                df_5m_save['trade_time'] = df_5m_save['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                df_5m_save['symbol'] = sym
                df_5m_save['timeframe'] = '5m'
                
                sub_5m = df_5m_save[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                c.execute("DELETE FROM futures_min_bars WHERE symbol = ? AND timeframe = '5m';", (sym,))
                sub_5m.to_sql('futures_min_bars', conn, if_exists='append', index=False, chunksize=500)
                print(f"  ├─ [5m  5分钟K]  落盘 {len(sub_5m)} 条 (最新: {sub_5m['close'].iloc[-1]:.2f})", flush=True)

                # 2. 重采样 15m, 30m, 1h, 2h, 3h, 4h
                for tf_label, freq in RESAMPLE_MAP.items():
                    df_res = df_5m.resample(freq).agg({
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }).dropna().reset_index()
                    
                    df_res['trade_time'] = df_res['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    df_res['symbol'] = sym
                    df_res['timeframe'] = tf_label
                    df_res['amount'] = np.round(df_res['close'] * df_res['volume'], 2)
                    
                    sub_res = df_res[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                    c.execute("DELETE FROM futures_min_bars WHERE symbol = ? AND timeframe = ?;", (sym, tf_label))
                    sub_res.to_sql('futures_min_bars', conn, if_exists='append', index=False, chunksize=500)
                    print(f"  ├─ [{tf_label:<4} {tf_label}K线]  落盘 {len(sub_res)} 条 (最新: {sub_res['close'].iloc[-1]:.2f})", flush=True)

                # 3. 日 K 线 (1d / daily) 同步至 stock_daily 与 stock_basic
                df_daily = ak.futures_zh_daily_sina(symbol=raw_code)
                if df_daily is not None and not df_daily.empty:
                    df_daily['trade_date'] = pd.to_datetime(df_daily['date']).dt.strftime('%Y-%m-%d')
                    df_daily['symbol'] = sym
                    df_daily['open'] = df_daily['open'].astype(float)
                    df_daily['high'] = df_daily['high'].astype(float)
                    df_daily['low'] = df_daily['low'].astype(float)
                    df_daily['close'] = df_daily['close'].astype(float)
                    df_daily['volume'] = df_daily['volume'].fillna(0.0).astype(float)
                    df_daily['amount'] = np.round(df_daily['close'] * df_daily['volume'], 2)
                    
                    c.execute("""
                        INSERT OR REPLACE INTO stock_basic (symbol, name, price, pe_ttm, pb, total_mv, circ_mv, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 50000000000.0, 50000000000.0, CURRENT_TIMESTAMP);
                    """, (sym, f"[期货指数] {name}", float(df_daily['close'].iloc[-1])))
                    
                    c.execute("DELETE FROM stock_daily WHERE symbol = ?;", (sym,))
                    sub_d = df_daily[['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                    sub_d.to_sql('stock_daily', conn, if_exists='append', index=False, chunksize=500)
                    print(f"  └─ [1d  日K线  ]  落盘 {len(sub_d)} 条 (最新: {sub_d['close'].iloc[-1]:.2f})", flush=True)

                conn.commit()

            except Exception as e:
                print(f"  ❌ 处理 {sym} 失败: {e}", flush=True)

    print("\n" + "=" * 80)
    print("✅ 高活跃度期货品种 8 大全周期 (5m, 15m, 30m, 1h, 2h, 3h, 4h, 1d) K 线同步落盘完毕！")
    print("=" * 80)


if __name__ == "__main__":
    sync_high_activity_futures()
