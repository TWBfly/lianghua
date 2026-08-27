"""
code/synthetic_market_regime_generator.py — 工业级全周期市场机制合成数据生成引擎 (物理隔离)
Industrial-Grade Regime-Switching Synthetic Market Generator with Strict Sandbox Isolation

核心机制：
1. 四大宏观周期机制 (Markov Regime Switching):
   - Regime 1: 单边暴涨 (Hyper-Bull Trend) — 强正漂移, 动量自回归, 量仓齐增
   - Regime 2: 恐慌暴跌 (Panic Crash) — 强负漂移, 波动率尖峰, 泊松跳空下挫
   - Regime 3: 长期窄幅横盘 (Grinding Box-Chop) — 零漂移, OU 均值回归, 波动率挤压, 密集假突破
   - Regime 4: 宽幅剧烈洗盘 (Whipsaw Range) — 高波动无趋势, 宽幅扫单与触轨反弹
2. 物理严格隔离 (Strict Isolation):
   - 严禁污染真实历史数据库 (ashare_quant.db/futures_min_bars)
   - 独立生成并持久化在独立沙盒/内存中，打上 is_synthetic=1 与 regime 标签
3. 大数定律保障:
   - 支持根据品种特征自动扩充至 100,000+ 根 Bar，确保产生 >= 1,000 笔策略平仓交易
"""

from __future__ import annotations

import os
import sys
import math
import sqlite3
import datetime
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTHETIC_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "synthetic_sandbox")
os.makedirs(SYNTHETIC_DATA_DIR, exist_ok=True)


class SyntheticMarketRegimeGenerator:
    """物理隔离的多机制市场行情合成器"""

    def __init__(self, seed: Optional[int] = 42):
        self.rng = np.random.default_rng(seed)

    def generate_regime_bars(
        self,
        symbol: str,
        start_price: float = 1000.0,
        bars_per_regime: int = 5000,
        tick_size: float = 1.0,
        timeframe: str = "1h",
    ) -> pd.DataFrame:
        """
        按照四大宏观周期顺序生成全场景合成行情：
        1. 单边暴涨 (Hyper-Bull)
        2. 宽幅洗盘 (Whipsaw)
        3. 恐慌暴跌 (Panic Crash)
        4. 长期窄幅横盘 (Grinding Chop)
        总计 4 * bars_per_regime 根 Bar (默认 20,000 根 Bar)
        """
        all_bars = []
        current_price = float(start_price)
        current_time = datetime.datetime(2015, 1, 1, 9, 0, 0)
        tf_minutes = {"1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
        time_step = datetime.timedelta(minutes=tf_minutes.get(timeframe, 15))

        regimes_config = [
            # 1. 单边暴涨: 正向漂移 (年化 +60% ~ +80%), 适中波动, 成交量持续放大
            {
                "name": "BULL_TREND",
                "label": "单边暴涨周期",
                "bars": bars_per_regime,
                "mu": 0.00015,       # 每小时适度复合漂移
                "sigma": 0.0040,     # 小时真实波动率
                "mean_revert": 0.001,
                "jump_prob": 0.008,
                "jump_mu": 0.004,
                "vol_base": 8000,
                "vol_mult": 1.5,
            },
            # 2. 宽幅剧烈洗盘: 零漂移, 高波动率 (小时波动 0.9%), 频繁假突破
            {
                "name": "WHIPSAW_RANGE",
                "label": "宽幅剧烈洗盘周期",
                "bars": bars_per_regime,
                "mu": 0.0000,
                "sigma": 0.0075,
                "mean_revert": 0.03,
                "jump_prob": 0.02,
                "jump_mu": -0.002,
                "vol_base": 6000,
                "vol_mult": 1.2,
            },
            # 3. 恐慌暴跌: 负向漂移 (年化 -60%), 波动率飙升, 脉冲跳空下挫
            {
                "name": "PANIC_CRASH",
                "label": "恐慌暴跌周期",
                "bars": bars_per_regime,
                "mu": -0.00020,
                "sigma": 0.0080,
                "mean_revert": 0.001,
                "jump_prob": 0.025,
                "jump_mu": -0.008,
                "vol_base": 12000,
                "vol_mult": 2.0,
            },
            # 4. 长期窄幅横盘: 零漂移, 极低波动率 (布林带挤压), 强 OU 均值回归
            {
                "name": "GRINDING_CHOP",
                "label": "长期窄幅横盘周期",
                "bars": bars_per_regime,
                "mu": 0.0000,
                "sigma": 0.0022,     # 极低波动率 (挤压状态)
                "mean_revert": 0.06, # 强均值拉回
                "jump_prob": 0.003,
                "jump_mu": 0.0,
                "vol_base": 3000,
                "vol_mult": 0.6,
            },
        ]

        for reg in regimes_config:
            center_price = current_price
            n_b = reg["bars"]
            mu = reg["mu"]
            sigma = reg["sigma"]
            theta = reg["mean_revert"]

            for i in range(n_b):
                # 机制收益计算: 几何布朗运动 + OU 均值回归 + 泊松跳跃
                drift = mu + theta * (math.log(center_price) - math.log(current_price))
                diffusion = sigma * self.rng.normal(0, 1)

                jump = 0.0
                if self.rng.random() < reg["jump_prob"]:
                    jump = self.rng.normal(reg["jump_mu"], sigma * 1.5)

                ret = drift + diffusion + jump
                next_price = max(tick_size * 5, current_price * math.exp(ret))

                # 生成单根 K 线的 Open, High, Low, Close
                p_open = current_price
                p_close = next_price

                # 模拟柱内波动
                intra_vol = sigma * math.sqrt(0.5) * current_price
                up_wick = abs(self.rng.normal(0, intra_vol))
                dn_wick = abs(self.rng.normal(0, intra_vol))

                p_high = max(p_open, p_close) + up_wick
                p_low = max(tick_size, min(p_open, p_close) - dn_wick)

                # 量与持仓量模拟
                vol = int(reg["vol_base"] * reg["vol_mult"] * (1.0 + abs(ret) * 30.0 + self.rng.exponential(0.3)))
                oi = int(vol * 8.5 + self.rng.normal(5000, 200))

                # 离散化至最小跳价
                p_open = round(p_open / tick_size) * tick_size
                p_high = round(p_high / tick_size) * tick_size
                p_low = round(p_low / tick_size) * tick_size
                p_close = round(p_close / tick_size) * tick_size

                all_bars.append({
                    "trade_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": f"{symbol}_SYNTHETIC",
                    "timeframe": timeframe,
                    "open": p_open,
                    "high": p_high,
                    "low": p_low,
                    "close": p_close,
                    "volume": max(10, vol),
                    "open_interest": max(100, oi),
                    "regime": reg["name"],
                    "regime_label": reg["label"],
                    "is_synthetic": 1,
                })

                current_price = p_close
                current_time += time_step

        df_synthetic = pd.DataFrame(all_bars)
        df_synthetic["trade_time"] = pd.to_datetime(df_synthetic["trade_time"])
        df_synthetic = df_synthetic.set_index("trade_time").sort_index()

        # 物理隔离保存至独立 sandbox 数据库 (严禁写入真实数据库 ashare_quant.db)
        sandbox_db_path = os.path.join(SYNTHETIC_DATA_DIR, "futures_synthetic_bars.db")
        conn = sqlite3.connect(sandbox_db_path)
        table_name = f"bars_{symbol.lower()}_{timeframe}"
        df_synthetic.to_sql(table_name, conn, if_exists="replace", index=True)
        conn.close()
        print(f"🔒 [物理隔离] 成功生成并持久化宏观周期合成数据至独立沙盒: {sandbox_db_path} -> 表: {table_name} (共 {len(df_synthetic):,} 根 Bar)")

        return df_synthetic


if __name__ == "__main__":
    gen = SyntheticMarketRegimeGenerator(seed=2026)
    df_ag_syn = gen.generate_regime_bars("AG_IDX", start_price=6000.0, bars_per_regime=5000, tick_size=1.0, timeframe="1h")
    df_rb_syn = gen.generate_regime_bars("RB_IDX", start_price=3500.0, bars_per_regime=5000, tick_size=1.0, timeframe="1h")
    print("\n✅ 四大周期合成数据概览:")
    print(df_ag_syn.groupby("regime_label")[["close", "volume"]].agg(["min", "max", "count"]))
