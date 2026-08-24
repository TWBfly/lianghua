"""
vnpy_backtest_runner.py — vn.py CTA 离散事件驱动回测引擎与绩效分析器

核心机制：
1. 严格时序撮合：上一周期的未成交委托在当前 Bar 开始时按价格区间撮合（多头 price >= low，空头 price <= high）；
2. 零未来函数：当前 Bar 结束时触发 strategy.on_bar，新委托只能在下一 Bar 生效；
3. 真实物理滑点与费率：精确扣除最小变动价位滑点、按比例/按手手续费；
4. 逐日盯市（Mark-to-Market）盈亏对账：每日收盘按结算价重估持仓市值，生成 DailyResult。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
import math
from pathlib import Path
from typing import Type, Dict, List, Any, Optional
import numpy as np
import pandas as pd

from vnpy_data_adapter import BarData, Exchange, Interval
from vnpy_strategy_template import (
    CtaTemplate, Direction, Offset, OrderData, TradeData, Status, StopOrder
)


@dataclass
class DailyResult:
    """逐日盯市盈亏记录"""
    date: date
    close_price: float
    previous_close: float
    trade_count: int = 0
    start_pos: float = 0.0
    end_pos: float = 0.0
    turnover: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    trading_pnl: float = 0.0
    holding_pnl: float = 0.0
    total_pnl: float = 0.0
    net_pnl: float = 0.0


class VnpyBacktestRunner:
    """
    vn.py 高保真 CTA 回测引擎
    """

    def __init__(
        self,
        vt_symbol: str = "ag888.SHFE",
        interval: Interval = Interval.MINUTE,
        start_date: Optional[str] = None,

        end_date: Optional[str] = None,
        rate: float = 0.00005,         # 手续费率 (万分之0.5)
        slippage: float = 1.0,         # 滑点 (点数)
        size: float = 15.0,            # 合约乘数
        pricetick: float = 1.0,        # 最小变动价位
        capital: float = 1_000_000.0,  # 初始本金
    ):
        self.vt_symbol = vt_symbol
        self.interval = interval
        self.start_date = start_date
        self.end_date = end_date
        self.rate = rate
        self.slippage = slippage
        self.size = size
        self.pricetick = pricetick
        self.capital = capital

        # 策略与回测运行状态
        self.strategy: Optional[CtaTemplate] = None
        self.bars: list[BarData] = []
        self.datetime: Optional[datetime] = None

        self.limit_order_count: int = 0
        self.limit_orders: dict[str, OrderData] = {}
        self.active_limit_orders: dict[str, OrderData] = {}

        self.trade_count: int = 0
        self.trades: dict[str, TradeData] = {}

        self.logs: list[str] = []
        self.daily_results: dict[date, DailyResult] = {}
        self.daily_df: Optional[pd.DataFrame] = None

    def add_strategy(self, strategy_class: Type[CtaTemplate], setting: dict = None):
        """绑定策略实例"""
        setting = setting or {}
        self.strategy = strategy_class(
            cta_engine=self,
            strategy_name=strategy_class.__name__,
            vt_symbol=self.vt_symbol,
            setting=setting
        )

    def load_bars(self, bars: list[BarData]):
        """加载 K 线序列"""
        self.bars = bars

    def write_log(self, msg: str):
        log_entry = f"[{self.datetime or 'INIT'}] {msg}"
        self.logs.append(log_entry)

    def send_order(
        self,
        strategy: CtaTemplate,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        stop: bool = False
    ) -> list[str]:
        """策略发送委托单回调"""
        self.limit_order_count += 1
        orderid = f"ORD_{self.limit_order_count:06d}"

        # 规范化价格至最小变动价位
        rounded_price = round(price / self.pricetick) * self.pricetick

        order = OrderData(
            symbol=self.vt_symbol.split(".")[0],
            exchange=Exchange.SHFE,
            orderid=orderid,
            direction=direction,
            offset=offset,
            price=rounded_price,
            volume=volume,
            status=Status.NOTTRADED,
            datetime=self.datetime,
            gateway_name="VNPY_BT"
        )
        self.active_limit_orders[orderid] = order
        self.limit_orders[orderid] = order
        return [order.vt_orderid]

    def cancel_order(self, strategy: CtaTemplate, vt_orderid: str):
        orderid = vt_orderid.split(".")[-1]
        if orderid in self.active_limit_orders:
            order = self.active_limit_orders.pop(orderid)
            order.status = Status.CANCELLED
            strategy.on_order(order)

    def cancel_all(self, strategy: CtaTemplate):
        for orderid in list(self.active_limit_orders.keys()):
            self.cancel_order(strategy, f"VNPY_BT.{orderid}")

    def cross_limit_order(self, bar: BarData):
        """
        核心时序撮合逻辑：在当前 Bar 内对历史有效报单进行价格匹配
        """
        for orderid, order in list(self.active_limit_orders.items()):
            long_cross_price = bar.low_price
            short_cross_price = bar.high_price

            # 撮合买单
            if order.direction == Direction.LONG:
                # 报单价 >= 最低价即可成交
                if order.price >= long_cross_price:
                    # 成交价判定（若开盘直接跳空低开，以开盘价成交；否则以报单价成交）
                    trade_price = min(order.price, bar.open_price) + self.slippage * self.pricetick
                    self.execute_trade(order, trade_price, bar.datetime)
            # 撮合卖单
            elif order.direction == Direction.SHORT:
                # 报单价 <= 最高价即可成交
                if order.price <= short_cross_price:
                    trade_price = max(order.price, bar.open_price) - self.slippage * self.pricetick
                    self.execute_trade(order, trade_price, bar.datetime)

    def execute_trade(self, order: OrderData, trade_price: float, dt: datetime):
        """撮合成交并更新持仓"""
        self.trade_count += 1
        tradeid = f"TRD_{self.trade_count:06d}"

        trade = TradeData(
            symbol=order.symbol,
            exchange=order.exchange,
            orderid=order.orderid,
            tradeid=tradeid,
            direction=order.direction,
            offset=order.offset,
            price=trade_price,
            volume=order.volume,
            datetime=dt,
            gateway_name="VNPY_BT"
        )

        # 更新委托状态
        order.traded = order.volume
        order.status = Status.ALLTRADED
        if order.orderid in self.active_limit_orders:
            del self.active_limit_orders[order.orderid]

        self.trades[tradeid] = trade

        # 更新策略持仓
        if trade.direction == Direction.LONG:
            self.strategy.pos += trade.volume
        else:
            self.strategy.pos -= trade.volume

        self.strategy.on_order(order)
        self.strategy.on_trade(trade)

    def run_backtesting(self) -> dict:
        """运行完整离散事件回测"""
        if not self.strategy:
            raise ValueError("No strategy added.")
        if not self.bars:
            raise ValueError("No bar data loaded.")

        self.strategy.on_init()
        self.strategy.on_start()

        for bar in self.bars:
            self.datetime = bar.datetime

            # 1. 先撮合上一周期发出的挂单
            self.cross_limit_order(bar)

            # 2. 推送当前完整 Bar 给策略（产生新信号并发出下一周期委托）
            self.strategy.on_bar(bar)

            # 3. 记录逐日数据
            self.update_daily_close(bar)

        self.strategy.on_stop()
        return self.calculate_statistics()

    def update_daily_close(self, bar: BarData):
        """按日聚合收盘价与持仓，供每日盯市结算"""
        bar_date = bar.datetime.date()
        if bar_date not in self.daily_results:
            self.daily_results[bar_date] = DailyResult(
                date=bar_date,
                close_price=bar.close_price,
                previous_close=bar.close_price,
                end_pos=self.strategy.pos
            )
        else:
            res = self.daily_results[bar_date]
            res.close_price = bar.close_price
            res.end_pos = self.strategy.pos

    def calculate_statistics(self) -> dict:
        """计算逐日盯市盈亏与核心风险收益指标"""
        if not self.daily_results:
            return {"status": "EMPTY"}

        # 整理 trades 到各交易日
        trades_list = list(self.trades.values())
        trades_by_date: dict[date, list[TradeData]] = {}
        for t in trades_list:
            d = t.datetime.date()
            trades_by_date.setdefault(d, []).append(t)

        sorted_dates = sorted(self.daily_results.keys())
        prev_close = self.bars[0].open_price
        prev_pos = 0.0

        daily_rows = []
        for d in sorted_dates:
            res = self.daily_results[d]
            res.previous_close = prev_close
            res.start_pos = prev_pos
            day_trades = trades_by_date.get(d, [])
            res.trade_count = len(day_trades)

            # 计算当日交易盈亏与手续费/滑点
            for t in day_trades:
                turnover = t.price * t.volume * self.size
                res.turnover += turnover
                res.commission += turnover * self.rate
                res.slippage += self.slippage * self.pricetick * t.volume * self.size

                # 交易盈亏
                pos_change = t.volume if t.direction == Direction.LONG else -t.volume
                res.trading_pnl += (res.close_price - t.price) * pos_change * self.size

            # 持仓隔夜盯市盈亏 (从昨日收盘到今日收盘)
            res.holding_pnl = res.start_pos * (res.close_price - res.previous_close) * self.size
            res.total_pnl = res.holding_pnl + res.trading_pnl
            res.net_pnl = res.total_pnl - res.commission - res.slippage

            daily_rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "close_price": res.close_price,
                "start_pos": res.start_pos,
                "end_pos": res.end_pos,
                "trade_count": res.trade_count,
                "turnover": res.turnover,
                "commission": res.commission,
                "slippage": res.slippage,
                "holding_pnl": res.holding_pnl,
                "trading_pnl": res.trading_pnl,
                "net_pnl": res.net_pnl
            })

            prev_close = res.close_price
            prev_pos = res.end_pos

        self.daily_df = pd.DataFrame(daily_rows)
        self.daily_df["balance"] = self.capital + self.daily_df["net_pnl"].cumsum()
        self.daily_df["daily_return"] = self.daily_df["net_pnl"] / self.capital
        self.daily_df["peak"] = self.daily_df["balance"].cummax()
        self.daily_df["drawdown"] = (self.daily_df["balance"] - self.daily_df["peak"]) / self.daily_df["peak"]

        # 统计汇总指标
        total_pnl = float(self.daily_df["net_pnl"].sum())
        total_return_pct = (total_pnl / self.capital) * 100.0
        max_dd_pct = float(abs(self.daily_df["drawdown"].min())) * 100.0

        daily_returns = self.daily_df["daily_return"].values
        std_ret = float(np.std(daily_returns))
        sharpe_ratio = float(np.mean(daily_returns) / (std_ret + 1e-8) * np.sqrt(240)) if std_ret > 0 else 0.0

        # 计算胜率与盈亏比
        closed_trades_pnl = []
        # 简单平仓配对
        long_entries = []
        short_entries = []
        for t in trades_list:
            if t.direction == Direction.LONG:
                if t.offset == Offset.OPEN:
                    long_entries.append(t.price)
                else:
                    if short_entries:
                        entry = short_entries.pop(0)
                        closed_trades_pnl.append((entry - t.price) * self.size)
            else:
                if t.offset == Offset.OPEN:
                    short_entries.append(t.price)
                else:
                    if long_entries:
                        entry = long_entries.pop(0)
                        closed_trades_pnl.append((t.price - entry) * self.size)

        win_trades = [p for p in closed_trades_pnl if p > 0]
        loss_trades = [p for p in closed_trades_pnl if p < 0]
        win_rate = len(win_trades) / len(closed_trades_pnl) if closed_trades_pnl else 0.0
        profit_loss_ratio = (np.mean(win_trades) / abs(np.mean(loss_trades))) if win_trades and loss_trades else 0.0

        return {
            "initial_capital": self.capital,
            "final_balance": float(self.daily_df["balance"].iloc[-1]),
            "total_net_pnl": total_pnl,
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "total_trade_count": self.trade_count,
            "closed_trade_count": len(closed_trades_pnl),
            "win_rate_pct": round(win_rate * 100.0, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "total_commission": round(float(self.daily_df["commission"].sum()), 2),
            "total_slippage": round(float(self.daily_df["slippage"].sum()), 2)
        }
