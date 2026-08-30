"""
contract_specs.py — 中国期货品种合约规格单一真相源 (Single Source of Truth)

ponytail: 从 run_qlib_futures_15m_research.py FUTURES_SPECS 提取，
消除 3 处重复定义（run_qlib_futures_15m_research / run_tianji_strict / run_real_dominant）。
升级路径 = 从交易所官网或 TqSdk API 动态拉取最新保证金率。
"""

from __future__ import annotations
from typing import NamedTuple


class ContractSpec(NamedTuple):
    name: str
    multiplier: float       # 合约乘数
    tick_size: float         # 最小变动价位
    fee_rate: float          # 手续费率（成交额比例）
    margin_rate: float       # 交易所保证金率
    exchange: str            # 交易所


# fmt: off
SPECS: dict[str, ContractSpec] = {
    "AG_IDX": ContractSpec("沪银",   15.0,    1.0,   0.00005, 0.12, "SHFE"),
    "AU_IDX": ContractSpec("沪金",   1000.0,  0.02,  0.00002, 0.10, "SHFE"),
    "CU_IDX": ContractSpec("沪铜",   5.0,     10.0,  0.00005, 0.10, "SHFE"),
    "AL_IDX": ContractSpec("沪铝",   5.0,     5.0,   0.00003, 0.09, "SHFE"),
    "ZN_IDX": ContractSpec("沪锌",   5.0,     5.0,   0.00003, 0.09, "SHFE"),
    "SN_IDX": ContractSpec("沪锡",   1.0,     10.0,  0.00003, 0.12, "SHFE"),
    "RB_IDX": ContractSpec("螺纹钢", 10.0,    1.0,   0.0001,  0.09, "SHFE"),
    "HC_IDX": ContractSpec("热卷",   10.0,    1.0,   0.0001,  0.09, "SHFE"),
    "I_IDX":  ContractSpec("铁矿石", 100.0,   0.5,   0.0001,  0.13, "DCE"),
    "JM_IDX": ContractSpec("焦煤",   60.0,    0.5,   0.00015, 0.15, "DCE"),
    "J_IDX":  ContractSpec("焦炭",   100.0,   0.5,   0.00015, 0.15, "DCE"),
    "MA_IDX": ContractSpec("甲醇",   10.0,    1.0,   0.00008, 0.09, "CZCE"),
    "TA_IDX": ContractSpec("PTA",    5.0,     2.0,   0.00006, 0.08, "CZCE"),
    "SA_IDX": ContractSpec("纯碱",   20.0,    1.0,   0.0001,  0.12, "CZCE"),
    "FG_IDX": ContractSpec("玻璃",   20.0,    1.0,   0.0001,  0.10, "CZCE"),
    "M_IDX":  ContractSpec("豆粕",   10.0,    1.0,   0.00005, 0.08, "DCE"),
    "Y_IDX":  ContractSpec("豆油",   10.0,    2.0,   0.00005, 0.08, "DCE"),
    "P_IDX":  ContractSpec("棕榈油", 10.0,    2.0,   0.00005, 0.09, "DCE"),
    "C_IDX":  ContractSpec("玉米",   10.0,    1.0,   0.00004, 0.07, "DCE"),
    "CF_IDX": ContractSpec("棉花",   5.0,     5.0,   0.00006, 0.08, "CZCE"),
    "SR_IDX": ContractSpec("白糖",   10.0,    1.0,   0.00005, 0.08, "CZCE"),
    "RU_IDX": ContractSpec("橡胶",   10.0,    5.0,   0.00008, 0.10, "SHFE"),
    "LC_IDX": ContractSpec("碳酸锂", 1.0,     50.0,  0.00008, 0.14, "GFEX"),
    "SI_IDX": ContractSpec("工业硅", 5.0,     5.0,   0.00006, 0.10, "GFEX"),
    "SC_IDX": ContractSpec("原油",   1000.0,  0.1,   0.00005, 0.12, "INE"),
}
# fmt: on

# ponytail: 默认 fallback 用于未知品种，避免硬崩
_DEFAULT = ContractSpec("未知", 10.0, 1.0, 0.0001, 0.10, "UNKNOWN")


def get_spec(symbol: str) -> ContractSpec:
    """查询品种合约规格，未知品种返回保守默认值。"""
    key = symbol.upper()
    if not key.endswith("_IDX"):
        key = f"{key}_IDX"
    return SPECS.get(key, _DEFAULT)
