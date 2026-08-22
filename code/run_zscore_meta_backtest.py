"""
run_zscore_meta_backtest.py — 极值 Z-Score 均值回归 + ML Meta-Labeling 25 大商品期货全量对冲回测研究系统

核心对比实验：
1. Baseline [纯规则引擎]: Z-Score(20) <= -2.2 & RSI(2) <= 12 & 阳线反包，止盈至 SMA(5)，止损 -1.2 ATR，超时 5 根 Bar 强平。
2. Meta-Labeling [ML 元标签升维]: 使用 Walk-Forward LightGBM 预测一阶信号成功率 P(y=1)，过滤致命单边破位假反弹。
3. 统计全指标: 胜率(Win Rate)、盈亏比(PL Ratio)、交易次数、逐日盯市真实日度夏普(Daily Sharpe)、真实浮动最大回撤(MTM Max Drawdown)、净利润。
"""

import sys
import sqlite3
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import DecoupledSymbolStrategyRunner, SYMBOL_CONFIGS
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi
from data_contract import validate_futures_universe

DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"


def compute_zscore_features_and_meta_labels(df: pd.DataFrame, multiplier: float = 10.0, sl_atr_mult: float = 1.2, max_bars: int = 5, macro_freq: str = "60min") -> pd.DataFrame:
    """计算 Z-Score、RSI(2)、微观拒绝形态、持仓量筹码流，并使用三重屏障生成 Meta-Labeling 标签"""
    df_res = df.copy()
    c = df_res["close"].astype(float)
    o = df_res["open"].astype(float)
    h = df_res["high"].astype(float)
    l = df_res["low"].astype(float)
    v = df_res["volume"].astype(float)

    # 1. 基础指标与偏离度
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std() + 1e-8
    zscore = (c - sma_20) / std_20
    df_res["zscore"] = zscore
    df_res["sma_20"] = sma_20

    # RSI(2)
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(2).mean()
    avg_loss = loss.rolling(2).mean() + 1e-8
    df_res["rsi_2"] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    # SMA(5) 首发止盈目标线
    sma_5 = c.rolling(5).mean()
    df_res["sma_5"] = sma_5

    # ATR(14) 与波动挤压特征
    df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    atr_14 = calculate_atr(df_temp, 14).fillna(c * 0.01)
    atr_7 = calculate_atr(df_temp, 7).fillna(c * 0.01)
    atr_28 = calculate_atr(df_temp, 28).fillna(c * 0.01)
    df_res["atr_14"] = atr_14
    df_res["squeeze"] = atr_7 / (atr_28 + 1e-8)

    # 物理二阶加速度
    e10 = calculate_ema(c, 10)
    e30 = calculate_ema(c, 30)
    e60 = calculate_ema(c, 60)
    df_res["accel_norm"] = ((e10 - e30) - (e30 - e60)) / (atr_14 + 1e-8)

    # 量比与 RSI(14)
    vol_ma20 = v.rolling(20).mean().fillna(1.0)
    df_res["vol_ratio"] = v / (vol_ma20 + 1e-8)
    df_res["vol_climax"] = np.where(v >= vol_ma20 * 1.5, 1.0, 0.0)
    df_res["rsi_14"] = calculate_rsi(c, 14).fillna(50.0)

    # 微观长影线拒斥比率 (Pin Bar Absorption)
    body = np.abs(c - o)
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)
    df_res["shadow_rejection_long"] = lower_shadow / (body + 1e-8)
    df_res["shadow_rejection_short"] = upper_shadow / (body + 1e-8)

    # 唐奇安通道偏离度
    don_hi = h.rolling(20).max()
    don_lo = l.rolling(20).min()
    df_res["donchian_dist"] = (c - (don_hi + don_lo) / 2.0) / (atr_14 + 1e-8)

    # 期货持仓量增减与量价背离 (OI 筹码特征)
    oi = df_res.get("open_interest", pd.Series(np.zeros(len(df_res)))).fillna(0).astype(float)
    oi_diff = oi.diff().fillna(0)
    df_res["oi_diff"] = oi_diff
    df_res["oi_flow"] = oi_diff / (vol_ma20 + 1e-8)
    # 空平/多平获利减仓特征 (胜率最高形态)
    df_res["oi_unwinding"] = np.where(oi_diff < 0, 1.0, 0.0)

    # 宏观跨周期顺势对齐 (shift 1 零前瞻)
    if "datetime" not in df_res.columns and "trade_time" in df_res.columns:
        df_res["datetime"] = pd.to_datetime(df_res["trade_time"])
    else:
        df_res["datetime"] = pd.to_datetime(df_res["datetime"])
    df_res = df_res.sort_values("datetime").reset_index(drop=True)
    df_macro = df_res.set_index("datetime").resample(macro_freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    c_macro = df_macro["close"]
    trend_macro_series = np.where(c_macro > calculate_ema(c_macro, 20), 1, np.where(c_macro < calculate_ema(c_macro, 20), -1, 0))
    df_macro["trend_1h"] = pd.Series(trend_macro_series, index=df_macro.index).shift(1)
    df_res = pd.merge_asof(df_res, df_macro[["trend_1h"]], on="datetime", direction="backward")
    df_res["trend_1h"] = df_res["trend_1h"].fillna(0)

    # 2. 一阶主模型触发条件 (结合 Pin Bar 拒斥与持仓量背离)
    bullish_reversal = (c > o) & (c > c.shift(1)) & (lower_shadow >= body * 0.5)
    bearish_reversal = (c < o) & (c < c.shift(1)) & (upper_shadow >= body * 0.5)

    oi_ok_long = oi_diff <= vol_ma20 * 0.5
    oi_ok_short = oi_diff <= vol_ma20 * 0.5

    long_trigger = (df_res["zscore"] <= -2.0) & (df_res["rsi_2"] <= 15.0) & bullish_reversal & (c < sma_5) & oi_ok_long
    short_trigger = (df_res["zscore"] >= 2.0) & (df_res["rsi_2"] >= 85.0) & bearish_reversal & (c > sma_5) & oi_ok_short

    df_res["primary_signal"] = 0
    df_res.loc[long_trigger, "primary_signal"] = 1
    df_res.loc[short_trigger, "primary_signal"] = -1

    # 3. 三重屏障 Meta 标注
    meta_labels = np.full(len(df_res), np.nan)
    close_arr = c.values
    high_arr = h.values
    low_arr = l.values
    atr_arr = atr_14.values
    sma5_arr = sma_5.values
    sig_arr = df_res["primary_signal"].values

    for i in range(len(df_res) - max_bars):
        sig = sig_arr[i]
        if sig == 0:
            continue

        p0 = close_arr[i]
        atr = max(2.0, float(atr_arr[i]))
        sl = p0 - sl_atr_mult * atr if sig == 1 else p0 + sl_atr_mult * atr

        hit_label = 0
        for b in range(1, max_bars + 1):
            curr_bar_h = high_arr[i + b]
            curr_bar_l = low_arr[i + b]
            curr_sma5 = sma5_arr[i + b]

            if sig == 1:
                if curr_bar_l <= sl:
                    hit_label = 0
                    break
                if curr_bar_h >= curr_sma5:
                    hit_label = 1
                    break
            elif sig == -1:
                if curr_bar_h >= sl:
                    hit_label = 0
                    break
                if curr_bar_l <= curr_sma5:
                    hit_label = 1
                    break

        meta_labels[i] = hit_label

    df_res["meta_label"] = meta_labels
    return df_res


def run_walk_forward_meta_classifier(df_feat: pd.DataFrame, feature_cols: list, train_window: int = 3000, step_size: int = 500, purge_gap: int = 5) -> np.ndarray:
    """Walk-Forward 交叉验证训练 Meta-Labeling 二元分类器 (支持稀疏信号与自适应先验)"""
    n_samples = len(df_feat)
    prob_meta = np.full(n_samples, np.nan)

    valid_idx = np.where(~np.isnan(df_feat["meta_label"].values))[0]
    if len(valid_idx) < 10:
        prob_meta[valid_idx] = 0.50
        return prob_meta

    X_all = df_feat[feature_cols].values.astype(np.float32)
    y_all = df_feat["meta_label"].values

    current_idx = train_window
    while current_idx < n_samples:
        train_end = current_idx
        train_start = 0  # 扩展窗口以保证充分的稀疏样本量

        train_mask = (valid_idx >= train_start) & (valid_idx < train_end)
        train_sample_idx = valid_idx[train_mask]

        if len(train_sample_idx) >= 8 and len(np.unique(y_all[train_sample_idx])) > 1:
            X_train = X_all[train_sample_idx]
            y_train = y_all[train_sample_idx].astype(int)

            clf = lgb.LGBMClassifier(
                n_estimators=30, learning_rate=0.03, max_depth=3, num_leaves=5,
                min_child_samples=3, class_weight="balanced", random_state=42, verbose=-1, n_jobs=1
            )
            clf.fit(X_train, y_train)

            test_start = min(n_samples, current_idx + purge_gap)
            test_end = min(n_samples, test_start + step_size)

            test_mask = (valid_idx >= test_start) & (valid_idx < test_end)
            test_sample_idx = valid_idx[test_mask]

            if len(test_sample_idx) > 0:
                prob_meta[test_sample_idx] = clf.predict_proba(X_all[test_sample_idx])[:, 1]

        current_idx += step_size

    # 对未被测试集覆盖的样本填充先验基准
    prob_meta[np.isnan(prob_meta) & ~np.isnan(df_feat["meta_label"].values)] = 0.50
    return prob_meta


def simulate_mean_reversion_execution(
    df_sim: pd.DataFrame,
    cfg: dict,
    symbol: str,
    use_meta_filter: bool = True,
    meta_prob_thresh: float = 0.52,
    initial_capital: float = 500000.0,
    sl_atr_mult: float = 1.2,
    max_holding_bars: int = 5
) -> dict:
    """真实逐日盯市 MTM 全真撮合仿真引擎 (V2 极速回归 + 动态保本与 Meta 动态加权)"""
    multiplier = cfg["multiplier"]
    fee_rate = 0.00005  # 万分之0.5

    close_arr = df_sim["close"].values
    open_arr = df_sim["open"].values
    high_arr = df_sim["high"].values
    low_arr = df_sim["low"].values
    sma5_arr = df_sim["sma_5"].values
    atr_arr = df_sim["atr_14"].values
    sig_arr = df_sim["primary_signal"].values
    prob_arr = df_sim["meta_prob"].values if "meta_prob" in df_sim.columns else np.full(len(df_sim), 1.0)
    dt_arr = df_sim["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S").values

    capital = initial_capital
    pos = 0  # 1=多, -1=空
    entry_p = 0.0
    sl_p = 0.0
    lots = 0
    holding_bars = 0
    entry_dt = ""

    trades = []
    eq_curve = []
    datetime_list = []

    for i in range(2500, len(df_sim) - 1):
        curr_p = close_arr[i]
        curr_h = high_arr[i]
        curr_l = low_arr[i]
        curr_dt = dt_arr[i]
        curr_atr = max(2.0, float(atr_arr[i]))
        next_o = open_arr[i + 1]
        slippage = 0.03 * curr_atr

        # 逐 Bar 盯市 MTM
        unrealized = (curr_p - entry_p) * multiplier * lots if pos == 1 else ((entry_p - curr_p) * multiplier * lots if pos == -1 else 0.0)
        eq_curve.append(max(0.0, capital + unrealized))
        datetime_list.append(curr_dt)

        # 1. 持仓出场逻辑 (SMA5 快速止盈 vs 动态保本 vs 硬止损 vs 超时)
        if pos != 0:
            holding_bars += 1
            exit_hit = False
            exit_p = 0.0
            exit_desc = ""

            if pos == 1:
                target_sma5 = sma5_arr[i]
                # (1) 触及 SMA(5) 极速完全止盈 (均值回归最佳半衰期锁定)
                if curr_h >= target_sma5:
                    exit_p = target_sma5 - slippage
                    exit_desc = f"回归 SMA(5) 极速止盈 ({target_sma5:.2f})"
                    exit_hit = True
                # (2) 触及硬止损 / 动态保本止损
                elif curr_l <= sl_p:
                    exit_p = min(open_arr[i], sl_p) - slippage
                    exit_desc = f"触发止损防守边界 ({sl_p:.2f})"
                    exit_hit = True
                # (3) 超时强平
                elif holding_bars >= max_holding_bars:
                    exit_p = curr_p - slippage
                    exit_desc = f"达到最大持仓上限 {max_holding_bars} Bar 均值清仓"
                    exit_hit = True

                if exit_hit:
                    pnl = (exit_p - entry_p) * multiplier * lots - (exit_p + entry_p) * multiplier * lots * fee_rate
                    capital += pnl
                    trades.append({
                        "symbol": symbol, "side": "LONG", "lots": lots, "entry_dt": entry_dt, "entry_p": entry_p,
                        "exit_dt": curr_dt, "exit_p": exit_p, "pnl": pnl, "ret_pct": (exit_p - entry_p) / entry_p * 100,
                        "bars": holding_bars, "reason": exit_desc
                    })
                    pos = 0
                else:
                    # 动态保本保护: 若已有 >0.4 ATR 浮盈，则将止损提升至保本线
                    if curr_h >= entry_p + 0.4 * curr_atr:
                        sl_p = max(sl_p, entry_p + 0.05 * curr_atr)

            elif pos == -1:
                target_sma5 = sma5_arr[i]
                if curr_l <= target_sma5:
                    exit_p = target_sma5 + slippage
                    exit_desc = f"回归 SMA(5) 极速止盈 ({target_sma5:.2f})"
                    exit_hit = True
                elif curr_h >= sl_p:
                    exit_p = max(open_arr[i], sl_p) + slippage
                    exit_desc = f"触发止损防守边界 ({sl_p:.2f})"
                    exit_hit = True
                elif holding_bars >= max_holding_bars:
                    exit_p = curr_p + slippage
                    exit_desc = f"达到最大持仓上限 {max_holding_bars} Bar 均值清仓"
                    exit_hit = True

                if exit_hit:
                    pnl = (entry_p - exit_p) * multiplier * lots - (exit_p + entry_p) * multiplier * lots * fee_rate
                    capital += pnl
                    trades.append({
                        "symbol": symbol, "side": "SHORT", "lots": lots, "entry_dt": entry_dt, "entry_p": entry_p,
                        "exit_dt": curr_dt, "exit_p": exit_p, "pnl": pnl, "ret_pct": (entry_p - exit_p) / entry_p * 100,
                        "bars": holding_bars, "reason": exit_desc
                    })
                    pos = 0
                else:
                    # 空头动态保本保护
                    if curr_l <= entry_p - 0.4 * curr_atr:
                        sl_p = min(sl_p, entry_p - 0.05 * curr_atr)

        # 2. 开仓信号
        if pos == 0:
            sig = sig_arr[i]
            prob = prob_arr[i]

            if sig != 0:
                # Meta-Labeling 过滤判定
                if use_meta_filter and (np.isnan(prob) or prob < meta_prob_thresh):
                    continue  # 坚决过滤劣质假反弹信号

                sl_dist = sl_atr_mult * curr_atr
                base_lots = max(1, min(cfg.get("max_lots", 5), int((capital * 0.01) / (sl_dist * multiplier + 1e-6))))
                # Lopez de Prado 连续置信度仓位缩放 (Bet Sizing)
                if use_meta_filter and not np.isnan(prob):
                    bet_scale = max(1.0, min(1.8, 1.0 + (prob - 0.5) * 3.0))
                    calc_lots = max(1, int(base_lots * bet_scale))
                else:
                    calc_lots = base_lots

                if sig == 1:
                    pos = 1
                    total_lots = calc_lots
                    rem_lots = calc_lots
                    entry_p = next_o + slippage
                    entry_dt = curr_dt
                    sl_p = entry_p - sl_dist
                    holding_bars = 0

                elif sig == -1:
                    pos = -1
                    lots = calc_lots
                    entry_p = next_o - slippage
                    entry_dt = curr_dt
                    sl_p = entry_p + sl_dist
                    holding_bars = 0

    # 统计核心指标
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total_trades = len(trades)
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

    avg_win = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
    avg_loss = abs(float(np.mean([t["pnl"] for t in losses]))) if losses else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    net_profit = capital - initial_capital
    tot_return = net_profit / initial_capital * 100.0

    eq_arr = np.array(eq_curve) if len(eq_curve) > 0 else np.array([initial_capital])
    peak = np.maximum.accumulate(eq_arr)
    drawdown = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(drawdown) * 100.0) if len(drawdown) > 0 else 0.0

    # 真实日度 MTM 夏普
    df_eq = pd.DataFrame({"datetime": pd.to_datetime(datetime_list), "equity": eq_curve})
    df_daily = df_eq.set_index("datetime").resample("1D").last().dropna()
    daily_ret = df_daily["equity"].pct_change().dropna()
    daily_sr = (daily_ret.mean() / (daily_ret.std() + 1e-8)) * np.sqrt(252) if len(daily_ret) > 1 and daily_ret.std() > 0 else 0.0

    return {
        "symbol": symbol,
        "name": cfg["name"],
        "use_meta": use_meta_filter,
        "total_trades": total_trades,
        "win_rate_pct": win_rate,
        "profit_loss_ratio": pl_ratio,
        "net_profit_rmb": net_profit,
        "total_return_pct": tot_return,
        "max_drawdown_pct": max_dd,
        "daily_sharpe": daily_sr,
        "avg_bars": np.mean([t["bars"] for t in trades]) if trades else 0.0,
        "trades": trades
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="极值 Z-Score 均值回归 + ML Meta-Labeling 多周期回测引擎")
    parser.add_argument("--timeframe", type=str, default="10m", choices=["1m", "5m", "10m", "15m", "30m"], help="回测周期 (1m, 5m, 10m, 15m, 30m)")
    parser.add_argument("--meta-thresh", type=float, default=0.52, help="Meta-Labeling 准入概率阈值")
    args = parser.parse_args()

    tf = args.timeframe
    macro_freq = "120min" if tf == "30m" else ("60min" if tf in ["10m", "15m"] else ("30min" if tf == "5m" else "15min"))

    print("=" * 110)
    print(f"🔬 极值 Z-Score 均值回归 + ML Meta-Labeling 25 大主力期货全量回测对决 【周期: {tf} | 宏观对齐: {macro_freq}】")
    print("=" * 110)

    conn = sqlite3.connect(DB_PATH)
    symbols = [
        "AU_IDX", "AG_IDX", "SA_IDX", "I_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "HC_IDX", "J_IDX", "JM_IDX",
        "AL_IDX", "ZN_IDX", "SN_IDX", "RU_IDX", "M_IDX", "P_IDX", "LC_IDX", "MA_IDX", "TA_IDX", "FG_IDX",
        "SR_IDX", "CF_IDX", "C_IDX", "Y_IDX", "SI_IDX"
    ]

    # 1. 契约安全校验
    validate_futures_universe(conn, symbols, timeframe=tf)
    conn.close()

    feature_cols = [
        "zscore", "rsi_2", "squeeze", "accel_norm", "vol_ratio", "vol_climax",
        "rsi_14", "shadow_rejection_long", "shadow_rejection_short",
        "donchian_dist", "oi_flow", "oi_unwinding", "trend_1h"
    ]

    
    # 动态加载对应周期数据
    def load_tf_data(sym: str, timeframe: str) -> pd.DataFrame:
        with sqlite3.connect(DB_PATH) as c:
            df = pd.read_sql_query(
                "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
                c, params=(sym, timeframe)
            )
            df["datetime"] = pd.to_datetime(df["trade_time"])
            return df

    results_baseline = []
    results_meta = []

    for sym in symbols:
        cfg = SYMBOL_CONFIGS[sym]
        df_raw = load_tf_data(sym, tf)
        df_feat = compute_zscore_features_and_meta_labels(df_raw, multiplier=cfg["multiplier"], macro_freq=macro_freq)


        # 训练 Meta 分类器
        prob_meta = run_walk_forward_meta_classifier(df_feat, feature_cols, train_window=3000, step_size=500, purge_gap=5)
        df_feat["meta_prob"] = prob_meta

        # 回测 A: 纯规则 Baseline
        res_a = simulate_mean_reversion_execution(df_feat, cfg, sym, use_meta_filter=False)
        results_baseline.append(res_a)

        # 回测 B: ML Meta-Labeling 过滤版
        res_b = simulate_mean_reversion_execution(df_feat, cfg, sym, use_meta_filter=True, meta_prob_thresh=args.meta_thresh)
        results_meta.append(res_b)

        print(
            f"[{sym:<8} {cfg['name']:<4}] | "
            f"纯规则: 交易{res_a['total_trades']:>3}笔, 胜率{res_a['win_rate_pct']:>5.1f}%, 盈亏比{res_a['profit_loss_ratio']:>4.2f}, 回撤{res_a['max_drawdown_pct']:>4.2f}%, 净利 ¥{res_a['net_profit_rmb']:>+9.2f} | "
            f"Meta过滤: 交易{res_b['total_trades']:>3}笔, 胜率{res_b['win_rate_pct']:>5.1f}%, 盈亏比{res_b['profit_loss_ratio']:>4.2f}, 回撤{res_b['max_drawdown_pct']:>4.2f}%, 净利 ¥{res_b['net_profit_rmb']:>+9.2f}"
        )

    # 汇总全局矩阵
    df_res_a = pd.DataFrame(results_baseline)
    df_res_b = pd.DataFrame(results_meta)

    print("\n" + "=" * 110)
    print(f"📊 25 大品种整体对照大盘汇总 【周期: {tf}】 (Baseline vs ML Meta-Labeling)")
    print("=" * 110)
    print(f"【纯规则 Baseline】: 平均胜率 {df_res_a['win_rate_pct'].mean():.1f}% | 平均盈亏比 {df_res_a['profit_loss_ratio'].mean():.2f} | 总交易次数 {df_res_a['total_trades'].sum()} | 组合总净利 ¥{df_res_a['net_profit_rmb'].sum():,.2f}")
    print(f"【Meta-Labeling  】: 平均胜率 {df_res_b['win_rate_pct'].mean():.1f}% | 平均盈亏比 {df_res_b['profit_loss_ratio'].mean():.2f} | 总交易次数 {df_res_b['total_trades'].sum()} | 组合总净利 ¥{df_res_b['net_profit_rmb'].sum():,.2f}")
    print("=" * 110)



if __name__ == "__main__":
    main()
