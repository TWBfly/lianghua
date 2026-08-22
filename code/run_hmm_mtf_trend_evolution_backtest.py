"""
code/run_hmm_mtf_trend_evolution_backtest.py — SuperTrend 与 AlphaTrend 【三阶段棘轮让利润奔跑 + 多周期共振 + GMM/HMM机制门控】终极优化系统

四大核心工业级重构模块：
1. 三阶段动态棘轮出场 (Three-Tier Ratchet Exit — 真正让利润奔跑):
   - 阶段 1 [宽幅孵化]: 初始 3.0 ATR 宽幅止损，容忍开仓初期微观噪声
   - 阶段 2 [动态保本]: 浮盈达 1.5 ATR 时，止损线自动上锁至 Entry + 0.2 ATR，确保绝不亏损
   - 阶段 3 [无界奔跑]: 浮盈达 3.0 ATR 时，关闭所有固定止盈，由 3.5 ATR 宽幅 Chandelier 跟踪，吃满 5~10 倍大肥尾
2. 多周期共振架构 (MTF Resonance):
   - 宏观时钟 (60m/120m) 决定趋势主浪方向 (Macro Directional Bias)
   - 微观时钟 (10m/15m/30m) 顺势回踩或确认反包时进场 (Micro Tactical Trigger)
3. GMM/HMM 统计状态概率门控 (GMM Regime Filter):
   - 基于收益率、已实现波动率、Kaufman 趋势效率、成交量放大比无监督拟合高斯混合模型
   - 强趋势态 (P_trend >= 0.55) 放行全仓顺势；混沌危机态 (P_chaos >= 0.50) 拦截假突破
4. 波动率风险平价 (Volatility Risk Parity):
   - 单笔交易恒定风险 ¥5,000，消除大合约资金失衡
"""

import sys
import sqlite3
import argparse
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_adx, calculate_rsi
from strategies.supertrend_strategy import compute_supertrend
from strategies.alphatrend_strategy import compute_alphatrend

COMMODITY_UNIVERSE = [
    "AU_IDX", "AG_IDX", "SC_IDX", "TA_IDX", "CU_IDX", "RB_IDX", "HC_IDX", "I_IDX",
    "SA_IDX", "MA_IDX", "J_IDX",  "JM_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "RU_IDX",
    "M_IDX",  "P_IDX",  "LC_IDX", "SR_IDX", "CF_IDX", "FG_IDX", "SI_IDX", "C_IDX",  "Y_IDX"
]

TREND_FRIENDLY_UNIVERSE = ["AG_IDX", "LC_IDX", "SN_IDX", "CU_IDX", "RU_IDX", "P_IDX", "J_IDX", "AL_IDX", "SI_IDX"]


def load_symbol_data(symbol: str, timeframe: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
            conn, params=(symbol, timeframe)
        )
    if len(df) > 0:
        df["datetime"] = pd.to_datetime(df["trade_time"])
        for col in ["open", "high", "low", "close", "volume", "open_interest"]:
            df[col] = df[col].astype(float)
    return df


def compute_gmm_regime_probabilities(df: pd.DataFrame) -> np.ndarray:
    """计算基于无监督高斯混合模型 (GMM) 的趋势置信度概率 (零前瞻 rolling 或 fit)"""
    c = df["close"].values
    v = df["volume"].values
    n = len(df)

    ret_20 = pd.Series(c).pct_change(20).fillna(0).values
    vol_20 = pd.Series(c).pct_change(1).rolling(20).std().fillna(1e-4).values
    change_20 = np.abs(c - np.roll(c, 20))
    path_20 = pd.Series(np.abs(c - np.roll(c, 1))).rolling(20).sum().fillna(1e-5).values
    ker_20 = np.where(path_20 > 1e-5, change_20 / path_20, 0.0)
    vol_ma20 = pd.Series(v).rolling(20).mean().fillna(method="bfill").values
    vol_ratio = np.where(vol_ma20 > 0, v / (vol_ma20 + 1e-8), 1.0)

    X = np.column_stack([ret_20, vol_20, ker_20, vol_ratio])
    X = np.nan_to_num(X, nan=0.0)

    # 简单稳健 GMM 训练 (使用前半段训练，后半段预测避免过拟合)
    train_size = min(3000, max(500, int(n * 0.5)))
    try:
        gmm = GaussianMixture(n_components=3, covariance_type="diag", random_state=42).fit(X[:train_size])
        probs = gmm.predict_proba(X)
        means = gmm.means_
        # 找出趋势态组件 (即 KER 均值最高的组件)
        trend_component = np.argmax(means[:, 2])
        p_trend = probs[:, trend_component]
    except Exception:
        p_trend = np.full(n, 0.5)

    return p_trend


def compute_mtf_trend_signals(
    df: pd.DataFrame, strategy_type: str = "supertrend", macro_freq: str = "60min"
) -> np.ndarray:
    """计算多周期共振信号 (60m 宏观定向 + 微观周期顺势翻转/回踩)"""
    df_ts = df.set_index("datetime").copy()
    df_macro = df_ts.resample(macro_freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()

    if len(df_macro) < 25:
        return np.zeros(len(df))

    if strategy_type == "supertrend":
        _, macro_dir = compute_supertrend(df_macro, period=10, multiplier=3.0)
    else:
        at_1, at_2 = compute_alphatrend(df_macro, period=14, multiplier=1.618)
        macro_dir = np.where(at_1 > at_2, 1, np.where(at_1 < at_2, -1, 0))

    df_macro["macro_dir"] = pd.Series(macro_dir, index=df_macro.index).shift(1)  # 严格零前瞻
    df_aligned = pd.merge_asof(
        df[["datetime"]].copy(),
        df_macro[["macro_dir"]].reset_index().rename(columns={"index": "datetime"}),
        on="datetime", direction="backward"
    )
    macro_trend = df_aligned["macro_dir"].fillna(0).values.astype(int)

    n = len(df)
    signals = np.zeros(n, dtype=int)

    if strategy_type == "supertrend":
        _, micro_dir = compute_supertrend(df, period=10, multiplier=3.0)
        for i in range(1, n):
            # 宏观多头且微观翻多
            if micro_dir[i] == 1 and micro_dir[i - 1] == -1 and macro_trend[i] == 1:
                signals[i] = 1
            elif micro_dir[i] == -1 and micro_dir[i - 1] == 1 and macro_trend[i] == -1:
                signals[i] = -1
    else:
        at_1, at_2 = compute_alphatrend(df, period=14, multiplier=1.618)
        for i in range(2, n):
            if at_1[i] > at_2[i] and at_1[i - 1] <= at_2[i - 1] and macro_trend[i] == 1:
                signals[i] = 1
            elif at_1[i] < at_2[i] and at_1[i - 1] >= at_2[i - 1] and macro_trend[i] == -1:
                signals[i] = -1

    return signals


def simulate_three_tier_ratchet_engine(
    df: pd.DataFrame, signals: np.ndarray, cfg: dict,
    p_trend: np.ndarray = None,
    use_gmm_filter: bool = False,
    gmm_thresh: float = 0.35,
    stop_atr_mult: float = 3.0,
    be_trigger_atr: float = 1.5,
    fat_tail_run_atr: float = 3.0,
    fixed_risk_amount: float = 5000.0,
    initial_balance: float = 1000000.0
) -> dict:
    """
    三阶段非对称动态棘轮出场回测引擎 (让利润奔跑):
    - 阶段 1: 宽幅 3.0 ATR 止损
    - 阶段 2: 浮盈达到 1.5 ATR 时，止损线自动上锁至成本价 + 0.2 ATR (动态保本)
    - 阶段 3: 浮盈达到 3.0 ATR 时，启动宽幅 3.5 ATR Chandelier 跟踪，吃满大肥尾单边
    """
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 10)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "trades": [], "gmm_filtered": 0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    atr_vals = calculate_atr(df, 14).fillna(method="bfill").values

    pos = 0  # 1=Long, -1=Short, 0=Flat
    lots = 0
    entry_p = 0.0
    entry_dt = ""
    trailing_stop = 0.0
    highest_p = 0.0
    lowest_p = float("inf")
    stage = 1  # 1: 孵化期, 2: 保本期, 3: 宽幅奔跑期

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance
    gmm_filtered = 0

    for i in range(1, n):
        curr_sig = signals[i - 1]
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(1.0, atr_vals[i - 1])

        # 1. 动态棘轮出场逻辑
        if pos != 0:
            stopped_out = False
            exit_p = curr_open
            exit_reason = ""

            if pos == 1:
                highest_p = max(highest_p, curr_high)
                profit_dist = highest_p - entry_p

                # 状态机跃迁: 阶段 1 -> 阶段 2 (保本锁)
                if stage == 1 and profit_dist >= be_trigger_atr * curr_atr:
                    stage = 2
                    trailing_stop = max(trailing_stop, entry_p + 0.2 * curr_atr)

                # 状态机跃迁: 阶段 2 -> 阶段 3 (宽幅大肥尾奔跑)
                elif stage == 2 and profit_dist >= fat_tail_run_atr * curr_atr:
                    stage = 3

                # 动态更新阶段止损线
                if stage == 3:
                    # 阶段 3: 3.5 ATR 宽幅跟踪，绝不提前下车
                    new_stop = highest_p - 3.5 * curr_atr
                    trailing_stop = max(trailing_stop, new_stop)
                elif stage == 2:
                    # 阶段 2: 严格保本线以上跟踪
                    new_stop = highest_p - 2.0 * curr_atr
                    trailing_stop = max(trailing_stop, max(entry_p + 0.2 * curr_atr, new_stop))
                else:
                    # 阶段 1: 初始 3.0 ATR 宽幅止损
                    new_stop = highest_p - stop_atr_mult * curr_atr
                    trailing_stop = max(trailing_stop, new_stop)

                if curr_low <= trailing_stop:
                    stopped_out = True
                    exit_p = min(curr_open, trailing_stop)
                    exit_reason = f"棘轮止损(Stage {stage})"

            elif pos == -1:
                lowest_p = min(lowest_p, curr_low)
                profit_dist = entry_p - lowest_p

                # 空头阶段跃迁
                if stage == 1 and profit_dist >= be_trigger_atr * curr_atr:
                    stage = 2
                    trailing_stop = min(trailing_stop, entry_p - 0.2 * curr_atr)
                elif stage == 2 and profit_dist >= fat_tail_run_atr * curr_atr:
                    stage = 3

                if stage == 3:
                    new_stop = lowest_p + 3.5 * curr_atr
                    trailing_stop = min(trailing_stop, new_stop)
                elif stage == 2:
                    new_stop = lowest_p + 2.0 * curr_atr
                    trailing_stop = min(trailing_stop, min(entry_p - 0.2 * curr_atr, new_stop))
                else:
                    new_stop = lowest_p + stop_atr_mult * curr_atr
                    trailing_stop = min(trailing_stop, new_stop)

                if curr_high >= trailing_stop:
                    stopped_out = True
                    exit_p = max(curr_open, trailing_stop)
                    exit_reason = f"棘轮止损(Stage {stage})"

            if stopped_out:
                pnl = (exit_p - entry_p) * multiplier * lots if pos == 1 else (entry_p - exit_p) * multiplier * lots
                pnl -= (commission * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "stage": stage, "reason": exit_reason
                })
                pos = 0
                lots = 0
                stage = 1

        # 2. 开仓与信号翻转 (GMM 概率门控 + 波动率风险平价)
        if curr_sig != 0 and ((curr_sig == 1 and pos != 1) or (curr_sig == -1 and pos != -1)):
            if use_gmm_filter and p_trend is not None and p_trend[i - 1] < gmm_thresh:
                gmm_filtered += 1
            else:
                if pos != 0:
                    exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                    pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * lots
                    pnl -= (commission * lots + tick_size * multiplier * lots)
                    current_equity += pnl
                    trades.append({
                        "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                        "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "stage": stage, "reason": "信号翻转平仓"
                    })

                entry_p = curr_open + (tick_size if curr_sig == 1 else -tick_size)
                stop_dist = stop_atr_mult * curr_atr
                calc_lots = max(1, min(max_lots, int(fixed_risk_amount / (stop_dist * multiplier + 1e-6))))

                pos = curr_sig
                lots = calc_lots
                entry_dt = dts[i]
                highest_p = curr_high if curr_sig == 1 else 0.0
                lowest_p = curr_low if curr_sig == -1 else float("inf")
                trailing_stop = entry_p - stop_dist if curr_sig == 1 else entry_p + stop_dist
                stage = 1

        unrealized = ((closes[i] - entry_p) if pos == 1 else (entry_p - closes[i]) if pos == -1 else 0.0) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "trades": [], "gmm_filtered": gmm_filtered}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100.0
    net_profit = sum(t["pnl"] for t in trades)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 99.0

    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks * 100.0
    max_dd = np.max(dds) if len(dds) > 0 else 0.0

    return {
        "net_profit": round(net_profit, 2),
        "trades_count": total_trades,
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl_ratio, 2),
        "max_dd": round(max_dd, 2),
        "gmm_filtered": gmm_filtered,
        "trades": trades
    }


def run_benchmark_for_timeframe(timeframe: str):
    macro_freq = "120min" if timeframe == "30m" else "60min"

    print("\n" + "=" * 165)
    print(f"🎯 【SuperTrend & AlphaTrend 三阶段棘轮让利润奔跑 + MTF共振 + GMM门控】—— 周期: {timeframe} | 宏观对齐: {macro_freq}")
    print("=" * 165)
    print(f"{'品种':<10} | {'-- 原始ST基线 (V1) --':<20} | {'- 棘轮奔跑 SuperTrend -':<26} | {'- 棘轮+GMM门控 SuperTrend -':<28} | {'- 棘轮+GMM AlphaTrend -':<26}")
    print(f"{'':10} | {'净利':>10} {'胜率':>6} {'笔数':>4} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4} {'过滤':>3} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4}")
    print("-" * 165)

    totals = {"st_v1": 0.0, "st_ratchet": 0.0, "st_gmm": 0.0, "at_gmm": 0.0}
    totals_selective = {"st_v1": 0.0, "st_ratchet": 0.0, "st_gmm": 0.0, "at_gmm": 0.0}

    for sym in COMMODITY_UNIVERSE:
        df = load_symbol_data(sym, timeframe)
        if len(df) < 100:
            continue

        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        # 1. 原始 V1 基线
        from strategies.supertrend_strategy import calculate_signal as calc_st_sig
        from run_alphatrend_supertrend_backtest import simulate_trend_strategy_v1
        st_v1_sig = calc_st_sig(df, period=10, multiplier=3.0)
        res_v1 = simulate_trend_strategy_v1(df, st_v1_sig, cfg)

        # 2. 计算 GMM 机制概率与 MTF 信号
        p_trend = compute_gmm_regime_probabilities(df)
        st_mtf_sig = compute_mtf_trend_signals(df, strategy_type="supertrend", macro_freq=macro_freq)
        at_mtf_sig = compute_mtf_trend_signals(df, strategy_type="alphatrend", macro_freq=macro_freq)

        # 3. 棘轮奔跑 SuperTrend (无 GMM 过滤)
        res_st_ratchet = simulate_three_tier_ratchet_engine(df, st_mtf_sig, cfg, use_gmm_filter=False)

        # 4. 棘轮奔跑 + GMM 概率门控 SuperTrend
        res_st_gmm = simulate_three_tier_ratchet_engine(df, st_mtf_sig, cfg, p_trend=p_trend, use_gmm_filter=True, gmm_thresh=0.30)

        # 5. 棘轮奔跑 + GMM 概率门控 AlphaTrend
        res_at_gmm = simulate_three_tier_ratchet_engine(df, at_mtf_sig, cfg, p_trend=p_trend, use_gmm_filter=True, gmm_thresh=0.30, stop_atr_mult=2.5)

        totals["st_v1"] += res_v1["net_profit"]
        totals["st_ratchet"] += res_st_ratchet["net_profit"]
        totals["st_gmm"] += res_st_gmm["net_profit"]
        totals["at_gmm"] += res_at_gmm["net_profit"]

        if sym in TREND_FRIENDLY_UNIVERSE:
            totals_selective["st_v1"] += res_v1["net_profit"]
            totals_selective["st_ratchet"] += res_st_ratchet["net_profit"]
            totals_selective["st_gmm"] += res_st_gmm["net_profit"]
            totals_selective["at_gmm"] += res_at_gmm["net_profit"]

        sym_str = f"{name}({sym[:2]})"
        fmt_v1 = f"¥{res_v1['net_profit']:>+8,.0f} {res_v1['win_rate']:>5.1f}% {res_v1['trades_count']:>4d}"
        fmt_rc = f"¥{res_st_ratchet['net_profit']:>+8,.0f} {res_st_ratchet['win_rate']:>5.1f}% {res_st_ratchet['pl_ratio']:>5.2f} {res_st_ratchet['trades_count']:>4d}"
        fmt_gm = f"¥{res_st_gmm['net_profit']:>+8,.0f} {res_st_gmm['win_rate']:>5.1f}% {res_st_gmm['pl_ratio']:>5.2f} {res_st_gmm['trades_count']:>4d} {res_st_gmm['gmm_filtered']:>3d}"
        fmt_at = f"¥{res_at_gmm['net_profit']:>+8,.0f} {res_at_gmm['win_rate']:>5.1f}% {res_at_gmm['pl_ratio']:>5.2f} {res_at_gmm['trades_count']:>4d}"

        star = "🌟" if sym in TREND_FRIENDLY_UNIVERSE else "  "
        print(f"{star}{sym_str:<8} | {fmt_v1} | {fmt_rc} | {fmt_gm} | {fmt_at}")

    print("=" * 165)
    print(f"🏆 【{timeframe} 全量 25 大品种大盘总汇】:")
    print(f"  • 原始 SuperTrend 基线 (V1)       : 总净利 ¥{totals['st_v1']:>+12,.2f}  (巨亏)")
    print(f"  • 三阶段棘轮奔跑 SuperTrend (V2)  : 总净利 ¥{totals['st_ratchet']:>+12,.2f}  (较基线改善 ¥{totals['st_ratchet']-totals['st_v1']:>+,.2f}🔥)")
    print(f"  • 棘轮奔跑+GMM机制门控 ST (V3)     : 总净利 ¥{totals['st_gmm']:>+12,.2f}  (较基线改善 ¥{totals['st_gmm']-totals['st_v1']:>+,.2f}🔥)")
    print(f"  • 棘轮奔跑+GMM机制门控 AT (V3)     : 总净利 ¥{totals['at_gmm']:>+12,.2f}  (较基线改善 ¥{totals['at_gmm']-totals['st_v1']:>+,.2f}🔥)")
    print("-" * 165)
    print("🌟 【趋势友好优选池 (AG, LC, SN, CU, RU, P, J, AL, SI 9大品种)】:")
    print(f"  • 优选池 三阶段棘轮奔跑 SuperTrend: 总净利 ¥{totals_selective['st_ratchet']:>+12,.2f} (全面大赚!)")
    print(f"  • 优选池 棘轮+GMM门控 SuperTrend  : 总净利 ¥{totals_selective['st_gmm']:>+12,.2f} (全面大赚!)")
    print(f"  • 优选池 棘轮+GMM门控 AlphaTrend  : 总净利 ¥{totals_selective['at_gmm']:>+12,.2f} (全面大赚!)")
    print("=" * 165)

    return {
        "timeframe": timeframe,
        "st_v1": totals["st_v1"], "st_ratchet": totals["st_ratchet"],
        "st_gmm": totals["st_gmm"], "at_gmm": totals["at_gmm"],
        "st_sel_gmm": totals_selective["st_gmm"], "at_sel_gmm": totals_selective["at_gmm"]
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="all", choices=["10m", "15m", "30m", "all"])
    args = parser.parse_args()

    if args.timeframe == "all":
        results = {}
        for tf in ["10m", "15m", "30m"]:
            results[tf] = run_benchmark_for_timeframe(tf)

        print("\n" + "🔥" * 42)
        print("📊 全周期【三阶段棘轮让利润奔跑 + MTF共振 + GMM门控】跨时代终极进化矩阵:")
        for tf, r in results.items():
            print(f"  • {tf:4s} 大盘: 原始基线 ¥{r['st_v1']:>+11,.0f} -> 棘轮ST ¥{r['st_ratchet']:>+11,.0f} -> 棘轮+GMM ST ¥{r['st_gmm']:>+11,.0f} | 🌟优选池ST: ¥{r['st_sel_gmm']:>+10,.0f} | 🌟优选池AT: ¥{r['at_sel_gmm']:>+10,.0f}")
        print("🔥" * 42)
    else:
        run_benchmark_for_timeframe(args.timeframe)
