"""
contract_specs.py — 中国期货品种合约规格单一真相源 (Single Source of Truth)

【真实交易与结算支持】：
1. 精准区分按成交额比例 (RATIO) 与按每手固定 (FIXED) 计费机制；
2. 真实平今仓费率倍数 (close_today_ratio) 建模 (如 CZCE/DCE/SHFE 平今高费率)；
3. 支持交易所基础保证金率与期货公司加收综合保证金率；
4. 提供统一单一同源计算函数 calculate_contract_fee 与 calculate_contract_margin。
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractSpec:
    name: str
    multiplier: float            # 合约乘数 (吨/手, 克/手等)
    tick_size: float             # 最小变动价位
    fee_rate: float              # 基础手续费率（成交额比例）
    margin_rate: float           # 交易所基础保证金率
    exchange: str                # 交易所 (SHFE, DCE, CZCE, GFEX, INE)
    fee_type: str = "RATIO"      # "RATIO" (按成交额比例) 或 "FIXED" (按每手固定金额)
    fixed_fee: float = 0.0       # 每手固定费用 (当 fee_type == 'FIXED' 时生效)
    close_today_ratio: float = 1.0 # 平今仓费率乘数
    broker_margin_rate: float = 0.0 # 期货公司实际综合保证金率 (若为0则默认 margin_rate + 0.02)
    base_price: float = 3000.0   # 品种典型价格中枢 (合成数据起始价, 单一真相源)


# fmt: off
SPECS: Dict[str, ContractSpec] = {
    "AG_IDX": ContractSpec("沪银",   15.0,    1.0,   0.00005, 0.12, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.14, base_price=7500.0),
    "AU_IDX": ContractSpec("沪金",   1000.0,  0.02,  0.00002, 0.10, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.12, base_price=550.0),
    "CU_IDX": ContractSpec("沪铜",   5.0,     10.0,  0.00005, 0.10, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.12, base_price=74000.0),
    "AL_IDX": ContractSpec("沪铝",   5.0,     5.0,   0.00003, 0.09, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=19500.0),
    "ZN_IDX": ContractSpec("沪锌",   5.0,     5.0,   0.00003, 0.09, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=23000.0),
    "SN_IDX": ContractSpec("沪锡",   1.0,     10.0,  0.00003, 0.12, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.14, base_price=250000.0),
    "RB_IDX": ContractSpec("螺纹钢", 10.0,    1.0,   0.00010, 0.09, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=3400.0),
    "HC_IDX": ContractSpec("热卷",   10.0,    1.0,   0.00010, 0.09, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=3600.0),
    "I_IDX":  ContractSpec("铁矿石", 100.0,   0.5,   0.00010, 0.13, "DCE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.15, base_price=780.0),
    "JM_IDX": ContractSpec("焦煤",   60.0,    0.5,   0.00015, 0.15, "DCE",  fee_type="RATIO", close_today_ratio=1.4, broker_margin_rate=0.18, base_price=1400.0),
    "J_IDX":  ContractSpec("焦炭",   100.0,   0.5,   0.00015, 0.15, "DCE",  fee_type="RATIO", close_today_ratio=1.4, broker_margin_rate=0.18, base_price=2100.0),
    "MA_IDX": ContractSpec("甲醇",   10.0,    1.0,   0.00008, 0.09, "CZCE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=2400.0),
    "TA_IDX": ContractSpec("PTA",    5.0,     2.0,   0.00006, 0.08, "CZCE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.10, base_price=5200.0),
    "SA_IDX": ContractSpec("纯碱",   20.0,    1.0,   0.00010, 0.12, "CZCE", fee_type="RATIO", close_today_ratio=2.0, broker_margin_rate=0.14, base_price=1800.0),
    "FG_IDX": ContractSpec("玻璃",   20.0,    1.0,   0.00010, 0.10, "CZCE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.12, base_price=1400.0),
    "M_IDX":  ContractSpec("豆粕",   10.0,    1.0,   0.00005, 0.08, "DCE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.10, base_price=3000.0),
    "Y_IDX":  ContractSpec("豆油",   10.0,    2.0,   0.00005, 0.08, "DCE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.10, base_price=8000.0),
    "P_IDX":  ContractSpec("棕榈油", 10.0,    2.0,   0.00005, 0.09, "DCE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.11, base_price=8200.0),
    "C_IDX":  ContractSpec("玉米",   10.0,    1.0,   0.00004, 0.07, "DCE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.09, base_price=2300.0),
    "CF_IDX": ContractSpec("棉花",   5.0,     5.0,   0.00006, 0.08, "CZCE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.10, base_price=14500.0),
    "SR_IDX": ContractSpec("白糖",   10.0,    1.0,   0.00005, 0.08, "CZCE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.10, base_price=6000.0),
    "RU_IDX": ContractSpec("橡胶",   10.0,    5.0,   0.00008, 0.10, "SHFE", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.12, base_price=15000.0),
    "LC_IDX": ContractSpec("碳酸锂", 1.0,     50.0,  0.00008, 0.14, "GFEX", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.16, base_price=80000.0),
    "SI_IDX": ContractSpec("工业硅", 5.0,     5.0,   0.00006, 0.10, "GFEX", fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.12, base_price=11000.0),
    "SC_IDX": ContractSpec("原油",   1000.0,  0.1,   0.00005, 0.12, "INE",  fee_type="RATIO", close_today_ratio=1.0, broker_margin_rate=0.14, base_price=580.0),
}
# fmt: on

_DEFAULT = ContractSpec("未知", 10.0, 1.0, 0.0001, 0.10, "UNKNOWN", broker_margin_rate=0.12)


def get_spec(symbol: str) -> ContractSpec:
    """查询品种合约规格，未知品种返回保守默认值并记录警告。"""
    key = symbol.upper()
    if not key.endswith("_IDX"):
        key = f"{key}_IDX"
    spec = SPECS.get(key)
    if spec is None:
        logger.warning("未找到品种 [%s] 的合约规格定义，使用默认 fallback 规格 (乘数=10.0, 保证金=10%%)", symbol)
        return _DEFAULT
    return spec


def calculate_contract_fee(
    spec: ContractSpec,
    price: float,
    lots: int,
    is_close_today: bool = False,
    cost_multiplier: float = 1.0,
) -> float:
    """
    单一同源手续费计算函数：
    严格处理比例费率 (RATIO)、固定每手 (FIXED)、平今乘数 (close_today_ratio) 与成本倍数 (cost_multiplier)。
    """
    mult = spec.close_today_ratio if is_close_today else 1.0
    if spec.fee_type == "FIXED":
        base_fee = spec.fixed_fee * lots * mult
    else:
        base_fee = price * spec.multiplier * lots * spec.fee_rate * mult
    return base_fee * cost_multiplier


def calculate_contract_margin(
    spec: ContractSpec,
    price: float,
    lots: int,
    use_broker_rate: bool = False,
) -> float:
    """
    单一同源保证金计算函数：
    支持交易所基础保证金率与期货公司实际综合保证金率。
    """
    rate = spec.broker_margin_rate if (use_broker_rate and spec.broker_margin_rate > 0) else spec.margin_rate
    return price * spec.multiplier * lots * rate

