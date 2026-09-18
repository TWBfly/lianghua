"""
code/deploy_taiyin_calendar_trader.py — 【太阴·跨期套利】黄金白银 15m 跨期套利 TqSim 虚拟盘自动化撮合守护引擎
Taiyin 15m Gold & Silver Calendar Spread TqSim Virtual Trading Daemon

核心设计与安全规范：
1. 真实虚拟盘撮合 (TqSim): 严禁假回测，直接对接天勤官方 TqSim 虚拟交易账户进行实时盘口撮合与双腿持仓管理；
2. 标的池: 黄金跨期 (SHFE.au2606 / SHFE.au2612) + 白银跨期 (SHFE.ag2606 / SHFE.ag2612)；
3. 严格因果时序与状态机: 15m 完成柱生成信号，下一根 K 线开盘通过 TargetPosTask 自动对冲下单；
4. 状态与台账持久化: 状态记录于 data/taiyin_calendar_state.json，交易明细同步至 SQLite futures_trade_records 与 CSV 台账。
"""

from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import datetime
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CODE_DIR))

from tqsdk import TqApi, TqAuth, TqSim, TargetPosTask

from taiyin_calendar_spread_15m import CARRY_COST_REGISTRY, CommodityCarryCostProfile
from technical_indicators import calculate_ehlers_supersmoother, calculate_kalman_velocity_tracker

STATE_FILE = PROJECT_ROOT / "data/taiyin_calendar_state.json"
LOG_DIR = PROJECT_ROOT / "data/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "taiyin_calendar_trader.log"
TRADES_CSV = LOG_DIR / "taiyin_daily_trades.csv"
DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

logger = logging.getLogger("TaiyinCalendarTrader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)


from runtime_credentials import load_required_credentials


def get_tq_credentials() -> Tuple[str, str]:
    """从 .env 获取天勤量化账号密码"""
    return load_required_credentials(PROJECT_ROOT / ".env")


# 核心贵金属跨期交易标的配置
TAIYIN_PAIRS_CONFIG = [
    {
        "symbol": "AU_IDX",
        "name": "黄金 2606-2612 跨期套利",
        "near": "SHFE.au2606",
        "far": "SHFE.au2612",
        "days_between": 183,
        "default_lots": 1,
        "multiplier": 1000.0,
        "tick_size": 0.02,
        "window": 40,
        "z_entry": 1.8,
        "z_exit": 0.2,
        "z_stop": 3.5,
    },
    {
        "symbol": "AG_IDX",
        "name": "白银 2606-2612 跨期套利",
        "near": "SHFE.ag2606",
        "far": "SHFE.ag2612",
        "days_between": 183,
        "default_lots": 2,
        "multiplier": 15.0,
        "tick_size": 1.0,
        "window": 40,
        "z_entry": 1.8,
        "z_exit": 0.2,
        "z_stop": 3.5,
    },
]


class TaiyinCalendarVirtualTrader:
    """太阴 15m 跨期套利 TqSim 虚拟盘守护引擎"""

    def __init__(self, initial_balance: float = 1_000_000.0):
        self.account, self.password = get_tq_credentials()
        self.initial_balance = initial_balance
        self.strategy_id = "taiyin_calendar_15m"
        self.strategy_state: Dict[str, Any] = {}
        self.load_state()
        self.init_trade_db()

    def init_trade_db(self):
        """初始化交易记录数据库表"""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS futures_trade_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                dominant_contract TEXT NOT NULL,
                direction TEXT NOT NULL,
                offset TEXT NOT NULL,
                action TEXT NOT NULL,
                entry_time TEXT,
                entry_price REAL,
                exit_time TEXT,
                exit_price REAL,
                lots INTEGER,
                pnl REAL DEFAULT 0.0,
                pnl_pct REAL DEFAULT 0.0,
                entry_reason TEXT,
                exit_reason TEXT,
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"初始化数据库表失败: {e}")

    def load_state(self):
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    self.strategy_state = json.load(f)
                logger.info(f"💾 成功加载历史跨期状态: {list(self.strategy_state.keys())}")
            except Exception as e:
                logger.error(f"读取状态文件失败: {e}")
                self.strategy_state = {}

        for cfg in TAIYIN_PAIRS_CONFIG:
            sym = cfg["symbol"]
            if sym not in self.strategy_state:
                self.strategy_state[sym] = {
                    "pos": 0,  # 0: 空仓, 1: 正套 (买近卖远), -1: 反套 (卖近买远)
                    "trade_id": None,
                    "near_contract": cfg["near"],
                    "far_contract": cfg["far"],
                    "lots": cfg["default_lots"],
                    "entry_spread": 0.0,
                    "entry_time": "-",
                    "entry_near_price": 0.0,
                    "entry_far_price": 0.0,
                    "current_spread": 0.0,
                    "current_zscore": 0.0,
                    "last_processed_dt": "-",
                }

    def save_state(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.strategy_state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def log_trade_to_csv(self, trade_record: dict):
        file_exists = TRADES_CSV.exists()
        if "pnl" in trade_record and "net_pnl" not in trade_record:
            trade_record["net_pnl"] = trade_record["pnl"]
        df = pd.DataFrame([trade_record])
        df.to_csv(TRADES_CSV, mode="a", header=not file_exists, index=False, encoding="utf-8-sig")

    def log_entry_db(self, sym: str, cfg: dict, direction: str, entry_spread: float, entry_time: str, reason: str) -> int:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
            INSERT INTO futures_trade_records 
            (strategy_id, symbol, dominant_contract, direction, offset, action, entry_time, entry_price, lots, entry_reason, reason)
            VALUES (?, ?, ?, ?, '开仓', 'ENTRY', ?, ?, ?, ?, ?)
            """, (
                self.strategy_id,
                sym,
                f"{cfg['near']}/{cfg['far']}",
                direction,
                entry_time,
                entry_spread,
                cfg["default_lots"],
                reason,
                reason
            ))
            trade_id = c.lastrowid
            conn.commit()
            conn.close()
            return trade_id
        except Exception as e:
            logger.error(f"写入开仓记录失败: {e}")
            return int(time.time())

    def log_exit_db(self, trade_id: int, exit_spread: float, exit_time: str, pnl: float, pnl_pct: float, reason: str):
        if not trade_id:
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
            UPDATE futures_trade_records 
            SET offset='平仓', action='EXIT', exit_time=?, exit_price=?, pnl=?, pnl_pct=?, exit_reason=?, reason=?
            WHERE id=?
            """, (
                exit_time,
                exit_spread,
                pnl,
                pnl_pct,
                reason,
                reason,
                trade_id
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"更新平仓记录失败: {e}")

    def run(self):
        masked_user = f"{self.account[:3]}***{self.account[-2:]}" if len(self.account) > 5 else "***"
        logger.info("=" * 80)
        logger.info(f"🚀 【太阴·北斗】15m 黄金白银跨期套利 TqSim 虚拟盘守护引擎启动 (Account: {masked_user})")
        logger.info(f"💰 虚拟盘初始资金: ¥{self.initial_balance:,.2f} | 交易周期: 15m (900秒)")
        logger.info("📌 撮合模式: 真实 TqSim 订单撮合 | 双腿独立 TargetPosTask 自动对冲")
        logger.info("=" * 80)

        # 1. 建立 TqApi 虚拟盘连接
        sim = TqSim(init_balance=self.initial_balance)
        api = TqApi(sim, auth=TqAuth(self.account, self.password))

        # 2. 订阅行情与 K 线
        pair_contexts = {}
        for cfg in TAIYIN_PAIRS_CONFIG:
            sym = cfg["symbol"]
            near = cfg["near"]
            far = cfg["far"]
            logger.info(f"📡 正在订阅跨期合约对: {cfg['name']} ({near} vs {far})...")

            quote_near = api.get_quote(near)
            quote_far = api.get_quote(far)
            klines_near = api.get_kline_serial(near, duration_seconds=900, data_length=120)
            klines_far = api.get_kline_serial(far, duration_seconds=900, data_length=120)
            target_pos_near = TargetPosTask(api, near)
            target_pos_far = TargetPosTask(api, far)

            pair_contexts[sym] = {
                "cfg": cfg,
                "quote_near": quote_near,
                "quote_far": quote_far,
                "klines_near": klines_near,
                "klines_far": klines_far,
                "target_pos_near": target_pos_near,
                "target_pos_far": target_pos_far,
            }

        logger.info("✅ 全部贵金属跨期行情订阅完成，开始进入主事件循环...\n")

        last_heartbeat = time.time()

        try:
            while True:
                api.wait_update()

                # 每 60 秒打印一次心跳
                if time.time() - last_heartbeat > 60.0:
                    account_info = api.get_account()
                    logger.info(
                        f"💓 [心跳] 静态权益: ¥{account_info.balance:,.2f} | 动态权益: ¥{account_info.float_profit + account_info.balance:,.2f} | "
                        f"可用资金: ¥{account_info.available:,.2f} | 保证金: ¥{account_info.margin:,.2f}"
                    )
                    last_heartbeat = time.time()

                now_dt = datetime.datetime.now()
                now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

                for sym, ctx in pair_contexts.items():
                    cfg = ctx["cfg"]
                    klines_near = ctx["klines_near"]
                    klines_far = ctx["klines_far"]
                    quote_near = ctx["quote_near"]
                    quote_far = ctx["quote_far"]
                    target_near = ctx["target_pos_near"]
                    target_far = ctx["target_pos_far"]

                    if len(klines_near) < cfg["window"] + 5 or len(klines_far) < cfg["window"] + 5:
                        continue

                    # 获取已完成的最后一根 15m K 线时间戳
                    last_kline_time = datetime.datetime.fromtimestamp(klines_near.iloc[-1]["datetime"] / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                    state = self.strategy_state[sym]

                    # 实时价差计算
                    real_near_p = quote_near.last_price
                    real_far_p = quote_far.last_price
                    if real_near_p == 0 or real_far_p == 0 or np.isnan(real_near_p) or np.isnan(real_far_p):
                        continue

                    current_spread = real_near_p - real_far_p
                    state["current_spread"] = round(current_spread, 3)

                    # 构建历史对齐价差序列 (前 N-1 根为完成柱收盘价)
                    df_n = pd.DataFrame({"close": klines_near["close"]})
                    df_f = pd.DataFrame({"close": klines_far["close"]})
                    raw_spreads = (df_n["close"] - df_f["close"]).dropna()

                    if len(raw_spreads) < cfg["window"]:
                        continue

                    # 计算滤波后价差与 Z-Score
                    smooth_s = calculate_ehlers_supersmoother(raw_spreads, period=4)
                    s_ma = float(smooth_s.rolling(cfg["window"]).mean().iloc[-1])
                    s_std = float(smooth_s.rolling(cfg["window"]).std().iloc[-1]) + 1e-6
                    zscore = (smooth_s.iloc[-1] - s_ma) / s_std
                    state["current_zscore"] = round(zscore, 2)

                    pos = state["pos"]
                    lots = cfg["default_lots"]
                    mult = cfg["multiplier"]

                    # 仅在 15m Bar 完结或发生有效信号时进行决策
                    if last_kline_time == state.get("last_processed_dt"):
                        continue

                    # ----------------------------------------------------
                    # 1. 开仓扫描
                    # ----------------------------------------------------
                    if pos == 0:
                        # 正套 (Bull Spread): 买近卖远 (Z <= -1.8)
                        if zscore <= -cfg["z_entry"]:
                            reason = f"太阴正套触发: 跨期价差过度贴水 (Z={zscore:.2f} <= -{cfg['z_entry']:.2f}, 价差={current_spread:.2f})"
                            logger.info(f"🎯 [{cfg['name']}] 开仓信号: {reason}")
                            trade_id = self.log_entry_db(sym, cfg, "BUY_SPREAD (正套: 买近卖远)", current_spread, now_str, reason)

                            # TqSim 下单: 买近卖远
                            target_near.set_target_volume(lots)
                            target_far.set_target_volume(-lots)

                            state["pos"] = 1
                            state["trade_id"] = trade_id
                            state["entry_spread"] = current_spread
                            state["entry_time"] = now_str
                            state["entry_near_price"] = real_near_p
                            state["entry_far_price"] = real_far_p
                            state["last_processed_dt"] = last_kline_time
                            self.save_state()

                            self.log_trade_to_csv({
                                "strategy_id": self.strategy_id, "symbol": sym, "pair": cfg["name"],
                                "action": "ENTRY_BUY_SPREAD", "time": now_str, "spread": current_spread,
                                "lots": lots, "near_p": real_near_p, "far_p": real_far_p, "reason": reason
                            })

                        # 反套 (Bear Spread): 卖近买远 (Z >= +2.0)
                        elif zscore >= (cfg["z_entry"] + 0.2):
                            reason = f"太阴反套触发: 跨期价差过度升水 (Z={zscore:.2f} >= {cfg['z_entry']+0.2:.2f}, 价差={current_spread:.2f})"
                            logger.info(f"🎯 [{cfg['name']}] 开仓信号: {reason}")
                            trade_id = self.log_entry_db(sym, cfg, "SELL_SPREAD (反套: 卖近买远)", current_spread, now_str, reason)

                            # TqSim 下单: 卖近买远
                            target_near.set_target_volume(-lots)
                            target_far.set_target_volume(lots)

                            state["pos"] = -1
                            state["trade_id"] = trade_id
                            state["entry_spread"] = current_spread
                            state["entry_time"] = now_str
                            state["entry_near_price"] = real_near_p
                            state["entry_far_price"] = real_far_p
                            state["last_processed_dt"] = last_kline_time
                            self.save_state()

                            self.log_trade_to_csv({
                                "strategy_id": self.strategy_id, "symbol": sym, "pair": cfg["name"],
                                "action": "ENTRY_SELL_SPREAD", "time": now_str, "spread": current_spread,
                                "lots": lots, "near_p": real_near_p, "far_p": real_far_p, "reason": reason
                            })

                    # ----------------------------------------------------
                    # 2. 平仓与风险管理
                    # ----------------------------------------------------
                    elif pos == 1:  # 当前持有多头正套 (买近卖远)
                        pnl = (current_spread - state["entry_spread"]) * mult * lots
                        pnl_pct = round(pnl / (abs(state["entry_spread"]) * mult * lots + 1e-6) * 100.0, 2)

                        # 正常止盈: Z 回归中轨 (Z >= -0.2)
                        exit_signal = zscore >= -cfg["z_exit"]
                        # 硬止损: Z 逆向突破 -3.5 或 单笔浮亏超 8000 元
                        stop_signal = (zscore <= -cfg["z_stop"]) or (pnl <= -8000.0)

                        if exit_signal or stop_signal:
                            reason = f"正套平仓: {'均值回归止盈 (Z >= -0.20)' if exit_signal else '触及极值硬止损'}"
                            logger.info(f"🛑 [{cfg['name']}] 平仓执行: {reason} | 净盈亏: ¥{pnl:,.2f}")

                            # TqSim 全平对冲仓位
                            target_near.set_target_volume(0)
                            target_far.set_target_volume(0)

                            self.log_exit_db(state["trade_id"], current_spread, now_str, pnl, pnl_pct, reason)
                            self.log_trade_to_csv({
                                "strategy_id": self.strategy_id, "symbol": sym, "pair": cfg["name"],
                                "action": "EXIT_BUY_SPREAD", "time": now_str, "spread": current_spread,
                                "lots": lots, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason
                            })

                            state["pos"] = 0
                            state["trade_id"] = None
                            state["last_processed_dt"] = last_kline_time
                            self.save_state()

                    elif pos == -1:  # 当前持有空头反套 (卖近买远)
                        pnl = (state["entry_spread"] - current_spread) * mult * lots
                        pnl_pct = round(pnl / (abs(state["entry_spread"]) * mult * lots + 1e-6) * 100.0, 2)

                        # 正常止盈: Z 溢价回落 (Z <= +0.2)
                        exit_signal = zscore <= cfg["z_exit"]
                        # 硬止损: Z 逆向升水 +3.5 或 单笔浮亏超 8000 元
                        stop_signal = (zscore >= cfg["z_stop"]) or (pnl <= -8000.0)

                        if exit_signal or stop_signal:
                            reason = f"反套平仓: {'溢价回归止盈 (Z <= 0.20)' if exit_signal else '现货逼仓硬止损'}"
                            logger.info(f"🛑 [{cfg['name']}] 平仓执行: {reason} | 净盈亏: ¥{pnl:,.2f}")

                            # TqSim 全平对冲仓位
                            target_near.set_target_volume(0)
                            target_far.set_target_volume(0)

                            self.log_exit_db(state["trade_id"], current_spread, now_str, pnl, pnl_pct, reason)
                            self.log_trade_to_csv({
                                "strategy_id": self.strategy_id, "symbol": sym, "pair": cfg["name"],
                                "action": "EXIT_SELL_SPREAD", "time": now_str, "spread": current_spread,
                                "lots": lots, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason
                            })

                            state["pos"] = 0
                            state["trade_id"] = None
                            state["last_processed_dt"] = last_kline_time
                            self.save_state()

        except KeyboardInterrupt:
            logger.info("🛑 收到用户中断信号，正在关闭交易引擎...")
        except Exception as e:
            logger.error(f"❌ 交易引擎运行时异常: {e}", exc_info=True)
        finally:
            api.close()
            logger.info("👋 TqApi 连接已安全关闭。")


if __name__ == "__main__":
    trader = TaiyinCalendarVirtualTrader()
    trader.run()
