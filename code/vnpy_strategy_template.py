"""
vnpy_strategy_template.py — vn.py CTA 策略标准模板与基础对象定义

兼容性说明：
1. 若环境中已安装 vnpy 及 vnpy_ctastrategy，优先继承官方对象与接口；
2. 若环境未安装或运行在精简沙箱中，提供 100% 结构对齐的纯 Python 纯净高保真抽象；
3. 支持统一的 on_bar / on_tick / buy / sell / short / cover 策略编程模式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import numpy as np
import pandas as pd

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VNPY_SRC = PROJECT_ROOT / "vnpy"
if VNPY_SRC.exists() and str(VNPY_SRC) not in sys.path:
    sys.path.insert(0, str(VNPY_SRC))

from vnpy_data_adapter import BarData, Exchange, Interval

try:
    from vnpy.trader.constant import Direction, Offset, Status
    from vnpy.trader.object import OrderData, TradeData, StopOrder
except ImportError:
    class Direction(Enum):
        """委托/成交方向"""
        LONG = "多"
        SHORT = "空"
        NET = "净"

    class Offset(Enum):
        """开平仓标志"""
        NONE = ""
        OPEN = "开仓"
        CLOSE = "平仓"
        CLOSETODAY = "平今"
        CLOSEYESTERDAY = "平昨"

    class Status(Enum):
        """订单状态"""
        SUBMITTING = "提交中"
        NOTTRADED = "未成交"
        PARTTRADED = "部分成交"
        ALLTRADED = "全部成交"
        CANCELLED = "已撤销"
        REJECTED = "拒单"

    @dataclass
    class OrderData:
        """vn.py 标准委托单"""
        symbol: str
        exchange: Exchange
        orderid: str
        direction: Direction
        offset: Offset
        price: float
        volume: float
        traded: float = 0.0
        status: Status = Status.NOTTRADED
        datetime: Optional[datetime] = None
        gateway_name: str = "VNPY_ENGINE"

        @property
        def vt_symbol(self) -> str:
            return f"{self.symbol}.{self.exchange.value}"

        @property
        def vt_orderid(self) -> str:
            return f"{self.gateway_name}.{self.orderid}"

        @property
        def is_active(self) -> bool:
            return self.status in {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}

    @dataclass
    class TradeData:
        """vn.py 标准成交单"""
        symbol: str
        exchange: Exchange
        orderid: str
        tradeid: str
        direction: Direction
        offset: Offset
        price: float
        volume: float
        datetime: datetime
        gateway_name: str = "VNPY_ENGINE"

        @property
        def vt_symbol(self) -> str:
            return f"{self.symbol}.{self.exchange.value}"

        @property
        def vt_tradeid(self) -> str:
            return f"{self.gateway_name}.{self.tradeid}"

    @dataclass
    class StopOrder:
        """vn.py 条件停止单"""
        vt_symbol: str
        direction: Direction
        offset: Offset
        price: float
        volume: float
        stop_orderid: str
        strategy_name: str
        datetime: Optional[datetime] = None
        is_active: bool = True



class CtaTemplate:
    """
    vn.py 标准 CTA 策略基类
    """
    author: str = "Lianghua Quant"
    parameters: list[str] = []
    variables: list[str] = []

    def __init__(
        self,
        cta_engine: Any,
        strategy_name: str,
        vt_symbol: str,
        setting: dict
    ):
        self.cta_engine = cta_engine
        self.strategy_name = strategy_name
        self.vt_symbol = vt_symbol
        self.setting = setting

        self.inited: bool = False
        self.trading: bool = False
        self.pos: float = 0.0

        # 从 setting 更新参数
        if setting:
            for name in self.parameters:
                if name in setting:
                    setattr(self, name, setting[name])

    def update_setting(self, setting: dict):
        for name in self.parameters:
            if name in setting:
                setattr(self, name, setting[name])

    def on_init(self):
        """策略初始化回调"""
        self.inited = True

    def on_start(self):
        """策略启动回调"""
        self.trading = True

    def on_stop(self):
        """策略停止回调"""
        self.trading = False

    def on_bar(self, bar: BarData):
        """K 线推送回调 (核心因果信号逻辑)"""
        pass

    def on_order(self, order: OrderData):
        """委托回报回调"""
        pass

    def on_trade(self, trade: TradeData):
        """成交回报回调"""
        pass

    def on_stop_order(self, stop_order: StopOrder):
        """停止单触发回调"""
        pass

    # ================= 委托动作接口 =================

    def buy(self, price: float, volume: float, stop: bool = False) -> list[str]:
        """买开 (做多)"""
        return self.send_order(Direction.LONG, Offset.OPEN, price, volume, stop)

    def sell(self, price: float, volume: float, stop: bool = False) -> list[str]:
        """卖平 (平多)"""
        return self.send_order(Direction.SHORT, Offset.CLOSE, price, volume, stop)

    def short(self, price: float, volume: float, stop: bool = False) -> list[str]:
        """卖开 (做空)"""
        return self.send_order(Direction.SHORT, Offset.OPEN, price, volume, stop)

    def cover(self, price: float, volume: float, stop: bool = False) -> list[str]:
        """买平 (平空)"""
        return self.send_order(Direction.LONG, Offset.CLOSE, price, volume, stop)

    def send_order(
        self,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        stop: bool = False
    ) -> list[str]:
        if self.cta_engine:
            return self.cta_engine.send_order(
                self, direction, offset, price, volume, stop
            )
        return []

    def cancel_order(self, vt_orderid: str):
        if self.cta_engine:
            self.cta_engine.cancel_order(self, vt_orderid)

    def cancel_all(self):
        if self.cta_engine:
            self.cta_engine.cancel_all(self)

    def write_log(self, msg: str):
        if self.cta_engine and hasattr(self.cta_engine, "write_log"):
            self.cta_engine.write_log(f"[{self.strategy_name}] {msg}")
