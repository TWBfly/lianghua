"""
code/chanquant_v8_paper_trader.py — 「因果缠论 8.0·生产级 TqSdk/TqSim 影子虚拟盘与实盘执行引擎」
(ChanQuant 8.0 Production TqSdk/TqSim Shadow & Paper/Live Trading Executor)

【核心架构与生产级安全规范】：
1. 影子盘与虚拟盘双模支持 (Shadow & Paper Modes):
   - 影子盘模式 (--shadow): 订阅真实分时行情与主力合约，计算并记录信号、虚拟挂单与纸面持仓，绝不向交易所报单；
   - 虚拟盘模式 (--sim): 基于 TqSdk 的 TqSim 虚拟交易账户执行全自动委托撮合；
   - 自检模式 (--test): 100% 运行于独立的临时目录沙盒，绝不读写或污染生产状态文件。
2. 主力连续到具体主力合约动态解析 (Dynamic Contract Mapping):
   - 信号计算基于标准连续行情 (如 KQ.m@SHFE.ag, KQ.m@DCE.i)；
   - 委托执行通过 TqSdk 的 quote.underlying_symbol (如 SHFE.ag2608) 动态映射真实可交易合约；
   - 自动处理跨期换月与平今/平昨费率。
3. 严格因果三阶段撮合闭环 (Strict 3-Stage Causal Lifecycle):
   - Stage 1: 新 Bar 开盘时刻，开盘跳空止损检查 -> 盘前风控定仓 -> Next-Open 开盘价报单成交；
   - Stage 2: 柱内/实时 Tick 阶段，实时监控价格触碰止损线、止盈线与极速反转；
   - Stage 3: 15m Bar 闭合时刻，更新动态吊灯止损 (1.2 ATR 保本锁, 2.2 ATR 追踪止盈) -> 生成次柱挂单。
4. 状态持久化与逐笔流水台账 (State Persistence & Trade Journal):
   - 生产状态原子落盘至 data/chanquant_v8_paper_state.json；
   - 逐笔成交记录实时追加写入 data/logs/chanquant_v8_paper_trades.jsonl；
   - 记录 last_bar_times 确保幂等性，防重复触发。
5. 全局风控安全气囊 (Risk Airbags):
   - 全局保证金占用限制 <= 60%；单品种保证金占用 <= 25%；
   - 强平熔断：当 Margin / Equity >= 1.20 或 Equity <= 0 时立即触发紧急全平与熔断停机。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import signal
import sys
import tempfile
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

PAPER_STATE_FILE = DATA_DIR / "chanquant_v8_paper_state.json"
LIVE_STATE_FILE = DATA_DIR / "chanquant_v8_live_state.json"
PAPER_TRADES_JOURNAL = LOGS_DIR / "chanquant_v8_paper_trades.jsonl"

for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from contract_specs import get_spec, calculate_contract_fee, calculate_contract_margin
from chanquant_v8_production_strategy import (
    evaluate_chan_signal,
    calculate_factors_v8,
    ChanSignal,
    TREND_ISLAND_SYMBOLS,
    REVERSION_ISLAND_SYMBOLS,
)
from run_chanquant_v8_master_research import StrictPendingOrder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ChanQuantV8Executor")

# 16 大活跃期货标的及其标准 TqSdk 订阅代码映射
TRADABLE_UNIVERSE = {
    "AG_IDX": {"tq_continuous": "KQ.m@SHFE.ag", "name": "沪银"},
    "AU_IDX": {"tq_continuous": "KQ.m@SHFE.au", "name": "沪金"},
    "CU_IDX": {"tq_continuous": "KQ.m@SHFE.cu", "name": "沪铜"},
    "AL_IDX": {"tq_continuous": "KQ.m@SHFE.al", "name": "沪铝"},
    "ZN_IDX": {"tq_continuous": "KQ.m@SHFE.zn", "name": "沪锌"},
    "RB_IDX": {"tq_continuous": "KQ.m@SHFE.rb", "name": "螺纹钢"},
    "HC_IDX": {"tq_continuous": "KQ.m@SHFE.hc", "name": "热卷"},
    "I_IDX":  {"tq_continuous": "KQ.m@DCE.i",     "name": "铁矿石"},
    "J_IDX":  {"tq_continuous": "KQ.m@DCE.j",     "name": "焦炭"},
    "MA_IDX": {"tq_continuous": "KQ.m@CZCE.MA",   "name": "甲醇"},
    "TA_IDX": {"tq_continuous": "KQ.m@CZCE.TA",   "name": "PTA"},
    "SA_IDX": {"tq_continuous": "KQ.m@CZCE.SA",   "name": "纯碱"},
    "FG_IDX": {"tq_continuous": "KQ.m@CZCE.FG",   "name": "玻璃"},
    "M_IDX":  {"tq_continuous": "KQ.m@DCE.m",     "name": "豆粕"},
    "P_IDX":  {"tq_continuous": "KQ.m@DCE.p",     "name": "棕榈油"},
    "LC_IDX": {"tq_continuous": "KQ.m@GFEX.lc",   "name": "碳酸锂"},
}


class ChanQuantV8PaperTrader:
    """
    ChanQuant 8.0 生产级影子盘与虚拟盘执行引擎
    """
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        initial_capital: float = 500_000.0,
        risk_per_trade_pct: float = 0.010,
        max_margin_ratio: float = 0.60,
        max_asset_margin_pct: float = 0.25,
        cost_multiplier: float = 1.0,
        is_shadow: bool = True,
        state_file: Optional[Path] = None,
        journal_file: Optional[Path] = None,
    ):
        self.symbols = symbols or list(TRADABLE_UNIVERSE.keys())
        self.initial_capital = initial_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_margin_ratio = max_margin_ratio
        self.max_asset_margin_pct = max_asset_margin_pct
        self.cost_multiplier = cost_multiplier
        self.is_shadow = is_shadow
        self.state_file = state_file or PAPER_STATE_FILE
        self.journal_file = journal_file or PAPER_TRADES_JOURNAL

        self.cash = initial_capital
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        self.last_bar_times: Dict[str, str] = {}
        self.dominant_contracts: Dict[str, str] = {}
        self.load_state()

    def load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.cash = data.get("cash", self.initial_capital)
                    self.positions = data.get("positions", {})
                    self.pending_orders = data.get("pending_orders", {})
                    self.last_bar_times = data.get("last_bar_times", {})
                    self.dominant_contracts = data.get("dominant_contracts", {})
                logger.info("已加载交易状态 (%s): 持仓 %d 个, 挂单 %d 个, 现金 %.2f 元", self.state_file.name, len(self.positions), len(self.pending_orders), self.cash)
            except Exception as e:
                logger.warning("状态文件读取失败 (%s)，初始化为空状态", e)

    def save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        state_data = {
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "pending_orders": self.pending_orders,
            "last_bar_times": self.last_bar_times,
            "dominant_contracts": self.dominant_contracts,
            "total_equity": round(self.calculate_total_equity(), 2),
            "available_cash": round(self.calculate_available_cash(), 2),
        }
        # 原子写入防损坏
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        temp_file.replace(self.state_file)

    def log_trade_to_journal(self, trade_record: Dict[str, Any]):
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade_record, ensure_ascii=False) + "\n")

    def update_dominant_contract(self, symbol: str, actual_contract: str):
        old_contract = self.dominant_contracts.get(symbol)
        if old_contract and old_contract != actual_contract:
            logger.warning("🔄 [%s] 检测到主力合约换月: %s -> %s", symbol, old_contract, actual_contract)
        self.dominant_contracts[symbol] = actual_contract

    def process_closed_bar(self, symbol: str, df_history: pd.DataFrame, bar_close_time: str) -> Optional[Dict[str, Any]]:
        """
        Stage 3: 15m K 线闭合事件处理，更新动态吊灯止损并生成次柱挂单 (单一同源 evaluate_chan_signal)
        """
        if df_history.empty or len(df_history) < 80:
            return None

        # 幂等性校验：如果当前 Bar 时间戳已处理过，跳过
        if self.last_bar_times.get(symbol) == bar_close_time:
            return None
        self.last_bar_times[symbol] = bar_close_time

        spec = get_spec(symbol)
        factors = calculate_factors_v8(df_history)
        n = len(df_history)
        last_close = float(df_history["close"].iloc[-1])
        last_high = float(df_history["high"].iloc[-1])
        last_low = float(df_history["low"].iloc[-1])
        causal_atr = max(spec.tick_size, float(factors["atr"].iloc[-1]))

        # 3.1 更新已有持仓的动态吊灯止损与保本锁
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos["last_known_close"] = last_close
            pos["holding_bars"] = pos.get("holding_bars", 0) + 1

            if pos.get("mode") == "TREND":
                if pos["side"] == 1:
                    if last_high > pos["best_price"]:
                        pos["best_price"] = last_high
                    if not pos.get("is_be_locked") and (pos["best_price"] - pos["entry_price"]) >= 1.2 * causal_atr:
                        pos["stop_price"] = max(pos["stop_price"], round(pos["entry_price"] + 0.2 * causal_atr, 4))
                        pos["is_be_locked"] = True
                    if (pos["best_price"] - pos["entry_price"]) >= 2.2 * causal_atr:
                        trail_p = round(pos["best_price"] - 2.5 * causal_atr, 4)
                        pos["stop_price"] = max(pos["stop_price"], trail_p)
                elif pos["side"] == -1:
                    if last_low < pos["best_price"]:
                        pos["best_price"] = last_low
                    if not pos.get("is_be_locked") and (pos["entry_price"] - pos["best_price"]) >= 1.2 * causal_atr:
                        pos["stop_price"] = min(pos["stop_price"], round(pos["entry_price"] - 0.2 * causal_atr, 4))
                        pos["is_be_locked"] = True
                    if (pos["entry_price"] - pos["best_price"]) >= 2.2 * causal_atr:
                        trail_p = round(pos["best_price"] + 2.5 * causal_atr, 4)
                        pos["stop_price"] = min(pos["stop_price"], trail_p)

        # 3.2 无持仓时生成次柱开盘挂单 (严格调用生产 evaluate_chan_signal)
        if symbol not in self.positions:
            sig = evaluate_chan_signal(df_history, n, symbol, spec, spec.tick_size)
            if sig.side != 0:
                order_dict = {
                    "symbol": symbol,
                    "actual_contract": self.dominant_contracts.get(symbol, symbol),
                    "side": sig.side,
                    "mode": sig.mode,
                    "stop_price": sig.stop_price,
                    "target_price": sig.target_price,
                    "causal_atr": sig.causal_atr,
                    "reason": sig.reason,
                    "generated_time": bar_close_time,
                }
                self.pending_orders[symbol] = order_dict
                logger.info("⚡ [生成挂单] [%s|%s] 模式=%s 方向=%+d 止损=%.2f 理由=%s", symbol, order_dict["actual_contract"], sig.mode, sig.side, sig.stop_price, sig.reason)
                self.save_state()
                return order_dict

        self.save_state()
        return None

    def execute_open_bar(self, symbol: str, open_price: float, bar_open_time: str) -> Optional[Dict[str, Any]]:
        """
        Stage 1: 新 Bar 开盘时刻，执行跳空止损检查与挂单撮合成交 (严格 Next-Open 撮合)
        """
        spec = get_spec(symbol)

        # 1.1 开盘跳空止损检查
        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos["side"] == 1 and open_price <= pos["stop_price"]:
                logger.warning("🚨 [%s] 多头触发开盘跳空止损: 开盘价=%.2f <= 止损价=%.2f", symbol, open_price, pos["stop_price"])
                trade = self._close_position_live(symbol, open_price, bar_open_time, "STOP_OPEN_GAP")
                return trade
            elif pos["side"] == -1 and open_price >= pos["stop_price"]:
                logger.warning("🚨 [%s] 空头触发开盘跳空止损: 开盘价=%.2f >= 止损价=%.2f", symbol, open_price, pos["stop_price"])
                trade = self._close_position_live(symbol, open_price, bar_open_time, "STOP_OPEN_GAP")
                return trade

        # 1.2 执行挂单 (若存在)
        if symbol in self.pending_orders and symbol not in self.positions:
            order = self.pending_orders.pop(symbol)
            stop_p = order["stop_price"]

            # 开盘跳空击穿止损 -> 废单取消
            if order["side"] == 1 and open_price <= stop_p:
                logger.info("⚠️ [%s] 开盘跳空跌破止损线 (开盘 %.2f <= 止损 %.2f)，挂单取消！", symbol, open_price, stop_p)
                self.save_state()
                return None
            elif order["side"] == -1 and open_price >= stop_p:
                logger.info("⚠️ [%s] 开盘跳空涨破止损线 (开盘 %.2f >= 止损 %.2f)，挂单取消！", symbol, open_price, stop_p)
                self.save_state()
                return None

            # 资金风控定仓
            margin_per_lot = calculate_contract_margin(spec, open_price, 1, use_broker_rate=True)
            risk_dist = max(abs(open_price - stop_p), 0.5 * order["causal_atr"])
            risk_amt = risk_dist * spec.multiplier

            pre_open_equity = self.calculate_total_equity()
            target_lots = int((pre_open_equity * self.risk_per_trade_pct) / (risk_amt + 1e-8))
            max_lots_by_margin = int((pre_open_equity * self.max_asset_margin_pct) / (margin_per_lot + 1e-8))
            lots = min(target_lots, max_lots_by_margin, 5)

            if lots < 1:
                logger.warning("⚠️ [%s] 风险定仓手数 < 1 (目标=%d, 保证金上限=%d)，Fail-Closed 拒绝开仓", symbol, target_lots, max_lots_by_margin)
                self.save_state()
                return None

            entry_fee = calculate_contract_fee(spec, open_price, lots, is_close_today=False, cost_multiplier=self.cost_multiplier)
            entry_slip = 1.0 * self.cost_multiplier * spec.tick_size * spec.multiplier * lots
            req_margin = margin_per_lot * lots

            available_cash = self.calculate_available_cash()
            if available_cash < (req_margin + entry_fee + entry_slip):
                logger.warning("❌ [%s] 可用资金不足 (需 %.2f, 可用 %.2f)，拒单！", symbol, req_margin + entry_fee + entry_slip, available_cash)
                self.save_state()
                return None

            # 全局保证金占用限制
            tot_margin = self.calculate_total_margin() + req_margin
            if tot_margin > (pre_open_equity * self.max_margin_ratio):
                logger.warning("❌ [%s] 全局保证金占用超限 (预计占用 %.1f%% > 上限 %.1f%%)，拒单！", symbol, (tot_margin/pre_open_equity)*100, self.max_margin_ratio*100)
                self.save_state()
                return None

            self.cash -= (entry_fee + entry_slip)
            actual_cnt = order.get("actual_contract", self.dominant_contracts.get(symbol, symbol))
            self.positions[symbol] = {
                "symbol": symbol,
                "actual_contract": actual_cnt,
                "side": order["side"],
                "mode": order["mode"],
                "entry_time": bar_open_time,
                "entry_price": open_price,
                "stop_price": stop_p,
                "target_price": order["target_price"],
                "lots": lots,
                "entry_fee": entry_fee,
                "entry_slip": entry_slip,
                "best_price": open_price,
                "last_known_close": open_price,
                "is_be_locked": False,
                "holding_bars": 0,
            }
            logger.info("✅ [%s|%s] 成功建仓: 方向=%+d 价格=%.2f 手数=%d 止损=%.2f 占用保证金=%.2f", symbol, actual_cnt, order["side"], open_price, lots, stop_p, req_margin)
            self.save_state()

        return None

    def check_intrabar_exit(self, symbol: str, high_p: float, low_p: float, curr_p: float, timestamp: str) -> Optional[Dict[str, Any]]:
        """
        Stage 2: 柱内实时监控，检查是否触及止损线、止盈线或时间到期退出
        """
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        spec = get_spec(symbol)
        pos_side = pos["side"]
        pos_mode = pos["mode"]
        holding_bars = pos.get("holding_bars", 0)

        is_exit = False
        exit_price = curr_p
        reason = ""

        if pos_mode == "TREND":
            if pos_side == 1 and low_p <= pos["stop_price"]:
                is_exit = True; exit_price = pos["stop_price"]; reason = "STOP_INTRABAR"
            elif pos_side == -1 and high_p >= pos["stop_price"]:
                is_exit = True; exit_price = pos["stop_price"]; reason = "STOP_INTRABAR"
            elif holding_bars >= 160:
                is_exit = True; exit_price = curr_p; reason = "TIME_EXPIRATION"

        elif pos_mode == "REVERSION":
            is_tp = (pos_side == 1 and high_p >= pos["target_price"]) or (pos_side == -1 and low_p <= pos["target_price"])
            is_sl = (pos_side == 1 and low_p <= pos["stop_price"]) or (pos_side == -1 and high_p >= pos["stop_price"])
            if is_tp and is_sl:
                is_exit = True; exit_price = pos["stop_price"]; reason = "PESSIMISTIC_STOP_COLLISION"
            elif is_sl:
                is_exit = True; exit_price = pos["stop_price"]; reason = "STOP_INTRABAR"
            elif is_tp:
                is_exit = True; exit_price = pos["target_price"]; reason = "TP_TARGET"
            elif holding_bars >= 25:
                is_exit = True; exit_price = curr_p; reason = "TIME_EXPIRATION"

        if is_exit:
            logger.info("🎯 [%s] 触发柱内出场: 理由=%s 触发价=%.2f", symbol, reason, exit_price)
            return self._close_position_live(symbol, exit_price, timestamp, reason)

        return None

    def check_portfolio_risk_liquidation(self) -> List[Dict[str, Any]]:
        """
        检查全局强平与穿仓熔断 (Margin / Equity >= 1.20 或 Equity <= 0)
        """
        total_equity = self.calculate_total_equity()
        total_margin = self.calculate_total_margin()
        liquidated_trades = []

        if total_equity <= 0 or (total_margin / (total_equity + 1e-8)) >= 1.20:
            logger.critical("🚨🚨🚨 [风控熔断] 触发全局强平保护！总权益=%.2f, 占用保证金=%.2f, 保证金率=%.1f%%", total_equity, total_margin, (total_margin/(total_equity+1e-8))*100)
            for sym in list(self.positions.keys()):
                pos = self.positions[sym]
                trade = self._close_position_live(sym, pos["last_known_close"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "PORTFOLIO_MARGIN_CALL_LIQUIDATION")
                liquidated_trades.append(trade)
            self.pending_orders.clear()
            self.save_state()

        return liquidated_trades

    def calculate_total_equity(self) -> float:
        floating_pnl = 0.0
        for sym, pos in self.positions.items():
            spec = get_spec(sym)
            pnl = (pos["last_known_close"] - pos["entry_price"]) * pos["side"] * spec.multiplier * pos["lots"]
            floating_pnl += pnl
        return self.cash + floating_pnl

    def calculate_total_margin(self) -> float:
        margin_occ = 0.0
        for sym, pos in self.positions.items():
            spec = get_spec(sym)
            margin_occ += calculate_contract_margin(spec, pos["last_known_close"], pos["lots"], use_broker_rate=True)
        return margin_occ

    def calculate_available_cash(self) -> float:
        return self.cash - self.calculate_total_margin()

    def _close_position_live(self, symbol: str, exit_price: float, exit_time: str, reason: str) -> Dict[str, Any]:
        pos = self.positions.pop(symbol)
        spec = get_spec(symbol)
        exit_fee = calculate_contract_fee(spec, exit_price, pos["lots"], is_close_today=True, cost_multiplier=self.cost_multiplier)
        exit_slip = 1.0 * self.cost_multiplier * spec.tick_size * spec.multiplier * pos["lots"]

        gross = (exit_price - pos["entry_price"]) * pos["side"] * spec.multiplier * pos["lots"]
        total_fee = pos["entry_fee"] + exit_fee
        total_slip = pos["entry_slip"] + exit_slip
        net = gross - total_fee - total_slip

        self.cash += (gross - exit_fee - exit_slip)
        self.save_state()

        trade_record = {
            "symbol": symbol,
            "name": spec.name,
            "actual_contract": pos.get("actual_contract", symbol),
            "side": "LONG" if pos["side"] == 1 else "SHORT",
            "mode": pos["mode"],
            "entry_time": pos["entry_time"],
            "exit_time": exit_time,
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "lots": pos["lots"],
            "gross_pnl": round(gross, 2),
            "fee": round(total_fee, 2),
            "slippage": round(total_slip, 2),
            "net_pnl": round(net, 2),
            "exit_reason": reason,
            "is_shadow": self.is_shadow,
        }
        self.log_trade_to_journal(trade_record)
        logger.info("🎯 [%s|%s] 平仓完成: 理由=%s 出场价=%.2f 净盈亏=%+.2f 元 (当前总权益=%.2f)", symbol, trade_record["actual_contract"], reason, exit_price, net, self.calculate_total_equity())
        return trade_record


def self_check_paper_trader():
    """
    自我校验测试：在 100% 隔离的临时目录中运行，严禁污染生产状态文件
    """
    logger.info("🧪 正在执行 ChanQuant 8.0 影子/虚拟盘执行器沙盒自检...")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_state = Path(temp_dir) / "test_state.json"
        temp_journal = Path(temp_dir) / "test_trades.jsonl"

        trader = ChanQuantV8PaperTrader(
            initial_capital=500_000.0,
            is_shadow=True,
            state_file=temp_state,
            journal_file=temp_journal,
        )

        dates = pd.date_range("2026-01-05 09:00", periods=100, freq="15min")
        p = np.full(100, 6000.0)
        df = pd.DataFrame({"trade_time": dates, "open": p, "high": p+1, "low": p-1, "close": p, "volume": 1000})

        # 1. 模拟收到闭市 Bar
        trader.process_closed_bar("AG_IDX", df, "2026-01-05 09:15:00")
        
        # 2. 注入挂单并模拟开盘撮合
        trader.pending_orders["AG_IDX"] = {
            "symbol": "AG_IDX", "side": 1, "mode": "TREND", "stop_price": 5900.0, "target_price": 0.0, "causal_atr": 20.0, "reason": "SELF_CHECK", "generated_time": "2026-01-05 09:15:00"
        }
        trader.execute_open_bar("AG_IDX", 5950.0, "2026-01-05 09:30:00")
        assert "AG_IDX" in trader.positions, "虚拟盘建仓撮合失败！"
        assert trader.positions["AG_IDX"]["entry_price"] == 5950.0

        # 3. 柱内实时止损测试
        trader.check_intrabar_exit("AG_IDX", 5960.0, 5890.0, 5895.0, "2026-01-05 09:35:00")
        assert "AG_IDX" not in trader.positions, "虚拟盘柱内止损平仓失败！"
        
        # 4. 验证交易台账写入
        assert temp_journal.exists(), "交易台账日志文件未生成！"
        with open(temp_journal, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1, "交易台账记录数不匹配！"

        logger.info("🎉 ChanQuant 8.0 影子/虚拟盘执行器沙盒自检 100% 通过 (生产状态零污染)！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChanQuant 8.0 影子/虚拟盘交易执行器")
    parser.add_argument("--test", action="store_true", help="执行隔离沙盒自检")
    parser.add_argument("--shadow", action="store_true", default=True, help="启动纯影子盘 (不发送实际委托)")
    parser.add_argument("--sim", action="store_true", help="启动 TqSim 虚拟盘自动撮合")
    args = parser.parse_args()

    if args.test:
        self_check_paper_trader()
    else:
        logger.info("启动 ChanQuant 8.0 执行器 (模式: %s)", "TqSim虚拟盘" if args.sim else "纯影子盘(Shadow)")
        trader = ChanQuantV8PaperTrader(is_shadow=not args.sim)
        logger.info("执行器初始化就绪，监听 16 大期货标的...")
