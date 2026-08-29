"""
code/deploy_taichong_squads_trader.py — 「太冲·弹塑性张量」双战队 (10m微观战队 + 30m波段战队) 实时虚拟盘自动化交易与守护引擎
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
from typing import Any

import numpy as np
import pandas as pd
from tqsdk import TargetPosTask, TqApi, TqAuth, TqSim

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
CODE_DIR = PROJECT_ROOT / "code"
for p in (STRATEGIES_DIR, CODE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from taichong_elastoplastic_tensor import calculate_factors, calculate_signal
from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "taichong_dual_squad_state.json"
LOG_FILE = LOG_DIR / "taichong_dual_squad_trader.log"
TRADES_CSV = LOG_DIR / "taichong_daily_trades.csv"

logger = logging.getLogger("TaiChongDualTrader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(formatter)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)

# 10分钟微观战队配置 (5 大核心品种)
SQUAD_10M_CONFIG = {
    "SN_IDX": {"symbol": "SN_IDX", "tq_symbol": "KQ.i@SHFE.sn", "name": "沪锡", "timeframe_sec": 600, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.35},
    "AU_IDX": {"symbol": "AU_IDX", "tq_symbol": "KQ.i@SHFE.au", "name": "沪金", "timeframe_sec": 600, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.20},
    "AG_IDX": {"symbol": "AG_IDX", "tq_symbol": "KQ.i@SHFE.ag", "name": "沪银", "timeframe_sec": 600, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.20},
    "P_IDX":  {"symbol": "P_IDX",  "tq_symbol": "KQ.i@DCE.p",    "name": "棕榈油", "timeframe_sec": 600, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.15},
    "MA_IDX": {"symbol": "MA_IDX", "tq_symbol": "KQ.i@CZCE.MA",  "name": "甲醇", "timeframe_sec": 600, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.10},
}

# 30分钟波段战队配置 (6 大核心品种)
SQUAD_30M_CONFIG = {
    "SC_IDX": {"symbol": "SC_IDX", "tq_symbol": "KQ.i@INE.sc",   "name": "原油", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.30},
    "LC_IDX": {"symbol": "LC_IDX", "tq_symbol": "KQ.i@GFEX.lc",  "name": "碳酸锂", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.20},
    "J_IDX":  {"symbol": "J_IDX",  "tq_symbol": "KQ.i@DCE.j",    "name": "焦炭", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.15},
    "AL_IDX": {"symbol": "AL_IDX", "tq_symbol": "KQ.i@SHFE.al",  "name": "沪铝", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.15},
    "TA_IDX": {"symbol": "TA_IDX", "tq_symbol": "KQ.i@CZCE.TA",  "name": "PTA", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.10},
    "SI_IDX": {"symbol": "SI_IDX", "tq_symbol": "KQ.i@GFEX.si",  "name": "工业硅", "timeframe_sec": 1800, "stop_atr_mult": 2.5, "trail_atr_mult": 5.0, "weight": 0.10},
}


def get_tq_credentials():
    env_path = PROJECT_ROOT / ".env"
    account = "13800000000"
    password = "redacted_password"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TQ_ACCOUNT="):
                    account = line.split("=", 1)[1].strip()
                elif line.startswith("TQ_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
    return account, password


class TaiChongDualSquadTrader:
    """太冲·弹塑性张量双战队 (10m + 30m) 实时自动化交易守护引擎"""

    def __init__(self, initial_capital: float = 2_000_000.0):
        self.account, self.password = get_tq_credentials()
        self.initial_capital = initial_capital
        self.state = self.load_state()

        logger.info("=" * 80)
        logger.info(f"🚀 初始化「太冲·弹塑性张量」双战队交易守护引擎")
        logger.info(f"💰 初始资金池: {initial_capital:,.2f} 元 (10m战队 100万 + 30m战队 100万)")
        logger.info(f"📊 10m 微观战队: {list(SQUAD_10M_CONFIG.keys())}")
        logger.info(f"📊 30m 波段战队: {list(SQUAD_30M_CONFIG.keys())}")
        logger.info("=" * 80)

    def load_state(self) -> dict[str, Any]:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取状态文件失败，重新初始化: {e}")
        return {
            "initial_capital": self.initial_capital,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "positions": {},
            "performance": {
                "total_trades": 0,
                "win_trades": 0,
                "net_pnl": 0.0,
                "max_drawdown": 0.0,
                "peak_equity": self.initial_capital,
            }
        }

    def save_state(self):
        self.state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def run(self):
        while True:
            try:
                logger.info(f"🔑 正在连接天勤量化 TqSim 虚拟盘网关 ({self.account})...")
                sim = TqSim(init_balance=self.initial_capital)
                api = TqApi(sim, auth=TqAuth(self.account, self.password))
                logger.info("✅ 天勤量化网关连接成功！开始订阅 11 个主力合约 K 线...")

                # 订阅 10m 和 30m K 线数据流
                klines_10m = {}
                klines_30m = {}
                target_pos_tasks = {}

                for sym, cfg in SQUAD_10M_CONFIG.items():
                    tq_sym = cfg["tq_symbol"]
                    klines_10m[sym] = api.get_kline_serial(tq_sym, duration_seconds=600, data_length=300)
                    target_pos_tasks[sym] = TargetPosTask(api, tq_sym)
                    logger.info(f"  [10m] 已订阅 {sym} ({cfg['name']}) -> {tq_sym} 10分钟K线")

                for sym, cfg in SQUAD_30M_CONFIG.items():
                    tq_sym = cfg["tq_symbol"]
                    klines_30m[sym] = api.get_kline_serial(tq_sym, duration_seconds=1800, data_length=300)
                    target_pos_tasks[sym] = TargetPosTask(api, tq_sym)
                    logger.info(f"  [30m] 已订阅 {sym} ({cfg['name']}) -> {tq_sym} 30分钟K线")

                logger.info("🟢 双战队策略实时监控引擎已完全就绪，开始事件循环驱动...")

                last_processed_10m = {sym: 0 for sym in SQUAD_10M_CONFIG}
                last_processed_30m = {sym: 0 for sym in SQUAD_30M_CONFIG}

                while True:
                    api.wait_update()

                    # 1. 驱动 10m 战队
                    for sym, cfg in SQUAD_10M_CONFIG.items():
                        kl = klines_10m[sym]
                        if len(kl) > 35 and api.is_changing(kl.iloc[-1], "datetime"):
                            last_bar_time = kl["datetime"].iloc[-2]
                            if last_bar_time != last_processed_10m[sym]:
                                last_processed_10m[sym] = last_bar_time
                                self.process_bar(sym, "10m", cfg, kl.iloc[:-1], target_pos_tasks[sym], api)

                    # 2. 驱动 30m 战队
                    for sym, cfg in SQUAD_30M_CONFIG.items():
                        kl = klines_30m[sym]
                        if len(kl) > 35 and api.is_changing(kl.iloc[-1], "datetime"):
                            last_bar_time = kl["datetime"].iloc[-2]
                            if last_bar_time != last_processed_30m[sym]:
                                last_processed_30m[sym] = last_bar_time
                                self.process_bar(sym, "30m", cfg, kl.iloc[:-1], target_pos_tasks[sym], api)

            except Exception as e:
                logger.error(f"❌ 交易循环异常断开: {e}", exc_info=True)
                logger.info("⏳ 等待 15 秒后尝试自动重新连接...")
                time.sleep(15)

    def process_bar(self, symbol: str, timeframe: str, cfg: dict[str, Any], kl_df: pd.DataFrame, target_task: TargetPosTask, api: TqApi):
        try:
            df = pd.DataFrame(
                {
                    "open": kl_df["open"].values,
                    "high": kl_df["high"].values,
                    "low": kl_df["low"].values,
                    "close": kl_df["close"].values,
                    "volume": kl_df["volume"].values,
                    "open_interest": kl_df["open_interest"].values if "open_interest" in kl_df else np.zeros(len(kl_df)),
                },
                index=pd.to_datetime(kl_df["datetime"], unit="ns"),
            )

            # 计算太冲微观信号
            signals = calculate_signal(df)
            current_signal = int(signals.iloc[-1])
            curr_price = float(df["close"].iloc[-1])
            curr_time = str(df.index[-1])

            # 计算 ATR 与 SMA5
            atr_s = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
            atr = float(atr_s.rolling(14).mean().iloc[-1])
            sma5 = float(df["close"].rolling(5).mean().iloc[-1])

            pos_info = self.state["positions"].get(symbol, {"pos": 0, "entry_price": 0.0, "entry_time": "", "stop_price": 0.0, "lots": 0})
            current_pos = pos_info["pos"]
            lots = pos_info["lots"]

            spec = ACTIVE_CONTRACT_SPECS.get(symbol, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001})
            multiplier = float(spec.get("multiplier", 10.0))
            tick = float(spec.get("tick", 1.0))

            # 离场判断
            exit_reason = None
            if current_pos > 0:
                if curr_price >= sma5:
                    exit_reason = "take_profit_sma5"
                elif curr_price <= pos_info["stop_price"]:
                    exit_reason = "stop_loss"
                elif current_signal == -1:
                    exit_reason = "reverse_signal"
            elif current_pos < 0:
                if curr_price <= sma5:
                    exit_reason = "take_profit_sma5"
                elif curr_price >= pos_info["stop_price"]:
                    exit_reason = "stop_loss"
                elif current_signal == 1:
                    exit_reason = "reverse_signal"

            if exit_reason and current_pos != 0:
                logger.info(f"🔔 [{timeframe} 战队] {symbol} 平仓信号: {exit_reason} (持仓: {current_pos}手 @ {pos_info['entry_price']:.2f}, 当前价: {curr_price:.2f})")
                target_task.set_target_volume(0)
                pnl = (curr_price - pos_info["entry_price"]) * multiplier * lots * current_pos
                self.record_trade(symbol, timeframe, pos_info["entry_time"], curr_time, "LONG" if current_pos > 0 else "SHORT", lots, pos_info["entry_price"], curr_price, pnl, exit_reason)
                self.state["positions"][symbol] = {"pos": 0, "entry_price": 0.0, "entry_time": "", "stop_price": 0.0, "lots": 0}
                self.save_state()
                current_pos = 0

            # 开仓判断
            if current_pos == 0 and current_signal != 0:
                weight = float(cfg["weight"])
                allocated_fund = 1_000_000.0 * weight
                unit_risk = max(tick * multiplier, 2.5 * atr * multiplier)
                target_lots = max(1, min(50, int(allocated_fund * 0.01 / unit_risk)))

                target_volume = target_lots if current_signal > 0 else -target_lots
                stop_price = curr_price - current_signal * 2.5 * atr

                logger.info(f"🎯 [{timeframe} 战队] {symbol} 触发开仓信号: {'做多' if current_signal > 0 else '做空'} {target_lots}手 @ {curr_price:.2f}, 止损价: {stop_price:.2f}")
                target_task.set_target_volume(target_volume)

                self.state["positions"][symbol] = {
                    "pos": current_signal,
                    "lots": target_lots,
                    "entry_price": curr_price,
                    "entry_time": curr_time,
                    "stop_price": stop_price,
                    "timeframe": timeframe,
                }
                self.save_state()

        except Exception as e:
            logger.error(f"处理 {symbol} ({timeframe}) Bar 异常: {e}", exc_info=True)

    def record_trade(self, symbol: str, timeframe: str, entry_time: str, exit_time: str, side: str, lots: int, entry_p: float, exit_p: float, pnl: float, reason: str):
        row = {
            "symbol": symbol,
            "timeframe": timeframe,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "side": side,
            "lots": lots,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "net_pnl": pnl,
            "exit_reason": reason,
        }
        df_new = pd.DataFrame([row])
        if not TRADES_CSV.exists():
            df_new.to_csv(TRADES_CSV, index=False, encoding="utf-8")
        else:
            df_new.to_csv(TRADES_CSV, mode="a", header=False, index=False, encoding="utf-8")

        perf = self.state["performance"]
        perf["total_trades"] += 1
        if pnl > 0:
            perf["win_trades"] += 1
        perf["net_pnl"] += pnl
        self.save_state()


def main():
    trader = TaiChongDualSquadTrader()
    trader.run()


if __name__ == "__main__":
    main()
