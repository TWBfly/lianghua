"""
vnpy_zscore_strategy.py — 极值 Z-Score 均值回归策略 (vn.py CTA 标准模板版)

核心原理：
1. 计算 20 周期收盘价 Z-Score: (Close - SMA(20)) / Std(20)；
2. 结合极值偏离 (> 2.0 / < -2.0) 触发均值回归操作；
3. 出场在触及均线中轨 (SMA 20) 或触发 ATR 硬止损时平仓。
"""

from collections import deque
import numpy as np

from vnpy_data_adapter import BarData
from vnpy_strategy_template import CtaTemplate


class VnpyZScoreStrategy(CtaTemplate):
    """vn.py 标准 Z-Score 均值回归策略"""
    author = "Lianghua Quant"

    # 参数
    window: int = 20
    entry_zscore: float = 2.0
    sl_atr_mult: float = 1.5
    fixed_size: float = 1.0

    # 变量
    zscore_val: float = 0.0
    sma_val: float = 0.0
    std_val: float = 0.0
    atr_val: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0

    parameters = ["window", "entry_zscore", "sl_atr_mult", "fixed_size"]
    variables = [
        "inited", "trading", "pos", "zscore_val", "sma_val", "atr_val",
        "entry_price", "stop_price"
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.closes = deque(maxlen=self.window + 20)
        self.highs = deque(maxlen=self.window + 20)
        self.lows = deque(maxlen=self.window + 20)
        self.true_ranges = deque(maxlen=14 + 5)
        self.last_close = 0.0

    def on_init(self):
        self.write_log("Z-Score 均值回归策略初始化就绪")
        self.inited = True

    def on_start(self):
        self.write_log("Z-Score 策略开始运行")
        self.trading = True

    def on_stop(self):
        self.write_log("Z-Score 策略停止运行")
        self.trading = False

    def on_bar(self, bar: BarData):
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

        if len(self.closes) < self.window:
            return

        c_arr = np.array(self.closes)[-self.window:]
        self.sma_val = float(np.mean(c_arr))
        self.std_val = float(np.std(c_arr)) + 1e-8
        self.zscore_val = (bar.close_price - self.sma_val) / self.std_val

        if len(self.true_ranges) >= 14:
            self.atr_val = float(np.mean(list(self.true_ranges)[-14:]))
        else:
            self.atr_val = float(bar.close_price * 0.01)

        # 仓位与平仓逻辑
        if self.pos > 0:
            # 触及均线中轨或止损平多
            if bar.close_price >= self.sma_val or bar.close_price <= self.stop_price:
                self.sell(bar.close_price, abs(self.pos))
                self.stop_price = 0.0
                return

        elif self.pos < 0:
            # 触及均线中轨或止损平空
            if bar.close_price <= self.sma_val or bar.close_price >= self.stop_price:
                self.cover(bar.close_price, abs(self.pos))
                self.stop_price = 0.0
                return

        # 开仓逻辑
        if self.pos == 0:
            if self.zscore_val <= -self.entry_zscore:
                self.buy(bar.close_price, self.fixed_size)
                self.entry_price = bar.close_price
                self.stop_price = bar.close_price - self.sl_atr_mult * self.atr_val
            elif self.zscore_val >= self.entry_zscore:
                self.short(bar.close_price, self.fixed_size)
                self.entry_price = bar.close_price
                self.stop_price = bar.close_price + self.sl_atr_mult * self.atr_val
