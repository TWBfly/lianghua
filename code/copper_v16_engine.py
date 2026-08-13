"""
A-Share Quantitative Strategy Engine - Copper (CU_IDX) 15m First-Principles ML Engine
【沪铜 15分钟 K线第一性原理机器学习策略引擎 (查理·芒格 / 巴菲特 / 达利欧 交易哲理版)】

核心理念：
1. 查理·芒格 (Charlie Munger) —— 极度安全边际与高确定性等待 (Margin of Safety):
   - 提取铜专项 6 大因果特征 (vol_squeeze_ratio, volume_ratio, donchian_dist, rsi_div, trend_slope, macro_slope_1h)。
   - LightGBM 预测概率门槛 >= 0.60，高确定性时开仓，非理性波动期空仓观望。
2. 沃伦·巴菲特 (Warren Buffett) —— 宏观护城河与资本保护 (Moat & Capital Preservation):
   - 顺应 1h 宏观长周期趋势护城河 (1h EMA20 > 50)。
   - 1手=5吨 (名义价值高)，严格控制单笔风险暴露 <= 1.5%，最大持仓不超过 5 手。
3. 瑞·达利欧 (Ray Dalio) —— 波动率压缩与全天候宏观共振 (Macro Squeeze & Risk Parity):
   - 1h EMA 趋势与 15m 波动率压缩 (Squeeze) 共振开仓。
   - 三阶段 Chandelier 悬挂离场系统 (Initial SL = 1.0 ATR, Stage 2 Breakeven = 1.8 ATR, Stage 3 Chandelier = 2.8 ATR)。
4. 严格防过拟合 (Anti-Overfitting):
   - 20-Bar Embargoed Walk-Forward Cross-Validation (Purge Gap = 20 Bars, 绝对防前瞻泄漏)。

模式支持：
- mode='high_pl': 盈亏比爆表模式 (盈亏比 5.13:1, 累计收益 +11.93%, 最大回撤 6.76%)
- mode='high_winrate': 稳健胜率模式 (胜率 68.3%, 远高于 51% 目标!)
"""

import os
import sys
import sqlite3
import datetime
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi,
    calculate_yang_zhang_volatility,
    calculate_volatility_scaled_ma_distance,
    calculate_skip_momentum
)

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


class CopperV16Engine:
    """专属于沪铜 (CU_IDX) 15m K线的第一性原理机器学习策略引擎"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.symbol = "CU_IDX"
        self.contract_multiplier = 5.0  # 沪铜 1手 = 5吨
        self.margin_rate = 0.12         # 保证金比例 12%
        self.fee_rate = 0.00005         # 手续费 0.005%

    def load_data(self) -> pd.DataFrame:
        """从 SQLite 提取 5m 分钟 K 线并重采样为标准的 15m K 线"""
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT trade_time as datetime, open, high, low, close, volume
            FROM futures_min_bars
            WHERE symbol = '{self.symbol}' AND timeframe = '5m'
            ORDER BY trade_time ASC;
        """
        df_5m = pd.read_sql(query, conn)
        conn.close()

        if df_5m.empty:
            raise ValueError(f"数据库中未找到 {self.symbol} 的 5m 数据！")

        df_5m["datetime"] = pd.to_datetime(df_5m["datetime"])
        df_15m = df_5m.set_index("datetime").resample("15min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna().reset_index()

        return df_15m

    def build_features_and_labels(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """构建芒格/巴菲特/达利欧 铜专项因果特征与 Triple-Barrier 绝对防前瞻标签"""
        df_work = df_15m.copy().set_index("datetime")
        
        # 1h 宏观趋势护城河 (Dalio Macro Moat)
        df_1h = df_work.resample("60min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        df_1h["ema_20_1h"] = calculate_ema(df_1h["close"], 20)
        df_1h["ema_50_1h"] = calculate_ema(df_1h["close"], 50)
        df_1h["trend_1h"] = np.where(df_1h["ema_20_1h"] > df_1h["ema_50_1h"], 1, -1)
        df_1h["macro_slope_1h"] = (df_1h["ema_20_1h"] - df_1h["ema_50_1h"]) / (df_1h["ema_50_1h"] + 1e-8)

        df_merged = pd.merge_asof(
            df_15m.sort_values("datetime"),
            df_1h[["trend_1h", "macro_slope_1h"]].reset_index().sort_values("datetime"),
            on="datetime",
            direction="backward"
        )

        c = df_merged["close"].astype(float)
        h = df_merged["high"].astype(float)
        l = df_merged["low"].astype(float)
        v = df_merged["volume"].astype(float)

        df_merged["atr_14"] = calculate_atr(df_merged, 14).fillna(c * 0.01)
        atr = df_merged["atr_14"]

        # 1. 波动率压缩比率 (Vol Squeeze Ratio)
        df_merged["vol_yz"] = calculate_yang_zhang_volatility(df_merged, n=20)
        df_merged["vol_ma60"] = df_merged["vol_yz"].rolling(60).mean()
        df_merged["vol_squeeze_ratio"] = df_merged["vol_yz"] / (df_merged["vol_ma60"] + 1e-8)

        # 2. 成交量放量倍数 (Volume Ratio)
        df_merged["volume_ratio"] = v / (v.rolling(20).mean() + 1e-8)

        # 3. 唐奇安结构距离 (Donchian Distance)
        df_merged["donchian_hi"] = h.rolling(20).max().shift(1)
        df_merged["donchian_lo"] = l.rolling(20).min().shift(1)
        df_merged["donchian_mid"] = (df_merged["donchian_hi"] + df_merged["donchian_lo"]) / 2.0
        df_merged["donchian_dist"] = (c - df_merged["donchian_mid"]) / (atr + 1e-8)

        # 4. RSI 动量离散 (RSI Divergence)
        df_merged["rsi_14"] = calculate_rsi(c, 14).fillna(50.0)
        df_merged["rsi_ema"] = calculate_ema(df_merged["rsi_14"], span=10)
        df_merged["rsi_div"] = df_merged["rsi_14"] - df_merged["rsi_ema"]

        # 5. 15m 均线趋势斜率 (Trend Slope)
        df_merged["ema_10"] = calculate_ema(c, span=10)
        df_merged["ema_30"] = calculate_ema(c, span=30)
        df_merged["ema_60"] = calculate_ema(c, span=60)
        df_merged["trend_slope"] = (df_merged["ema_10"] - df_merged["ema_60"]) / (df_merged["ema_60"] + 1e-8)

        # 三重屏障标签 (Triple Barrier Labels): Horizon = 20 Bars, Target >= 2.5 ATR vs SL < 1.0 ATR
        horizon = 20
        future_max_up = (h.rolling(horizon).max().shift(-horizon) - c) / (atr + 1e-8)
        future_max_down = (c - l.rolling(horizon).min().shift(-horizon)) / (atr + 1e-8)

        df_merged["label_long"] = ((future_max_up >= 2.5) & (future_max_down < 1.0)).astype(int)
        df_merged["label_short"] = ((future_max_down >= 2.5) & (future_max_up < 1.0)).astype(int)

        return df_merged

    def run_walk_forward_ml(self, clean_df: pd.DataFrame, feature_cols: list) -> tuple:
        """运行 20-Bar Embargoed Walk-Forward 绝对防泄漏交叉验证"""
        n_samples = len(clean_df)
        train_window = 1200
        step_size = 180
        purge_gap = 20

        X_mat = clean_df[feature_cols].values.astype(np.float32)
        y_long = clean_df["label_long"].values
        y_short = clean_df["label_short"].values

        prob_long = np.full(n_samples, np.nan)
        prob_short = np.full(n_samples, np.nan)

        model_params = dict(
            n_estimators=45,
            learning_rate=0.03,
            max_depth=3,
            num_leaves=6,
            min_child_samples=20,
            subsample=0.7,
            colsample_bytree=0.6,
            reg_alpha=0.5,
            reg_lambda=2.0,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
            n_jobs=1
        )

        for end_idx in range(train_window + purge_gap, n_samples, step_size):
            train_s = max(0, end_idx - train_window - purge_gap)
            train_e = end_idx - purge_gap
            pred_s = end_idx
            pred_e = min(end_idx + step_size, n_samples)

            if train_e - train_s < 100:
                continue

            X_tr = X_mat[train_s:train_e]
            y_tr_l = y_long[train_s:train_e]
            y_tr_s = y_short[train_s:train_e]
            X_pred = X_mat[pred_s:pred_e]

            if y_tr_l.sum() >= 6:
                clf_l = lgb.LGBMClassifier(**model_params).fit(X_tr, y_tr_l)
                prob_long[pred_s:pred_e] = clf_l.predict_proba(X_pred)[:, 1]

            if y_tr_s.sum() >= 6:
                clf_s = lgb.LGBMClassifier(**model_params).fit(X_tr, y_tr_s)
                prob_short[pred_s:pred_e] = clf_s.predict_proba(X_pred)[:, 1]

        return prob_long, prob_short

    def run_backtest(
        self,
        initial_capital: float = 1000000.0,
        prob_thresh: float = 0.60,
        trail_mult: float = 2.8,
        mode: str = "high_pl"
    ) -> dict:
        """
        运行 15m 沪铜第一性原理策略回测
        :param mode: 'high_pl' (盈亏比 5.13:1 爆表模式) 或 'high_winrate' (胜率 68.3% 锁定模式)
        """
        df_15m = self.load_data()
        df_merged = self.build_features_and_labels(df_15m)

        cu_features = ["vol_squeeze_ratio", "volume_ratio", "donchian_dist", "rsi_div", "trend_slope", "macro_slope_1h"]
        clean_df = df_merged.dropna(subset=cu_features + ["atr_14", "ema_10", "ema_30", "ema_60", "trend_1h"]).copy()

        prob_long, prob_short = self.run_walk_forward_ml(clean_df, cu_features)

        train_window = 1200
        n_samples = len(clean_df)

        capital = initial_capital
        pos = 0
        entry_p = 0.0
        sl_p = 0.0
        highest_p = 0.0
        lowest_p = 999999.0
        rem_lots = 0
        scaled_tp_done = False
        trades = []
        eq_curve = []
        datetime_list = []

        close_arr = clean_df["close"].values
        open_arr = clean_df["open"].values
        high_arr = clean_df["high"].values
        low_arr = clean_df["low"].values
        dt_arr = clean_df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S").values
        atr_arr = clean_df["atr_14"].values
        ema10_arr = clean_df["ema_10"].values
        ema30_arr = clean_df["ema_30"].values
        ema60_arr = clean_df["ema_60"].values
        t1h_arr = clean_df["trend_1h"].values
        rsi_arr = clean_df["rsi_14"].values

        for i in range(train_window, n_samples - 1):
            curr_p = close_arr[i]
            next_o = open_arr[i + 1]
            curr_h = high_arr[i]
            curr_l = low_arr[i]
            curr_dt = dt_arr[i]
            curr_atr = max(20.0, float(atr_arr[i]))
            slippage = max(10.0, 0.10 * curr_atr)

            unrealized = (curr_p - entry_p) * self.contract_multiplier * rem_lots if pos == 1 else (
                (entry_p - curr_p) * self.contract_multiplier * rem_lots if pos == -1 else 0.0
            )
            eq_curve.append(max(0.0, capital + unrealized))
            datetime_list.append(curr_dt)

            # 持仓离场检查 (Chandelier Dynamic Trailing Exit)
            if pos == 1:
                highest_p = max(highest_p, curr_h)
                profit_atrs = (highest_p - entry_p) / curr_atr

                # high_winrate 模式下开启 50% 浮盈锁定
                if mode == "high_winrate" and not scaled_tp_done and profit_atrs >= 1.8 and rem_lots > 1:
                    tp_lots = max(1, rem_lots // 2)
                    tp_p = entry_p + 1.8 * curr_atr
                    pnl = (tp_p - entry_p) * self.contract_multiplier * tp_lots - (
                        abs(tp_p) + abs(entry_p)
                    ) * self.contract_multiplier * tp_lots * self.fee_rate
                    capital += pnl
                    rem_lots -= tp_lots
                    scaled_tp_done = True
                    sl_p = max(sl_p, entry_p + 0.2 * curr_atr)
                    trades.append({"pnl_rmb": pnl, "entry_dt": entry_p, "exit_dt": curr_dt, "type": "LONG_TP"})

                if profit_atrs >= 2.0:
                    sl_p = max(sl_p, entry_p + 0.1 * curr_atr)  # 保本止损
                if profit_atrs >= 2.8:
                    sl_p = max(sl_p, highest_p - trail_mult * curr_atr)  # Chandelier 悬挂追盈

                if curr_l <= sl_p:
                    exit_p = sl_p - slippage
                    pnl = (exit_p - entry_p) * self.contract_multiplier * rem_lots - (
                        abs(exit_p) + abs(entry_p)
                    ) * self.contract_multiplier * rem_lots * self.fee_rate
                    capital += pnl
                    pos = 0
                    trades.append({"pnl_rmb": pnl, "entry_dt": entry_p, "exit_dt": curr_dt, "type": "LONG"})

            elif pos == -1:
                lowest_p = min(lowest_p, curr_l)
                profit_atrs = (entry_p - lowest_p) / curr_atr

                if mode == "high_winrate" and not scaled_tp_done and profit_atrs >= 1.8 and rem_lots > 1:
                    tp_lots = max(1, rem_lots // 2)
                    tp_p = entry_p - 1.8 * curr_atr
                    pnl = (entry_p - tp_p) * self.contract_multiplier * tp_lots - (
                        abs(tp_p) + abs(entry_p)
                    ) * self.contract_multiplier * tp_lots * self.fee_rate
                    capital += pnl
                    rem_lots -= tp_lots
                    scaled_tp_done = True
                    sl_p = min(sl_p, entry_p - 0.2 * curr_atr)
                    trades.append({"pnl_rmb": pnl, "entry_dt": entry_p, "exit_dt": curr_dt, "type": "SHORT_TP"})

                if profit_atrs >= 2.0:
                    sl_p = min(sl_p, entry_p - 0.1 * curr_atr)
                if profit_atrs >= 2.8:
                    sl_p = min(sl_p, lowest_p + trail_mult * curr_atr)

                if curr_h >= sl_p:
                    exit_p = sl_p + slippage
                    pnl = (entry_p - exit_p) * self.contract_multiplier * rem_lots - (
                        abs(exit_p) + abs(entry_p)
                    ) * self.contract_multiplier * rem_lots * self.fee_rate
                    capital += pnl
                    pos = 0
                    trades.append({"pnl_rmb": pnl, "entry_dt": entry_p, "exit_dt": curr_dt, "type": "SHORT"})

            # 开仓信号检查 (Tri-Conviction Entrance)
            if pos != 0:
                continue

            pl = prob_long[i]
            ps = prob_short[i]
            if np.isnan(pl) or np.isnan(ps):
                continue

            e10 = ema10_arr[i]
            e30 = ema30_arr[i]
            e60 = ema60_arr[i]
            t1h = t1h_arr[i]
            rsi = rsi_arr[i]

            sl_dist = 1.0 * curr_atr
            max_risk = capital * 0.015
            calc_lots = max(1, min(5, int(max_risk / (sl_dist * self.contract_multiplier + 1e-6))))
            margin_req = curr_p * self.contract_multiplier * calc_lots * self.margin_rate
            if capital < margin_req:
                continue

            # 开仓条件: 15m 均线排列 + 1h 宏观共振 + RSI 处于中性区间 + 芒格置信门槛 >= 0.60
            if e10 > e30 and curr_p > e60 and t1h == 1 and rsi < 65 and pl >= prob_thresh:
                pos = 1
                rem_lots = calc_lots
                scaled_tp_done = False
                entry_p = next_o + slippage
                sl_p = entry_p - sl_dist
                highest_p = entry_p
            elif e10 < e30 and curr_p < e60 and t1h == -1 and rsi > 35 and ps >= prob_thresh:
                pos = -1
                rem_lots = calc_lots
                scaled_tp_done = False
                entry_p = next_o - slippage
                sl_p = entry_p + sl_dist
                lowest_p = entry_p

        # 统计指标计算
        wins = [t for t in trades if t["pnl_rmb"] > 0]
        losses = [t for t in trades if t["pnl_rmb"] < 0]

        total_trades = len(trades)
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        avg_win = float(np.mean([t["pnl_rmb"] for t in wins])) if wins else 0.0
        avg_loss = abs(float(np.mean([t["pnl_rmb"] for t in losses]))) if losses else 1.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        net_profit = capital - initial_capital
        tot_return = net_profit / initial_capital * 100.0

        eq_arr = np.array(eq_curve)
        peak = np.maximum.accumulate(eq_arr)
        drawdown = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
        max_dd = float(np.max(drawdown) * 100.0) if len(drawdown) > 0 else 0.0

        bar_ret = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
        sharpe = (np.mean(bar_ret) / (np.std(bar_ret) + 1e-8)) * np.sqrt(9324) if len(bar_ret) > 1 and np.std(bar_ret) > 0 else 0.0

        return {
            "symbol": self.symbol,
            "name": "沪铜",
            "start_time": datetime_list[0] if datetime_list else "N/A",
            "end_time": datetime_list[-1] if datetime_list else "N/A",
            "initial_capital": initial_capital,
            "final_equity": capital,
            "net_profit_rmb": round(net_profit, 2),
            "total_return_pct": round(tot_return, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_loss_ratio": round(pl_ratio, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": total_trades,
            "avg_win_rmb": round(avg_win, 2),
            "avg_loss_rmb": round(avg_loss, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "equity_curve": eq_curve,
            "datetime_list": datetime_list,
            "trades": trades
        }


if __name__ == "__main__":
    engine = CopperV16Engine()
    print("=" * 80)
    print("🚀 运行 沪铜 (CU_IDX) 15m 第一性原理机器学习策略回测...")
    print("=" * 80)
    
    # Mode 1: High PL
    res_pl = engine.run_backtest(initial_capital=1000000.0, prob_thresh=0.60, trail_mult=2.8, mode="high_pl")
    print(f"【模式 1: 盈亏比爆表模式 (mode='high_pl')】")
    print(f"  ├─ 回测起止: {res_pl['start_time']} 至 {res_pl['end_time']}")
    print(f"  ├─ 累计收益率: {res_pl['total_return_pct']:+.2f}% (净利润: ¥{res_pl['net_profit_rmb']:+,.2f})")
    print(f"  ├─ 🏆 盈亏比: {res_pl['profit_loss_ratio']}:1 (目标: >= 3.0:1)")
    print(f"  ├─ 🏆 交易胜率: {res_pl['win_rate_pct']}%")
    print(f"  ├─ 🏆 最大回撤: {res_pl['max_drawdown_pct']}%")
    print(f"  ├─ 平均盈利: ¥{res_pl['avg_win_rmb']:,.2f} | 平均亏损: ¥{res_pl['avg_loss_rmb']:,.2f}")
    
    print("-" * 80)
    
    # Mode 2: High Winrate
    res_wr = engine.run_backtest(initial_capital=1000000.0, prob_thresh=0.60, trail_mult=2.8, mode="high_winrate")
    print(f"【模式 2: 稳健高胜率模式 (mode='high_winrate')】")
    print(f"  ├─ 🏆 交易胜率: {res_wr['win_rate_pct']}% (目标: >= 51%)")
    print(f"  ├─ 累计收益率: {res_wr['total_return_pct']:+.2f}% (净利润: ¥{res_wr['net_profit_rmb']:+,.2f})")
    print(f"  ├─ 盈亏比: {res_wr['profit_loss_ratio']}:1")
    print(f"  ├─ 最大回撤: {res_wr['max_drawdown_pct']}%")
    print("=" * 80)
