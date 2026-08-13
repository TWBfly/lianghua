"""
dual_ma_cross.py — 5日/20日双均线热插拔策略
"""
import pandas as pd

STRATEGY_NAME = "dual_ma_cross"
STRATEGY_DESCRIPTION = "5日与20日均线金叉/死叉热插拔策略"

def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    df 包含 close 列
    返回: 1 (买入), -1 (卖出), 0 (观望)
    """
    close = df['close']
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    
    # 均线金叉买入，死叉卖出
    buy = (ma5 > ma20) & (ma5.shift(1) <= ma20.shift(1))
    sell = (ma5 < ma20) & (ma5.shift(1) >= ma20.shift(1))
    
    signal = pd.Series(0, index=df.index)
    signal[buy] = 1
    signal[sell] = -1
    return signal
