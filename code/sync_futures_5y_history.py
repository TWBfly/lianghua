"""
A-Share Quantitative Strategy Engine - Futures Multi-Timeframe (1m, 5m, 15m, 30m, 1h, 1d) History Sync Engine
【全量 5 年期货历史指数行情 + 1m/5m/15m/30m/1h 分钟 K 线全套存储】

核心功能：
1. 全量存储 24 大热门高活跃度期货品种的 5 年历史日线数据 (用于日线及长周期回测)。
2. 完整获取 1m (1分钟)、5m (5分钟)、15m (15分钟)、30m (30分钟)、1h (1小时) 5 大极细颗粒度 K 线数据。
3. 严格遵循 SQLite `futures_min_bars` 表结构 (`symbol`, `timeframe`, `trade_time`, `open`, `high`, `low`, `close`, `volume`, `amount`, `open_interest`, `settlement`) 归一化落盘。
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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "ashare_quant.db")

# 24 大热门高活跃度期货品种清单
ACTIVE_FUTURES_POOL = [
    {"symbol_idx": "AG_IDX", "raw_code": "AG0", "name": "沪银",   "category": "贵金属"},
    {"symbol_idx": "AU_IDX", "raw_code": "AU0", "name": "沪金",   "category": "贵金属避险"},
    {"symbol_idx": "CU_IDX", "raw_code": "CU0", "name": "沪铜",   "category": "有色工业"},
    {"symbol_idx": "AL_IDX", "raw_code": "AL0", "name": "沪铝",   "category": "有色金属"},
    {"symbol_idx": "ZN_IDX", "raw_code": "ZN0", "name": "沪锌",   "category": "有色金属"},
    {"symbol_idx": "SN_IDX", "raw_code": "SN0", "name": "沪锡",   "category": "有色稀缺"},
    {"symbol_idx": "LC_IDX", "raw_code": "LC0", "name": "碳酸锂", "category": "新能源电池"},
    {"symbol_idx": "SI_IDX", "raw_code": "SI0", "name": "工业硅", "category": "光伏新能源"},
    {"symbol_idx": "RB_IDX", "raw_code": "RB0", "name": "螺纹钢", "category": "黑色建筑"},
    {"symbol_idx": "HC_IDX", "raw_code": "HC0", "name": "热卷",   "category": "黑色工业"},
    {"symbol_idx": "I_IDX",  "raw_code": "I0",  "name": "铁矿石", "category": "黑色原材料"},
    {"symbol_idx": "J_IDX",  "raw_code": "J0",  "name": "焦炭",   "category": "双焦能源"},
    {"symbol_idx": "JM_IDX", "raw_code": "JM0", "name": "焦煤",   "category": "双焦能源"},
    {"symbol_idx": "SA_IDX", "raw_code": "SA0", "name": "纯碱",   "category": "化工高波"},
    {"symbol_idx": "FG_IDX", "raw_code": "FG0", "name": "玻璃",   "category": "建材地产"},
    {"symbol_idx": "SC_IDX", "raw_code": "SC0", "name": "原油",   "category": "能源化工"},
    {"symbol_idx": "MA_IDX", "raw_code": "MA0", "name": "甲醇",   "category": "化工原料"},
    {"symbol_idx": "TA_IDX", "raw_code": "TA0", "name": "PTA",    "category": "纺织化工"},
    {"symbol_idx": "RU_IDX", "raw_code": "RU0", "name": "橡胶",   "category": "化工高波"},
    {"symbol_idx": "M_IDX",  "raw_code": "M0",  "name": "豆粕",   "category": "农产品"},
    {"symbol_idx": "P_IDX",  "raw_code": "P0",  "name": "棕榈油", "category": "油脂农产品"},
    {"symbol_idx": "Y_IDX",  "raw_code": "Y0",  "name": "豆油",   "category": "油脂农产品"},
    {"symbol_idx": "SR_IDX", "raw_code": "SR0", "name": "白糖",   "category": "软商品"},
    {"symbol_idx": "CF_IDX", "raw_code": "CF0", "name": "棉花",   "category": "软商品"}
]


def sync_all_timeframe_futures_data(db_path=DB_PATH):
    """全量同步 5 年历史日线 + 1m / 5m / 15m / 30m / 1h 分钟 K 线行情"""
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    print("=" * 90)
    print("🚀 启动 1m/5m/15m/30m/1h 全套分钟 K 线与 5 年日线行情落盘程序...")
    print(f"目标数据库: {db_path}")
    print("=" * 90)

    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()

        idx_success_count = 0
        min_1m_success_count = 0

        for item in ACTIVE_FUTURES_POOL:
            sym_idx = item["symbol_idx"]
            raw_code = item["raw_code"]
            name = item["name"]
            category = item["category"]

            print(f"\n────────────────────────────────────────────────────────────────────────")
            print(f"📦 [正在同步品种: {name} ({category})] 指数: {sym_idx} | 代码: {raw_code}")

            # ── 1. 同步过去 5 年指数日线行情 (stock_daily) ─────────────────────────
            try:
                df_idx = ak.futures_zh_daily_sina(symbol=raw_code)
                if df_idx is not None and not df_idx.empty:
                    df_idx['trade_date'] = pd.to_datetime(df_idx['date']).dt.strftime('%Y-%m-%d')
                    df_5y = df_idx[df_idx['trade_date'] >= "2021-01-01"].copy()
                    if df_5y.empty:
                        df_5y = df_idx.tail(1260).copy()

                    close_series = df_5y['close'].astype(float)
                    prev_close = close_series.shift(1).fillna(close_series)
                    chg_amt = close_series - prev_close
                    pct_chg = (chg_amt / (prev_close + 1e-8)) * 100.0
                    high_series = df_5y['high'].astype(float)
                    low_series = df_5y['low'].astype(float)
                    amp = ((high_series - low_series) / (prev_close + 1e-8)) * 100.0

                    df_5y['symbol'] = sym_idx
                    df_5y['open'] = df_5y['open'].astype(float)
                    df_5y['high'] = high_series
                    df_5y['low'] = low_series
                    df_5y['close'] = close_series
                    df_5y['volume'] = df_5y['volume'].fillna(0.0).astype(float)
                    df_5y['amount'] = np.round(close_series * df_5y['volume'], 2)
                    df_5y['amplitude'] = np.round(amp, 2)
                    df_5y['pct_chg'] = np.round(pct_chg, 2)
                    df_5y['change_amount'] = np.round(chg_amt, 2)
                    df_5y['turnover_rate'] = 0.0

                    c.execute("DELETE FROM stock_daily WHERE symbol = ? AND trade_date >= '2021-01-01';", (sym_idx,))
                    sub_idx = df_5y[['symbol', 'trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'amplitude', 'pct_chg', 'change_amount', 'turnover_rate']]
                    sub_idx.to_sql('stock_daily', conn, if_exists='append', index=False, chunksize=500)

                    c.execute("""
                        INSERT OR REPLACE INTO stock_basic (symbol, name, price, pe_ttm, pb, total_mv, circ_mv, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 50000000000.0, 50000000000.0, CURRENT_TIMESTAMP);
                    """, (sym_idx, f"[期货指数] {name}", float(close_series.iloc[-1])))

                    conn.commit()
                    idx_success_count += 1
                    print(f"  ├─ ✅ [5年日线] 写入 {len(df_5y)} 条 | 最新收盘: {close_series.iloc[-1]:.2f}")

            except Exception as e:
                print(f"  ├─ ❌ [日线] 异常: {e}")

            # ── 2. 同步 1m (1分钟) K 线数据 ─────────────────────────────────────────
            try:
                df_1m = ak.futures_zh_minute_sina(symbol=raw_code, period='1')
                if df_1m is not None and not df_1m.empty:
                    df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
                    df_1m['trade_time'] = df_1m['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    df_1m['symbol'] = sym_idx
                    df_1m['timeframe'] = '1m'
                    df_1m['open'] = df_1m['open'].astype(float)
                    df_1m['high'] = df_1m['high'].astype(float)
                    df_1m['low'] = df_1m['low'].astype(float)
                    df_1m['close'] = df_1m['close'].astype(float)
                    df_1m['volume'] = df_1m['volume'].fillna(0.0).astype(float)
                    df_1m['amount'] = np.round(df_1m['close'] * df_1m['volume'], 2)
                    df_1m['open_interest'] = df_1m['hold'].astype(float) if 'hold' in df_1m.columns else 0.0
                    df_1m['settlement'] = df_1m['close']

                    sub_1m = df_1m[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount', 'open_interest', 'settlement']]
                    c.executemany("""
                        INSERT OR REPLACE INTO futures_min_bars (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, sub_1m.values.tolist())

                    conn.commit()
                    min_1m_success_count += 1
                    print(f"  ├─ ✅ [1分钟 K线 (1m)] 存储 {len(df_1m)} 根 Bar | 时间: {df_1m['trade_time'].iloc[0]} -> {df_1m['trade_time'].iloc[-1]}")

            except Exception as e:
                print(f"  ├─ ⚠️ [1m K线] 提示: {e}")

            # ── 3. 同步 5m / 15m / 30m / 1h 分钟 K 线数据 ───────────────────────────
            try:
                df_5m = ak.futures_zh_minute_sina(symbol=raw_code, period='5')
                if df_5m is not None and not df_5m.empty:
                    df_5m['datetime'] = pd.to_datetime(df_5m['datetime'])
                    df_5m['trade_time'] = df_5m['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    df_5m['symbol'] = sym_idx
                    df_5m['timeframe'] = '5m'
                    df_5m['open'] = df_5m['open'].astype(float)
                    df_5m['high'] = df_5m['high'].astype(float)
                    df_5m['low'] = df_5m['low'].astype(float)
                    df_5m['close'] = df_5m['close'].astype(float)
                    df_5m['volume'] = df_5m['volume'].fillna(0.0).astype(float)
                    df_5m['amount'] = np.round(df_5m['close'] * df_5m['volume'], 2)
                    df_5m['open_interest'] = df_5m['hold'].astype(float) if 'hold' in df_5m.columns else 0.0
                    df_5m['settlement'] = df_5m['close']

                    sub_5m = df_5m[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount', 'open_interest', 'settlement']]
                    c.executemany("""
                        INSERT OR REPLACE INTO futures_min_bars (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, sub_5m.values.tolist())

                    # 重采样生成 15m / 30m / 1h
                    for tf_label, rule in [("15m", "15min"), ("30m", "30min"), ("1h", "60min")]:
                        df_res = df_5m.set_index('datetime').resample(rule).agg({
                            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'open_interest': 'last'
                        }).dropna().reset_index()
                        df_res['symbol'] = sym_idx
                        df_res['timeframe'] = tf_label
                        df_res['trade_time'] = df_res['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                        df_res['amount'] = np.round(df_res['close'] * df_res['volume'], 2)
                        df_res['settlement'] = df_res['close']

                        sub_res = df_res[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount', 'open_interest', 'settlement']]
                        c.executemany("""
                            INSERT OR REPLACE INTO futures_min_bars (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, sub_res.values.tolist())

                    conn.commit()
                    print(f"  ├─ ✅ [5m/15m/30m/1h K线] 衍生重采样存储完成")

            except Exception as e:
                print(f"  ├─ ⚠️ [分钟重采样] 提示: {e}")

    print("\n" + "=" * 90)
    print("🎉 包含 1 分钟 (1m) 在内的全套多周期 K 线数据落盘完毕!")
    print(f"  ├─ 1m 分钟 K 线涵盖品种: {min_1m_success_count} 个")
    print(f"  ├─ 5 年指数日线品种: {idx_success_count} 个")
    print(f"  ├─ 数据库文件地址: {db_path}")
    print("=" * 90)


if __name__ == "__main__":
    sync_all_timeframe_futures_data()
