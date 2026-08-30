"""
vnpy_tianji_strategy.py — 天玑 (Tianji) 非预测高胜率趋势动量策略 (vn.py CTA 标准模板版)

核心原理：
1. 采用考夫曼自适应效率比率 (Kaufman Efficiency Ratio, KER) 与唐奇安通道位置 (Donchian Position) 捕捉高确定性物理动量；
2. 严格基于当前 Bar 完结时的数据更新指标并在下一 Bar 开盘/当前 Bar 收盘挂限价单；
3. 动态 ATR 吊灯止盈与保本安全垫保护。
"""

from collections import deque
import numpy as np

from vnpy_data_adapter import BarData
from vnpy_strategy_template import CtaTemplate, Direction, Offset


class VnpyTianjiStrategy(CtaTemplate):
    """vn.py 标准天玑趋势动量策略"""
    author = "Lianghua Tianji Architect"

    # 策略参数
    ker_window: int = 20
    donchian_window: int = 20
    atr_window: int = 14
    initial_stop_atr: float = 1.2
    trail_stop_atr: float = 2.5
    fixed_size: float = 1.0

    # 策略变量
    ker_val: float = 0.0
    donchian_pos: float = 0.0
    atr_val: float = 0.0
    entry_price: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 999999.0
    stop_price: float = 0.0

    parameters = [
        "ker_window",
        "donchian_window",
        "atr_window",
        "initial_stop_atr",
        "trail_stop_atr",
        "fixed_size"
    ]
    variables = [
        "inited",
        "trading",
        "pos",
        "ker_val",
        "donchian_pos",
        "atr_val",
        "entry_price",
        "highest_price",
        "lowest_price",
        "stop_price"
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.closes = deque(maxlen=max(self.ker_window, self.donchian_window) + 20)
        self.highs = deque(maxlen=max(self.ker_window, self.donchian_window) + 20)
        self.lows = deque(maxlen=max(self.ker_window, self.donchian_window) + 20)
        self.true_ranges = deque(maxlen=self.atr_window + 5)
        self.last_close = 0.0

    def on_init(self):
        self.write_log("天玑策略初始化就绪")
        self.inited = True

    def on_start(self):
        self.write_log("天玑策略开始运行")
        self.trading = True

    def on_stop(self):
        self.write_log("天玑策略停止运行")
        self.trading = False

    def on_bar(self, bar: BarData):
        """K 线推送回调 (事件驱动核心)"""
        # 1. 缓存行情窗口
        self.closes.append(bar.close_price)
        self.highs.append(bar.high_price)
        self.lows.append(bar.low_price)

        if self.last_close > 0:
            tr = max(
                bar.high_price - bar.low_price,
                abs(bar.high_price - self.last_close),
                abs(bar.low_price - self.last_close)
            )
            self.true_ranges.append(tr)
        self.last_close = bar.close_price

        # 检查数据预热
        if len(self.closes) < max(self.ker_window, self.donchian_window) + 1:
            return

        # 2. 计算因果指标
        # 2.1 考夫曼自适应效率比率 (Signed KER)
        c_arr = np.array(self.closes)
        net_change = c_arr[-1] - c_arr[-self.ker_window]
        price_diffs = np.abs(np.diff(c_arr[-self.ker_window - 1:]))
        volatility = np.sum(price_diffs) + 1e-8
        er = abs(net_change) / volatility
        self.ker_val = float(er * np.sign(net_change))

        # 2.2 唐奇安通道位置
        h_arr = np.array(self.highs)[-self.donchian_window:]
        l_arr = np.array(self.lows)[-self.donchian_window:]
        don_hi = np.max(h_arr)
        don_lo = np.min(l_arr)
        if don_hi > don_lo:
            self.donchian_pos = float((bar.close_price - don_lo) / (don_hi - don_lo))
        else:
            self.donchian_pos = 0.5

        # 2.3 ATR 计算
        if len(self.true_ranges) >= self.atr_window:
            self.atr_val = float(np.mean(list(self.true_ranges)[-self.atr_window:]))
        else:
            self.atr_val = float(bar.close_price * 0.01)

        # 3. 仓位与出场管理
        if self.pos > 0:
            self.highest_price = max(self.highest_price, bar.high_price)
            # 吊灯移动止损
            dyn_stop = self.highest_price - self.trail_stop_atr * self.atr_val
            self.stop_price = max(self.stop_price, dyn_stop)

            # 触发止损/止盈平仓
            if bar.close_price <= self.stop_price or self.ker_val < -0.2:
                self.sell(bar.close_price, abs(self.pos))
                self.stop_price = 0.0
                return

        elif self.pos < 0:
            self.lowest_price = min(self.lowest_price, bar.low_price)
            # 吊灯移动止损
            dyn_stop = self.lowest_price + self.trail_stop_atr * self.atr_val
            self.stop_price = min(self.stop_price, dyn_stop)

            # 触发止损/止盈平仓
            if bar.close_price >= self.stop_price or self.ker_val > 0.2:
                self.cover(bar.close_price, abs(self.pos))
                self.stop_price = 0.0
                return

        # 4. 入场信号生成 (零未来函数：当前收盘确定信号，发出委托)
        if self.pos == 0:
            # 多头入场条件：考夫曼效率比率 > 0.35 且 唐奇安处于强势区 (>0.75)
            if self.ker_val > 0.35 and self.donchian_pos > 0.75:
                self.buy(bar.close_price, self.fixed_size)
                self.entry_price = bar.close_price
                self.highest_price = bar.high_price
                self.stop_price = bar.close_price - self.initial_stop_atr * self.atr_val

            # 空头入场条件：考夫曼效率比率 < -0.35 且 唐奇安处于弱势区 (<0.25)
            elif self.ker_val < -0.35 and self.donchian_pos < 0.25:
                self.short(bar.close_price, self.fixed_size)
                self.entry_price = bar.close_price
                self.lowest_price = bar.low_price
                self.stop_price = bar.close_price + self.initial_stop_atr * self.atr_val
