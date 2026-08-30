"""
code/deploy_ek_supertrend_v7_trader.py — 「太冲·零滞后相变趋势引擎」(EK-ZLP SuperTrend V7) 实时虚拟盘自动化交易与守护引擎
(支持 127.0.0.1 / https://739265.xyz/ 实时云端监控与 TqSdk / 仿真执行)

实盘配置与执行铁律：
1. 核心精选 5 大高弹性大宗商品：白银 (AG)、沪铜 (CU)、黄金 (AU)、碳酸锂 (LC)、棕榈油 (P)；
2. 多空非对称自适应开关：宏观顺大势多头时，空头仓位自动降半 (Short Lots = Long Lots / 2)；
3. 2.5R 阶梯锁利 50% + 零风险动态保本抬升 + Ehlers SuperTrend 原生动态轨线放飞；
4. 状态实时持久化至 data/ek_supertrend_v7_state.json，无缝对接 739265.xyz Web 监控大屏。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from tqsdk import TargetPosTask, TqApi, TqAuth, TqSim

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
CODE_DIR = PROJECT_ROOT / "code"
for p in (STRATEGIES_DIR, CODE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from technical_indicators import (
    calculate_atr,
    calculate_ehlers_supersmoother,
    calculate_kalman_velocity_tracker,
    calculate_permutation_entropy
)
from run_ek_supertrend_v7_lln_audit import compute_v7_dynamic_supertrend
from runtime_credentials import load_required_credentials

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "ek_supertrend_v7_state.json"
LOG_FILE = LOG_DIR / "ek_supertrend_v7_trader.log"
TRADES_CSV = LOG_DIR / "ek_supertrend_v7_trades.csv"

logger = logging.getLogger("EKSupretrendTrader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(formatter)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(fh)
    logger.addHandler(ch)

# 核心精选 5 大高弹性品种实盘配置表
EK_V7_SYMBOLS_CONFIG = {
    "AG_IDX": {
        "symbol": "AG_IDX", "tq_symbol": "KQ.i@SHFE.ag", "name": "白银", "sector": "贵金属",
        "multiplier": 15.0, "tick": 1.0, "base_lots": 2, "asymmetric_short": True,
        "period": 14, "base_multiplier": 2.5, "pe_thresh": 0.68, "weight": 0.25
    },
    "CU_IDX": {
        "symbol": "CU_IDX", "tq_symbol": "KQ.i@SHFE.cu", "name": "沪铜", "sector": "有色金属",
        "multiplier": 5.0, "tick": 10.0, "base_lots": 2, "asymmetric_short": True,
        "period": 14, "base_multiplier": 2.5, "pe_thresh": 0.68, "weight": 0.25
    },
    "AU_IDX": {
        "symbol": "AU_IDX", "tq_symbol": "KQ.i@SHFE.au", "name": "黄金", "sector": "贵金属",
        "multiplier": 1000.0, "tick": 0.02, "base_lots": 2, "asymmetric_short": True,
        "period": 14, "base_multiplier": 2.5, "pe_thresh": 0.68, "weight": 0.20
    },
    "LC_IDX": {
        "symbol": "LC_IDX", "tq_symbol": "KQ.i@GFEX.lc", "name": "碳酸锂", "sector": "新能源",
        "multiplier": 1.0, "tick": 50.0, "base_lots": 2, "asymmetric_short": True,
        "period": 14, "base_multiplier": 2.5, "pe_thresh": 0.68, "weight": 0.15
    },
    "P_IDX": {
        "symbol": "P_IDX", "tq_symbol": "KQ.i@DCE.p", "name": "棕榈油", "sector": "农产品油脂",
        "multiplier": 10.0, "tick": 2.0, "base_lots": 2, "asymmetric_short": True,
        "period": 14, "base_multiplier": 2.5, "pe_thresh": 0.68, "weight": 0.15
    }
}


def get_tq_credentials():
    return load_required_credentials(PROJECT_ROOT / ".env")


class EKSupretrendV7Trader:
    """太冲·零滞后相变趋势引擎 V7 实时虚拟盘执行守护进程"""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.account, self.password = get_tq_credentials()
        self.initial_capital = initial_capital
        self.state = self.load_state()

        logger.info("=" * 85)
        logger.info("🚀 初始化「太冲·零滞后相变趋势引擎」(EK-ZLP SuperTrend V7) 实时虚拟盘守护进程")
        logger.info(f"💰 初始资金池: {initial_capital:,.2f} 元 | 监控终端: https://739265.xyz/")
        logger.info(f"📊 精选 5 大高弹性主力: {list(EK_V7_SYMBOLS_CONFIG.keys())}")
        logger.info("=" * 85)

    def load_state(self) -> Dict[str, Any]:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"读取状态文件异常，初始化默认状态: {e}")

        positions = {}
        for sym in EK_V7_SYMBOLS_CONFIG.keys():
            positions[sym] = {
                "symbol": sym,
                "name": EK_V7_SYMBOLS_CONFIG[sym]["name"],
                "pos": 0,
                "lots": 0,
                "rem_lots": 0,
                "entry_price": 0.0,
                "entry_time": "",
                "stop_price": 0.0,
                "tp1_price": 0.0,
                "tp1_hit": False,
                "floating_pnl": 0.0,
                "realized_pnl": 0.0,
                "trades_count": 0,
                "win_count": 0,
                "highest_price": 0.0,
                "lowest_price": float("inf"),
                "pe_entropy": 0.50,
                "macro_direction": 0,
                "kalman_velocity": 0.0
            }

        return {
            "strategy_id": "ek_supertrend_v7",
            "strategy_name": "🔮 【太冲·零滞后相变趋势引擎】EK-ZLP SuperTrend V7 (DSP+熵门禁+非对称)",
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "initial_capital": self.initial_capital,
            "cash": self.initial_capital,
            "total_equity": self.initial_capital,
            "net_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "positions": positions,
            "daily_history": []
        }

    def save_state(self):
        self.state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def run(self):
        logger.info("🔗 正在连接天勤量化 TqSdk 实时行情与虚拟仿真柜台...")
        sim = TqSim(init_balance=self.initial_capital)
        auth = TqAuth(self.account, self.password)
        api = TqApi(sim, auth=auth)

        # 订阅 15m 实时 K 线序列与主力合约
        klines_dict = {}
        target_tasks = {}
        for sym, cfg in EK_V7_SYMBOLS_CONFIG.items():
            tq_sym = cfg["tq_symbol"]
            klines_dict[sym] = api.get_kline_serial(tq_sym, duration_seconds=900, data_length=150)
            target_tasks[sym] = TargetPosTask(api, tq_sym)

        logger.info("✅ 5 大核心品种 15m 实时 K 线订阅成功，进入事件驱动循环...")

        last_sync_time = 0.0
        while True:
            api.wait_update()
            curr_ts = time.time()

            # 盘中信号处理与仓位更新
            for sym, cfg in EK_V7_SYMBOLS_CONFIG.items():
                df_kl = klines_dict[sym]
                if df_kl is None or len(df_kl) < 45:
                    continue

                closes = df_kl["close"].to_numpy(dtype=float)
                highs = df_kl["high"].to_numpy(dtype=float)
                lows = df_kl["low"].to_numpy(dtype=float)
                opens = df_kl["open"].to_numpy(dtype=float)
                curr_price = float(closes[-1])
                curr_high = float(highs[-1])
                curr_low = float(lows[-1])
                curr_open = float(opens[-1])
                curr_time_str = datetime.datetime.fromtimestamp(df_kl["datetime"].iloc[-1] / 1e9).strftime("%Y-%m-%d %H:%M:%S")

                # 1. 动态自适应 SuperTrend
                ehlers_center, st_line, direction, final_upper, final_lower = compute_v7_dynamic_supertrend(
                    df_kl, period=cfg["period"], base_multiplier=cfg["base_multiplier"]
                )

                # 2. 卡尔曼瞬时速度与宏观斜率
                c_series = pd.Series(closes)
                _, kalman_v = calculate_kalman_velocity_tracker(c_series, q_factor=0.01, r_factor=0.5)
                curr_kv = float(kalman_v.iloc[-1])

                ehlers_macro = calculate_ehlers_supersmoother(c_series, period=48).to_numpy()
                macro_slope = float(ehlers_macro[-1] - ehlers_macro[-5]) if len(ehlers_macro) >= 5 else 0.0
                macro_up = macro_slope > 0
                macro_dn = macro_slope < 0

                # 3. 统计物理排列熵门禁
                pe_series = calculate_permutation_entropy(pd.Series(ehlers_center), order=3, delay=1, window=30).to_numpy()
                curr_pe = float(pe_series[-1])

                # 4. 波动率能量挤压门禁
                atr_series = calculate_atr(df_kl, n=cfg["period"]).fillna(method="bfill").to_numpy()
                curr_atr = float(atr_series[-1])
                std_20 = c_series.rolling(20).std(ddof=0)
                bb_width = 4.0 * std_20
                sq_ratio = (bb_width / (pd.Series(atr_series) * 2.0 + 1e-8)).to_numpy()
                had_squeeze = bool(pd.Series(sq_ratio).rolling(6).min().iloc[-1] <= 1.25)

                pos_info = self.state["positions"][sym]
                pos_info["pe_entropy"] = round(curr_pe, 3)
                pos_info["macro_direction"] = 1 if macro_up else -1 if macro_dn else 0
                pos_info["kalman_velocity"] = round(curr_kv, 2)

                # -------------------------------------------------------------
                # A. 盘中止盈、保本抬升与动态出场
                # -------------------------------------------------------------
                if pos_info["pos"] != 0 and pos_info["rem_lots"] > 0:
                    pos = pos_info["pos"]
                    entry_p = pos_info["entry_price"]
                    tp1_p = pos_info["tp1_price"]
                    stop_p = pos_info["stop_price"]

                    # 1. 达到 +2.5R 第一目标位：平仓 50% 锁定确定性利润，并将止损抬升至保本价
                    if not pos_info["tp1_hit"] and pos_info["rem_lots"] > 1:
                        scale_lots = pos_info["rem_lots"] // 2
                        hit_tp1 = (pos == 1 and curr_high >= tp1_p) or (pos == -1 and curr_low <= tp1_p)
                        if hit_tp1:
                            exit_p = tp1_p
                            diff = (exit_p - entry_p) if pos == 1 else (entry_p - exit_p)
                            pnl = diff * scale_lots * cfg["multiplier"]
                            pos_info["realized_pnl"] += pnl
                            self.state["cash"] += pnl
                            pos_info["rem_lots"] -= scale_lots
                            pos_info["tp1_hit"] = True
                            # 止损线上抬至开仓价 + 1 跳保本
                            pos_info["stop_price"] = entry_p + (cfg["tick"] if pos == 1 else -cfg["tick"])
                            target_tasks[sym].set_target_volume(pos_info["rem_lots"] if pos == 1 else -pos_info["rem_lots"])
                            logger.info(f"🎯 [{sym} {cfg['name']}] 触发 +2.5R 阶梯锁利！平仓 {scale_lots} 手，落袋利润 +{pnl:,.2f} 元，止损线上抬至保本价 {pos_info['stop_price']:.2f}")

                    # 2. 动态 SuperTrend 轨线出场
                    st_stop = final_lower[-1] if pos == 1 else final_upper[-1]
                    effective_stop = max(pos_info["stop_price"], st_stop) if pos == 1 else min(pos_info["stop_price"], st_stop)

                    hit_exit = False
                    if pos == 1 and curr_low <= effective_stop:
                        hit_exit = True
                        exit_price = effective_stop
                    elif pos == -1 and curr_high >= effective_stop:
                        hit_exit = True
                        exit_price = effective_stop

                    if hit_exit:
                        diff = (exit_price - entry_p) if pos == 1 else (entry_p - exit_price)
                        pnl = diff * pos_info["rem_lots"] * cfg["multiplier"]
                        pos_info["realized_pnl"] += pnl
                        self.state["cash"] += pnl
                        pos_info["trades_count"] += 1
                        if (pos_info["realized_pnl"]) > 0:
                            pos_info["win_count"] += 1

                        target_tasks[sym].set_target_volume(0)
                        logger.info(f"🛑 [{sym} {cfg['name']}] 触发 SuperTrend 动态离场！平仓 {pos_info['rem_lots']} 手，单次出场平仓盈亏: {pnl:+,.2f} 元")
                        pos_info["pos"] = 0
                        pos_info["lots"] = 0
                        pos_info["rem_lots"] = 0
                        pos_info["entry_price"] = 0.0
                        pos_info["stop_price"] = 0.0
                        pos_info["tp1_price"] = 0.0
                        pos_info["tp1_hit"] = False

                # -------------------------------------------------------------
                # B. 开仓信号检查 (ST翻转 + 宏观顺势 + 卡尔曼速度 + 排列熵低熵 + Squeeze 蓄势)
                # -------------------------------------------------------------
                if pos_info["pos"] == 0:
                    is_st_flip_up = (direction[-1] == 1) and (direction[-2] == -1)
                    is_st_flip_dn = (direction[-1] == -1) and (direction[-2] == 1)
                    is_clean_regime = (curr_pe <= cfg["pe_thresh"]) and had_squeeze

                    long_signal = macro_up and is_st_flip_up and (curr_kv > 0) and is_clean_regime
                    short_signal = macro_dn and is_st_flip_dn and (curr_kv < 0) and is_clean_regime

                    if long_signal:
                        lots = cfg["base_lots"]
                        stop_dist = max(cfg["tick"] * 4, curr_atr * 2.5)
                        pos_info["pos"] = 1
                        pos_info["lots"] = lots
                        pos_info["rem_lots"] = lots
                        pos_info["entry_price"] = curr_price
                        pos_info["entry_time"] = curr_time_str
                        pos_info["stop_price"] = curr_price - stop_dist
                        pos_info["tp1_price"] = curr_price + stop_dist * 2.5
                        pos_info["tp1_hit"] = False

                        target_tasks[sym].set_target_volume(lots)
                        logger.info(f"⚡ [{sym} {cfg['name']}] 开多信号触发 (LONG) | 价格: {curr_price:.2f} | 数量: {lots}手 | 初始止损: {pos_info['stop_price']:.2f} | 目标TP1: {pos_info['tp1_price']:.2f} | 排列熵: {curr_pe:.3f}")

                    elif short_signal:
                        # 多空非对称：宏观大势上行时，空头仓位自动减半
                        lots = max(1, cfg["base_lots"] // 2) if cfg.get("asymmetric_short", True) else cfg["base_lots"]
                        stop_dist = max(cfg["tick"] * 4, curr_atr * 2.5)
                        pos_info["pos"] = -1
                        pos_info["lots"] = lots
                        pos_info["rem_lots"] = lots
                        pos_info["entry_price"] = curr_price
                        pos_info["entry_time"] = curr_time_str
                        pos_info["stop_price"] = curr_price + stop_dist
                        pos_info["tp1_price"] = curr_price - stop_dist * 2.5
                        pos_info["tp1_hit"] = False

                        target_tasks[sym].set_target_volume(-lots)
                        logger.info(f"⚡ [{sym} {cfg['name']}] 开空信号触发 (SHORT, 非对称减半) | 价格: {curr_price:.2f} | 数量: {lots}手 | 初始止损: {pos_info['stop_price']:.2f} | 目标TP1: {pos_info['tp1_price']:.2f} | 排列熵: {curr_pe:.3f}")

                # 计算盘中浮动盈亏
                if pos_info["pos"] != 0:
                    pos_info["floating_pnl"] = (curr_price - pos_info["entry_price"]) * pos_info["rem_lots"] * cfg["multiplier"] if pos_info["pos"] == 1 else (pos_info["entry_price"] - curr_price) * pos_info["rem_lots"] * cfg["multiplier"]
                else:
                    pos_info["floating_pnl"] = 0.0

            # 定时状态同步与持久化 (每 5 秒同步一次)
            if curr_ts - last_sync_time >= 5.0:
                total_floating = sum(p["floating_pnl"] for p in self.state["positions"].values())
                total_realized = sum(p["realized_pnl"] for p in self.state["positions"].values())
                total_trades = sum(p["trades_count"] for p in self.state["positions"].values())
                total_wins = sum(p["win_count"] for p in self.state["positions"].values())

                self.state["total_equity"] = round(self.state["cash"] + total_floating, 2)
                self.state["net_pnl"] = round(total_realized + total_floating, 2)
                self.state["total_trades"] = total_trades
                self.state["win_rate"] = round(total_wins / max(1, total_trades) * 100.0, 1)
                self.save_state()
                last_sync_time = curr_ts


if __name__ == "__main__":
    trader = EKSupretrendV7Trader(initial_capital=1_000_000.0)
    try:
        trader.run()
    except KeyboardInterrupt:
        logger.info("用户手动停止守护进程。")
    except Exception as e:
        logger.exception(f"交易守护进程异常退出: {e}")
