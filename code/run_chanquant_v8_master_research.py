"""
code/run_chanquant_v8_master_research.py — 工业级因果缠论 8.0 严格挂单撮合·全账本复算·持续风控科研审计引擎

【严格量化审计与系统级约束】：
1. 真正 Pre-Generated Pending Orders (彻底消除 Same-Open Lookahead):
   Stage 3 (收盘): 依据已闭合柱特征生成次柱挂单 PendingOrder，锁定方向、止损与目标；
   Stage 1 (开盘): 依据 Pre-Open 资金定仓并在开盘价严格撮合成交，若开盘跳空跌破止损则废单取消；
   Stage 2 (柱内): 悲观止损/止盈碰撞撮合 (止损优先)；
   Stage 3 (收盘): 持续风控监控 (穿仓/强平检测)、更新动态吊灯、记录逐柱 M2M 净值。
2. 持续风险监控与强平/破产熔断 (Continuous Risk Monitoring & Liquidation):
   逐柱持续监控 Equity <= 0 (破产) 或 Margin/Equity >= 1.20 (券商强平线)，触发时市价强平并终止交易。
3. 保存完整可复算账本 (Complete Recomputable Ledger in JSON):
   JSON 报告完整持久化逐笔 trades 记录、逐柱 equity_history、数据 SHA256、代码 Git 状态与参数快照。
4. 真实与严谨披露 (Academic Honesty & Transparency):
   如实披露 1x vs 3x 收益结构、Top 3 尾部交易贡献占比及各时序切片表现。
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from contract_specs import get_spec, calculate_contract_fee, calculate_contract_margin
from technical_indicators import calculate_atr
from causal_chan_engine import CausalChanEngine
try:
    from strategies.chanquant_v8_production_strategy import (
        evaluate_chan_signal,
        calculate_factors_v8,
        ChanSignal,
        TREND_ISLAND_SYMBOLS,
        REVERSION_ISLAND_SYMBOLS,
        STRATEGY_NAME,
        STRATEGY_DESCRIPTION,
    )
except ImportError:
    from chanquant_v8_production_strategy import (
        evaluate_chan_signal,
        calculate_factors_v8,
        ChanSignal,
        TREND_ISLAND_SYMBOLS,
        REVERSION_ISLAND_SYMBOLS,
        STRATEGY_NAME,
        STRATEGY_DESCRIPTION,
    )

from unified_backtest_pipeline import UnifiedDataProvider, round_to_tick, REPORTS_DIR
from backtest_validator import wilson_score_interval, grade_reliability, GRADE_A, GRADE_B, GRADE_F


ALL_COMMODITIES = [
    "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "JM_IDX",
    "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "AG_IDX", "AU_IDX",
    "TA_IDX", "MA_IDX", "SA_IDX", "FG_IDX", "SC_IDX",
    "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX", "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
]


@dataclass
class StrictPendingOrder:
    symbol: str
    side: int  # +1 Long, -1 Short
    mode: str  # 'TREND' or 'REVERSION'
    stop_price: float
    target_price: float
    causal_atr: float
    reason: str
    generated_time: str


@dataclass
class StrictPositionV8:
    symbol: str
    side: int  # +1 Long, -1 Short
    mode: str  # 'TREND' or 'REVERSION'
    entry_time: str
    entry_price: float
    stop_price: float
    target_price: float
    lots: int
    entry_bar_idx: int
    entry_fee: float
    entry_slip: float
    best_price: float
    last_known_close: float
    is_be_locked: bool = False


@dataclass
class StrictTradeRecordV8:
    symbol: str
    name: str
    side: str
    mode: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    lots: int
    holding_bars: int
    gross_pnl: float
    fee: float
    slippage: float
    net_pnl: float
    exit_reason: str
    is_oos: bool
    slice_id: int = 0


class StrictCausalSharedPortfolioEngine:
    """
    工业级严格事件时序·单账户财务对账·多品种共享资金池量化引擎
    """
    def __init__(
        self,
        initial_capital: float = 500_000.0,
        cost_multiplier: float = 1.0,
        max_margin_ratio: float = 0.70,
        risk_per_trade_pct: float = 0.010,
        max_asset_margin_pct: float = 0.25,
    ):
        self.initial_capital = initial_capital
        self.cost_multiplier = cost_multiplier
        self.max_margin_ratio = max_margin_ratio
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_asset_margin_pct = max_asset_margin_pct

        self.cash = initial_capital
        self.positions: Dict[str, StrictPositionV8] = {}
        self.pending_orders: Dict[str, StrictPendingOrder] = {}
        self.trades: List[StrictTradeRecordV8] = []
        self.equity_history: List[Dict[str, Any]] = []

    def run_portfolio(
        self,
        data_map: Dict[str, pd.DataFrame],
        oos_start_time: str = "",
        slice_id: int = 0,
        initial_pending_orders: Optional[Dict[str, StrictPendingOrder]] = None,
    ) -> Dict[str, Any]:
        self.cash = self.initial_capital
        self.positions.clear()
        if initial_pending_orders:
            self.pending_orders = dict(initial_pending_orders)
        else:
            self.pending_orders.clear()
        self.trades.clear()
        self.equity_history.clear()


        # 1. 预处理各品种数据与严格因果指标
        processed_data = {}
        all_timestamps = set()

        for sym, df_or_pdata in data_map.items():
            if isinstance(df_or_pdata, dict) and "factors" in df_or_pdata:
                pdata = df_or_pdata
            else:
                df = df_or_pdata
                if df.empty or len(df) < 80:
                    continue
                pdata = self._preprocess_symbol(df, sym)
            processed_data[sym] = pdata
            all_timestamps.update(pdata["trade_time"].tolist() if hasattr(pdata["trade_time"], "tolist") else list(pdata["trade_time"]))

        sorted_times = sorted(list(all_timestamps))
        n_total_bars = len(sorted_times)
        if n_total_bars == 0:
            return {}

        if not oos_start_time:
            split_idx = int(n_total_bars * 0.70)
            oos_start_time = sorted_times[split_idx]

        time_to_bar = {}
        for sym, pdata in processed_data.items():
            t_arr = pdata["trade_time"]
            time_to_bar[sym] = {t_arr[i]: i for i in range(len(t_arr))}

        last_known_close_map = {sym: pdata["close"][0] for sym, pdata in processed_data.items()}

        # 2. 严格按因果生命周期推进
        for t_idx, t_str in enumerate(sorted_times):
            is_oos = (t_str >= oos_start_time)

            # ------------------------------------------------------------------
            # Stage 1: 开盘阶段 (At Open of Bar t)
            # ------------------------------------------------------------------
            # 1.1 开盘跳空止损处理
            for sym in list(self.positions.keys()):
                pos = self.positions[sym]
                if sym in processed_data and t_str in time_to_bar[sym]:
                    b_idx = time_to_bar[sym][t_str]
                    curr_o = processed_data[sym]["open"][b_idx]
                    if pos.side == 1 and curr_o <= pos.stop_price:
                        self._close_position(pos, curr_o, t_str, "STOP_OPEN_GAP", is_oos, processed_data[sym]["spec"], b_idx, slice_id)
                        del self.positions[sym]
                    elif pos.side == -1 and curr_o >= pos.stop_price:
                        self._close_position(pos, curr_o, t_str, "STOP_OPEN_GAP", is_oos, processed_data[sym]["spec"], b_idx, slice_id)
                        del self.positions[sym]

            # 1.2 盘前可用资金与权益核算 (严格基于已知上一柱收盘价)
            pre_open_floating_pnl = sum(
                (pos.last_known_close - pos.entry_price) * pos.side * processed_data[pos.symbol]["spec"].multiplier * pos.lots
                for pos in self.positions.values()
            )
            pre_open_margin_occ = sum(
                calculate_contract_margin(processed_data[pos.symbol]["spec"], pos.last_known_close, pos.lots, use_broker_rate=True)
                for pos in self.positions.values()
            )
            pre_open_equity = self.cash + pre_open_floating_pnl
            pre_open_available_cash = self.cash - pre_open_margin_occ

            # 1.3 执行上一柱已收盘生成的挂单 (Pre-Generated Pending Orders)
            # 严格修复异步挂单生命周期：仅当标的在当前全局时间戳 t_str 真正开盘时才弹出并执行挂单，其余标的挂单安全保留
            for sym in list(self.pending_orders.keys()):
                if sym in self.positions:
                    # 已有持仓，清除多余挂单
                    self.pending_orders.pop(sym, None)
                    continue
                if sym not in processed_data or t_str not in time_to_bar[sym]:
                    # 当前时间戳属于其他交易品种，该标的当前未开盘；挂单继续保留等待！
                    continue

                # 当前标的正处于开盘时刻，弹出挂单进行撮合核算
                order = self.pending_orders.pop(sym)
                b_idx = time_to_bar[sym][t_str]
                pdata = processed_data[sym]
                spec = pdata["spec"]
                curr_o = pdata["open"][b_idx]
                curr_h = pdata["high"][b_idx]
                curr_l = pdata["low"][b_idx]
                causal_atr = pdata["causal_atr"][b_idx]
                stop_p = order.stop_price

                # 开盘跳空方向有效性校验：若开盘已跳空穿越止损，逻辑失效直接废单取消
                if order.side == 1 and curr_o <= stop_p:
                    continue
                elif order.side == -1 and curr_o >= stop_p:
                    continue

                margin_per_lot = calculate_contract_margin(spec, curr_o, 1, use_broker_rate=True)
                risk_dist = max(abs(curr_o - stop_p), 0.5 * causal_atr)
                risk_amt = risk_dist * spec.multiplier

                target_lots = int((pre_open_equity * self.risk_per_trade_pct) / (risk_amt + 1e-8))
                max_lots_by_margin = int((pre_open_equity * self.max_asset_margin_pct) / (margin_per_lot + 1e-8))
                lots = min(target_lots, max_lots_by_margin, 5)

                if lots < 1:
                    continue

                entry_fee = calculate_contract_fee(spec, curr_o, lots, is_close_today=False, cost_multiplier=self.cost_multiplier)
                entry_slip = 1.0 * self.cost_multiplier * spec.tick_size * spec.multiplier * lots
                req_margin = margin_per_lot * lots

                if pre_open_available_cash < (req_margin + entry_fee + entry_slip):
                    continue

                if (pre_open_margin_occ + req_margin) > pre_open_equity * self.max_margin_ratio:
                    continue

                self.cash -= (entry_fee + entry_slip)
                pre_open_margin_occ += req_margin
                pre_open_available_cash = self.cash - pre_open_margin_occ

                new_pos = StrictPositionV8(
                    symbol=sym,
                    side=order.side,
                    mode=order.mode,
                    entry_time=t_str,
                    entry_price=curr_o,
                    stop_price=stop_p,
                    target_price=order.target_price,
                    lots=lots,
                    entry_bar_idx=b_idx,
                    entry_fee=entry_fee,
                    entry_slip=entry_slip,
                    best_price=curr_o,
                    last_known_close=curr_o,
                    is_be_locked=False,
                )

                same_exit, same_exit_p, same_reason = self._check_same_bar(
                    new_pos, curr_o, curr_h, curr_l, spec.tick_size
                )
                if same_exit:
                    self._close_position(new_pos, same_exit_p, t_str, same_reason, is_oos, spec, b_idx, slice_id)
                else:
                    self.positions[sym] = new_pos

            # ------------------------------------------------------------------
            # Stage 2: 柱内阶段 (Intrabar Evaluation)
            # ------------------------------------------------------------------
            for sym in list(self.positions.keys()):
                pos = self.positions[sym]
                if sym not in processed_data or t_str not in time_to_bar[sym]:
                    continue

                b_idx = time_to_bar[sym][t_str]
                pdata = processed_data[sym]
                curr_o = pdata["open"][b_idx]
                curr_h = pdata["high"][b_idx]
                curr_l = pdata["low"][b_idx]
                curr_c = pdata["close"][b_idx]
                spec = pdata["spec"]
                causal_atr = pdata["causal_atr"][b_idx]

                exit_sig, exit_p, reason = self._check_intrabar_exit(
                    pos, curr_o, curr_h, curr_l, curr_c, b_idx, causal_atr, spec.tick_size
                )

                if exit_sig:
                    self._close_position(pos, exit_p, t_str, reason, is_oos, spec, b_idx, slice_id)
                    del self.positions[sym]

            # ------------------------------------------------------------------
            # Stage 3: 收盘阶段 (At Close of Bar t)
            # ------------------------------------------------------------------
            # 3.1 更新当前 Bar 收盘价与次柱吊灯止损线
            for sym, pdata in processed_data.items():
                if t_str in time_to_bar[sym]:
                    b_idx = time_to_bar[sym][t_str]
                    curr_h = pdata["high"][b_idx]
                    curr_l = pdata["low"][b_idx]
                    curr_c = pdata["close"][b_idx]
                    causal_atr = pdata["causal_atr"][b_idx]
                    last_known_close_map[sym] = curr_c

                    if sym in self.positions:
                        pos = self.positions[sym]
                        pos.last_known_close = curr_c
                        self._update_trailing(pos, curr_h, curr_l, causal_atr, pdata["spec"].tick_size)

            # 3.2 依据已闭合柱评估生成次柱开盘挂单 (严格无未来信息)
            for sym, pdata in processed_data.items():
                if sym in self.positions:
                    continue
                if t_str not in time_to_bar[sym]:
                    continue

                b_idx = time_to_bar[sym][t_str]
                if b_idx < 1 or b_idx >= len(pdata["close"]) - 1:
                    continue

                sig = evaluate_chan_signal(pdata, b_idx + 1, sym, pdata["spec"], pdata["spec"].tick_size)
                if sig.side != 0:
                    self.pending_orders[sym] = StrictPendingOrder(
                        symbol=sym,
                        side=sig.side,
                        mode=sig.mode,
                        stop_price=sig.stop_price,
                        target_price=sig.target_price,
                        causal_atr=sig.causal_atr,
                        reason=sig.reason,
                        generated_time=t_str,
                    )

            # 3.3 持续风险监控：核算 Mark-to-Market 组合权益与穿仓/强平检查
            close_floating_pnl = sum(
                (pos.last_known_close - pos.entry_price) * pos.side * processed_data[pos.symbol]["spec"].multiplier * pos.lots
                for pos in self.positions.values()
            )
            close_margin_occ = sum(
                calculate_contract_margin(processed_data[pos.symbol]["spec"], pos.last_known_close, pos.lots, use_broker_rate=True)
                for pos in self.positions.values()
            )
            total_eq = self.cash + close_floating_pnl

            # 破产或券商强平线 (Margin/Equity >= 1.20 或 Equity <= 0) 持续监控
            if total_eq <= 0 or (total_eq > 0 and close_margin_occ / total_eq >= 1.20):
                for sym in list(self.positions.keys()):
                    pos = self.positions[sym]
                    self._close_position(pos, last_known_close_map[sym], t_str, "PORTFOLIO_MARGIN_CALL_LIQUIDATION", is_oos, processed_data[sym]["spec"], 0, slice_id)
                    del self.positions[sym]
                self.pending_orders.clear()
                self.equity_history.append({
                    "time": t_str,
                    "equity": round(self.cash, 2),
                    "cash": round(self.cash, 2),
                    "margin": 0.0,
                    "positions_count": 0,
                    "is_oos": is_oos,
                })
                break

            self.equity_history.append({
                "time": t_str,
                "equity": round(total_eq, 2),
                "cash": round(self.cash, 2),
                "margin": round(close_margin_occ, 2),
                "positions_count": len(self.positions),
                "is_oos": is_oos,
            })

        # 期末清算：强制 Mark-to-Market 清算所有剩余头寸，并完整记录进权益历史
        last_time_str = sorted_times[-1] if sorted_times else ""
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            self._close_position(pos, last_known_close_map[sym], last_time_str, "FINAL_BAR_MTM_SETTLEMENT", True, processed_data[sym]["spec"], 0, slice_id)
            del self.positions[sym]

        final_equity = round(self.cash, 2)
        total_net_pnl = round(sum(t.net_pnl for t in self.trades), 2)
        diff = abs(final_equity - (self.initial_capital + total_net_pnl))

        self.equity_history.append({
            "time": last_time_str,
            "equity": final_equity,
            "cash": final_equity,
            "margin": 0.0,
            "positions_count": 0,
            "is_oos": True,
        })

        assert diff < 0.50, (
            f"❌ 财务对账失败！Final Equity ({final_equity:.2f}) != Initial Capital ({self.initial_capital:.2f}) + Total Net PnL ({total_net_pnl:.2f})"
        )

        return self._build_report(oos_start_time, slice_id)

    def _preprocess_symbol(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        spec = get_spec(symbol)
        df_clean = df.drop_duplicates(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
        factors = calculate_factors_v8(df_clean)
        n = len(df_clean)

        atr_vals = factors["atr"].values
        causal_atr = np.zeros(n)
        causal_atr[1:] = atr_vals[:-1]
        causal_atr[0] = atr_vals[0]
        factors_arrays = {c: factors[c].values for c in factors.columns}

        return {
            "symbol": symbol,
            "spec": spec,
            "trade_time": df_clean["trade_time"].astype(str).values,
            "open": [round_to_tick(v, spec.tick_size) for v in df_clean["open"].astype(float).values],
            "high": [round_to_tick(v, spec.tick_size) for v in df_clean["high"].astype(float).values],
            "low": [round_to_tick(v, spec.tick_size) for v in df_clean["low"].astype(float).values],
            "close": [round_to_tick(v, spec.tick_size) for v in df_clean["close"].astype(float).values],
            "causal_atr": [max(spec.tick_size, v) for v in causal_atr],
            "factors": factors,
            "factors_arrays": factors_arrays,
        }

    def _check_intrabar_exit(
        self,
        pos: StrictPositionV8,
        curr_o: float,
        curr_h: float,
        curr_l: float,
        curr_c: float,
        b_idx: int,
        causal_atr: float,
        tick_size: float,
    ) -> Tuple[bool, float, str]:
        holding_bars = b_idx - pos.entry_bar_idx

        if pos.side == 1:
            if pos.mode == "TREND":
                if curr_l <= pos.stop_price:
                    exit_p = round_to_tick(min(pos.stop_price, curr_h), tick_size)
                    return True, exit_p, "STOP_INTRABAR"
                if holding_bars >= 160:
                    return True, curr_o, "TIME_EXPIRATION"

            elif pos.mode == "REVERSION":
                is_tp = (curr_h >= pos.target_price)
                is_sl = (curr_l <= pos.stop_price)
                if is_tp and is_sl:
                    return True, pos.stop_price, "PESSIMISTIC_STOP_COLLISION"
                if is_sl:
                    return True, pos.stop_price, "STOP_INTRABAR"
                if is_tp:
                    return True, pos.target_price, "TP_MID"
                if holding_bars >= 25:
                    return True, curr_o, "TIME_EXPIRATION"

        elif pos.side == -1:
            if pos.mode == "TREND":
                if curr_h >= pos.stop_price:
                    exit_p = round_to_tick(max(pos.stop_price, curr_l), tick_size)
                    return True, exit_p, "STOP_INTRABAR"
                if holding_bars >= 160:
                    return True, curr_o, "TIME_EXPIRATION"

            elif pos.mode == "REVERSION":
                is_tp = (curr_l <= pos.target_price)
                is_sl = (curr_h >= pos.stop_price)
                if is_tp and is_sl:
                    return True, pos.stop_price, "PESSIMISTIC_STOP_COLLISION"
                if is_sl:
                    return True, pos.stop_price, "STOP_INTRABAR"
                if is_tp:
                    return True, pos.target_price, "TP_MID"
                if holding_bars >= 25:
                    return True, curr_o, "TIME_EXPIRATION"

        return False, 0.0, ""

    def _update_trailing(self, pos: StrictPositionV8, curr_h: float, curr_l: float, causal_atr: float, tick_size: float):
        if pos.mode != "TREND":
            return

        if pos.side == 1:
            if curr_h > pos.best_price:
                pos.best_price = curr_h
            gain = pos.best_price - pos.entry_price
            if gain >= 1.0 * causal_atr:
                pos.stop_price = max(pos.stop_price, round_to_tick(pos.entry_price + 0.2 * causal_atr, tick_size))
                pos.is_be_locked = True
            if gain >= 1.6 * causal_atr:
                trail_p = round_to_tick(pos.best_price - 1.5 * causal_atr, tick_size)
                pos.stop_price = max(pos.stop_price, trail_p)
            if gain >= 3.0 * causal_atr:
                trail_p = round_to_tick(pos.best_price - 1.2 * causal_atr, tick_size)
                pos.stop_price = max(pos.stop_price, trail_p)

        elif pos.side == -1:
            if curr_l < pos.best_price:
                pos.best_price = curr_l
            gain = pos.entry_price - pos.best_price
            if gain >= 1.0 * causal_atr:
                pos.stop_price = min(pos.stop_price, round_to_tick(pos.entry_price - 0.2 * causal_atr, tick_size))
                pos.is_be_locked = True
            if gain >= 1.6 * causal_atr:
                trail_p = round_to_tick(pos.best_price + 1.5 * causal_atr, tick_size)
                pos.stop_price = min(pos.stop_price, trail_p)
            if gain >= 3.0 * causal_atr:
                trail_p = round_to_tick(pos.best_price + 1.2 * causal_atr, tick_size)
                pos.stop_price = min(pos.stop_price, trail_p)

    def _check_same_bar(self, pos: StrictPositionV8, curr_o: float, curr_h: float, curr_l: float, tick_size: float) -> Tuple[bool, float, str]:
        if pos.side == 1 and curr_l <= pos.stop_price:
            fill_p = round_to_tick(min(curr_o, pos.stop_price) if curr_o <= pos.stop_price else pos.stop_price, tick_size)
            fill_p = max(curr_l, min(curr_h, fill_p))
            return True, fill_p, "SAME_BAR_STOP"
        elif pos.side == -1 and curr_h >= pos.stop_price:
            fill_p = round_to_tick(max(curr_o, pos.stop_price) if curr_o >= pos.stop_price else pos.stop_price, tick_size)
            fill_p = max(curr_l, min(curr_h, fill_p))
            return True, fill_p, "SAME_BAR_STOP"
        return False, 0.0, ""

    def _close_position(self, pos: StrictPositionV8, exit_price: float, exit_time: str, reason: str, is_oos: bool, spec: Any, b_idx: int, slice_id: int):
        holding_bars = b_idx - pos.entry_bar_idx if b_idx > pos.entry_bar_idx else 1
        is_close_today = (holding_bars <= 16)
        exit_fee = calculate_contract_fee(spec, exit_price, pos.lots, is_close_today=is_close_today, cost_multiplier=self.cost_multiplier)
        exit_slip = 1.0 * self.cost_multiplier * spec.tick_size * spec.multiplier * pos.lots

        gross = (exit_price - pos.entry_price) * pos.side * spec.multiplier * pos.lots
        total_fee = pos.entry_fee + exit_fee
        total_slip = pos.entry_slip + exit_slip
        net = gross - total_fee - total_slip

        self.cash += (gross - exit_fee - exit_slip)

        self.trades.append(StrictTradeRecordV8(
            symbol=pos.symbol,
            name=spec.name,
            side="LONG" if pos.side == 1 else "SHORT",
            mode=pos.mode,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            lots=pos.lots,
            holding_bars=holding_bars,
            gross_pnl=round(gross, 2),
            fee=round(total_fee, 2),
            slippage=round(total_slip, 2),
            net_pnl=round(net, 2),
            exit_reason=reason,
            is_oos=is_oos,
            slice_id=slice_id,
        ))

    def _build_report(self, oos_start_time: str, slice_id: int) -> Dict[str, Any]:
        if not self.trades:
            return {"total_trades": 0, "net_pnl": 0.0}

        all_trades = self.trades
        is_trades = [t for t in all_trades if not t.is_oos]
        oos_trades = [t for t in all_trades if t.is_oos]

        def metrics(tlist: List[StrictTradeRecordV8]) -> Dict[str, Any]:
            if not tlist:
                return {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}
            pnls = np.array([t.net_pnl for t in tlist])
            wins = pnls[pnls > 0]
            losses = np.abs(pnls[pnls < 0])
            wr = len(wins) / len(pnls)
            tot_win = float(wins.sum()) if len(wins) > 0 else 0.0
            tot_loss = float(losses.sum()) if len(losses) > 0 else 0.0
            pf = float(tot_win / (tot_loss + 1e-8))
            net = float(pnls.sum())
            cum = np.insert(np.cumsum(pnls), 0, 0.0)
            mdd = float((np.maximum.accumulate(cum) - cum).max())
            return {
                "trades": len(tlist),
                "net_pnl": round(net, 2),
                "win_rate": round(wr, 4),
                "profit_factor": round(pf, 2),
                "total_win_rmb": round(tot_win, 2),
                "total_loss_rmb": round(tot_loss, 2),
                "max_drawdown": round(mdd, 2),
            }

        eq_series = np.array([pt["equity"] for pt in self.equity_history])
        peak_series = np.maximum.accumulate(eq_series)
        portfolio_mdd_rmb = float((peak_series - eq_series).max())
        portfolio_mdd_pct = float(((peak_series - eq_series) / np.maximum(peak_series, 1e-6)).max())

        is_eq = np.array([pt["equity"] for pt in self.equity_history if not pt["is_oos"]])
        oos_eq = np.array([pt["equity"] for pt in self.equity_history if pt["is_oos"]])

        is_mdd = float((np.maximum.accumulate(is_eq) - is_eq).max()) if len(is_eq) > 0 else 0.0
        oos_mdd = float((np.maximum.accumulate(oos_eq) - oos_eq).max()) if len(oos_eq) > 0 else 0.0

        is_m = metrics(is_trades)
        is_m["portfolio_m2m_max_drawdown"] = round(is_mdd, 2)

        oos_m = metrics(oos_trades)
        oos_m["portfolio_m2m_max_drawdown"] = round(oos_mdd, 2)

        symbol_summary = {}
        for sym in ALL_COMMODITIES:
            sym_t = [t for t in all_trades if t.symbol == sym]
            if sym_t:
                m = metrics(sym_t)
                m["name"] = sym_t[0].name
                w_low, w_high = wilson_score_interval(int(m["win_rate"] * m["trades"]), m["trades"])
                m["wilson_95_ci"] = [round(w_low, 4), round(w_high, 4)]
                m["reliability_grade"] = grade_reliability(m["trades"], w_low, w_high)
                symbol_summary[sym] = m

        pnls_sorted = sorted([t.net_pnl for t in all_trades], reverse=True)
        top3_pnl = sum(pnls_sorted[:3])
        total_pnl = sum(pnls_sorted)

        ag_au_pnl = sum(t.net_pnl for t in all_trades if t.symbol in ("AG_IDX", "AU_IDX"))
        other_pnl = total_pnl - ag_au_pnl

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "slice_id": slice_id,
            "initial_capital": self.initial_capital,
            "final_equity": round(self.cash, 2),
            "total_net_pnl": round(total_pnl, 2),
            "portfolio_max_drawdown_rmb": round(portfolio_mdd_rmb, 2),
            "portfolio_max_drawdown_pct": round(portfolio_mdd_pct * 100, 2),
            "oos_start_time": oos_start_time,
            "overall_metrics": metrics(all_trades),
            "in_sample_metrics": is_m,
            "out_of_sample_metrics": oos_m,
            "concentration_analysis": {
                "top3_trades_pnl": round(top3_pnl, 2),
                "top3_pnl_share_pct": round(top3_pnl / max(abs(total_pnl), 1e-6) * 100, 2),
                "pnl_without_top3": round(total_pnl - top3_pnl, 2),
                "ag_au_net_pnl": round(ag_au_pnl, 2),
                "non_precious_metals_pnl": round(other_pnl, 2),
            },
            "symbols": symbol_summary,
            "total_trades_count": len(all_trades),
            "trade_records": [asdict(t) for t in all_trades],
            "equity_history": self.equity_history,
        }


def get_git_revision() -> str:
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
        return rev
    except Exception:
        return "UNKNOWN_GIT"


def compute_data_sha256(data_map: Dict[str, pd.DataFrame]) -> str:
    """
    全量数据防伪哈希：对所有品种的完整时间戳与 OHLCV 数据流计算标准 64 位 SHA256。
    """
    h = hashlib.sha256()
    for sym in sorted(data_map.keys()):
        df = data_map[sym]
        h.update(sym.encode("utf-8"))
        if not df.empty:
            cols = [c for c in ["trade_time", "open", "high", "low", "close", "volume"] if c in df.columns]
            raw_bytes = df[cols].to_csv(index=False).encode("utf-8")
            h.update(raw_bytes)
    return h.hexdigest()


def run_temporal_slice_audit():
    provider = UnifiedDataProvider()
    data_map = {}
    meta_map = {}
    print("🚀 【ChanQuant 8.0·严格挂单·全账本复算版】 Loading Data...")
    for sym in ALL_COMMODITIES:
        df, meta = provider.load_or_generate_bars(sym, "15m", target_min_trades=1000)
        if not df.empty:
            data_map[sym] = df
            meta_map[sym] = meta

    all_timestamps = sorted(list(set(
        t for df in data_map.values() for t in df["trade_time"].astype(str).tolist()
    )))
    n_bars = len(all_timestamps)
    total_accumulated_bars = sum(len(df) for df in data_map.values())

    print(f"\n📊 行情数据元数据与大数定律样本审计 (共加载 {len(data_map)} 个品种, 组合总步数: {n_bars:,}, 品种级总K线: {total_accumulated_bars:,}):")
    insufficient_count = 0
    data_provenance = {}
    for sym, m in sorted(meta_map.items()):
        status_mark = "✅" if m["lln_status"] == "SUFFICIENT_REAL_SAMPLE" else "⚠️"
        if m["lln_status"] != "SUFFICIENT_REAL_SAMPLE":
            insufficient_count += 1
        print(f"  {status_mark} [{sym:<8}] {m['name']:<5}: {m['real_bars']:>6} 根 ({m['start_time']} ~ {m['end_time']}) -> {m['lln_status']}")
        data_provenance[sym] = {
            "name": m["name"],
            "real_bars": m["real_bars"],
            "start_time": m["start_time"],
            "end_time": m["end_time"],
            "lln_status": m["lln_status"],
        }

    if insufficient_count > 0:
        print(f"\n⚠️ 样本充足性警示：当前有 {insufficient_count}/{len(data_map)} 个品种的真实历史样本未达到大数定律充足门槛 (60,000 根)，报告中将严格如实标注！")

    print("\n🔬 正在进行全量 25 品种严格因果指标与缠论特征同源预计算 (一次性计算)...")
    base_engine = StrictCausalSharedPortfolioEngine(cost_multiplier=1.0)
    full_processed_map = {}
    for sym, df in data_map.items():
        full_processed_map[sym] = base_engine._preprocess_symbol(df, sym)

    def slice_pdata(pdata: Dict[str, Any], cutoff_time: str) -> Optional[Dict[str, Any]]:
        t_arr = pdata["trade_time"]
        idx_end = np.searchsorted(t_arr, cutoff_time, side="right")
        if idx_end < 80:
            return None
        factors_sub = pdata["factors"].iloc[:idx_end].reset_index(drop=True)
        factors_arrs_sub = {c: v[:idx_end] for c, v in pdata["factors_arrays"].items()}
        return {
            "symbol": pdata["symbol"],
            "spec": pdata["spec"],
            "trade_time": pdata["trade_time"][:idx_end],
            "open": pdata["open"][:idx_end],
            "high": pdata["high"][:idx_end],
            "low": pdata["low"][:idx_end],
            "close": pdata["close"][:idx_end],
            "causal_atr": pdata["causal_atr"][:idx_end],
            "factors": factors_sub,
            "factors_arrays": factors_arrs_sub,
        }

    # 3 个固定锚定时序性能切片 (Anchored Temporal Performance Slices):
    # Slice 1: 0~40% 训练 vs 40%~60% 切片
    # Slice 2: 0~60% 训练 vs 60%~80% 切片
    # Slice 3: 0~80% 训练 vs 80%~100% 切片
    slices_config = [
        {"slice_id": 1, "train_end": int(n_bars * 0.40), "test_end": int(n_bars * 0.60)},
        {"slice_id": 2, "train_end": int(n_bars * 0.60), "test_end": int(n_bars * 0.80)},
        {"slice_id": 3, "train_end": int(n_bars * 0.80), "test_end": n_bars},
    ]

    print("\n================================================================================")
    print("🔬 正在执行固定锚定时序切片审计 (Anchored Temporal Performance Slices)...")
    print("================================================================================")

    slice_results_1x = []
    slice_results_3x = []

    for s_cfg in slices_config:
        sid = s_cfg["slice_id"]
        t_end_idx = s_cfg["test_end"]
        oos_start_idx = s_cfg["train_end"]
        oos_start_t = all_timestamps[oos_start_idx]
        cutoff_t = all_timestamps[t_end_idx - 1]

        sub_data_map = {}
        for sym, pdata in full_processed_map.items():
            sub_p = slice_pdata(pdata, cutoff_t)
            if sub_p is not None:
                sub_data_map[sym] = sub_p

        engine_1x = StrictCausalSharedPortfolioEngine(cost_multiplier=1.0)
        rep_1x = engine_1x.run_portfolio(sub_data_map, oos_start_time=oos_start_t, slice_id=sid)
        slice_results_1x.append(rep_1x)

        engine_3x = StrictCausalSharedPortfolioEngine(cost_multiplier=3.0)
        rep_3x = engine_3x.run_portfolio(sub_data_map, oos_start_time=oos_start_t, slice_id=sid)
        slice_results_3x.append(rep_3x)

        print(f"  • Slice {sid}: Start {oos_start_t} ~ {cutoff_t}")
        print(f"    - 1x IS Net: {rep_1x['in_sample_metrics']['net_pnl']:>9,.2f} RMB | 1x Slice Net: {rep_1x['out_of_sample_metrics']['net_pnl']:>9,.2f} RMB (WR: {rep_1x['out_of_sample_metrics']['win_rate']*100:.1f}%, PF: {rep_1x['out_of_sample_metrics']['profit_factor']:.2f})")
        print(f"    - 3x IS Net: {rep_3x['in_sample_metrics']['net_pnl']:>9,.2f} RMB | 3x Slice Net: {rep_3x['out_of_sample_metrics']['net_pnl']:>9,.2f} RMB (WR: {rep_3x['out_of_sample_metrics']['win_rate']*100:.1f}%, PF: {rep_3x['out_of_sample_metrics']['profit_factor']:.2f})")

    # 执行全区间基准回测 (70% IS vs 30% OOS)
    print("\n⚖️ 正在执行全区间基准严格回测 (1x Baseline & 3x Stress)...")
    base_engine_1x = StrictCausalSharedPortfolioEngine(cost_multiplier=1.0)
    full_rep_1x = base_engine_1x.run_portfolio(full_processed_map)

    base_engine_3x = StrictCausalSharedPortfolioEngine(cost_multiplier=3.0)
    full_rep_3x = base_engine_3x.run_portfolio(full_processed_map)

    git_hash = get_git_revision()
    data_hash = compute_data_sha256(data_map)
    ts_str = time.strftime("%Y%m%d_%H%M%S")

    out_file = REPORTS_DIR / f"ChanQuant_8.0_Strict_Full_Ledger_Audit_{ts_str}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": STRATEGY_NAME,
            "description": STRATEGY_DESCRIPTION,
            "git_revision": git_hash,
            "data_content_sha256": data_hash,
            "time_range": {"start": all_timestamps[0], "end": all_timestamps[-1], "total_bars": n_bars},
            "timeline_statistics": {
                "portfolio_timeline_steps": n_bars,
                "total_accumulated_symbol_bars": total_accumulated_bars,
                "insufficient_sample_symbols_count": insufficient_count,
            },
            "data_provenance": data_provenance,
            "parameters": {
                "initial_capital": 500000.0,
                "max_margin_ratio": 0.70,
                "risk_per_trade_pct": 0.010,
                "max_asset_margin_pct": 0.25,
                "trend_island_symbols": list(TREND_ISLAND_SYMBOLS),
                "reversion_island_symbols": list(REVERSION_ISLAND_SYMBOLS),
            },
            "slices_1x": slice_results_1x,
            "slices_3x": slice_results_3x,
            "full_baseline_1x": full_rep_1x,
            "full_stress_3x": full_rep_3x,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n📁 包含完整可复算账本的终极科研审计报告已归档至: {out_file}")
    return full_rep_1x, full_rep_3x, slice_results_1x, slice_results_3x


if __name__ == "__main__":
    run_temporal_slice_audit()
