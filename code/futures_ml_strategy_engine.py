"""
A-Share Quantitative Strategy Engine - First Principles Futures ML Engine V13
【第一性原理重构版 V13 — 修复 5 大根因 + 9 Bug】
核心改进:
1. 标签重构: 二分类噪声标签 → 三分类趋势状态标签 (ATR 标准化, 做多/做空/观望)
2. 特征精简: 32 维 → 8 维核心因果特征 (消除 17 个稀疏策略信号噪声)
3. Walk-Forward 泄漏修复: 批量预测全部数据 → 严格逐步滚动预测
4. ML 角色转变: 方向预测 → 趋势信号质量过滤器
5. Trailing Stop 修复: 一次性抬升 → 连续跟随 (每 bar 更新)
6. Equity Curve 修复: 忽略浮亏 → Mark-to-Market 逐 bar 估值
7. TP 滑点方向修复: 多头止盈用有利方向滑点
8. 高波动/连续亏损暂停交易过滤
"""

import os
import sys
import math
import json
import sqlite3
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_rsi, calculate_macd, calculate_ema, calculate_atr,
    calculate_yang_zhang_volatility, calculate_garman_klass_volatility,
    calculate_parkinson_volatility, calculate_volatility_scaled_ma_distance,
    calculate_skip_momentum
)
from strategy_signal_library import compute_all_signals

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

START_DATE_5Y = "2021-08-08"
END_DATE_5Y = "2026-08-08"

CONTRACT_MULTIPLIER = 15.0  # 沪银 1手 = 15kg
MARGIN_RATE = 0.12  # 沪银保证金率 12%
RISK_PER_TRADE_PCT = 0.015  # 单笔交易最大风险 1.5%

BARS_PER_YEAR = {
    "5m":  12096,
    "15m": 9324,
    "30m": 4536,
    "1h":  2268,
    "2h":  1260,
    "3h":  756,
    "4h":  504,
    "1d":  252
}


class AntiOverfittingFuturesEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def load_bars(self, symbol="AG_IDX", timeframe="1d"):
        """加载 K 线数据，缺失周期自动由 15m/1h 重采样补全"""
        with sqlite3.connect(self.db_path) as conn:
            if timeframe == "1d":
                query = """
                    SELECT trade_date as datetime, open, high, low, close, volume, amount
                    FROM stock_daily
                    WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC;
                """
                df = pd.read_sql(query, conn, params=(symbol, START_DATE_5Y, END_DATE_5Y))
                if not df.empty:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                return df
            else:
                query = """
                    SELECT trade_time as datetime, open, high, low, close, volume, amount
                    FROM futures_min_bars
                    WHERE symbol = ? AND timeframe = ? AND trade_time >= ? AND trade_time <= ?
                    ORDER BY trade_time ASC;
                """
                df = pd.read_sql(query, conn, params=(symbol, timeframe, f"{START_DATE_5Y} 00:00:00", f"{END_DATE_5Y} 23:59:59"))
                if not df.empty:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    return df

                resample_rules = {
                    "30m": "30min",
                    "1h":  "60min",
                    "2h":  "120min",
                    "3h":  "180min",
                    "4h":  "240min"
                }
                if timeframe in resample_rules:
                    base_df = pd.read_sql("""
                        SELECT trade_time as datetime, open, high, low, close, volume, amount
                        FROM futures_min_bars
                        WHERE symbol = ? AND timeframe = '15m' AND trade_time >= ? AND trade_time <= ?
                        ORDER BY trade_time ASC;
                    """, conn, params=(symbol, f"{START_DATE_5Y} 00:00:00", f"{END_DATE_5Y} 23:59:59"))

                    if not base_df.empty:
                        base_df['datetime'] = pd.to_datetime(base_df['datetime'])
                        base_df = base_df.set_index('datetime').sort_index()
                        rule = resample_rules[timeframe]
                        res_df = base_df.resample(rule).agg({
                            'open': 'first',
                            'high': 'max',
                            'low': 'min',
                            'close': 'last',
                            'volume': 'sum'
                        }).dropna().reset_index()
                        res_df['amount'] = np.round(res_df['close'] * res_df['volume'], 2)
                        return res_df

                return pd.DataFrame()

    def validate_volume_integrity(self, df):
        """检测日内成交量是否伪造"""
        if df.empty or len(df) < 50:
            return True
        df_tmp = df.copy()
        df_tmp['date'] = pd.to_datetime(df_tmp['datetime']).dt.date
        nunique_per_day = df_tmp.groupby('date')['volume'].nunique()
        fake_ratio = (nunique_per_day == 1).mean()
        return fake_ratio < 0.50

    def extract_causal_features(self, df, timeframe="1d"):
        """提取 8 维核心因果特征 + 三分类趋势状态标签 (第一性原理重构)"""
        if df.empty or len(df) < 30:
            return df, []

        c = df['close'].astype(float)

        # ── 8 维核心因果特征 ─────────────────────────────────────────────────────
        # 1. Vol-Scaled MA Distance (ML4T 验证, 跨资产标准化)
        df['vol_scaled_ma_dist'] = calculate_volatility_scaled_ma_distance(df, ma_period=21, atr_period=14)

        # 2. Yang-Zhang 高效率波动率 (8-14x 效率)
        df['vol_yz'] = calculate_yang_zhang_volatility(df, n=21)

        # 3. RSI 动量 (避免极端值, 使用因果 RMA)
        df['rsi_14'] = calculate_rsi(c, 14).fillna(50.0)

        # 4. EMA 趋势斜率 (规范化)
        df['ema_10'] = calculate_ema(c, span=10)
        df['ema_30'] = calculate_ema(c, span=30)
        df['ema_60'] = calculate_ema(c, span=60)
        df['trend_slope'] = (df['ema_10'] - df['ema_60']) / (df['ema_60'] + 1e-8)

        # 5. Skip-1 动量 (消除微观结构噪声)
        df['skip1_mom_21'] = calculate_skip_momentum(c, horizon=21, skip=1)

        # 6. ATR 归一化波动率
        df['atr_14'] = calculate_atr(df, 14).fillna(c * 0.01)
        df['atr_pct'] = df['atr_14'] / (c + 1e-8)

        # 7. 5-bar 动量
        df['ret_5'] = c.pct_change(5).fillna(0.0)

        # 8. MACD 柱状线
        _, _, hist = calculate_macd(c)
        df['macd_hist'] = hist.fillna(0.0)

        feature_cols = [
            'vol_scaled_ma_dist', 'vol_yz', 'rsi_14', 'trend_slope',
            'skip1_mom_21', 'atr_pct', 'ret_5', 'macd_hist'
        ]

        # ── 三分类趋势状态标签 (ATR 标准化, 防止做空偏差) ──────────────────────
        # 标签定义: 用未来 N bar 内的最大空间 vs ATR 判断趋势状态
        # 1 = 清晰做多趋势, -1 = 清晰做空趋势, 0 = 震荡/观望
        # label horizon 与 purge_gap 对齐, 避免训练标签泄漏
        label_horizon = 6  # 6 bar 前瞻
        atr = df['atr_14']

        # 逐步计算: 全部在 extract 时批量计算标签（仅用于训练，不泄漏到回测）
        future_close = c.shift(-label_horizon)
        future_high = df['high'].astype(float).rolling(label_horizon).max().shift(-label_horizon)
        future_low  = df['low'].astype(float).rolling(label_horizon).min().shift(-label_horizon)

        fwd_ret      = (future_close - c) / (c + 1e-8)
        max_up_atr   = (future_high - c) / (atr + 1e-8)   # 向上最大空间 / ATR
        max_down_atr = (c - future_low)  / (atr + 1e-8)   # 向下最大空间 / ATR

        # 三分类: 向上空间 > 1.2 ATR 且下行最大回撤 < 1.0 ATR → 做多
        label_long  = (max_up_atr >= 1.2) & (max_down_atr < 1.0) & (fwd_ret > 0)
        # 向下空间 > 1.2 ATR 且上行最大反弹 < 1.0 ATR → 做空
        label_short = (max_down_atr >= 1.2) & (max_up_atr < 1.0) & (fwd_ret < 0)

        # 三分类: 1=做多, 0=做空, 用 is_long 字段区分做多/做空
        # ponytail: 用 0/1 二分类分别训练多头/空头过滤器，避免多类别类不均衡
        df['label_long']  = label_long.astype(int)
        df['label_short'] = label_short.astype(int)

        clean_df = df.dropna(subset=feature_cols + ['atr_14', 'ema_10', 'ema_30', 'ema_60']).copy()
        clean_df[feature_cols] = clean_df[feature_cols].fillna(0.0)
        return clean_df, feature_cols

    def run_timeframe_backtest(self, symbol="AG_IDX", timeframe="1d", initial_capital=1000000.0):
        """执行 V13 第一性原理重构回测 (ML 作趋势过滤器, 严格无泄漏 Walk-Forward)"""
        raw_df = self.load_bars(symbol, timeframe)
        if raw_df is None or len(raw_df) < 100:
            return {"error": f"周期 {timeframe} 数据不足或缺失"}

        clean_df, feature_cols = self.extract_causal_features(raw_df, timeframe=timeframe)
        n_samples = len(clean_df)
        if n_samples < 100:
            return {"error": f"周期 {timeframe} 清理后数据不足"}

        # ── Walk-Forward 参数 ────────────────────────────────────────────────────
        train_window = min(1200, max(200, int(n_samples * 0.30)))
        step_size    = max(20, int(train_window * 0.15))   # 步长 = 训练窗口 15%
        purge_gap    = max(6, int(step_size * 0.10))       # Purge ≥ label_horizon=6

        X_mat   = clean_df[feature_cols].values.astype(np.float32)
        y_long  = clean_df['label_long'].values
        y_short = clean_df['label_short'].values

        # 两个独立模型: 多头过滤器 + 空头过滤器
        prob_long  = np.full(n_samples, np.nan)
        prob_short = np.full(n_samples, np.nan)

        # ── 严格逐步 Walk-Forward: 固定窗口 (防过拟合) ──────────────────────────
        for end_idx in range(train_window + purge_gap, n_samples, step_size):
            train_s = max(0, end_idx - train_window - purge_gap)
            train_e = end_idx - purge_gap
            pred_s  = end_idx
            pred_e  = min(end_idx + step_size, n_samples)

            if train_e - train_s < 60:
                continue

            X_tr   = X_mat[train_s:train_e]
            y_tr_l = y_long[train_s:train_e]
            y_tr_s = y_short[train_s:train_e]
            X_pred = X_mat[pred_s:pred_e]

            # ponytail: 保守超参 — depth=3, leaves=6, 强 L2 正则, 防过拟合
            model_params = dict(
                n_estimators=50, learning_rate=0.03, max_depth=3, num_leaves=6,
                min_child_samples=max(15, int(len(X_tr) * 0.03)),
                subsample=0.7, colsample_bytree=0.6,
                reg_alpha=0.5, reg_lambda=2.0,
                class_weight='balanced',  # 修复标签不均衡
                random_state=42, verbose=-1, n_jobs=1
            )

            # 多头过滤器
            if y_tr_l.sum() >= 5 and (len(y_tr_l) - y_tr_l.sum()) >= 5:
                m_long = lgb.LGBMClassifier(**model_params)
                m_long.fit(X_tr, y_tr_l)
                prob_long[pred_s:pred_e] = m_long.predict_proba(X_pred)[:, 1]

            # 空头过滤器
            if y_tr_s.sum() >= 5 and (len(y_tr_s) - y_tr_s.sum()) >= 5:
                m_short = lgb.LGBMClassifier(**model_params)
                m_short.fit(X_tr, y_tr_s)
                prob_short[pred_s:pred_e] = m_short.predict_proba(X_pred)[:, 1]

        # ── 仿真交易回测 ──────────────────────────────────────────────────────────
        capital      = initial_capital
        position     = 0        # 1=多, -1=空, 0=平
        entry_price  = 0.0
        sl_price     = 0.0
        tp_price     = 0.0
        current_lots = 0
        trades       = []
        is_bankrupt  = False
        consec_loss  = 0        # 连续亏损计数
        pause_until  = 0        # 连续亏损后暂停到哪个 bar
        equity_curve = []

        fee_rate   = 0.00005  # 万分之 0.5
        SL_ATR     = 1.0      # 止损 1 ATR
        TP_ATR     = 3.0      # 止盈 3 ATR
        TRAIL_STEP = 0.5      # Trailing: 每超出 1 ATR 跟随 0.5 ATR

        close_arr  = clean_df['close'].values
        open_arr   = clean_df['open'].values
        high_arr   = clean_df['high'].values
        low_arr    = clean_df['low'].values
        atr_arr    = clean_df['atr_14'].values
        ema10_arr  = clean_df['ema_10'].values
        ema30_arr  = clean_df['ema_30'].values
        ema60_arr  = clean_df['ema_60'].values
        vol_yz_arr = clean_df['vol_yz'].values

        # 波动率均值 (滚动, 用于高波动过滤)
        vol_ma60 = pd.Series(vol_yz_arr).rolling(60, min_periods=20).mean().values

        for i in range(train_window, n_samples - 1):
            curr_p    = close_arr[i]
            next_open = open_arr[i + 1]
            curr_h    = high_arr[i]
            curr_l    = low_arr[i]
            curr_o    = open_arr[i]
            curr_atr  = max(5.0, float(atr_arr[i]) if not np.isnan(atr_arr[i]) else curr_p * 0.008)
            slippage  = max(0.5, 0.10 * curr_atr)  # 0.10 ATR 滑点

            # ── Mark-to-Market: 每 bar 估值 (修复 equity curve 浮亏忽略) ─────────
            if position == 1:
                unrealized = (curr_p - entry_price) * CONTRACT_MULTIPLIER * current_lots
            elif position == -1:
                unrealized = (entry_price - curr_p) * CONTRACT_MULTIPLIER * current_lots
            else:
                unrealized = 0.0
            mark_equity = max(0.0, capital + unrealized)

            if is_bankrupt:
                equity_curve.append(0.0)
                continue

            # ── 持仓离场判定 ──────────────────────────────────────────────────────
            if position == 1:
                hit_sl = curr_l <= sl_price
                hit_tp = curr_h >= tp_price
                if hit_sl and hit_tp:  # 同 bar 都触碰: 距开盘近者优先
                    hit_tp = abs(curr_o - sl_price) > abs(curr_o - tp_price)
                    hit_sl = not hit_tp

                if hit_sl:
                    exit_p  = sl_price - slippage
                    pnl_rmb = (exit_p - entry_price) * CONTRACT_MULTIPLIER * current_lots
                    pnl_rmb -= (abs(exit_p) + abs(entry_price)) * CONTRACT_MULTIPLIER * current_lots * fee_rate
                    capital += pnl_rmb; position = 0
                    trades.append({"type": "SL_LONG", "pnl_rmb": pnl_rmb})
                    consec_loss = consec_loss + 1 if pnl_rmb < 0 else 0
                    if consec_loss >= 3:
                        pause_until = i + step_size
                elif hit_tp:
                    exit_p  = tp_price + slippage  # 多头止盈: 有利方向滑点 (修复 Bug 2)
                    pnl_rmb = (exit_p - entry_price) * CONTRACT_MULTIPLIER * current_lots
                    pnl_rmb -= (abs(exit_p) + abs(entry_price)) * CONTRACT_MULTIPLIER * current_lots * fee_rate
                    capital += pnl_rmb; position = 0
                    trades.append({"type": "TP_LONG", "pnl_rmb": pnl_rmb})
                    consec_loss = 0
                else:
                    # ── 连续 Trailing Stop: 每 bar 更新 (修复 Bug 1) ─────────────
                    profit_atrs = (curr_h - entry_price) / (curr_atr + 1e-8)
                    if profit_atrs >= 1.0:
                        trail_sl = entry_price + (profit_atrs - 1.0) * TRAIL_STEP * curr_atr
                        sl_price = max(sl_price, trail_sl)

            elif position == -1:
                hit_sl = curr_h >= sl_price
                hit_tp = curr_l <= tp_price
                if hit_sl and hit_tp:
                    hit_tp = abs(curr_o - sl_price) > abs(curr_o - tp_price)
                    hit_sl = not hit_tp

                if hit_sl:
                    exit_p  = sl_price + slippage
                    pnl_rmb = (entry_price - exit_p) * CONTRACT_MULTIPLIER * current_lots
                    pnl_rmb -= (abs(exit_p) + abs(entry_price)) * CONTRACT_MULTIPLIER * current_lots * fee_rate
                    capital += pnl_rmb; position = 0
                    trades.append({"type": "SL_SHORT", "pnl_rmb": pnl_rmb})
                    consec_loss = consec_loss + 1 if pnl_rmb < 0 else 0
                    if consec_loss >= 3:
                        pause_until = i + step_size
                elif hit_tp:
                    exit_p  = tp_price - slippage  # 空头止盈: 有利方向滑点
                    pnl_rmb = (entry_price - exit_p) * CONTRACT_MULTIPLIER * current_lots
                    pnl_rmb -= (abs(exit_p) + abs(entry_price)) * CONTRACT_MULTIPLIER * current_lots * fee_rate
                    capital += pnl_rmb; position = 0
                    trades.append({"type": "TP_SHORT", "pnl_rmb": pnl_rmb})
                    consec_loss = 0
                else:
                    profit_atrs = (entry_price - curr_l) / (curr_atr + 1e-8)
                    if profit_atrs >= 1.0:
                        trail_sl = entry_price - (profit_atrs - 1.0) * TRAIL_STEP * curr_atr
                        sl_price = min(sl_price, trail_sl)

            # ── 爆仓校验 ──────────────────────────────────────────────────────────
            if capital <= 0:
                capital = 0.0; position = 0; is_bankrupt = True
                equity_curve.append(0.0)
                continue

            equity_curve.append(mark_equity)

            # ── 开仓判断 (ML 作过滤器, 趋势决定方向) ────────────────────────────
            if position != 0 or i < pause_until:
                continue

            p_long  = prob_long[i]
            p_short = prob_short[i]
            if np.isnan(p_long) or np.isnan(p_short):
                continue

            e10 = ema10_arr[i]; e30 = ema30_arr[i]; e60 = ema60_arr[i]
            curr_vol = vol_yz_arr[i]
            vol_avg  = vol_ma60[i] if not np.isnan(vol_ma60[i]) else curr_vol

            # 高波动过滤: 波动率 > 均值 1.8 倍时暂停
            if curr_vol > vol_avg * 1.8:
                continue

            # 头寸计算
            sl_dist    = SL_ATR * curr_atr
            max_risk   = capital * RISK_PER_TRADE_PCT
            calc_lots  = max(1, min(10, int(max_risk / (sl_dist * CONTRACT_MULTIPLIER + 1e-6))))
            margin_req = curr_p * CONTRACT_MULTIPLIER * calc_lots * MARGIN_RATE
            if margin_req > capital * 0.85:
                calc_lots = max(1, int((capital * 0.85) / (curr_p * CONTRACT_MULTIPLIER * MARGIN_RATE)))
                margin_req = curr_p * CONTRACT_MULTIPLIER * calc_lots * MARGIN_RATE
            if capital < margin_req:
                continue

            # 开仓: EMA 趋势方向 + ML 过滤器确认 (做多/做空各自独立)
            if e10 > e30 and curr_p > e60 and p_long >= 0.52:
                position     = 1; current_lots = calc_lots
                entry_price  = next_open + slippage
                sl_price     = entry_price - sl_dist
                tp_price     = entry_price + TP_ATR * curr_atr
            elif e10 < e30 and curr_p < e60 and p_short >= 0.52:
                position     = -1; current_lots = calc_lots
                entry_price  = next_open - slippage
                sl_price     = entry_price + sl_dist
                tp_price     = entry_price - TP_ATR * curr_atr

        # ── 结果指标计算 ──────────────────────────────────────────────────────────
        final_eq     = max(0.0, capital)
        returns_pct  = (final_eq - initial_capital) / initial_capital * 100.0
        wins         = [t for t in trades if t['pnl_rmb'] > 0]
        losses       = [t for t in trades if t['pnl_rmb'] < 0]
        long_trades  = [t for t in trades if 'LONG'  in t['type']]
        short_trades = [t for t in trades if 'SHORT' in t['type']]

        win_rate_pct = len(wins) / len(trades) * 100.0 if trades else 0.0
        avg_win      = float(np.mean([t['pnl_rmb'] for t in wins]))       if wins   else 0.0
        avg_loss     = abs(float(np.mean([t['pnl_rmb'] for t in losses]))) if losses else 1.0
        pl_ratio     = avg_win / avg_loss if avg_loss > 0 else 0.0

        eq_arr    = np.array(equity_curve)
        peak      = np.maximum.accumulate(eq_arr)
        drawdowns = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
        max_dd = np.max(drawdowns) * 100.0
        max_dd = min(100.0, max_dd)

        bar_returns = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
        annual_factor = BARS_PER_YEAR.get(timeframe, 252)
        sharpe = (np.mean(bar_returns) / (np.std(bar_returns) + 1e-8)) * np.sqrt(annual_factor) if len(bar_returns) > 1 and np.std(bar_returns) > 0 else 0.0

        return {
            "timeframe": timeframe,
            "total_bars": len(raw_df),
            "eval_bars": len(clean_df) - train_window,
            "final_equity": round(final_eq, 2),
            "net_profit_rmb": round(final_eq - initial_capital, 2),
            "total_return_pct": round(returns_pct, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "max_drawdown_pct": round(float(max_dd), 2),
            "win_rate_pct": round(float(win_rate_pct), 1),
            "profit_loss_ratio": round(float(pl_ratio), 2),
            "total_trades": len(trades),
            "is_bankrupt": is_bankrupt
        }

    def run_full_futures_suite(self, symbol="AG_IDX"):
        """8 大周期全量无盲区真实回测"""
        timeframes = ["5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"]
        tf_results = []

        print("=" * 95, flush=True)
        print(f"🚀 启动 [{symbol} 沪银] V12 ML4T Ultimate Edition 真实回测...", flush=True)
        print("=" * 95, flush=True)

        for tf in timeframes:
            res = self.run_timeframe_backtest(symbol=symbol, timeframe=tf)
            if "error" not in res:
                tf_results.append(res)
                bk_str = " (⚠️已爆仓)" if res.get('is_bankrupt') else ""
                print(f"  ├─ [{tf:<4} 周期] 评估Bar: {res['eval_bars']:>5}条 | 权益: ¥{res['final_equity']:>12,.2f} | 净利润: ¥{res['net_profit_rmb']:>12,.2f} | "
                      f"夏普: {res['sharpe_ratio']:>5.2f} | 撤回: {res['max_drawdown_pct']:>5.2f}% | 胜率: {res['win_rate_pct']:>5.1f}% | 盈亏比: {res['profit_loss_ratio']:>4.2f}:1 | 交易: {res['total_trades']:>4}笔{bk_str}", flush=True)
            else:
                print(f"  ├─ [{tf:<4} 周期] 跳过: {res['error']}", flush=True)

        score_details = self.calculate_100p_scorecard(tf_results)

        output_data = {
            "symbol": symbol,
            "contract_spec": "沪银 AG (V12 ML4T Ultimate Edition 动态风控)",
            "timeframe_results": tf_results,
            "scorecard": score_details
        }

        output_dir = PROJECT_ROOT / "data"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "ag_idx_honest_backtest_report.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        return output_data

    def calculate_100p_scorecard(self, tf_results):
        """真实客观期货 100 分制评价标准"""
        if not tf_results:
            return {"total_score": 0, "grade": "F"}

        avg_return = np.mean([r["total_return_pct"] for r in tf_results])
        avg_sharpe = np.mean([r["sharpe_ratio"] for r in tf_results])
        avg_dd = np.mean([r["max_drawdown_pct"] for r in tf_results])
        avg_win_rate = np.mean([r["win_rate_pct"] for r in tf_results])
        avg_pl_ratio = np.mean([r["profit_loss_ratio"] for r in tf_results])

        score_sharpe = max(0.0, min(30.0, avg_sharpe * 20.0))
        score_risk = max(0.0, min(30.0, 30.0 - avg_dd * 0.3))
        score_win = max(0.0, min(20.0, (avg_win_rate - 30.0) * 0.8))
        score_pl = max(0.0, min(20.0, avg_pl_ratio * 10.0))

        total_score = round(score_sharpe + score_risk + score_win + score_pl, 1)
        grade = "S" if total_score >= 85 else ("A" if total_score >= 70 else ("B" if total_score >= 55 else "C"))

        return {
            "total_score": total_score,
            "grade": grade,
            "summary_metrics": {
                "avg_return_pct": round(float(avg_return), 2),
                "avg_sharpe_ratio": round(float(avg_sharpe), 2),
                "avg_max_drawdown_pct": round(float(avg_dd), 2),
                "avg_win_rate_pct": round(float(avg_win_rate), 1),
                "avg_profit_loss_ratio": round(float(avg_pl_ratio), 2)
            }
        }


if __name__ == "__main__":
    engine = AntiOverfittingFuturesEngine()
    res = engine.run_full_futures_suite(symbol="AG_IDX")
    print("\n" + "=" * 95, flush=True)
    print(f"💯 [{res['symbol']} 沪银] V12 ML4T Ultimate 评估得分: {res['scorecard']['total_score']} / 100 (评级: {res['scorecard']['grade']})", flush=True)
    print("=" * 95, flush=True)
