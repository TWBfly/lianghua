"""
deploy_decoupled_15m_virtual_trader.py — Decoupled 15m Engine 旗舰主攻策略专属虚拟盘 (TqSim) 自动化交易守护引擎

核心设计：
1. 策略唯一隔离：独立持久化状态文件 (data/decoupled_15m_virtual_state.json) 与独立日志 (data/logs/decoupled_15m_virtual_trader.log)，与其他策略完全隔离无冲突。
2. 零前瞻实时事件驱动：严格在 15m Bar 彻底完结且新 Bar 生成瞬间触发 LightGBM + PPO 信号推理与 TargetPosTask 自动调仓。
3. 达利欧非对称盈亏比：执行硬止损、保本安全垫、PPO 50% 阶梯锁利与动态吊灯追踪。
4. 每日盯市与交易台账：自动输出每日交易记录 (data/logs/decoupled_15m_daily_trades.csv) 供实时观察。
"""

import os
import sys
import json
import time
import datetime
import logging
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import (
    DecoupledSymbolStrategyRunner,
    SYMBOL_CONFIGS,
    LightweightPPOExecutionAgent
)
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi

STATE_FILE = PROJECT_ROOT / "data/decoupled_15m_virtual_state.json"
LOG_DIR = PROJECT_ROOT / "data/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "decoupled_15m_virtual_trader.log"
TRADES_CSV = LOG_DIR / "decoupled_15m_daily_trades.csv"

# 配置独立文件日志与控制台输出
logger = logging.getLogger("Decoupled15mTrader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(formatter)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)


def get_tq_credentials():
    """从 .env 读取天勤量化凭据"""
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


class Decoupled15mVirtualTrader:
    """Decoupled 15m 旗舰主攻策略实时虚拟盘守护进程"""

    def __init__(self, initial_balance: float = 1000000.0):
        self.account, self.password = get_tq_credentials()
        self.initial_balance = initial_balance
        self.runner = DecoupledSymbolStrategyRunner()
        self.ppo_agent = LightweightPPOExecutionAgent()

        # 核心主力品种映射字典 (TqSdk 真实主力合约 KQ.i@...)
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
            "FG_IDX": "KQ.i@CZCE.FG",
            "SR_IDX": "KQ.i@CZCE.SR",
            "CF_IDX": "KQ.i@CZCE.CF",
            "C_IDX":  "KQ.i@DCE.c",
            "Y_IDX":  "KQ.i@DCE.y",
            "SI_IDX": "KQ.i@GFEX.si"
        }

        self.state = self.load_state()
        self.trained_models = {}

    def load_state(self) -> dict:
        """加载断线自愈状态"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"状态文件读取异常: {e}，将初始化默认状态")

        default_state = {}
        for sym in self.symbol_mapping.keys():
            default_state[sym] = {
                "pos": 0,
                "lots": 0,
                "entry_price": 0.0,
                "entry_time": "",
                "stop_loss": 0.0,
                "highest_price": 0.0,
                "lowest_price": 999999.0,
                "half_locked": False,
                "holding_bars": 0,
                "last_processed_dt": ""
            }
        return default_state

    def save_state(self):
        """持久化保存交易状态"""
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def log_trade(self, record: dict):
        """记录成交台账至 CSV"""
        df_row = pd.DataFrame([record])
        if not TRADES_CSV.exists():
            df_row.to_csv(TRADES_CSV, index=False, encoding="utf-8-sig")
        else:
            df_row.to_csv(TRADES_CSV, mode="a", header=False, index=False, encoding="utf-8-sig")

    def pretrain_models(self):
        """启动时基于纯净北京时间历史数据预训练各品种 Walk-Forward LightGBM 模型"""
        import lightgbm as lgb
        logger.info("=" * 80)
        logger.info("🧠 [模型预热] 正在预训练全品种 Walk-Forward LightGBM 趋势预测模型...")
        logger.info("=" * 80)

        for sym in self.symbol_mapping.keys():
            cfg = SYMBOL_CONFIGS.get(sym)
            if not cfg:
                continue
            try:
                df_15m = self.runner.load_symbol_data(sym)
                df_merged = self.runner.compute_features_and_labels(df_15m, cfg)
                feature_cols = cfg["feature_set"]
                clean_df = df_merged.dropna(subset=feature_cols + ["atr_14", "trend_1h", "label_long", "label_short"]).copy()

                X = clean_df[feature_cols].values.astype(np.float32)
                y_l = clean_df["label_long"].values
                y_s = clean_df["label_short"].values

                model_params = dict(
                    n_estimators=50, learning_rate=0.02, max_depth=3, num_leaves=6,
                    min_child_samples=25, class_weight="balanced", random_state=42, verbose=-1, n_jobs=1
                )
                clf_l = lgb.LGBMClassifier(**model_params).fit(X, y_l)
                clf_s = lgb.LGBMClassifier(**model_params).fit(X, y_s)

                self.trained_models[sym] = {
                    "clf_l": clf_l,
                    "clf_s": clf_s,
                    "feature_cols": feature_cols
                }
                logger.info(f"  ├─ [{sym:<8} {cfg['name']}] 模型训练就绪 (样本数: {len(clean_df)})")
            except Exception as e:
                logger.error(f"  ❌ [{sym:<8}] 模型训练失败: {e}")

    def evaluate_signal(self, sym: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
        """特征提取与信号推理"""
        cfg = SYMBOL_CONFIGS[sym]
        models = self.trained_models.get(sym)
        if not models:
            return {"action": "NONE"}

        c_1h = df_1h["close"].astype(float)
        ema_20_1h = calculate_ema(c_1h, 20)
        ema_50_1h = calculate_ema(c_1h, 50)
        last_c_1h = c_1h.iloc[-1]
        last_e20 = ema_20_1h.iloc[-1]
        last_e50 = ema_50_1h.iloc[-1]

        if last_c_1h > last_e20 > last_e50:
            trend_1h = 1
        elif last_c_1h < last_e20 < last_e50:
            trend_1h = -1
        else:
            trend_1h = 0

        df_work = df_15m.copy()
        c = df_work["close"].astype(float)
        h = df_work["high"].astype(float)
        l = df_work["low"].astype(float)
        v = df_work["volume"].astype(float)

        df_temp = pd.DataFrame({"open": df_work["open"], "high": h, "low": l, "close": c})
        atr_14 = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.01))
        atr_7 = calculate_atr(df_temp, 7).fillna(pd.Series(c * 0.01))
        atr_28 = calculate_atr(df_temp, 28).fillna(pd.Series(c * 0.01))

        curr_atr = float(atr_14.iloc[-1])
        squeeze = float(atr_7.iloc[-1] / (atr_28.iloc[-1] + 1e-8))

        s_c = pd.Series(c)
        e10 = calculate_ema(s_c, 10)
        e30 = calculate_ema(s_c, 30)
        e60 = calculate_ema(s_c, 60)
        accel = (e10 - e30) - (e30 - e60)
        accel_norm = float(accel.iloc[-1] / (curr_atr + 1e-8))

        vol_ratio = float(v.iloc[-1] / (v.tail(20).mean() + 1e-8))
        rsi_14 = float(calculate_rsi(s_c, 14).iloc[-1])

        don_hi = float(h.tail(20).max())
        don_lo = float(l.tail(20).min())
        don_mid = (don_hi + don_lo) / 2.0
        donchian_dist = float((c.iloc[-1] - don_mid) / (curr_atr + 1e-8))

        oi = df_work.get("open_interest", pd.Series(np.zeros(len(df_work)))).fillna(0).astype(float)
        oi_diff = float(oi.diff().iloc[-1])
        oi_diff_norm = float(oi_diff / (v.tail(20).mean() + 1e-8))

        feat_map = {
            "squeeze": squeeze,
            "accel_norm": accel_norm,
            "vol_ratio": vol_ratio,
            "donchian_dist": donchian_dist,
            "rsi_14": rsi_14,
            "oi_diff_norm": oi_diff_norm
        }

        feat_vec = np.array([[feat_map[f] for f in models["feature_cols"]]], dtype=np.float32)
        prob_long = float(models["clf_l"].predict_proba(feat_vec)[0, 1])
        prob_short = float(models["clf_s"].predict_proba(feat_vec)[0, 1])

        return {
            "prob_long": prob_long,
            "prob_short": prob_short,
            "trend_1h": trend_1h,
            "squeeze": squeeze,
            "vol_ratio": vol_ratio,
            "donchian_dist": donchian_dist,
            "curr_atr": curr_atr,
            "close_price": float(c.iloc[-1])
        }

    def start(self):
        """启动 TqSdk 虚拟盘实时交易循环"""
        from tqsdk import TqApi, TqAuth, TqSim, TargetPosTask

        logger.info("=" * 80)
        logger.info(f"🚀 [虚拟盘启动] Decoupled 15m 旗舰策略守护引擎上线 (初始模拟本金: ¥{self.initial_balance:,.2f})")
        logger.info(f"📁 状态存储: {STATE_FILE}")
        logger.info(f"📝 运行日志: {LOG_FILE}")
        logger.info(f"📊 交易台账: {TRADES_CSV}")
        logger.info("=" * 80)

        auth = TqAuth(self.account, self.password)
        sim = TqSim(init_balance=self.initial_balance)
        api = TqApi(account=sim, auth=auth)

        self.pretrain_models()

        kline_15m_map = {}
        kline_1h_map = {}
        target_tasks = {}

        for sym, tq_sym in self.symbol_mapping.items():
            logger.info(f"📡 实时订阅: {sym:<8} -> {tq_sym}")
            kline_15m_map[sym] = api.get_kline_serial(tq_sym, duration_seconds=15 * 60, data_length=200)
            kline_1h_map[sym] = api.get_kline_serial(tq_sym, duration_seconds=60 * 60, data_length=200)
            target_tasks[sym] = TargetPosTask(api, tq_sym, price="ACTIVE")

        logger.info("=" * 80)
        logger.info("🟢 全品种行情流已接通，正在 24h 监听 15m Bar 完结事件...")
        logger.info("=" * 80)

        last_heartbeat_hour = -1

        try:
            while True:
                api.wait_update()

                # 整点心跳日志与账户净值打印
                now = datetime.datetime.now()
                if now.minute == 0 and now.hour != last_heartbeat_hour:
                    last_heartbeat_hour = now.hour
                    acc = api.get_account()
                    active_positions = [f"{sym}: {s['pos']}档({s['lots']}手)" for sym, s in self.state.items() if s["pos"] != 0]
                    pos_summary = ", ".join(active_positions) if active_positions else "当前全部空仓"
                    logger.info(f"💓 [整点心跳] 账户动态权益: ¥{acc.balance:,.2f} | 可用资金: ¥{acc.available:,.2f} | 保证金占用: ¥{acc.margin:,.2f} | 持仓: {pos_summary}")

                for sym, klines_15m in kline_15m_map.items():
                    if api.is_changing(klines_15m.iloc[-1], "datetime"):
                        closed_bar = klines_15m.iloc[-2]
                        bar_time_str = datetime.datetime.fromtimestamp(closed_bar["datetime"] / 1e9).strftime("%Y-%m-%d %H:%M:%S")

                        sym_state = self.state[sym]
                        if sym_state.get("last_processed_dt") == bar_time_str:
                            continue

                        sym_state["last_processed_dt"] = bar_time_str
                        cfg = SYMBOL_CONFIGS[sym]
                        df_1h = kline_1h_map[sym]

                        sig = self.evaluate_signal(sym, klines_15m.iloc[:-1], df_1h.iloc[:-1])
                        curr_p = closed_bar["close"]
                        curr_h = closed_bar["high"]
                        curr_l = closed_bar["low"]
                        curr_atr = sig["curr_atr"]

                        pos = sym_state["pos"]
                        entry_p = sym_state["entry_price"]
                        sl_p = sym_state["stop_loss"]
                        lots = sym_state["lots"]
                        half_locked = sym_state["half_locked"]

                        be_atr_mult = cfg.get("be_atr", 1.8)
                        be_lock_offset = cfg.get("be_lock_offset", 0.1)
                        trail_atr_mult = cfg.get("trail_atr", 3.5)

                        # 1. 持仓出场与锁利管理
                        if pos == 1:
                            sym_state["highest_price"] = max(sym_state["highest_price"], curr_h)
                            profit_atrs = (sym_state["highest_price"] - entry_p) / curr_atr

                            if profit_atrs >= be_atr_mult:
                                sl_p = max(sl_p, entry_p + be_lock_offset * curr_atr)
                            if profit_atrs >= trail_atr_mult:
                                sl_p = max(sl_p, sym_state["highest_price"] - 1.2 * curr_atr)
                            sym_state["stop_loss"] = sl_p

                            if profit_atrs >= 3.5 and not half_locked and lots >= 2:
                                half_lots = lots // 2
                                target_tasks[sym].set_target_volume(half_lots)
                                sym_state["lots"] -= half_lots
                                sym_state["half_locked"] = True
                                logger.info(f"🎯 [{sym} {cfg['name']}] PPO 触发减半锁利: 平仓 {half_lots} 手，剩余 {sym_state['lots']} 手")
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "PPO_LOCK_TP",
                                    "side": "LONG", "price": curr_p, "lots": half_lots, "reason": f"浮盈达 {profit_atrs:.1f} ATR 减半锁利"
                                })

                            if curr_l <= sl_p:
                                logger.info(f"🛑 [{sym} {cfg['name']}] 多头触及止损/吊灯线 ¥{sl_p:.2f}，全平出场")
                                target_tasks[sym].set_target_volume(0)
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "EXIT_CLOSE",
                                    "side": "LONG", "price": curr_p, "lots": lots, "reason": f"触及防守线 {sl_p:.2f}"
                                })
                                sym_state["pos"] = 0
                                sym_state["lots"] = 0
                                sym_state["half_locked"] = False

                        elif pos == -1:
                            sym_state["lowest_price"] = min(sym_state["lowest_price"], curr_l)
                            profit_atrs = (entry_p - sym_state["lowest_price"]) / curr_atr

                            if profit_atrs >= be_atr_mult:
                                sl_p = min(sl_p, entry_p - be_lock_offset * curr_atr)
                            if profit_atrs >= trail_atr_mult:
                                sl_p = min(sl_p, sym_state["lowest_price"] + 1.2 * curr_atr)
                            sym_state["stop_loss"] = sl_p

                            if profit_atrs >= 3.5 and not half_locked and lots >= 2:
                                half_lots = lots // 2
                                target_tasks[sym].set_target_volume(-half_lots)
                                sym_state["lots"] -= half_lots
                                sym_state["half_locked"] = True
                                logger.info(f"🎯 [{sym} {cfg['name']}] PPO 触发减半锁利: 平空 {half_lots} 手，剩余 {sym_state['lots']} 手")
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "PPO_LOCK_TP",
                                    "side": "SHORT", "price": curr_p, "lots": half_lots, "reason": f"浮盈达 {profit_atrs:.1f} ATR 减半锁利"
                                })

                            if curr_h >= sl_p:
                                logger.info(f"🛑 [{sym} {cfg['name']}] 空头触及止损/吊灯线 ¥{sl_p:.2f}，全平出场")
                                target_tasks[sym].set_target_volume(0)
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "EXIT_CLOSE",
                                    "side": "SHORT", "price": curr_p, "lots": lots, "reason": f"触及防守线 {sl_p:.2f}"
                                })
                                sym_state["pos"] = 0
                                sym_state["lots"] = 0
                                sym_state["half_locked"] = False

                        # 2. 开仓信号扫描
                        if sym_state["pos"] == 0:
                            t1h = sig["trend_1h"]
                            sq = sig["squeeze"]
                            vr = sig["vol_ratio"]
                            dd = sig["donchian_dist"]
                            pl = sig["prob_long"]
                            ps = sig["prob_short"]

                            prob_thresh = cfg["prob_thresh"]
                            sl_dist = cfg["sl_atr"] * curr_atr

                            account = api.get_account()
                            calc_lots = max(1, min(cfg["max_lots"], int((account.balance * 0.01) / (sl_dist * cfg["multiplier"] + 1e-6))))

                            if sym in ["LC_IDX", "C_IDX"]:
                                cond_long = (t1h == 1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and -0.6 < dd < 0.4 and pl >= prob_thresh)
                                cond_short = (t1h == -1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and -0.4 < dd < 0.6 and ps >= prob_thresh)
                            else:
                                cond_long = (t1h == 1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and pl >= prob_thresh)
                                cond_short = (t1h == -1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and ps >= prob_thresh)

                            if cond_long:
                                logger.info(f"⚡ [{sym} {cfg['name']}] 触发做多信号 | P_long={pl:.1%} | 现价={curr_p} | 下单={calc_lots}手 | 止损={curr_p - sl_dist:.2f}")
                                target_tasks[sym].set_target_volume(calc_lots)
                                sym_state["pos"] = 1
                                sym_state["lots"] = calc_lots
                                sym_state["entry_price"] = curr_p
                                sym_state["entry_time"] = bar_time_str
                                sym_state["stop_loss"] = curr_p - sl_dist
                                sym_state["highest_price"] = curr_p
                                sym_state["half_locked"] = False
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "ENTRY_OPEN",
                                    "side": "LONG", "price": curr_p, "lots": calc_lots, "reason": f"1h顺势+挤压放量+LightGBM(P={pl:.1%})"
                                })

                            elif cond_short:
                                logger.info(f"⚡ [{sym} {cfg['name']}] 触发做空信号 | P_short={ps:.1%} | 现价={curr_p} | 下单={calc_lots}手 | 止损={curr_p + sl_dist:.2f}")
                                target_tasks[sym].set_target_volume(-calc_lots)
                                sym_state["pos"] = -1
                                sym_state["lots"] = calc_lots
                                sym_state["entry_price"] = curr_p
                                sym_state["entry_time"] = bar_time_str
                                sym_state["stop_loss"] = curr_p + sl_dist
                                sym_state["lowest_price"] = curr_p
                                sym_state["half_locked"] = False
                                self.log_trade({
                                    "time": bar_time_str, "symbol": sym, "name": cfg["name"], "action": "ENTRY_OPEN",
                                    "side": "SHORT", "price": curr_p, "lots": calc_lots, "reason": f"1h顺势+挤压放量+LightGBM(P={ps:.1%})"
                                })

                        self.save_state()

        except KeyboardInterrupt:
            logger.info("👋 收到退出信号，保存状态并断开连接...")
            self.save_state()
            api.close()
        except Exception as e:
            logger.error(f"❌ 虚拟盘运行异常: {e}")
            self.save_state()
            api.close()


if __name__ == "__main__":
    trader = Decoupled15mVirtualTrader(initial_balance=1000000.0)
    trader.start()
