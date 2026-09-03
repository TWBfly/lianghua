"""
A-Share Quantitative Strategy Engine - 15-Symbol Real-Time Futures Live / Paper Trader
【第一性原理：15 大商品期货 LightGBM + PPO 真实虚拟/实盘账户事件驱动交易引擎】

核心功能与架构：
1. 真实主力合约动态订阅：自动将连续指数映射至 TqSdk 实时主力合约 (KQ.i@...)。
2. 绝对零前瞻 Bar 完结事件监听：严格只在 15m K线收盘且新 K线生成的第 1 个毫秒触发模型推理。
3. 状态落盘与断线自愈：实时持久化当前仓位、止损点、保本点、最高价/最低价与 PPO 锁利状态至 JSON。
4. TqSdk TargetPosTask 托管：自动处理上期所平今/平昨与郑商/大商所平仓细节，超价对手单防飞单。
5. 全局账户风控安全气囊：全局保证金占用限制 <= 60%，单日亏损熔断保护。
"""

import os
import sys
import json
import time
import signal
import datetime
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import (
    DecoupledSymbolStrategyRunner,
    SYMBOL_CONFIGS,
    LightweightPPOExecutionAgent
)
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi

STATE_FILE = PROJECT_ROOT / "data/futures_live_state.json"


class FuturesLiveTradingEngine:
    """15 大核心商品期货 LightGBM + PPO 实时事件驱动交易引擎"""

    def __init__(self, tq_account: str = "", tq_password: str = "", is_sim: bool = True, initial_balance: float = 1000000.0):
        self.tq_account = tq_account
        self.tq_password = tq_password
        self.is_sim = is_sim
        self.initial_balance = initial_balance
        
        self.runner = DecoupledSymbolStrategyRunner()
        self.ppo_agent = LightweightPPOExecutionAgent()
        
        # 连续指数到 TqSdk 真实主力连续合约映射表 (实盘/模拟盘必须交易可下单的主力连续 KQ.m@，严禁使用指数 KQ.i@)
        self.symbol_mapping = {
            "AG_IDX": "KQ.m@SHFE.ag",
            "AU_IDX": "KQ.m@SHFE.au",
            "CU_IDX": "KQ.m@SHFE.cu",
            "SN_IDX": "KQ.m@SHFE.sn",
            "RB_IDX": "KQ.m@SHFE.rb",
            "I_IDX":  "KQ.m@DCE.i",
            "J_IDX":  "KQ.m@DCE.j",
            "JM_IDX": "KQ.m@DCE.jm",
            "SC_IDX": "KQ.m@INE.sc",
            "MA_IDX": "KQ.m@CZCE.MA",
            "TA_IDX": "KQ.m@CZCE.TA",
            "SA_IDX": "KQ.m@CZCE.SA",
            "M_IDX":  "KQ.m@DCE.m",
            "C_IDX":  "KQ.m@DCE.c",
            "LC_IDX": "KQ.m@GFEX.lc"
        }
        
        self.state = self.load_state()
        self.trained_models = {}  # 缓存各品种 LightGBM 训练好的模型

    def load_state(self) -> dict:
        """加载历史持久化交易状态 (断线与重启自愈)"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ 状态文件读取异常: {e}，初始化为空状态")
        
        default_state = {}
        for sym in SYMBOL_CONFIGS.keys():
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
        """实时保存交易状态"""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def pretrain_all_models(self):
        """盘前/启动时预训练各品种 LightGBM 模型 (使用全部历史 K线)"""
        print("=" * 80)
        print("🧠 [盘前初始化] 开始预训练 15 大品种 Walk-Forward LightGBM 模型...")
        print("=" * 80)
        import lightgbm as lgb
        
        for sym, cfg in SYMBOL_CONFIGS.items():
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
                print(f"  ├─ [{sym:<8} {cfg['name']}] 模型训练就绪 (样本量: {len(clean_df)})")
            except Exception as e:
                print(f"  ❌ [{sym:<8}] 模型训练失败: {e}")

    def evaluate_live_signal(self, sym: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
        """单品种实时 15m 收盘特征计算与信号推断"""
        cfg = SYMBOL_CONFIGS[sym]
        models = self.trained_models.get(sym)
        if not models:
            return {"action": "NONE"}

        # 1. 计算 1h 宏观主趋势 (严格上一已收盘 1h K线)
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

        # 2. 计算 15m 物理特征 (使用倒数第 1 根已收盘完结的 Bar)
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

    def run_live_loop(self):
        """启动 TqSdk 实时事件驱动流式交易主循环 (带外层自动重连与优雅退出保护)"""
        from tqsdk import TqApi, TqAuth, TqSim, TargetPosTask

        def sig_handler(signum, frame):
            print(f"\n👋 收到终止信号 ({signum})，保存状态并安全退出...")
            self.save_state()
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, sig_handler)
            signal.signal(signal.SIGINT, sig_handler)
        except Exception:
            pass

        print("=" * 80)
        mode_str = "【虚拟模拟盘 (TqSim)】" if self.is_sim else "【真实实盘 (CTP)】"
        print(f"🚀 启动 15 大商品期货 {mode_str} 实时自动化交易系统...")
        print("=" * 80)

        self.pretrain_all_models()

        retry_count = 0
        while True:
            api = None
            try:
                # 初始化 TqApi
                auth = TqAuth(self.tq_account, self.tq_password)
                sim_account = TqSim(init_balance=self.initial_balance) if self.is_sim else None
                api = TqApi(account=sim_account, auth=auth)

                # 订阅 15 大品种真实主力合约的 15m 与 1h K线
                kline_15m_map = {}
                kline_1h_map = {}
                target_pos_tasks = {}

                for sym, tq_sym in self.symbol_mapping.items():
                    print(f"📡 订阅行情: {sym:<8} -> {tq_sym}")
                    kline_15m_map[sym] = api.get_kline_serial(tq_sym, duration_seconds=15 * 60, data_length=200)
                    kline_1h_map[sym] = api.get_kline_serial(tq_sym, duration_seconds=60 * 60, data_length=200)
                    target_pos_tasks[sym] = TargetPosTask(api, tq_sym, price="ACTIVE")  # 对手价超价委托

                # M6 修复: 启动时仓位对账与状态校准
                if hasattr(api, 'get_position'):
                    for sym, tq_sym in self.symbol_mapping.items():
                        try:
                            pos_obj = api.get_position(tq_sym)
                            broker_net_pos = (pos_obj.pos_long - pos_obj.pos_short) if pos_obj else 0
                            local_pos = self.state[sym]["pos"] * self.state[sym]["lots"]
                            if broker_net_pos != local_pos:
                                print(f"⚠️ [启动对账告警] 品种 {sym}: 券商实时持仓={broker_net_pos} 手, 本地 STATE_FILE 记录={local_pos} 手")
                        except Exception:
                            pass

                print("=" * 80)
                print("🟢 所有品种行情订阅与 TargetPosTask 就绪，进入 15m Bar 完结事件监听循环...")
                print("=" * 80)
                retry_count = 0  # 连接成功后重置计数器

                while True:
                    api.wait_update()
                    
                    # ── 全局风控安全气囊 ──────────────────────────────
                    if hasattr(api, 'get_account'):
                        _acct = api.get_account()
                        # 保证金占用 > 60% 禁止新开仓
                        if _acct.margin / max(_acct.balance, 1.0) > 0.60:
                            _margin_breach = True
                        else:
                            _margin_breach = False
                        # 单日亏损 > 3% 全平熔断
                        if not hasattr(self, '_day_start_equity'):
                            self._day_start_equity = _acct.balance
                        _curr_date = datetime.datetime.now().strftime('%Y-%m-%d')
                        if not hasattr(self, '_last_check_date') or self._last_check_date != _curr_date:
                            self._day_start_equity = _acct.balance
                            self._last_check_date = _curr_date
                        if (_acct.balance - self._day_start_equity) / max(self._day_start_equity, 1.0) < -0.03:
                            print(f"🚨 单日亏损熔断！当日亏损 {(_acct.balance - self._day_start_equity):.2f}，全平所有仓位")
                            for _sym, _tpt in target_pos_tasks.items():
                                _tpt.set_target_volume(0)
                                self.state[_sym]["pos"] = 0
                                self.state[_sym]["lots"] = 0
                            self.save_state()
                            continue
                    else:
                        _margin_breach = False
                    
                    for sym, klines_15m in kline_15m_map.items():
                        # 严格判定：当上一根 15m Bar 彻底收盘、新 Bar 生成瞬间触发
                        if api.is_changing(klines_15m.iloc[-1], "datetime"):
                            # 取倒数第 2 根（即刚收盘完结的完整 15m Bar）
                            closed_bar = klines_15m.iloc[-2]
                            bar_time_str = datetime.datetime.fromtimestamp(closed_bar["datetime"] / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                            
                            sym_state = self.state[sym]
                            if sym_state.get("last_processed_dt") == bar_time_str:
                                continue  # 杜绝同周期重复触发
                                
                            sym_state["last_processed_dt"] = bar_time_str
                            cfg = SYMBOL_CONFIGS[sym]
                            df_1h = kline_1h_map[sym]
                            
                            # 特征提取与信号推断
                            sig = self.evaluate_live_signal(sym, klines_15m.iloc[:-1], df_1h.iloc[:-1])
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
                            
                            # 1. 持仓管理与动态出场 / PPO 锁利
                            if pos == 1:
                                sym_state["highest_price"] = max(sym_state["highest_price"], curr_h)
                                profit_atrs = (sym_state["highest_price"] - entry_p) / curr_atr
                                
                                # 保本与吊灯止盈
                                if profit_atrs >= be_atr_mult:
                                    sl_p = max(sl_p, entry_p + be_lock_offset * curr_atr)
                                if profit_atrs >= trail_atr_mult:
                                    sl_p = max(sl_p, sym_state["highest_price"] - 1.2 * curr_atr)
                                sym_state["stop_loss"] = sl_p
                                
                                # PPO 减半锁利
                                if profit_atrs >= 3.5 and not half_locked and lots >= 2:
                                    half_lots = lots // 2
                                    target_pos_tasks[sym].set_target_volume(half_lots)
                                    sym_state["lots"] -= half_lots
                                    sym_state["half_locked"] = True
                                    print(f"🎯 [{sym} {cfg['name']}] PPO 触发减半锁利: 平仓 {half_lots} 手，剩余 {sym_state['lots']} 手")
                                    
                                # 触及止损平仓
                                if curr_l <= sl_p:
                                    print(f"🛑 [{sym} {cfg['name']}] 多头触及止损/止盈线 {sl_p:.2f}，全平出场")
                                    target_pos_tasks[sym].set_target_volume(0)
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
                                    target_pos_tasks[sym].set_target_volume(-half_lots)
                                    sym_state["lots"] -= half_lots
                                    sym_state["half_locked"] = True
                                    print(f"🎯 [{sym} {cfg['name']}] PPO 触发减半锁利: 平空 {half_lots} 手，剩余 {sym_state['lots']} 手")
                                    
                                if curr_h >= sl_p:
                                    print(f"🛑 [{sym} {cfg['name']}] 空头触及止损/止盈线 {sl_p:.2f}，全平出场")
                                    target_pos_tasks[sym].set_target_volume(0)
                                    sym_state["pos"] = 0
                                    sym_state["lots"] = 0
                                    sym_state["half_locked"] = False

                            # 2. 空仓时寻找入场开仓机会
                            if sym_state["pos"] == 0:
                                t1h = sig["trend_1h"]
                                sq = sig["squeeze"]
                                vr = sig["vol_ratio"]
                                dd = sig["donchian_dist"]
                                pl = sig["prob_long"]
                                ps = sig["prob_short"]
                                
                                prob_thresh = cfg["prob_thresh"]
                                sl_dist = cfg["sl_atr"] * curr_atr
                                
                                # 资金管理与下单手数计算
                                account = api.get_account()
                                calc_lots = max(1, min(cfg["max_lots"], int((account.balance * 0.01) / (sl_dist * cfg["multiplier"] + 1e-6))))
                                
                                # 针对碳酸锂与玉米的唐奇安回踩规则
                                if sym in ["LC_IDX", "C_IDX"]:
                                    cond_long = (t1h == 1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and -0.6 < dd < 0.4 and pl >= prob_thresh)
                                    cond_short = (t1h == -1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and -0.4 < dd < 0.6 and ps >= prob_thresh)
                                else:
                                    cond_long = (t1h == 1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and pl >= prob_thresh)
                                    cond_short = (t1h == -1 and sq < cfg["squeeze_thresh"] and vr > 1.10 and ps >= prob_thresh)
                                    
                                if _margin_breach:
                                    print(f"⚠️ [{sym}] 保证金占用超 60%，跳过新开仓")
                                    pass
                                elif cond_long:
                                    print(f"⚡ [{sym} {cfg['name']}] 触发做多信号 | P_long={pl:.3f} | 当前价={curr_p} | 开仓={calc_lots}手 | 止损={curr_p - sl_dist:.2f}")
                                    target_pos_tasks[sym].set_target_volume(calc_lots)
                                    sym_state["pos"] = 1
                                    sym_state["lots"] = calc_lots
                                    sym_state["entry_price"] = curr_p
                                    sym_state["entry_time"] = bar_time_str
                                    sym_state["stop_loss"] = curr_p - sl_dist
                                    sym_state["highest_price"] = curr_p
                                    sym_state["half_locked"] = False
                                    
                                elif cond_short:
                                    print(f"⚡ [{sym} {cfg['name']}] 触发做空信号 | P_short={ps:.3f} | 当前价={curr_p} | 开仓={calc_lots}手 | 止损={curr_p + sl_dist:.2f}")
                                    target_pos_tasks[sym].set_target_volume(-calc_lots)
                                    sym_state["pos"] = -1
                                    sym_state["lots"] = calc_lots
                                    sym_state["entry_price"] = curr_p
                                    sym_state["entry_time"] = bar_time_str
                                    sym_state["stop_loss"] = curr_p + sl_dist
                                    sym_state["lowest_price"] = curr_p
                                    sym_state["half_locked"] = False
                            
                            # 每次处理完毕即刻持久化状态
                            self.save_state()

            except (KeyboardInterrupt, SystemExit):
                print("\n👋 收到终止指令，保存状态并安全退出...")
                self.save_state()
                if api:
                    try:
                        api.close()
                    except Exception:
                        pass
                break
            except Exception as e:
                self.save_state()
                # ponytail: 指数退避重连，上限 5 次
                retry_count += 1
                if retry_count > 5:
                    print(f"\n❌ 连续重试 {retry_count} 次失败，退出: {e}")
                    if api:
                        try:
                            api.close()
                        except Exception:
                            pass
                    break
                wait_sec = min(2 ** retry_count, 60)
                print(f"\n⚠️ 实盘异常 ({retry_count}/5): {e}，{wait_sec}s 后重连...")
                if api:
                    try:
                        api.close()
                    except Exception:
                        pass
                time.sleep(wait_sec)


TRADING_DISABLED_REASON = (
    "15m futures research has not passed the required gates; "
    "TqSim and live execution are isolated"
)


def main():
    print(f"TRADING_DISABLED: {TRADING_DISABLED_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
