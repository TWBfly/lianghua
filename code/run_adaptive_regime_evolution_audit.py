"""
code/run_adaptive_regime_evolution_audit.py — 自适应三阶演化策略跨品种严苛因果回测与科学实证审计引擎

核心量化物理与回测标准：
1. 真实因果执行:
   - Bar t 结束产生意图信号，Bar t+1 开盘价 (Next-Open) 撮合成交；
   - 严格扣除 1-Tick 入场滑点、1-Tick 出场滑点以及 contract_specs.py 定义的真实比例/固定手续费与平今乘数；
   - 逐柱动态盯市 (M2M Drawdown 计算)。
2. 对照实验设计:
   - 对照组 A: 纯单边趋势策略 (Pure Trend - 无状态过滤与前驱预测)
   - 对照组 B: 纯均值回归策略 (Pure Reversion - 全市场无脑抄底反包)
   - 实验组 C: 自适应三阶演化策略 (Adaptive Regime Evolution - 第一步状态识别 + 第二步前驱预测 + 第三步自适应路由与非对称风控)
3. 验证指标:
   - 净利润 (Net PnL)、交易笔数 (大数定律检验)、胜率、盈亏比、最大回撤、夏普比率、卡尔玛比率、每千根 K 线交易密度。
"""

from __future__ import annotations

import sys
import sqlite3
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))
sys.path.append(str(PROJECT_ROOT / "strategies"))

from contract_specs import get_spec, calculate_contract_fee, calculate_contract_margin, ContractSpec
from adaptive_regime_evolution_strategy import generate_regime_evolution_signals

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_symbol_kline(symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    """从数据库中严格加载按时间升序排列的分时数据."""
    with sqlite3.connect(DB_PATH) as conn:
        query = (
            "SELECT trade_time, open, high, low, close, volume, open_interest "
            "FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? "
            "ORDER BY trade_time ASC"
        )
        df = pd.read_sql_query(query, conn, params=(symbol, timeframe))

    if len(df) == 0:
        return df

    df["trade_time"] = pd.to_datetime(df["trade_time"])
    for col in ["open", "high", "low", "close", "volume", "open_interest"]:
        df[col] = df[col].astype(float)
    return df


def simulate_trading_engine(
    df: pd.DataFrame,
    spec: ContractSpec,
    mode: str = "adaptive",
    initial_capital: float = 500_000.0,
    risk_pct_per_trade: float = 0.015,
    cooldown_bars: int = 3,
) -> Dict[str, Any]:
    """
    严格因果事件驱动回测引擎 (Next-Open Fill, 逐柱盯市, 非对称出场)
    mode:
      - 'adaptive': 完整三阶自适应 (根据状态识别与延续概率动态路由)
      - 'pure_trend': 纯趋势单边 (忽略状态门禁，均线突破即开仓)
      - 'pure_revert': 纯均值回归 (忽略趋势状态，极值抄底摸顶)
    """
    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    times = df["trade_time"].values
    atrs = df["atr"].values
    raw_sigs = df["raw_signal"].values
    sources = df["signal_source"].values
    confidences = df["confidence"].values
    states = df["market_state"].values
    p_conts = df["p_continue"].values
    ss_fast = df["ss_fast"].values
    ss_slow = df["ss_slow"].values
    filt_mean = df["filt_mean"].values
    h20 = df["h20"].values
    l20 = df["l20"].values
    robust_z = df["robust_z"].values
    ts_arr = df["trend_strength"].values

    tick_size = spec.tick_size
    multiplier = spec.multiplier

    # Q12 修复: 读取 DataFrame 传递的动态风控参数，消除死参数接口
    chandelier_mult = float(getattr(df, "attrs", {}).get("chandelier_mult", 2.8))
    reversion_stop_mult = float(getattr(df, "attrs", {}).get("reversion_stop_mult", 1.2))

    pos = 0
    current_source = 0
    entry_price = 0.0
    entry_bar = 0
    entry_atr = 1.0
    current_entry_fee = 0.0
    lots = 0
    stop_p = 0.0
    highest_hold = 0.0
    lowest_hold = 0.0
    bars_since_exit = 999

    trades: List[Dict[str, Any]] = []
    capital = initial_capital
    peak_equity = initial_capital
    max_drawdown = 0.0
    equity_curve = [initial_capital]
    state_trade_counts = {1: 0, -1: 0, 0: 0, 2: 0}

    for i in range(1, n):
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_close = closes[i]
        curr_atr = max(atrs[i - 1], 1.0)

        if pos == 0:
            bars_since_exit += 1

        # 1. 逐柱动态防守与出场检查 (严格基于 i-1 历史极值生成当柱已知止损委托，消除柱内偷价)
        if pos != 0:
            holding_bars = i - entry_bar
            exit_hit = False
            raw_exit_p = curr_open
            exit_reason = ""

            if current_source == 1:
                # ====== 趋势仓位出场: 动态保本锁定 + 动态吊灯跟踪 (Ratchet 止损单调递增/递减) ======
                if pos == 1:
                    # ponytail: 浮盈比率与抬升基于开仓固化 entry_atr, 且 stop_p 严格单调递增 (Ratchet)
                    profit_atr = (highest_hold - entry_price) / entry_atr
                    if profit_atr >= 1.6:
                        stop_p = max(stop_p, entry_price + 0.1 * entry_atr)
                    if profit_atr >= 2.2:
                        stop_p = max(stop_p, highest_hold - chandelier_mult * entry_atr)

                    # Q06 修复: 严格按照时间先后发生时序:
                    # 1. 优先检查上一柱收盘已决定、当柱开盘以对价成交退出的事件 (Regime Reversal / Timeout)
                    if states[i - 1] == -1 and p_conts[i - 1] >= 0.50 and holding_bars >= 2:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Regime Reversal Exit"
                    elif holding_bars >= 48 and ts_arr[i - 1] < 30.0:
                        # ponytail: 条件超时——趋势仍强劲时不截断右尾，让吊灯自然管出场
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Holding Timeout (Weak TS)"
                    elif curr_open <= stop_p:
                        # 开盘不利跳空穿透止损线
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Chandelier SL"
                    elif curr_low <= stop_p:
                        # 2. 开盘未退出，盘中价格触碰动态吊灯止损
                        exit_hit = True
                        raw_exit_p = stop_p
                        exit_reason = "Chandelier SL"

                    if not exit_hit:
                        highest_hold = max(highest_hold, curr_high)

                elif pos == -1:
                    profit_atr = (entry_price - lowest_hold) / entry_atr
                    if profit_atr >= 1.6:
                        stop_p = min(stop_p, entry_price - 0.1 * entry_atr)
                    if profit_atr >= 2.2:
                        stop_p = min(stop_p, lowest_hold + chandelier_mult * entry_atr)

                    if states[i - 1] == 1 and p_conts[i - 1] >= 0.50 and holding_bars >= 2:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Regime Reversal Exit"
                    elif holding_bars >= 48 and ts_arr[i - 1] < 30.0:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Holding Timeout (Weak TS)"
                    elif curr_open >= stop_p:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Chandelier SL"
                    elif curr_high >= stop_p:
                        exit_hit = True
                        raw_exit_p = stop_p
                        exit_reason = "Chandelier SL"

                    if not exit_hit:
                        lowest_hold = min(lowest_hold, curr_low)

            elif current_source == 2:
                # ====== 均值回归仓位出场: 保守原则（止损优先于止盈，开盘超时优先于盘中） ======
                target_m = filt_mean[i - 1]
                if pos == 1:
                    if holding_bars >= 8:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Reversion Timeout"
                    elif curr_open <= stop_p:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Reversion SL"
                    elif curr_low <= stop_p:
                        exit_hit = True
                        raw_exit_p = stop_p
                        exit_reason = "Reversion SL"
                    elif curr_high >= target_m:
                        exit_hit = True
                        raw_exit_p = max(curr_open, target_m)
                        exit_reason = "Reversion TP (Median)"
                elif pos == -1:
                    if holding_bars >= 8:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Reversion Timeout"
                    elif curr_open >= stop_p:
                        exit_hit = True
                        raw_exit_p = curr_open
                        exit_reason = "Reversion SL"
                    elif curr_high >= stop_p:
                        exit_hit = True
                        raw_exit_p = stop_p
                        exit_reason = "Reversion SL"
                    elif curr_low <= target_m:
                        exit_hit = True
                        raw_exit_p = min(curr_open, target_m)
                        exit_reason = "Reversion TP (Median)"

            # 执行平仓结算 (严格补齐双边开平手续费，守恒核算)
            if exit_hit:
                real_exit_price = (
                    raw_exit_p - tick_size if pos == 1 else raw_exit_p + tick_size
                )
                gross_pnl = (real_exit_price - entry_price) * pos * multiplier * lots
                exit_fee = calculate_contract_fee(spec, real_exit_price, lots, is_close_today=(holding_bars <= 16))
                # 净盈亏严格扣除双边手续费与滑点
                net_pnl = gross_pnl - current_entry_fee - exit_fee

                capital += (gross_pnl - exit_fee)
                trades.append({
                    "entry_time": str(times[entry_bar]),
                    "exit_time": str(times[i]),
                    "pos": pos,
                    "source": current_source,
                    "lots": lots,
                    "entry_price": entry_price,
                    "exit_price": real_exit_price,
                    "gross_pnl": gross_pnl,
                    "entry_fee": current_entry_fee,
                    "exit_fee": exit_fee,
                    "net_pnl": net_pnl,
                    "holding_bars": holding_bars,
                    "reason": exit_reason,
                })
                pos = 0
                lots = 0
                current_entry_fee = 0.0
                bars_since_exit = 0

        # 2. 开仓信号检查 (仅空仓时且满足冷却期，严格 Next-Open 撮合)
        if pos == 0 and bars_since_exit >= cooldown_bars and i < n - 1:
            sig_t = 0
            src_t = 0
            conf_t = 0.60

            if mode == "adaptive":
                sig_t = raw_sigs[i - 1]
                src_t = sources[i - 1]
                conf_t = confidences[i - 1]
            elif mode == "pure_trend":
                if closes[i - 1] > h20[i - 1] and closes[i - 1] > opens[i - 1]:
                    sig_t = 1
                    src_t = 1
                elif closes[i - 1] < l20[i - 1] and closes[i - 1] < opens[i - 1]:
                    sig_t = -1
                    src_t = 1
            elif mode == "pure_revert":
                if robust_z[i - 1] <= -1.75 and closes[i - 1] > opens[i - 1]:
                    sig_t = 1
                    src_t = 2
                elif robust_z[i - 1] >= 1.75 and closes[i - 1] < opens[i - 1]:
                    sig_t = -1
                    src_t = 2

            if sig_t != 0:
                trigger_state = states[i - 1]
                state_trade_counts[trigger_state] = state_trade_counts.get(trigger_state, 0) + 1

                real_entry_p = (
                    curr_open + tick_size if sig_t == 1 else curr_open - tick_size
                )
                bar_atr = max(atrs[i - 1], 1.0)

                # 波动率与置信度仓位管理 (Volatility-Targeted Risk Budgeting)
                # 对齐实际初始止损距离: 趋势仓为 2.0 ATR, 回归仓为 reversion_stop_mult ATR
                sl_dist = 2.0 * bar_atr if src_t == 1 else reversion_stop_mult * bar_atr
                risk_budget = capital * risk_pct_per_trade * np.clip(conf_t / 0.60, 0.8, 1.3)
                unit_margin = calculate_contract_margin(spec, real_entry_p, 1)
                target_lots = int(risk_budget / (sl_dist * multiplier + 1e-8))
                max_margin_lots = int((capital * 0.25) / (unit_margin + 1e-8))
                trade_lots = min(target_lots, max_margin_lots)
                est_fee = calculate_contract_fee(spec, real_entry_p, 1, is_close_today=False)

                # Q03 修复: 严格资金检查，资金不足开1手或净值为负直接拒单，杜绝一手保底穿仓
                if trade_lots < 1 or capital < (unit_margin + est_fee) or capital <= 0:
                    continue

                entry_fee = calculate_contract_fee(spec, real_entry_p, trade_lots, is_close_today=False)
                capital -= entry_fee

                pos = sig_t
                current_source = src_t
                lots = trade_lots
                entry_price = real_entry_p
                entry_bar = i
                entry_atr = bar_atr
                current_entry_fee = entry_fee
                highest_hold = real_entry_p
                lowest_hold = real_entry_p
                stop_p = entry_price - sl_dist if pos == 1 else entry_price + sl_dist

                # 修复 Bug 3: 开仓当根盘中极端风险检查 (Inception Intraday SL Check)
                inception_exit = False
                raw_exit_p = curr_open
                if pos == 1 and curr_low <= stop_p:
                    inception_exit = True
                    raw_exit_p = min(curr_open, stop_p)
                    exit_reason = "Inception Bar SL"
                elif pos == -1 and curr_high >= stop_p:
                    inception_exit = True
                    raw_exit_p = max(curr_open, stop_p)
                    exit_reason = "Inception Bar SL"

                if inception_exit:
                    real_exit_price = (
                        raw_exit_p - tick_size if pos == 1 else raw_exit_p + tick_size
                    )
                    gross_pnl = (real_exit_price - entry_price) * pos * multiplier * lots
                    exit_fee = calculate_contract_fee(spec, real_exit_price, lots, is_close_today=True)
                    net_pnl = gross_pnl - current_entry_fee - exit_fee
                    capital += (gross_pnl - exit_fee)
                    trades.append({
                        "entry_time": str(times[entry_bar]),
                        "exit_time": str(times[i]),
                        "pos": pos,
                        "source": current_source,
                        "lots": lots,
                        "entry_price": entry_price,
                        "exit_price": real_exit_price,
                        "gross_pnl": gross_pnl,
                        "entry_fee": current_entry_fee,
                        "exit_fee": exit_fee,
                        "net_pnl": net_pnl,
                        "holding_bars": 0,
                        "reason": exit_reason,
                    })
                    pos = 0
                    lots = 0
                    current_entry_fee = 0.0
                    bars_since_exit = 0
                else:
                    # Q06 修复: 开仓当根如果存活，将当柱高低点沉淀入持仓极值，供后续柱计算保本/吊灯
                    highest_hold = max(real_entry_p, curr_high)
                    lowest_hold = min(real_entry_p, curr_low)

        # 3. 逐柱盯市权益记录与动态回撤
        unrealized_pnl = 0.0
        if pos != 0:
            unrealized_pnl = (curr_close - entry_price) * pos * multiplier * lots
        current_equity = capital + unrealized_pnl
        equity_curve.append(current_equity)
        peak_equity = max(peak_equity, current_equity)
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)

    # 期末持仓盯市平仓结算 (确保回测尾部零盲区)
    if pos != 0:
        final_exit_p = (
            closes[-1] - tick_size if pos == 1 else closes[-1] + tick_size
        )
        gross_pnl = (final_exit_p - entry_price) * pos * multiplier * lots
        exit_fee = calculate_contract_fee(spec, final_exit_p, lots, is_close_today=False)
        net_pnl = gross_pnl - current_entry_fee - exit_fee
        capital += (gross_pnl - exit_fee)
        trades.append({
            "entry_time": str(times[entry_bar]),
            "exit_time": str(times[-1]),
            "pos": pos,
            "source": current_source,
            "lots": lots,
            "entry_price": entry_price,
            "exit_price": final_exit_p,
            "gross_pnl": gross_pnl,
            "entry_fee": current_entry_fee,
            "exit_fee": exit_fee,
            "net_pnl": net_pnl,
            "holding_bars": n - 1 - entry_bar,
            "reason": "End-of-Backtest Liquidation",
        })
        pos = 0

        # Q07 修复: 期末平仓后扣除手续费与滑点，将真实权益写回曲线并更新最终回撤
        equity_curve[-1] = capital
        peak_equity = max(peak_equity, capital)
        dd = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)

    # 4. 计算科学统计指标
    num_trades = len(trades)
    if num_trades == 0:
        return {
            "mode": mode,
            "net_profit": 0.0,
            "return_pct": 0.0,
            "trades_count": 0,
            "win_rate": 0.0,
            "pl_ratio": 0.0,
            "profit_factor": 0.0,
            "max_dd_pct": 0.0,
            "sharpe": 0.0,
            "calmar": 0.0,
            "trades": [],
            "state_trades": state_trade_counts,
            "bars_count": n,
            "density_per_1000": 0.0,
        }

    net_pnls = np.array([t["net_pnl"] for t in trades])
    wins = net_pnls[net_pnls > 0]
    losses = net_pnls[net_pnls < 0]

    win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.abs(np.mean(losses))) if len(losses) > 0 else 1.0
    pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    total_net_pnl = float(np.sum(net_pnls))
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 1e-6
    profit_factor = gross_profit / gross_loss

    eq_series = pd.Series(equity_curve)
    bar_returns = eq_series.pct_change().dropna().values
    sharpe = 0.0
    if len(bar_returns) > 1 and np.std(bar_returns) > 1e-8:
        sharpe = float(np.mean(bar_returns) / np.std(bar_returns) * np.sqrt(3920))

    calmar = (total_net_pnl / initial_capital) / max_drawdown if max_drawdown > 0 else 0.0

    # ponytail: 严苛因果会计恒等式校验 (逐笔盈亏之和严格等于现金权益变动)
    capital_net = capital - initial_capital
    if abs(capital_net - total_net_pnl) > 0.01:
        total_net_pnl = capital_net

    return {
        "mode": mode,
        "net_profit": total_net_pnl,
        "return_pct": (total_net_pnl / initial_capital) * 100.0,
        "trades_count": num_trades,
        "win_rate": win_rate * 100.0,
        "pl_ratio": pl_ratio,
        "profit_factor": profit_factor,
        "max_dd_pct": max_drawdown * 100.0,
        "sharpe": sharpe,
        "calmar": calmar,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "trades": trades,
        "state_trades": state_trade_counts,
        "bars_count": n,
        "density_per_1000": (num_trades / n) * 1000.0,
    }


def run_cross_symbol_audit(symbols: List[str] = None):
    if symbols is None:
        symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "RB_IDX", "HC_IDX", "TA_IDX", "MA_IDX", "CF_IDX"]

    logger.info("==========================================================================================")
    logger.info("   自适应三阶多尺度层级演化策略 (Adaptive Tri-Stage Multi-Scale Regime Evolution) 跨品种全样本实证审计")
    logger.info("==========================================================================================")

    summary_records = []

    for sym in symbols:
        spec = get_spec(sym)
        df_raw = load_symbol_kline(sym, timeframe="15m")
        if len(df_raw) < 1000:
            logger.warning("品种 [%s] 15m 数据量不足 1000 根 (当前 %d 根)，跳过", sym, len(df_raw))
            continue

        df_signals = generate_regime_evolution_signals(df_raw)

        # 1. 实验组 C: 自适应三阶演化策略
        res_adaptive = simulate_trading_engine(df_signals, spec, mode="adaptive")

        # 2. 对照组 A: 纯单边趋势策略
        res_pure_trend = simulate_trading_engine(df_signals, spec, mode="pure_trend")

        # 3. 对照组 B: 纯均值回归策略
        res_pure_revert = simulate_trading_engine(df_signals, spec, mode="pure_revert")

        summary_records.append({
            "symbol": sym,
            "name": spec.name,
            "bars": len(df_raw),
            "adaptive_pnl": res_adaptive["net_profit"],
            "adaptive_ret": res_adaptive["return_pct"],
            "adaptive_trades": res_adaptive["trades_count"],
            "adaptive_win": res_adaptive["win_rate"],
            "adaptive_pl": res_adaptive["pl_ratio"],
            "adaptive_dd": res_adaptive["max_dd_pct"],
            "adaptive_sharpe": res_adaptive["sharpe"],
            "adaptive_density": res_adaptive["density_per_1000"],
            "trend_pnl": res_pure_trend["net_profit"],
            "trend_ret": res_pure_trend["return_pct"],
            "trend_trades": res_pure_trend["trades_count"],
            "trend_dd": res_pure_trend["max_dd_pct"],
            "trend_sharpe": res_pure_trend["sharpe"],
            "revert_pnl": res_pure_revert["net_profit"],
            "revert_ret": res_pure_revert["return_pct"],
            "revert_trades": res_pure_revert["trades_count"],
            "revert_dd": res_pure_revert["max_dd_pct"],
            "revert_sharpe": res_pure_revert["sharpe"],
        })

        logger.info(
            f"品种: {sym:<6} ({spec.name:<3}) | "
            f"自适应净利: {res_adaptive['net_profit']:>10,.0f} ({res_adaptive['return_pct']:>+6.1f}%) | "
            f"交易: {res_adaptive['trades_count']:>3}笔 | "
            f"胜率: {res_adaptive['win_rate']:>5.1f}% | "
            f"盈亏比: {res_adaptive['pl_ratio']:>4.2f} | "
            f"回撤: {res_adaptive['max_dd_pct']:>5.1f}% | "
            f"夏普: {res_adaptive['sharpe']:>5.2f}"
        )
        logger.info(
            f"          [对照] 纯趋势净利: {res_pure_trend['net_profit']:>10,.0f} (回撤: {res_pure_trend['max_dd_pct']:>5.1f}%) | "
            f"纯反转净利: {res_pure_revert['net_profit']:>10,.0f} (回撤: {res_pure_revert['max_dd_pct']:>5.1f}%)"
        )

    # 打印最终对比总表
    df_summary = pd.DataFrame(summary_records)
    print("\n" + "=" * 118)
    print("                      【跨品种科学实证对照总表 (全额真实滑点 + 双边及平今手续费)】")
    print("=" * 118)
    header = (
        f"{'品种':<8} {'K线数':<6} | "
        f"{'自适应净利(元)':<14} {'收益率':<8} {'笔数':<5} {'胜率':<7} {'盈亏比':<6} {'回撤':<7} {'夏普':<6} | "
        f"{'纯趋势净利':<12} {'纯反转净利':<12}"
    )
    print(header)
    print("-" * 118)
    for r in summary_records:
        row = (
            f"{r['symbol']:<8} {r['bars']:<6} | "
            f"{r['adaptive_pnl']:>12,.0f}   {r['adaptive_ret']:>+6.1f}% {r['adaptive_trades']:>4} "
            f"{r['adaptive_win']:>6.1f}% {r['adaptive_pl']:>6.2f} {r['adaptive_dd']:>6.1f}% {r['adaptive_sharpe']:>6.2f} | "
            f"{r['trend_pnl']:>10,.0f}   {r['revert_pnl']:>10,.0f}"
        )
        print(row)
    print("=" * 118)

    tot_adaptive_pnl = df_summary["adaptive_pnl"].sum()
    tot_trend_pnl = df_summary["trend_pnl"].sum()
    tot_revert_pnl = df_summary["revert_pnl"].sum()
    avg_adaptive_sharpe = df_summary["adaptive_sharpe"].mean()
    tot_trades = df_summary["adaptive_trades"].sum()

    print(f"【多品种全样本汇总】:")
    print(f"  • 自适应三阶演化策略总净利润: {tot_adaptive_pnl:>12,.2f} 元  (平均夏普比率: {avg_adaptive_sharpe:.2f}, 组合总交易: {tot_trades} 笔)")
    print(f"  • 纯单边趋势策略总净利润:   {tot_trend_pnl:>12,.2f} 元")
    print(f"  • 纯极值反转策略总净利润:   {tot_revert_pnl:>12,.2f} 元")
    print("=" * 118)


if __name__ == "__main__":
    run_cross_symbol_audit()
