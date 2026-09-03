"""
futures_trading_day.py — 中国期货市场真实交易日历、时钟对齐与平今仓判定引擎

核心功能：
1. 区分日盘 (09:00-10:15, 10:30-11:30, 13:30-15:00) 与夜盘 (21:00-02:30)；
2. 严格对齐中国期货交易日时钟：
   - 周一至周四夜盘 (21:00 - 02:30) 归属于次日 (T+1) 交易日；
   - 周五夜盘 (21:00 - 02:30) 归属于下周一交易日；
   - 法定节假日前一晚通常无夜盘；
3. 真实“平今仓 (Close Today)”与“平昨仓 (Close Yesterday)”判定：
   - 开仓交易日 == 平仓交易日 -> 判定为平今 (触发 close_today_ratio 高费率)；
   - 开仓交易日 < 平仓交易日 -> 判定为平昨 (执行普通平仓费率)；
   - 彻底废弃 holding_bars <= 16 的粗暴估计。
"""

from __future__ import annotations

import datetime
from typing import Union
import pandas as pd


def get_futures_trading_date(dt_val: Union[datetime.datetime, pd.Timestamp, str]) -> str:
    """
    根据给定的时间戳，计算其在期货交易所结算系统中的真实归属交易日 (YYYY-MM-DD)。
    """
    if isinstance(dt_val, str):
        try:
            dt = datetime.datetime.strptime(dt_val[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.datetime.strptime(dt_val[:10], "%Y-%m-%d")
            except ValueError:
                dt = datetime.datetime.now()
    elif isinstance(dt_val, pd.Timestamp):
        dt = dt_val.to_pydatetime()
    else:
        dt = dt_val

    hour = dt.hour
    minute = dt.minute
    weekday = dt.weekday() # 0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday

    # 夜盘判定：20:00 之后属于夜盘前半段，00:00 - 04:00 属于夜盘后半段
    if hour >= 20:
        # 周一至周四夜盘归属下一自然日
        if weekday < 4:
            target_date = dt.date() + datetime.timedelta(days=1)
        elif weekday == 4: # 周五夜盘归属下周一
            target_date = dt.date() + datetime.timedelta(days=3)
        else: # 周六/周日异常夜盘按最近工作日处理
            target_date = dt.date() + datetime.timedelta(days=(7 - weekday))
    elif hour < 5:
        # 凌晨 00:00 - 05:00 跨日夜盘，所属交易日即为当天(工作日)或下周一
        if weekday < 5:
            target_date = dt.date()
        elif weekday == 5: # 周六凌晨属于周五夜盘，归属下周一
            target_date = dt.date() + datetime.timedelta(days=2)
        else:
            target_date = dt.date() + datetime.timedelta(days=1)
    else:
        # 日盘 (08:30 - 16:00) 交易日即为当前日期
        target_date = dt.date()

    return target_date.strftime("%Y-%m-%d")


def is_close_today(
    open_time: Union[datetime.datetime, pd.Timestamp, str],
    close_time: Union[datetime.datetime, pd.Timestamp, str]
) -> bool:
    """
    精确判断是否属于“平今仓”：
    如果开仓归属的期货交易日与平仓归属的期货交易日完全相同，则为平今仓。
    """
    open_trade_date = get_futures_trading_date(open_time)
    close_trade_date = get_futures_trading_date(close_time)
    return open_trade_date == close_trade_date
