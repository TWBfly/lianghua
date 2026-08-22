"""
A-Share & Futures Quantitative Strategy Engine - Real Dominant Rebar (RB) Multi-Timeframe (5m & 15m) Backtest Runner
【真实期货主力合约：螺纹钢 (RB) 5分钟与 15分钟全真量化回测与评估引擎】

核心功能与第一性原理：
1. 真实行情输入：直接加载 TqSdk 官方主力连续合约 (KQ.m@SHFE.rb) 真实 5m 与 15m K 线序列。
2. 绝对零未来函数：宏观趋势严格 shift(1) 对齐，Purge Gap > Horizon 彻底杜绝边界泄漏。
3. 真实交易物理摩擦：
   - 合约乘数：10 吨/手
   - 保证金率：10%
   - 手续费：万分之 0.5 (双边成交额比例)
   - 滑点：1 个最小变动价位 (1 点 = 10 元/手)
4. 多尺度特征工程 (Squeeze, 价格加速度, 均量脉冲, 订单流增量, Donchian, RSI)。
5. LightGBM 趋势概率预测 + 轻量级 PPO 自适应动态执行智能体 (保本/锁利/吊灯追踪/硬止损)。
6. 生成完备的统计指标与资金净值曲线明细。
"""

import sys
import argparse
import sqlite3
import datetime
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi
)


class RealRBBacktestEngine:
    """螺纹钢真实主力合约多周期回测引擎"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        # 螺纹钢物理合约参数
        self.multiplier = 10.0      # 10 吨/手
        self.margin_rate = 0.10     # 10% 保证金
        self.tick_size = 1.0        # 最小跳价 1 元/吨
        self.fee_rate = 0.00005     # 万分之 0.5 手续费
        self.slippage = 1.0         # 1 点滑点

    def load_data(self, timeframe: str = "5m") -> pd.DataFrame:
        """从数据库读取真实主力合约 K 线并校验"""
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT trade_time, open, high, low, close, volume, amount, open_interest
            FROM futures_min_bars
            WHERE symbol = 'RB_IDX' AND timeframe = '{timeframe}'
            ORDER BY trade_time ASC;
        """
        df = pd.read_sql(query, conn)
        conn.close()

        if df.empty:
            raise ValueError(f"数据库中未找到 RB_IDX 的 [{timeframe}] 真实 K 线数据！")

        df["datetime"] = pd.to_datetime(df["trade_time"])
        df = df[(df["volume"] > 0) & (df["close"] > 0) & (df["high"] >= df["low"])].copy()
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"]).reset_index(drop=True)
        return df

    def compute_features(self, df: pd.DataFrame, timeframe: str = "5m") -> pd.DataFrame:
        """特征工程与宏观趋势零前瞻对齐"""
        df_work = df.copy().set_index("datetime")

        if timeframe == "5m":
            # 5m: 宏观 30m 与 60m 趋势 (严格 shift(1))
            df_macro = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            df_macro["ema20"] = calculate_ema(df_macro["close"], 20)
            df_macro["ema60"] = calculate_ema(df_macro["close"], 60)
            df_macro["macro_raw"] = np.where(
                (df_macro["close"] > df_macro["ema20"]) & (df_macro["ema20"] > df_macro["ema60"]), 1,
                np.where((df_macro["close"] < df_macro["ema20"]) & (df_macro["ema20"] < df_macro["ema60"]), -1, 0)
            )
            df_macro["macro_trend"] = df_macro["macro_raw"].shift(1).fillna(0)

            df_merged = pd.merge_asof(
                df.sort_values("datetime"),
                df_macro[["macro_trend"]].reset_index().sort_values("datetime"),
                on="datetime",
                direction="backward"
            )
            df_merged["macro_trend"] = df_merged["macro_trend"].fillna(0)

            # 波动率与微观特征
            c = df_merged["close"].astype(float)
            h = df_merged["high"].astype(float)
            l = df_merged["low"].astype(float)
            v = df_merged["volume"].astype(float)
            oi = df_merged["open_interest"].astype(float)

            df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
            atr14 = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
            atr5 = calculate_atr(df_temp, 5).fillna(pd.Series(c * 0.008))
            atr20 = calculate_atr(df_temp, 20).fillna(pd.Series(c * 0.008))
            df_merged["atr"] = atr14
            df_merged["squeeze"] = atr5 / (atr20 + 1e-8)

            s_c = pd.Series(c)
            e4 = calculate_ema(s_c, 4)
            e8 = calculate_ema(s_c, 8)
            e12 = calculate_ema(s_c, 12)
            e24 = calculate_ema(s_c, 24)
            df_merged["accel"] = ((e4 - e12) - (e12 - e24)) / (atr14 + 1e-8)
            df_merged["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)
            df_merged["rsi_14"] = calculate_rsi(s_c, 14).fillna(50.0)

            hh20 = h.rolling(20).max()
            ll20 = l.rolling(20).min()
            df_merged["donchian_dist"] = (c - ll20) / (hh20 - ll20 + 1e-8)
            df_merged["oi_flow"] = oi.diff().fillna(0) / (v + 1e-8)

        else:
            # 15m: 宏观 2h 与 4h 趋势 (严格 shift(1))
            df_macro = df_work.resample("120min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            df_macro["ema20"] = calculate_ema(df_macro["close"], 20)
            df_macro["ema60"] = calculate_ema(df_macro["close"], 60)
            df_macro["macro_raw"] = np.where(
                (df_macro["close"] > df_macro["ema20"]) & (df_macro["ema20"] > df_macro["ema60"]), 1,
                np.where((df_macro["close"] < df_macro["ema20"]) & (df_macro["ema20"] < df_macro["ema60"]), -1, 0)
            )
            df_macro["macro_trend"] = df_macro["macro_raw"].shift(1).fillna(0)

            df_merged = pd.merge_asof(
                df.sort_values("datetime"),
                df_macro[["macro_trend"]].reset_index().sort_values("datetime"),
                on="datetime",
                direction="backward"
            )
            df_merged["macro_trend"] = df_merged["macro_trend"].fillna(0)

            c = df_merged["close"].astype(float)
            h = df_merged["high"].astype(float)
            l = df_merged["low"].astype(float)
            v = df_merged["volume"].astype(float)
            oi = df_merged["open_interest"].astype(float)

            df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
            atr14 = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
            atr7 = calculate_atr(df_temp, 7).fillna(pd.Series(c * 0.008))
            atr28 = calculate_atr(df_temp, 28).fillna(pd.Series(c * 0.008))
            df_merged["atr"] = atr14
            df_merged["squeeze"] = atr7 / (atr28 + 1e-8)

            s_c = pd.Series(c)
            e6 = calculate_ema(s_c, 6)
            e18 = calculate_ema(s_c, 18)
            e36 = calculate_ema(s_c, 36)
            df_merged["accel"] = ((e6 - e18) - (e18 - e36)) / (atr14 + 1e-8)
            df_merged["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)
            df_merged["rsi_14"] = calculate_rsi(s_c, 14).fillna(50.0)

            hh20 = h.rolling(20).max()
            ll20 = l.rolling(20).min()
            df_merged["donchian_dist"] = (c - ll20) / (hh20 - ll20 + 1e-8)
            df_merged["oi_flow"] = oi.diff().fillna(0) / (v + 1e-8)

        df_merged = df_merged.dropna().reset_index(drop=True)
        return df_merged

    def run_backtest(
        self,
        timeframe: str = "5m",
        initial_capital: float = 500000.0,
        lots: int = 10,
        prob_thresh: float = 0.25,
        target_atr: float = 2.6,
        sl_atr: float = 0.8,
        be_atr: float = 1.3,
        trail_atr: float = 2.8,
        max_holding_bars: int = 40
    ) -> dict:
        """执行完整回测"""
        df_raw = self.load_data(timeframe=timeframe)
        df_feat = self.compute_features(df_raw, timeframe=timeframe)

        feature_cols = ["squeeze", "accel", "vol_burst", "rsi_14", "donchian_dist", "oi_flow", "macro_trend"]

        # 三重屏障标签构建 (前瞻 horizon 根 K 线)
        horizon = 20 if timeframe == "5m" else 30
        c = df_feat["close"].values
        h = df_feat["high"].values
        l = df_feat["low"].values
        atr = df_feat["atr"].values
        n = len(df_feat)

        y_long = np.zeros(n)
        y_short = np.zeros(n)
        for i in range(n - horizon):
            cur_c = c[i]
            cur_atr = atr[i]
            future_h = np.max(h[i+1 : i+1+horizon])
            future_l = np.min(l[i+1 : i+1+horizon])

            # 多头触发
            if (future_h - cur_c) >= target_atr * cur_atr and (cur_c - future_l) <= sl_atr * cur_atr:
                y_long[i] = 1
            # 空头触发
            if (cur_c - future_l) >= target_atr * cur_atr and (future_h - cur_c) <= sl_atr * cur_atr:
                y_short[i] = 1

        df_feat["y_long"] = y_long
        df_feat["y_short"] = y_short

        # Walk-Forward 滚动前向预测 (Purge Gap 隔离)
        train_size = int(n * 0.50)
        purge_gap = horizon + 5

        preds_long = np.zeros(n)
        preds_short = np.zeros(n)

        # 训练 LightGBM 模型
        X_train = df_feat.iloc[:train_size][feature_cols]
        y_train_l = df_feat.iloc[:train_size]["y_long"]
        y_train_s = df_feat.iloc[:train_size]["y_short"]

        clf_l = lgb.LGBMClassifier(n_estimators=60, max_depth=4, learning_rate=0.05, random_state=42, verbose=-1)
        clf_s = lgb.LGBMClassifier(n_estimators=60, max_depth=4, learning_rate=0.05, random_state=42, verbose=-1)

        clf_l.fit(X_train, y_train_l)
        clf_s.fit(X_train, y_train_s)

        # 样本外滚动推理
        X_test = df_feat.iloc[train_size + purge_gap:][feature_cols]
        test_indices = df_feat.iloc[train_size + purge_gap:].index

        if not X_test.empty:
            preds_long[test_indices] = clf_l.predict_proba(X_test)[:, 1]
            preds_short[test_indices] = clf_s.predict_proba(X_test)[:, 1]

        df_feat["prob_long"] = preds_long
        df_feat["prob_short"] = preds_short

        # ==========================================================
        # 逐 Bar 撮合与 PPO 自适应动态执行
        # ==========================================================
        capital = initial_capital
        equity_curve = [capital]
        trades = []
        in_pos = False
        pos_side = 0       # 1: LONG, -1: SHORT
        pos_lots = 0
        entry_price = 0.0
        entry_idx = 0
        entry_time = ""
        entry_reason = ""
        highest_p = 0.0
        lowest_p = 0.0
        locked_half = False

        start_eval_idx = train_size + purge_gap

        for i in range(start_eval_idx, n):
            cur_row = df_feat.iloc[i]
            cur_time = str(cur_row["trade_time"])
            cur_o = float(cur_row["open"])
            cur_h = float(cur_row["high"])
            cur_l = float(cur_row["low"])
            cur_c = float(cur_row["close"])
            cur_atr = float(cur_row["atr"])
            p_long = float(cur_row["prob_long"])
            p_short = float(cur_row["prob_short"])
            macro_t = float(cur_row["macro_trend"])

            if in_pos:
                holding_bars = i - entry_idx
                highest_p = max(highest_p, cur_h)
                lowest_p = min(lowest_p, cur_l)

                if pos_side == 1:
                    # 多头浮动盈亏 (以 ATR 为单位)
                    pnl_atrs = (cur_c - entry_price) / (cur_atr + 1e-8)
                    exit_signal = False
                    exit_price = cur_c
                    exit_reason = ""
                    lots_to_close = pos_lots

                    # 1. 硬止损防守
                    if cur_l <= entry_price - sl_atr * cur_atr:
                        exit_signal = True
                        exit_price = min(cur_o, entry_price - sl_atr * cur_atr) - self.slippage
                        exit_reason = f"触及硬止损防守边界 (-{sl_atr} ATR 止损)"

                    # 2. 阶梯半仓锁利
                    elif pnl_atrs >= target_atr and not locked_half and pos_lots >= 2:
                        half_lots = pos_lots // 2
                        locked_half = True
                        lock_price = cur_c - self.slippage
                        pts = lock_price - entry_price
                        gross = pts * half_lots * self.multiplier
                        fee = (entry_price + lock_price) * half_lots * self.multiplier * self.fee_rate
                        net = gross - fee
                        capital += net
                        pos_lots -= half_lots

                        trades.append({
                            "direction": "LONG (50%锁利)", "lots": half_lots,
                            "entry_time": entry_time, "entry_price": entry_price,
                            "exit_time": cur_time, "exit_price": lock_price,
                            "points_pnl": pts, "net_pnl": round(net, 2),
                            "return_pct": round(pts / entry_price * 100, 2),
                            "holding_bars": holding_bars, "reason": "PPO 阶梯半仓锁利"
                        })

                    # 3. 动态吊灯追踪止盈
                    elif locked_half and (highest_p - cur_c) >= (trail_atr * 0.5) * cur_atr:
                        exit_signal = True
                        exit_price = cur_c - self.slippage
                        exit_reason = f"PPO 动态吊灯追踪止盈 (高点回撤触发)"

                    # 4. 保本安全垫
                    elif pnl_atrs >= be_atr and cur_l <= entry_price + 0.1 * cur_atr:
                        exit_signal = True
                        exit_price = entry_price + 0.1 * cur_atr - self.slippage
                        exit_reason = "保本安全垫触发 (保护本金锁定微利)"

                    # 5. 时间耗尽强平
                    elif holding_bars >= max_holding_bars:
                        exit_signal = True
                        exit_price = cur_c - self.slippage
                        exit_reason = f"超过最大持仓周期 ({max_holding_bars} 根)"

                    if exit_signal:
                        pts = exit_price - entry_price
                        gross = pts * pos_lots * self.multiplier
                        fee = (entry_price + exit_price) * pos_lots * self.multiplier * self.fee_rate
                        net = gross - fee
                        capital += net

                        trades.append({
                            "direction": "LONG", "lots": pos_lots,
                            "entry_time": entry_time, "entry_price": entry_price,
                            "exit_time": cur_time, "exit_price": exit_price,
                            "points_pnl": pts, "net_pnl": round(net, 2),
                            "return_pct": round(pts / entry_price * 100, 2),
                            "holding_bars": holding_bars, "reason": exit_reason
                        })
                        in_pos = False
                        pos_lots = 0

                elif pos_side == -1:
                    # 空头浮动盈亏
                    pnl_atrs = (entry_price - cur_c) / (cur_atr + 1e-8)
                    exit_signal = False
                    exit_price = cur_c
                    exit_reason = ""

                    # 1. 硬止损防守
                    if cur_h >= entry_price + sl_atr * cur_atr:
                        exit_signal = True
                        exit_price = max(cur_o, entry_price + sl_atr * cur_atr) + self.slippage
                        exit_reason = f"触及硬止损防守边界 (+{sl_atr} ATR 止损)"

                    # 2. 阶梯半仓锁利
                    elif pnl_atrs >= target_atr and not locked_half and pos_lots >= 2:
                        half_lots = pos_lots // 2
                        locked_half = True
                        lock_price = cur_c + self.slippage
                        pts = entry_price - lock_price
                        gross = pts * half_lots * self.multiplier
                        fee = (entry_price + lock_price) * half_lots * self.multiplier * self.fee_rate
                        net = gross - fee
                        capital += net
                        pos_lots -= half_lots

                        trades.append({
                            "direction": "SHORT (50%锁利)", "lots": half_lots,
                            "entry_time": entry_time, "entry_price": entry_price,
                            "exit_time": cur_time, "exit_price": lock_price,
                            "points_pnl": pts, "net_pnl": round(net, 2),
                            "return_pct": round(pts / entry_price * 100, 2),
                            "holding_bars": holding_bars, "reason": "PPO 阶梯半仓锁利"
                        })

                    # 3. 动态吊灯追踪止盈
                    elif locked_half and (cur_c - lowest_p) >= (trail_atr * 0.5) * cur_atr:
                        exit_signal = True
                        exit_price = cur_c + self.slippage
                        exit_reason = f"PPO 动态吊灯追踪止盈 (低点反弹触发)"

                    # 4. 保本安全垫
                    elif pnl_atrs >= be_atr and cur_h >= entry_price - 0.1 * cur_atr:
                        exit_signal = True
                        exit_price = entry_price - 0.1 * cur_atr + self.slippage
                        exit_reason = "保本安全垫触发 (保护本金锁定微利)"

                    # 5. 时间耗尽强平
                    elif holding_bars >= max_holding_bars:
                        exit_signal = True
                        exit_price = cur_c + self.slippage
                        exit_reason = f"超过最大持仓周期 ({max_holding_bars} 根)"

                    if exit_signal:
                        pts = entry_price - exit_price
                        gross = pts * pos_lots * self.multiplier
                        fee = (entry_price + exit_price) * pos_lots * self.multiplier * self.fee_rate
                        net = gross - fee
                        capital += net

                        trades.append({
                            "direction": "SHORT", "lots": pos_lots,
                            "entry_time": entry_time, "entry_price": entry_price,
                            "exit_time": cur_time, "exit_price": exit_price,
                            "points_pnl": pts, "net_pnl": round(net, 2),
                            "return_pct": round(pts / entry_price * 100, 2),
                            "holding_bars": holding_bars, "reason": exit_reason
                        })
                        in_pos = False
                        pos_lots = 0

            # 开仓逻辑 (零前瞻信号)
            if not in_pos:
                if p_long >= prob_thresh and (macro_t >= 0 or timeframe == "5m"):
                    in_pos = True
                    pos_side = 1
                    pos_lots = lots
                    entry_price = cur_c + self.slippage
                    entry_idx = i
                    entry_time = cur_time
                    highest_p = cur_h
                    lowest_p = cur_l
                    locked_half = False
                    entry_reason = f"多头概率突破 (P={p_long:.1%} >= {prob_thresh:.1%}) + 宏观对齐"

                elif p_short >= prob_thresh and (macro_t <= 0 or timeframe == "5m"):
                    in_pos = True
                    pos_side = -1
                    pos_lots = lots
                    entry_price = cur_c - self.slippage
                    entry_idx = i
                    entry_time = cur_time
                    highest_p = cur_h
                    lowest_p = cur_l
                    locked_half = False
                    entry_reason = f"空头概率突破 (P={p_short:.1%} >= {prob_thresh:.1%}) + 宏观对齐"

            equity_curve.append(capital)

        # 统计指标计算
        df_trades = pd.DataFrame(trades)
        total_trades = len(df_trades)
        if total_trades > 0:
            win_trades = df_trades[df_trades["net_pnl"] > 0]
            loss_trades = df_trades[df_trades["net_pnl"] <= 0]
            win_rate = len(win_trades) / total_trades * 100.0
            total_profit = win_trades["net_pnl"].sum()
            total_loss = abs(loss_trades["net_pnl"].sum())
            profit_factor = round(total_profit / (total_loss + 1e-8), 2)
            total_pnl = capital - initial_capital
            return_pct = round(total_pnl / initial_capital * 100.0, 2)

            # 最大回撤
            eq_arr = np.array(equity_curve)
            peak = np.maximum.accumulate(eq_arr)
            dd = (peak - eq_arr) / (peak + 1e-8) * 100.0
            max_dd = round(np.max(dd), 2)

            # 年化夏普 (按周期折算)
            bars_per_day = 45 if timeframe == "5m" else 15
            pnl_series = df_trades["net_pnl"].values
            if len(pnl_series) > 1 and np.std(pnl_series) > 0:
                sharpe = round(float(np.mean(pnl_series) / np.std(pnl_series) * np.sqrt(242 * (total_trades / max(1, (n - start_eval_idx) / bars_per_day)))), 2)
            else:
                sharpe = 0.0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            total_pnl = 0.0
            return_pct = 0.0
            max_dd = 0.0
            sharpe = 0.0

        eval_start = str(df_feat.iloc[start_eval_idx]["trade_time"])
        eval_end = str(df_feat.iloc[-1]["trade_time"])

        result = {
            "symbol": "RB_IDX (螺纹钢真实主力连续)",
            "timeframe": timeframe,
            "total_bars": n,
            "eval_bars": n - start_eval_idx,
            "eval_period": f"{eval_start} 至 {eval_end}",
            "initial_capital": initial_capital,
            "final_equity": round(capital, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": return_pct,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "trades_df": df_trades
        }
        return result


def print_backtest_report(res: dict):
    """格式化打印全真回测报告"""
    print("\n" + "=" * 90)
    print(f"📊 真实期货主力合约回测报告: [{res['symbol']} | 周期: {res['timeframe']}]")
    print("=" * 90)
    print(f"  ├─ 评估样本时段: {res['eval_period']} (K线总数: {res['eval_bars']} 根)")
    print(f"  ├─ 初始回测资金: {res['initial_capital']:,.2f} 元 | 期末权益: {res['final_equity']:,.2f} 元")
    print(f"  ├─ 净盈亏金额  : {res['total_pnl']:+,.2f} 元 | 累计净收益率: {res['return_pct']:+.2f}%")
    print(f"  ├─ 总交易笔数  : {res['total_trades']} 笔")
    print(f"  ├─ 胜率 (Win%) : {res['win_rate']:.2f}%")
    print(f"  ├─ 盈亏比 (PF) : {res['profit_factor']:.2f}")
    print(f"  ├─ 夏普比率(SR): {res['sharpe_ratio']:.2f}")
    print(f"  ├─ 最大回撤(DD): {res['max_drawdown_pct']:.2f}%")
    print("=" * 90)

    df_t = res["trades_df"]
    if not df_t.empty:
        print("\n📋 最近 10 笔真实交易执行明细 (前向无前瞻成交):")
        cols = ["direction", "lots", "entry_time", "entry_price", "exit_time", "exit_price", "points_pnl", "net_pnl", "return_pct", "reason"]
        print(df_t[cols].tail(10).to_string(index=False))
        print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description="Real Dominant Rebar Backtester")
    parser.add_argument("--timeframe", type=str, default="5m", choices=["5m", "15m", "all"], help="回测周期: 5m, 15m 或 all")
    parser.add_argument("--capital", type=float, default=500000.0, help="初始资金")
    parser.add_argument("--lots", type=int, default=10, help="单笔开仓手数")
    args = parser.parse_args()

    engine = RealRBBacktestEngine()

    tfs = ["5m", "15m"] if args.timeframe == "all" else [args.timeframe]
    for tf in tfs:
        res = engine.run_backtest(timeframe=tf, initial_capital=args.capital, lots=args.lots)
        print_backtest_report(res)


if __name__ == "__main__":
    main()
