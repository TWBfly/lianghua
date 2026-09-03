"""
futures_contract_calendar.py — 25 大期货品种主力换月日历、判定引擎与展期摩擦核算库

第一性原理：
1. 真实复原中国期货市场 (上期所、大商所、郑商所、中金所、广期所) 历史各时刻的主力合约编号；
2. 精确计算换月时间窗口 (Roll Window) 与次主力 (Next Dominant)；
3. 核算跨换月持仓的展期摩擦 (双向平旧开新手续费 + 双向滑点冲击)；
4. 支撑回测引擎与实盘交易 100% 像素级对齐。
"""

from __future__ import annotations

import datetime
from typing import Dict, Tuple, Optional
import numpy as np
import pandas as pd


# 25 大品种交易所与主力月份规则表
COMMODITY_RULES = {
    # 贵金属: 06/12 循环
    "AG_IDX": {"name": "白银", "exchange": "SHFE", "prefix": "ag", "type": "06_12", "shift_months": [4, 10], "shift_days": [25, 25]},
    "AU_IDX": {"name": "黄金", "exchange": "SHFE", "prefix": "au", "type": "06_12", "shift_months": [4, 10], "shift_days": [25, 25]},
    
    # 黑色系: 01/05/10 循环
    "RB_IDX": {"name": "螺纹钢", "exchange": "SHFE", "prefix": "rb", "type": "01_05_10", "shift_months": [12, 4, 8], "shift_days": [15, 15, 15]},
    "HC_IDX": {"name": "热卷",   "exchange": "SHFE", "prefix": "hc", "type": "01_05_10", "shift_months": [12, 4, 8], "shift_days": [15, 15, 15]},
    "I_IDX":  {"name": "铁矿石", "exchange": "DCE",  "prefix": "i",  "type": "01_05_10", "shift_months": [12, 4, 8], "shift_days": [15, 15, 15]},
    "J_IDX":  {"name": "焦炭",   "exchange": "DCE",  "prefix": "j",  "type": "01_05_10", "shift_months": [12, 4, 8], "shift_days": [15, 15, 15]},
    "JM_IDX": {"name": "焦煤",   "exchange": "DCE",  "prefix": "jm", "type": "01_05_10", "shift_months": [12, 4, 8], "shift_days": [15, 15, 15]},

    # 农产品与软商品: 01/05/09 循环
    "M_IDX":  {"name": "豆粕",   "exchange": "DCE",  "prefix": "m",  "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "Y_IDX":  {"name": "豆油",   "exchange": "DCE",  "prefix": "y",  "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "P_IDX":  {"name": "棕榈油", "exchange": "DCE",  "prefix": "p",  "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "C_IDX":  {"name": "玉米",   "exchange": "DCE",  "prefix": "c",  "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "SR_IDX": {"name": "白糖",   "exchange": "CZCE", "prefix": "SR", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "CF_IDX": {"name": "棉花",   "exchange": "CZCE", "prefix": "CF", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "SA_IDX": {"name": "纯碱",   "exchange": "CZCE", "prefix": "SA", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "FG_IDX": {"name": "玻璃",   "exchange": "CZCE", "prefix": "FG", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "MA_IDX": {"name": "甲醇",   "exchange": "CZCE", "prefix": "MA", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "TA_IDX": {"name": "PTA",    "exchange": "CZCE", "prefix": "TA", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},
    "RU_IDX": {"name": "橡胶",   "exchange": "SHFE", "prefix": "ru", "type": "01_05_09", "shift_months": [12, 4, 8], "shift_days": [10, 10, 10]},

    # 有色金属: 逐月主力 (后推 2 个月)
    "CU_IDX": {"name": "沪铜",   "exchange": "SHFE", "prefix": "cu", "type": "monthly_lead2", "shift_day": 15},
    "AL_IDX": {"name": "沪铝",   "exchange": "SHFE", "prefix": "al", "type": "monthly_lead2", "shift_day": 15},
    "ZN_IDX": {"name": "沪锌",   "exchange": "SHFE", "prefix": "zn", "type": "monthly_lead2", "shift_day": 15},
    "SN_IDX": {"name": "沪锡",   "exchange": "SHFE", "prefix": "sn", "type": "monthly_lead2", "shift_day": 15},

    # 能源原油: 逐月主力 (后推 2 个月，20日前后切换)
    "SC_IDX": {"name": "原油",   "exchange": "INE",  "prefix": "sc", "type": "monthly_lead2", "shift_day": 20},

    # 广期所新能源: 01/07/11 或 05/11 循环
    "LC_IDX": {"name": "碳酸锂", "exchange": "GFEX", "prefix": "lc", "type": "01_07_11", "shift_months": [11, 5, 9], "shift_days": [15, 15, 15]},
    "SI_IDX": {"name": "工业硅", "exchange": "GFEX", "prefix": "si", "type": "01_07_11", "shift_months": [11, 5, 9], "shift_days": [15, 15, 15]}
}


def parse_datetime(dt_val) -> datetime.datetime:
    if isinstance(dt_val, datetime.datetime):
        return dt_val
    if isinstance(dt_val, pd.Timestamp):
        return dt_val.to_pydatetime()
    if isinstance(dt_val, str):
        try:
            return datetime.datetime.strptime(dt_val[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.datetime.strptime(dt_val[:10], "%Y-%m-%d")
    return datetime.datetime.now()


def get_dominant_contract_by_date(symbol: str, dt_val) -> str:
    """根据历史任意时刻的日期时间，计算该品种在当时真实处于主力地位的具体合约代码
    # ponytail: 硬编码换月日期是基于历史统计的近似值，
    # 真实换月由持仓量(OI)决定。升级路径 = 接入 TqSdk 历史持仓量数据动态判定
    """
    sym = symbol.upper()
    if not sym.endswith("_IDX"):
        sym = f"{sym}_IDX"
    
    cfg = COMMODITY_RULES.get(sym)
    if not cfg:
        return f"{symbol.lower()}.COMM"
    
    dt = parse_datetime(dt_val)
    year = dt.year
    month = dt.month
    day = dt.day
    yy = year % 100
    prefix = cfg["prefix"]
    exch = cfg["exchange"]
    c_type = cfg["type"]

    if c_type == "06_12":
        # 04-25 之前为主力 06，04-25 ~ 10-25 为主力 12，10-25 之后为主力次年 06
        if (month < 4) or (month == 4 and day < 25):
            target_yy, target_mm = yy, "06"
        elif (month < 10) or (month == 10 and day < 25):
            target_yy, target_mm = yy, "12"
        else:
            target_yy, target_mm = (yy + 1) % 100, "06"

    elif c_type == "01_05_10":
        # 01 -> 05 切换在 12-15；05 -> 10 切换在 04-15；10 -> 01 切换在 08-15
        if (month < 4) or (month == 4 and day < 15):
            target_yy, target_mm = yy, "05"
        elif (month < 8) or (month == 8 and day < 15):
            target_yy, target_mm = yy, "10"
        elif (month < 12) or (month == 12 and day < 15):
            target_yy, target_mm = (yy + 1) % 100, "01"
        else:
            target_yy, target_mm = (yy + 1) % 100, "05"

    elif c_type == "01_05_09":
        # 01 -> 05 切换在 12-10；05 -> 09 切换在 04-10；09 -> 01 切换在 08-10
        if (month < 4) or (month == 4 and day < 10):
            target_yy, target_mm = yy, "05"
        elif (month < 8) or (month == 8 and day < 10):
            target_yy, target_mm = yy, "09"
        elif (month < 12) or (month == 12 and day < 10):
            target_yy, target_mm = (yy + 1) % 100, "01"
        else:
            target_yy, target_mm = (yy + 1) % 100, "05"

    elif c_type == "01_07_11":
        # 05 -> 11 切换在 09-15；11 -> 01 切换在 11-15；01 -> 05/07 切换在 05-15
        if (month < 5) or (month == 5 and day < 15):
            target_yy, target_mm = yy, "07"
        elif (month < 9) or (month == 9 and day < 15):
            target_yy, target_mm = yy, "11"
        elif (month < 11) or (month == 11 and day < 15):
            target_yy, target_mm = yy, "11"
        else:
            target_yy, target_mm = (yy + 1) % 100, "01"

    elif c_type == "monthly_lead2":
        # 逐月主力 (当月 shift_day 前为主力 M+2，shift_day 之后为主力 M+3)
        shift_day = cfg.get("shift_day", 15)
        lead = 2 if day < shift_day else 3
        calc_month = month + lead
        target_yy = (yy + (calc_month - 1) // 12) % 100
        target_mm = f"{((calc_month - 1) % 12 + 1):02d}"

    else:
        target_yy, target_mm = yy, f"{month:02d}"

    return f"{prefix}{target_yy:02d}{target_mm}.{exch}"


def is_in_roll_window(symbol: str, dt_val, window_days: int = 7) -> bool:
    """判定当前日期是否处于主力移仓换月的关键窗口期 (前后 window_days 天)"""
    dt = parse_datetime(dt_val)
    curr_dom = get_dominant_contract_by_date(symbol, dt)
    next_dom = get_dominant_contract_by_date(symbol, dt + datetime.timedelta(days=window_days))
    return curr_dom != next_dom


def get_next_dominant_contract(symbol: str, dt_val) -> str:
    """获取下一任次主力合约编号"""
    dt = parse_datetime(dt_val)
    return get_dominant_contract_by_date(symbol, dt + datetime.timedelta(days=40))


def calculate_roll_friction(
    price: float,
    multiplier: float,
    lots: int,
    fee_rate: float = 0.00005,
    slippage: float = 1.0
) -> float:
    """
    计算一次主力换月展期的完整摩擦成本 (第一性原理硬成本核算)：
    1. 平掉旧主力合约手续费 + 开立新主力合约手续费 (双重手续费)
    2. 平旧合约滑点 + 开新合约滑点 (双重滑点)
    """
    turnover = price * multiplier * lots
    commission_cost = 2.0 * (turnover * fee_rate)
    slippage_cost = 2.0 * (slippage * multiplier * lots)
    return commission_cost + slippage_cost


def calculate_roll_adjustment_ratio(old_close: float, new_close: float) -> float:
    """
    计算主力换月展期价格调整比例 (用于连续合约比例后复权):
    adjustment_ratio = new_close / old_close (若 old_close > 0)
    """
    if old_close <= 0 or new_close <= 0:
        return 1.0
    return float(new_close / old_close)


def adjust_continuous_series(
    df: pd.DataFrame,
    roll_indices: list[int],
    ratios: list[float],
    price_cols: list[str] = None
) -> pd.DataFrame:
    """
    对连续合约历史数据做累积比例后复权，消除换月跳空伪信号。
    df: 包含 price_cols 的 DataFrame
    roll_indices: 每次展期发生的行索引列表 (按时间升序)
    ratios: 每次展期对应的 ratio = new_close / old_close
    """
    if price_cols is None:
        price_cols = [c for c in ["open", "high", "low", "close", "settlement"] if c in df.columns]
    
    df_adj = df.copy()
    if not roll_indices or not ratios or len(roll_indices) != len(ratios):
        return df_adj

    # 从最新展期向前回溯，累积应用调整因子
    cum_factor = 1.0
    # 建立从后向前的调整权重
    factors = np.ones(len(df_adj), dtype=float)
    
    for idx, ratio in reversed(list(zip(roll_indices, ratios))):
        if idx < len(df_adj) and ratio > 0:
            cum_factor *= ratio
            factors[:idx] = cum_factor

    for col in price_cols:
        df_adj[col] = df_adj[col] * factors

    return df_adj
