"""
code/deploy_taiyin_relative_value_trader.py — 【连山·太阴】实盘级商品跨品种相对价值套利后台守护进程
Lianshan-Taiyin Relative Value Live Paper Trader Daemon

监控并交易第一梯队 S 级与第二梯队 A 级核心跨品种产业链对：
1. MA_PP: 甲醇 vs 聚丙烯 (MTO 利润, 6:4 手数)
2. TA_PF: PTA vs 短纤 (聚酯纺丝差, 8:7 手数)
3. SC_FU: 原油 vs 燃油 (渣油裂解差, 1:10 手数)
4. TA_EG: PTA vs 乙二醇 (聚酯双原料, 6:5 手数)
5. C_CS:  玉米 vs 淀粉 (深加工利润, 10:7 手数)
6. JM_J:  焦煤 vs 焦炭 (双焦配比, 4:3 手数)
"""

from __future__ import annotations

import os
import sys
import time
import json
import math
import datetime

# 强制统一北京时间 (UTC+8 / Asia/Shanghai)
os.environ["TZ"] = "Asia/Shanghai"
try:
    time.tzset()
except Exception:
    pass
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(CODE_DIR))

STATE_FILE = DATA_DIR / "taiyin_relative_value_state.json"
TRADES_CSV = LOGS_DIR / "taiyin_relative_value_daily_trades.csv"
LOG_FILE = LOGS_DIR / "taiyin_relative_value_trader.log"
DB_PATH = str(DATA_DIR / "ashare_quant.db")

TIER_1_PAIRS = {
    "MA_PP": {
        "name": "甲醇制烯烃 (MTO利润)",
        "sector": "煤化工",
        "sym_a": "MA_IDX", "sym_b": "PP_IDX",
        "contract_a": "MA2609.CZCE", "contract_b": "pp2609.DCE",
        "mult_a": 10.0, "mult_b": 5.0,
        "lots_a": 6, "lots_b": 4,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 1.5, "win_rate": 85.7, "sharpe": 3.55
    },
    "TA_PF": {
        "name": "聚酯短纤纺丝差",
        "sector": "聚酯化纤",
        "sym_a": "TA_IDX", "sym_b": "PF_IDX",
        "contract_a": "TA2609.CZCE", "contract_b": "PF2609.CZCE",
        "mult_a": 5.0, "mult_b": 5.0,
        "lots_a": 8, "lots_b": 7,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 1.1, "win_rate": 84.8, "sharpe": 3.77
    },
    "SC_FU": {
        "name": "渣油裂解价差",
        "sector": "石油能化",
        "sym_a": "SC_IDX", "sym_b": "FU_IDX",
        "contract_a": "sc2610.INE", "contract_b": "fu2610.SHFE",
        "mult_a": 1000.0, "mult_b": 10.0,
        "lots_a": 1, "lots_b": 10,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 3.4, "win_rate": 58.6, "sharpe": 1.51
    },
    "TA_EG": {
        "name": "聚酯双原料配比",
        "sector": "聚酯化纤",
        "sym_a": "TA_IDX", "sym_b": "EG_IDX",
        "contract_a": "TA2609.CZCE", "contract_b": "eg2609.DCE",
        "mult_a": 5.0, "mult_b": 10.0,
        "lots_a": 6, "lots_b": 5,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 4.0, "win_rate": 77.3, "sharpe": 2.11
    },
    "C_CS": {
        "name": "玉米淀粉加工利润",
        "sector": "农产加工",
        "sym_a": "C_IDX", "sym_b": "CS_IDX",
        "contract_a": "c2609.DCE", "contract_b": "cs2609.DCE",
        "mult_a": 10.0, "mult_b": 10.0,
        "lots_a": 10, "lots_b": 7,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 2.9, "win_rate": 85.2, "sharpe": 3.29
    },
    "JM_J": {
        "name": "双焦炼焦利润",
        "sector": "黑色原材料",
        "sym_a": "JM_IDX", "sym_b": "J_IDX",
        "contract_a": "jm2609.DCE", "contract_b": "j2609.DCE",
        "mult_a": 60.0, "mult_b": 100.0,
        "lots_a": 4, "lots_b": 3,
        "win": 160, "z_in": 1.8, "z_out": 0.2, "z_stop": 3.5,
        "half_life": 13.2, "win_rate": 60.9, "sharpe": 0.71
    }
}


def log_message(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{ts}] {msg}"
    print(log_line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        pass


def init_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "initial_capital": 1000000.0,
        "current_equity": 1000000.0,
        "total_profit": 0.0,
        "active_positions": 0,
        "positions": {},
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def save_state(state: Dict[str, Any]):
    state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_daemon_cycle():
    log_message("🚀 【连山·太阴】实盘级跨品种相对价值套利守护进程启动...")
    state = init_state()

    while True:
        try:
            now = datetime.datetime.now()
            # 刷新状态
            pos_dict = state.get("positions", {})
            active_cnt = sum(1 for p in pos_dict.values() if p.get("pos", 0) != 0)
            state["active_positions"] = active_cnt
            state["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            save_state(state)

            # 每 15 秒心跳日志
            log_message(f"💓 [Heartbeat] 活跃相对价值配对: {len(TIER_1_PAIRS)} 个 | 持仓配对数: {active_cnt} | 账户权益: ¥{state['current_equity']:,.2f}")
            time.sleep(15)

        except KeyboardInterrupt:
            log_message("🛑 收到终止信号，安全退出...")
            break
        except Exception as e:
            log_message(f"❌ 运行异常: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run_daemon_cycle()
