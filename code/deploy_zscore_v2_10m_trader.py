"""
deploy_zscore_v2_10m_trader.py — 极值 Z-Score 均值回归 + ML Meta-Labeling (10m V2 高胜率版) 虚拟盘 (TqSim) 自动化守护引擎

核心设计与安全隔离：
1. 策略唯一状态隔离: 状态写入 `data/zscore_v2_10m_virtual_state.json`，日志写入 `data/logs/zscore_v2_10m_virtual_trader.log`，台账写入 `data/logs/zscore_v2_10m_daily_trades.csv`。
2. 零冲突独立运行: 独立 TqSim 虚拟盘实例与独立 TargetPosTask 账户，与 15m 策略互不干扰。
3. 严格事件驱动: 在 10m Bar 完结瞬间执行 V2 微观形态与 Meta-Labeling 置信度推理，并在触及 SMA(5) 或动态保本锁时自动出场。
"""

import os
import sys
import json
import time
import sqlite3
import datetime
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from tqsdk import TqApi, TqAuth, TqSim, TargetPosTask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi

STATE_FILE = PROJECT_ROOT / "data/zscore_v2_10m_virtual_state.json"
LOG_DIR = PROJECT_ROOT / "data/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "zscore_v2_10m_virtual_trader.log"
TRADES_CSV = LOG_DIR / "zscore_v2_10m_daily_trades.csv"

logger = logging.getLogger("ZScore10mV2Trader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(formatter)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)


def get_tq_credentials():
    env_path = PROJECT_ROOT / ".env"
    account = ""
    password = ""
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "账号" in line or "TQ_ACCOUNT" in line:
                    parts = line.replace("：", ":").split(":")
                    if len(parts) > 1:
                        account = parts[1].strip()
                elif "密码" in line or "TQ_PASSWORD" in line:
                    parts = line.replace("：", ":").split(":")
                    if len(parts) > 1:
                        password = parts[1].strip()
    return account or "13800000000", password or "redacted_password"


class ZScore10mVirtualTrader:
    """10m 极值 Z-Score 均值回归 + ML Meta-Labeling 独立守护进程"""

    def __init__(self, initial_balance: float = 1000000.0):
        self.account, self.password = get_tq_credentials()
        self.initial_balance = initial_balance
        self.timeframe_sec = 600  # 10分钟 = 600秒

        # 核心主力映射
        self.symbol_mapping = {
            "AU_IDX": "KQ.i@SHFE.au",
            "AG_IDX": "KQ.i@SHFE.ag",
            "SC_IDX": "KQ.i@INE.sc",
            "TA_IDX": "KQ.i@CZCE.TA",
            "CU_IDX": "KQ.i@SHFE.cu",
            "RB_IDX": "KQ.i@SHFE.rb",
            "HC_IDX": "KQ.i@SHFE.hc",
            "I_IDX":  "KQ.i@DCE.i",
            "SA_IDX": "KQ.i@CZCE.SA",
            "MA_IDX": "KQ.i@CZCE.MA",
            "J_IDX":  "KQ.i@DCE.j",
            "JM_IDX": "KQ.i@DCE.jm",
            "AL_IDX": "KQ.i@SHFE.al",
            "ZN_IDX": "KQ.i@SHFE.zn",
            "SN_IDX": "KQ.i@SHFE.sn",
            "RU_IDX": "KQ.i@SHFE.ru",
            "M_IDX":  "KQ.i@DCE.m",
            "P_IDX":  "KQ.i@DCE.p",
            "LC_IDX": "KQ.i@GFEX.lc",
            "SR_IDX": "KQ.i@CZCE.SR",
            "CF_IDX": "KQ.i@CZCE.CF",
            "FG_IDX": "KQ.i@CZCE.FG",
            "SI_IDX": "KQ.i@GFEX.si",
            "C_IDX":  "KQ.i@DCE.c",
            "Y_IDX":  "KQ.i@DCE.y"
        }

        self.strategy_state = {}
        self.load_state()
        self.meta_models = {}
        self.pretrain_meta_models()

    def load_state(self):
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    self.strategy_state = json.load(f)
                logger.info(f"💾 成功加载 10m 历史状态: {len(self.strategy_state)} 个品种记录")
            except Exception as e:
                logger.error(f"读取状态文件失败: {e}")
                self.strategy_state = {}
        for sym in self.symbol_mapping.keys():
            if sym not in self.strategy_state:
                self.strategy_state[sym] = {
                    "pos": 0, "lots": 0, "entry_price": 0.0, "entry_time": "-",
                    "stop_loss": 0.0, "highest_price": 0.0, "lowest_price": 0.0,
                    "holding_bars": 0, "breakeven_locked": False, "last_processed_dt": "-"
                }

    def save_state(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.strategy_state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def log_trade_to_csv(self, trade_record: dict):
        file_exists = TRADES_CSV.exists()
        df = pd.DataFrame([trade_record])
        df.to_csv(TRADES_CSV, mode="a", header=not file_exists, index=False, encoding="utf-8-sig")

    def pretrain_meta_models(self):
        logger.info("🧠 正在预训练 10m 极值 Z-Score Meta-Labeling 滚动分类器...")
        feature_cols = [
            "zscore", "rsi_2", "squeeze", "accel_norm", "vol_ratio", "vol_climax",
            "rsi_14", "shadow_rejection_long", "shadow_rejection_short",
            "donchian_dist", "oi_flow", "oi_unwinding", "trend_1h"
        ]
        conn = sqlite3.connect(DB_PATH)
        for sym in self.symbol_mapping.keys():
            try:
                df = pd.read_sql_query(
                    "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                    "WHERE symbol=? AND timeframe='10m' ORDER BY trade_time ASC",
                    conn, params=(sym,)
                )
                if len(df) >= 2000:
                    from run_zscore_meta_backtest import compute_zscore_features_and_meta_labels
                    cfg = SYMBOL_CONFIGS.get(sym, {"multiplier": 10.0})
                    df_feat = compute_zscore_features_and_meta_labels(df, multiplier=cfg["multiplier"], macro_freq="60min")
                    valid_idx = np.where(~np.isnan(df_feat["meta_label"].values))[0]
                    if len(valid_idx) >= 10:
                        X = df_feat[feature_cols].iloc[valid_idx].values.astype(np.float32)
                        y = df_feat["meta_label"].iloc[valid_idx].values.astype(int)
                        clf = lgb.LGBMClassifier(
                            n_estimators=30, learning_rate=0.03, max_depth=3, num_leaves=5,
                            min_child_samples=3, class_weight="balanced", random_state=42, verbose=-1, n_jobs=1
                        )
                        clf.fit(X, y)
                        self.meta_models[sym] = clf
            except Exception as e:
                logger.warning(f"预训练 10m 模型跳过 [{sym}]: {e}")
        conn.close()
        logger.info(f"✅ 10m Meta-Labeling 预训练就绪: {len(self.meta_models)} 个品种")

    def run(self):
        logger.info("=" * 80)
        logger.info(f"🚀 启动 10m 极值 Z-Score + ML Meta-Labeling 虚拟盘守护引擎")
        logger.info(f"📌 覆盖 25 大真实主力合约 | 周期: 10m | 初始本金: ¥{self.initial_balance:,.2f}")
        logger.info("=" * 80)

        sim = TqSim(init_balance=self.initial_balance)
        api = TqApi(sim, auth=TqAuth(self.account, self.password))

        klines_map = {}
        target_pos_map = {}
        for sym, tq_code in self.symbol_mapping.items():
            try:
                klines_map[sym] = api.get_kline_serial(tq_code, self.timeframe_sec, data_length=200)
                target_pos_map[sym] = TargetPosTask(api, tq_code)
            except Exception as e:
                logger.error(f"订阅品种失败 [{sym} -> {tq_code}]: {e}")

        last_heartbeat = time.time()

        try:
            while True:
                api.wait_update()
                now_ts = time.time()

                if now_ts - last_heartbeat >= 3600:
                    last_heartbeat = now_ts
                    account_info = api.get_account()
                    logger.info(f"💓 [10m 心跳] 账户动态权益: ¥{account_info.balance:,.2f} | 浮动盈亏: ¥{account_info.float_profit:,.2f}")

                for sym, klines in klines_map.items():
                    if len(klines) < 30:
                        continue

                    cfg = SYMBOL_CONFIGS.get(sym, {"multiplier": 10.0, "max_lots": 5})
                    multiplier = cfg["multiplier"]
                    state = self.strategy_state[sym]

                    last_k = klines.iloc[-1]
                    curr_dt_str = datetime.datetime.fromtimestamp(last_k.datetime / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                    curr_c = float(last_k.close)
                    curr_h = float(last_k.high)
                    curr_l = float(last_k.low)

                    # 1. 实时持仓盯市与动态出场
                    if state["pos"] != 0:
                        state["highest_price"] = max(state["highest_price"], curr_h)
                        state["lowest_price"] = min(state["lowest_price"], curr_l)
                        
                        close_series = pd.Series(klines["close"].values)
                        sma_5 = float(close_series.rolling(5).mean().iloc[-1])
                        atr_14 = max(2.0, float(calculate_atr(pd.DataFrame({
                            "open": klines["open"], "high": klines["high"], "low": klines["low"], "close": klines["close"]
                        }), 14).iloc[-1]))

                        exit_trigger = False
                        exit_price = curr_c
                        exit_reason = ""

                        if state["pos"] == 1:
                            if curr_h >= sma_5:
                                exit_trigger = True
                                exit_price = sma_5
                                exit_reason = f"回归 SMA(5) 极速完全止盈 ({sma_5:.2f})"
                            elif curr_l <= state["stop_loss"]:
                                exit_trigger = True
                                exit_price = state["stop_loss"]
                                exit_reason = f"触发止损边界 ({state['stop_loss']:.2f})"
                            elif state["holding_bars"] >= 5:
                                exit_trigger = True
                                exit_price = curr_c
                                exit_reason = "达到最大持仓上限 5 根 Bar 均值清仓"
                            else:
                                if curr_h >= state["entry_price"] + 0.4 * atr_14:
                                    if not state.get("breakeven_locked", False):
                                        state["stop_loss"] = max(state["stop_loss"], state["entry_price"] + 0.05 * atr_14)
                                        state["breakeven_locked"] = True
                                        logger.info(f"🔒 [10m {sym}] 浮盈超 0.4 ATR，触发动态保本锁: 止损提至 {state['stop_loss']:.2f}")

                        elif state["pos"] == -1:
                            if curr_l <= sma_5:
                                exit_trigger = True
                                exit_price = sma_5
                                exit_reason = f"回归 SMA(5) 极速完全止盈 ({sma_5:.2f})"
                            elif curr_h >= state["stop_loss"]:
                                exit_trigger = True
                                exit_price = state["stop_loss"]
                                exit_reason = f"触发止损边界 ({state['stop_loss']:.2f})"
                            elif state["holding_bars"] >= 5:
                                exit_trigger = True
                                exit_price = curr_c
                                exit_reason = "达到最大持仓上限 5 根 Bar 均值清仓"
                            else:
                                if curr_l <= state["entry_price"] - 0.4 * atr_14:
                                    if not state.get("breakeven_locked", False):
                                        state["stop_loss"] = min(state["stop_loss"], state["entry_price"] - 0.05 * atr_14)
                                        state["breakeven_locked"] = True
                                        logger.info(f"🔒 [10m {sym}] 浮盈超 0.4 ATR，触发动态保本锁: 止损降至 {state['stop_loss']:.2f}")

                        if exit_trigger:
                            target_pos_map[sym].set_target_volume(0)
                            pnl = (exit_price - state["entry_price"]) * multiplier * state["lots"] if state["pos"] == 1 else (state["entry_price"] - exit_price) * multiplier * state["lots"]
                            logger.info(f"🏁 [10m {sym} 平仓] 价格: {exit_price:.2f} | 盈亏: ¥{pnl:+,.2f} | 原因: {exit_reason}")
                            self.log_trade_to_csv({
                                "symbol": sym, "side": "LONG" if state["pos"] == 1 else "SHORT", "action": "EXIT",
                                "lots": state["lots"], "entry_time": state["entry_time"], "entry_price": state["entry_price"],
                                "exit_time": curr_dt_str, "exit_price": exit_price, "pnl": pnl, "reason": exit_reason
                            })
                            state["pos"] = 0
                            state["lots"] = 0
                            state["holding_bars"] = 0
                            state["breakeven_locked"] = False
                            self.save_state()

                    # 2. 仅在整点 10m Bar 完结瞬间判定新开仓
                    if api.is_changing(klines.iloc[-1], "datetime"):
                        state["holding_bars"] += 1

                        if state["pos"] == 0 and curr_dt_str != state.get("last_processed_dt", ""):
                            state["last_processed_dt"] = curr_dt_str

                            df_k = pd.DataFrame({
                                "datetime": pd.to_datetime(klines["datetime"] / 1e9, unit="s", utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None),
                                "open": klines["open"].astype(float),
                                "high": klines["high"].astype(float),
                                "low": klines["low"].astype(float),
                                "close": klines["close"].astype(float),
                                "volume": klines["volume"].astype(float),
                                "open_interest": klines.get("open_interest", pd.Series(np.zeros(len(klines)))).astype(float)
                            })

                            from strategies.zscore_mean_reversion_meta import calculate_signal
                            sig_series = calculate_signal(df_k)
                            sig = int(sig_series.iloc[-2]) if len(sig_series) >= 2 else 0

                            if sig != 0:
                                prob = 0.55
                                if sym in self.meta_models:
                                    try:
                                        from run_zscore_meta_backtest import compute_zscore_features_and_meta_labels
                                        df_f = compute_zscore_features_and_meta_labels(df_k, multiplier=multiplier, macro_freq="60min")
                                        feature_cols = [
                                            "zscore", "rsi_2", "squeeze", "accel_norm", "vol_ratio", "vol_climax",
                                            "rsi_14", "shadow_rejection_long", "shadow_rejection_short",
                                            "donchian_dist", "oi_flow", "oi_unwinding", "trend_1h"
                                        ]
                                        x_latest = df_f[feature_cols].iloc[-2].values.reshape(1, -1).astype(np.float32)
                                        prob = float(self.meta_models[sym].predict_proba(x_latest)[0, 1])
                                    except Exception:
                                        prob = 0.50

                                if prob >= 0.52:
                                    atr = max(2.0, float(calculate_atr(df_k, 14).iloc[-2]))
                                    sl_dist = 1.2 * atr
                                    base_lots = max(1, min(cfg.get("max_lots", 5), int((self.initial_balance * 0.01) / (sl_dist * multiplier + 1e-6))))
                                    bet_scale = max(1.0, min(1.8, 1.0 + (prob - 0.5) * 3.0))
                                    calc_lots = max(1, int(base_lots * bet_scale))

                                    if sig == 1:
                                        target_pos_map[sym].set_target_volume(calc_lots)
                                        state["pos"] = 1
                                        state["lots"] = calc_lots
                                        state["entry_price"] = curr_c
                                        state["entry_time"] = curr_dt_str
                                        state["stop_loss"] = curr_c - sl_dist
                                        state["highest_price"] = curr_c
                                        state["lowest_price"] = curr_c
                                        state["holding_bars"] = 0
                                        state["breakeven_locked"] = False
                                        logger.info(f"🎯 [10m {sym} 极值买多] 价格: {curr_c:.2f} | 数量: {calc_lots}手 | 止损: {state['stop_loss']:.2f} | Meta置信度: {prob:.1%}")

                                    elif sig == -1:
                                        target_pos_map[sym].set_target_volume(-calc_lots)
                                        state["pos"] = -1
                                        state["lots"] = calc_lots
                                        state["entry_price"] = curr_c
                                        state["entry_time"] = curr_dt_str
                                        state["stop_loss"] = curr_c + sl_dist
                                        state["highest_price"] = curr_c
                                        state["lowest_price"] = curr_c
                                        state["holding_bars"] = 0
                                        state["breakeven_locked"] = False
                                        logger.info(f"🎯 [10m {sym} 极值卖空] 价格: {curr_c:.2f} | 数量: {calc_lots}手 | 止损: {state['stop_loss']:.2f} | Meta置信度: {prob:.1%}")

                                    self.save_state()

        except KeyboardInterrupt:
            logger.info("🛑 接收到退出信号，安全保存状态并退出...")
            self.save_state()
            api.close()
        except Exception as e:
            logger.error(f"❌ 虚拟盘运行时异常: {e}", exc_info=True)
            self.save_state()
            api.close()


if __name__ == "__main__":
    trader = ZScore10mVirtualTrader()
    trader.run()
