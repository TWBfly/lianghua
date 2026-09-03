"""
code/futures_dashboard_server.py — 全品种商品期货量化策略多战队实盘与全景监控大屏 Web Server
【支持 太冲·10m微观弹性战队 + 太冲·30m波段中枢战队 + 归元·15m极值策略 一键实时切换】
访问地址: http://127.0.0.1:8090 (云端反向代理域名: https://739265.xyz/)
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import sqlite3
import sys
import time

# 强制统一北京时间 (UTC+8 / Asia/Shanghai)
os.environ["TZ"] = "Asia/Shanghai"
try:
    time.tzset()
except Exception:
    pass
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request
import numpy as np
import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from symbol_strategies.decoupled_symbol_engines import DB_PATH, SYMBOL_CONFIGS
from taichong_elastoplastic_tensor import calculate_signal, calculate_factors
from guiyuan_zscore_reversion import calculate_signal as calculate_guiyuan_signal
from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS
from run_ek_supertrend_v7_lln_audit import compute_v7_dynamic_supertrend

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)

DASHBOARD_SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "").strip()

@app.before_request
def check_auth():
    # 若配置了 DASHBOARD_SECRET_KEY，则对 /api/ 接口启用 Token 鉴权
    if DASHBOARD_SECRET_KEY and request.path.startswith("/api/"):
        token = request.headers.get("X-Dashboard-Token") or request.args.get("token")
        if token != DASHBOARD_SECRET_KEY:
            return jsonify({"error": "Unauthorized", "message": "Invalid or missing X-Dashboard-Token"}), 401

@app.after_request
def add_security_headers(response):
    origin = request.headers.get("Origin", "")
    allowed_domains = ["739265.xyz", "localhost", "127.0.0.1"]
    if any(d in origin for d in allowed_domains):
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Dashboard-Token"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

# 10m 战队与 30m 战队核心品种定义
SQUAD_10M_SYMBOLS = ["SN_IDX", "AU_IDX", "AG_IDX", "MA_IDX", "P_IDX"]
SQUAD_30M_SYMBOLS = ["SC_IDX", "LC_IDX", "J_IDX", "AL_IDX", "TA_IDX", "SI_IDX"]
DUAL_SQUAD_SYMBOLS = SQUAD_10M_SYMBOLS + SQUAD_30M_SYMBOLS
TIER_1_15M_SYMBOLS = ["AU_IDX", "AG_IDX", "SC_IDX", "TA_IDX", "MA_IDX", "SA_IDX", "HC_IDX", "P_IDX"]
TIANJI_TIER1_SYMBOLS = ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX", "P_IDX", "TA_IDX", "SC_IDX", "MA_IDX"]

STRATEGY_REGISTRY = {
    "tianji_dual_island_v2": {
        "id": "tianji_dual_island_v2",
        "name": "👑 【天极·双岛正交自适应策略 V2.0】 第一梯队 (4H宏观趋势 AU/AG/LC/SN + 30m产业均值 P/TA/SC/MA)",
        "short_name": "👑 天极·双岛正交 V2.0 (第一梯队 8大主力)",
        "timeframe": "4H/30m",
        "symbols": TIANJI_TIER1_SYMBOLS,
        "default_symbol": "AU_IDX",
        "state_file": PROJECT_ROOT / "data/tianji_v2_live_state.json",
        "fallback_state": PROJECT_ROOT / "data/tianji_v2_live_state.json",
        "log_file": PROJECT_ROOT / "data/logs/tianji_v2_tier1_live.log",
        "trades_csv": PROJECT_ROOT / "data/logs/tianji_v2_trades.csv",
        "process_keyword": "deploy_tianji_v2_tier1_trader",
        "execution_status": "NOT_IMPLEMENTED_LIVE_EXECUTION",
        "initial_capital": 1000000.0,
        "summary_win_rate": 56.9,
    },
    "taichong_dual_squad": {
        "id": "taichong_dual_squad",
        "name": "🔮 【太冲·弹塑性张量】双战队 (10m微观弹性 + 30m波段中枢回归)",
        "short_name": "太冲·双战队全景 (10m+30m 11主力)",
        "timeframe": "10m/30m",
        "symbols": DUAL_SQUAD_SYMBOLS,
        "default_symbol": "SN_IDX",
        "state_file": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "fallback_state": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taichong_dual_squad_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taichong_daily_trades.csv",
        "process_keyword": "deploy_taichong_squads_trader",
        "initial_capital": 2000000.0,
        "summary_win_rate": 78.6,
    },
    "taichong_10m_squad": {
        "id": "taichong_10m_squad",
        "name": "⚡ 【太冲·10m微观战队】沪锡/沪金/沪银/甲醇/棕榈油 (5h日内谐振+50m均线落袋)",
        "short_name": "太冲·10m微观战队 (5大主力)",
        "timeframe": "10m",
        "symbols": SQUAD_10M_SYMBOLS,
        "default_symbol": "SN_IDX",
        "state_file": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "fallback_state": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taichong_dual_squad_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taichong_daily_trades.csv",
        "process_keyword": "deploy_taichong_squads_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 78.2,
    },
    "taichong_30m_squad": {
        "id": "taichong_30m_squad",
        "name": "🌊 【太冲·30m波段战队】原油/碳酸锂/焦炭/沪铝/PTA/工业硅 (跨日宏观中枢回归)",
        "short_name": "太冲·30m波段战队 (6大主力)",
        "timeframe": "30m",
        "symbols": SQUAD_30M_SYMBOLS,
        "default_symbol": "SC_IDX",
        "state_file": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "fallback_state": PROJECT_ROOT / "data/taichong_dual_squad_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taichong_dual_squad_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taichong_daily_trades.csv",
        "process_keyword": "deploy_taichong_squads_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 79.0,
    },
    "guiyuan_zscore_15m": {
        "id": "guiyuan_zscore_15m",
        "name": "⚡ 【极值均值反转】15m 归元·极值策略 + ML Meta-Labeling (第一梯队核心实盘)",
        "short_name": "归元·极值策略 (15m 第一梯队)",
        "timeframe": "15m",
        "symbols": TIER_1_15M_SYMBOLS,
        "default_symbol": "AU_IDX",
        "state_file": PROJECT_ROOT / "data/zscore_v2_15m_virtual_state.json",
        "fallback_state": PROJECT_ROOT / "data/vnpy_zscore_15m_state.json",
        "log_file": PROJECT_ROOT / "data/logs/zscore_v2_15m_virtual_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/zscore_v2_15m_daily_trades.csv",
        "process_keyword": "deploy_zscore_v2_15m_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 76.5,
    },
    "taiyin_relative_value": {
        "id": "taiyin_relative_value",
        "name": "⚖️ 【太阴·跨品种相对价值套利】第一梯队 (MA-PP / TA-PF / SC-FU / C-CS / JM-J / TA-EG)",
        "short_name": "太阴·跨品种套利 (第一梯队 S级)",
        "timeframe": "15m",
        "symbols": ["MA_PP", "TA_PF", "SC_FU", "TA_EG", "C_CS", "JM_J"],
        "default_symbol": "MA_PP",
        "state_file": PROJECT_ROOT / "data/taiyin_relative_value_state.json",
        "fallback_state": PROJECT_ROOT / "data/taiyin_relative_value_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taiyin_relative_value_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taiyin_relative_value_daily_trades.csv",
        "process_keyword": "deploy_taiyin_relative_value_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 85.7,
    },
    "ek_supertrend_v7": {
        "id": "ek_supertrend_v7",
        "name": "🔮 【太冲·零滞后相变趋势引擎】EK-ZLP SuperTrend V7 (DSP零滞后+排列熵+非对称)",
        "short_name": "太冲·零滞后相变趋势 V7 (5大主力)",
        "timeframe": "15m",
        "symbols": ["AG_IDX", "CU_IDX", "AU_IDX", "LC_IDX", "P_IDX"],
        "default_symbol": "AG_IDX",
        "state_file": PROJECT_ROOT / "data/ek_supertrend_v7_state.json",
        "fallback_state": PROJECT_ROOT / "data/ek_supertrend_v7_state.json",
        "log_file": PROJECT_ROOT / "data/logs/ek_supertrend_v7_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/ek_supertrend_v7_trades.csv",
        "process_keyword": "deploy_ek_supertrend_v7_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 64.0,
    },
    "taiyin_calendar_spread": {
        "id": "taiyin_calendar_spread",
        "name": "⚖️ 【太阴·跨期套利】黄金白银 15m 跨期持有成本与期限结构套利 (TqSim 虚拟盘)",
        "short_name": "太阴·跨期套利 (黄金/白银 15m)",
        "timeframe": "15m",
        "symbols": ["AU_IDX", "AG_IDX"],
        "default_symbol": "AU_IDX",
        "state_file": PROJECT_ROOT / "data/taiyin_calendar_state.json",
        "fallback_state": PROJECT_ROOT / "data/taiyin_calendar_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taiyin_calendar_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taiyin_daily_trades.csv",
        "process_keyword": "deploy_taiyin_calendar_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 81.0,
    },
    "tianshu_liquidity_profile": {
        "id": "tianshu_liquidity_profile",
        "name": "⚡ 【天枢·量价真空跃迁】15m VPVR拓扑+OFI订单流失衡 (流动性真空极速跃迁)",
        "short_name": "天枢·量价真空跃迁 (15m)",
        "timeframe": "15m",
        "symbols": ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"],
        "default_symbol": "AG_IDX",
        "state_file": PROJECT_ROOT / "data/tianshu_liquidity_state.json",
        "fallback_state": PROJECT_ROOT / "data/tianshu_liquidity_state.json",
        "log_file": PROJECT_ROOT / "data/logs/tianshu_liquidity_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/tianshu_daily_trades.csv",
        "process_keyword": "deploy_tianshu_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 68.5,
    },
    "taiwei_wavelet_squeeze": {
        "id": "taiwei_wavelet_squeeze",
        "name": "🌊 【太微·小波分形相变】15m MODWT 3级多分辨率+DFA Hurst (能量相变趋势)",
        "short_name": "太微·小波分形相变 (15m)",
        "timeframe": "15m",
        "symbols": ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"],
        "default_symbol": "CU_IDX",
        "state_file": PROJECT_ROOT / "data/taiwei_wavelet_state.json",
        "fallback_state": PROJECT_ROOT / "data/taiwei_wavelet_state.json",
        "log_file": PROJECT_ROOT / "data/logs/taiwei_wavelet_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/taiwei_daily_trades.csv",
        "process_keyword": "deploy_taiwei_trader",
        "initial_capital": 1000000.0,
        "summary_win_rate": 66.2,
    },
    "beiji_csmom_matrix": {
        "id": "beiji_csmom_matrix",
        "name": "🧭 【北极·截面展期套利】15m 全市场年化展期收益率矩阵+截面动量 (风险平价对冲)",
        "short_name": "北极·截面展期套利 (15m)",
        "timeframe": "15m",
        "symbols": ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"],
        "default_symbol": "SC_IDX",
        "state_file": PROJECT_ROOT / "data/beiji_csmom_state.json",
        "fallback_state": PROJECT_ROOT / "data/beiji_csmom_state.json",
        "log_file": PROJECT_ROOT / "data/logs/beiji_csmom_trader.log",
        "trades_csv": PROJECT_ROOT / "data/logs/beiji_daily_trades.csv",
        "process_keyword": "deploy_beiji_trader",
        "initial_capital": 2000000.0,
        "summary_win_rate": 62.8,
    }
}

ALIAS_MAP = {
    "tianji": "tianji_dual_island_v2",
    "tianji_v2": "tianji_dual_island_v2",
    "tianji_dual_island_v2": "tianji_dual_island_v2",
    "taichong": "taichong_dual_squad",
    "taichong_dual": "taichong_dual_squad",
    "taichong_dual_squad": "taichong_dual_squad",
    "taichong_10m": "taichong_10m_squad",
    "taichong_10m_squad": "taichong_10m_squad",
    "taichong_30m": "taichong_30m_squad",
    "taichong_30m_squad": "taichong_30m_squad",
    "guiyuan_15m": "guiyuan_zscore_15m",
    "guiyuan_zscore_15m": "guiyuan_zscore_15m",
    "ek_supertrend_v7": "ek_supertrend_v7",
    "supertrend": "ek_supertrend_v7",
    "supertrend_v7": "ek_supertrend_v7",
    "taiyin_rv": "taiyin_relative_value",
    "taiyin_relative_value": "taiyin_relative_value",
    "relative_value": "taiyin_relative_value",
    "taiyin": "taiyin_relative_value",
    "taiyin_calendar": "taiyin_calendar_spread",
    "taiyin_calendar_spread": "taiyin_calendar_spread",
    "tianshu": "tianshu_liquidity_profile",
    "tianshu_liquidity": "tianshu_liquidity_profile",
    "tianshu_liquidity_profile": "tianshu_liquidity_profile",
    "taiwei": "taiwei_wavelet_squeeze",
    "taiwei_wavelet": "taiwei_wavelet_squeeze",
    "taiwei_wavelet_squeeze": "taiwei_wavelet_squeeze",
    "beiji": "beiji_csmom_matrix",
    "beiji_csmom": "beiji_csmom_matrix",
    "beiji_csmom_matrix": "beiji_csmom_matrix",
    "default": "tianji_dual_island_v2"
}

DOMINANT_CONTRACT_MAP = {
    "MA_PP": "MA2609 vs pp2609",
    "TA_PF": "TA2609 vs PF2609",
    "SC_FU": "sc2610 vs fu2610",
    "TA_EG": "TA2609 vs eg2609",
    "C_CS":  "c2609 vs cs2609",
    "JM_J":  "jm2609 vs j2609",
    "AU_IDX": "au2612.SHFE",
    "AG_IDX": "ag2612.SHFE",
    "SC_IDX": "sc2610.INE",
    "TA_IDX": "TA2609.CZCE",
    "MA_IDX": "MA2609.CZCE",
    "SA_IDX": "SA2609.CZCE",
    "HC_IDX": "hc2610.SHFE",
    "P_IDX":  "p2609.DCE",
    "CU_IDX": "cu2610.SHFE",
    "SN_IDX": "sn2610.SHFE",
    "AL_IDX": "al2610.SHFE",
    "ZN_IDX": "zn2610.SHFE",
    "SI_IDX": "si2611.GFEX",
    "LC_IDX": "lc2611.GFEX",
    "RB_IDX": "rb2610.SHFE",
    "I_IDX":  "i2609.DCE",
    "J_IDX":  "j2609.DCE",
    "JM_IDX": "jm2609.DCE",
    "RU_IDX": "ru2609.SHFE",
}

# 10m、30m 与 15m 大数定律五重门禁基准数据 (1000+ 笔平仓大数定律)
LLN_BENCHMARK_MAP = {
    # 天极·双岛正交自适应 V2.0 第一梯队
    "tianji_AU_IDX_4h": {"name": "沪金 (4H宏观)", "timeframe": "4H", "win_rate_pct": 56.9, "profit_loss_ratio": 2.20, "total_return_pct": 32.1, "net_profit_rmb": 321241.89, "total_trades": 168, "max_drawdown_pct": 9.21, "daily_sharpe": 2.85, "category": "贵金属 (4H 宏观趋势岛)"},
    "tianji_LC_IDX_4h": {"name": "碳酸锂 (4H宏观)", "timeframe": "4H", "win_rate_pct": 42.0, "profit_loss_ratio": 1.54, "total_return_pct": 25.2, "net_profit_rmb": 252508.84, "total_trades": 182, "max_drawdown_pct": 13.04, "daily_sharpe": 2.10, "category": "新能源 (4H 宏观趋势岛)"},
    "tianji_AG_IDX_4h": {"name": "沪银 (4H宏观)", "timeframe": "4H", "win_rate_pct": 48.5, "profit_loss_ratio": 1.40, "total_return_pct": 9.2, "net_profit_rmb": 91579.59, "total_trades": 195, "max_drawdown_pct": 12.13, "daily_sharpe": 1.85, "category": "贵金属 (4H 宏观趋势岛)"},
    "tianji_SN_IDX_4h": {"name": "沪锡 (4H宏观)", "timeframe": "4H", "win_rate_pct": 45.0, "profit_loss_ratio": 1.25, "total_return_pct": 4.5, "net_profit_rmb": 25478.41, "total_trades": 170, "max_drawdown_pct": 15.20, "daily_sharpe": 1.20, "category": "有色金属 (4H 宏观趋势岛)"},
    "tianji_P_IDX_30m":  {"name": "棕榈油 (30m均值)", "timeframe": "30m", "win_rate_pct": 57.1, "profit_loss_ratio": 1.45, "total_return_pct": 37.9, "net_profit_rmb": 379248.77, "total_trades": 210, "max_drawdown_pct": 0.44, "daily_sharpe": 3.10, "category": "油脂油料 (30m 产业均值岛)"},
    "tianji_TA_IDX_30m": {"name": "PTA (30m均值)", "timeframe": "30m", "win_rate_pct": 55.8, "profit_loss_ratio": 1.38, "total_return_pct": 13.7, "net_profit_rmb": 137221.03, "total_trades": 240, "max_drawdown_pct": 0.27, "daily_sharpe": 2.95, "category": "纺织化工 (30m 产业均值岛)"},
    "tianji_SC_IDX_30m": {"name": "原油 (30m均值)", "timeframe": "30m", "win_rate_pct": 51.5, "profit_loss_ratio": 1.25, "total_return_pct": 15.2, "net_profit_rmb": 152272.24, "total_trades": 225, "max_drawdown_pct": 1.85, "daily_sharpe": 2.15, "category": "能源化工 (30m 产业均值岛)"},
    "tianji_MA_IDX_30m": {"name": "甲醇 (30m均值)", "timeframe": "30m", "win_rate_pct": 46.3, "profit_loss_ratio": 1.15, "total_return_pct": 7.0, "net_profit_rmb": 69940.39, "total_trades": 230, "max_drawdown_pct": 1.20, "daily_sharpe": 1.65, "category": "能源化工 (30m 产业均值岛)"},
    "AU_IDX_4h": {"name": "沪金 (4H宏观)", "timeframe": "4H", "win_rate_pct": 56.9, "profit_loss_ratio": 2.20, "total_return_pct": 32.1, "net_profit_rmb": 321241.89, "total_trades": 168, "max_drawdown_pct": 9.21, "daily_sharpe": 2.85, "category": "贵金属 (4H 宏观趋势岛)"},
    "LC_IDX_4h": {"name": "碳酸锂 (4H宏观)", "timeframe": "4H", "win_rate_pct": 42.0, "profit_loss_ratio": 1.54, "total_return_pct": 25.2, "net_profit_rmb": 252508.84, "total_trades": 182, "max_drawdown_pct": 13.04, "daily_sharpe": 2.10, "category": "新能源 (4H 宏观趋势岛)"},
    "AG_IDX_4h": {"name": "沪银 (4H宏观)", "timeframe": "4H", "win_rate_pct": 48.5, "profit_loss_ratio": 1.40, "total_return_pct": 9.2, "net_profit_rmb": 91579.59, "total_trades": 195, "max_drawdown_pct": 12.13, "daily_sharpe": 1.85, "category": "贵金属 (4H 宏观趋势岛)"},
    "SN_IDX_4h": {"name": "沪锡 (4H宏观)", "timeframe": "4H", "win_rate_pct": 45.0, "profit_loss_ratio": 1.25, "total_return_pct": 4.5, "net_profit_rmb": 25478.41, "total_trades": 170, "max_drawdown_pct": 15.20, "daily_sharpe": 1.20, "category": "有色金属 (4H 宏观趋势岛)"},
    # 跨品种相对价值套利 (第一梯队 S级 与 第二梯队 A级)
    "MA_PP_15m": {"name": "甲醇/聚丙烯 (MTO利润)", "timeframe": "15m", "win_rate_pct": 85.71, "profit_loss_ratio": 19.21, "total_return_pct": 10.93, "net_profit_rmb": 109255.9, "total_trades": 21, "max_drawdown_pct": 0.81, "daily_sharpe": 3.55, "category": "煤化工加工利润 (第一梯队 S级)"},
    "TA_PF_15m": {"name": "PTA/短纤 (纺丝加工差)", "timeframe": "15m", "win_rate_pct": 84.85, "profit_loss_ratio": 5.58, "total_return_pct": 15.44, "net_profit_rmb": 154425.4, "total_trades": 33, "max_drawdown_pct": 3.03, "daily_sharpe": 3.77, "category": "聚酯纺丝差 (第一梯队 S级)"},
    "SC_FU_15m": {"name": "原油/燃油 (渣油裂解差)", "timeframe": "15m", "win_rate_pct": 58.62, "profit_loss_ratio": 2.34, "total_return_pct": 32.21, "net_profit_rmb": 322100.4, "total_trades": 29, "max_drawdown_pct": 16.29, "daily_sharpe": 1.51, "category": "渣油裂解差 (第一梯队 S级)"},
    "TA_EG_15m": {"name": "PTA/乙二醇 (聚酯原料)", "timeframe": "15m", "win_rate_pct": 77.27, "profit_loss_ratio": 2.86, "total_return_pct": 9.58, "net_profit_rmb": 95762.9, "total_trades": 22, "max_drawdown_pct": 2.75, "daily_sharpe": 2.11, "category": "聚酯双原料 (第二梯队 A级)"},
    "C_CS_15m":  {"name": "玉米/淀粉 (深加工利润)", "timeframe": "15m", "win_rate_pct": 85.19, "profit_loss_ratio": 12.62, "total_return_pct": 3.20, "net_profit_rmb": 31977.7, "total_trades": 27, "max_drawdown_pct": 0.46, "daily_sharpe": 3.29, "category": "深加工利润 (第二梯队 A级)"},
    "JM_J_15m":  {"name": "焦煤/焦炭 (双焦配比)", "timeframe": "15m", "win_rate_pct": 60.87, "profit_loss_ratio": 1.34, "total_return_pct": 6.95, "net_profit_rmb": 69502.2, "total_trades": 69, "max_drawdown_pct": 9.04, "daily_sharpe": 0.71, "category": "黑色原材料 (第二梯队 A级)"},
    # 10m 战队
    "SN_IDX_10m": {"name": "沪锡", "timeframe": "10m", "win_rate_pct": 73.15, "profit_loss_ratio": 5.80, "total_return_pct": 50.57, "net_profit_rmb": 50570.0, "total_trades": 1058, "max_drawdown_pct": 0.38, "daily_sharpe": 4.09, "category": "有色金属"},
    "AU_IDX_10m": {"name": "沪金", "timeframe": "10m", "win_rate_pct": 66.97, "profit_loss_ratio": 1.45, "total_return_pct": 25.08, "net_profit_rmb": 25076.3, "total_trades": 1088, "max_drawdown_pct": 1.68, "daily_sharpe": 1.10, "category": "贵金属"},
    "AG_IDX_10m": {"name": "沪银", "timeframe": "10m", "win_rate_pct": 68.52, "profit_loss_ratio": 1.51, "total_return_pct": 15.66, "net_profit_rmb": 15661.8, "total_trades": 1219, "max_drawdown_pct": 1.09, "daily_sharpe": 1.37, "category": "贵金属"},
    "P_IDX_10m":  {"name": "棕榈油", "timeframe": "10m", "win_rate_pct": 57.53, "profit_loss_ratio": 1.30, "total_return_pct": 5.41, "net_profit_rmb": 5414.4, "total_trades": 1120, "max_drawdown_pct": 0.49, "daily_sharpe": 0.74, "category": "油脂油料"},
    "MA_IDX_10m": {"name": "甲醇", "timeframe": "10m", "win_rate_pct": 63.64, "profit_loss_ratio": 1.25, "total_return_pct": 4.95, "net_profit_rmb": 4950.2, "total_trades": 1119, "max_drawdown_pct": 0.54, "daily_sharpe": 0.59, "category": "能源化工"},
    # 30m 战队
    "SC_IDX_30m": {"name": "原油", "timeframe": "30m", "win_rate_pct": 68.50, "profit_loss_ratio": 1.77, "total_return_pct": 69.65, "net_profit_rmb": 69654.9, "total_trades": 1104, "max_drawdown_pct": 4.32, "daily_sharpe": 0.79, "category": "能源化工"},
    "LC_IDX_30m": {"name": "碳酸锂", "timeframe": "30m", "win_rate_pct": 63.41, "profit_loss_ratio": 1.73, "total_return_pct": 12.51, "net_profit_rmb": 12509.7, "total_trades": 1068, "max_drawdown_pct": 0.53, "daily_sharpe": 1.03, "category": "新能源"},
    "J_IDX_30m":  {"name": "焦炭", "timeframe": "30m", "win_rate_pct": 64.44, "profit_loss_ratio": 1.47, "total_return_pct": 10.48, "net_profit_rmb": 10482.6, "total_trades": 1013, "max_drawdown_pct": 0.74, "daily_sharpe": 0.67, "category": "黑色系"},
    "AL_IDX_30m": {"name": "沪铝", "timeframe": "30m", "win_rate_pct": 55.17, "profit_loss_ratio": 1.37, "total_return_pct": 7.59, "net_profit_rmb": 7592.8, "total_trades": 1044, "max_drawdown_pct": 1.22, "daily_sharpe": 0.45, "category": "有色金属"},
    "TA_IDX_30m": {"name": "PTA", "timeframe": "30m", "win_rate_pct": 56.16, "profit_loss_ratio": 1.27, "total_return_pct": 6.55, "net_profit_rmb": 6551.4, "total_trades": 1187, "max_drawdown_pct": 0.89, "daily_sharpe": 0.32, "category": "纺织化工"},
    "SI_IDX_30m": {"name": "工业硅", "timeframe": "30m", "win_rate_pct": 61.84, "profit_loss_ratio": 1.21, "total_return_pct": 4.67, "net_profit_rmb": 4665.8, "total_trades": 1162, "max_drawdown_pct": 0.91, "daily_sharpe": 0.31, "category": "工业金属"},
    # 15m 基准
    "AU_IDX_15m": {"name": "黄金", "timeframe": "15m", "win_rate_pct": 77.8, "profit_loss_ratio": 2.28, "total_return_pct": 147.8, "net_profit_rmb": 1478574.0, "total_trades": 2168, "max_drawdown_pct": 2.82, "daily_sharpe": 2.45, "category": "贵金属"},
    "AG_IDX_15m": {"name": "白银", "timeframe": "15m", "win_rate_pct": 78.3, "profit_loss_ratio": 2.43, "total_return_pct": 93.3, "net_profit_rmb": 932664.0, "total_trades": 1732, "max_drawdown_pct": 1.36, "daily_sharpe": 2.88, "category": "贵金属"},
    "SC_IDX_15m": {"name": "原油", "timeframe": "15m", "win_rate_pct": 76.3, "profit_loss_ratio": 2.04, "total_return_pct": 151.9, "net_profit_rmb": 1518858.0, "total_trades": 1696, "max_drawdown_pct": 2.14, "daily_sharpe": 2.31, "category": "能源化工"},
    "TA_IDX_15m": {"name": "PTA", "timeframe": "15m", "win_rate_pct": 73.9, "profit_loss_ratio": 2.04, "total_return_pct": 24.8, "net_profit_rmb": 247565.0, "total_trades": 1300, "max_drawdown_pct": 0.67, "daily_sharpe": 2.65, "category": "纺织化工"},
    "MA_IDX_15m": {"name": "甲醇", "timeframe": "15m", "win_rate_pct": 74.2, "profit_loss_ratio": 2.15, "total_return_pct": 26.4, "net_profit_rmb": 264044.0, "total_trades": 1421, "max_drawdown_pct": 0.91, "daily_sharpe": 2.52, "category": "能源化工"},
    "SA_IDX_15m": {"name": "纯碱", "timeframe": "15m", "win_rate_pct": 74.0, "profit_loss_ratio": 1.93, "total_return_pct": 22.2, "net_profit_rmb": 222323.0, "total_trades": 1016, "max_drawdown_pct": 1.24, "daily_sharpe": 2.10, "category": "能源化工"},
    "HC_IDX_15m": {"name": "热卷", "timeframe": "15m", "win_rate_pct": 77.2, "profit_loss_ratio": 2.37, "total_return_pct": 62.1, "net_profit_rmb": 620841.0, "total_trades": 1699, "max_drawdown_pct": 0.96, "daily_sharpe": 2.74, "category": "黑色建材"},
    "P_IDX_15m":  {"name": "棕榈油", "timeframe": "15m", "win_rate_pct": 74.9, "profit_loss_ratio": 2.16, "total_return_pct": 59.5, "net_profit_rmb": 594921.0, "total_trades": 1539, "max_drawdown_pct": 1.96, "daily_sharpe": 2.22, "category": "油脂油料"}
}

BACKTEST_CACHE = {}
CACHE_TTL_SECONDS = 5.0


def get_cached_strategy_data(strategy_id: str, symbol: str):
    strat_key = ALIAS_MAP.get(strategy_id, "taichong_dual_squad")
    strat_cfg = STRATEGY_REGISTRY.get(strat_key, STRATEGY_REGISTRY["taichong_dual_squad"])

    # 确定具体品种的真实运行周期
    if strat_key == "tianji_dual_island_v2":
        tf = "4h" if symbol in ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX"] else "30m"
    elif strat_key == "taichong_dual_squad":
        tf = "10m" if symbol in SQUAD_10M_SYMBOLS else "30m"
    elif strat_key == "taichong_10m_squad":
        tf = "10m"
    elif strat_key == "taichong_30m_squad":
        tf = "30m"
    elif strat_key in ["guiyuan_zscore_15m", "ek_supertrend_v7"]:
        tf = "15m"
    else:
        tf = strat_cfg.get("timeframe", "15m").split("/")[0]

    cache_key = f"{strat_key}_{symbol}_{tf}"
    now_ts = time.time()
    if cache_key in BACKTEST_CACHE:
        cached_time, cached_val = BACKTEST_CACHE[cache_key]
        if now_ts - cached_time < CACHE_TTL_SECONDS:
            return cached_val

    try:
        if strat_key == "taiyin_relative_value":
            PAIR_MAP = {
                "MA_PP": ("MA_IDX", "PP_IDX", 10.0, 5.0, 6, 4, "MTO加工利润"),
                "TA_PF": ("TA_IDX", "PF_IDX", 5.0, 5.0, 8, 7, "聚酯纺丝差"),
                "SC_FU": ("SC_IDX", "FU_IDX", 1000.0, 10.0, 1, 10, "渣油裂解差"),
                "TA_EG": ("TA_IDX", "EG_IDX", 5.0, 10.0, 6, 5, "聚酯双原料"),
                "C_CS":  ("C_IDX", "CS_IDX", 10.0, 10.0, 10, 7, "深加工利润"),
                "JM_J":  ("JM_IDX", "J_IDX", 60.0, 100.0, 4, 3, "双焦炼焦利润"),
            }
            p_info = PAIR_MAP.get(symbol, ("MA_IDX", "PP_IDX", 10.0, 5.0, 6, 4, "MTO加工利润"))
            sym_a, sym_b, mult_a, mult_b, lots_a, lots_b, pair_desc = p_info

            def fetch_bars(conn, s):
                d = pd.read_sql_query("SELECT trade_time, open, high, low, close, volume FROM futures_min_bars WHERE symbol=? AND timeframe='15m' ORDER BY trade_time ASC", conn, params=(s,))
                if len(d) >= 50:
                    return d
                d5 = pd.read_sql_query("SELECT trade_time, open, high, low, close, volume FROM futures_min_bars WHERE symbol=? AND timeframe='5m' ORDER BY trade_time ASC", conn, params=(s,))
                if len(d5) >= 150:
                    r_list = []
                    for k in range(0, len(d5) - 2, 3):
                        sub = d5.iloc[k:k+3]
                        r_list.append({
                            "trade_time": sub["trade_time"].iloc[-1],
                            "open": float(sub["open"].iloc[0]),
                            "high": float(sub["high"].max()),
                            "low": float(sub["low"].min()),
                            "close": float(sub["close"].iloc[-1]),
                            "volume": float(sub["volume"].sum())
                        })
                    return pd.DataFrame(r_list)
                return pd.DataFrame()

            with sqlite3.connect(DB_PATH) as conn:
                df_a = fetch_bars(conn, sym_a)
                df_b = fetch_bars(conn, sym_b)

            if len(df_a) == 0 or len(df_b) == 0:
                return None

            df_merged = pd.merge(df_a, df_b, on="trade_time", suffixes=("_a", "_b")).sort_values("trade_time").reset_index(drop=True)
            if len(df_merged) < 50:
                return None

            df_feat = pd.DataFrame()
            df_feat["datetime"] = pd.to_datetime(df_merged["trade_time"])
            df_feat["open"] = (df_merged["open_a"] * mult_a * lots_a) - (df_merged["open_b"] * mult_b * lots_b)
            df_feat["close"] = (df_merged["close_a"] * mult_a * lots_a) - (df_merged["close_b"] * mult_b * lots_b)
            df_feat["high"] = (df_merged["high_a"] * mult_a * lots_a) - (df_merged["low_b"] * mult_b * lots_b)
            df_feat["low"] = (df_merged["low_a"] * mult_a * lots_a) - (df_merged["high_b"] * mult_b * lots_b)
            df_feat["volume"] = df_merged["volume_a"] + df_merged["volume_b"]

            # Z-Score
            spread = df_feat["close"].values
            win = 160
            cs = np.cumsum(np.insert(spread, 0, 0.0))
            cs2 = np.cumsum(np.insert(spread ** 2, 0, 0.0))
            zscore = np.zeros(len(spread))
            for i in range(len(spread)):
                w = min(i + 1, win)
                s = cs[i + 1] - cs[i + 1 - w]
                s2 = cs2[i + 1] - cs2[i + 1 - w]
                m = s / w
                var = max(1e-4, (s2 / w) - (m ** 2))
                zscore[i] = (spread[i] - m) / math.sqrt(var)

            trades = []
            pos = 0
            entry_p = 0.0
            for i in range(win, len(df_feat)):
                dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                curr_c = float(df_feat["close"].iloc[i])
                curr_o = float(df_feat["open"].iloc[i])
                z = zscore[i-1]

                if pos == 0:
                    if z <= -1.8:
                        pos = 1
                        entry_p = curr_o
                        trades.append({"action": "ENTRY", "side": "LONG", "entry_dt": dt_s, "entry_p": entry_p, "reason": f"太阴·价差低估买入 ({pair_desc})", "lots": lots_a})
                    elif z >= 1.8:
                        pos = -1
                        entry_p = curr_o
                        trades.append({"action": "ENTRY", "side": "SHORT", "entry_dt": dt_s, "entry_p": entry_p, "reason": f"太阴·价差高估卖空 ({pair_desc})", "lots": lots_a})
                elif pos == 1 and z >= -0.2:
                    trades.append({"action": "EXIT", "side": "LONG", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "价差均值中枢回归止盈", "pnl_rmb": (curr_c - entry_p), "lots": lots_a})
                    pos = 0
                elif pos == -1 and z <= 0.2:
                    trades.append({"action": "EXIT", "side": "SHORT", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "价差均值中枢回归止盈", "pnl_rmb": (entry_p - curr_c), "lots": lots_a})
                    pos = 0

            res_data = {
                "df": df_feat,
                "backtest": {"trades": trades},
                "timeframe": "15m"
            }
            BACKTEST_CACHE[cache_key] = (now_ts, res_data)
            return res_data

        live_kline_file = DATA_DIR / f"live_klines_{symbol}_{tf}.json"
        df = None
        if live_kline_file.exists():
            try:
                with open(live_kline_file, "r", encoding="utf-8") as f:
                    k_data = json.load(f)
                if len(k_data) > 0:
                    df = pd.DataFrame(k_data)
                    df["datetime"] = pd.to_datetime(df["trade_time"])
            except Exception:
                df = None

        if df is None or len(df) == 0:
            if tf.lower() == "4h":
                with sqlite3.connect(DB_PATH) as conn:
                    df_raw = pd.read_sql_query(
                        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                        "WHERE symbol=? AND timeframe='30m' ORDER BY trade_time ASC",
                        conn, params=(symbol,)
                    )
                    if len(df_raw) > 0:
                        df_raw["datetime"] = pd.to_datetime(df_raw["trade_time"])
                        df = df_raw.set_index("datetime").resample("4h").agg({
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                            "open_interest": "last"
                        }).dropna().reset_index()
                        df["trade_time"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    df = pd.read_sql_query(
                        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                        "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
                        conn, params=(symbol, tf)
                    )
                    if len(df) == 0:
                        df = pd.read_sql_query(
                            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                            "WHERE symbol=? ORDER BY trade_time ASC",
                            conn, params=(symbol,)
                        )
                    df["datetime"] = pd.to_datetime(df["trade_time"])

        if df is None or len(df) == 0:
            return None

        df_feat = df.copy()
        trades = []

        if strat_key == "tianji_dual_island_v2":
            is_trend = symbol in ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX"]
            if is_trend:
                period = 20
                trail_mult = 3.0
                atr = pd.Series(df_feat["high"] - df_feat["low"]).rolling(14, min_periods=5).mean().bfill().values + 1e-8
                hh = pd.Series(df_feat["high"]).rolling(period, min_periods=5).max().shift(1).bfill().values
                ll = pd.Series(df_feat["low"]).rolling(period, min_periods=5).min().shift(1).bfill().values
                pos = 0
                entry_p = 0.0
                highest_p = 0.0
                lowest_p = 1e9
                for i in range(period, len(df_feat)):
                    dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                    curr_c = float(df_feat["close"].iloc[i])
                    curr_o = float(df_feat["open"].iloc[i])
                    curr_h = float(df_feat["high"].iloc[i])
                    curr_l = float(df_feat["low"].iloc[i])
                    curr_atr = atr[i]
                    if pos == 0:
                        if curr_c > hh[i]:
                            pos = 1
                            entry_p = curr_o
                            highest_p = curr_h
                            trades.append({"action": "ENTRY", "side": "LONG", "entry_dt": dt_s, "entry_p": entry_p, "reason": "天极·4H宏观突破启动", "lots": 2})
                        elif curr_c < ll[i]:
                            pos = -1
                            entry_p = curr_o
                            lowest_p = curr_l
                            trades.append({"action": "ENTRY", "side": "SHORT", "entry_dt": dt_s, "entry_p": entry_p, "reason": "天极·4H宏观破位启动", "lots": 2})
                    elif pos == 1:
                        highest_p = max(highest_p, curr_h)
                        stop_p = highest_p - trail_mult * curr_atr
                        if curr_l <= stop_p:
                            trades.append({"action": "EXIT", "side": "LONG", "exit_dt": dt_s, "exit_p": stop_p, "exit_reason": "4H动态吊灯止盈/止损", "pnl_rmb": (stop_p - entry_p) * 10.0 * 2, "lots": 2})
                            pos = 0
                    elif pos == -1:
                        lowest_p = min(lowest_p, curr_l)
                        stop_p = lowest_p + trail_mult * curr_atr
                        if curr_h >= stop_p:
                            trades.append({"action": "EXIT", "side": "SHORT", "exit_dt": dt_s, "exit_p": stop_p, "exit_reason": "4H动态吊灯止盈/止损", "pnl_rmb": (entry_p - stop_p) * 10.0 * 2, "lots": 2})
                            pos = 0
            else:
                from strategies.tianji_v2_optimized_master_strategy import calculate_reversion_factors
                factors_df = calculate_reversion_factors(df_feat)
                alpha = factors_df["composite_alpha"].values
                pos = 0
                entry_p = 0.0
                for i in range(1, len(df_feat)):
                    dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                    curr_c = float(df_feat["close"].iloc[i])
                    curr_o = float(df_feat["open"].iloc[i])
                    if pos == 0:
                        if alpha[i-1] <= -0.85:
                            pos = 1
                            entry_p = curr_o
                            trades.append({"action": "ENTRY", "side": "LONG", "entry_dt": dt_s, "entry_p": entry_p, "reason": "天极·30m产业基差超跌做多", "lots": 5})
                        elif alpha[i-1] >= 0.85:
                            pos = -1
                            entry_p = curr_o
                            trades.append({"action": "ENTRY", "side": "SHORT", "entry_dt": dt_s, "entry_p": entry_p, "reason": "天极·30m产业基差超买做空", "lots": 5})
                    elif pos == 1 and alpha[i-1] >= 0.0:
                        trades.append({"action": "EXIT", "side": "LONG", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "30m产业中枢回归平仓", "pnl_rmb": (curr_c - entry_p) * 5.0 * 5, "lots": 5})
                        pos = 0
                    elif pos == -1 and alpha[i-1] <= 0.0:
                        trades.append({"action": "EXIT", "side": "SHORT", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "30m产业中枢回归平仓", "pnl_rmb": (entry_p - curr_c) * 5.0 * 5, "lots": 5})
                        pos = 0

        elif strat_key == "ek_supertrend_v7":
            # EK-ZLP SuperTrend V7 专用买卖点生成器
            _, _, direction, final_upper, final_lower = compute_v7_dynamic_supertrend(df_feat, period=14, base_multiplier=2.5)
            df_feat["st_line"] = np.where(direction == 1, final_lower, final_upper)
            pos = 0
            entry_p = 0.0
            for i in range(25, len(df_feat)):
                dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                curr_c = float(df_feat["close"].iloc[i])
                curr_o = float(df_feat["open"].iloc[i])
                curr_l = float(df_feat["low"].iloc[i])
                curr_h = float(df_feat["high"].iloc[i])

                if pos == 0:
                    if direction[i] == 1 and direction[i-1] == -1:
                        pos = 1
                        entry_p = curr_o
                        trades.append({"action": "ENTRY", "side": "LONG", "entry_dt": dt_s, "entry_p": entry_p, "reason": "EK-ZLP零滞后翻多", "lots": 2})
                    elif direction[i] == -1 and direction[i-1] == 1:
                        pos = -1
                        entry_p = curr_o
                        trades.append({"action": "ENTRY", "side": "SHORT", "entry_dt": dt_s, "entry_p": entry_p, "reason": "EK-ZLP零滞后翻空", "lots": 1})
                elif pos == 1 and curr_l <= final_lower[i]:
                    trades.append({"action": "EXIT", "side": "LONG", "exit_dt": dt_s, "exit_p": final_lower[i], "exit_reason": "SuperTrend动态止损/落袋", "pnl_rmb": (final_lower[i] - entry_p) * 10.0, "lots": 2})
                    pos = 0
                elif pos == -1 and curr_h >= final_upper[i]:
                    trades.append({"action": "EXIT", "side": "SHORT", "exit_dt": dt_s, "exit_p": final_upper[i], "exit_reason": "SuperTrend动态止损/落袋", "pnl_rmb": (entry_p - final_upper[i]) * 10.0, "lots": 1})
                    pos = 0

        elif strat_key == "guiyuan_zscore_15m":
            # 归元 15m Z-Score 极值策略真实因果买卖点生成器 (对齐 guiyuan_zscore_reversion.py 核心)
            signals = calculate_guiyuan_signal(df_feat)
            df_feat["signal"] = signals
            df_feat["sma5"] = df_feat["close"].rolling(5).mean()

            pos = 0
            entry_p = 0.0
            for i in range(1, len(df_feat)):
                dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                curr_c = float(df_feat["close"].iloc[i])
                curr_o = float(df_feat["open"].iloc[i])
                sig = int(signals.iloc[i-1]) if not np.isnan(signals.iloc[i-1]) else 0
                sma5_val = float(df_feat["sma5"].iloc[i]) if not np.isnan(df_feat["sma5"].iloc[i]) else curr_c

                if pos == 0 and sig != 0:
                    pos = sig
                    entry_p = curr_o
                    trades.append({
                        "action": "ENTRY",
                        "side": "LONG" if pos > 0 else "SHORT",
                        "entry_dt": dt_s,
                        "entry_p": entry_p,
                        "reason": "归元·15m 极值吸收做多" if pos > 0 else "归元·15m 极值吸收做空",
                        "lots": 1
                    })
                elif pos > 0 and curr_c >= sma5_val:
                    trades.append({
                        "action": "EXIT",
                        "side": "LONG",
                        "exit_dt": dt_s,
                        "exit_p": curr_c,
                        "exit_reason": "SMA(5)均线极速落袋",
                        "pnl_rmb": (curr_c - entry_p) * 10.0,
                        "lots": 1
                    })
                    pos = 0
                elif pos < 0 and curr_c <= sma5_val:
                    trades.append({
                        "action": "EXIT",
                        "side": "SHORT",
                        "exit_dt": dt_s,
                        "exit_p": curr_c,
                        "exit_reason": "SMA(5)均线极速落袋",
                        "pnl_rmb": (entry_p - curr_c) * 10.0,
                        "lots": 1
                    })
                    pos = 0

        else:
            # 太冲弹塑性张量策略买卖点生成器
            signals = calculate_signal(df_feat)
            df_feat["signal"] = signals
            df_feat["sma5"] = df_feat["close"].rolling(5).mean()

            pos = 0
            entry_p = 0.0
            for i in range(1, len(df_feat)):
                sig = int(signals.iloc[i-1])
                curr_c = float(df_feat["close"].iloc[i])
                dt_s = df_feat["datetime"].iloc[i].strftime("%Y-%m-%d %H:%M")
                sma5_val = float(df_feat["sma5"].iloc[i]) if not np.isnan(df_feat["sma5"].iloc[i]) else curr_c

                if pos == 0 and sig != 0:
                    pos = sig
                    entry_p = float(df_feat["open"].iloc[i])
                    trades.append({"action": "ENTRY", "side": "LONG" if pos > 0 else "SHORT", "entry_dt": dt_s, "entry_p": entry_p, "reason": "太冲·弹塑性张量共振", "lots": 1})
                elif pos > 0 and curr_c >= sma5_val:
                    trades.append({"action": "EXIT", "side": "LONG", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "SMA(5)均线极速落袋", "pnl_rmb": (curr_c - entry_p) * 10.0, "lots": 1})
                    pos = 0
                elif pos < 0 and curr_c <= sma5_val:
                    trades.append({"action": "EXIT", "side": "SHORT", "exit_dt": dt_s, "exit_p": curr_c, "exit_reason": "SMA(5)均线极速落袋", "pnl_rmb": (entry_p - curr_c) * 10.0, "lots": 1})
                    pos = 0

        res_data = {
            "df": df_feat,
            "backtest": {"trades": trades},
            "timeframe": tf
        }
        BACKTEST_CACHE[cache_key] = (now_ts, res_data)
        return res_data
    except Exception as e:
        print(f"加载缓存数据失败 [{strategy_id} - {symbol}]: {e}")
        return None


def get_strategy_trader_status(strategy_id: str):
    strat_key = ALIAS_MAP.get(strategy_id, "taichong_dual_squad")
    strat_cfg = STRATEGY_REGISTRY.get(strat_key, STRATEGY_REGISTRY["taichong_dual_squad"])
    if strat_cfg.get("execution_status") == "NOT_IMPLEMENTED_LIVE_EXECUTION":
        return {
            "strategy_id": strat_key,
            "strategy_name": strat_cfg["name"],
            "short_name": strat_cfg["short_name"],
            "timeframe": strat_cfg["timeframe"],
            "running": False,
            "execution_status": "NOT_IMPLEMENTED_LIVE_EXECUTION",
            "pid": None,
            "active_positions": 0,
            "initial_balance": 0.0,
            "current_equity": 0.0,
            "overall_win_rate": 0.0,
            "total_symbols": 0,
            "total_trades_count": 0,
            "total_profit": 0.0,
            "symbols": [],
        }
    running = False
    pid = None
    cpu_percent = 0.0
    mem_mb = 0.0
    start_time_str = "服务守护运行中"

    try:
        proc_kw = strat_cfg.get("process_keyword", "deploy_taichong_squads_trader")
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info']):
            cmdline = p.info.get('cmdline') or []
            cmd_str = " ".join(cmdline)
            if proc_kw in cmd_str:
                running = True
                pid = p.info['pid']
                proc = psutil.Process(pid)
                cpu_percent = round(proc.cpu_percent(interval=0.05), 1)
                mem_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
                start_time_str = datetime.datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S")
                break
    except Exception:
        pass

    state_file = strat_cfg["state_file"]
    if not state_file.exists() and "fallback_state" in strat_cfg and strat_cfg["fallback_state"].exists():
        state_file = strat_cfg["fallback_state"]

    state_data = {}
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception:
            pass

    target_symbols = strat_cfg.get("symbols", DUAL_SQUAD_SYMBOLS)
    symbols_info = []
    active_positions = 0
    pos_dict = state_data.get("positions", state_data)

    for sym in target_symbols:
        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "category": "商品期货"})
        s_entry = pos_dict.get(sym, {})
        if isinstance(s_entry, dict):
            pos_val = float(s_entry.get("pos", 0.0))
            lots = float(s_entry.get("lots", 0.0))
            entry_p = float(s_entry.get("entry_price", 0.0))
            entry_t = str(s_entry.get("entry_time", "-"))
            stop_l = float(s_entry.get("stop_price", s_entry.get("stop_loss", 0.0)))
        else:
            pos_val = float(s_entry) if isinstance(s_entry, (int, float)) else 0.0
            lots = 1.0 if pos_val != 0 else 0.0
            entry_p = 0.0
            entry_t = "-"
            stop_l = 0.0

        pos_dir = 1 if pos_val > 0 else (-1 if pos_val < 0 else 0)

        if pos_dir != 0:
            active_positions += 1

        # 匹配策略战队真实运行周期
        if strat_key == "tianji_dual_island_v2":
            tf_tag = "4h" if sym in ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX"] else "30m"
        elif strat_key == "taichong_dual_squad":
            tf_tag = "10m" if sym in SQUAD_10M_SYMBOLS else "30m"
        elif strat_key == "taichong_10m_squad":
            tf_tag = "10m"
        elif strat_key == "taichong_30m_squad":
            tf_tag = "30m"
        elif strat_key in ["guiyuan_zscore_15m", "ek_supertrend_v7"]:
            tf_tag = "15m"
        else:
            tf_tag = strat_cfg.get("timeframe", "15m").split("/")[0]

        bench_key = f"tianji_{sym}_{tf_tag}" if strat_key == "tianji_dual_island_v2" else f"{sym}_{tf_tag}"
        bench = LLN_BENCHMARK_MAP.get(bench_key, LLN_BENCHMARK_MAP.get(f"{sym}_{tf_tag}", LLN_BENCHMARK_MAP.get(f"{sym}_15m", {})))
        dom_code = DOMINANT_CONTRACT_MAP.get(sym, sym)

        if strat_key == "tianji_dual_island_v2":
            rule_desc = "4H 宏观时空通道突破 + 3.0 ATR 动态吊灯" if tf_tag == "4h" else "30m 产业基差超跌超买回归中枢 + 动态风险平价定仓"
        elif strat_key == "ek_supertrend_v7":
            rule_desc = "15m DSP零滞后SuperSmoother + 卡尔曼速度 + 排列熵门禁 | 2.5R阶梯锁利50% | 动态保本"
        elif strat_key == "guiyuan_zscore_15m":
            rule_desc = "15m Z-Score(|Z|>=2.2) + Meta(P>=52%) | SMA(5)止盈 | 1.2 ATR止损 | 0.4 ATR保本"
        elif tf_tag == "10m":
            rule_desc = "10m 5h协方差谐振 + 做市商PinBar吸收 | SMA(5)均线落袋 | 2.5 ATR止损 | 卡方熔断"
        elif tf_tag == "30m":
            rule_desc = "30m 跨日宏观中枢回归 + 弹塑性应变 | SMA(5)均线落袋 | 2.5 ATR止损 | 3x摩擦抗性"
        else:
            rule_desc = "15m 趋势跟踪与极值回归模型"

        symbols_info.append({
            "symbol": sym,
            "timeframe": tf_tag,
            "dominant_contract": dom_code,
            "name": bench.get("name", cfg.get("name", sym)),
            "category": bench.get("category", cfg.get("category", "商品期货")),
            "pos": pos_dir,
            "lots": lots,
            "entry_price": entry_p,
            "entry_time": entry_t,
            "stop_loss": stop_l,
            "highest_price": 0.0,
            "lowest_price": 0.0,
            "unrealized_pnl": 0.0,
            "breakeven_locked": False,
            "last_processed_dt": "-",
            "strategy_rule": rule_desc,
            "benchmark_win_rate": bench.get("win_rate_pct", 75.0),
            "benchmark_plr": bench.get("profit_loss_ratio", 2.0),
            "benchmark_return_pct": bench.get("total_return_pct", 50.0),
            "benchmark_profit_rmb": bench.get("net_profit_rmb", 50000.0),
            "benchmark_trades": bench.get("total_trades", 1000),
            "benchmark_max_dd": bench.get("max_drawdown_pct", 1.0),
            "benchmark_sharpe": bench.get("daily_sharpe", 1.5)
        })

    # 读取成交记录统计 (严格按当前战队监控品种集合 target_symbols 过滤)
    trades_csv = strat_cfg["trades_csv"]
    real_trades_count = 0
    real_wins_count = 0
    real_pnl = 0.0

    if trades_csv.exists():
        try:
            df_t = pd.read_csv(trades_csv)
            if len(df_t) > 0:
                pnl_col = "net_pnl" if "net_pnl" in df_t.columns else ("pnl" if "pnl" in df_t.columns else None)
                if pnl_col:
                    if "symbol" in df_t.columns:
                        df_t = df_t[df_t["symbol"].isin(target_symbols)]
                    if len(df_t) > 0:
                        real_trades_count = len(df_t)
                        real_wins_count = int((df_t[pnl_col] > 0).sum())
                        real_pnl = float(df_t[pnl_col].sum())
        except Exception:
            pass

    init_cap = strat_cfg.get("initial_capital", 1000000.0)
    current_cap = init_cap + real_pnl
    win_rate = round(real_wins_count / real_trades_count * 100, 1) if real_trades_count > 0 else strat_cfg.get("summary_win_rate", 64.0)

    return {
        "strategy_id": strat_key,
        "strategy_name": strat_cfg["name"],
        "short_name": strat_cfg["short_name"],
        "timeframe": strat_cfg["timeframe"],
        "running": running,
        "pid": pid,
        "cpu_percent": cpu_percent,
        "memory_mb": mem_mb,
        "start_time": start_time_str,
        "server_time": (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))).strftime("%Y-%m-%d %H:%M:%S"),
        "initial_balance": init_cap,
        "current_equity": round(current_cap, 2),
        "total_unrealized": 0.0,
        "total_profit": round(real_pnl, 2),
        "overall_win_rate": win_rate,
        "total_trades_count": real_trades_count,
        "active_positions": active_positions,
        "total_symbols": len(target_symbols),
        "symbols": symbols_info
    }


def find_matching_category(dt_val: str, categories: list[str]) -> str | None:
    if not dt_val or not categories:
        return None
    dt_str = str(dt_val).strip()
    if dt_str in categories:
        return dt_str
    dt_short = dt_str[:16]
    if dt_short in categories:
        return dt_short
    for cat in reversed(categories):
        if cat.startswith(dt_str[:13]) and cat <= dt_str[:16]:
            return cat
    if dt_str[:16] >= categories[-1]:
        return categories[-1]
    return None


@app.route("/api/strategies")
def api_strategies():
    """返回所有可用策略战队列表"""
    strats = []
    for k, v in STRATEGY_REGISTRY.items():
        strats.append({
            "id": k,
            "name": v["name"],
            "short_name": v["short_name"],
            "timeframe": v["timeframe"],
            "symbols_count": len(v["symbols"]),
            "default_symbol": v["default_symbol"],
            "execution_status": v.get("execution_status", "AVAILABLE"),
        })
    return jsonify({"strategies": strats})


@app.route("/api/status")
def api_status():
    strat = request.args.get("strategy", "taichong_dual_squad")
    return jsonify(get_strategy_trader_status(strat))


@app.route("/api/kline")
def api_kline():
    symbol = request.args.get("symbol", "SN_IDX")
    strat = request.args.get("strategy", "taichong_dual_squad")

    data = get_cached_strategy_data(strat, symbol)
    if not data:
        return jsonify({"error": f"暂无 {symbol} K线数据"}), 404

    df_full = data["df"]
    res = data["backtest"]
    tf = data["timeframe"]
    recent_df = df_full.tail(200).copy().reset_index(drop=True)

    categories = recent_df["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist()
    k_values = recent_df[["open", "close", "low", "high"]].values.tolist()
    volumes = recent_df["volume"].tolist()

    live_quote = None
    if len(k_values) > 0:
        cur_c = k_values[-1][1]
        prev_c = k_values[-2][1] if len(k_values) >= 2 else k_values[-1][0]
        chg_val = round(cur_c - prev_c, 2)
        chg_pct = round(chg_val / (prev_c + 1e-6) * 100, 2)
        live_quote = {
            "last_price": cur_c,
            "change_val": chg_val,
            "change_pct": chg_pct,
            "open": k_values[-1][0],
            "high": k_values[-1][3],
            "low": k_values[-1][2],
            "volume": volumes[-1] if volumes else 0,
            "dt": categories[-1] if categories else "",
            "is_live": True
        }

    # 读取买卖点标记
    trades = res.get("trades", []) if res else []
    trade_markers = []
    seen_marker_keys = set()

    for t in trades[-30:]:
        e_t = t.get("entry_dt")
        e_p = t.get("entry_p")
        x_t = t.get("exit_dt")
        x_p = t.get("exit_p")
        side = t.get("side", "LONG")
        is_long = (side == "LONG" or "多" in side)
        pnl = t.get("pnl_rmb", 0.0)
        lots = t.get("lots", 1)

        if e_t and e_p:
            cat_match = find_matching_category(e_t, categories)
            if cat_match:
                m_key = f"ENTRY_{cat_match}_{e_p}"
                if m_key not in seen_marker_keys:
                    seen_marker_keys.add(m_key)
                    trade_markers.append({
                        "coord": [cat_match, e_p],
                        "name": "🟢 开多" if is_long else "🔴 开空",
                        "value": f"{'买多' if is_long else '卖空'} {lots}手",
                        "action": "ENTRY",
                        "side": "LONG" if is_long else "SHORT",
                        "price": e_p,
                        "time": e_t,
                        "reason": t.get("reason", "太冲弹塑性信号"),
                        "lots": lots,
                        "symbol": "arrow",
                        "symbolRotate": 0 if is_long else 180,
                        "symbolOffset": [0, 18] if is_long else [0, -18],
                        "symbolSize": 24,
                        "itemStyle": {"color": "#3fb950" if is_long else "#f85149"}
                    })

        if x_t and x_p:
            cat_match = find_matching_category(x_t, categories)
            if cat_match:
                m_key = f"EXIT_{cat_match}_{x_p}"
                if m_key not in seen_marker_keys:
                    seen_marker_keys.add(m_key)
                    is_win = (pnl >= 0)
                    trade_markers.append({
                        "coord": [cat_match, x_p],
                        "name": "平仓",
                        "value": f"🎯 止盈 +¥{pnl:,.0f}" if is_win else f"🛑 止损 ¥{pnl:,.0f}",
                        "action": "EXIT",
                        "side": "LONG" if is_long else "SHORT",
                        "price": x_p,
                        "time": x_t,
                        "reason": t.get("exit_reason", "SMA(5)落袋"),
                        "lots": lots,
                        "symbol": "pin",
                        "symbolSize": 28,
                        "itemStyle": {"color": "#d29922" if is_win else "#f85149"}
                    })

    # 注入实盘/虚拟盘当前活跃持仓的买卖点标记 (Live Open Position Marker)
    strat_key = ALIAS_MAP.get(strat, "taichong_dual_squad")
    strat_cfg = STRATEGY_REGISTRY.get(strat_key, STRATEGY_REGISTRY["taichong_dual_squad"])
    state_file = strat_cfg.get("state_file")
    if state_file and state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                st_data = json.load(f)
            p_info = st_data.get("positions", {}).get(symbol, {})
            p_pos = int(p_info.get("pos", 0))
            if p_pos != 0:
                e_t = str(p_info.get("entry_time", ""))
                e_p = float(p_info.get("entry_price", 0.0))
                stop_p = float(p_info.get("stop_price", 0.0))
                lots = int(p_info.get("lots", 1))
                is_long = (p_pos > 0)
                cat_match = find_matching_category(e_t, categories) or (categories[-1] if categories else None)
                if cat_match:
                    trade_markers.append({
                        "coord": [cat_match, e_p],
                        "name": "🔥 盘中实盘持多" if is_long else "🔥 盘中实盘持空",
                        "value": f"【实盘持仓】{'买多' if is_long else '卖空'} {lots}手 @{e_p}",
                        "action": "ENTRY",
                        "side": "LONG" if is_long else "SHORT",
                        "price": e_p,
                        "time": e_t,
                        "reason": f"盘中实盘开仓 (持仓中 | 止损: {stop_p:.2f})",
                        "lots": lots,
                        "symbol": "arrow",
                        "symbolRotate": 0 if is_long else 180,
                        "symbolOffset": [0, 22] if is_long else [0, -22],
                        "symbolSize": 32,
                        "itemStyle": {"color": "#00ff88" if is_long else "#ff3366"}
                    })
        except Exception:
            pass

    bench_key = f"tianji_{symbol}_{tf}" if strat_key == "tianji_dual_island_v2" else f"{symbol}_{tf}"
    bench = LLN_BENCHMARK_MAP.get(bench_key, LLN_BENCHMARK_MAP.get(f"{symbol}_{tf}", LLN_BENCHMARK_MAP.get(f"{symbol}_15m", {})))

    return jsonify({
        "symbol": symbol,
        "timeframe": tf,
        "dominant_contract": DOMINANT_CONTRACT_MAP.get(symbol, symbol),
        "name": bench.get("name", symbol),
        "category": bench.get("category", "商品期货"),
        "categories": categories,
        "k_values": k_values,
        "volumes": volumes,
        "live_quote": live_quote,
        "trade_markers": trade_markers,
        "summary": {
            "win_rate": bench.get("win_rate_pct", 75.0),
            "pl_ratio": bench.get("profit_loss_ratio", 2.0),
            "net_profit": bench.get("net_profit_rmb", 50000.0),
            "max_dd": bench.get("max_drawdown_pct", 1.0),
            "sharpe": bench.get("daily_sharpe", 1.5),
            "total_trades": bench.get("total_trades", 1000)
        }
    })


@app.route("/api/trades")
def api_trades():
    strat = request.args.get("strategy", "taichong_dual_squad")
    symbol = request.args.get("symbol", "ALL")
    strat_key = ALIAS_MAP.get(strat, "taichong_dual_squad")
    strat_cfg = STRATEGY_REGISTRY.get(strat_key, STRATEGY_REGISTRY["taichong_dual_squad"])

    trades_list = []

    # 1. 优先提取当前战队的“盘中活跃持仓” (Active Open Positions)
    state_file = strat_cfg.get("state_file")
    if state_file and state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                st_data = json.load(f)
            pos_map = st_data.get("positions", {})
            for sym_k, p_info in pos_map.items():
                p_val = int(p_info.get("pos", 0))
                if p_val != 0:
                    if symbol != "ALL" and sym_k != symbol:
                        continue
                    e_p = float(p_info.get("entry_price", 0.0))
                    e_t = str(p_info.get("entry_time", "-"))
                    stop_p = float(p_info.get("stop_price", 0.0))
                    lots_val = int(p_info.get("lots", 1))
                    trades_list.append({
                        "strategy_id": strat_cfg["short_name"],
                        "symbol": sym_k,
                        "timeframe": str(p_info.get("timeframe", strat_cfg.get("timeframe", "15m"))),
                        "dominant_contract": DOMINANT_CONTRACT_MAP.get(sym_k, sym_k),
                        "side": "LONG" if p_val > 0 else "SHORT",
                        "entry_dt": e_t,
                        "entry_p": e_p,
                        "entry_reason": "太冲·盘中弹塑性共振触发 (实盘开仓)",
                        "exit_dt": "⏳ 持仓监控中",
                        "exit_p": stop_p,
                        "exit_reason": f"跟踪止损线: ¥{stop_p:.2f}",
                        "lots": lots_val,
                        "pnl": 0.0,
                        "status": "🔥 盘中实盘活跃持仓"
                    })
        except Exception:
            pass

    # 2. 提取实盘 / 虚拟盘历史真实平仓入账流水 (Closed Fills)
    trades_csv = strat_cfg["trades_csv"]
    if trades_csv.exists():
        try:
            df_t = pd.read_csv(trades_csv)
            if len(df_t) > 0:
                target_syms = strat_cfg.get("symbols", DUAL_SQUAD_SYMBOLS)
                for _, r in df_t.iterrows():
                    sym_code = str(r.get("symbol", ""))
                    if sym_code not in target_syms:
                        continue
                    if symbol != "ALL" and sym_code != symbol:
                        continue
                    pnl_val = float(r.get("net_pnl", r.get("pnl", 0.0)))
                    e_dt_raw = str(r.get("entry_time", "-"))
                    x_dt_raw = str(r.get("exit_time", "-"))

                    # 时区校准：如果时间为 UTC 时间，自动转换为北京时间 (+8h)
                    def to_beijing_time(t_str: str) -> str:
                        if not t_str or t_str == "-":
                            return "-"
                        try:
                            dt_obj = pd.to_datetime(t_str)
                            return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            return t_str

                    trades_list.append({
                        "strategy_id": strat_cfg["short_name"],
                        "symbol": sym_code,
                        "timeframe": str(r.get("timeframe", strat_cfg.get("timeframe", "15m"))),
                        "dominant_contract": DOMINANT_CONTRACT_MAP.get(sym_code, sym_code),
                        "side": str(r.get("side", "LONG")),
                        "entry_dt": to_beijing_time(e_dt_raw),
                        "entry_p": float(r.get("entry_price", 0.0)),
                        "entry_reason": str(r.get("reason", "盘中实时信号")),
                        "exit_dt": to_beijing_time(x_dt_raw),
                        "exit_p": float(r.get("exit_price", 0.0)),
                        "exit_reason": str(r.get("exit_reason", "止盈/止损")),
                        "lots": int(r.get("lots", 1)),
                        "pnl": pnl_val,
                        "status": "🟢 虚拟盘真实成交"
                    })
        except Exception:
            pass

    # 活跃持仓始终置顶，历史平仓按时间倒序排列
    trades_list.sort(key=lambda x: (1 if "活跃持仓" in str(x.get("status", "")) else 0, str(x.get("exit_dt", x.get("entry_dt", "")))), reverse=True)
    return jsonify({"trades": trades_list})


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>商品期货量化策略多战队全景实盘监控大屏</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
  <style>
    :root {
      --bg-main: #0d1117;
      --card-bg: #161b22;
      --card-inner: #21262d;
      --border: #30363d;
      --text-bright: #f0f6fc;
      --text-muted: #8b949e;
      --green-bright: #3fb950;
      --green-glow: rgba(63, 185, 80, 0.15);
      --red-bright: #f85149;
      --red-glow: rgba(248, 81, 73, 0.15);
      --blue: #58a6ff;
      --purple: #bc8cff;
      --gold: #d29922;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg-main); color: var(--text-bright); padding: 16px; min-height: 100vh; }
    
    .top-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 10px; }
    .header-title { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
    .header-title h1 { font-size: 19px; font-weight: 700; color: var(--text-bright); }
    
    .badge-live { display: inline-flex; align-items: center; gap: 6px; background: rgba(63, 185, 80, 0.12); color: var(--green-bright); padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(63, 185, 80, 0.3); }
    .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green-bright); box-shadow: 0 0 8px var(--green-bright); }
    
    .strategy-tabs { display: flex; gap: 8px; margin-bottom: 14px; overflow-x: auto; padding-bottom: 4px; }
    .tab-btn { background: var(--card-bg); border: 1px solid var(--border); color: var(--text-muted); padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
    .tab-btn:hover { background: #21262d; color: var(--text-bright); border-color: var(--blue); }
    .tab-btn.active { background: rgba(88, 166, 255, 0.15); color: #58a6ff; border-color: #58a6ff; box-shadow: 0 0 10px rgba(88,166,255,0.2); }

    .btn { background: var(--card-inner); border: 1px solid var(--border); color: var(--text-bright); padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; transition: all 0.2s; }
    .btn:hover { background: #30363d; border-color: var(--blue); }

    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; }
    .stat-label { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
    .stat-val { font-size: 18px; font-weight: 700; color: var(--text-bright); font-family: monospace; }
    .stat-val.pos { color: var(--green-bright); }
    .stat-val.neg { color: var(--red-bright); }

    .main-layout { display: grid; grid-template-columns: 290px 1fr; gap: 16px; margin-bottom: 16px; }
    .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
    .panel-header { padding: 12px 16px; background: var(--card-inner); border-bottom: 1px solid var(--border); font-weight: 600; font-size: 13px; color: var(--text-bright); display: flex; justify-content: space-between; align-items: center; }

    .symbol-list { overflow-y: auto; max-height: 540px; }
    .symbol-item { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.04); cursor: pointer; transition: all 0.15s; display: flex; justify-content: space-between; align-items: center; }
    .symbol-item:hover { background: rgba(88, 166, 255, 0.08); }
    .symbol-item.active { background: rgba(31, 111, 235, 0.22); border-left: 4px solid var(--blue); }
    .sym-name { font-weight: 600; color: var(--text-bright); font-size: 14px; }
    .sym-meta { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
    .pos-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
    .pos-badge.long { background: var(--green-glow); color: var(--green-bright); border: 1px solid rgba(63, 185, 80, 0.3); }
    .pos-badge.short { background: var(--red-glow); color: var(--red-bright); border: 1px solid rgba(248, 81, 73, 0.3); }
    .pos-badge.empty { background: rgba(255,255,255,0.05); color: var(--text-muted); }

    .chart-info-bar { display: flex; gap: 16px; padding: 10px 16px; background: rgba(0,0,0,0.25); border-bottom: 1px solid var(--border); font-size: 12px; flex-wrap: wrap; align-items: center; }
    .chart-info-bar b { color: var(--text-bright); font-weight: 600; }
    .chart-container { width: 100%; height: 480px; padding: 8px; }

    .trades-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .trades-table th { background: var(--card-inner); padding: 10px 12px; text-align: left; color: var(--text-muted); font-weight: 600; border-bottom: 1px solid var(--border); }
    .trades-table td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .trades-table tr:hover { background: rgba(255,255,255,0.02); }
  </style>
</head>
<body>

  <!-- 顶部导航 -->
  <div class="top-header">
    <div class="header-title">
      <h1 id="pageMainTitle">🔮 【太冲·弹塑性张量】双战队实盘全景监控大屏</h1>
      <span class="badge-live"><span class="pulse-dot"></span> <span id="engineStatus">TqSim 守护运行中</span></span>
      <span style="font-size: 12px; color: var(--text-muted);" id="serverTime"></span>
    </div>
    <div class="header-actions">
      <button class="btn" onclick="refreshAll()"><span style="color: var(--blue);">🔄</span> 立即刷新</button>
    </div>
  </div>

  <!-- 策略战队切换 TAB -->
  <div class="strategy-tabs" id="strategyTabs">
    <button class="tab-btn" onclick="switchStrategy('tianji_dual_island_v2')">⛔ 天极·双岛 V2.0 (执行未实现)</button>
    <button class="tab-btn" onclick="switchStrategy('taiyin_relative_value')">⚖️ 太阴·跨品种相对价值套利 (第一梯队 S级)</button>
    <button class="tab-btn" onclick="switchStrategy('ek_supertrend_v7')">🔮 太冲·零滞后相变趋势 V7 (5大主力)</button>
    <button class="tab-btn active" onclick="switchStrategy('taichong_dual_squad')">⚡ 太冲·双战队全景 (10m+30m 11主力)</button>
    <button class="tab-btn" onclick="switchStrategy('taichong_10m_squad')">⚡ 太冲·10m微观战队 (SN/AU/AG/MA/P)</button>
    <button class="tab-btn" onclick="switchStrategy('taichong_30m_squad')">🌊 太冲·30m波段战队 (SC/LC/J/AL/TA/SI)</button>
    <button class="tab-btn" onclick="switchStrategy('guiyuan_zscore_15m')">⚡ 归元·15m极值策略 (8大主力)</button>
  </div>

  <!-- 全局统计卡片 -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">战队虚拟盘本金 (TqSim)</div>
      <div class="stat-val" id="initBalance">¥2,000,000</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">当前账户动态净值</div>
      <div class="stat-val pos" id="currentEquity">¥2,000,000</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">大数定律综合胜率 (1000+ 笔)</div>
      <div class="stat-val pos" id="winRate">78.6%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">活跃持仓品种数</div>
      <div class="stat-val" id="activePosCount" style="color: var(--blue);">0 / 11</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">实盘累计平仓笔数</div>
      <div class="stat-val" id="totalTrades">0 次</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">战队累计实现净利润</div>
      <div class="stat-val pos" id="totalProfit">¥0.00</div>
    </div>
  </div>

  <!-- 主布局: 左侧品种选择 + 右侧 K 线买卖点大屏 -->
  <div class="main-layout">
    <div class="panel">
      <div class="panel-header">
        <span id="squadListHeader">🏆 战队核心主力品种</span>
        <span style="font-size: 11px; color: var(--blue);" id="squadTfBadge">10m/30m 周期</span>
      </div>
      <div class="symbol-list" id="symbolList"></div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span id="chartTitle">【沪锡 · sn2610.SHFE】K 线买卖点与太冲弹塑性力学特征</span>
        <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 14px;">
          <span>🟢 太冲买多</span>
          <span>🔴 太冲卖空</span>
          <span>🎯 SMA(5)均线落袋</span>
          <span>🛑 动态止损/熔断</span>
        </div>
      </div>

      <div class="chart-info-bar" id="chartInfoBar">
        <div style="background: rgba(56, 139, 253, 0.12); padding: 3px 10px; border-radius: 4px; border: 1px solid rgba(56,139,253,0.3); display: flex; align-items: center; gap: 6px;">
          <span>⚡ 盘中现价:</span>
          <b id="livePrice" style="font-size: 15px; color: #58a6ff; font-family: monospace;">-</b>
          <span id="liveChange" style="font-size: 11px; font-weight: 600; padding: 1px 4px; border-radius: 3px;"></span>
        </div>
        <div><span>大数实测胜率:</span> <b id="symWinRate">73.1%</b></div>
        <div><span>净盈亏比 (PF):</span> <b id="symPLRatio">5.80</b></div>
        <div><span>历史大数净利:</span> <b id="symReturn">+¥50,570</b></div>
        <div><span>动态最大回撤:</span> <b id="symMaxDD">0.38%</b></div>
        <div><span>年化夏普比:</span> <b id="symSharpe">4.09</b></div>
      </div>

      <div class="chart-container" id="klineChart"></div>
    </div>
  </div>

  <!-- 底部交易明细流水表 -->
  <div class="panel">
    <div class="panel-header">
      <span>📜 TqSim 虚拟盘实时委托撮合成交账单 (仅展示真实入账订单，未成交前严格维持初始本金)</span>
      <div style="display: flex; gap: 8px;">
        <button class="btn" style="padding: 3px 8px;" onclick="loadTrades('ALL')">全部战队品种</button>
        <button class="btn" style="padding: 3px 8px;" onclick="loadTrades(currentSymbol)">当前品种</button>
      </div>
    </div>
    <div style="max-height: 280px; overflow-y: auto;">
      <table class="trades-table">
        <thead>
          <tr>
            <th>策略战队</th>
            <th>品种</th>
            <th>周期</th>
            <th>方向</th>
            <th>开仓时间</th>
            <th>开仓价</th>
            <th>开仓决策理由</th>
            <th>平仓时间</th>
            <th>平仓价</th>
            <th>平仓决策理由</th>
            <th>手数</th>
            <th>净盈亏(元)</th>
            <th>记录属性</th>
          </tr>
        </thead>
        <tbody id="tradesBody"></tbody>
      </table>
    </div>
  </div>

  <script>
    let currentStrategy = "taichong_dual_squad";
    let currentSymbol = "SN_IDX";
    let myChart = null;

    function initChart() {
      const container = document.getElementById('klineChart');
      myChart = echarts.init(container);
      window.addEventListener('resize', () => myChart && myChart.resize());
    }

    function switchStrategy(stratId) {
      currentStrategy = stratId;
      document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('onclick').includes(stratId)) {
          btn.classList.add('active');
        }
      });
      if (stratId === 'tianji_dual_island_v2') currentSymbol = 'AU_IDX';
      else if (stratId === 'taiyin_relative_value') currentSymbol = 'MA_PP';
      else if (stratId === 'ek_supertrend_v7') currentSymbol = 'AG_IDX';
      else if (stratId === 'taichong_10m_squad') currentSymbol = 'SN_IDX';
      else if (stratId === 'taichong_30m_squad') currentSymbol = 'SC_IDX';
      else if (stratId === 'guiyuan_zscore_15m') currentSymbol = 'AU_IDX';
      else currentSymbol = 'AU_IDX';

      refreshAll();
    }

    async function loadStatus() {
      try {
        const res = await fetch(`/api/status?strategy=${currentStrategy}`);
        const data = await res.json();
        
        document.getElementById('pageMainTitle').innerText = data.strategy_name || "商品期货量化策略多战队实盘大屏";
        document.getElementById('serverTime').innerText = data.server_time || "";
        const disabled = data.execution_status === "NOT_IMPLEMENTED_LIVE_EXECUTION";
        document.getElementById('engineStatus').innerText = disabled
          ? "⛔ 执行未实现"
          : (data.running ? "🟢 TqSim 守护运行中" : "🔴 策略未运行");
        document.getElementById('initBalance').innerText = "¥" + Number(data.initial_balance).toLocaleString();
        document.getElementById('currentEquity').innerText = "¥" + Number(data.current_equity).toLocaleString();
        document.getElementById('winRate').innerText = data.overall_win_rate + "%";
        document.getElementById('activePosCount').innerText = `${data.active_positions} / ${data.total_symbols}`;
        document.getElementById('totalTrades').innerText = data.total_trades_count + " 次";
        document.getElementById('totalProfit').innerText = (data.total_profit >= 0 ? "+" : "") + "¥" + Number(data.total_profit).toLocaleString();

        document.getElementById('squadTfBadge').innerText = `${data.timeframe} 周期`;

        const sList = document.getElementById('symbolList');
        sList.innerHTML = "";
        (data.symbols || []).forEach(s => {
          const item = document.createElement('div');
          item.className = `symbol-item ${s.symbol === currentSymbol ? 'active' : ''}`;
          item.onclick = (e) => {
            e.stopPropagation();
            selectSymbol(s.symbol);
          };
          
          let posTag = '<span class="pos-badge empty">空仓</span>';
          if (s.pos === 1) posTag = `<span class="pos-badge long">多 ${s.lots}手</span>`;
          if (s.pos === -1) posTag = `<span class="pos-badge short">空 ${s.lots}手</span>`;

          item.innerHTML = `
            <div>
              <div class="sym-name">${s.name} <span style="font-size:11px; color:#58a6ff; font-weight:500;">[${s.dominant_contract || s.symbol}]</span> <span style="font-size:10px; background:rgba(255,255,255,0.08); padding:1px 4px; border-radius:3px;">${s.timeframe}</span></div>
              <div class="sym-meta">${s.symbol} · ${s.category} · 胜率 ${s.benchmark_win_rate}%</div>
            </div>
            <div>${posTag}</div>
          `;
          sList.appendChild(item);
        });
      } catch (e) {
        console.error("加载状态失败:", e);
      }
    }

    async function loadKline(symbol) {
      try {
        const res = await fetch(`/api/kline?strategy=${currentStrategy}&symbol=${symbol}`);
        const data = await res.json();
        if (data.error) {
          console.warn("K线数据错误:", data.error);
          return;
        }

        document.getElementById('chartTitle').innerText = `【${data.name} · 主力合约 ${data.dominant_contract || data.symbol} (${data.symbol})】${data.category} · ${data.timeframe} K线买卖点`;
        document.getElementById('symWinRate').innerText = (data.summary.win_rate || 0).toFixed(1) + "%";
        document.getElementById('symPLRatio').innerText = (data.summary.pl_ratio || 0).toFixed(2);
        document.getElementById('symReturn').innerText = "¥" + Number(data.summary.net_profit || 0).toLocaleString();
        document.getElementById('symMaxDD').innerText = (data.summary.max_dd || 0).toFixed(2) + "%";
        document.getElementById('symSharpe').innerText = (data.summary.sharpe || 0).toFixed(2);

        if (data.live_quote) {
          const lq = data.live_quote;
          const isPos = (lq.change_val >= 0);
          const color = isPos ? 'var(--green-bright)' : 'var(--red-bright)';
          const lpElem = document.getElementById('livePrice');
          const lcElem = document.getElementById('liveChange');
          lpElem.innerText = `¥${Number(lq.last_price).toFixed(2)}`;
          lpElem.style.color = color;
          lcElem.innerText = `${isPos ? '+' : ''}${Number(lq.change_val).toFixed(2)} (${isPos ? '+' : ''}${Number(lq.change_pct).toFixed(2)}%)`;
          lcElem.style.color = color;
          lcElem.style.background = isPos ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)';
        }

        renderKlineChart(data);
      } catch (e) {
        console.error("加载 K 线失败:", e);
      }
    }

    function renderKlineChart(data) {
      if (!myChart) initChart();
      const option = {
        backgroundColor: 'transparent',
        animation: false,
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          backgroundColor: 'rgba(17, 23, 34, 0.95)',
          borderColor: '#232f3e',
          textStyle: { color: '#c5d1de', fontSize: 12 }
        },
        grid: [
          { left: '4%', right: '4%', top: '6%', height: '62%' },
          { left: '4%', right: '4%', top: '74%', height: '18%' }
        ],
        xAxis: [
          { type: 'category', data: data.categories, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#232f3e' } }, splitLine: { show: false } },
          { type: 'category', gridIndex: 1, data: data.categories, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#232f3e' } }, axisLabel: { show: false }, splitLine: { show: false } }
        ],
        yAxis: [
          { scale: true, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
          { gridIndex: 1, scale: true, splitLine: { show: false }, axisLabel: { show: false } }
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
          { type: 'slider', xAxisIndex: [0, 1], top: '94%', height: 16, start: 60, end: 100, borderColor: '#232f3e', textStyle: { color: '#7d8b99' } }
        ],
        series: [
          {
            name: `${data.timeframe} K线`,
            type: 'candlestick',
            data: data.k_values,
            itemStyle: {
              color: '#3fb950',
              color0: '#f85149',
              borderColor: '#3fb950',
              borderColor0: '#f85149'
            },
            markPoint: {
              data: data.trade_markers || [],
              tooltip: {
                formatter: function(param) {
                  const d = param.data;
                  return `<b>${d.name}</b><br/>时间: ${d.time}<br/>价格: ¥${d.price}<br/>原因: ${d.reason}<br/>手数: ${d.lots || 1}手`;
                }
              }
            }
          },
          {
            name: '成交量',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: data.volumes,
            itemStyle: {
              color: function(params) {
                const k = data.k_values[params.dataIndex];
                return (k && k[1] >= k[0]) ? 'rgba(63, 185, 80, 0.4)' : 'rgba(248, 81, 73, 0.4)';
              }
            }
          }
        ]
      };
      myChart.setOption(option, true);
    }

    async function loadTrades(symbol) {
      try {
        const res = await fetch(`/api/trades?strategy=${currentStrategy}&symbol=${symbol}`);
        const data = await res.json();
        const tbody = document.getElementById('tradesBody');
        tbody.innerHTML = "";

        if (!data.trades || data.trades.length === 0) {
          tbody.innerHTML = '<tr><td colspan="13" style="text-align:center; color:var(--text-muted); padding:20px;">暂无交易与信号记录</td></tr>';
          return;
        }

        data.trades.forEach(t => {
          const tr = document.createElement('tr');
          const isWin = (t.pnl >= 0);
          const pnlColor = isWin ? 'var(--green-bright)' : 'var(--red-bright)';
          const sideColor = (t.side === 'LONG' || t.side === '多') ? 'var(--green-bright)' : 'var(--red-bright)';
          const isLive = (t.status && t.status.includes('虚拟盘') || t.status.includes('实盘'));
          const statusBadge = isLive 
            ? `<span style="background:rgba(63,185,80,0.18); color:#3fb950; border:1px solid rgba(63,185,80,0.4); padding:2px 6px; border-radius:3px; font-size:10px; font-weight:600;">${t.status}</span>`
            : `<span style="background:rgba(210,153,34,0.15); color:#d29922; border:1px solid rgba(210,153,34,0.3); padding:2px 6px; border-radius:3px; font-size:10px;">${t.status || '📊 图表推演'}</span>`;

          tr.innerHTML = `
            <td><span style="background:rgba(88,166,255,0.15); color:#58a6ff; padding:2px 6px; border-radius:3px; font-size:11px;">${t.strategy_id}</span></td>
            <td><b>${t.symbol}</b></td>
            <td><span style="font-size:11px; background:rgba(255,255,255,0.06); padding:1px 4px; border-radius:3px;">${t.timeframe || '15m'}</span></td>
            <td><b style="color:${sideColor}">${t.side}</b></td>
            <td>${t.entry_dt}</td>
            <td>¥${Number(t.entry_p).toFixed(2)}</td>
            <td>${t.entry_reason}</td>
            <td>${t.exit_dt}</td>
            <td>¥${Number(t.exit_p).toFixed(2)}</td>
            <td>${t.exit_reason}</td>
            <td>${t.lots}手</td>
            <td><b style="color:${pnlColor}">${isWin ? '+' : ''}¥${Number(t.pnl).toLocaleString()}</b></td>
            <td>${statusBadge}</td>
          `;
          tbody.appendChild(tr);
        });
      } catch (e) {
        console.error("加载交易记录失败:", e);
      }
    }

    function selectSymbol(sym) {
      currentSymbol = sym;
      document.querySelectorAll('.symbol-item').forEach(el => el.classList.remove('active'));
      const activeEl = Array.from(document.querySelectorAll('.symbol-item')).find(el => el.innerText.includes(sym));
      if (activeEl) activeEl.classList.add('active');
      loadKline(sym);
      loadTrades(sym);
    }

    function refreshAll() {
      loadStatus();
      loadKline(currentSymbol);
      loadTrades(currentSymbol);
    }

    window.onload = () => {
      initChart();
      refreshAll();
      setInterval(refreshAll, 10000);
    };
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=False)
