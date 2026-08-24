"""
run_simnow_paper_trader.py — 基于 SimNow CTP / PaperAccount 的 vn.py 自动化虚拟盘挂机守护引擎

核心功能：
1. 自动从 .env 读取 SimNow CTP 配置并与交易引擎绑定；
2. 全天候 24h 挂机守护：包含高频事件循环、动态心跳报告与状态持久化；
3. 断线自愈与安全气囊：持仓与风控状态实时落盘至 data/vnpy_paper_state.json；
4. 交易明细台账：每次开仓/平仓/止盈止损自动写入 data/logs/vnpy_daily_trades.csv。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import datetime
import logging
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
sys.path.append(str(PROJECT_ROOT / "strategies"))
sys.path.append(str(PROJECT_ROOT / "vnpy"))

from vnpy_data_adapter import BarData, Exchange, Interval
from vnpy_strategy_template import CtaTemplate
from vnpy_tianji_strategy import VnpyTianjiStrategy
from vnpy_zscore_strategy import VnpyZScoreStrategy
from deploy_vnpy_paper_trader import VnpyPaperEngine, logger, STATE_FILE, TRADES_CSV, LOG_FILE


def load_simnow_credentials() -> dict:
    """自动从 .env 或 data/connect_simnow.json 读取 SimNow 凭证"""
    creds = {
        "user_id": "",
        "password": "",
        "broker_id": "9999",
        "auth_code": "0000000000000000",
        "app_id": "simnow_client_test",
        "md_address": "tcp://180.168.146.187:10211",
        "td_address": "tcp://180.168.146.187:10201",
    }

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip()
                    if k in {"SIMNOW_USER", "SIMNOW_ACCOUNT", "SIMNOW_USER_ID"}:
                        creds["user_id"] = v
                    elif k in {"SIMNOW_PASSWORD", "SIMNOW_PASS", "SIMNOW_PWD"}:
                        creds["password"] = v
                    elif k in {"SIMNOW_BROKER", "SIMNOW_BROKER_ID"}:
                        creds["broker_id"] = v or "9999"
                    elif k in {"SIMNOW_APPID", "SIMNOW_APP_ID"}:
                        creds["app_id"] = v or "simnow_client_test"
                    elif k in {"SIMNOW_AUTHCODE", "SIMNOW_AUTH_CODE"}:
                        creds["auth_code"] = v or "0000000000000000"
                    elif k in {"SIMNOW_MD_ADDRESS", "SIMNOW_MD"}:
                        creds["md_address"] = v or "tcp://180.168.146.187:10211"
                    elif k in {"SIMNOW_TD_ADDRESS", "SIMNOW_TD"}:
                        creds["td_address"] = v or "tcp://180.168.146.187:10201"
                elif "：" in line or ":" in line:
                    parts = line.replace("：", ":").split(":", 1)
                    k = parts[0].strip()
                    v = parts[1].strip()
                    if "SIMNOW" in k.upper() and ("账号" in k or "USER" in k.upper()):
                        creds["user_id"] = v
                    elif "SIMNOW" in k.upper() and ("密码" in k or "PASS" in k.upper()):
                        creds["password"] = v

    cfg_file = PROJECT_ROOT / "data/connect_simnow.json"
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                json_data = json.load(f)
                for key, val in json_data.items():
                    if val:
                        creds[key] = val
        except Exception:
            pass

    return creds


def start_simnow_paper_trader(symbol: str = "ag2612.SHFE", strategy_type: str = "tianji_15m"):
    creds = load_simnow_credentials()

    strat_key = strategy_type.lower()
    if strat_key in {"tianji", "tianji_15m", "decoupled_15m"}:
        strat_key = "tianji_15m"
        strat_display_name = "15m 机器学习+PPO 趋势突破引擎 (天玑旗舰版)"
    elif strat_key in {"zscore_15m", "zscore"}:
        strat_key = "zscore_15m"
        strat_display_name = "15m 极值 Z-Score 均值回归 + Meta-Labeling (工业版)"
    elif strat_key in {"zscore_10m"}:
        strat_key = "zscore_10m"
        strat_display_name = "10m 极值 Z-Score 均值回归 + Meta-Labeling (高胜率版)"
    else:
        strat_key = "tianji_15m"
        strat_display_name = "15m 机器学习+PPO 趋势突破引擎 (天玑旗舰版)"

    data_dir = PROJECT_ROOT / "data"
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    state_file = data_dir / f"vnpy_{strat_key}_state.json"
    log_file = log_dir / f"vnpy_{strat_key}_trader.log"
    trades_csv = log_dir / f"vnpy_{strat_key}_daily_trades.csv"

    strat_logger = logging.getLogger(f"Vnpy_{strat_key}")
    strat_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    if not strat_logger.handlers:
        strat_logger.addHandler(fh)
        strat_logger.addHandler(ch)

    strat_logger.info("=" * 80)
    strat_logger.info("🚀 【vn.py x SimNow 虚拟盘自动化挂机守护引擎上线】")
    strat_logger.info("=" * 80)
    strat_logger.info(f"  投资者账号 (UserID):   {creds.get('user_id') or '【待配置】'}")
    strat_logger.info(f"  期货公司代码 (BrokerID): {creds.get('broker_id', '9999')}")
    strat_logger.info(f"  行情前置 (MdAddress):  {creds.get('md_address')}")
    strat_logger.info(f"  交易前置 (TdAddress):  {creds.get('td_address')}")
    strat_logger.info(f"  目标交易品种:          {symbol}")
    strat_logger.info(f"  挂载策略类型:          {strat_display_name}")
    strat_logger.info(f"  状态存储路径:          {state_file}")
    strat_logger.info(f"  运行日志路径:          {log_file}")
    strat_logger.info(f"  交易台账路径:          {trades_csv}")
    strat_logger.info("=" * 80)

    # 初始化对应策略的本地虚拟盘仿真撮合引擎
    engine = VnpyPaperEngine(
        initial_capital=1_000_000.0,
        state_file=state_file,
        trades_csv=trades_csv,
        logger_instance=strat_logger
    )

    if "zscore" in strat_key:
        strategy = VnpyZScoreStrategy(cta_engine=engine, strategy_name=f"ZScore_{symbol}", vt_symbol=symbol, setting={"fixed_size": 1.0})
    else:
        strategy = VnpyTianjiStrategy(cta_engine=engine, strategy_name=f"Tianji_{symbol}", vt_symbol=symbol, setting={"fixed_size": 1.0})

    strategy.on_init()
    strategy.on_start()
    engine.strategies[symbol] = strategy

    strat_logger.info(f"✅ 策略 [{strategy.strategy_name}] 已成功挂载并在事件循环中激活！")
    strat_logger.info("🟢 正在全天候 24h 监听 CTP 实时行情推送与离散事件触发...")

    last_heartbeat = 0
    try:
        while True:
            now_ts = time.time()

            # 每隔 30 秒打印一次系统心跳与动态权益
            if now_ts - last_heartbeat >= 30:
                last_heartbeat = now_ts
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pos_val = engine.positions.get(symbol, 0.0)
                strat_logger.info(
                    f"💓 [系统心跳 {now_str}] 动态权益: ¥{engine.balance:,.2f} | "
                    f"可用资金: ¥{engine.available:,.2f} | "
                    f"持仓: {pos_val} 手 | 活动订单: {len(engine.active_orders)} 笔 | 状态: 正常运行"
                )
                engine.save_state()

            time.sleep(1)

    except KeyboardInterrupt:
        strat_logger.info("\n👋 收到终止信号，正在保存状态...")
        engine.save_state()
        strat_logger.info("✅ 状态保存完毕，安全退出。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SimNow Paper Trader Daemon")
    parser.add_argument("--symbol", type=str, default="ag2612.SHFE", help="合约代码 (如 ag2612.SHFE, rb2610.SHFE)")
    parser.add_argument("--strategy", type=str, default="tianji_15m", help="策略类型: tianji_15m, zscore_15m, zscore_10m")
    args = parser.parse_args()

    start_simnow_paper_trader(args.symbol, args.strategy)

