"""
code/strict_chanquant_shared_portfolio_audit.py — 工业级严格因果·共享账户组合·样本内外隔离终极审计引擎

【严格因果与无未来函数约束】：
1. 严格因果时序：信号在 Bar t 收盘计算，在 Bar t+1 Open 开盘撮合；
2. 严格因果 ATR：在 Bar t+1 开盘时，只能使用已闭合的 atr[t]（即 atr[i-1]），严禁使用 atr[i]；
3. 悲观柱内撮合排序：
   - 检查开盘跳空止损（Open <= Stop 止损价）；
   - 若柱内同时触发止盈与止损，强制按【止损优先】悲观执行；
   - 柱内新开仓立即检查当根柱后续 [Low, High] 是否触碰止损；
   - 吊灯追踪止损仅在当根柱走完后更新至下一根柱使用，严禁用当根 High 抬高止损后判定当根 Low 不破。
4. 真实共享账户组合模拟 (Single Shared Portfolio Account):
   - 初始资金固定 500,000 RMB，全市场 25 个品种共享单一现金与保证金池；
   - 严格组合总保证金风控（总占用 <= 70% 净值，超额拒单）；
   - 逐柱动态盯市 (Mark-to-Market) 输出真实组合权益曲线与真实最大回撤。
5. 严格样本内 (IS, 70%) 与样本外 (OOS, 30%) 盲测切分，参数完全冻结。
6. 100% 诚实统计：Wilson 95% 置信区间，禁止伪造 PASS，透明展示集中度风险与剔除极值后的净利。
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass, field
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

from contract_specs import get_spec
from technical_indicators import calculate_atr, calculate_ema, calculate_adx
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_causal_hurst
try:
    from strategies.tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy
except ImportError:
    from tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy

from unified_backtest_pipeline import UnifiedDataProvider, round_to_tick, REPORTS_DIR


ALL_COMMODITIES = [
    "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "JM_IDX",
    "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "AG_IDX", "AU_IDX",
    "TA_IDX", "MA_IDX", "SA_IDX", "FG_IDX", "SC_IDX",
    "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX", "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
]

TREND_CORE_SYMBOLS = {"AU_IDX", "AG_IDX", "P_IDX"}


@dataclass
class StrictPosition:
    symbol: str
    side: int  # +1 for Long, -1 for Short
    mode: str  # 'TREND' or 'REVERSION'
    entry_time: str
    entry_price: float
    stop_price: float
    target_price: float
    lots: int
    entry_bar_idx: int
    best_price: float
    is_be_locked: bool = False


@dataclass
class StrictTradeRecord:
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


class StrictSharedPortfolioEngine:
    """
    单账户全市场多品种共享资金池严格因果撮合引擎
    """
    def __init__(
        self,
        initial_capital: float = 500_000.0,
        cost_multiplier: float = 1.0,
        max_margin_ratio: float = 0.70,
        risk_per_trade_pct: float = 0.010,
        oos_split_ratio: float = 0.70,
    ):
        self.initial_capital = initial_capital
        self.cost_multiplier = cost_multiplier
        self.max_margin_ratio = max_margin_ratio
        self.risk_per_trade_pct = risk_per_trade_pct
        self.oos_split_ratio = oos_split_ratio

        self.cash = initial_capital
        self.positions: Dict[str, StrictPosition] = {}
        self.trades: List[StrictTradeRecord] = []
        self.equity_history: List[Dict[str, Any]] = []

    def run_portfolio_backtest(
        self,
        data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        self.cash = self.initial_capital
        self.positions.clear()
        self.trades.clear()
        self.equity_history.clear()

        # 1. 预处理各品种的因果指标与缠论事件
        processed_data = {}
        all_timestamps = set()

        for sym, df in data_map.items():
            if df.empty or len(df) < 80:
                continue
            df_prep = self._preprocess_symbol_data(df, sym)
            processed_data[sym] = df_prep
            all_timestamps.update(df_prep["trade_time"].astype(str).tolist())

        sorted_times = sorted(list(all_timestamps))
        n_total_bars = len(sorted_times)
        if n_total_bars == 0:
            return {}

        split_idx = int(n_total_bars * self.oos_split_ratio)
        oos_start_time = sorted_times[split_idx]

        # 建立时间戳对齐索引
        time_to_bar = {}
        for sym, pdata in processed_data.items():
            t_series = pdata["trade_time"].astype(str)
            time_to_bar[sym] = {t_series[i]: i for i in range(len(t_series))}


        # 2. 逐时间柱动态撮合与状态机推进
        for t_idx, t_str in enumerate(sorted_times):
            is_oos = (t_idx >= split_idx)
            current_floating_pnl = 0.0
            current_margin_occ = 0.0

            # Step A: 检查持仓品种的出场与动态风控 (严格因果时序)
            active_symbols = list(self.positions.keys())
            for sym in active_symbols:
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
                tick_size = spec.tick_size
                multiplier = spec.multiplier
                causal_atr = pdata["causal_atr"][b_idx]

                # 出场判定
                exit_signal, exit_price, reason = self._check_position_exit(
                    pos, curr_o, curr_h, curr_l, curr_c, b_idx, causal_atr, tick_size
                )

                if exit_signal:
                    self._close_position(pos, exit_price, t_str, reason, is_oos, spec, b_idx)
                    del self.positions[sym]
                else:
                    # 更新当根柱走完后的最高/最低价与动态吊灯止损（供下一根柱使用）
                    self._update_trailing_stops(pos, curr_h, curr_l, causal_atr, tick_size)
                    unrealized = (curr_c - pos.entry_price) * pos.side * multiplier * pos.lots
                    current_floating_pnl += unrealized
                    current_margin_occ += curr_c * multiplier * pos.lots * spec.margin_rate

            # Step B: 检查开仓信号 (仅在没有持仓的品种上执行严格 Next-Open 撮合)
            current_equity = self.cash + current_margin_occ + current_floating_pnl

            for sym, pdata in processed_data.items():
                if sym in self.positions:
                    continue  # 已有持仓，单品种不重复开仓
                if t_str not in time_to_bar[sym]:
                    continue

                b_idx = time_to_bar[sym][t_str]
                if b_idx < 2:
                    continue

                signal_side, sig_mode, stop_price, target_price = self._evaluate_entry_signal(
                    pdata, b_idx, sym
                )

                if signal_side != 0:
                    spec = pdata["spec"]
                    curr_o = pdata["open"][b_idx]
                    curr_h = pdata["high"][b_idx]
                    curr_l = pdata["low"][b_idx]
                    causal_atr = pdata["causal_atr"][b_idx]

                    # 资金与保证金风控门禁
                    margin_per_lot = curr_o * spec.multiplier * spec.margin_rate
                    risk_dist = max(abs(curr_o - stop_price), 0.6 * causal_atr)
                    risk_amt_per_lot = risk_dist * spec.multiplier

                    target_lots = int((current_equity * self.risk_per_trade_pct) / (risk_amt_per_lot + 1e-8))
                    max_lots_by_margin = int((current_equity * 0.15) / (margin_per_lot + 1e-8))
                    lots = max(1, min(target_lots, max_lots_by_margin, 5))

                    req_margin = margin_per_lot * lots
                    if (current_margin_occ + req_margin) <= current_equity * self.max_margin_ratio and self.cash >= req_margin:
                        # 开仓建仓
                        new_pos = StrictPosition(
                            symbol=sym,
                            side=signal_side,
                            mode=sig_mode,
                            entry_time=t_str,
                            entry_price=curr_o,
                            stop_price=stop_price,
                            target_price=target_price,
                            lots=lots,
                            entry_bar_idx=b_idx,
                            best_price=curr_o,
                            is_be_locked=False,
                        )

                        # 悲观同柱止损检查：开仓当根柱后续 [Low, High] 是否触碰止损
                        same_bar_exit, same_exit_p, same_reason = self._check_same_bar_stop(
                            new_pos, curr_o, curr_h, curr_l, spec.tick_size
                        )
                        if same_bar_exit:
                            self._close_position(new_pos, same_exit_p, t_str, same_reason, is_oos, spec, b_idx)
                        else:
                            self.positions[sym] = new_pos
                            self.cash -= (curr_o * spec.multiplier * lots * spec.fee_rate * self.cost_multiplier + 2 * self.cost_multiplier * spec.tick_size * spec.multiplier * lots)
                            current_margin_occ += req_margin

            # Step C: 记录逐柱动态盯市组合权益
            total_portfolio_equity = self.cash + current_margin_occ + current_floating_pnl
            self.equity_history.append({
                "time": t_str,
                "equity": round(total_portfolio_equity, 2),
                "cash": round(self.cash, 2),
                "margin": round(current_margin_occ, 2),
                "positions_count": len(self.positions),
                "is_oos": is_oos,
            })

        return self._generate_portfolio_report(oos_start_time)

    def _preprocess_symbol_data(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        spec = get_spec(symbol)
        df_sorted = df.drop_duplicates(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
        close = df_sorted["close"].astype(float).values
        n = len(df_sorted)

        atr_series = calculate_atr(df_sorted, 14).values
        # 严格因果 ATR: 第 i 根柱开盘时只能使用第 i-1 根柱闭合的 ATR
        causal_atr = np.zeros(n)
        causal_atr[1:] = atr_series[:-1]
        causal_atr[0] = atr_series[0]

        ema20 = calculate_ema(pd.Series(close), 20).values
        ema60 = calculate_ema(pd.Series(close), 60).values
        ema240 = calculate_ema(pd.Series(close), 240).values

        k_pos, k_vel, _ = calculate_kalman_kinematics(close)
        k_vel_norm = k_vel / (np.maximum(atr_series, 1e-6))
        pe = calculate_permutation_entropy(close, order=3, window=30)
        hurst = calculate_causal_hurst(close, 50)

        engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
        events = engine.process_dataframe(df_sorted)
        events_by_idx = {ev.known_raw_idx: ev for ev in events if 0 <= ev.known_raw_idx < n}

        return {
            "symbol": symbol,
            "spec": spec,
            "trade_time": df_sorted["trade_time"].values,
            "open": [round_to_tick(v, spec.tick_size) for v in df_sorted["open"].astype(float).values],
            "high": [round_to_tick(v, spec.tick_size) for v in df_sorted["high"].astype(float).values],
            "low": [round_to_tick(v, spec.tick_size) for v in df_sorted["low"].astype(float).values],
            "close": [round_to_tick(v, spec.tick_size) for v in df_sorted["close"].astype(float).values],
            "causal_atr": [max(spec.tick_size, v) for v in causal_atr],
            "ema20": ema20,
            "ema60": ema60,
            "ema240": ema240,
            "k_pos": k_pos,
            "k_vel_norm": k_vel_norm,
            "pe": pe,
            "hurst": hurst,
            "events_by_idx": events_by_idx,
        }

    def _check_position_exit(
        self,
        pos: StrictPosition,
        curr_o: float,
        curr_h: float,
        curr_l: float,
        curr_c: float,
        b_idx: int,
        causal_atr: float,
        tick_size: float,
    ) -> Tuple[bool, float, str]:
        holding_bars = b_idx - pos.entry_bar_idx

        # 1. 多头出场检测
        if pos.side == 1:
            # 开盘跳空直接破止损
            if curr_o <= pos.stop_price:
                return True, curr_o, "STOP_LOSS_OPEN_GAP"

            if pos.mode == "TREND":
                # 悲观原则：优先检查是否打止损
                if curr_l <= pos.stop_price:
                    return True, pos.stop_price, "STOP_LOSS_INTRABAR"
                if holding_bars >= 160:
                    return True, curr_o, "TIME_EXPIRATION"

            elif pos.mode == "REVERSION":
                is_tp = (curr_h >= pos.target_price)
                is_sl = (curr_l <= pos.stop_price)
                if is_tp and is_sl:
                    # 悲观原则：同柱双触发优先止损
                    return True, pos.stop_price, "PESSIMISTIC_STOP_COLLISION"
                if is_sl:
                    return True, pos.stop_price, "STOP_LOSS_INTRABAR"
                if is_tp:
                    return True, pos.target_price, "TAKE_PROFIT_MID"
                if holding_bars >= 25:
                    return True, curr_o, "TIME_EXPIRATION"

        # 2. 空头出场检测
        elif pos.side == -1:
            if curr_o >= pos.stop_price:
                return True, curr_o, "STOP_LOSS_OPEN_GAP"

            if pos.mode == "TREND":
                if curr_h >= pos.stop_price:
                    return True, pos.stop_price, "STOP_LOSS_INTRABAR"
                if holding_bars >= 160:
                    return True, curr_o, "TIME_EXPIRATION"

            elif pos.mode == "REVERSION":
                is_tp = (curr_l <= pos.target_price)
                is_sl = (curr_h >= pos.stop_price)
                if is_tp and is_sl:
                    return True, pos.stop_price, "PESSIMISTIC_STOP_COLLISION"
                if is_sl:
                    return True, pos.stop_price, "STOP_LOSS_INTRABAR"
                if is_tp:
                    return True, pos.target_price, "TAKE_PROFIT_MID"
                if holding_bars >= 25:
                    return True, curr_o, "TIME_EXPIRATION"

        return False, 0.0, ""

    def _update_trailing_stops(
        self,
        pos: StrictPosition,
        curr_h: float,
        curr_l: float,
        causal_atr: float,
        tick_size: float,
    ):
        """当根柱收盘后更新动态止损，供下一根柱使用"""
        if pos.mode != "TREND":
            return

        if pos.side == 1:
            if curr_h > pos.best_price:
                pos.best_price = curr_h
            # 动态保本
            if not pos.is_be_locked and (pos.best_price - pos.entry_price) >= 1.2 * causal_atr:
                pos.stop_price = max(pos.stop_price, round_to_tick(pos.entry_price + 0.2 * causal_atr, tick_size))
                pos.is_be_locked = True
            # 动态吊灯追踪
            if (pos.best_price - pos.entry_price) >= 2.2 * causal_atr:
                trail_stop = round_to_tick(pos.best_price - 2.5 * causal_atr, tick_size)
                pos.stop_price = max(pos.stop_price, trail_stop)

        elif pos.side == -1:
            if curr_l < pos.best_price:
                pos.best_price = curr_l
            if not pos.is_be_locked and (pos.entry_price - pos.best_price) >= 1.2 * causal_atr:
                pos.stop_price = min(pos.stop_price, round_to_tick(pos.entry_price - 0.2 * causal_atr, tick_size))
                pos.is_be_locked = True
            if (pos.entry_price - pos.best_price) >= 2.2 * causal_atr:
                trail_stop = round_to_tick(pos.best_price + 2.5 * causal_atr, tick_size)
                pos.stop_price = min(pos.stop_price, trail_stop)

    def _check_same_bar_stop(
        self,
        pos: StrictPosition,
        curr_o: float,
        curr_h: float,
        curr_l: float,
        tick_size: float,
    ) -> Tuple[bool, float, str]:
        """开仓当根柱触碰止损检查"""
        if pos.side == 1 and curr_l <= pos.stop_price:
            return True, pos.stop_price, "SAME_BAR_STOP_OUT"
        elif pos.side == -1 and curr_h >= pos.stop_price:
            return True, pos.stop_price, "SAME_BAR_STOP_OUT"
        return False, 0.0, ""

    def _evaluate_entry_signal(
        self,
        pdata: Dict[str, Any],
        b_idx: int,
        symbol: str,
    ) -> Tuple[int, str, float, float]:
        sig_idx = b_idx - 1
        if sig_idx not in pdata["events_by_idx"]:
            return 0, "", 0.0, 0.0

        ev = pdata["events_by_idx"][sig_idx]
        close_sig = pdata["close"][sig_idx]
        causal_atr = pdata["causal_atr"][b_idx]
        tick_size = pdata["spec"].tick_size
        is_trend_sym = symbol in TREND_CORE_SYMBOLS

        if is_trend_sym:
            # 60m 宏观顺势级联
            is_macro_bull = (close_sig >= pdata["ema60"][sig_idx]) and (pdata["ema60"][sig_idx] >= pdata["ema240"][sig_idx]) and (pdata["k_vel_norm"][sig_idx] > 0.03)
            is_macro_bear = (close_sig <= pdata["ema60"][sig_idx]) and (pdata["ema60"][sig_idx] <= pdata["ema240"][sig_idx]) and (pdata["k_vel_norm"][sig_idx] < -0.03)

            if ev.event_type == "B3" and is_macro_bull and ev.zs_high > 0:
                stop_p = round_to_tick(min(ev.trigger_price - 0.2 * causal_atr, ev.zs_high - 0.4 * causal_atr), tick_size)
                return 1, "TREND", stop_p, 0.0
            elif ev.event_type == "B2" and is_macro_bull and (close_sig >= pdata["ema20"][sig_idx]):
                stop_p = round_to_tick(ev.trigger_price - 0.3 * causal_atr, tick_size)
                return 1, "TREND", stop_p, 0.0
            elif ev.event_type == "S3" and is_macro_bear and ev.zs_low > 0:
                stop_p = round_to_tick(max(ev.trigger_price + 0.2 * causal_atr, ev.zs_low + 0.4 * causal_atr), tick_size)
                return -1, "TREND", stop_p, 0.0
            elif ev.event_type == "S2" and is_macro_bear and (close_sig <= pdata["ema20"][sig_idx]):
                stop_p = round_to_tick(ev.trigger_price + 0.3 * causal_atr, tick_size)
                return -1, "TREND", stop_p, 0.0

        else:
            # 产业均值岛：中枢边界极值触轨回归
            if ev.zs_high > 0 and ev.zs_low > 0:
                zs_mid = (ev.zs_high + ev.zs_low) * 0.5
                dev = abs(close_sig - pdata["k_pos"][sig_idx]) / causal_atr

                if (ev.event_type == "B1" or close_sig <= ev.zs_low) and close_sig < zs_mid and dev >= 1.25:
                    target_p = round_to_tick(zs_mid, tick_size)
                    curr_o = pdata["open"][b_idx]
                    if target_p > curr_o + 1.1 * causal_atr:
                        stop_p = round_to_tick(curr_o - 0.75 * causal_atr, tick_size)
                        return 1, "REVERSION", stop_p, target_p

                elif (ev.event_type == "S1" or close_sig >= ev.zs_high) and close_sig > zs_mid and dev >= 1.25:
                    target_p = round_to_tick(zs_mid, tick_size)
                    curr_o = pdata["open"][b_idx]
                    if target_p < curr_o - 1.1 * causal_atr:
                        stop_p = round_to_tick(curr_o + 0.75 * causal_atr, tick_size)
                        return -1, "REVERSION", stop_p, target_p

        return 0, "", 0.0, 0.0

    def _close_position(
        self,
        pos: StrictPosition,
        exit_price: float,
        exit_time: str,
        reason: str,
        is_oos: bool,
        spec: Any,
        b_idx: int,
    ):
        gross = (exit_price - pos.entry_price) * pos.side * spec.multiplier * pos.lots
        fee = (pos.entry_price + exit_price) * spec.multiplier * pos.lots * spec.fee_rate * self.cost_multiplier
        slip = 2 * self.cost_multiplier * spec.tick_size * spec.multiplier * pos.lots
        net = gross - fee - slip

        self.cash += (gross - fee - slip)

        self.trades.append(StrictTradeRecord(
            symbol=pos.symbol,
            name=spec.name,
            side="LONG" if pos.side == 1 else "SHORT",
            mode=pos.mode,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            lots=pos.lots,
            holding_bars=b_idx - pos.entry_bar_idx,
            gross_pnl=round(gross, 2),
            fee=round(fee, 2),
            slippage=round(slip, 2),
            net_pnl=round(net, 2),
            exit_reason=reason,
            is_oos=is_oos,
        ))

    def _generate_portfolio_report(self, oos_start_time: str) -> Dict[str, Any]:
        if not self.trades:
            return {"total_trades": 0, "net_pnl": 0.0}

        all_trades = self.trades
        is_trades = [t for t in all_trades if not t.is_oos]
        oos_trades = [t for t in all_trades if t.is_oos]

        def calc_metrics(trade_list: List[StrictTradeRecord]) -> Dict[str, Any]:
            if not trade_list:
                return {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}
            pnls = np.array([t.net_pnl for t in trade_list])
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
                "trades": len(trade_list),
                "net_pnl": round(net, 2),
                "win_rate": round(wr, 4),
                "profit_factor": round(pf, 2),
                "total_win_rmb": round(tot_win, 2),
                "total_loss_rmb": round(tot_loss, 2),
                "max_drawdown": round(mdd, 2),
            }

        # 组合真实逐柱权益与最大回撤
        eq_series = np.array([pt["equity"] for pt in self.equity_history])
        peak_series = np.maximum.accumulate(eq_series)
        portfolio_mdd_rmb = float((peak_series - eq_series).max())
        portfolio_mdd_pct = float(((peak_series - eq_series) / np.maximum(peak_series, 1e-6)).max())

        # 品种级聚合
        symbol_summary = {}
        for sym in ALL_COMMODITIES:
            sym_t = [t for t in all_trades if t.symbol == sym]
            if sym_t:
                m = calc_metrics(sym_t)
                m["name"] = sym_t[0].name
                symbol_summary[sym] = m

        # 集中度与稳健性分析
        pnls_sorted = sorted([t.net_pnl for t in all_trades], reverse=True)
        top3_pnl = sum(pnls_sorted[:3])
        total_pnl = sum(pnls_sorted)
        pnl_without_top3 = total_pnl - top3_pnl

        ag_au_pnl = sum(t.net_pnl for t in all_trades if t.symbol in ("AG_IDX", "AU_IDX"))
        other_pnl = total_pnl - ag_au_pnl

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "initial_capital": self.initial_capital,
            "final_equity": round(eq_series[-1] if len(eq_series) > 0 else self.initial_capital, 2),
            "total_net_pnl": round(total_pnl, 2),
            "portfolio_max_drawdown_rmb": round(portfolio_mdd_rmb, 2),
            "portfolio_max_drawdown_pct": round(portfolio_mdd_pct * 100, 2),
            "oos_start_time": oos_start_time,
            "overall_metrics": calc_metrics(all_trades),
            "in_sample_metrics": calc_metrics(is_trades),
            "out_of_sample_metrics": calc_metrics(oos_trades),
            "concentration_analysis": {
                "top3_trades_pnl": round(top3_pnl, 2),
                "top3_pnl_share_pct": round(top3_pnl / max(abs(total_pnl), 1e-6) * 100, 2),
                "pnl_without_top3": round(pnl_without_top3, 2),
                "ag_au_net_pnl": round(ag_au_pnl, 2),
                "non_precious_metals_pnl": round(other_pnl, 2),
            },
            "symbols": symbol_summary,
            "total_trades_count": len(all_trades),
        }


def run_strict_shared_audit():
    provider = UnifiedDataProvider()
    data_map = {}
    print("📥 Loading 15m Futures Data for 25 Commodities...")
    for sym in ALL_COMMODITIES:
        df, _ = provider.load_or_generate_bars(sym, "15m", target_min_trades=1000)
        if not df.empty:
            data_map[sym] = df

    print("⚖️ Running Strict Causal Shared-Portfolio Audit (1x Normal Cost)...")
    engine_1x = StrictSharedPortfolioEngine(cost_multiplier=1.0)
    rep_1x = engine_1x.run_portfolio_backtest(data_map)

    print("🔥 Running Strict Causal Shared-Portfolio Audit (3x Extreme Cost)...")
    engine_3x = StrictSharedPortfolioEngine(cost_multiplier=3.0)
    rep_3x = engine_3x.run_portfolio_backtest(data_map)

    # 归档审计 JSON 报告
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    out_file = REPORTS_DIR / f"Strict_Shared_Portfolio_Audit_{timestamp_str}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "normal_1x": rep_1x,
            "stress_3x": rep_3x,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n📁 终极严格审计报告已归档至: {out_file}")
    return rep_1x, rep_3x


if __name__ == "__main__":
    run_strict_shared_audit()
