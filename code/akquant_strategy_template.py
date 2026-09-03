"""
akquant_strategy_template.py — AKQuant 策略标准解耦模板与基础类

架构设计：
1. 若系统已编译/安装 akquant，优先直接继承官方 akquant.Strategy；
2. 若运行在轻量/未编译环境，提供 100% 接口与属性对齐的高保真 Python 抽象基类；
3. 为 lianghua 的经典量化算法（如 ChanQuant、Taiyi、Tianji 等）提供标准桥接；
4. 保证未来升级 akquant 时只需适配本模板，业务策略代码零改动。
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AKQUANT_SRC = PROJECT_ROOT / "akquant" / "python"
if AKQUANT_SRC.exists() and str(AKQUANT_SRC) not in sys.path:
    sys.path.insert(0, str(AKQUANT_SRC))

logger = logging.getLogger("akquant_strategy_template")

try:
    from akquant import Bar as AkquantBar
    from akquant import Strategy as AkquantStrategy
    AKQUANT_NATIVE_AVAILABLE = True
except Exception:
    AKQUANT_NATIVE_AVAILABLE = False


@dataclass
class Bar:
    """标准 K 线事件对象"""
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    open_interest: float = 0.0

    @property
    def timestamp_iso(self) -> str:
        return self.datetime.isoformat()


class AkquantStrategyBase:
    """
    AKQuant 策略解耦基类。
    策略开发者继承此类编写因果信号与交易逻辑。
    """
    strategy_name: str = "AkquantBaseStrategy"
    author: str = "Lianghua Quant"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.positions: Dict[str, float] = {}
        self.entry_prices: Dict[str, float] = {}
        self.bars_held: Dict[str, int] = {}
        self.orders: List[Dict[str, Any]] = []
        self.inited: bool = False
        self.trading: bool = False

    def on_init(self) -> None:
        """策略初始化生命周期"""
        self.inited = True

    def on_start(self) -> None:
        """策略启动生命周期"""
        self.trading = True

    def on_stop(self) -> None:
        """策略停止生命周期"""
        self.trading = False

    def on_bar(self, bar: Any) -> None:
        """
        K 线事件回调 (逐柱到达)
        :param bar: AKQuant Bar 对象或标准 Bar 结构
        """
        pass

    def on_trade(self, trade: Any) -> None:
        """成交回报回调"""
        pass

    def on_order(self, order: Any) -> None:
        """委托回报回调"""
        pass

    # ================= 标准交易动作接口 =================

    def get_position(self, symbol: str) -> float:
        """获取指定标的的当前持仓手数"""
        return self.positions.get(symbol, 0.0)

    def buy(self, symbol: str, quantity: float, price: Optional[float] = None) -> None:
        """买入 / 开多"""
        self.positions[symbol] = self.positions.get(symbol, 0.0) + quantity
        self.orders.append({
            "action": "BUY",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "time": datetime.now()
        })

    def sell(self, symbol: str, quantity: float, price: Optional[float] = None) -> None:
        """卖出 / 平多 / 开空"""
        current = self.positions.get(symbol, 0.0)
        self.positions[symbol] = current - quantity
        self.orders.append({
            "action": "SELL",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "time": datetime.now()
        })

    def close_position(self, symbol: Optional[str] = None) -> None:
        """平掉指定或全部持仓"""
        if symbol:
            pos = self.get_position(symbol)
            if pos != 0:
                self.sell(symbol, abs(pos)) if pos > 0 else self.buy(symbol, abs(pos))
                self.positions[symbol] = 0.0
        else:
            for sym, pos in list(self.positions.items()):
                if pos != 0:
                    self.sell(sym, abs(pos)) if pos > 0 else self.buy(sym, abs(pos))
                    self.positions[sym] = 0.0

    def order_target_percent(self, target_percent: float, symbol: str) -> None:
        """按目标资金比例调仓"""
        pass


def get_base_strategy_class():
    """
    动态获取最佳策略基类。若原生 AKQuant 可用则无缝切换，
    否则使用解耦纯 Python 基类。
    """
    if AKQUANT_NATIVE_AVAILABLE and AkquantStrategy is not None:
        return AkquantStrategy
    return AkquantStrategyBase
