"""
code/taiyin_calendar_spread_100pct_real.py — 【太阴·北斗】真实双合约 15m K 线级跨期回测
Taiyin Dual-Contract 15m Bar-Level Backtest

核心特性：
1. 100% 纯原始真实双合约 K 线相减 (Real Spread = P_near - P_far)；
2. 信号使用已完成 K 线，下一根 K 线开盘成交；
3. 逐柱盯市，逐笔统计手续费、滑点和净利润；
4. 输出真实样本外、参数扰动、成本压力和账本验证，不模拟订单簿。
"""

from __future__ import annotations

import os
import sys
import math
import sqlite3
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from backtest_metrics import calculate_performance
from taiyin_calendar_spread_15m import CARRY_COST_REGISTRY, CommodityCarryCostProfile
from sync_calendar_spread_pairs import CALENDAR_SPREAD_PAIRS, DB_PATH


def classify_validation(
    holdout_trades: int,
    holdout_net_profit: float,
    profitable_parameter_sets: int,
    triple_cost_net_profit: float,
    ledger_reconciled: bool,
    unclosed_position: bool,
) -> str:
    if (
        not ledger_reconciled
        or unclosed_position
        or holdout_net_profit <= 0
        or triple_cost_net_profit <= 0
    ):
        return "REJECTED"
    if holdout_trades < 30 or profitable_parameter_sets < 12:
        return "INSUFFICIENT_EVIDENCE"
    return "BACKTEST_VALIDATED"


class Taiyin100PctRealSpreadEngine:
    """真实双合约 15m K 线级跨期回测引擎。"""

    def __init__(
        self,
        z_entry: float = 1.8,
        z_exit: float = 0.2,
        z_stop: float = 3.5,
        lookback_window: int = 40,
        days_between_contracts: int = 92
    ):
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.z_stop = z_stop
        self.window = lookback_window
        self.days_between = days_between_contracts

    def calculate_carrying_cost(
        self,
        near_price: float,
        profile: CommodityCarryCostProfile,
        days_between_contracts: Optional[int] = None,
    ) -> float:
        """根据现货持有成本模型计算理论升水上限"""
        days = self.days_between if days_between_contracts is None else days_between_contracts
        dt_years = days / 365.0
        interest_cost = near_price * profile.annual_interest_rate * dt_years
        storage_cost = profile.storage_fee_per_day * days
        total_carry = interest_cost + storage_cost + profile.delivery_fee_fixed + profile.vat_capital_drag
        return total_carry

    def run_pair_real_backtest(
        self,
        df_near: pd.DataFrame,
        df_far: pd.DataFrame,
        profile: CommodityCarryCostProfile,
        pair_info: Dict[str, str],
        initial_capital: float = 1_000_000.0,
        fee_rate: float = 0.00005,
        slippage_ticks: float = 1.0,
        min_leg_volume: float = 10.0,
    ) -> Dict[str, Any]:
        """用完成柱生成信号，并在下一根 K 线开盘成交。"""
        df_near = df_near.set_index("trade_time").sort_index()
        df_far = df_far.set_index("trade_time").sort_index()

        df = pd.DataFrame(index=df_near.index)
        df["near_close"] = df_near["close"]
        df["near_open"] = df_near["open"]
        df["near_vol"] = df_near["volume"]
        df["far_close"] = df_far["close"]
        df["far_open"] = df_far["open"]
        df["far_vol"] = df_far["volume"]
        df = df.dropna()
        df = df.loc[df.index >= pair_info.get("not_before", "2025-01-01")]
        n = len(df)
        if n < self.window + 10:
            return {}

        df["raw_spread"] = df["near_close"] - df["far_close"]
        raw_spreads = df["raw_spread"].to_numpy(dtype=float)
        open_spreads = (df["near_open"] - df["far_open"]).to_numpy(dtype=float)
        near_closes = df["near_close"].to_numpy(dtype=float)
        far_closes = df["far_close"].to_numpy(dtype=float)
        near_opens = df["near_open"].to_numpy(dtype=float)
        far_opens = df["far_open"].to_numpy(dtype=float)
        near_vols = df["near_vol"].to_numpy(dtype=float)
        far_vols = df["far_vol"].to_numpy(dtype=float)
        times = df.index.to_numpy()

        spread_series = df["raw_spread"]
        spread_ma = spread_series.rolling(self.window).mean().to_numpy(dtype=float)
        spread_std = spread_series.rolling(self.window).std().to_numpy(dtype=float) + 1e-6
        zscores = (raw_spreads - spread_ma) / spread_std
        near_returns_1h = df["near_close"].pct_change(4).fillna(0.0).to_numpy(dtype=float)

        cash = float(initial_capital)
        pos = 0
        entry_spread = 0.0
        entry_time = ""
        lots = profile.default_lots
        mult = profile.multiplier
        tick = profile.tick_size
        days_between = int(pair_info.get("days_between_contracts", self.days_between))
        entry_fee = 0.0
        entry_slippage = 0.0
        pending: Optional[Dict[str, Any]] = None
        trades: List[Dict[str, Any]] = []
        equity_points: List[Dict[str, Any]] = []

        def costs(near_price: float, far_price: float) -> Tuple[float, float]:
            fee = (near_price + far_price) * mult * lots * fee_rate
            slippage = tick * mult * lots * slippage_ticks * 2
            return fee, slippage

        def close_position(
            i: int,
            near_price: float,
            far_price: float,
            reason: str,
        ) -> float:
            nonlocal cash, pos
            exit_spread = near_price - far_price
            gross_pnl = pos * (exit_spread - entry_spread) * mult * lots
            exit_fee, exit_slippage = costs(near_price, far_price)
            net_pnl = gross_pnl - entry_fee - entry_slippage - exit_fee - exit_slippage
            cash += gross_pnl - exit_fee - exit_slippage
            trades.append({
                "symbol": profile.symbol,
                "pair_name": pair_info["name"],
                "contract_near": pair_info["near"],
                "contract_far": pair_info["far"],
                "direction": "BUY_SPREAD" if pos == 1 else "SELL_SPREAD",
                "entry_time": entry_time,
                "exit_time": str(times[i]),
                "entry_spread": entry_spread,
                "exit_spread": exit_spread,
                "lots": lots,
                "gross_pnl": gross_pnl,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "entry_slippage": entry_slippage,
                "exit_slippage": exit_slippage,
                "net_pnl": net_pnl,
                "pnl": net_pnl,
                "reason": reason,
            })
            turnover = (near_price + far_price) * mult * lots
            pos = 0
            return turnover

        for i in range(self.window, n):
            turnover = 0.0
            if pending and pending["fill_index"] == i:
                if pending["action"] == "ENTER":
                    pos = int(pending["direction"])
                    entry_spread = open_spreads[i]
                    entry_time = str(times[i])
                    entry_fee, entry_slippage = costs(near_opens[i], far_opens[i])
                    cash -= entry_fee + entry_slippage
                    turnover += (near_opens[i] + far_opens[i]) * mult * lots
                else:
                    turnover += close_position(
                        i, near_opens[i], far_opens[i], pending["reason"]
                    )
                pending = None

            s = raw_spreads[i]
            z = zscores[i]
            p_near = near_closes[i]
            p_far = far_closes[i]
            equity = cash + (pos * (s - entry_spread) * mult * lots if pos else 0.0)
            equity_points.append({
                "trade_time": str(times[i]),
                "equity": equity,
                "cash": cash,
                "turnover": turnover,
            })

            if i + 1 >= n or pending is not None:
                continue

            liquid = near_vols[i] >= min_leg_volume and far_vols[i] >= min_leg_volume
            carry_cost = self.calculate_carrying_cost(p_near, profile, days_between)
            contango_bound = -carry_cost
            fee_cost, slip_cost = costs(p_near, p_far)
            min_friction_spread = (fee_cost + slip_cost) / (mult * lots) * 3.0
            has_spread_edge = abs(s - spread_ma[i]) >= min_friction_spread

            if pos == 0 and liquid and has_spread_edge:
                direction = 0
                if profile.structure_type == "BACKWARDATION_MOMENTUM":
                    if z >= (self.z_entry - 0.2) and near_returns_1h[i] > 0:
                        direction = 1
                    elif z <= -(self.z_entry - 0.2) and near_returns_1h[i] < 0:
                        direction = -1
                else:
                    if s <= contango_bound or z <= -self.z_entry:
                        direction = 1
                    elif z >= (self.z_entry + 0.2):
                        direction = -1
                if direction:
                    pending = {"action": "ENTER", "direction": direction, "fill_index": i + 1}

            elif pos and liquid:
                unrealized_pnl = pos * (s - entry_spread) * mult * lots
                if pos == 1:
                    exit_signal = (
                        z <= self.z_exit
                        if profile.structure_type == "BACKWARDATION_MOMENTUM"
                        else z >= -self.z_exit
                    )
                    stop_signal = (
                        (profile.structure_type == "CONTANGO_REVERSION" and s <= contango_bound * 1.4)
                        or (profile.structure_type == "BACKWARDATION_MOMENTUM" and s - entry_spread <= -6.0)
                        or unrealized_pnl <= -8000.0
                    )
                else:
                    exit_signal = (
                        z >= -self.z_exit
                        if profile.structure_type == "BACKWARDATION_MOMENTUM"
                        else z <= self.z_exit
                    )
                    stop_signal = (
                        z >= self.z_stop
                        or (profile.structure_type == "BACKWARDATION_MOMENTUM" and entry_spread - s <= -6.0)
                        or unrealized_pnl <= -8000.0
                    )
                if exit_signal or stop_signal:
                    pending = {
                        "action": "EXIT",
                        "fill_index": i + 1,
                        "reason": "SIGNAL" if exit_signal else "STOP",
                    }

        unclosed_position = False
        if pos:
            last = n - 1
            liquid = near_vols[last] >= min_leg_volume and far_vols[last] >= min_leg_volume
            if liquid:
                turnover = close_position(
                    last, near_closes[last], far_closes[last], "END_OF_DATA"
                )
                equity_points[-1]["cash"] = cash
                equity_points[-1]["equity"] = cash
                equity_points[-1]["turnover"] += turnover
            else:
                unclosed_position = True

        df_trades = pd.DataFrame(trades)
        total_trades = len(df_trades)
        net_pnls = df_trades["net_pnl"] if total_trades else pd.Series(dtype=float)
        wins = int((net_pnls > 0).sum())
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profit = float(net_pnls[net_pnls > 0].sum())
        gross_loss = abs(float(net_pnls[net_pnls < 0].sum()))
        plr = gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0)

        eq_arr = np.array([point["equity"] for point in equity_points], dtype=float)
        peaks = np.maximum.accumulate(eq_arr)
        dds = (peaks - eq_arr) / peaks
        max_dd_pct = float(np.max(dds)) * 100.0 if len(dds) else 0.0
        final_equity = float(eq_arr[-1])
        net_profit = final_equity - initial_capital
        ret_pct = round(net_profit / initial_capital * 100.0, 2)

        daily_results = []
        peak = float(initial_capital)
        previous = float(initial_capital)
        curve_frame = pd.DataFrame(equity_points)
        curve_frame["date"] = curve_frame["trade_time"].str[:10]
        for date, group in curve_frame.groupby("date", sort=True):
            end_equity = float(group.iloc[-1]["equity"])
            peak = max(peak, end_equity)
            daily_results.append({
                "date": date,
                "end_equity": end_equity,
                "daily_return": end_equity / previous - 1.0 if previous else 0.0,
                "drawdown": (peak - end_equity) / peak if peak else 0.0,
                "turnover": float(group["turnover"].sum()),
            })
            previous = end_equity
        performance = calculate_performance(daily_results, initial_capital)

        realized_net = float(net_pnls.sum())
        ledger_reconciled = bool(
            not unclosed_position
            and abs((initial_capital + realized_net) - cash) <= 0.01
            and abs(cash - final_equity) <= 0.01
        )

        return {
            "symbol": profile.symbol,
            "name": profile.name,
            "pair_name": pair_info["name"],
            "near_contract": pair_info["near"],
            "far_contract": pair_info["far"],
            "start_time": str(times[self.window]),
            "end_time": str(times[-1]),
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_loss_ratio": round(plr, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "net_profit_rmb": round(net_profit, 2),
            "return_pct": ret_pct,
            "final_cash": round(cash, 2),
            "final_equity": round(final_equity, 2),
            "ledger_reconciled": ledger_reconciled,
            "unclosed_position": unclosed_position,
            "equity_curve": curve_frame,
            "daily_results": daily_results,
            "sharpe_ratio": round(performance["sharpe_ratio"], 4),
            "sortino_ratio": round(performance["sortino_ratio"], 4),
            "calmar_ratio": round(performance["calmar_ratio"], 4),
            "fee_rate": fee_rate,
            "slippage_ticks": slippage_ticks,
            "trades": df_trades,
        }


def validate_pair(
    df_near: pd.DataFrame,
    df_far: pd.DataFrame,
    profile: CommodityCarryCostProfile,
    pair_info: Dict[str, Any],
    fee_rate: float = 0.00005,
    slippage_ticks: float = 1.0,
    min_leg_volume: float = 10.0,
) -> Dict[str, Any]:
    """Run only observed holdout, parameter, cost, and ledger checks."""
    near = df_near.set_index("trade_time").sort_index()
    far = df_far.set_index("trade_time").sort_index()
    common = near.index.intersection(far.index).sort_values()
    common = common[common >= pair_info.get("not_before", "2025-01-01")]
    near = near.loc[common].reset_index()
    far = far.loc[common].reset_index()
    cut = int(len(common) * 0.70)
    base_fee = float(pair_info.get("fee_rate", fee_rate))
    base_slippage = float(pair_info.get("slippage_ticks", slippage_ticks))

    def run(
        near_frame: pd.DataFrame,
        far_frame: pd.DataFrame,
        *,
        window: int = 40,
        z_entry: float = 1.8,
        cost_multiplier: int = 1,
    ) -> Dict[str, Any]:
        return Taiyin100PctRealSpreadEngine(
            z_entry=z_entry, lookback_window=window
        ).run_pair_real_backtest(
            near_frame,
            far_frame,
            profile,
            pair_info,
            fee_rate=base_fee * cost_multiplier,
            slippage_ticks=base_slippage * cost_multiplier,
            min_leg_volume=min_leg_volume,
        )

    full = run(near, far)
    holdout_near = near.iloc[cut:].reset_index(drop=True)
    holdout_far = far.iloc[cut:].reset_index(drop=True)
    holdout = run(holdout_near, holdout_far)

    profitable_parameter_sets = 0
    parameter_results = []
    for window in (20, 40, 80, 120):
        for z_entry in (1.4, 1.8, 2.2, 2.6):
            result = run(
                holdout_near,
                holdout_far,
                window=window,
                z_entry=z_entry,
            )
            net_profit = float(result.get("net_profit_rmb", 0.0)) if result else 0.0
            passed = bool(
                result
                and net_profit > 0
                and result["ledger_reconciled"]
                and not result["unclosed_position"]
            )
            profitable_parameter_sets += int(passed)
            parameter_results.append({
                "window": window,
                "z_entry": z_entry,
                "net_profit_rmb": net_profit,
                "passed": passed,
            })

    cost_stress = {1: full, 2: run(near, far, cost_multiplier=2), 3: run(near, far, cost_multiplier=3)}
    triple_cost_net_profit = float(cost_stress[3].get("net_profit_rmb", 0.0))
    status = classify_validation(
        int(holdout.get("total_trades", 0)) if holdout else 0,
        float(holdout.get("net_profit_rmb", 0.0)) if holdout else 0.0,
        profitable_parameter_sets,
        triple_cost_net_profit,
        bool(full and full["ledger_reconciled"]),
        bool(not full or full["unclosed_position"]),
    )
    return {
        "full": full,
        "holdout": holdout,
        "parameter_results": parameter_results,
        "profitable_parameter_sets": profitable_parameter_sets,
        "cost_stress": cost_stress,
        "triple_cost_net_profit": triple_cost_net_profit,
        "status": status,
    }


def run_100pct_real_calendar_research():
    """执行全部真实双合约的 K 线级回测和可复现验证。"""
    print("=" * 132)
    print("【太阴·北斗】真实双合约 15m K 线级回测")
    print("信号: 完成柱收盘 | 成交: 下一柱开盘 | 成本: 双腿手续费+滑点 | 非 Tick/盘口/订单簿回测")
    print("默认成本假设: fee_rate=0.00005, slippage=1 tick/leg；同时报告 3 倍成本压力")
    print("=" * 132)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='futures_contract_bars';")
    if cursor.fetchone()[0] == 0:
        print("数据库中没有 futures_contract_bars，请先运行 sync_calendar_spread_pairs.py")
        conn.close()
        return

    validations = []
    for pair in CALENDAR_SPREAD_PAIRS:
        sym = pair["symbol"]
        profile = CARRY_COST_REGISTRY.get(sym)
        if not profile:
            continue
        df_near = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume FROM futures_contract_bars WHERE contract=? AND timeframe='15m' ORDER BY trade_time ASC",
            conn, params=(pair["near"],)
        )
        df_far = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume FROM futures_contract_bars WHERE contract=? AND timeframe='15m' ORDER BY trade_time ASC",
            conn, params=(pair["far"],)
        )
        if len(df_near) < 200 or len(df_far) < 200:
            validations.append({"pair": pair, "status": "INSUFFICIENT_EVIDENCE"})
            continue
        validation = validate_pair(df_near, df_far, profile, pair)
        validation["pair"] = pair
        validations.append(validation)

    conn.close()
    completed = [item for item in validations if item.get("full")]
    if not completed:
        print("没有足够的对齐双合约数据")
        return

    print(
        f"{'品种':<7} {'合约对':<20} {'交易':>5} {'净胜率':>8} {'M2M回撤':>9} "
        f"{'净利润':>12} {'尾部交易':>8} {'尾部净利':>11} {'参数':>6} {'3倍成本':>11} {'状态':>23}"
    )
    print("-" * 132)
    for item in validations:
        pair = item["pair"]
        if not item.get("full"):
            print(f"{pair['symbol']:<7} {pair['name']:<20} {'-':>5} {'-':>8} {'-':>9} {'-':>12} {'-':>8} {'-':>11} {'-':>6} {'-':>11} {item['status']:>23}")
            continue
        full = item["full"]
        holdout = item["holdout"] or {}
        print(
            f"{pair['symbol']:<7} {pair['name']:<20} {full['total_trades']:>5} "
            f"{full['win_rate_pct']:>7.1f}% {full['max_drawdown_pct']:>8.2f}% "
            f"{full['net_profit_rmb']:>12,.0f} {holdout.get('total_trades', 0):>8} "
            f"{holdout.get('net_profit_rmb', 0):>11,.0f} "
            f"{item['profitable_parameter_sets']:>4}/16 {item['triple_cost_net_profit']:>11,.0f} "
            f"{item['status']:>23}"
        )

    total_net = sum(item["full"]["net_profit_rmb"] for item in completed)
    total_trades = sum(item["full"]["total_trades"] for item in completed)
    profitable = sum(item["full"]["net_profit_rmb"] > 0 for item in completed)
    statuses = pd.Series([item["status"] for item in validations]).value_counts()
    print("-" * 132)
    print(f"完整组合: {len(completed)} 对 | 盈利 {profitable}/{len(completed)} | 交易 {total_trades} | 净利润 ¥{total_net:,.2f}")
    print("验证状态:", ", ".join(f"{name}={count}" for name, count in statuses.items()))
    print("BACKTEST_VALIDATED 仅代表历史回测闸门通过，不代表模拟盘或实盘许可。")


if __name__ == "__main__":
    run_100pct_real_calendar_research()
